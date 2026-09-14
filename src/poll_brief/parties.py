"""Bundled candidate-party mapping for newsletter presentation only.

VoteHub does not provide party per candidate. No party is inferred from names.
The bundled JSON is a static, partial third-party roster, not official verification.
"""

import json
from importlib.resources import files
from urllib.parse import urlsplit

from .presentation import race_heading

ELECTION_TYPES = {"governor", "us-senator", "us-representative"}
PARTIES = {"D", "R", "I", "O"}


def _key(year, poll_type, race, name):
    return (
        str(year).strip(),
        poll_type.strip().casefold(),
        race.strip().casefold(),
        " ".join(name.split()).casefold(),
    )


class CandidateParties:
    def __init__(self, document):
        if (
            not isinstance(document, dict)
            or document.get("version") != 1
            or not isinstance(document.get("candidates"), list)
        ):
            raise ValueError("Invalid candidate-party registry")
        self.entries = {}
        for row in document["candidates"]:
            if not isinstance(row, dict) or set(row) != {
                "year",
                "poll_type",
                "race",
                "name",
                "party",
                "source",
            }:
                raise ValueError("Invalid candidate-party entry")
            year, office, race, name, party, source = (
                row[key] for key in ("year", "poll_type", "race", "name", "party", "source")
            )
            if not all(
                isinstance(value, str) and value.strip()
                for value in (year, office, race, name, party, source)
            ):
                raise ValueError("Candidate-party fields must be nonempty text")
            parsed = urlsplit(source)
            if (
                len(year) != 4
                or not year.isdigit()
                or office not in ELECTION_TYPES
                or party not in PARTIES
                or parsed.scheme != "https"
                or not parsed.netloc
            ):
                raise ValueError("Invalid candidate-party year, office, party, or source")
            key = _key(year, office, race, name)
            if key in self.entries:
                raise ValueError("Duplicate candidate-party entry")
            self.entries[key] = (party, source)

    @classmethod
    def bundled(cls):
        document = json.loads(
            files("poll_brief").joinpath("candidate_parties.json").read_text(encoding="utf-8-sig")
        )
        # Accept the compact top-level list used by the maintained registry while
        # retaining strict validation for callers constructing a document.
        if isinstance(document, list):
            document = [
                dict(row, party="O" if row.get("party") == "OTH" else row.get("party"))
                for row in document
            ]
            document = {"version": 1, "candidates": document}
        return cls(document)

    def lookup(self, poll, name):
        if poll.poll_type == "generic-ballot":
            return ({"dem": "D", "rep": "R"}.get(name.strip().casefold()), None)
        if poll.poll_type not in ELECTION_TYPES:
            return (None, None)
        race, year = race_heading(poll)
        if not year:
            return (None, None)
        return self.entries.get(_key(year, poll.poll_type, race, name), (None, None))

    def for_answer(self, poll, name):
        return self.lookup(poll, name)[0]
