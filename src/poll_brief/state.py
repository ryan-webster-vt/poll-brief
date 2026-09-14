"""S3 state and compare-and-swap leases. No AWS calls at import time."""

import json
import logging
import time
import uuid
from contextlib import contextmanager

LOG = logging.getLogger(__name__)
STATE_KEY = "poll-brief/state.json"
LOCK_KEY = "poll-brief/lease.json"


def empty_state():
    return {"version": 1, "initialized": False, "ids": [], "last_delivery": None}


def validate_state(data):
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or type(data.get("initialized")) is not bool
        or not isinstance(data.get("ids"), list)
        or any(not isinstance(value, str) for value in data["ids"])
        or not (data.get("last_delivery") is None or isinstance(data["last_delivery"], str))
    ):
        raise ValueError("Invalid digest state; restore a known good S3 version")
    return data


def error_code(error):
    return getattr(error, "response", {}).get("Error", {}).get("Code")


class AlreadyRunning(RuntimeError):
    pass


class S3State:
    def __init__(self, client, bucket, clock=time.time):
        self.client, self.bucket, self.clock = client, bucket, clock
        self.state_etag = None

    def _read(self, key):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            if error_code(error) == "NoSuchKey":
                return None, None
            raise
        with response["Body"] as body:
            return json.load(body), response["ETag"]

    def load(self):
        data, self.state_etag = self._read(STATE_KEY)
        return empty_state() if self.state_etag is None else validate_state(data)

    def save(self, ids, delivery):
        data = {
            "version": 1,
            "initialized": True,
            "ids": sorted(ids),
            "last_delivery": delivery,
            "saved_at": self.clock(),
        }
        condition = {"IfMatch": self.state_etag} if self.state_etag else {"IfNoneMatch": "*"}
        self.client.put_object(
            Bucket=self.bucket,
            Key=STATE_KEY,
            Body=json.dumps(data).encode(),
            ContentType="application/json",
            **condition,
        )

    @contextmanager
    def lease(self):
        existing, etag = self._read(LOCK_KEY)
        if existing and existing["expires"] > self.clock():
            raise AlreadyRunning("A digest invocation holds the lease")
        owner = str(uuid.uuid4())
        # Ten minutes comfortably exceeds the deployed Lambda's 180-second timeout.
        expires = self.clock() + 600
        body = json.dumps({"owner": owner, "expires": expires}).encode()
        condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
        try:
            result = self.client.put_object(
                Bucket=self.bucket, Key=LOCK_KEY, Body=body, **condition
            )
        except Exception as error:
            if error_code(error) in ("PreconditionFailed", "ConditionalRequestConflict"):
                raise AlreadyRunning("A concurrent invocation won the lease") from None
            raise
        lease_etag = result["ETag"]
        try:
            yield
        finally:
            # Expire our own lease using its ETag; never delete somebody else's lock.
            try:
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=LOCK_KEY,
                    Body=json.dumps({"owner": owner, "expires": 0}).encode(),
                    IfMatch=lease_etag,
                )
            except Exception:
                LOG.warning("Lease release failed; it will expire automatically")
