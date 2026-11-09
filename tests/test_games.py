"""Tests for the game tracker. Games mirror the layout of the NHL feed (score + boxscore endpoints).
Real results from 2026-11-08 are used where possible; goalie names are placeholders."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.games import Store, analyze, leaders, needs_boxscore, simplify_standings, update  # noqa: E402

_t = [0]


def goal(team, first, last, a, h, strength="ev", period=1, ptype="REG", mod="none", pid=None):
    _t[0] += 61
    return {"period": period, "periodDescriptor": {"number": period, "periodType": ptype},
            "timeInPeriod": f"{(_t[0] // 60) % 20:02d}:{_t[0] % 60:02d}", "playerId": pid or hash(last) % 10**7,
            "name": {"default": f"{first[0]}. {last}"}, "firstName": {"default": first}, "lastName": {"default": last},
            "goalModifier": mod, "teamAbbrev": team, "awayScore": a, "homeScore": h, "strength": strength}


def game(gid, away, home, fa, fh, goals, last="REG", d="2026-11-08"):
    return {"id": gid, "gameDate": d, "gameState": "OFF", "awayTeam": {"abbrev": away, "score": fa},
            "homeTeam": {"abbrev": home, "score": fh}, "gameOutcome": {"lastPeriodType": last}, "goals": goals}


def box(away_goalies, home_goalies):
    mk = lambda gs: [{"playerId": pid, "name": {"default": n}, "toi": toi, "saves": 30, "shotsAgainst": 30}
                     for pid, n, toi in gs]
    return {"playerByGameStats": {"awayTeam": {"goalies": mk(away_goalies)}, "homeTeam": {"goalies": mk(home_goalies)}}}


VGK_BUF = game(2026020278, "VGK", "BUF", 4, 1, [
    goal("VGK", "Mitch", "Marner", 1, 0, "sh"), goal("VGK", "Jack", "Eichel", 2, 0),
    goal("BUF", "Beck", "Malenstyn", 2, 1), goal("VGK", "Tomas", "Hertl", 3, 1), goal("VGK", "Tomas", "Hertl", 4, 1)])
TBL_WPG = game(2026020280, "TBL", "WPG", 3, 4, [
    goal("WPG", "Cole", "Perfetti", 0, 1, "pp"), goal("WPG", "Morgan", "Barron", 0, 2),
    goal("WPG", "Brayden", "Yager", 0, 3, "pp"), goal("TBL", "Brandon", "Hagel", 1, 3, period=2),
    goal("TBL", "Pontus", "Holmberg", 2, 3, period=3), goal("TBL", "Pontus", "Holmberg", 3, 3, period=3),
    goal("WPG", "Mark", "Scheifele", 3, 4, "pp", period=3)])
NJD_TOR = game(2026020279, "NJD", "TOR", 4, 0, [
    goal("NJD", "Timo", "Meier", 1, 0), goal("NJD", "Timo", "Meier", 2, 0),
    goal("NJD", "Nico", "Hischier", 3, 0, "pp"), goal("NJD", "Connor", "Brown", 4, 0, mod="empty-net", period=3)])
PHI_CGY_OT = game(2026020281, "PHI", "CGY", 3, 4, [
    goal("PHI", "Denver", "Barkey", 1, 0), goal("CGY", "Zayne", "Parekh", 1, 1), goal("PHI", "Nick", "Acciari", 2, 1),
    goal("CGY", "Zach", "Whitecloud", 2, 2), goal("PHI", "Owen", "Tippett", 3, 2, "pp"),
    goal("CGY", "Joel", "Farabee", 3, 3, "sh", period=3), goal("CGY", "Matt", "Coronato", 3, 4, period=4, ptype="OT")], "OT")


def test_gwg_regulation_and_overtime():
    assert analyze(VGK_BUF)["game_winning_goal"]["player"] == "Jack Eichel"         # 2nd VGK goal (BUF scored 1)
    r = analyze(TBL_WPG)
    assert r["game_winning_goal"]["player"] == "Mark Scheifele" and r["game_winning_goal"]["strength"] == "pp"
    assert analyze(PHI_CGY_OT)["game_winning_goal"]["player"] == "Matt Coronato"
    assert analyze(PHI_CGY_OT)["decided_in"] == "overtime"
    assert analyze(NJD_TOR, box([(1, "Goalie A", "60:00")], [(2, "Goalie B", "58:30")]))["game_winning_goal"]["player"] == "Timo Meier"


def test_special_teams_and_empty_net():
    r = analyze(TBL_WPG)
    assert [g["player"] for g in r["power_play_goals"]] == ["Cole Perfetti", "Brayden Yager", "Mark Scheifele"]
    assert [g["player"] for g in analyze(VGK_BUF)["shorthanded_goals"]] == ["Mitch Marner"]
    assert [g["player"] for g in analyze(PHI_CGY_OT)["shorthanded_goals"]] == ["Joel Farabee"]
    assert [g["player"] for g in analyze(NJD_TOR)["empty_net_goals"]] == ["Connor Brown"]
    assert analyze(VGK_BUF)["warnings"] == []


def test_shutouts():
    assert needs_boxscore(NJD_TOR) and not needs_boxscore(VGK_BUF)
    r = analyze(NJD_TOR, box([(1, "Goalie A", "60:00"), (3, "Backup", "00:00")], [(2, "Goalie B", "58:30")]))
    assert r["shutouts"] == [{"team": "NJD", "type": "individual", "goalie": "Goalie A", "player_id": 1,
                              "saves": 30, "shots_against": 30, "note": None}]
    shared = analyze(NJD_TOR, box([(1, "Goalie A", "35:00"), (3, "Goalie C", "25:00")], [(2, "Goalie B", "58:30")]))
    assert shared["shutouts"][0]["type"] == "team" and shared["shutouts"][0]["goalie"] is None


def test_shootouts():
    so_00 = game(2026020300, "BOS", "MTL", 1, 0, [goal("BOS", "David", "Pastrnak", 1, 0, period=5, ptype="SO")], "SO")
    r = analyze(so_00, box([(10, "Goalie X", "65:00")], [(11, "Goalie Y", "65:00")]))
    assert r["game_winning_goal"] is None and r["decided_in"] == "shootout" and not r["warnings"]
    assert {s["goalie"] for s in r["shutouts"]} == {"Goalie X", "Goalie Y"}               # both credited at 0-0
    so_32 = game(2026020301, "SEA", "VAN", 3, 2, [goal("SEA", "A", "One", 1, 0), goal("VAN", "B", "Two", 1, 1),
                                                    goal("SEA", "C", "Three", 2, 1), goal("VAN", "D", "Four", 2, 2)], "SO")
    r = analyze(so_32)
    assert r["game_winning_goal"] is None and not r["warnings"] and r["winner"] == "SEA"


def test_incomplete_feed_is_flagged():
    bad = game(2026020302, "DAL", "STL", 2, 1, [goal("DAL", "A", "One", 1, 0)])
    r = analyze(bad)
    assert r["warnings"] and r["game_winning_goal"] is None


def test_leaders_and_standings():
    recs = [analyze(VGK_BUF), analyze(TBL_WPG), analyze(PHI_CGY_OT),
            analyze(NJD_TOR, box([(1, "Goalie A", "60:00")], [(2, "Goalie B", "60:00")]))]
    lb = leaders(recs)
    assert lb["games_counted"] == 4
    assert lb["power_play_goals"][0]["count"] == 1 and len(lb["power_play_goals"]) == 5
    assert lb["shutouts"] == [{"player_id": 1, "goalie": "Goalie A", "team": "NJD", "count": 1}]
    raw = {"standingsDateTimeUtc": "2026-11-09T05:00:00Z", "standings": [
        {"teamAbbrev": {"default": "CAR"}, "teamName": {"default": "Carolina Hurricanes"}, "conferenceName": "Eastern",
         "divisionName": "Metropolitan", "gamesPlayed": 19, "wins": 14, "losses": 3, "otLosses": 2, "points": 30,
         "pointPctg": 0.789474, "regulationWins": 13, "goalFor": 78, "goalAgainst": 45, "goalDifferential": 33,
         "l10Wins": 7, "l10Losses": 2, "l10OtLosses": 1, "streakCode": "W", "streakCount": 2,
         "leagueSequence": 1, "divisionSequence": 1}]}
    st = simplify_standings(raw)
    assert st["teams"][0]["team"] == "CAR" and st["teams"][0]["l10"] == "7-2-1" and st["teams"][0]["streak"] == "W2"


class FakeClient:
    calls = 0

    def __init__(self):
        self.box_calls = 0

    def score(self, d):
        self.calls += 1
        live = game(2026020290, "COL", "CHI", 1, 0, [], d=d)
        live["gameState"] = "LIVE"
        return {"games": [VGK_BUF, NJD_TOR, live]} if d == "2026-11-08" else {"games": []}

    def boxscore(self, gid):
        self.box_calls += 1
        return box([(1, "Goalie A", "60:00")], [(2, "Goalie B", "60:00")])

    def standings(self):
        return {"standings": []}


def test_update_is_idempotent(tmp_path):
    store, client, out = Store(tmp_path / "g.db"), FakeClient(), tmp_path / "out"
    s1 = update(client, store, ["2026-11-07", "2026-11-08"], out)
    assert s1["new_final_games"] == 2 and s1["in_progress_or_scheduled"] == 1 and client.box_calls == 1
    s2 = update(client, store, ["2026-11-08"], out)
    assert s2["new_final_games"] == 0 and client.box_calls == 1            # finished games aren't refetched
    day = json.loads((out / "2026-11-08.json").read_text())
    assert {g["game_id"] for g in day} == {2026020278, 2026020279}
    lb = json.loads((out / "leaders-20262027-regular.json").read_text())
    assert lb["games_counted"] == 2
    assert (out / "standings.json").exists() and (out / "last_run.json").exists()
