"""Combine facts from several pages: vote by source weight, flag agreement and conflicts."""
from __future__ import annotations

from collections import defaultdict

from . import normalize as N

KEY_FIELDS = ("term_years", "cap_hit_usd", "total_value_usd")


# ---------------------------------------------------------------- voting helpers
def _vote(items: list[dict], field: str):
    """Weighted vote. Returns (value, n_domains_agreeing, competing_values)."""
    tally: dict = defaultdict(float)
    doms: dict = defaultdict(set)
    for it in items:
        v = it.get(field)
        if v in (None, "", []):
            continue
        key = tuple(v) if isinstance(v, list) else v
        tally[key] += it["_weight"]
        doms[key].add(it["_domain"])
    if not tally:
        return None, 0, []
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], -len(doms[kv[0]])))
    best = ranked[0][0]
    others = [k for k, w in ranked[1:] if w >= 0.5 * ranked[0][1]]
    return (list(best) if isinstance(best, tuple) else best), len(doms[best]), others


def _close(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol * max(abs(a), abs(b), 1)


# ---------------------------------------------------------------- contracts
def _contract_match(a: dict, b: dict) -> bool:
    if a.get("team_abbr") and b.get("team_abbr") and a["team_abbr"] != b["team_abbr"]:
        return False
    ta, tb = a.get("contract_type"), b.get("contract_type")
    if "entry_level" in (ta, tb) and ta != tb and "unknown" not in (ta, tb):
        return False
    if a.get("first_season") and b.get("first_season"):
        return a["first_season"] == b["first_season"]
    if a.get("term_years") and b.get("term_years") and a["term_years"] != b["term_years"]:
        return False
    ya, yb = N.date_year(a.get("signing_date")), N.date_year(b.get("signing_date"))
    if ya and yb and abs(ya - yb) > 1:
        return False
    if a.get("total_value_usd") and b.get("total_value_usd"):
        return _close(a["total_value_usd"], b["total_value_usd"])
    if a.get("cap_hit_usd") and b.get("cap_hit_usd"):
        return _close(a["cap_hit_usd"], b["cap_hit_usd"])
    return bool(a.get("term_years") and ya and ya == yb)


def _cluster(items, match):
    clusters: list[list[dict]] = []
    for it in items:
        for cl in clusters:
            if any(match(it, other) for other in cl):
                cl.append(it)
                break
        else:
            clusters.append([it])
    return clusters


def _status(n_agree: int, conflicts: list) -> str:
    if conflicts:
        return "conflict"
    return "confirmed" if n_agree >= 2 else "single_source"


def merge_contracts(items: list[dict]) -> list[dict]:
    out = []
    for cl in _cluster(items, _contract_match):
        rec, derived, conflicts, agree = {}, [], [], []
        for f in ("team_abbr", "contract_type", "signing_date", "first_season", *KEY_FIELDS):
            v, n, others = _vote(cl, f)
            rec[f] = v
            if f in KEY_FIELDS and v is not None:
                agree.append(n)
                if others:
                    conflicts.append({"field": f, "chosen": v, "other_reported": others})
        # prefer the most precise signing date among ones that agree on the year
        dates = [c["signing_date"] for c in cl if c.get("signing_date")]
        if rec["signing_date"] and dates:
            same_year = [d for d in dates if d[:4] == rec["signing_date"][:4]]
            rec["signing_date"] = max(same_year, key=len)
        if rec["contract_type"] in (None, "unknown"):
            known = [c["contract_type"] for c in cl if c.get("contract_type") not in (None, "unknown")]
            rec["contract_type"] = max(set(known), key=known.count) if known else "unknown"
        clauses = []
        for c in sorted(cl, key=lambda c: -c["_weight"]):
            for x in c.get("clauses") or []:
                if x and x.lower() not in [y.lower() for y in clauses]:
                    clauses.append(x)
        rec["clauses"] = clauses
        # fill gaps with arithmetic
        t, cap, tot = rec["term_years"], rec["cap_hit_usd"], rec["total_value_usd"]
        if t and cap and not tot and rec["contract_type"] != "entry_level":
            rec["total_value_usd"] = cap * t
            derived.append("total_value_usd")
        if t and tot and not cap:
            rec["cap_hit_usd"] = int(round(tot / t))
            derived.append("cap_hit_usd")
        rec["team"] = N.team_name(rec["team_abbr"]) or next((c.get("team") for c in cl if c.get("team")), None)
        rec["status"] = _status(max(agree) if agree else 0, conflicts)
        rec["conflicts"] = conflicts
        rec["derived_fields"] = derived
        rec["sources"] = sorted({c["_url"] for c in cl})
        rec["evidence"] = [{"url": c["_url"], "quote": c.get("evidence")} for c in cl][:3]
        out.append(rec)
    return _order_and_fill_seasons(out)


def _order_and_fill_seasons(contracts: list[dict]) -> list[dict]:
    def first_guess(c):
        if c.get("first_season"):
            return c["first_season"]
        d = c.get("signing_date")
        if d and len(d) >= 7 and c.get("contract_type") != "extension":
            return N.season_for_date(d)
        return None

    for c in contracts:
        g = first_guess(c)
        if g and not c.get("first_season"):
            c["first_season"] = g
            c["derived_fields"].append("first_season (from signing date)")

    def sort_key(c):
        fs = c.get("first_season")
        d = c.get("signing_date") or ""
        return (int(fs[:4]) if fs else (N.date_year(d) or 9999) + 1, d)

    contracts.sort(key=sort_key)
    # an extension starts the season after the contract before it ends
    for i, c in enumerate(contracts):
        if not c.get("first_season") and c.get("contract_type") == "extension" and i > 0:
            prev = contracts[i - 1]
            if prev.get("first_season") and prev.get("term_years"):
                c["first_season"] = N.season_add(prev["first_season"], prev["term_years"])
                c["derived_fields"].append("first_season (follows previous contract)")
    for c in contracts:
        if c.get("first_season") and c.get("term_years"):
            c["seasons"] = [N.season_add(c["first_season"], k) for k in range(c["term_years"])]
        else:
            c["seasons"] = []
    contracts.sort(key=sort_key)
    for i, c in enumerate(contracts, 1):
        c["contract_number"] = i
    return contracts


# ---------------------------------------------------------------- trades
def _trade_match(a, b) -> bool:
    if (a["from_abbr"], a["to_abbr"]) != (b["from_abbr"], b["to_abbr"]):
        return False
    da, db = a.get("date"), b.get("date")
    if not da or not db:
        return True
    if len(da) >= 10 and len(db) >= 10:
        from datetime import date
        x, y = date.fromisoformat(da[:10]), date.fromisoformat(db[:10])
        return abs((x - y).days) <= 7
    return da[:7] == db[:7] if len(da) >= 7 and len(db) >= 7 else da[:4] == db[:4]


def merge_trades(items: list[dict]) -> list[dict]:
    out = []
    for cl in _cluster(items, _trade_match):
        dates = [t["date"] for t in cl if t.get("date")]
        best_date = max(dates, key=len) if dates else None
        best = max(cl, key=lambda t: (t["_weight"], len(t.get("new_team_received") or [])
                                      + len(t.get("old_team_received") or [])))
        pct, _, pct_conf = _vote(cl, "salary_retained_pct")
        doms = {t["_domain"] for t in cl}
        out.append({
            "date": best_date,
            "from_team": N.team_name(best["from_abbr"]), "from_abbr": best["from_abbr"],
            "to_team": N.team_name(best["to_abbr"]), "to_abbr": best["to_abbr"],
            "new_team_received": best.get("new_team_received") or [],
            "old_team_received": best.get("old_team_received") or [],
            "salary_retained_pct": pct,
            "status": "conflict" if pct_conf else ("confirmed" if len(doms) >= 2 else "single_source"),
            "sources": sorted({t["_url"] for t in cl}),
            "evidence": [{"url": t["_url"], "quote": t.get("evidence")} for t in cl][:3],
        })
    out.sort(key=lambda t: t["date"] or "9999")
    return out


# ---------------------------------------------------------------- bio
def merge_bio(items: list[dict]) -> dict:
    bio = {}
    for f in ("position", "shoots", "birth_date", "birthplace", "draft_year", "draft_round",
              "draft_overall", "draft_team_abbr"):
        v, n, others = _vote(items, f)
        bio[f] = v
    if bio.get("birth_date"):
        precise = [i["birth_date"] for i in items if i.get("birth_date") and i["birth_date"][:4] == bio["birth_date"][:4]]
        bio["birth_date"] = max(precise, key=len)
    return bio


# ---------------------------------------------------------------- stats
STAT_KEYS_SKATER = ("gp", "g", "a", "pts", "pim", "plus_minus")
STAT_KEYS_GOALIE = ("gp", "w", "l", "ot", "t", "ga", "so", "gaa", "sv_pct", "toi_min")
# Columns every site agrees on; used to decide whether two sources report the same numbers.
CORE_SKATER = ("gp", "g", "a", "pts", "pim")
CORE_GOALIE = ("gp", "w", "l", "so")


def merge_stats(tables: list[dict]) -> dict | None:
    """tables: [{'url','domain','weight', 'regular_season': [...], 'playoffs': [...], 'goalie', 'page_totals'}]"""
    if not tables:
        return None
    goalie = sum(t["goalie"] for t in tables) > len(tables) / 2
    keys = STAT_KEYS_GOALIE if goalie else STAT_KEYS_SKATER
    core = CORE_GOALIE if goalie else CORE_SKATER
    result = {"goalie": goalie, "sources": sorted({t["url"] for t in tables}), "conflicts": []}
    latest_season = max(r["season"] for t in tables for r in t["regular_season"])
    for part in ("regular_season", "playoffs"):
        bucket: dict[tuple, list] = defaultdict(list)
        for t in tables:
            for r in t[part]:
                bucket[(r["season"], r["team"])].append((t, r))
        rows = []
        for (season, team), cands in sorted(bucket.items(), key=lambda kv: kv[0][0]):
            sig: dict[tuple, list] = defaultdict(list)
            for t, r in cands:
                sig[tuple(r.get(k) for k in core)].append((t, r))
            if len(sig) == 1:
                chosen = next(iter(sig))
                status = "confirmed" if len({t["domain"] for t, _ in sig[chosen]}) >= 2 else "single_source"
            elif season == latest_season:
                # season in progress: sites update at different times, so keep the most games played
                chosen = max(sig, key=lambda v: v[0] or 0)
                status = "in_progress_sources_differ"
            else:
                chosen = max(sig, key=lambda v: (sum(t["weight"] for t, _ in sig[v]), len(sig[v])))
                status = "conflict"
                result["conflicts"].append({"part": part, "season": season, "team": team,
                                            "versions": [dict(zip(core, v)) for v in sig]})
            row = {"season": season, "team": team}
            for t, r in sorted(sig[chosen], key=lambda tr: -tr[0]["weight"]):
                for k in keys:
                    if r.get(k) is not None and k not in row:
                        row[k] = r[k]
            row["status"] = status
            row["sources"] = len({t["domain"] for t, _ in sig[chosen]})
            rows.append(row)
        result[part] = rows
        totals = {k: sum(r.get(k) or 0 for r in rows) for k in keys
                  if k not in ("gaa", "sv_pct") and any(k in r for r in rows)}
        if rows and "pts" in totals and totals.get("gp"):
            totals["points_per_game"] = round(totals["pts"] / totals["gp"], 2)
        result[f"{part}_totals"] = totals
    result["page_totals"] = [{"url": t["url"], **t["page_totals"]} for t in tables if t.get("page_totals")]
    result["latest_season"] = latest_season
    return result
