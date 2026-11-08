"""Best-effort current roster from the team's Wikipedia page (players file is the fallback)."""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

import lxml.html

from . import normalize as N
from .stats_tables import _grid

log = logging.getLogger(__name__)


def roster_from_wikipedia(team: str, fetcher) -> list[str]:
    abbr = N.team_abbr(team)
    full = N.team_name(abbr) if abbr else team
    url = "https://en.wikipedia.org/wiki/" + quote(full.replace(" ", "_"))
    page = fetcher.get(url)
    if not page:
        log.warning("could not fetch %s", url)
        return []
    return parse_roster(page["html"])


def parse_roster(html: str) -> list[str]:
    doc = lxml.html.fromstring(html)
    best: list[str] = []
    for table in doc.xpath("//table"):
        grid = _grid(table)
        for hi, row in enumerate(grid[:4]):
            low = [c.lower() for c in row]
            if "player" in low and ("pos" in low or "position" in low):
                col = low.index("player")
                names = []
                for r in grid[hi + 1:]:
                    if col < len(r) and r[col]:
                        names.append(_clean(r[col]))
                names = [n for n in names if n and len(n.split()) >= 2]
                if len(names) > len(best):
                    best = names
                break
    return list(dict.fromkeys(best))


def _clean(cell: str) -> str:
    s = re.sub(r"\((?:C|A)\)|\*|†|‡", "", cell).strip()
    s = re.sub(r"\s+", " ", s)
    if "," in s:                       # "Makar, Cale" -> "Cale Makar"
        last, first = [x.strip() for x in s.split(",", 1)]
        s = f"{first} {last}"
    return s
