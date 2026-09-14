"""Normalization and stable identities, independent of storage and delivery."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Poll:
    identity: str
    pollster: str | None
    subject: str | None
    poll_type: str | None
    seat_name: str | None
    start_date: str | None
    end_date: str | None
    sample_size: str | None
    population: str | None
    answers: tuple[tuple[str, Decimal | None], ...]
    url: str | None
    published: datetime | None

    @property
    def group(self):
        return (
            " / ".join(v for v in (self.subject, self.seat_name, self.poll_type) if v)
            or "Other polls"
        )

    @property
    def margin(self):
        # Only verified election types support a candidate/party lead.
        # Approval and favorability are response balances, not candidate margins.
        if self.poll_type == "generic-ballot":
            results = dict(self.answers)
            if results.get("Dem") is not None and results.get("Rep") is not None:
                diff = results["Dem"] - results["Rep"]
                return (
                    "Tie (0 points)"
                    if not diff
                    else f"{'Dem' if diff > 0 else 'Rep'} +{abs(diff):g} points"
                )
        if self.poll_type in {"governor", "us-senator", "us-representative"}:
            # Be conservative: two named choices with percentages, no residual bucket.
            residuals = {"other", "undecided", "unsure", "don't know", "someone else"}
            if len(self.answers) == 2 and all(
                pct is not None and name.casefold() not in residuals for name, pct in self.answers
            ):
                first, second = sorted(self.answers, key=lambda answer: (-answer[1], answer[0]))
                diff = first[1] - second[1]
                return "Tie (0 points)" if not diff else f"{first[0]} +{diff:g} points"
        return None


def text(value):
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list, bool)):
        raise ValueError("Unexpected structured poll field")
    return str(value)


def normalize(raw):
    if not raw or not any(raw.get(k) for k in ("id", "pollster", "subject", "answers")):
        raise ValueError("Unrecognizable poll record")
    answers = []
    for item in raw.get("answers") or []:
        if not isinstance(item, dict):
            raise ValueError("Invalid answer record")
        choice = text(item.get("choice"))
        if not choice:
            raise ValueError("Answer has no choice")
        pct = None
        if item.get("pct") is not None:
            try:
                pct = Decimal(str(item["pct"]))
            except InvalidOperation:
                raise ValueError("Invalid response percentage") from None
            if not pct.is_finite() or not 0 <= pct <= 100:
                raise ValueError("Response percentage outside 0-100")
        answers.append((choice, pct))
    published = None
    if raw.get("created_at"):
        value = str(raw["created_at"])
        published = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
    identity = text(raw.get("id"))
    fields = (
        "pollster",
        "subject",
        "poll_type",
        "seat_name",
        "start_date",
        "end_date",
        "sample_size",
        "population",
        "url",
    )
    normalized = {key: text(raw.get(key)) for key in fields}
    if not identity:
        canonical = dict(
            normalized,
            answers=sorted(
                (name, str(pct.normalize()) if pct is not None else None) for name, pct in answers
            ),
        )
        serialized = json.dumps(
            canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        identity = "sha256:" + hashlib.sha256(serialized.encode()).hexdigest()
    return Poll(identity=identity, answers=tuple(answers), published=published, **normalized)


def select_new(raw_polls, state, days=7, all_on_first_run=False, now=None):
    if days < 1:
        raise ValueError("First-run days must be positive")
    now = now or datetime.now(timezone.utc)
    # created_at is usually date-only; include today and the previous six UTC dates.
    cutoff = datetime.combine(now.date() - timedelta(days=days - 1), time.min, timezone.utc)
    accounted = set(state["ids"])
    new, fetched = [], set()
    for raw in raw_polls:
        poll = normalize(raw)
        if poll.identity in fetched:
            continue
        fetched.add(poll.identity)
        if poll.identity in accounted:
            continue
        if (
            state["initialized"]
            or all_on_first_run
            or poll.published is None
            or poll.published >= cutoff
        ):
            new.append(poll)
    return new, accounted | fetched
