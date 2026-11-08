"""Web search through a self-hosted SearXNG instance, plus page selection."""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import requests

from .config import Config

log = logging.getLogger(__name__)

_TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid",
             "ref", "cmpid", "ocid"}


def clean_url(url: str) -> str:
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in _TRACKING]
    return urlunparse((p.scheme, p.netloc.lower(), p.path, "", urlencode(q), ""))


class Searcher:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.url = cfg.search["searxng_url"].rstrip("/") + "/search"
        self.session = requests.Session()

    def search(self, query: str) -> list[dict]:
        try:
            r = self.session.get(self.url, params={"q": query, "format": "json", "language": "en"},
                                 timeout=30)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            log.warning("search failed for %r: %s", query, e)
            return []
        except ValueError:
            log.warning("SearXNG did not return JSON — is 'json' enabled in searxng/settings.yml?")
            return []
        results = data.get("results", [])[: int(self.cfg.search["results_per_query"])]
        return [{"url": clean_url(x["url"]), "title": x.get("title", ""), "snippet": x.get("content", "")}
                for x in results if x.get("url", "").startswith("http")]

    def queries_for(self, name: str, team_hint: str | None) -> list[str]:
        out = []
        for q in self.cfg.search["queries"]:
            q = q.replace("{name}", name).replace("{team}", team_hint or "")
            out.append(" ".join(q.split()))
        return out

    def find_pages(self, name: str, team_hint: str | None = None) -> list[dict]:
        """Run all queries and pick the best, most diverse set of pages to read."""
        hits: dict[str, dict] = {}
        for q in self.queries_for(name, team_hint):
            for rank, res in enumerate(self.search(q)):
                if self.cfg.is_blocked(res["url"]):
                    continue
                h = hits.setdefault(res["url"], {**res, "queries": 0, "best_rank": rank})
                h["queries"] += 1
                h["best_rank"] = min(h["best_rank"], rank)
            time.sleep(float(self.cfg.search["delay_between_searches_s"]))
        return self.select(list(hits.values()), name)

    def select(self, hits: list[dict], name: str) -> list[dict]:
        last = name.split()[-1].lower()
        for h in hits:
            text = (h["title"] + " " + h["snippet"] + " " + h["url"]).lower()
            mentions = last in text
            h["score"] = (self.cfg.weight(h["url"]) * 2 + h["queries"] - h["best_rank"] * 0.1
                          + (1.5 if mentions else -3))
        hits.sort(key=lambda h: -h["score"])

        max_total = int(self.cfg.fetch["max_pages_per_player"])
        per_domain = int(self.cfg.fetch["max_pages_per_domain"])
        reserve = int(self.cfg.fetch["reserve_stats_pages"])
        chosen: list[dict] = []
        counts: dict[str, int] = {}

        def take(h):
            d = self.cfg.host(h["url"])
            if counts.get(d, 0) >= per_domain or h in chosen:
                return False
            counts[d] = counts.get(d, 0) + 1
            chosen.append(h)
            return True

        # 1) reserve slots for pages likely to carry a stats table (one per stats site)
        stats_taken = set()
        for h in hits:
            if len(stats_taken) >= reserve:
                break
            d = self.cfg.host(h["url"])
            if self.cfg.is_stats_domain(h["url"]) and d not in stats_taken and h["score"] > 0:
                if take(h):
                    stats_taken.add(d)
        # 2) fill the rest by score
        for h in hits:
            if len(chosen) >= max_total:
                break
            if h["score"] > 0:
                take(h)
        return chosen[:max_total]
