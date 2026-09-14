"""Verified VoteHub adapter: a single full collection, without date filters."""

import json
import logging
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

LOG = logging.getLogger(__name__)


class ApiError(RuntimeError):
    """Fetching failed; callers must not treat this as an empty collection."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward optional credentials to a different endpoint.


def decode_collection(payload):
    # Live API: list. Documentation: {"polls": [...]}. No pagination is documented.
    if isinstance(payload, dict):
        if set(payload) != {"polls"}:
            raise ApiError("Unexpected envelope/pagination; API adapter needs review")
        payload = payload["polls"]
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ApiError("Unexpected VoteHub collection schema")
    return payload


def retry_delay(value, attempt):
    if value:
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = None
        if delay is not None:
            if delay > 30:
                raise ApiError("Rate-limit delay exceeds retry budget; try a later run")
            return max(0, delay)
    return min(8, 2**attempt + random.random())


def fetch_polls(
    url="https://api.votehub.com/polls",
    token=None,
    timeout=15,
    attempts=4,
    opener=None,
    sleep=time.sleep,
):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("API URL must be HTTPS without embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("API URL must not contain filters, credentials, or fragments")
    if not 1 <= attempts <= 4 or not 0 < timeout <= 15:
        raise ValueError("Use 1-4 attempts and a timeout of 0-15 seconds")
    opener = opener or build_opener(NoRedirect()).open
    headers = {"Accept": "application/json", "User-Agent": "poll-brief/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    for attempt in range(attempts):
        try:
            with opener(request, timeout=timeout) as response:
                if response.status != 200:
                    raise ApiError("Unexpected API success status")
                if response.headers.get("Link"):
                    raise ApiError("Unexpected pagination Link header; refusing partial digest")
                try:
                    return decode_collection(json.load(response))
                except (ValueError, UnicodeError):
                    raise ApiError("Invalid API JSON") from None
        except HTTPError as error:
            code, retry_after = error.code, error.headers.get("Retry-After")
            error.close()
            if code not in (429, 500, 502, 503, 504):
                raise ApiError(f"VoteHub HTTP {code}") from None
        except (URLError, TimeoutError, OSError, IncompleteRead):
            code, retry_after = "network", None
        if attempt == attempts - 1:
            raise ApiError("VoteHub request failed after bounded retries") from None
        delay = retry_delay(retry_after, attempt)
        LOG.warning(
            "Retrying VoteHub request: status=%s attempt=%d delay=%.1fs", code, attempt + 1, delay
        )
        sleep(delay)
    raise AssertionError("Unreachable")
