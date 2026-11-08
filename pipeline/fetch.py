"""Polite page fetcher: robots.txt, per-site delays, disk cache, honest user agent."""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import Config

log = logging.getLogger(__name__)


def _decode(raw: bytes, declared: str | None) -> str:
    """Decode page bytes. Uses the declared charset, else UTF-8, else a detected one."""
    if declared and declared.lower() not in ("iso-8859-1", "latin-1"):   # requests' default guess
        try:
            return raw.decode(declared)
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
        if best and best.encoding:
            return raw.decode(best.encoding, errors="replace")
    except ImportError:
        pass
    return raw.decode("latin-1", errors="replace")


class Fetcher:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        f = cfg.fetch
        self.ua = f["user_agent"]
        self.min_delay = float(f["min_delay_per_domain_s"])
        self.timeout = float(f["timeout_s"])
        self.max_bytes = int(f["max_bytes"])
        self.ttl_s = float(f["cache_ttl_days"]) * 86400
        self.cache = cfg.resolve(f["cache_dir"]) / "pages"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.ua, "Accept": "text/html,application/xhtml+xml",
                                     "Accept-Language": "en"})
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self._cooldown: set[str] = set()   # sites that told us to slow down (429) this run
        self.stats = {"fetched": 0, "cached": 0, "robots_blocked": 0, "errors": 0}

    # ---- cache ------------------------------------------------------------
    def _paths(self, url: str) -> tuple[Path, Path]:
        k = hashlib.sha1(url.encode()).hexdigest()
        return self.cache / f"{k}.html", self.cache / f"{k}.json"

    def _from_cache(self, url: str) -> dict | None:
        hp, mp = self._paths(url)
        if hp.exists() and mp.exists() and time.time() - mp.stat().st_mtime < self.ttl_s:
            meta = json.loads(mp.read_text())
            meta["html"] = hp.read_text(encoding="utf-8", errors="replace")
            meta["from_cache"] = True
            return meta
        return None

    def _to_cache(self, url: str, page: dict) -> None:
        hp, mp = self._paths(url)
        hp.write_text(page["html"], encoding="utf-8")
        mp.write_text(json.dumps({k: v for k, v in page.items() if k != "html"}, indent=1))

    # ---- politeness ---------------------------------------------------------
    def _robot(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base in self._robots:
            return self._robots[base]
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = self.session.get(base + "/robots.txt", timeout=self.timeout)
            if r.status_code in (401, 403):
                rp.disallow_all = True
            elif r.status_code >= 500:
                rp.disallow_all = True          # be conservative when the site is unhappy
            elif r.status_code >= 400:
                rp.allow_all = True
            else:
                rp.parse(r.text.splitlines())
        except requests.RequestException:
            rp.disallow_all = True
        self._robots[base] = rp
        return rp

    def _wait(self, host: str, crawl_delay: float | None) -> None:
        delay = max(self.min_delay, crawl_delay or 0)
        last = self._last_hit.get(host)
        if last is not None:
            gap = time.time() - last
            if gap < delay:
                time.sleep(delay - gap)
        self._last_hit[host] = time.time()

    # ---- main ---------------------------------------------------------------
    def get(self, url: str) -> dict | None:
        """Return {'url','final_url','status','fetched_at','html'} or None."""
        cached = self._from_cache(url)
        if cached:
            self.stats["cached"] += 1
            return cached
        host = self.cfg.host(url)
        if host in self._cooldown:
            return None
        rp = self._robot(url)
        if rp and not rp.can_fetch(self.ua, url):
            log.info("robots.txt disallows %s — skipped", url)
            self.stats["robots_blocked"] += 1
            return None
        self._wait(host, rp.crawl_delay(self.ua) if rp else None)
        try:
            with self.session.get(url, timeout=self.timeout, stream=True, allow_redirects=True) as r:
                if r.status_code == 429:
                    log.warning("%s asked us to slow down (429) — skipping it for this run", host)
                    self._cooldown.add(host)
                    return None
                if r.status_code >= 400:
                    log.info("HTTP %s for %s — skipped", r.status_code, url)
                    self.stats["errors"] += 1
                    return None
                ctype = r.headers.get("Content-Type", "")
                if "html" not in ctype and "xml" not in ctype:
                    log.info("not an HTML page (%s): %s", ctype, url)
                    return None
                chunks, size = [], 0
                for chunk in r.iter_content(65536):
                    size += len(chunk)
                    if size > self.max_bytes:
                        break
                    chunks.append(chunk)
                raw = b"".join(chunks)
                html = _decode(raw, r.encoding)
                page = {"url": url, "final_url": r.url, "status": r.status_code,
                        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "html": html}
        except requests.RequestException as e:
            log.info("fetch failed for %s: %s", url, e)
            self.stats["errors"] += 1
            return None
        self.stats["fetched"] += 1
        self._to_cache(url, page)
        page["from_cache"] = False
        return page
