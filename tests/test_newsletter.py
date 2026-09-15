import unittest
from dataclasses import replace
from decimal import Decimal
from html.parser import HTMLParser

from poll_brief.polls import normalize
from poll_brief.presentation import field_dates, margin_label, number, race_heading, sample_label
from poll_brief.render import render


def poll(**changes):
    return normalize(
        dict(
            id="synthetic-senate",
            subject="2026 Florida",
            poll_type="us-senator",
            pollster="Example Research",
            start_date="2026-09-08",
            end_date="2026-09-10",
            sample_size=733,
            population="lv",
            url="https://example.com/poll",
            answers=[
                {"choice": "Ashley Moody", "pct": 50.1},
                {"choice": "Angie Nixon", "pct": 42.7},
            ],
            **changes,
        )
    )


class NewsletterTests(unittest.TestCase):
    def test_polls_sort_by_end_date_newest_first_with_undated_last(self):
        rows = [
            replace(poll(), identity=str(i), pollster=name, end_date=ended)
            for i, (name, ended) in enumerate(
                [
                    ("Alpha", "2026-08-21"),
                    ("Zulu", "2026-09-03"),
                    ("Missing", None),
                    ("Invalid", "invalid"),
                    ("Old year", "2025-12-31"),
                ]
            )
        ]
        for body in render(rows)[1:]:
            positions = [
                body.index(name) for name in ("Zulu", "Alpha", "Old year", "Invalid", "Missing")
            ]
            self.assertEqual(positions, sorted(positions))

    def test_multicandidate_margin_and_descending_results(self):
        row = normalize(
            {
                "id": "multiple",
                "poll_type": "us-senator",
                "answers": [
                    {"choice": "Sam Runner", "pct": 44},
                    {"choice": "Pat Third", "pct": 3},
                    {"choice": "Alex Leader", "pct": 52},
                ],
            }
        )
        self.assertEqual(row.margin, "Alex Leader +8 points")
        for body in render([row])[1:]:
            self.assertIn("Leader +8", body)
            self.assertLess(body.index("Alex Leader"), body.index("Sam Runner"))
            self.assertLess(body.index("Sam Runner"), body.index("Pat Third"))
            self.assertNotIn("percentage points", body)
            self.assertNotIn("Margin:", body)
        missing = replace(row, answers=row.answers + (("Unknown result", None),))
        self.assertIsNone(missing.margin)
        self.assertGreater(
            render([missing])[2].index("Unknown result"), render([missing])[2].index("Pat Third")
        )
        residual = replace(row, answers=row.answers + (("Undecided", Decimal("1")),))
        self.assertEqual(residual.margin, "Alex Leader +8 points")

    def test_requested_senate_presentation_in_both_bodies(self):
        subject, plain, html = render([poll()])
        for body in (plain, html):
            self.assertIn("Florida · U.S. Senate", body)
            self.assertIn("Sep 8–10 · 733 LV", body)
            self.assertIn("Moody +7.4", body)
            self.assertIn("Ashley Moody", body)
            self.assertIn("50.1%", body)
            self.assertIn("View poll →", body)
            self.assertNotIn("Fieldwork start", body)
        self.assertIn("2026", html)

    def test_district_names_ordinals_and_unknown_topics(self):
        for seat, expected in (
            ("CA-40", "California 40th"),
            ("NY-21", "New York 21st"),
            ("TX-12", "Texas 12th"),
            ("AK-AL", "Alaska At-large"),
        ):
            row = normalize(
                {
                    "id": seat,
                    "subject": f"2026 {seat}",
                    "seat_name": seat,
                    "poll_type": "us-representative",
                }
            )
            self.assertEqual(race_heading(row), (f"{expected} · U.S. House", "2026"))
        unknown = normalize({"id": "x", "subject": "Unfamiliar topic", "poll_type": "custom"})
        self.assertEqual(race_heading(unknown), ("Unfamiliar topic · custom", None))

    def test_dates_handle_missing_cross_month_cross_year_and_invalid_values(self):
        cases = [
            (("2026-09-08", "2026-09-10"), "Sep 8–10"),
            (("2026-09-30", "2026-10-02"), "Sep 30–Oct 2"),
            (("2025-12-30", "2026-01-02"), "Dec 30, 2025–Jan 2, 2026"),
            ((None, "2026-09-10"), "Through Sep 10"),
            (("2026-09-08", None), "From Sep 8"),
            (("2026-09-08", "2026-09-08"), "Sep 8"),
            ((None, None), None),
            (("invalid", None), "From: invalid"),
        ]
        for args, expected in cases:
            self.assertEqual(field_dates(*args), expected)

    def test_sample_codes_missing_values_and_numeric_format(self):
        self.assertEqual(sample_label(poll()), "733 LV")
        self.assertEqual(sample_label(normalize({"id": "x", "population": "custom"})), "custom")
        self.assertEqual(sample_label(normalize({"id": "x"})), "")
        self.assertEqual(number(Decimal("50.0")), "50")
        self.assertEqual(number(Decimal("100")), "100")
        self.assertEqual(number(Decimal("7.40")), "7.4")

    def test_same_surnames_keep_full_margin_name(self):
        row = normalize(
            {
                "id": "same-name",
                "poll_type": "governor",
                "answers": [
                    {"choice": "Alex Smith", "pct": 51},
                    {"choice": "Taylor Smith", "pct": 45},
                ],
            }
        )
        self.assertEqual(margin_label(row), "Alex Smith +6")

    def test_year_groups_do_not_merge_or_fail_with_an_undated_group(self):
        rows = [
            normalize({"id": str(i), "subject": subject, "poll_type": "us-senator"})
            for i, subject in enumerate(("2024 Florida", "2026 Florida", "Florida"))
        ]
        html = render(rows)[2]
        self.assertEqual(html.count(">Florida · U.S. Senate</h2>"), 3)
        self.assertIn("2024 ELECTION", html)
        self.assertIn("2026 ELECTION", html)

    def test_races_sort_by_impact_then_year_and_geography_in_both_bodies(self):
        cases = (
            ("2026 TX-12", "us-representative", "Texas 12th · U.S. House"),
            ("2026 Florida", "governor", "Florida · Governor"),
            ("2026 New York", "us-senator", "New York · U.S. Senate"),
            ("2024 Alabama", "us-senator", "Alabama · U.S. Senate"),
            ("2026 Florida", "us-senator", "Florida · U.S. Senate"),
            ("2026 Generic", "generic-ballot", "Generic ballot"),
            ("2026 Ohio", "approval", "Ohio · Approval"),
            ("2026 Iowa", "us-senator", "Iowa · U.S. Senate"),
            ("2026 North Carolina", "us-senator", "North Carolina · U.S. Senate"),
            ("2026 Arizona", "governor", "Arizona · Governor"),
            ("2026 AZ-01", "us-representative", "Arizona 1st · U.S. House"),
        )
        rows = [
            normalize({"id": str(index), "subject": subject, "poll_type": office})
            for index, (subject, office, _) in enumerate(cases)
        ]
        expected = [cases[index][2] for index in (5, 7, 8, 9, 10, 1, 4, 2, 6, 0, 3)]
        forward = render(rows)
        reverse = render(list(reversed(rows)))
        self.assertEqual(forward, reverse)
        for body in forward[1:]:
            positions = [body.index(heading) for heading in expected]
            self.assertEqual(positions, sorted(positions))

    def test_email_markup_keeps_all_results_and_has_no_active_dependencies(self):
        class Elements(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
                self.links = []
                self.tables = []

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                self.tags.append(tag)
                if tag == "a":
                    self.links.append(values.get("href"))
                    if values.get("href") == "https://example.com/poll":
                        if values.get("target") != "_blank" or "noopener" not in values.get(
                            "rel", ""
                        ):
                            raise AssertionError("Poll source must open safely in a new tab")
                if tag == "table":
                    self.tables.append(values)
                self.assert_no_handlers(values)

            def assert_no_handlers(self, values):
                if any(key.startswith("on") for key in values):
                    raise AssertionError("Active HTML event handler")

        html = render([poll()])[2]
        parsed = Elements()
        parsed.feed(html)
        self.assertNotIn("script", parsed.tags)
        self.assertNotIn("link", parsed.tags)
        self.assertTrue(all(table["role"] == "presentation" for table in parsed.tables))
        self.assertIn("max-width:640px", html)
        self.assertIn("<!--[if mso]>", html)
        self.assertIn("https://example.com/poll", parsed.links)
        self.assertIn("42.7%", html)
        self.assertGreater(html.index("Polling data from"), html.index("View poll"))


if __name__ == "__main__":
    unittest.main()
