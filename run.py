#!/usr/bin/env python3
"""Research NHL players with a local model and export JSON.

Examples
  python run.py --check
  python run.py --players "Nazem Kadri"
  python run.py --players "Cale Makar" "Nazem Kadri" --name test
  python run.py --players-file players.txt --name avalanche
  python run.py --team "Colorado Avalanche"
  python run.py --players "Nazem Kadri" --dry-run      # search + fetch only, no model

Whole league
  python run.py --build-league-list league.txt         # 32 rosters -> one player list (review it)
  caffeinate -i python run.py --players-file league.txt --name league
  # two Macs: --shard 1/2 on one, --shard 2/2 on the other, then combine (see README)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from pipeline import normalize as N
from pipeline.config import Config
from pipeline.export import write_bundle, write_player, write_report
from pipeline.extract import Extractor
from pipeline.fetch import Fetcher
from pipeline.llm import LLMError, LocalLLM
from pipeline.player import PlayerResearcher
from pipeline.roster import roster_from_wikipedia
from pipeline.search import Searcher


def read_players_file(path: str) -> list[tuple[str, str | None]]:
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, _, hint = line.partition("|")
        out.append((name.strip(), hint.strip() or None))
    return out


def build_league_list(path: Path, fetcher: Fetcher, log) -> int:
    lines, missing, seen = [], [], set()
    for abbr in N.CURRENT_TEAMS:
        team = N.team_name(abbr)
        names = roster_from_wikipedia(team, fetcher)
        log.info("%-24s %2d players", team, len(names))
        if not names:
            missing.append(team)
            lines.append(f"# {team}: roster not found on Wikipedia — add players by hand: Name | {team}")
            continue
        lines.append(f"# {team}")
        for nm in names:
            if nm.lower() not in seen:
                seen.add(nm.lower())
                lines.append(f"{nm} | {team}")
    path.write_text("\n".join(lines) + "\n")
    log.info("wrote %s: %d players from %d teams%s", path, len(seen), 32 - len(missing),
             f" — {len(missing)} rosters missing, see '#' lines" if missing else "")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", nargs="*", default=[], help="player names")
    ap.add_argument("--players-file", help="text file, one player per line, optional '| team hint'")
    ap.add_argument("--team", help="research a team's current roster (from Wikipedia)")
    ap.add_argument("--name", help="name for the bundle/report files (default: team or 'players')")
    ap.add_argument("--out", default="out", help="output folder")
    ap.add_argument("--format", choices=["json", "ndjson", "both"], default="both")
    ap.add_argument("--config", help="path to config.toml")
    ap.add_argument("--model", help="override the model in config.toml")
    ap.add_argument("--force", action="store_true", help="re-research players that already have output")
    ap.add_argument("--dry-run", action="store_true", help="search and fetch only; show which pages would be read")
    ap.add_argument("--debug", action="store_true", help="save raw model answers to out/debug/")
    ap.add_argument("--check", action="store_true", help="check that SearXNG and the model server respond")
    ap.add_argument("--build-league-list", metavar="FILE",
                    help="read all 32 current rosters from Wikipedia, write a players file, and stop")
    ap.add_argument("--shard", metavar="K/N", help="only do every N-th player starting at K (split across Macs)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("urllib3", "trafilatura", "htmldate", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    log = logging.getLogger("run")

    cfg = Config(args.config)
    out = cfg.resolve(args.out)
    out.mkdir(parents=True, exist_ok=True)
    llm = LocalLLM(cfg, model=args.model)
    searcher, fetcher = Searcher(cfg), Fetcher(cfg)

    if args.build_league_list:
        return build_league_list(Path(args.build_league_list), fetcher, log)

    if args.check or not args.dry_run:
        try:
            log.info(llm.check())
        except LLMError as e:
            log.error("%s", e)
            return 1
        hits = searcher.search("Colorado Avalanche")
        if not hits:
            log.error("SearXNG returned no results at %s — is it running? (docker compose up -d)",
                      cfg.search["searxng_url"])
            return 1
        log.info("SearXNG OK (%d results for a test query)", len(hits))
        if args.check:
            return 0

    players: list[tuple[str, str | None]] = [(p, None) for p in args.players]
    if args.players_file:
        players += read_players_file(args.players_file)
    if args.team:
        names = roster_from_wikipedia(args.team, fetcher)
        if not names:
            log.error("could not read the roster for %s — use --players-file instead", args.team)
            return 1
        log.info("roster: %d players", len(names))
        players += [(n, args.team) for n in names]
    if not players:
        ap.error("give --players, --players-file or --team")
    bundle = args.name or (N.slugify(args.team) if args.team else "players")
    if args.shard:
        try:
            k, n = (int(x) for x in args.shard.split("/"))
            assert 1 <= k <= n
        except (ValueError, AssertionError):
            ap.error("--shard must look like 1/2")
        players = players[k - 1::n]
        bundle = f"{bundle}-shard{k}of{n}"
        log.info("shard %d/%d: %d players", k, n, len(players))

    if args.dry_run:
        for name, hint in players:
            pages = searcher.find_pages(name, hint)
            print(f"\n{name}:")
            for p in pages:
                ok = fetcher.get(p["url"]) is not None
                print(f"  {'OK ' if ok else '-- '} {p['score']:5.1f}  {p['url']}")
        return 0

    extractor = Extractor(llm, cfg)
    researcher = PlayerResearcher(cfg, searcher, fetcher, extractor,
                                  debug_dir=out / "debug" if args.debug else None)
    records, failed, durations = [], [], []
    t0 = time.time()
    todo = [(nm, h) for nm, h in players
            if args.force or not (out / "players" / f"{N.slugify(nm)}.json").exists()]
    log.info("%d players: %d already done, %d to research", len(players), len(players) - len(todo), len(todo))
    remaining = len(todo)
    for k, (name, hint) in enumerate(players, 1):
        existing = out / "players" / f"{N.slugify(name)}.json"
        if existing.exists() and not args.force:
            records.append(json.loads(existing.read_text()))
            continue
        log.info("[%d/%d] researching %s", k, len(players), name)
        started = time.time()
        try:
            rec = researcher.research(name, hint)
        except KeyboardInterrupt:
            log.warning("stopped — finished players are saved; rerun the same command to continue")
            break
        except Exception as e:  # never let one player stop an overnight run
            log.error("  %s failed (%s: %s) — skipped; rerun later to retry", name, type(e).__name__, e)
            failed.append(name)
            remaining -= 1
            continue
        if rec["verification"]["pages_read"] == 0:
            # nothing could be read (search down, every site blocked): don't mark the player as done
            log.error("  %s: no pages could be read — not saved; rerun later to retry", name)
            failed.append(name)
            remaining -= 1
            continue
        p = write_player(rec, out)
        v = rec["verification"]
        durations.append(time.time() - started)
        remaining -= 1
        avg = sum(durations) / len(durations)
        log.info("  saved %s  (%d contracts, %d trades, %d stat seasons, %d warnings, %.1f min) — "
                 "%d left, about %.1f h to go",
                 p.name, len(rec["contracts"]), len(rec["trade_history"]),
                 len((rec.get("career_statistics") or {}).get("regular_season", [])),
                 len(v["warnings"]), v["seconds"] / 60, remaining, remaining * avg / 3600)
        records.append(rec)
    if failed:
        (out / f"{bundle}-failed.txt").write_text("".join(f"{n}\n" for n in failed))
        log.warning("%d players failed — listed in %s-failed.txt", len(failed), bundle)

    if records:
        paths = write_bundle(records, out, bundle, args.format)
        rep = write_report(records, out, bundle, llm.usage, fetcher.stats)
        log.info("done in %.1f min → %s, %s", (time.time() - t0) / 60, ", ".join(p.name for p in paths), rep.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
