import unittest

from poll_brief.polls import normalize
from poll_brief.race_priority import race_priority


class RacePriorityTests(unittest.TestCase):
    def test_ratings_are_scoped_by_year_office_and_exact_geography(self):
        cases = [
            ("2026 IA", "us-senator", (1, 0)),
            ("2026 Iowa", "us-senator", (1, 0)),
            ("2024 Iowa", "us-senator", (4, 0)),
            ("Iowa", "us-senator", (4, 0)),
            ("2026 Iowa", "approval", (4, 0)),
            ("2026 Iowa", "governor", (2, 1)),
            ("2026 AZ-1", "us-representative", (3, 0)),
            ("2026 AZ-01", "us-representative", (3, 0)),
            ("2026 Arizona", "us-representative", (4, 0)),
            ("2026 FL", "us-senator", (4, 0)),
            ("2026 Generic", "generic-ballot", (0, 0)),
        ]
        for subject, office, expected in cases:
            with self.subTest(subject=subject, office=office):
                poll = normalize({"id": "example", "subject": subject, "poll_type": office})
                self.assertEqual(race_priority(poll), expected)
