"""Compact display labels; raw poll fields and identities remain unchanged."""

import re
from datetime import date
from decimal import Decimal

STATES = dict(
    line.split(":", 1)
    for line in """AL:Alabama
AK:Alaska
AZ:Arizona
AR:Arkansas
CA:California
CO:Colorado
CT:Connecticut
DE:Delaware
DC:District of Columbia
FL:Florida
GA:Georgia
HI:Hawaii
ID:Idaho
IL:Illinois
IN:Indiana
IA:Iowa
KS:Kansas
KY:Kentucky
LA:Louisiana
ME:Maine
MD:Maryland
MA:Massachusetts
MI:Michigan
MN:Minnesota
MS:Mississippi
MO:Missouri
MT:Montana
NE:Nebraska
NV:Nevada
NH:New Hampshire
NJ:New Jersey
NM:New Mexico
NY:New York
NC:North Carolina
ND:North Dakota
OH:Ohio
OK:Oklahoma
OR:Oregon
PA:Pennsylvania
RI:Rhode Island
SC:South Carolina
SD:South Dakota
TN:Tennessee
TX:Texas
UT:Utah
VT:Vermont
VA:Virginia
WA:Washington
WV:West Virginia
WI:Wisconsin
WY:Wyoming""".splitlines()
)
OFFICES = {
    "us-senator": "U.S. Senate",
    "us-representative": "U.S. House",
    "governor": "Governor",
    "generic-ballot": "Generic ballot",
    "approval": "Approval",
    "favorability": "Favorability",
}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def ordinal(number):
    suffix = (
        "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    )
    return f"{number}{suffix}"


def geography(value):
    match = re.fullmatch(r"([A-Z]{2})-(\d+|AL)", value)
    if match and match[1] in STATES:
        district = "At-large" if match[2] in ("0", "00", "AL") else ordinal(int(match[2]))
        return f"{STATES[match[1]]} {district}"
    return STATES.get(value, value)


def race_heading(poll):
    """Return the friendly heading and explicit election year, when supplied."""
    subject = poll.subject or ""
    match = re.fullmatch(r"(\d{4})(?:\s+(.+))?", subject)
    year = match[1] if match else None
    if match:
        subject = match[2] or ""
    parts = []
    for value in (subject, poll.seat_name or ""):
        if poll.poll_type == "generic-ballot" and value.casefold() == "generic":
            continue
        label = geography(value)
        if label and label not in parts:
            parts.append(label)
    # The district already contains the state; avoid "California · California 40th".
    if len(parts) == 2 and parts[1].startswith(parts[0] + " "):
        parts.pop(0)
    office = OFFICES.get(poll.poll_type, poll.poll_type)
    if office and office not in parts:
        parts.append(office)
    return " · ".join(parts) or "Other polls", year


def field_dates(start, end):
    def parse(value):
        return date.fromisoformat(value) if value else None

    def short(value, year=False):
        return f"{MONTHS[value.month - 1]} {value.day}" + (f", {value.year}" if year else "")

    try:
        first, last = parse(start), parse(end)
    except ValueError:
        return " · ".join(
            f"{label}: {value}" for label, value in (("From", start), ("Through", end)) if value
        )
    if first and last:
        if first > last:
            return f"From {start} · Through {end}"
        if first == last:
            return short(first)
        if first.year != last.year:
            return f"{short(first, True)}–{short(last, True)}"
        if first.month == last.month:
            return f"{short(first)}–{last.day}"
        return f"{short(first)}–{short(last)}"
    if first:
        return f"From {short(first)}"
    return f"Through {short(last)}" if last else None


def sample_label(poll):
    population = {"lv": "LV", "rv": "RV", "a": "A"}.get(poll.population, poll.population)
    return " ".join(value for value in (poll.sample_size, population) if value)


def number(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def margin_label(poll):
    margin = poll.margin
    if not margin:
        return None
    if margin == "Tie (0 points)":
        return "Tie"
    name, amount = margin.removesuffix(" points").rsplit(" +", 1)
    if poll.poll_type in ("governor", "us-senator", "us-representative"):
        # Keep full names in result rows; abbreviate only an unambiguous last token.
        last = name.split()[-1]
        if (
            last.casefold().rstrip(".,") not in {"jr", "sr", "ii", "iii", "iv"}
            and sum(candidate.split()[-1] == last for candidate, _ in poll.answers) == 1
        ):
            name = last
    return f"{name} +{number(Decimal(amount))}"
