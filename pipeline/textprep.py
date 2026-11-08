"""Turn HTML into clean text and trim it to the parts that matter for one player."""
from __future__ import annotations

import re

import lxml.html
import trafilatura
from trafilatura import extract_metadata

KEYWORDS = re.compile(
    r"contract|extension|signed|sign |cap hit|aav|average annual|million|\$|salary|bonus|"
    r"no-movement|no-trade|clause|trade|traded|acquired|deal|retain|free agen|draft|"
    r"entry-level|term|year", re.I)


def html_to_text(html: str, url: str) -> tuple[str, dict]:
    text = trafilatura.extract(html, url=url, include_tables=True, include_comments=False,
                               favor_recall=True, deduplicate=True) or ""
    if len(text) < 300:  # extraction failed (some sites are mostly tables/JS) — plain fallback
        try:
            doc = lxml.html.fromstring(html)
            for bad in doc.xpath("//script|//style|//noscript|//nav|//footer"):
                bad.drop_tree()
            fallback = re.sub(r"\n\s*\n+", "\n", doc.text_content())
            if len(fallback) > len(text):
                text = fallback
        except (lxml.etree.ParserError, ValueError):
            pass
    meta = {"title": None, "published": None}
    try:
        md = extract_metadata(html, default_url=url)
        if md is not None:
            meta["title"] = getattr(md, "title", None)
            meta["published"] = getattr(md, "date", None)
    except Exception:  # metadata is a nice-to-have
        pass
    return text.strip(), meta


def mentions(text: str, name: str) -> int:
    last = name.split()[-1]
    return len(re.findall(r"\b" + re.escape(last) + r"\b", text, re.I))


def chunks_for_llm(text: str, name: str, max_chars: int, max_chunks: int) -> list[str]:
    """Whole page if it fits; otherwise keep lines near the player's name or contract/trade words."""
    if len(text) <= max_chars:
        return [text]
    last = name.split()[-1].lower()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    keep = set()
    for i, ln in enumerate(lines):
        low = ln.lower()
        if last in low or (KEYWORDS.search(ln) and len(ln) > 40):
            keep.update({i - 1, i, i + 1})
    picked = [lines[i] for i in sorted(keep) if 0 <= i < len(lines)]
    out, cur = [], ""
    for ln in picked:
        if len(cur) + len(ln) + 1 > max_chars:
            out.append(cur)
            cur = ""
            if len(out) >= max_chunks:
                break
        cur += ln + "\n"
    if cur and len(out) < max_chunks:
        out.append(cur)
    return out
