"""Normalisation helpers: team names, seasons, dates, money and term mentions."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

from dateutil import parser as dateparser

# --------------------------------------------------------------------------- teams
TEAMS: dict[str, list[str]] = {
    "ANA": ["Anaheim Ducks", "Mighty Ducks of Anaheim", "Anaheim", "Ducks"],
    "BOS": ["Boston Bruins", "Boston", "Bruins"],
    "BUF": ["Buffalo Sabres", "Buffalo", "Sabres"],
    "CGY": ["Calgary Flames", "Calgary", "Flames"],
    "CAR": ["Carolina Hurricanes", "Carolina", "Hurricanes"],
    "CHI": ["Chicago Blackhawks", "Chicago Black Hawks", "Chicago", "Blackhawks"],
    "COL": ["Colorado Avalanche", "Colorado", "Avalanche", "Avs"],
    "CBJ": ["Columbus Blue Jackets", "Columbus", "Blue Jackets"],
    "DAL": ["Dallas Stars", "Dallas", "Stars"],
    "DET": ["Detroit Red Wings", "Detroit", "Red Wings"],
    "EDM": ["Edmonton Oilers", "Edmonton", "Oilers"],
    "FLA": ["Florida Panthers", "Florida", "Panthers"],
    "LAK": ["Los Angeles Kings", "Los Angeles", "LA Kings", "L.A. Kings", "Kings"],
    "MIN": ["Minnesota Wild", "Minnesota", "Wild"],
    "MTL": ["Montreal Canadiens", "Montréal Canadiens", "Montreal", "Montréal", "Canadiens", "Habs"],
    "NSH": ["Nashville Predators", "Nashville", "Predators", "Preds"],
    "NJD": ["New Jersey Devils", "New Jersey", "Devils"],
    "NYI": ["New York Islanders", "NY Islanders", "Islanders"],
    "NYR": ["New York Rangers", "NY Rangers", "Rangers"],
    "OTT": ["Ottawa Senators", "Ottawa", "Senators", "Sens"],
    "PHI": ["Philadelphia Flyers", "Philadelphia", "Flyers"],
    "PIT": ["Pittsburgh Penguins", "Pittsburgh", "Penguins", "Pens"],
    "SJS": ["San Jose Sharks", "San Jose", "Sharks"],
    "SEA": ["Seattle Kraken", "Seattle", "Kraken"],
    "STL": ["St. Louis Blues", "St Louis Blues", "St. Louis", "St Louis", "Blues"],
    "TBL": ["Tampa Bay Lightning", "Tampa Bay", "Tampa", "Lightning"],
    "TOR": ["Toronto Maple Leafs", "Toronto", "Maple Leafs", "Leafs"],
    "UTA": ["Utah Mammoth", "Utah Hockey Club", "Utah", "Mammoth"],
    "VAN": ["Vancouver Canucks", "Vancouver", "Canucks"],
    "VGK": ["Vegas Golden Knights", "Vegas", "Golden Knights"],
    "WSH": ["Washington Capitals", "Washington", "Capitals", "Caps"],
    "WPG": ["Winnipeg Jets", "Winnipeg", "Jets"],
    # former franchises / names
    "ARI": ["Arizona Coyotes", "Arizona", "Coyotes"],
    "PHX": ["Phoenix Coyotes", "Phoenix"],
    "ATL": ["Atlanta Thrashers", "Atlanta", "Thrashers"],
    "HFD": ["Hartford Whalers", "Hartford", "Whalers"],
    "QUE": ["Quebec Nordiques", "Quebec", "Nordiques"],
    "MNS": ["Minnesota North Stars", "North Stars"],
}
FORMER = {"ARI", "PHX", "ATL", "HFD", "QUE", "MNS"}
CURRENT_TEAMS = [abbr for abbr in TEAMS if abbr not in FORMER]   # the 32 active franchises

# Extra short codes that sites use
_ALT_CODES = {"LA": "LAK", "L.A.": "LAK", "NJ": "NJD", "N.J.": "NJD", "SJ": "SJS", "S.J.": "SJS",
              "TB": "TBL", "T.B.": "TBL", "VEG": "VGK", "VGS": "VGK", "WAS": "WSH", "CLB": "CBJ",
              "MON": "MTL", "NAS": "NSH", "CAL": "CGY", "UTAH": "UTA", "WIN": "WPG"}

_ALIASES: list[tuple[str, str]] = sorted(
    [(alias.lower(), abbr) for abbr, names in TEAMS.items() for alias in names],
    key=lambda t: -len(t[0]),
)


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def team_abbr(name: str | None) -> str | None:
    """Map any team spelling ('Avalanche', 'COL', 'Colorado Avalanche') to its abbreviation."""
    if not name:
        return None
    raw = name.strip()
    up = raw.upper().rstrip(".")
    if up in TEAMS:
        return up
    if raw.upper() in _ALT_CODES:
        return _ALT_CODES[raw.upper()]
    if up in _ALT_CODES:
        return _ALT_CODES[up]
    folded = _fold(raw)
    for alias, abbr in _ALIASES:
        if folded == _fold(alias):
            return abbr
    for alias, abbr in _ALIASES:
        if len(alias) > 3 and re.search(r"\b" + re.escape(_fold(alias)) + r"\b", folded):
            return abbr
    return None


def team_name(abbr: str | None) -> str | None:
    return TEAMS[abbr][0] if abbr in TEAMS else None


# --------------------------------------------------------------------------- seasons
_SEASON_RE = re.compile(r"(\d{4})\s*[-–—/]\s*(\d{2,4})")


def season(s: str | None) -> str | None:
    """'2026–27', '2026-2027', '2026/27' -> '2026-27'."""
    if not s:
        return None
    m = _SEASON_RE.search(str(s))
    if not m:
        return None
    y1 = int(m.group(1))
    y2s = m.group(2)
    y2 = int(y2s) if len(y2s) == 4 else int(str(y1)[:2] + y2s)
    if y2 != y1 + 1:
        # handle century roll-over such as 1999-00
        if not (len(y2s) == 2 and y2 == y1 + 1 - 100):
            return None
    return f"{y1}-{str(y1 + 1)[2:]}"


def season_start(s: str) -> int:
    return int(s[:4])


def season_add(s: str, n: int) -> str:
    y = season_start(s) + n
    return f"{y}-{str(y + 1)[2:]}"


def season_for_date(d: str | None) -> str | None:
    """The NHL season a calendar date falls in (season rolls over on 1 July)."""
    if not d or len(d) < 7:
        return None
    y, m = int(d[:4]), int(d[5:7])
    start = y if m >= 7 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


# --------------------------------------------------------------------------- dates
_ISO_FULL = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MONTH = re.compile(r"^\d{4}-\d{2}$")
_YEAR = re.compile(r"^\d{4}$")


def norm_date(s: str | None) -> str | None:
    """Return 'YYYY-MM-DD', 'YYYY-MM' or 'YYYY' (whatever precision is known)."""
    if not s:
        return None
    s = str(s).strip()
    if _ISO_FULL.match(s) or _ISO_MONTH.match(s) or _YEAR.match(s):
        return s
    has_day = bool(re.search(r"\b\d{1,2}(st|nd|rd|th)?\b", re.sub(r"\d{4}", "", s)))
    try:
        dt = dateparser.parse(s, default=date(1900, 1, 1), fuzzy=True)
    except (ValueError, OverflowError):
        m = re.search(r"\b(19|20)\d{2}\b", s)
        return m.group(0) if m else None
    if dt.year == 1900:
        return None
    if has_day:
        return dt.strftime("%Y-%m-%d")
    if re.search(r"[A-Za-z]{3,}", s):
        return dt.strftime("%Y-%m")
    return str(dt.year)


def date_year(d: str | None) -> int | None:
    return int(d[:4]) if d and re.match(r"^\d{4}", d) else None


# --------------------------------------------------------------------------- money / numbers
_UNIT = {"million": 1e6, "mil": 1e6, "mln": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9,
         "k": 1e3, "thousand": 1e3}
_MONEY_RE = re.compile(
    r"(?:US|CA|C|U\.S\.)?\$\s?(\d+(?:,\d{3})*(?:\.\d+)?)\s*-?\s*(million|mil\.?|mln|billion|bn|thousand|[mMbBkK]\b)?",
)
_BARE_UNIT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*-?\s*(million|[mM]\b)")


def money_mentions(text: str) -> set[int]:
    vals: set[int] = set()
    for m in _MONEY_RE.finditer(text):
        num = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower().rstrip(".")
        vals.add(int(round(num * _UNIT.get(unit, 1))))
    for m in _BARE_UNIT_RE.finditer(text):
        vals.add(int(round(float(m.group(1)) * 1e6)))
    return vals


def money_supported(value: int | None, mentions: set[int], tol: float) -> bool:
    if value is None:
        return True
    return any(v > 0 and abs(v - value) / v <= tol for v in mentions)


_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_TERM_RE = re.compile(r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
                      r"\s*[- ]\s*(?:year|yr|season)s?\b", re.I)
_TERM_RE2 = re.compile(r"\b(\d{1,2})\s*(?:years|yrs)\b", re.I)


def term_mentions(text: str) -> set[int]:
    out: set[int] = set()
    for m in _TERM_RE.finditer(text):
        t = m.group(1).lower()
        out.add(int(t) if t.isdigit() else _NUM_WORDS[t])
    for m in _TERM_RE2.finditer(text):
        out.add(int(m.group(1)))
    return out


def parse_int(s) -> int | None:
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("−", "-").replace("–", "-")
    if s in ("", "-", "—", "–", "N/A", "n/a"):
        return None
    m = re.match(r"^[+]?(-?\d+)$", s)
    return int(m.group(1)) if m else None


def parse_float(s) -> float | None:
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("−", "-")
    try:
        return float(s)
    except ValueError:
        return None


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _fold(name)).strip("-")


def text_norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("−", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip().lower()
