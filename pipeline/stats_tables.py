"""Read career-statistics tables straight from HTML with code (no model involved).

Works on the common layout used by Wikipedia, Elite Prospects, HockeyDB and similar sites:
Season | Team | League | GP G A Pts PIM (+/-) | GP G A Pts PIM   (regular season, then playoffs)
Goalie tables (GP W L OT ... GAA SV%) are handled the same way.
"""
from __future__ import annotations

import re

import lxml.html

from . import normalize as N

COLMAP = {
    "gp": "gp", "g": "g", "a": "a", "pts": "pts", "p": "pts", "tp": "pts", "pim": "pim",
    "+/-": "plus_minus", "+/−": "plus_minus", "±": "plus_minus",
    "w": "w", "l": "l", "ot": "ot", "otl": "ot", "t": "t", "t/ot": "ot", "ot/t": "ot",
    "min": "toi_min", "mins": "toi_min", "toi": "toi_min", "ga": "ga", "so": "so",
    "gaa": "gaa", "sv%": "sv_pct", "sv": "sv_pct",
}
FLOAT_KEYS = {"gaa", "sv_pct"}
SEASON_RE = re.compile(r"^\s*(\d{4})\s*[-–—/]\s*(\d{2,4})")


def _grid(table) -> list[list[str]]:
    """Expand a table into a full grid, honouring rowspan/colspan."""
    grid: list[list[str | None]] = []
    spans: dict[tuple[int, int], str] = {}
    for r, tr in enumerate(table.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr")):
        row: list[str] = []
        c = 0
        cells = tr.xpath("./th|./td")
        i = 0
        while i < len(cells) or (r, c) in spans:
            if (r, c) in spans:
                row.append(spans.pop((r, c)))
                c += 1
                continue
            cell = cells[i]
            i += 1
            txt = re.sub(r"\[\w+\]", "", cell.text_content())       # drop footnote marks
            txt = re.sub(r"\s+", " ", txt).strip()
            rs = int(re.sub(r"\D", "", cell.get("rowspan", "1")) or 1)
            cs = int(re.sub(r"\D", "", cell.get("colspan", "1")) or 1)
            for dc in range(cs):
                row.append(txt)
                for dr in range(1, min(rs, 200)):
                    spans[(r + dr, c + dc)] = txt
            c += cs
        grid.append(row)
    return grid


def _header_index(grid) -> int | None:
    for i, row in enumerate(grid[:6]):
        low = [x.lower() for x in row]
        if low.count("gp") >= 1 and ("pts" in low or "p" in low or "tp" in low or "gaa" in low):
            return i
    return None


def _blocks(header: list[str]) -> list[dict[str, int]]:
    """Split header into stat blocks, each starting at a GP column."""
    blocks, cur = [], None
    for idx, h in enumerate(header):
        key = COLMAP.get(h.lower().strip())
        if key == "gp":
            if cur:
                blocks.append(cur)
            cur = {"gp": idx}
        elif cur is not None and key and key not in cur:
            cur[key] = idx
    if cur:
        blocks.append(cur)
    return blocks


def _find(header, *names) -> int | None:
    low = [h.lower().strip() for h in header]
    for n in names:
        if n in low:
            return low.index(n)
    return None


def _val(row, idx, key):
    if idx is None or idx >= len(row):
        return None
    if key in FLOAT_KEYS:
        v = N.parse_float(row[idx])
        if key == "sv_pct" and v is not None and v > 1:
            v = round(v / 100, 4)          # 91.5 -> 0.915
        return v
    return N.parse_int(row[idx])


def parse_tables(html: str) -> dict | None:
    """Return the NHL rows of the best career table on the page, or None."""
    try:
        doc = lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        return None
    best = None
    for table in doc.xpath("//table"):
        grid = _grid(table)
        hi = _header_index(grid)
        if hi is None:
            continue
        header = grid[hi]
        blocks = _blocks(header)
        if not blocks:
            continue
        i_season = _find(header, "season", "s", "year", "yr")
        i_team = _find(header, "team", "tm", "club")
        i_league = _find(header, "league", "lg", "lge")
        if i_season is None or i_team is None or i_league is None:
            continue   # without a league column we cannot be sure the rows are NHL
        goalie = any("gaa" in b or "sv_pct" in b for b in blocks)
        reg, po, totals = [], [], {}
        for row in grid[hi + 1:]:
            if len(row) <= max(i_season, i_team, i_league):
                continue
            league = row[i_league].strip().upper()
            first = " ".join(row[:3]).lower()
            if "nhl totals" in first or ("totals" in first and league in ("NHL", "")):
                for bi, blk in enumerate(blocks[:2]):
                    totals["regular" if bi == 0 else "playoffs"] = {
                        k: _val(row, idx, k) for k, idx in blk.items()}
                continue
            if league != "NHL":
                continue
            s = N.season(row[i_season])
            if not s:
                continue
            team = row[i_team]
            base = {"season": s, "team": N.team_abbr(team) or team}
            r_stats = {k: _val(row, idx, k) for k, idx in blocks[0].items()}
            if r_stats.get("gp"):
                reg.append({**base, **r_stats})
            if len(blocks) > 1:
                p_stats = {k: _val(row, idx, k) for k, idx in blocks[1].items()}
                if p_stats.get("gp"):
                    po.append({**base, **p_stats})
        if reg and (best is None or len(reg) > len(best["regular_season"])):
            best = {"goalie": goalie, "regular_season": reg, "playoffs": po, "page_totals": totals}
    return best
