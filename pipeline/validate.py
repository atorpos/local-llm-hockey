"""Code checks on the merged record. Nothing here trusts the model."""
from __future__ import annotations

from datetime import date

from . import normalize as N


def check(record: dict) -> list[str]:
    w: list[str] = []
    today = date.today().isoformat()

    # ---- stats
    st = record.get("career_statistics")
    if st and not st.get("goalie"):
        for part in ("regular_season", "playoffs"):
            for r in st.get(part, []):
                if None not in (r.get("g"), r.get("a"), r.get("pts")) and r["g"] + r["a"] != r["pts"]:
                    w.append(f"stats {part} {r['season']} {r['team']}: G+A ({r['g']}+{r['a']}) != PTS ({r['pts']})")
        tot = st.get("regular_season_totals", {})
        for pt in st.get("page_totals", []):
            reg = pt.get("regular")
            if reg and reg.get("gp") and tot.get("gp") and reg["gp"] != tot["gp"]:
                w.append(f"stats: season rows sum to {tot['gp']} GP but {pt['url']} shows NHL total {reg['gp']} "
                         f"(normal if the current season is in progress)")
    # ---- contracts
    covered: dict[str, int] = {}
    for c in record.get("contracts", []):
        n = c.get("contract_number")
        t, cap, tot = c.get("term_years"), c.get("cap_hit_usd"), c.get("total_value_usd")
        if t and cap and tot and c.get("contract_type") != "entry_level":
            if abs(cap * t - tot) > 0.01 * tot:
                w.append(f"contract {n}: cap hit x term ({cap:,} x {t}) does not equal total ({tot:,})")
        if c.get("signing_date") and c["signing_date"] > today:
            w.append(f"contract {n}: signing date {c['signing_date']} is in the future")
        if not c.get("seasons"):
            w.append(f"contract {n}: seasons unknown (start season not stated in sources)")
        for s in c.get("seasons", []):
            if s in covered and c.get("contract_type") != "entry_level":
                w.append(f"contract {n}: season {s} also covered by contract {covered[s]}")
            covered.setdefault(s, n)
        if c.get("status") == "single_source":
            w.append(f"contract {n}: only one source — verify before relying on it")
        if c.get("status") == "conflict":
            w.append(f"contract {n}: sources disagree — see 'conflicts'")

    # ---- trades
    for i, t in enumerate(record.get("trade_history", []), 1):
        if not t.get("date"):
            w.append(f"trade {i}: date not found")
        if t.get("status") == "single_source":
            w.append(f"trade {i}: only one source — verify before relying on it")

    # ---- trades vs stats: a mid-season team change usually means a trade
    if st:
        teams_by_season = {}
        for r in st.get("regular_season", []):
            teams_by_season.setdefault(r["season"], set()).add(r["team"])
        trade_seasons = {N.season_for_date(t["date"]) for t in record.get("trade_history", []) if t.get("date")}
        for s, teams in teams_by_season.items():
            if len(teams) > 1 and s not in trade_seasons:
                w.append(f"{s}: played for {len(teams)} teams but no trade found that season")
    return w
