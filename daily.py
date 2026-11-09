#!/usr/bin/env python3
"""Hourly/daily NHL game tracker. No AI model needed.

For every finished game it records the game-winning goal, power-play goals, shorthanded goals,
empty-net goals and shutouts, keeps season leaderboards, and saves current standings.

Examples
  python daily.py                                   # yesterday + today (what the hourly job runs)
  python daily.py --from 2026-10-06 --to 2026-11-08 # backfill the season so far
  python daily.py --date 2026-11-08                 # one day
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta

from pipeline.config import Config
from pipeline.games import ET, NHLClient, Store, dates_between, update


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="one game date, YYYY-MM-DD (Eastern time)")
    ap.add_argument("--from", dest="start", help="first date to backfill")
    ap.add_argument("--to", dest="end", help="last date to backfill (default: today)")
    ap.add_argument("--out", default="out/games", help="output folder")
    ap.add_argument("--db", default="data/nhl_games.db", help="SQLite database file")
    ap.add_argument("--no-standings", action="store_true", help="skip the standings snapshot")
    ap.add_argument("--config", help="path to config.toml (for the user agent)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    log = logging.getLogger("daily")

    cfg = Config(args.config)
    today = datetime.now(ET).date()
    if args.date:
        days = [args.date]
    elif args.start:
        days = dates_between(args.start, args.end or today.isoformat())
    else:
        days = [(today - timedelta(days=1)).isoformat(), today.isoformat()]   # late games finish after midnight

    client = NHLClient(cfg.fetch["user_agent"], delay_s=1.0)
    store = Store(cfg.resolve(args.db))
    try:
        s = update(client, store, days, cfg.resolve(args.out), standings=not args.no_standings)
    except Exception as e:
        log.error("update failed: %s: %s", type(e).__name__, e)
        return 1
    log.info("done: %d new final games, %d not finished yet, %d API calls, %d warnings",
             s["new_final_games"], s["in_progress_or_scheduled"], s["api_calls"], len(s["warnings"]))
    for w in s["warnings"]:
        log.warning("%s", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
