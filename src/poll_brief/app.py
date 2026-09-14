"""Lambda orchestration and read-only local preview."""

import argparse
import json
import logging
import os
from pathlib import Path

from .api import decode_collection, fetch_polls
from .email import send_digest
from .polls import select_new
from .render import render
from .state import AlreadyRunning, S3State, empty_state, validate_state

LOG = logging.getLogger(__name__)


def run(
    fetch, state, deliver, delivery=None, days=7, all_on_first_run=False, before_send=lambda: None
):
    with state.lease():
        previous = state.load()
        if delivery and previous["last_delivery"] == delivery:
            return {"skipped": "already-delivered"}
        LOG.info("Fetching VoteHub collection")
        polls = fetch()
        selected, accounted = select_new(polls, previous, days, all_on_first_run)
        subject, plain, html = render(selected)
        LOG.info("Fetch complete: fetched=%d selected=%d", len(polls), len(selected))
        before_send()
        message_id = deliver(subject, plain, html)
        if not message_id:
            raise RuntimeError("Email was not accepted")
        LOG.info("SES accepted digest; saving state")
        state.save(accounted, delivery)
        LOG.info("Digest completed: selected=%d", len(selected))
        return {"selected": len(selected), "fetched": len(polls)}


def handler(event, context):
    import boto3
    from botocore.config import Config

    logging.getLogger().setLevel(logging.INFO)
    aws_config = Config(
        connect_timeout=3, read_timeout=5, retries={"mode": "standard", "total_max_attempts": 3}
    )
    # SES SendEmail has no idempotency key. Avoid automatic SDK resend on ambiguous errors.
    ses_config = Config(connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 1})
    sender, recipient = os.environ["SES_SENDER"], os.environ["SES_RECIPIENT"]
    if not sender or not recipient:
        raise ValueError("Sender and recipient must be configured")
    url = os.environ.get("VOTEHUB_API_URL", "https://api.votehub.com/polls")
    parameter = os.environ.get("API_TOKEN_PARAMETER")
    token = None
    if parameter:
        token = boto3.client("ssm", config=aws_config).get_parameter(
            Name=parameter, WithDecryption=True
        )["Parameter"]["Value"]
    state = S3State(boto3.client("s3", config=aws_config), os.environ["STATE_BUCKET"])
    ses = boto3.client("ses", config=ses_config)

    def check_time():
        if context.get_remaining_time_in_millis() < 30000:
            raise RuntimeError("Insufficient Lambda time to send and save state")

    try:
        return run(
            lambda: fetch_polls(url, token),
            state,
            lambda *content: send_digest(ses, sender, recipient, *content),
            delivery=event.get("scheduled_time"),
            days=int(os.environ.get("FIRST_RUN_DAYS", "7")),
            all_on_first_run=os.environ.get("FIRST_RUN_ALL", "false").lower() == "true",
            before_send=check_time,
        )
    except AlreadyRunning:
        LOG.info("Skipped overlapping invocation")
        return {"skipped": "overlap"}
    except Exception as error:
        LOG.error(
            "Digest failed: %s; state was not advanced unless its write succeeded",
            type(error).__name__,
        )
        raise RuntimeError("Digest failed; inspect CloudWatch logs") from None


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and render a preview; never send email or access AWS state"
    )
    parser.add_argument("--fixture", type=Path, help="Use synthetic JSON instead of the live API")
    parser.add_argument("--state", type=Path, help="Optional read-only local state JSON")
    parser.add_argument("--output", type=Path, default=Path("preview.html"))
    parser.add_argument(
        "--api-url", default=os.environ.get("VOTEHUB_API_URL", "https://api.votehub.com/polls")
    )
    parser.add_argument("--first-run-days", type=int, default=7)
    parser.add_argument(
        "--all", action="store_true", help="Include the entire collection on an initial preview"
    )
    args = parser.parse_args()
    polls = (
        decode_collection(json.loads(args.fixture.read_text(encoding="utf-8-sig")))
        if args.fixture
        else fetch_polls(args.api_url)
    )
    state = (
        validate_state(json.loads(args.state.read_text(encoding="utf-8-sig")))
        if args.state
        else empty_state()
    )
    selected, _ = select_new(polls, state, args.first_run_days, args.all)
    subject, plain, html = render(selected)
    args.output.write_text(html, encoding="utf-8")
    args.output.with_suffix(".txt").write_text(plain, encoding="utf-8")
    print(f"{subject}; preview written to {args.output} and {args.output.with_suffix('.txt')}")


if __name__ == "__main__":
    main()
