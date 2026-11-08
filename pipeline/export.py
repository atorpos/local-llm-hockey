"""Write per-player JSON, a team bundle, NDJSON for bulk import, and a readable run report."""
from __future__ import annotations

import json
from pathlib import Path


def clean(obj):
    """Drop internal keys (starting with '_') before export."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    return obj


def write_player(rec: dict, out: Path) -> Path:
    d = out / "players"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{rec['player']['slug']}.json"
    p.write_text(json.dumps(clean(rec), indent=2, ensure_ascii=False))
    return p


def write_bundle(records: list[dict], out: Path, name: str, fmt: str) -> list[Path]:
    paths = []
    if fmt in ("json", "both"):
        p = out / f"{name}.json"
        p.write_text(json.dumps([clean(r) for r in records], indent=2, ensure_ascii=False))
        paths.append(p)
    if fmt in ("ndjson", "both"):
        p = out / f"{name}.ndjson"
        p.write_text("".join(json.dumps(clean(r), ensure_ascii=False) + "\n" for r in records))
        paths.append(p)
    return paths


def write_report(records: list[dict], out: Path, name: str, llm_usage: dict, fetch_stats: dict) -> Path:
    lines = [f"# Run report: {name}", ""]
    lines.append(f"- Players: {len(records)}")
    lines.append(f"- Model calls: {llm_usage['calls']}, tokens in/out: {llm_usage['prompt_tokens']:,} / "
                 f"{llm_usage['output_tokens']:,}, model time: {llm_usage['seconds'] / 60:.1f} min")
    lines.append(f"- Pages fetched: {fetch_stats['fetched']}, from cache: {fetch_stats['cached']}, "
                 f"blocked by robots.txt: {fetch_stats['robots_blocked']}, errors: {fetch_stats['errors']}")
    lines.append("")
    lines.append("| Player | Contracts (confirmed / single / conflict) | Trades | Stat seasons | Dropped | Warnings | Time |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in records:
        cs = r["contracts"]
        cnt = lambda s: sum(c["status"] == s for c in cs)
        st = r.get("career_statistics") or {}
        v = r["verification"]
        lines.append(f"| {r['player']['name']} | {len(cs)} ({cnt('confirmed')} / {cnt('single_source')} / "
                     f"{cnt('conflict')}) | {len(r['trade_history'])} | {len(st.get('regular_season', []))} | "
                     f"{v['dropped_unverified_items']} | {len(v['warnings'])} | {v.get('seconds', 0) / 60:.1f} min |")
    for r in records:
        w = r["verification"]["warnings"]
        if w:
            lines += ["", f"## {r['player']['name']}", ""] + [f"- {x}" for x in w]
    p = out / f"{name}-report.md"
    p.write_text("\n".join(lines) + "\n")
    return p
