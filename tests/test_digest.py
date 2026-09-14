import copy
import io
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import boto3
from botocore.exceptions import ClientError
from botocore.stub import ANY, Stubber

from poll_brief.api import ApiError, decode_collection, fetch_polls
from poll_brief.app import handler, main, run
from poll_brief.email import send_digest
from poll_brief.polls import normalize, select_new
from poll_brief.render import render
from poll_brief.state import LOCK_KEY, STATE_KEY, AlreadyRunning, S3State, empty_state

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic-polls.json"
ROWS = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


class Response(io.BytesIO):
    def __init__(self, payload, headers=None):
        super().__init__(json.dumps(payload).encode())
        self.headers = headers or {}
        self.status = 200


class ApiTests(unittest.TestCase):
    def test_live_list_and_documented_envelope_are_complete_single_requests(self):
        for payload in (ROWS, {"polls": ROWS}, []):
            opener = Mock(return_value=Response(payload))
            self.assertEqual(fetch_polls(opener=opener), decode_collection(payload))
            self.assertEqual(opener.call_count, 1)
            request = opener.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.votehub.com/polls")
            self.assertFalse(request.has_header("Authorization"))
            self.assertEqual(opener.call_args.kwargs["timeout"], 15)

    def test_unverified_pagination_aborts_instead_of_sending_partial_data(self):
        for key in ("next", "pagination", "total", "cursor", "next_page"):
            with self.subTest(key=key), self.assertRaises(ApiError):
                fetch_polls(opener=Mock(return_value=Response({"polls": ROWS, key: "page2"})))
        with self.assertRaises(ApiError):
            fetch_polls(
                opener=Mock(
                    return_value=Response(
                        ROWS, {"Link": '<https://api.votehub.com/polls?page=2>; rel="next"'}
                    )
                )
            )

    def test_pagination_failure_cannot_email_or_advance_state(self):
        state, mail = MemoryState(), Mock()

        def fetch():
            return fetch_polls(opener=Mock(return_value=Response({"polls": ROWS, "next": "page2"})))

        with self.assertRaises(ApiError):
            run(fetch, state, mail)
        mail.assert_not_called()
        self.assertFalse(state.saved)

    def test_429_respects_retry_after_and_recovers(self):
        opener = Mock(
            side_effect=[
                HTTPError("url", 429, "limited", {"Retry-After": "3"}, None),
                Response(ROWS),
            ]
        )
        sleep = Mock()
        self.assertEqual(fetch_polls(opener=opener, sleep=sleep), ROWS)
        sleep.assert_called_once_with(3)

    def test_long_rate_limit_does_not_retry_early(self):
        sleep = Mock()
        opener = Mock(side_effect=HTTPError("url", 429, "limited", {"Retry-After": "120"}, None))
        with self.assertRaises(ApiError):
            fetch_polls(opener=opener, sleep=sleep)
        sleep.assert_not_called()
        self.assertEqual(opener.call_count, 1)

    def test_transient_failure_has_bounded_retries(self):
        for error in (URLError("offline"), TimeoutError(), HTTPError("url", 503, "down", {}, None)):
            opener, sleep = Mock(side_effect=error), Mock()
            with self.assertRaises(ApiError):
                fetch_polls(opener=opener, sleep=sleep)
            self.assertEqual(opener.call_count, 4)
            self.assertEqual(sleep.call_count, 3)

    def test_permanent_failures_do_not_retry(self):
        for code in (301, 401, 403, 404):
            opener = Mock(side_effect=HTTPError("url", code, "error", {}, None))
            with self.assertRaises(ApiError):
                fetch_polls(opener=opener)
            self.assertEqual(opener.call_count, 1)

    def test_bad_json_and_schema_do_not_become_empty_results(self):
        response = Response([])
        response.seek(0)
        response.write(b"bad json")
        response.seek(0)
        for payload in ({"error": "down"}, {"polls": None}, ["bad"]):
            with self.assertRaises(ApiError):
                fetch_polls(opener=Mock(return_value=Response(payload)))
        with self.assertRaises(ApiError):
            fetch_polls(opener=Mock(return_value=response))

    def test_filters_and_insecure_urls_are_rejected(self):
        for url in (
            "http://api.votehub.com/polls",
            "https://api.votehub.com/polls?from_date=2026-09-12",
            "https://token@api.votehub.com/polls",
        ):
            with self.assertRaises(ValueError):
                fetch_polls(url)


class PollTests(unittest.TestCase):
    def test_deduplicates_within_collection_and_against_state(self):
        initial = empty_state()
        initial.update(initialized=True, ids=[ROWS[0]["id"]])
        selected, ids = select_new(ROWS + ROWS, initial)
        self.assertEqual([p.identity for p in selected], [ROWS[1]["id"]])
        self.assertEqual(len(ids), 2)

    def test_late_addition_includes_old_publication_and_fieldwork_after_initialization(self):
        row = dict(ROWS[0], created_at="2020-01-01", end_date="2019-12-30")
        state = dict(empty_state(), initialized=True)
        selected, _ = select_new([row], state, now=NOW)
        self.assertEqual(len(selected), 1)

    def test_first_run_window_baselines_old_ids_and_includes_undated_polls(self):
        old = dict(ROWS[0], id="old", created_at="2026-09-06")
        boundary = dict(ROWS[0], id="boundary", created_at="2026-09-07")
        selected, ids = select_new([old, boundary, ROWS[1]], empty_state(), now=NOW)
        self.assertEqual({p.identity for p in selected}, {"boundary", ROWS[1]["id"]})
        self.assertIn("old", ids)
        selected, _ = select_new(
            [old, boundary, ROWS[1]], dict(empty_state(), initialized=True, ids=list(ids))
        )
        self.assertFalse(selected)

    def test_first_run_all_is_configurable(self):
        old = dict(ROWS[0], created_at="2020-01-01")
        selected, _ = select_new([old], empty_state(), now=NOW, all_on_first_run=True)
        self.assertEqual(len(selected), 1)

    def test_content_fingerprint_is_stable_under_answer_order_and_numeric_format(self):
        row = dict(ROWS[0], id=None)
        changed = copy.deepcopy(row)
        changed["answers"].reverse()
        changed["answers"][0]["pct"] = "44.1000"
        changed["created_at"] = "2026-01-01"
        self.assertEqual(normalize(row).identity, normalize(changed).identity)
        self.assertTrue(normalize(row).identity.startswith("sha256:"))

    def test_candidate_margin_uses_verified_race_types_and_excludes_residuals(self):
        row = dict(
            ROWS[0],
            poll_type="governor",
            answers=[
                {"choice": "Candidate A", "pct": 44.1},
                {"choice": "Candidate B", "pct": 47.2},
            ],
        )
        self.assertEqual(normalize(row).margin, "Candidate B +3.1 points")
        row["answers"][1]["choice"] = "Undecided"
        self.assertIsNone(normalize(row).margin)

    def test_malformed_records_fail_instead_of_disappearing(self):
        for row in (
            {},
            dict(ROWS[0], created_at="bad"),
            dict(ROWS[0], answers=[{"choice": "X", "pct": "NaN"}]),
        ):
            with self.assertRaises(ValueError):
                normalize(row)

    def test_decimal_margin_and_approval_has_no_candidate_margin(self):
        self.assertEqual(normalize(ROWS[0]).margin, "Dem +3.1 points")
        self.assertIsNone(normalize(ROWS[1]).margin)
        tied = dict(ROWS[0], answers=[{"choice": "Dem", "pct": 40}, {"choice": "Rep", "pct": 40}])
        self.assertEqual(normalize(tied).margin, "Tie (0 points)")


class RenderTests(unittest.TestCase):
    def test_html_escaping_and_unsafe_source_links(self):
        row = dict(ROWS[1], subject='<script>alert("x")</script>', url="javascript:alert(1)")
        _, plain, html = render([normalize(row)])
        self.assertIn("Example <Survey> & Research", plain)
        self.assertIn("Example &lt;Survey&gt; &amp; Research", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("Sample size", html)
        self.assertIn("Aug 1–5", html)

    def test_source_url_attribute_is_escaped(self):
        row = dict(ROWS[0], url='https://example.com/?q="onclick="bad&x=1')
        html = render([normalize(row)])[2]
        self.assertIn("&quot;", html)
        self.assertIn("&amp;", html)
        self.assertNotIn('q="onclick=', html)

    def test_empty_digest_and_attribution(self):
        subject, plain, html = render([])
        self.assertIn("No new polls", subject)
        self.assertIn("successful VoteHub fetch", plain)
        self.assertIn("CC BY 4.0", html)


class MemoryState:
    def __init__(self, previous=None):
        self.previous = previous or empty_state()
        self.saved, self.locked = False, False

    @contextmanager
    def lease(self):
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    def load(self):
        return self.previous

    def save(self, ids, delivery):
        self.saved = True
        self.previous = dict(
            empty_state(), initialized=True, ids=sorted(ids), last_delivery=delivery
        )


class FlowTests(unittest.TestCase):
    def test_email_failure_does_not_advance_state(self):
        state = MemoryState()
        for mail in (Mock(side_effect=RuntimeError("SES failure")), Mock(return_value=None)):
            with self.assertRaises(RuntimeError):
                run(lambda: ROWS, state, mail, all_on_first_run=True)
            self.assertFalse(state.saved)
            self.assertFalse(state.locked)

    def test_api_failure_does_not_send_or_save(self):
        state, mail = MemoryState(), Mock()
        with self.assertRaises(ApiError):
            run(Mock(side_effect=ApiError("offline")), state, mail)
        mail.assert_not_called()
        self.assertFalse(state.saved)

    def test_empty_fetch_sends_once_and_initializes_state(self):
        state, mail = MemoryState(), Mock(return_value="message")
        result = run(lambda: [], state, mail, delivery="today")
        self.assertEqual(result["selected"], 0)
        self.assertTrue(state.previous["initialized"])
        self.assertIn("No new polls", mail.call_args.args[0])
        fetch = Mock()
        self.assertEqual(
            run(fetch, state, mail, delivery="today"), {"skipped": "already-delivered"}
        )
        fetch.assert_not_called()
        self.assertEqual(mail.call_count, 1)

    def test_save_only_after_acceptance_and_save_failure_propagates(self):
        state = MemoryState()

        def deliver(*args):
            self.assertFalse(state.saved)
            self.assertTrue(state.locked)
            return "message"

        state.save = Mock(side_effect=RuntimeError("S3 down"))
        with self.assertRaises(RuntimeError):
            run(lambda: ROWS, state, deliver, all_on_first_run=True)
        state.save.assert_called_once()
        self.assertFalse(state.locked)

    def test_low_remaining_time_prevents_send_and_save(self):
        state, mail = MemoryState(), Mock()
        with self.assertRaises(RuntimeError):
            run(lambda: ROWS, state, mail, before_send=Mock(side_effect=RuntimeError("timeout")))
        mail.assert_not_called()
        self.assertFalse(state.saved)

    def test_dry_run_reads_local_state_without_mutation_or_aws_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.html"
            state_path = Path(directory) / "state.json"
            original = json.dumps(empty_state())
            state_path.write_text(original)
            with (
                patch(
                    "sys.argv",
                    [
                        "preview",
                        "--fixture",
                        str(FIXTURE),
                        "--all",
                        "--state",
                        str(state_path),
                        "--output",
                        str(output),
                    ],
                ),
                patch("boto3.client") as aws,
            ):
                main()
            aws.assert_not_called()
            self.assertEqual(state_path.read_text(), original)
            self.assertIn("Dem +3.1", output.read_text(encoding="utf-8"))
            self.assertTrue(output.with_suffix(".txt").exists())


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.revision = 0

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        body, etag = self.objects[Key]
        return {"Body": io.BytesIO(body), "ETag": etag}

    def put_object(self, Bucket, Key, Body, IfMatch=None, IfNoneMatch=None, **kwargs):
        old = self.objects.get(Key)
        if (IfNoneMatch == "*" and old) or (IfMatch is not None and (not old or IfMatch != old[1])):
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.revision += 1
        etag = f'"revision-{self.revision}"'
        self.objects[Key] = Body, etag
        return {"ETag": etag}


class StateTests(unittest.TestCase):
    def test_first_run_and_saved_ids_roundtrip(self):
        state = S3State(FakeS3(), "test", clock=lambda: 100)
        self.assertFalse(state.load()["initialized"])
        state.save({"one"}, "today")
        self.assertEqual(state.load()["ids"], ["one"])
        state.save({"one", "two"}, "tomorrow")
        self.assertEqual(state.load()["last_delivery"], "tomorrow")

    def test_existing_lease_blocks_concurrent_run_and_releases_for_next(self):
        s3 = FakeS3()
        first, second = (
            S3State(s3, "test", clock=lambda: 100),
            S3State(s3, "test", clock=lambda: 100),
        )
        with first.lease():
            with self.assertRaises(AlreadyRunning), second.lease():
                self.fail("Acquired held lease")
        with second.lease():
            pass

    def test_expired_lease_can_be_recovered(self):
        s3 = FakeS3()
        s3.put_object(Bucket="test", Key=LOCK_KEY, Body=b'{"owner":"dead","expires":99}')
        with S3State(s3, "test", clock=lambda: 100).lease():
            pass

    def test_old_owner_cannot_release_a_replacement_lease(self):
        s3 = FakeS3()
        with S3State(s3, "test", clock=lambda: 100).lease():
            replacement = b'{"owner":"replacement","expires":900}'
            s3.put_object(Bucket="test", Key=LOCK_KEY, Body=replacement)
        self.assertEqual(s3.objects[LOCK_KEY][0], replacement)

    def test_failed_lease_race_is_an_overlap(self):
        s3 = FakeS3()
        s3.put_object = Mock(
            side_effect=ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        )
        with self.assertRaises(AlreadyRunning), S3State(s3, "test").lease():
            self.fail("Acquired contended lease")

    def test_corrupt_or_inaccessible_state_is_never_a_first_run(self):
        for body in (b"{}", b"bad json", b"null"):
            s3 = FakeS3()
            s3.put_object(Bucket="test", Key=STATE_KEY, Body=body)
            with self.assertRaises(ValueError):
                S3State(s3, "test").load()
        s3.get_object = Mock(
            side_effect=ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
        )
        with self.assertRaises(ClientError):
            S3State(s3, "test").load()

    def test_conditional_state_write_prevents_overwrite(self):
        s3 = FakeS3()
        state = S3State(s3, "test")
        state.load()
        s3.put_object(Bucket="test", Key=STATE_KEY, Body=json.dumps(empty_state()).encode())
        with self.assertRaises(ClientError):
            state.save({"one"}, "today")

    def test_boto3_accepts_conditional_put_parameters(self):
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        with Stubber(client) as stub:
            stub.add_client_error(
                "get_object",
                service_error_code="NoSuchKey",
                http_status_code=404,
                expected_params={"Bucket": "test", "Key": LOCK_KEY},
            )
            stub.add_response(
                "put_object",
                {"ETag": '"lease"'},
                {"Bucket": "test", "Key": LOCK_KEY, "Body": ANY, "IfNoneMatch": "*"},
            )
            stub.add_response(
                "put_object",
                {"ETag": '"released"'},
                {"Bucket": "test", "Key": LOCK_KEY, "Body": ANY, "IfMatch": '"lease"'},
            )
            with S3State(client, "test").lease():
                pass
            stub.assert_no_pending_responses()


class HandlerTests(unittest.TestCase):
    def test_lambda_wires_secure_token_s3_and_ses_without_logging_token(self):
        s3, ses, ssm = FakeS3(), Mock(), Mock()
        ses.send_email.return_value = {"MessageId": "accepted"}
        ssm.get_parameter.return_value = {"Parameter": {"Value": "synthetic-secret"}}
        clients = {"s3": s3, "ses": ses, "ssm": ssm}
        context = Mock()
        context.get_remaining_time_in_millis.return_value = 180000
        env = {
            "STATE_BUCKET": "test",
            "SES_SENDER": "sender@example.com",
            "SES_RECIPIENT": "recipient@example.com",
            "API_TOKEN_PARAMETER": "/test/token",
            "FIRST_RUN_ALL": "true",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("boto3.client", side_effect=lambda name, **kw: clients[name]),
            patch("poll_brief.app.fetch_polls", return_value=ROWS) as fetch,
            self.assertLogs("poll_brief", level="INFO") as logs,
        ):
            result = handler({"scheduled_time": "today"}, context)
        self.assertEqual(result["selected"], 2)
        fetch.assert_called_once_with("https://api.votehub.com/polls", "synthetic-secret")
        ssm.get_parameter.assert_called_once_with(Name="/test/token", WithDecryption=True)
        self.assertEqual(json.loads(s3.objects[STATE_KEY][0])["last_delivery"], "today")
        self.assertNotIn("synthetic-secret", " ".join(logs.output))
        ses.send_email.assert_called_once()

    def test_lambda_overlap_skips_email(self):
        s3, ses = FakeS3(), Mock()
        s3.put_object(Bucket="test", Key=LOCK_KEY, Body=b'{"owner":"active","expires":9999999999}')
        with (
            patch.dict(
                "os.environ",
                {
                    "STATE_BUCKET": "test",
                    "SES_SENDER": "s@example.com",
                    "SES_RECIPIENT": "r@example.com",
                },
                clear=True,
            ),
            patch("boto3.client", side_effect=lambda name, **kw: s3 if name == "s3" else ses),
            patch("poll_brief.app.fetch_polls") as fetch,
        ):
            self.assertEqual(handler({}, Mock()), {"skipped": "overlap"})
        fetch.assert_not_called()
        ses.send_email.assert_not_called()


class EmailTests(unittest.TestCase):
    def test_ses_receives_one_recipient_and_both_bodies(self):
        client = boto3.client(
            "ses",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        expected = {
            "Source": "sender@example.com",
            "Destination": {"ToAddresses": ["recipient@example.com"]},
            "Message": {
                "Subject": {"Data": "subject", "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": "plain", "Charset": "UTF-8"},
                    "Html": {"Data": "html", "Charset": "UTF-8"},
                },
            },
        }
        with Stubber(client) as stub:
            stub.add_response("send_email", {"MessageId": "accepted"}, expected)
            self.assertEqual(
                send_digest(
                    client,
                    "sender@example.com",
                    "recipient@example.com",
                    "subject",
                    "plain",
                    "html",
                ),
                "accepted",
            )
            stub.assert_no_pending_responses()


if __name__ == "__main__":
    unittest.main()
