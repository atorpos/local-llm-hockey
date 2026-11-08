"""Ask the local model to pull contract / trade / bio facts from one page, then verify them
against the page text so invented values are dropped."""
from __future__ import annotations

import logging
import re
from datetime import date

from rapidfuzz import fuzz

from . import normalize as N
from .llm import LocalLLM, LLMError

log = logging.getLogger(__name__)

S = {"type": ["string", "null"]}
I = {"type": ["integer", "null"]}
NUM = {"type": ["number", "null"]}

EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["page_is_about_player", "bio", "contracts", "trades"],
    "properties": {
        "page_is_about_player": {"type": "boolean"},
        "bio": {
            "type": "object", "additionalProperties": False,
            "required": ["position", "shoots", "birth_date", "birthplace", "draft_year", "draft_round",
                         "draft_overall", "draft_team", "evidence"],
            "properties": {"position": S, "shoots": S, "birth_date": S, "birthplace": S, "draft_year": I,
                           "draft_round": I, "draft_overall": I, "draft_team": S, "evidence": S},
        },
        "contracts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["team", "contract_type", "signing_date", "first_season", "term_years",
                         "total_value_usd", "cap_hit_usd", "clauses", "evidence"],
            "properties": {
                "team": S,
                "contract_type": {"type": "string",
                                  "enum": ["entry_level", "extension", "rfa", "ufa", "unknown"]},
                "signing_date": S, "first_season": S, "term_years": I,
                "total_value_usd": I, "cap_hit_usd": I,
                "clauses": {"type": "array", "items": {"type": "string"}},
                "evidence": {"type": "string"},
            }}},
        "trades": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["date", "from_team", "to_team", "new_team_received", "old_team_received",
                         "salary_retained_pct", "evidence"],
            "properties": {
                "date": S, "from_team": S, "to_team": S,
                "new_team_received": {"type": "array", "items": {"type": "string"}},
                "old_team_received": {"type": "array", "items": {"type": "string"}},
                "salary_retained_pct": NUM,
                "evidence": {"type": "string"},
            }}},
    },
}

SYSTEM = ("You extract NHL contract and trade facts about ONE player from ONE web page. "
          "Use only the page text. Never use outside knowledge. If a value is not written in the text, "
          "use null. For every contract and trade, copy one exact sentence from the page into 'evidence'.")

PROMPT = """Player: {name}
Today's date: {today}
Page: {url}
Page published: {published}

Rules:
- Only contracts signed by {name} himself. Ignore other players' contracts.
- Money is whole US dollars: "$54 million" -> 54000000, "$9M" -> 9000000, "$880,833" -> 880833.
- cap_hit_usd is the cap hit / AAV per season. total_value_usd is the full contract value.
- term_years is the number of seasons (an "eight-year deal" -> 8).
- first_season only if the page says which season it starts, written like 2027-28.
- signing_date as YYYY-MM-DD if the full date is given, else YYYY-MM or YYYY, else null.
- contract_type: entry_level, extension, rfa, ufa, or unknown.
- clauses: short phrases such as "full no-movement clause" or "modified no-trade clause (10-team list)".
- trades: only trades that moved {name} from one team to another. new_team_received = what {name}'s
  new team got (including {name}); old_team_received = what his old team got. Write picks like
  "2027 4th-round pick". salary_retained_pct is the percent the old team kept, if stated.
- If the page is not about {name}, set page_is_about_player to false and return empty lists.

PAGE TEXT:
<<<
{text}
>>>"""


class Extractor:
    def __init__(self, llm: LocalLLM, cfg):
        self.llm = llm
        self.threshold = float(cfg.extract["evidence_match_threshold"])
        self.tol = float(cfg.extract["money_tolerance"])
        self.dropped: list[dict] = []

    def run(self, name: str, chunk: str, url: str, published: str | None) -> dict:
        user = PROMPT.format(name=name, today=date.today().isoformat(), url=url,
                             published=published or "unknown", text=chunk)
        try:
            return self.llm.json_call(SYSTEM, user, EXTRACTION_SCHEMA)
        except LLMError as e:
            log.warning("extraction failed for %s: %s", url, e)
            return {"page_is_about_player": False, "bio": {}, "contracts": [], "trades": []}

    # ---------------------------------------------------------------- verification
    def _evidence_ok(self, evidence: str | None, page_norm: str) -> bool:
        if not evidence or len(evidence) < 15:
            return False
        ev = N.text_norm(evidence)
        if ev in page_norm:
            return True
        return fuzz.partial_ratio(ev, page_norm) >= self.threshold

    def _drop(self, kind, item, reason, url):
        self.dropped.append({"kind": kind, "reason": reason, "url": url, "item": item})

    def verify(self, raw: dict, page_text: str, url: str) -> dict:
        """Keep only facts that the page really contains."""
        page_norm = N.text_norm(page_text)
        monies = N.money_mentions(page_text)
        terms = N.term_mentions(page_text)
        years = set(re.findall(r"\b(?:19|20)\d{2}\b", page_text))
        notes: list[str] = []
        out = {"contracts": [], "trades": [], "bio": {}}

        for c in raw.get("contracts", []) or []:
            if not self._evidence_ok(c.get("evidence"), page_norm):
                self._drop("contract", c, "evidence sentence not found on page", url)
                continue
            c = dict(c)
            for f in ("total_value_usd", "cap_hit_usd"):
                if c.get(f) is not None and not N.money_supported(int(c[f]), monies, self.tol):
                    notes.append(f"{f}={c[f]} not found on page — removed")
                    c[f] = None
            if c.get("term_years") is not None and int(c["term_years"]) not in terms:
                notes.append(f"term_years={c['term_years']} not found on page — removed")
                c["term_years"] = None
            c["signing_date"] = N.norm_date(c.get("signing_date"))
            if c["signing_date"] and c["signing_date"][:4] not in years:
                c["signing_date"] = None
            c["first_season"] = N.season(c.get("first_season"))
            if c["first_season"] and c["first_season"][:4] not in years:
                c["first_season"] = None
            c["team_abbr"] = N.team_abbr(c.get("team"))
            if c.get("contract_type") not in ("entry_level", "extension", "rfa", "ufa"):
                c["contract_type"] = "unknown"
            if c.get("term_years") is None and c.get("total_value_usd") is None and c.get("cap_hit_usd") is None:
                self._drop("contract", c, "no verifiable term or money", url)
                continue
            out["contracts"].append(c)

        for t in raw.get("trades", []) or []:
            if not self._evidence_ok(t.get("evidence"), page_norm):
                self._drop("trade", t, "evidence sentence not found on page", url)
                continue
            t = dict(t)
            t["from_abbr"], t["to_abbr"] = N.team_abbr(t.get("from_team")), N.team_abbr(t.get("to_team"))
            if not t["from_abbr"] or not t["to_abbr"] or t["from_abbr"] == t["to_abbr"]:
                self._drop("trade", t, "teams missing or identical", url)
                continue
            t["date"] = N.norm_date(t.get("date"))
            if t["date"] and t["date"][:4] not in years:
                t["date"] = None
            pct = t.get("salary_retained_pct")
            if pct is not None:
                p = f"{pct:g}"
                if not re.search(rf"\b{re.escape(p)}\s*(%|percent|per cent)", page_text, re.I):
                    t["salary_retained_pct"] = None
            out["trades"].append(t)

        b = dict(raw.get("bio") or {})
        if b:
            if b.get("draft_overall") is not None and not re.search(rf"\b{int(b['draft_overall'])}\b|"
                                                                    rf"\b{_ordinal(int(b['draft_overall']))}\b",
                                                                    page_text, re.I):
                b["draft_overall"] = None
            if b.get("draft_year") is not None and str(b["draft_year"]) not in years:
                b["draft_year"] = None
            b["birth_date"] = N.norm_date(b.get("birth_date"))
            if b["birth_date"] and b["birth_date"][:4] not in years:
                b["birth_date"] = None
            b["draft_team_abbr"] = N.team_abbr(b.get("draft_team"))
            out["bio"] = b
        out["notes"] = notes
        return out


_ORD_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh",
              8: "eighth", 9: "ninth", 10: "tenth"}


def _ordinal(n: int) -> str:
    if n in _ORD_WORDS:
        return _ORD_WORDS[n]
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"
