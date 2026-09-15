import unittest
from html.parser import HTMLParser

from poll_brief.parties import CandidateParties
from poll_brief.polls import normalize
from poll_brief.render import render

SOURCE = "https://example.org/official-candidate-record"


def row(name, party, race="Florida · U.S. Senate", office="us-senator", year="2026"):
    return {
        "year": year,
        "poll_type": office,
        "race": race,
        "name": name,
        "party": party,
        "source": SOURCE,
    }


def sample(**changes):
    data = {
        "id": "synthetic",
        "subject": "2026 Florida",
        "poll_type": "us-senator",
        "pollster": "Example Research",
        "sample_size": 733,
        "population": "lv",
        "answers": [
            {"choice": "Ashley Moody", "pct": 50.1},
            {"choice": "Angie Nixon", "pct": 42.7},
        ],
    }
    data.update(changes)
    return normalize(data)


class PartyPresentationTests(unittest.TestCase):
    def setUp(self):
        self.parties = CandidateParties(
            {"version": 1, "candidates": [row("Ashley Moody", "R"), row("Angie Nixon", "D")]}
        )

    def test_bundled_registry_has_example_races(self):
        known = CandidateParties.bundled()
        self.assertEqual(known.for_answer(sample(), "Ashley Moody"), "R")
        self.assertEqual(known.for_answer(sample(), "Angie Nixon"), "D")
        house = normalize(
            {
                "id": "house",
                "subject": "2026 CA-40",
                "seat_name": "CA-40",
                "poll_type": "us-representative",
                "answers": [
                    {"choice": "Ken Calvert", "pct": 33},
                    {"choice": "Young Kim", "pct": 32},
                ],
            }
        )
        self.assertEqual(known.for_answer(house, "Ken Calvert"), "R")
        self.assertEqual(known.for_answer(house, "Young Kim"), "R")
        governor = normalize(
            {
                "id": "governor",
                "subject": "2026 Florida",
                "poll_type": "governor",
                "answers": [
                    {"choice": "David Jolly", "pct": 47},
                    {"choice": "Byron Donalds", "pct": 44},
                ],
            }
        )
        self.assertEqual(known.for_answer(governor, "David Jolly"), "D")
        self.assertEqual(known.for_answer(governor, "Byron Donalds"), "R")

    def test_republican_lead_uses_red_and_icons_and_plain_text_party_labels(self):
        _, plain, html = render([sample()], self.parties)
        self.assertIn("Daily Poll Digest", html)
        self.assertIn("Ashley Moody (R): 50.1%", plain)
        self.assertIn("Angie Nixon (D): 42.7%", plain)
        self.assertIn("https://upload.wikimedia.org/wikipedia/commons/9/93/GOP_elephant.jpg", html)
        self.assertIn("https://encrypted-tbn0.gstatic.com/images", html)
        self.assertIn('alt="Republican"', html)
        self.assertIn('alt="Democrat"', html)
        self.assertIn("https://example.org/official-candidate-record", html)
        self.assertIn("border-left:3px solid #b94850", html)
        self.assertIn("Moody +7.4", html)

    def test_democratic_lead_uses_blue(self):
        poll = sample(
            answers=[
                {"choice": "Ashley Moody", "pct": 42.7},
                {"choice": "Angie Nixon", "pct": 50.1},
            ]
        )
        html = render([poll], self.parties)[2]
        self.assertIn("border-left:3px solid #5276b2", html)
        self.assertIn("Nixon +7.4", html)

    def test_tie_and_unmapped_races_remain_neutral(self):
        tied = sample(
            answers=[{"choice": "Ashley Moody", "pct": 47}, {"choice": "Angie Nixon", "pct": 47}]
        )
        unknown = sample(subject="2026 Ohio")
        for poll in (tied, unknown):
            html = render([poll], self.parties)[2]
            self.assertIn("border-left:3px solid #147d78", html)
            self.assertNotIn("GOP_elephant.jpg", html) if poll is unknown else None
        self.assertIn("GOP_elephant.jpg", render([tied], self.parties)[2])

        self.assertIn("🟨", render([unknown], self.parties)[2])

    def test_candidate_lookup_is_exact_and_scoped_by_year_office_race(self):
        for field in ("subject", "poll_type"):
            changed = {field: "2028 Florida" if field == "subject" else "governor"}
            self.assertIsNone(self.parties.for_answer(sample(**changed), "Ashley Moody"))
        self.assertIsNone(self.parties.for_answer(sample(), "A. Moody"))
        self.assertIsNone(self.parties.for_answer(sample(subject="Florida"), "Ashley Moody"))
        generic = normalize(
            {
                "id": "generic",
                "subject": "2026",
                "poll_type": "generic-ballot",
                "answers": [{"choice": "Dem", "pct": 45}, {"choice": "Rep", "pct": 42}],
            }
        )
        self.assertEqual(self.parties.for_answer(generic, "Dem"), "D")
        self.assertEqual(self.parties.for_answer(generic, "Rep"), "R")

    def test_invalid_or_duplicate_registry_fails_before_digest(self):
        invalid = [
            dict(row("Ashley Moody", "R"), party="unknown"),
            dict(row("Ashley Moody", "R"), source="http://example.org"),
            dict(row("Ashley Moody", "R"), year="future"),
        ]
        for entry in invalid:
            with self.assertRaises(ValueError):
                CandidateParties({"version": 1, "candidates": [entry]})
        with self.assertRaises(ValueError):
            CandidateParties(
                {"version": 1, "candidates": [row("Ashley Moody", "R"), row("Ashley Moody", "D")]}
            )

    def test_icons_have_alt_text_without_visible_party_letters(self):
        class Checker(HTMLParser):
            tags = set()

            def handle_starttag(self, tag, attrs):
                self.tags.add(tag)

        html = render([sample()], self.parties)[2]
        parsed = Checker()
        parsed.feed(html)
        self.assertNotIn("script", parsed.tags)
        self.assertNotIn("R</a>", html)
        self.assertNotIn("D</a>", html)
        self.assertIn('alt="Republican"', html)
        self.assertIn('alt="Democrat"', html)

    def test_third_party_lead_is_yellow_and_tie_is_neutral(self):
        for party in ("I", "O"):
            parties = CandidateParties({"version": 1, "candidates": [row("Alex Green", party)]})
            answers = [
                {"choice": "Sam Blue", "pct": 32},
                {"choice": "Alex Green", "pct": 41},
                {"choice": "Pat Red", "pct": 27},
            ]
            html = render([sample(answers=answers)], parties)[2]
            self.assertIn("Green +9", html)
            self.assertIn("background-color:#fff8d6", html)
            self.assertIn("🟨", html)
            answers[0]["pct"] = 41
            tied = render([sample(answers=answers)], parties)[2]
            self.assertIn(">Tie</p>", tied)
            self.assertNotIn("0 pts", tied)
            self.assertNotIn("background-color:#fff8d6", tied)


if __name__ == "__main__":
    unittest.main()
