"""Offline tests: run with  python -m pytest -q  (no internet or model needed)."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import normalize as N                                   # noqa: E402
from pipeline.config import Config                                    # noqa: E402
from pipeline.extract import Extractor                                # noqa: E402
from pipeline.fetch import Fetcher                                    # noqa: E402
from pipeline.llm import LocalLLM                                     # noqa: E402
from pipeline.player import PlayerResearcher                          # noqa: E402
from pipeline.roster import parse_roster                              # noqa: E402
from pipeline.search import Searcher                                  # noqa: E402
from pipeline.stats_tables import parse_tables                        # noqa: E402
from pipeline.export import write_player, write_bundle, write_report  # noqa: E402
from tests import fixtures as F                                       # noqa: E402
from tests import mocks                                               # noqa: E402
import compare_reference                                              # noqa: E402


def make_cfg(tmp_path, **over) -> Config:
    raw = (ROOT / "config.toml").read_text()
    for key, val in over.items():
        raw = re.sub(rf"^{key}\s*=.*$", f"{key} = {val}", raw, count=1, flags=re.M)
    p = tmp_path / "config.toml"
    p.write_text(raw)
    return Config(p)


# ----------------------------------------------------------------- normalisation
def test_teams():
    assert N.team_abbr("Colorado Avalanche") == "COL"
    assert N.team_abbr("Avalanche") == "COL"
    assert N.team_abbr("the Flames") == "CGY"
    assert N.team_abbr("Montréal Canadiens") == "MTL"
    assert N.team_abbr("Minnesota North Stars") == "MNS"
    assert N.team_abbr("Minnesota") == "MIN"
    assert N.team_abbr("NJ") == "NJD"
    assert N.team_abbr("St. Louis Blues") == "STL"
    assert N.team_abbr("London Knights") is None


def test_seasons_and_dates():
    assert N.season("2026–27") == "2026-27"
    assert N.season("2026-2027") == "2026-27"
    assert N.season("1999-00") == "1999-00"
    assert N.season("2026-29") is None
    assert N.season_add("2027-28", 7) == "2034-35"
    assert N.season_for_date("2026-03-06") == "2025-26"
    assert N.season_for_date("2022-08-18") == "2022-23"
    assert N.norm_date("March 6, 2026") == "2026-03-06"
    assert N.norm_date("Aug. 18, 2022") == "2022-08-18"
    assert N.norm_date("September 2013") == "2013-09"
    assert N.norm_date("2009") == "2009"
    assert N.norm_date("nonsense") is None


def test_money_and_terms():
    t = "a seven-year, $49 million deal; AAV $7,000,000; $9-million; 20.4M per season; 6 year extension"
    m = N.money_mentions(t)
    assert {49_000_000, 7_000_000, 9_000_000, 20_400_000} <= m
    assert N.money_supported(6_166_666, {6_170_000}, 0.01)
    assert not N.money_supported(2_950_000, {2_900_000, 5_800_000}, 0.01)
    assert N.term_mentions(t) >= {7, 6}


# ----------------------------------------------------------------- stats tables
def test_wikipedia_table():
    t = parse_tables(F.wiki_page())
    assert t and not t["goalie"]
    reg = t["regular_season"]
    assert all(r["season"] >= "2009-10" for r in reg), "OHL rows must be dropped"
    assert len(reg) == 19
    assert sum(r["gp"] for r in reg) == 1078 and sum(r["pts"] for r in reg) == 774
    assert sum(r["gp"] for r in t["playoffs"]) == 65
    assert t["page_totals"]["regular"]["gp"] == 1078
    assert {r["team"] for r in reg} == {"TOR", "COL", "CGY"}


def test_hockeydb_table():
    t = parse_tables(F.hockeydb_page())
    assert len(t["regular_season"]) == 19
    assert t["regular_season"][0]["plus_minus"] == -1


def test_roster_parse():
    html = """<table><tr><th>No.</th><th>Nat</th><th>Player</th><th>Pos</th><th>Age</th></tr>
    <tr><td>8</td><td>CAN</td><td>Makar, Cale (A)</td><td>D</td><td>28</td></tr>
    <tr><td>91</td><td>CAN</td><td>Kadri, Nazem</td><td>C</td><td>36</td></tr></table>"""
    assert parse_roster(html) == ["Cale Makar", "Nazem Kadri"]


# ----------------------------------------------------------------- fetcher politeness
def test_fetcher_rules(tmp_path):
    srv, base = mocks.start_site()
    try:
        cfg = make_cfg(tmp_path, cache_dir=f'"{tmp_path / "cache"}"', min_delay_per_domain_s=0.6)
        f = Fetcher(cfg)
        mocks.SiteHandler.hits.clear()
        assert f.get(base + "/private/secret") is None                 # robots.txt
        t0 = time.time()
        assert f.get(base + "/a") and f.get(base + "/b")
        assert time.time() - t0 >= 0.55                                 # per-site delay
        assert f.get(base + "/file.pdf") is None                        # not HTML
        n = len(mocks.SiteHandler.hits)
        assert f.get(base + "/a")["from_cache"] and len(mocks.SiteHandler.hits) == n   # cache
        assert f.get(base + "/slow-down") is None                       # 429 ...
        assert f.get(base + "/c") is None                               # ... cools the site down
        assert "/private/secret" not in mocks.SiteHandler.hits
        page = Fetcher(make_cfg(tmp_path, cache_dir=f'"{tmp_path / "cache2"}"', min_delay_per_domain_s=0)).get(base + "/nocharset")
        assert page and "Kadri" in page["html"]                        # regression: streamed body decode
    finally:
        srv.shutdown()


# ----------------------------------------------------------------- end to end
class FixtureFetcher(Fetcher):
    def get(self, url):
        if url in F.PAGES:
            return {"url": url, "final_url": url, "status": 200, "fetched_at": "2026-11-08T00:00:00+00:00",
                    "html": F.PAGES[url](), "from_cache": False}
        return None


@pytest.fixture()
def servers():
    o, ourl = mocks.start_ollama()
    s, surl = mocks.start_searxng()
    mocks.OllamaHandler.calls.clear()
    yield ourl, surl
    o.shutdown()
    s.shutdown()


def test_end_to_end_kadri(tmp_path, servers):
    ourl, surl = servers
    cfg = make_cfg(tmp_path, base_url=f'"{ourl}"', searxng_url=f'"{surl}"', delay_between_searches_s=0,
                   cache_dir=f'"{tmp_path / "cache"}"')
    llm = LocalLLM(cfg)
    assert "OK" in llm.check()
    searcher = Searcher(cfg)
    pages = searcher.find_pages("Nazem Kadri")
    urls = [p["url"] for p in pages]
    assert not any("hockey-reference" in u or "amazon" in u for u in urls), "blocked sites must be skipped"
    assert any("wikipedia" in u for u in urls) and any("hockeydb" in u for u in urls), "stats pages reserved"

    ex = Extractor(llm, cfg)
    rec = PlayerResearcher(cfg, searcher, FixtureFetcher(cfg), ex, debug_dir=tmp_path / "debug").research("Nazem Kadri")
    v = rec["verification"]
    assert v["schema_valid"], v["warnings"]

    # model is never called for hockeydb (tables read by code) or the unrelated recap
    called = {re.search(r"^Page: (\S+)", c["messages"][1]["content"], re.M).group(1) for c in mocks.OllamaHandler.calls}
    assert not any("hockeydb" in u or "makar-game" in u for u in called)
    assert all(c.get("think") is False for c in mocks.OllamaHandler.calls)

    # hallucinated extension dropped; wrong numbers removed
    assert v["dropped_unverified_items"] >= 1
    assert not any(c["team_abbr"] == "COL" for c in rec["contracts"])
    cs = {(c["team_abbr"], c["term_years"]): c for c in rec["contracts"]}
    assert len(rec["contracts"]) == 5
    flames = cs[("CGY", 7)]
    assert flames["status"] == "confirmed" and flames["cap_hit_usd"] == 7_000_000
    assert flames["seasons"][0] == "2022-23" and flames["seasons"][-1] == "2028-29"
    assert len(flames["sources"]) == 3
    two = cs[("TOR", 2)]
    assert two["cap_hit_usd"] == 2_900_000 and "cap_hit_usd" in two["derived_fields"]
    six = cs[("TOR", 6)]
    assert six["first_season"] == "2016-17"                       # follows the 1-year deal
    assert [c["contract_number"] for c in rec["contracts"]] == [1, 2, 3, 4, 5]
    assert rec["contracts"][0]["contract_type"] == "entry_level"

    # trades merged across sources
    tr = rec["trade_history"]
    assert [t["date"] for t in tr] == ["2019-07-01", "2026-03-06"]
    assert all(t["status"] == "confirmed" for t in tr)
    assert tr[0]["salary_retained_pct"] is None                   # 50 % was not on the page
    assert tr[1]["salary_retained_pct"] == 20
    assert "Victor Olofsson" in tr[1]["old_team_received"]        # most complete source kept

    # stats: two sources, current season differs, +/- filled from the second site
    st = rec["career_statistics"]
    assert st["regular_season_totals"]["gp"] == 1078 and st["regular_season_totals"]["pts"] == 774
    assert st["playoffs_totals"]["pts"] == 53
    cur = [r for r in st["regular_season"] if r["season"] == "2026-27"][0]
    assert cur["gp"] == 16 and cur["status"] == "in_progress_sources_differ"
    assert st["regular_season"][0]["status"] == "confirmed" and st["regular_season"][0]["plus_minus"] == -1

    assert rec["player"]["current_team_abbr"] == "COL"
    assert rec["draft"] == {"year": 2009, "round": 1, "overall_pick": 7, "team": "Toronto Maple Leafs", "team_abbr": "TOR"}
    assert rec["player"]["birth_date"] == "1990-10-06"
    assert rec["summary"]["times_traded"] == 2 and rec["summary"]["under_contract_through"] == "2028-29"
    assert not any("no trade found" in w for w in v["warnings"])

    # export + compare with the hand-checked reference file
    out = tmp_path / "out"
    p = write_player(rec, out)
    assert "_url" not in p.read_text()
    paths = write_bundle([rec], out, "test", "both")
    assert len(paths[1].read_text().strip().splitlines()) == 1
    write_report([rec], out, "test", llm.usage, {"fetched": 0, "cached": 0, "robots_blocked": 0, "errors": 0})
    rows = compare_reference.compare(json.loads(p.read_text()),
                                     json.loads((ROOT / "reference" / "nazem_kadri_contract_trade_stats.json").read_text()))
    failed = [r for r in rows if not r[1]]
    assert not failed, failed


def test_lmstudio_provider_and_retry(tmp_path):
    srv, url = mocks.start_openai()
    try:
        cfg = make_cfg(tmp_path, provider='"openai"', base_url=f'"{url}/v1"')
        llm = LocalLLM(cfg, model="qwen3-8b-mlx")
        assert "OK" in llm.check()
        out = llm.json_call("sys", "user", {"type": "object"})
        assert out["page_is_about_player"] is False and llm.usage["calls"] == 2
    finally:
        srv.shutdown()
