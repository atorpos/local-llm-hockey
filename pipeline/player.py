"""Research one player end to end: search -> fetch -> read -> extract -> verify -> merge -> check."""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path

import jsonschema

from . import normalize as N
from .config import Config, ROOT
from .extract import Extractor
from .fetch import Fetcher
from .merge import merge_bio, merge_contracts, merge_stats, merge_trades
from .search import Searcher
from .stats_tables import parse_tables
from .textprep import chunks_for_llm, html_to_text, mentions
from . import validate

log = logging.getLogger(__name__)
PIPELINE_VERSION = "1.0"
SCHEMA = json.loads((ROOT / "schema" / "player_record.schema.json").read_text())


class PlayerResearcher:
    def __init__(self, cfg: Config, searcher: Searcher, fetcher: Fetcher, extractor: Extractor,
                 debug_dir: Path | None = None):
        self.cfg, self.searcher, self.fetcher, self.extractor = cfg, searcher, fetcher, extractor
        self.debug_dir = debug_dir
        self.skip_llm = cfg.extract.get("skip_llm_domains", [])

    def research(self, name: str, team_hint: str | None = None, urls: list[str] | None = None) -> dict:
        t0 = time.time()
        slug = N.slugify(name)
        pages = [{"url": u, "title": "", "snippet": ""} for u in urls] if urls \
            else self.searcher.find_pages(name, team_hint)
        log.info("%s: %d candidate pages", name, len(pages))

        contracts, trades, bios, tables, sources, skipped = [], [], [], [], [], []
        n_dropped_before = len(self.extractor.dropped)
        max_chars = int(self.cfg.extract["max_chars_per_call"])
        max_calls = int(self.cfg.extract["max_calls_per_page"])

        for i, p in enumerate(pages, 1):
            url = p["url"]
            try:
                page = self.fetcher.get(url)
                if not page:
                    skipped.append({"url": url, "reason": "not fetched (blocked, robots.txt or error)"})
                    continue
                text, meta = html_to_text(page["html"], url)
                if mentions(text, name) < 2:
                    skipped.append({"url": url, "reason": "page barely mentions the player"})
                    continue
                domain, weight = self.cfg.host(url), self.cfg.weight(url)
                used_for = []

                tbl = parse_tables(page["html"])
                if tbl:
                    tables.append({**tbl, "url": url, "domain": domain, "weight": weight})
                    used_for.append("stats")

                if not any(self.cfg._suffix_match(domain, d) for d in self.skip_llm):
                    chunks = chunks_for_llm(text, name, max_chars, max_calls)
                    for ci, chunk in enumerate(chunks):
                        log.info("  [%d/%d] reading %s (part %d/%d, %d chars)", i, len(pages), domain,
                                 ci + 1, len(chunks), len(chunk))
                        raw = self.extractor.run(name, chunk, url, meta.get("published"))
                        if not raw.get("page_is_about_player", False):
                            break
                        ver = self.extractor.verify(raw, text, url)
                        tag = {"_url": url, "_domain": domain, "_weight": weight, "_published": meta.get("published")}
                        contracts += [{**c, **tag} for c in ver["contracts"]]
                        trades += [{**t, **tag} for t in ver["trades"]]
                        if ver["bio"]:
                            bios.append({**ver["bio"], **tag})
                        if ver["contracts"]:
                            used_for.append("contracts")
                        if ver["trades"]:
                            used_for.append("trades")
                        self._debug(slug, f"{i:02d}-{ci}", {"url": url, "raw": raw, "verified": ver})
                sources.append({"url": url, "domain": domain, "title": meta.get("title"),
                                "published": meta.get("published"), "fetched_at": page.get("fetched_at"),
                                "weight": weight, "used_for": sorted(set(used_for))})
            except Exception as e:  # a site with odd HTML must not stop the run
                log.warning("  [%d/%d] %s failed (%s: %s) — page skipped", i, len(pages), url, type(e).__name__, e)
                skipped.append({"url": url, "reason": f"error: {type(e).__name__}: {e}"})

        record = self._build(name, slug, merge_bio(bios), merge_contracts(contracts), merge_trades(trades),
                             merge_stats(tables), sources)
        dropped = self.extractor.dropped[n_dropped_before:]
        record["verification"] = {
            "warnings": validate.check(record),
            "dropped_unverified_items": len(dropped),
            "dropped_examples": [{"kind": d["kind"], "reason": d["reason"], "url": d["url"]} for d in dropped[:5]],
            "pages_read": len(sources),
            "pages_skipped": skipped,
            "seconds": round(time.time() - t0, 1),
        }
        try:
            jsonschema.validate(record, SCHEMA)
            record["verification"]["schema_valid"] = True
        except jsonschema.ValidationError as e:
            record["verification"]["schema_valid"] = False
            record["verification"]["warnings"].append(f"schema: {e.message} at {list(e.absolute_path)}")
        return record

    # ------------------------------------------------------------------ helpers
    def _debug(self, slug, tag, obj):
        if not self.debug_dir:
            return
        d = self.debug_dir / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{tag}.json").write_text(json.dumps(obj, indent=2, default=str))

    def _build(self, name, slug, bio, contracts, trades, stats, sources) -> dict:
        today = date.today().isoformat()
        current_season = N.season_for_date(today)

        # current team = team of the most recent dated event (signing or trade)
        events = [(c["signing_date"], c["team_abbr"]) for c in contracts if c.get("signing_date") and c.get("team_abbr")]
        events += [(t["date"], t["to_abbr"]) for t in trades if t.get("date")]
        cur = max(events)[1] if events else None
        if not cur and stats and stats.get("regular_season"):
            t = stats["regular_season"][-1]["team"]
            cur = t if t in N.TEAMS else None

        teams = []
        for r in (stats or {}).get("regular_season", []):
            nm = N.team_name(r["team"]) or r["team"]
            if nm not in teams:
                teams.append(nm)
        for t in trades:
            for ab in (t["from_abbr"], t["to_abbr"]):
                nm = N.team_name(ab)
                if nm and nm not in teams:
                    teams.append(nm)

        all_seasons = [s for c in contracts for s in c.get("seasons", [])]
        cur_cap = next((c["cap_hit_usd"] for c in contracts if current_season in c.get("seasons", [])), None)
        draft = None
        if any(bio.get(k) for k in ("draft_year", "draft_overall", "draft_team_abbr")):
            draft = {"year": bio.get("draft_year"), "round": bio.get("draft_round"),
                     "overall_pick": bio.get("draft_overall"), "team": N.team_name(bio.get("draft_team_abbr")),
                     "team_abbr": bio.get("draft_team_abbr")}
        return {
            "schema_version": "1.0",
            "player": {"name": name, "slug": slug, "position": bio.get("position"), "shoots": bio.get("shoots"),
                       "birth_date": bio.get("birth_date"), "birthplace": bio.get("birthplace"),
                       "current_team": N.team_name(cur), "current_team_abbr": cur},
            "draft": draft,
            "contracts": contracts,
            "trade_history": trades,
            "career_statistics": stats,
            "summary": {"total_nhl_contracts": len(contracts), "teams_played_for": teams,
                        "times_traded": len(trades),
                        "under_contract_through": max(all_seasons) if all_seasons else None,
                        "current_cap_hit_usd": cur_cap},
            "sources": sources,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "generator": {"pipeline_version": PIPELINE_VERSION, "model": self.extractor.llm.model,
                          "provider": self.extractor.llm.provider},
        }
