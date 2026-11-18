"""The 62 jurisdictions in the LTPP data: numeric code, name as stored, postal abbreviation."""

import difflib

JURISDICTIONS: list[tuple[int, str, str]] = [
    (1, "Alabama", "AL"), (2, "Alaska", "AK"), (4, "Arizona", "AZ"), (5, "Arkansas", "AR"),
    (6, "California", "CA"), (8, "Colorado", "CO"), (9, "Connecticut", "CT"), (10, "Delaware", "DE"),
    (11, "District of Columbia", "DC"), (12, "Florida", "FL"), (13, "Georgia", "GA"), (15, "Hawaii", "HI"),
    (16, "Idaho", "ID"), (17, "Illinois", "IL"), (18, "Indiana", "IN"), (19, "Iowa", "IA"),
    (20, "Kansas", "KS"), (21, "Kentucky", "KY"), (22, "Louisiana", "LA"), (23, "Maine", "ME"),
    (24, "Maryland", "MD"), (25, "Massachusetts", "MA"), (26, "Michigan", "MI"), (27, "Minnesota", "MN"),
    (28, "Mississippi", "MS"), (29, "Missouri", "MO"), (30, "Montana", "MT"), (31, "Nebraska", "NE"),
    (32, "Nevada", "NV"), (33, "New Hampshire", "NH"), (34, "New Jersey", "NJ"), (35, "New Mexico", "NM"),
    (36, "New York", "NY"), (37, "North Carolina", "NC"), (38, "North Dakota", "ND"), (39, "Ohio", "OH"),
    (40, "Oklahoma", "OK"), (41, "Oregon", "OR"), (42, "Pennsylvania", "PA"), (44, "Rhode Island", "RI"),
    (45, "South Carolina", "SC"), (46, "South Dakota", "SD"), (47, "Tennessee", "TN"), (48, "Texas", "TX"),
    (49, "Utah", "UT"), (50, "Vermont", "VT"), (51, "Virginia", "VA"), (53, "Washington", "WA"),
    (54, "West Virginia", "WV"), (55, "Wisconsin", "WI"), (56, "Wyoming", "WY"), (72, "Puerto Rico", "PR"),
    (81, "Alberta", "AB"), (82, "British Columbia", "BC"), (83, "Manitoba", "MB"), (84, "New Brunswick", "NB"),
    (85, "Newfoundland", "NL"), (86, "Nova Scotia", "NS"), (87, "Ontario", "ON"),
    (88, "Prince Edward Island", "PE"), (89, "Quebec", "QC"), (90, "Saskatchewan", "SK"),
]  # fmt: skip

_BY_NAME = {name.lower(): code for code, name, _ in JURISDICTIONS}
_BY_ABBR = {abbr.lower(): code for code, _, abbr in JURISDICTIONS}
_BY_CODE = {code: name for code, name, _ in JURISDICTIONS}


def state_name(code: int) -> str | None:
    return _BY_CODE.get(code)


def resolve_state(text: str | int) -> int:
    """Turn a name ("Ohio"), postal abbreviation ("OH") or numeric code ("39") into the numeric code."""
    raw = str(text).strip()
    key = raw.lower()
    if key in _BY_NAME:
        return _BY_NAME[key]
    if key in _BY_ABBR:
        return _BY_ABBR[key]
    if raw.isdigit() and int(raw) in _BY_CODE:
        return int(raw)
    close = [n for n in _BY_NAME if key and (n.startswith(key) or key in n)]
    close += [n for n in difflib.get_close_matches(key, list(_BY_NAME), n=3, cutoff=0.6) if n not in close]
    hint = f" Did you mean {', '.join(n.title() for n in close[:4])}?" if close else ""
    raise ValueError(
        f"Unknown state or province '{raw}'. Use a name (Ohio), postal abbreviation (OH) or numeric code (39).{hint}"
    )
