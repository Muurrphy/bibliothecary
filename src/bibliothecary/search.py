"""Where the librarian looks things up.

- papers: OpenAlex (free, no key; ``OPENALEX_API_KEY`` raises the daily budget), with arXiv as a
  fallback. Open-access works only, so whatever is found can actually be read. "classic" sorts by
  citations among works at least five years old; "new" keeps the last twelve months.
- web: OpenAI's built-in web search (same key as the model), for news, long-form pieces, essays and
  books. It returns real pages with their addresses.

Every result carries the address it came from; the librarian may only offer those.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

UA = {"User-Agent": "Bibliothecary (personal reading librarian)"}


class SearchError(RuntimeError):
    pass


def _get(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.read()
    except urllib.error.HTTPError as err:
        raise SearchError(f"{err.code} from {urllib.parse.urlsplit(url).netloc}") from err
    except (urllib.error.URLError, OSError) as err:
        raise SearchError(f"cannot reach {urllib.parse.urlsplit(url).netloc}: {getattr(err, 'reason', err)}") from err


def _abstract(inverted: dict[str, list[int]] | None, size: int = 400) -> str:
    if not inverted:
        return ""
    words = sorted((pos, word) for word, places in inverted.items() for pos in places)
    text = " ".join(word for _, word in words)
    return text if len(text) <= size else text[:size].rsplit(" ", 1)[0] + "…"


def openalex(query: str, prefer: str = "any", limit: int = 5, *, today: dt.date | None = None,
             get=_get) -> list[dict]:
    today = today or dt.datetime.now().astimezone().date()
    filters = ["has_abstract:true", "open_access.is_oa:true", "type:article|review|preprint|book-chapter"]
    params = {"search": query, "per_page": str(limit),
              "select": "title,publication_year,cited_by_count,doi,best_oa_location,primary_location,"
                        "abstract_inverted_index"}
    if prefer == "classic":
        filters.append(f"to_publication_date:{today.year - 5}-12-31")
        params["sort"] = "cited_by_count:desc"
    elif prefer == "new":
        filters.append(f"from_publication_date:{today - dt.timedelta(days=365)}")
    params["filter"] = ",".join(filters)
    if os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    data = json.loads(get("https://api.openalex.org/works?" + urllib.parse.urlencode(params)))
    out = []
    for work in data.get("results") or []:
        oa = work.get("best_oa_location") or {}
        primary = work.get("primary_location") or {}
        url = oa.get("pdf_url") or oa.get("landing_page_url") or work.get("doi")
        if not url or not work.get("title"):
            continue
        out.append({"title": work["title"], "year": work.get("publication_year"),
                    "venue": ((primary.get("source") or {}).get("display_name") or ""),
                    "cited": work.get("cited_by_count") or 0, "url": url,
                    "about": _abstract(work.get("abstract_inverted_index"))})
    return out


ATOM = {"a": "http://www.w3.org/2005/Atom"}


def arxiv(query: str, prefer: str = "any", limit: int = 5, *, get=_get) -> list[dict]:
    params = {"search_query": f"all:{query}", "max_results": str(limit),
              "sortBy": "submittedDate" if prefer == "new" else "relevance"}
    root = ET.fromstring(get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)))
    out = []
    for entry in root.findall("a:entry", ATOM):
        title = " ".join((entry.findtext("a:title", "", ATOM) or "").split())
        link = entry.findtext("a:id", "", ATOM).replace("/abs/", "/pdf/")
        summary = " ".join((entry.findtext("a:summary", "", ATOM) or "").split())
        if title and link:
            out.append({"title": title, "year": (entry.findtext("a:published", "", ATOM) or "")[:4],
                        "venue": "arXiv", "cited": None, "url": link,
                        "about": summary[:400] + ("…" if len(summary) > 400 else "")})
    return out


def papers(query: str, prefer: str = "any", limit: int = 5, *, get=_get) -> list[dict]:
    """Open-access papers; OpenAlex first, arXiv when OpenAlex is unavailable or finds nothing."""
    try:
        found = openalex(query, prefer, limit, get=get)
        if found:
            return found
    except (SearchError, ValueError):
        pass
    return arxiv(query, prefer, limit, get=get)


def web(client, query: str) -> list[dict]:
    """Pages found by the model's own web search: [{"title", "url", "about"}]."""
    answer = client.web_search(query)
    seen, out = set(), []
    for source in answer.get("sources") or []:
        url = source.get("url")
        if url and url not in seen:
            seen.add(url)
            out.append({"title": source.get("title") or url, "url": url, "about": ""})
    if out and answer.get("text"):
        out[0]["about"] = answer["text"][:600]
    return out


def describe(results: list[dict[str, Any]]) -> str:
    """Results as plain lines for the model to choose from."""
    if not results:
        return "(nothing found)"
    lines = []
    for n, r in enumerate(results, 1):
        meta = ", ".join(str(x) for x in (r.get("year"), r.get("venue"),
                                          f"cited {r['cited']}" if r.get("cited") is not None else None) if x)
        lines.append(f"{n}. {r['title']}" + (f" ({meta})" if meta else "") + f"\n   {r['url']}"
                     + (f"\n   {r['about']}" if r.get("about") else ""))
    return "\n".join(lines)
