"""Where the librarian looks things up.

- papers: OpenAlex (free, no key; ``OPENALEX_API_KEY`` raises the daily budget), with arXiv as a
  fallback. Open-access works only, so whatever is found can actually be read. "classic" sorts by
  citations among works at least five years old; "new" keeps the last twelve months.
- web: OpenAI's built-in web search (same key as the model), for science writing, news, essays and
  books, but only on the sites of one shelf of the collection (``shelves.toml``). Anything from
  another site is dropped, whatever the search returns.

Every result carries the address it came from; the librarian may only offer those.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import library

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
    filters = ["has_abstract:true", "open_access.is_oa:true", "is_paratext:false", "is_retracted:false",
               "type:article|review|preprint|book-chapter"]
    params = {"search": query, "per_page": str(limit),
              "select": "title,publication_year,cited_by_count,doi,best_oa_location,primary_location,"
                        "abstract_inverted_index"}
    if prefer == "classic":                    # well cited, and old enough to have earned it
        filters += [f"to_publication_date:{today.year - 5}-12-31", "cited_by_count:>99"]
        params["sort"] = "cited_by_count:desc"
    elif prefer == "new":                      # the last year, the most noticed first
        filters.append(f"from_publication_date:{today - dt.timedelta(days=365)}")
        params["sort"] = "cited_by_count:desc"
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


DEFAULT_SHELVES = Path(__file__).with_name("shelves.toml")


def shelves() -> dict[str, dict]:
    """The collection: {name: {"about", "sites"}}, the defaults adjusted by ~/Bibliothecary/shelves.toml."""
    out = tomllib.loads(DEFAULT_SHELVES.read_text(encoding="utf-8"))
    mine = library.home() / "shelves.toml"
    if mine.is_file():
        for name, shelf in tomllib.loads(mine.read_text(encoding="utf-8")).items():
            if not isinstance(shelf, dict):
                continue
            if "sites" in shelf or name not in out:
                out[name] = {"about": shelf.get("about", name), "sites": list(shelf.get("sites") or [])}
            base = out[name]
            base["sites"] = [x for x in base["sites"] + list(shelf.get("add") or []) if x not in (shelf.get("remove") or [])]
    return {name: {"about": str(s.get("about") or name), "sites": [str(x).lower() for x in s.get("sites") or []]}
            for name, s in out.items() if isinstance(s, dict) and s.get("sites")}


def on_shelf(url: str, sites: list[str]) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return any(host == site or host.endswith("." + site) for site in sites)


def _clean(url: str) -> str:
    """Drop tracking parameters (``utm_…``, ``trk``) that the search adds to links."""
    parts = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() != "trk"]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def web_report(client, query: str, shelf: str = "science") -> tuple[list[dict], str]:
    """Pages from one shelf's sites, found by the model's own web search, and what the search said.

    The text matters on its own: for recent events (this year's prizes, new discoveries) it carries
    facts newer than the chat model's training, even when few of its links are on the shelf."""
    collection = shelves()
    if shelf not in collection:
        raise SearchError(f"no shelf called {shelf!r}; the shelves are {', '.join(collection)}")
    sites = collection[shelf]["sites"]
    answer = client.web_search(query, domains=sites)
    seen, out = set(), []
    for source in answer.get("sources") or []:
        url = source.get("url")
        if not url:
            continue
        url = _clean(url)
        if url not in seen and on_shelf(url, sites):
            seen.add(url)
            out.append({"title": source.get("title") or url, "url": url, "about": ""})
    text = str(answer.get("text") or "").replace("?utm_source=openai", "").replace("&utm_source=openai", "")
    if out and text:
        out[0]["about"] = text[:600]
    return out, text


def facts(client, query: str) -> str:
    """What the open web says about something (no shelf): facts for the librarian, not readings."""
    text = str(client.web_search(query).get("text") or "")
    return text.replace("?utm_source=openai", "").replace("&utm_source=openai", "")[:2500]


def web(client, query: str, shelf: str = "science") -> list[dict]:
    """Pages from one shelf's sites, found by the model's own web search: [{"title", "url", "about"}]."""
    return web_report(client, query, shelf)[0]


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
