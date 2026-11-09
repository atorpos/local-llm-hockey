#!/usr/bin/env python3
"""Score a pipeline output against a hand-checked reference file.

  python compare_reference.py out/players/nazem-kadri.json reference/nazem_kadri_contract_trade_stats.json
  python compare_reference.py --all        # every reference file that has a matching output
  python compare_reference.py --all out-gemma4   # same, for a run saved with --out out-gemma4
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REF_TO_SLUG = {
    "cale_makar_contract_trade_history.json": "cale-makar",
    "patrick_kane_contract_trade_history.json": "patrick-kane",
    "connor_hellebuyck_contract_trade_history.json": "connor-hellebuyck",
    "nazem_kadri_contract_trade_stats.json": "nazem-kadri",
}


def _cap(c):
    return c.get("cap_hit_usd", c.get("cap_hit"))


def _total(c):
    return c.get("total_value_usd", c.get("total_value"))


def _close(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol * max(a, b)


def compare(out: dict, ref: dict) -> list[tuple[str, bool, str]]:
    res = []
    # contracts: each reference contract should appear with the same term and cap hit
    for rc in ref.get("contracts", []):
        label = f"contract {rc.get('contract_number')} ({rc.get('team', '')[:22]}, {rc.get('term_years')} yr)"
        match = [c for c in out.get("contracts", [])
                 if c.get("term_years") == rc.get("term_years") and _close(_cap(c), _cap(rc))]
        if match:
            m = match[0]
            tot_ok = _total(rc) is None or _total(m) is None or _close(_total(m), _total(rc))
            res.append((label, tot_ok, "term + cap hit match" + ("" if tot_ok else f", total differs ({_total(m):,} vs {_total(rc):,})")))
        else:
            res.append((label, False, "not found with same term and cap hit"))
    extra = len(out.get("contracts", [])) - len(ref.get("contracts", []))
    if extra > 0:
        res.append(("extra contracts", False, f"{extra} contract(s) not in the reference — possible duplicates or errors"))

    # trades by date (month precision)
    for rt in ref.get("trade_history", []):
        d = rt.get("date", "")[:7]
        ok = any((t.get("date") or "")[:7] == d for t in out.get("trade_history", []))
        res.append((f"trade {rt.get('date')}", ok, "found" if ok else "missing or wrong date"))
    if not ref.get("trade_history"):
        ok = not out.get("trade_history")
        res.append(("no trades", ok, "correct" if ok else f"output lists {len(out['trade_history'])} trade(s)"))

    # stats totals
    rs = (ref.get("career_statistics") or {}).get("regular_season_totals")
    os_ = (out.get("career_statistics") or {}).get("regular_season_totals")
    if rs:
        if not os_:
            res.append(("career stats", False, "no stats in output"))
        else:
            for k in ("gp", "g", "a", "pts"):
                ok = rs.get(k) == os_.get(k)
                res.append((f"career {k.upper()}", ok, f"{os_.get(k)} vs reference {rs.get(k)}"
                            + ("" if ok else " (a current-season difference is normal)")))
    return res


def report(out_path: Path, ref_path: Path) -> tuple[int, int]:
    if not out_path.exists():
        print(f"No output file at {out_path}: the run did not finish. Check the run.py log above.")
        return 0, 0
    out, ref = json.loads(out_path.read_text()), json.loads(ref_path.read_text())
    rows = compare(out, ref)
    print(f"\n{out['player']['name']}  ({out_path.name} vs {ref_path.name})")
    for label, ok, note in rows:
        print(f"  {'PASS' if ok else 'FAIL'}  {label:45s} {note}")
    passed = sum(ok for _, ok, _ in rows)
    print(f"  score: {passed}/{len(rows)}")
    return passed, len(rows)


def main():
    if sys.argv[1:2] == ["--all"]:
        out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "out"
        if not out_dir.is_absolute():
            out_dir = ROOT / out_dir
        tp = tt = 0
        for ref_name, slug in REF_TO_SLUG.items():
            o = out_dir / "players" / f"{slug}.json"
            if o.exists():
                p, t = report(o, ROOT / "reference" / ref_name)
                tp, tt = tp + p, tt + t
        print(f"\nOVERALL: {tp}/{tt}")
        return
    if len(sys.argv) == 3:
        report(Path(sys.argv[1]), Path(sys.argv[2]))
        return
    print(__doc__)


if __name__ == "__main__":
    main()
