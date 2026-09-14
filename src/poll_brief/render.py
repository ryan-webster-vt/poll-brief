"""Table-based email newsletter with inline CSS and a plain-text equivalent."""

from collections import defaultdict
from html import escape
from urllib.parse import urlsplit

from .parties import CandidateParties
from .presentation import field_dates, margin_label, number, race_heading, sample_label

ATTRIBUTION = "Data: VoteHub, https://votehub.com/polls/api/ (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/). Grouping and margins calculated by poll-brief."
FONT = "font-family:Arial,Helvetica,sans-serif;"
TABLE = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'


def safe_url(value):
    if not value or any(ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return value if parsed.scheme in ("https", "http") and parsed.netloc else None


PARTY_STYLES = {
    "R": (
        "#a52e36",
        "#fff1f2",
        "#b94850",
        "https://upload.wikimedia.org/wikipedia/commons/9/93/GOP_elephant.jpg?utm_source=commons.wikimedia.org&utm_campaign=index&utm_content=original",
        "Republican",
    ),
    "D": (
        "#2756a0",
        "#eef3ff",
        "#5276b2",
        "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRJAWmU_isz0e7WoEh_AKC2NZ72QS6S6DXlbFDneYExkg&s=10",
        "Democrat",
    ),
}
NEUTRAL_STYLE = ("#12625f", "#edf6f5", "#147d78")
NEUTRAL_ICON = "🟨"
RACE_PRIORITY = {
    "us-senator": 0,
    "governor": 1,
    "us-representative": 2,
    "generic-ballot": 3,
}


def race_sort_key(members):
    poll = members[0]
    heading, year = race_heading(poll)
    return (
        RACE_PRIORITY.get(poll.poll_type, len(RACE_PRIORITY)),
        -int(year) if year else float("inf"),
        heading.casefold(),
        poll.group.casefold(),
    )


def margin_party(poll, parties):
    margin = poll.margin
    if not margin or margin == "Tie (0 points)":
        return None
    winner = margin.removesuffix(" points").rsplit(" +", 1)[0]
    return parties.for_answer(poll, winner)


def poll_card(poll, parties):
    metadata = " · ".join(
        value
        for value in (field_dates(poll.start_date, poll.end_date), sample_label(poll))
        if value
    )
    plain = [poll.pollster] if poll.pollster else []
    html = [
        f'<table {TABLE} width="100%" bgcolor="#ffffff" style="width:100%;table-layout:fixed;border:1px solid #dfe4e9;border-radius:12px;border-collapse:separate;background-color:#ffffff;">',
        f'<tr><td style="padding:20px;{FONT}color:#172b3a;word-wrap:break-word;overflow-wrap:anywhere;">',
    ]
    if poll.pollster:
        html.append(
            f'<h3 style="margin:0 0 6px;font-size:16px;line-height:22px;font-weight:700;">{escape(poll.pollster)}</h3>'
        )
    if metadata:
        plain.append(metadata)
        html.append(
            f'<p style="margin:0 0 16px;font-size:13px;line-height:20px;color:#647180;">{escape(metadata)}</p>'
        )
    if poll.answers:
        html.append(f'<table {TABLE} width="100%" style="width:100%;table-layout:fixed;">')
        for name, pct in poll.answers:
            value = f"{number(pct)}%" if pct is not None else ""
            party, party_source = parties.lookup(poll, name)
            plain.append(
                f"{name} ({party}): {value}"
                if party and value
                else f"{name}: {value}"
                if value
                else name
            )
            marker = ""
            if party in PARTY_STYLES:
                color, _, _, icon_url, label = PARTY_STYLES[party]
                marker_text = (
                    f'<img src="{escape(icon_url, quote=True)}" alt="{label}" width="18" '
                    f'height="18" style="display:inline-block;width:18px;height:18px;'
                    f'vertical-align:-4px;object-fit:contain;" /> {party}'
                )
                if party_source:
                    marker = f'<a href="{escape(party_source, quote=True)}" aria-label="{label} party source" style="display:inline-block;margin-right:6px;color:{color};font-size:14px;text-decoration:none;white-space:nowrap;">{marker_text}</a>'
                else:
                    marker = f'<span aria-label="{label}" style="display:inline-block;margin-right:6px;color:{color};font-size:14px;white-space:nowrap;">{marker_text}</span>'
            elif party:
                marker = f'<span aria-label="Unknown or third-party" style="display:inline-block;margin-right:6px;font-size:14px;white-space:nowrap;">{NEUTRAL_ICON} {party}</span>'
            else:
                marker = f'<span aria-label="Unknown or third-party" style="display:inline-block;margin-right:6px;font-size:14px;white-space:nowrap;">{NEUTRAL_ICON}</span>'
            html.append(
                f'<tr><td valign="top" style="padding:5px 12px 5px 0;{FONT}font-size:16px;line-height:24px;color:#233747;word-wrap:break-word;overflow-wrap:anywhere;">{marker}{escape(name)}</td>'
                f'<td width="82" align="right" valign="top" style="width:82px;padding:5px 0;{FONT}font-size:20px;line-height:24px;font-weight:700;color:#172b3a;white-space:nowrap;">{value}</td></tr>'
            )
        html.append("</table>")
    margin = margin_label(poll)
    if margin:
        plain.append(f"Margin: {margin} (percentage points)")
        party = margin_party(poll, parties)
        color, background, border = (
            PARTY_STYLES[party][:3] if party in PARTY_STYLES else NEUTRAL_STYLE
        )
        html.append(
            f'<p style="margin:16px 0 0;padding:12px 14px;border-left:3px solid {border};background-color:{background};color:{color};font-size:22px;line-height:28px;font-weight:700;">{escape(margin)}'
            f'<span style="display:block;font-size:11px;line-height:18px;font-weight:400;color:{color};">Margin · percentage points</span></p>'
        )
    url = safe_url(poll.url)
    if url:
        plain.append(f"View poll → {url}")
        html.append(
            f'<p style="margin:14px 0 0;font-size:13px;line-height:22px;"><a href="{escape(url, quote=True)}" style="display:inline-block;padding:5px 0;color:#476778;text-decoration:underline;">View poll →</a></p>'
        )
    html.append("</td></tr></table>")
    return "\n".join(plain), "".join(html)


def render(polls, parties=None):
    parties = CandidateParties.bundled() if parties is None else parties
    subject = f"VoteHub: {len(polls)} new poll(s)" if polls else "VoteHub: No new polls"
    groups = defaultdict(list)
    for poll in polls:
        # Display labels may omit years, so retain the raw grouping key.
        groups[poll.group].append(poll)
    count = f"{len(polls)} new {'poll' if len(polls) == 1 else 'polls'}"
    summary = f"{count} · {len(groups)} {'race or topic' if len(groups) == 1 else 'races & topics'}"
    plain = [subject]
    html = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="x-apple-disable-message-reformatting">',
        "<title>VoteHub daily poll digest</title></head>",
        f'<body bgcolor="#f3f5f7" style="margin:0;padding:0;width:100%;background-color:#f3f5f7;{FONT}-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">',
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">{escape(summary)}. The latest from VoteHub.</div>',
        f'<table {TABLE} width="100%" bgcolor="#f3f5f7" style="width:100%;background-color:#f3f5f7;"><tr><td align="center" style="padding:24px 12px;">',
        '<!--[if mso]><table role="presentation" width="640" align="center" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->',
        f'<table {TABLE} align="center" width="100%" style="width:100%;max-width:640px;table-layout:fixed;">',
        f'<tr><td style="padding:8px 4px 22px;border-bottom:2px solid #172b3a;{FONT}">',
        '<p style="margin:0 0 10px;color:#147d78;font-size:11px;line-height:16px;letter-spacing:2px;font-weight:700;">POLL BRIEF</p>',
        '<h1 style="margin:0 0 10px;color:#172b3a;font-size:30px;line-height:36px;letter-spacing:-0.6px;">Daily Poll Digest</h1>',
        f'<p style="margin:0;color:#647180;font-size:14px;line-height:22px;">{escape(summary)}</p></td></tr>',
    ]
    if not polls:
        message = "No new polls to include after a successful VoteHub fetch."
        plain.append(message)
        html.append(
            f'<tr><td style="padding:24px 0;"><table {TABLE} width="100%" bgcolor="#ffffff" style="border:1px solid #dfe4e9;border-radius:12px;"><tr><td style="padding:24px;{FONT}color:#647180;font-size:15px;line-height:24px;"><h2 style="margin:0 0 8px;color:#172b3a;font-size:20px;">No new polls</h2>{message}</td></tr></table></td></tr>'
        )
    ordered = sorted(groups.values(), key=race_sort_key)
    for members in ordered:
        heading, year = race_heading(members[0])
        plain.extend(("", heading + (f" ({year})" if year else "")))
        html.append(
            f'<tr><td style="padding:28px 4px 12px;{FONT}word-wrap:break-word;overflow-wrap:anywhere;">'
        )
        if year:
            html.append(
                f'<p style="margin:0 0 4px;color:#647180;font-size:11px;line-height:16px;letter-spacing:1px;">{year} ELECTION</p>'
            )
        html.append(
            f'<h2 style="margin:0;color:#172b3a;font-size:19px;line-height:26px;font-weight:700;">{escape(heading)}</h2></td></tr>'
        )
        for poll in sorted(members, key=lambda p: (p.pollster or "", p.end_date or "", p.identity)):
            text, card = poll_card(poll, parties)
            plain.append(text)
            html.append(f'<tr><td style="padding:0 0 12px;">{card}</td></tr>')
    plain.append("\n" + ATTRIBUTION)
    html.append(
        f'<tr><td style="padding:20px 4px 8px;border-top:1px solid #dfe4e9;{FONT}color:#697581;font-size:11px;line-height:18px;">'
        '<p style="margin:0 0 4px;">Polling data from <a href="https://votehub.com/polls/api/" style="color:#697581;text-decoration:underline;">VoteHub</a> · '
        '<a href="https://creativecommons.org/licenses/by/4.0/" style="color:#697581;text-decoration:underline;">CC BY 4.0</a></p>'
        '<p style="margin:0;">Grouping and margins calculated by poll-brief.</p></td></tr></table>'
        "<!--[if mso]></td></tr></table><![endif]--></td></tr></table></body></html>"
    )
    return subject, "\n\n".join(plain), "".join(html)
