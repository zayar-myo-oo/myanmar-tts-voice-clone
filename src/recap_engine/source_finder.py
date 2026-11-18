"""Source Finder: find where a clip / drama comes from (to credit it or to get a cleaner, higher
quality original). Builds search queries from the title + transcript (local LLM makes Chinese
keywords), searches YouTube and Bilibili via yt-dlp (no API key), ranks by title/keyword overlap
and duration. Results are suggestions only - always check them yourself."""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .manifest import Project

YTDLP = [sys.executable, "-m", "yt_dlp"]


def _search(prefix: str, query: str, n: int = 8) -> list[dict]:
    try:
        r = subprocess.run([*YTDLP, "--flat-playlist", "--dump-json", "--no-warnings", "--skip-download",
                            f"{prefix}{n}:{query}"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return []
    out = []
    for line in r.stdout.splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        url = j.get("webpage_url") or j.get("url") or ""
        if url and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={j.get('id')}" if prefix.startswith("yt") else url
        thumbs = j.get("thumbnails") or []
        out.append({"title": j.get("title") or "", "url": url, "channel": j.get("channel") or j.get("uploader") or "",
                    "duration": j.get("duration"), "views": j.get("view_count"),
                    "thumb": (thumbs[-1].get("url") if thumbs else j.get("thumbnail")) or "",
                    "site": "YouTube" if prefix.startswith("yt") else "Bilibili", "query": query})
    return out


def keywords_for(p: Project) -> list[str]:
    """Queries: the title itself + Chinese keywords the local LLM extracts from the transcript."""
    title = re.sub(r"[#@]\S+|\s+", " ", p.manifest.title or "").strip()[:80]
    qs = [title] if title else []
    tr = p.read_json("analysis/transcript.json", {}) or {}
    lines = " ".join(c.get("text", "") for c in (tr.get("cues") or [])[:60])[:1500]
    if lines:
        try:
            from .llm import chat_json
            kw = chat_json(p.manifest.settings.llm_model,
                           "You help find the original Chinese short drama / film of a clip.",
                           "From these Chinese subtitle lines, give 3 short search queries (Chinese) that would find "
                           "the original drama on YouTube/Bilibili: likely drama title words, character names, "
                           "unique plot terms. Lines:\n" + lines,
                           {"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
                            "required": ["queries"]}, temperature=0.2, num_ctx=4096)
            qs += [q.strip() for q in kw.get("queries", []) if q.strip()][:3]
        except Exception:  # noqa: BLE001  (LLM offline: title search still works)
            pass
    return list(dict.fromkeys(qs))[:4]


def _score(r: dict, queries: list[str], dur: float | None) -> float:
    t = r["title"].lower()
    sim = max((difflib.SequenceMatcher(None, q.lower(), t).ratio() for q in queries), default=0)
    hits = max((sum(1 for w in re.findall(r"[一-鿿]{2,}|\w{3,}", q.lower()) if w in t) for q in queries), default=0)
    s = sim * 2 + min(hits, 4) * 0.5
    if dur and r.get("duration"):  # the original is usually as long as the clip or longer
        s += 0.5 if r["duration"] >= dur * 0.9 else 0
    return round(s, 3)


def find_sources(p: Project | None = None, query: str = "", limit: int = 12) -> dict[str, Any]:
    queries = [query.strip()] if query.strip() else []
    dur = None
    if p is not None:
        queries = queries or keywords_for(p)
        dur = float(p.manifest.source.get("probe", {}).get("duration") or 0) or None
    if not queries:
        return {"queries": [], "results": []}
    jobs = [(pre, q) for q in queries for pre in ("ytsearch", "bilisearch")]
    with ThreadPoolExecutor(max_workers=6) as ex:
        found = [r for res in ex.map(lambda a: _search(*a), jobs) for r in res]
    seen, results = set(), []
    for r in found:
        if r["url"] and r["url"] not in seen:
            seen.add(r["url"])
            r["score"] = _score(r, queries, dur)
            results.append(r)
    results.sort(key=lambda r: -r["score"])
    out = {"queries": queries, "results": results[:limit]}
    if p is not None:
        p.write_json("export/source_finder.json", out)
    return out
