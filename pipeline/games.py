"""Game tracker: game-winning, power-play, shorthanded and empty-net goals, shutouts, standings.

Data comes from the NHL's public game feed (api-web.nhle.com). No AI model is involved:
every result is computed by code from the official play data.

Scoring rules applied
- Game-winning goal: the winning team's goal that gives it one more goal than the loser's final total.
  Games decided in a shootout have no individual game-winning goal (the NHL doesn't credit one).
- Shutout: a team allows no goals in regulation + overtime. Credited to the goalie only if he played the
  whole game alone; if two goalies shared it, it is a team shutout. In a 0-0 game decided by a shootout,
  both goalies are credited.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)
API = "https://api-web.nhle.com/v1"
ET = ZoneInfo("America/New_York")
FINAL_STATES = {"OFF", "FINAL"}
GAME_TYPES = {1: "preseason", 2: "regular", 3: "playoffs"}


# --------------------------------------------------------------------------- API client
class NHLClient:
    def __init__(self, user_agent: str, delay_s: float = 1.0, timeout_s: float = 20):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
        self.delay, self.timeout, self._last = delay_s, timeout_s, 0.0
        self.calls = 0

    def get(self, path: str) -> dict:
        for attempt in range(3):
            gap = time.time() - self._last
            if gap < self.delay:
                time.sleep(self.delay - gap)
            self._last = time.time()
            try:
                r = self.s.get(f"{API}/{path}", timeout=self.timeout)
                self.calls += 1
                if r.status_code == 429 or r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, ValueError) as e:
                if attempt == 2:
                    raise
                log.warning("NHL API %s failed (%s), retrying", path, e)
                time.sleep(5 * (attempt + 1))
        raise RuntimeError("unreachable")

    def score(self, d: str) -> dict:
        return self.get(f"score/{d}")

    def boxscore(self, game_id: int) -> dict:
        return self.get(f"gamecenter/{game_id}/boxscore")

    def standings(self) -> dict:
        return self.get("standings/now")


# --------------------------------------------------------------------------- game analysis
def _clock(g: dict) -> tuple[int, int]:
    p = g.get("periodDescriptor", {}).get("number") or g.get("period") or 0
    mm, _, ss = (g.get("timeInPeriod") or "0:0").partition(":")
    return int(p), int(mm or 0) * 60 + int(ss or 0)


def _player(g: dict) -> str:
    first = (g.get("firstName") or {}).get("default")
    last = (g.get("lastName") or {}).get("default")
    return f"{first} {last}" if first and last else (g.get("name") or {}).get("default", "?")


def _goal_row(g: dict) -> dict:
    pd = g.get("periodDescriptor", {})
    return {"player_id": g.get("playerId"), "player": _player(g), "team": g.get("teamAbbrev"),
            "period": pd.get("number", g.get("period")), "period_type": pd.get("periodType", "REG"),
            "time": g.get("timeInPeriod"), "strength": g.get("strength"),
            "modifier": g.get("goalModifier") if g.get("goalModifier") not in (None, "none") else None,
            "score_after": f"{g.get('awayScore')}-{g.get('homeScore')}"}


def is_final(game: dict) -> bool:
    return game.get("gameState") in FINAL_STATES


def needs_boxscore(game: dict) -> bool:
    """Only shutout candidates need the boxscore (to see which goalies played)."""
    goals = [g for g in game.get("goals", []) if g.get("periodDescriptor", {}).get("periodType") != "SO"]
    teams = {game["awayTeam"]["abbrev"], game["homeTeam"]["abbrev"]}
    scored = {g.get("teamAbbrev") for g in goals}
    return bool(teams - scored)


def analyze(game: dict, box: dict | None = None) -> dict:
    away, home = game["awayTeam"]["abbrev"], game["homeTeam"]["abbrev"]
    fa, fh = game["awayTeam"].get("score", 0), game["homeTeam"].get("score", 0)
    last = (game.get("gameOutcome") or {}).get("lastPeriodType") or \
        (game.get("periodDescriptor") or {}).get("periodType", "REG")
    goals = sorted((g for g in game.get("goals", [])
                    if g.get("periodDescriptor", {}).get("periodType") != "SO"), key=_clock)
    n = {away: sum(g.get("teamAbbrev") == away for g in goals), home: sum(g.get("teamAbbrev") == home for g in goals)}
    winner = away if fa > fh else home if fh > fa else None
    loser = home if winner == away else away if winner == home else None
    warnings = []

    # data completeness: goal list must add up to the final score
    if last == "SO":
        if n[away] != n[home] or {fa, fh} != {n[away], n[away] + 1}:
            warnings.append("goal list does not match the shootout final score")
    elif n[away] != fa or n[home] != fh:
        warnings.append(f"goal list has {n[away]}-{n[home]} but final score is {fa}-{fh} (feed incomplete?)")

    gwg = None
    if winner and last != "SO" and not warnings:
        win_goals = [g for g in goals if g.get("teamAbbrev") == winner]
        gwg = _goal_row(win_goals[n[loser]])

    shutouts = []
    for team, opp in ((away, home), (home, away)):
        if n[opp] != 0:
            continue
        side = "awayTeam" if team == away else "homeTeam"
        goalies = (((box or {}).get("playerByGameStats") or {}).get(side) or {}).get("goalies", [])
        played = [gl for gl in goalies if (gl.get("toi") or "00:00") not in ("00:00", "0:00")]
        if not box:
            shutouts.append({"team": team, "type": "unknown", "goalie": None, "player_id": None,
                             "note": "boxscore not loaded"})
        elif len(played) == 1:
            gl = played[0]
            shutouts.append({"team": team, "type": "individual", "goalie": (gl.get("name") or {}).get("default"),
                             "player_id": gl.get("playerId"), "saves": gl.get("saves"),
                             "shots_against": gl.get("shotsAgainst"),
                             "note": "0-0, decided in shootout" if last == "SO" else None})
        else:
            shutouts.append({"team": team, "type": "team", "goalie": None, "player_id": None,
                             "goalies": [(gl.get("name") or {}).get("default") for gl in played],
                             "note": "shared by goalies: credited to the team, not a goalie"})

    gid = game["id"]
    return {
        "game_id": gid,
        "date": game.get("gameDate"),
        "season": f"{gid // 1000000}{gid // 1000000 + 1}",
        "game_type": GAME_TYPES.get((gid // 10000) % 100, "other"),
        "away": away, "home": home, "away_score": fa, "home_score": fh,
        "decided_in": {"REG": "regulation", "OT": "overtime", "SO": "shootout"}.get(last, last),
        "winner": winner,
        "game_winning_goal": gwg,
        "power_play_goals": [_goal_row(g) for g in goals if g.get("strength") == "pp"],
        "shorthanded_goals": [_goal_row(g) for g in goals if g.get("strength") == "sh"],
        "empty_net_goals": [_goal_row(g) for g in goals if g.get("goalModifier") == "empty-net"],
        "shutouts": shutouts,
        "warnings": warnings,
        "source": f"{API}/score/{game.get('gameDate')}",
    }


# --------------------------------------------------------------------------- storage
class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS games (
            game_id INTEGER PRIMARY KEY, game_date TEXT, season TEXT, game_type TEXT,
            record TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS standings (
            taken_at TEXT PRIMARY KEY, record TEXT NOT NULL)""")
        self.db.commit()

    def has_final(self, game_id: int) -> bool:
        row = self.db.execute("SELECT record FROM games WHERE game_id=?", (game_id,)).fetchone()
        return bool(row) and not json.loads(row[0]).get("warnings")

    def save_game(self, rec: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO games VALUES (?,?,?,?,?,?)",
                        (rec["game_id"], rec["date"], rec["season"], rec["game_type"], json.dumps(rec),
                         datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self.db.commit()

    def games_on(self, d: str) -> list[dict]:
        return [json.loads(r[0]) for r in self.db.execute(
            "SELECT record FROM games WHERE game_date=? ORDER BY game_id", (d,))]

    def season_games(self, season: str, game_type: str) -> list[dict]:
        return [json.loads(r[0]) for r in self.db.execute(
            "SELECT record FROM games WHERE season=? AND game_type=? ORDER BY game_date, game_id", (season, game_type))]

    def latest_season(self) -> str | None:
        r = self.db.execute("SELECT season FROM games ORDER BY game_date DESC LIMIT 1").fetchone()
        return r[0] if r else None

    def save_standings(self, rec: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO standings VALUES (?,?)", (rec["taken_at"], json.dumps(rec)))
        self.db.commit()


# --------------------------------------------------------------------------- summaries
def leaders(games: list[dict], top: int = 25) -> dict:
    def tally(rows_key, single=False):
        t: dict = {}
        for g in games:
            rows = [g[rows_key]] if single else g[rows_key]
            for r in rows:
                if not r:
                    continue
                k = (r["player_id"], r["player"], r["team"])
                t[k] = t.get(k, 0) + 1
        ranked = sorted(t.items(), key=lambda kv: (-kv[1], kv[0][1]))[:top]
        return [{"player_id": k[0], "player": k[1], "team": k[2], "count": v} for k, v in ranked]

    so: dict = {}
    team_so: dict = {}
    for g in games:
        for s in g["shutouts"]:
            if s["type"] == "individual":
                k = (s["player_id"], s["goalie"], s["team"])
                so[k] = so.get(k, 0) + 1
            elif s["type"] == "team":
                team_so[s["team"]] = team_so.get(s["team"], 0) + 1
    return {
        "games_counted": len(games),
        "game_winning_goals": tally("game_winning_goal", single=True),
        "power_play_goals": tally("power_play_goals"),
        "shorthanded_goals": tally("shorthanded_goals"),
        "empty_net_goals": tally("empty_net_goals"),
        "shutouts": [{"player_id": k[0], "goalie": k[1], "team": k[2], "count": v}
                     for k, v in sorted(so.items(), key=lambda kv: (-kv[1], kv[0][1]))[:top]],
        "team_shutouts_shared": [{"team": t, "count": c} for t, c in sorted(team_so.items(), key=lambda kv: -kv[1])],
    }


def simplify_standings(raw: dict) -> dict:
    rows = []
    for t in raw.get("standings", []):
        rows.append({
            "team": t["teamAbbrev"]["default"], "name": t["teamName"]["default"],
            "conference": t.get("conferenceName"), "division": t.get("divisionName"),
            "gp": t.get("gamesPlayed"), "w": t.get("wins"), "l": t.get("losses"), "otl": t.get("otLosses"),
            "pts": t.get("points"), "pts_pct": t.get("pointPctg"), "regulation_wins": t.get("regulationWins"),
            "gf": t.get("goalFor"), "ga": t.get("goalAgainst"), "diff": t.get("goalDifferential"),
            "l10": f"{t.get('l10Wins')}-{t.get('l10Losses')}-{t.get('l10OtLosses')}",
            "streak": f"{t.get('streakCode', '')}{t.get('streakCount', '')}",
            "league_rank": t.get("leagueSequence"), "division_rank": t.get("divisionSequence"),
        })
    rows.sort(key=lambda r: r["league_rank"] or 99)
    return {"taken_at": raw.get("standingsDateTimeUtc") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "teams": rows}


# --------------------------------------------------------------------------- run
def dates_between(start: str, end: str) -> list[str]:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def update(client: NHLClient, store: Store, days: list[str], out: Path, standings: bool = True) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    summary = {"run_at": datetime.now(ET).isoformat(timespec="seconds"), "dates": days,
               "new_final_games": 0, "in_progress_or_scheduled": 0, "warnings": []}
    for d in days:
        data = client.score(d)
        for game in data.get("games", []):
            if game.get("gameDate") and game["gameDate"] != d:
                continue
            if not is_final(game):
                summary["in_progress_or_scheduled"] += 1
                continue
            if store.has_final(game["id"]):
                continue
            box = client.boxscore(game["id"]) if needs_boxscore(game) else None
            rec = analyze(game, box)
            store.save_game(rec)
            summary["new_final_games"] += 1
            for w in rec["warnings"]:
                summary["warnings"].append(f"{rec['away']}@{rec['home']} {d}: {w}")
            log.info("%s %s %d-%d %s  GWG: %s  PPG: %d  SHG: %d  shutouts: %s", d, f"{rec['away']}@{rec['home']}",
                     rec["away_score"], rec["home_score"], rec["decided_in"],
                     rec["game_winning_goal"]["player"] if rec["game_winning_goal"] else "—",
                     len(rec["power_play_goals"]), len(rec["shorthanded_goals"]),
                     ", ".join(s["goalie"] or f"{s['team']} (team)" for s in rec["shutouts"]) or "—")
        games_today = store.games_on(d)
        if games_today:
            (out / f"{d}.json").write_text(json.dumps(games_today, indent=2, ensure_ascii=False))

    season = store.latest_season()
    if season:
        for gt in ("regular", "playoffs"):
            gs = store.season_games(season, gt)
            if gs:
                (out / f"leaders-{season}-{gt}.json").write_text(json.dumps(leaders(gs), indent=2, ensure_ascii=False))
    if standings:
        st = simplify_standings(client.standings())
        store.save_standings(st)
        (out / "standings.json").write_text(json.dumps(st, indent=2, ensure_ascii=False))
    summary["api_calls"] = client.calls
    (out / "last_run.json").write_text(json.dumps(summary, indent=2))
    return summary
