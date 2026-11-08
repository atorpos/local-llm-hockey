"""Load config.toml and expose simple helpers."""
from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent


class Config:
    def __init__(self, path: str | Path | None = None):
        path = Path(path) if path else ROOT / "config.toml"
        with open(path, "rb") as f:
            self.raw = tomllib.load(f)
        self.path = path
        self.llm = self.raw["llm"]
        self.search = self.raw["search"]
        self.fetch = self.raw["fetch"]
        self.extract = self.raw["extract"]
        self.sources = self.raw["sources"]
        self.weights: dict[str, float] = self.sources.get("weights", {})
        self.blocked: list[str] = self.sources.get("blocked", [])
        self.stats_domains: list[str] = self.sources.get("stats_domains", [])

    # ---- domain helpers -------------------------------------------------
    @staticmethod
    def host(url: str) -> str:
        h = (urlparse(url).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h

    @staticmethod
    def _suffix_match(host: str, pattern: str) -> bool:
        pattern = pattern.lower()
        if pattern.endswith("."):          # "amazon." matches amazon.com, amazon.ca ...
            return pattern in host + "."
        return host == pattern or host.endswith("." + pattern)

    def is_blocked(self, url: str) -> bool:
        h = self.host(url)
        return any(self._suffix_match(h, p) for p in self.blocked)

    def weight(self, url: str) -> float:
        h = self.host(url)
        matches = [float(w) for dom, w in self.weights.items() if self._suffix_match(h, dom)]
        return max(matches) if matches else 1.0

    def is_stats_domain(self, url: str) -> bool:
        h = self.host(url)
        return any(self._suffix_match(h, d) for d in self.stats_domains)

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else ROOT / p
