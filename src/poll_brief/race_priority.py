"""Editorial race ordering from a dated, manually maintained ratings snapshot.

Cook Political Report Toss Up and Lean categories, retrieved 2026-09-14:
Senate (2026-08-20): https://www.cookpolitical.com/ratings/senate-race-ratings
Governor (2026-09-10): https://www.cookpolitical.com/ratings/governor-race-ratings
House (2026-09-11): https://www.cookpolitical.com/ratings/house-race-ratings

Competitive Senate seats are a proxy for chamber-control relevance, not a model
of the tipping-point seat. Unlisted races and other years receive no promotion.
"""

from .presentation import OFFICES, geography, race_heading

# Toss-up before Lean within each office. Party direction does not affect rank.
COMPETITIVE_2026 = {
    "us-senator": (
        "AK IA ME MI OH TX".split(),
        "GA NC NH".split(),
    ),
    "governor": (
        "GA NV OH WI".split(),
        "AK AZ IA KS MI OR".split(),
    ),
    "us-representative": (
        "AZ-01 AZ-06 CA-22 CO-08 FL-14 FL-25 IA-01 IA-03 MI-07 MI-10 NJ-07 NY-17 "
        "OH-07 OH-09 PA-07 PA-08 PA-10 TX-34 VA-02 WA-03 WI-03".split(),
        "CA-13 CA-48 FL-22 IA-02 MI-04 NC-01 NC-11 NE-02 NM-02 NV-03 NY-03 NY-04 "
        "OH-01 TX-15 TX-28 VA-01".split(),
    ),
}
RATINGS = {
    ("2026", office, f"{geography(code)} · {OFFICES[office]}".casefold()): rating
    for office, bands in COMPETITIVE_2026.items()
    for rating, codes in enumerate(bands)
    for code in codes
}
OFFICE_PRIORITY = {"us-senator": 1, "governor": 2, "us-representative": 3}


def race_priority(poll):
    if poll.poll_type == "generic-ballot":
        return (0, 0)
    heading, year = race_heading(poll)
    rating = RATINGS.get((year, poll.poll_type, heading.casefold()))
    if rating is None:
        return (4, 0)
    return (OFFICE_PRIORITY[poll.poll_type], rating)
