"""The reference desk: where the librarian talks with you, looks things up and remembers you.

Used by every way of talking to the librarian (Telegram, ``biblio chat``), so they share one
memory: the chat log (``chat.jsonl``) and what the librarian has learned about you
(``reader.json``), both in the local folder.

A reply can take several rounds. The model may search (papers, or one shelf of the collection);
every batch of results is vetted by a second, strict pass that keeps only pieces that are really
about what you want and worth an evening, and says why. Only vetted pieces reach the
conversation, and only their links (or links you gave) can be prepared.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from concurrent.futures import ThreadPoolExecutor, wait
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from margin.lesson import Lesson

from . import library, search

CHAT_SYSTEM = """You are the reader's personal librarian, talking with them in a chat. You know books,
science, essays and journalism well and you are curious about people. Your job is to find what is
worth their time to read tonight at bedtime (they will hear it explained aloud on a Kindle or phone),
to talk about what they read, and to remember who they are.

Like a good reference librarian, find out what someone really wants before fetching anything: what
has been on their mind lately, why they want to read, what it is for (a project, a talk, a demo to
film, curiosity, winding down). When the request is open ("what should I read tonight?") and what you
know about them (below) is not enough to choose well, ask one or two real questions first, and you
may offer a direction or two to react to. Follow the conversation; pick up on what they say.

When you recommend, say why each piece suits them in particular (tie it to what they told you or
read before), what it is like (length, tone, how it reads aloud), and number the pieces. One excellent
piece beats three mediocre ones: never pad a list.

Choosing:
- It is bedtime listening: favour pieces with a story and ideas over dense technical papers, unless
  they ask for research or papers.
- "Interesting", "fun", "light", "something good", something to show or film: start with the science
  and essays shelves (Quanta, Aeon, Nautilus and the like), not papers.
- Papers when they want research, or when one paper is the best way in. Classic means important;
  new means notable.
- A prize, a discovery or an event: the primary source (for a Nobel Prize, nobelprize.org's popular
  information) or the original paper, not a news item about it.
- Anything recent (this year's prizes, new discoveries, news) may be newer than what you know: first
  search the facts to learn what happened (who won, for what), then look for the readings by name
  (the laureates' original papers, the official explanation). Never tell the reader something has not
  happened, or that you cannot find it, before you have searched the facts. What the facts search
  reports is current and good enough to act on: official sites are often indexed days late, so do
  not hold back or ask the reader for proof because an official page did not turn up.
- Never market, finance, celebrity or listicle pieces, or anything too thin for twenty minutes.
- Search with different angles until you have something genuinely good. Results below have been
  vetted; offer only those. Every link you give must come from them or from the reader; never
  invent one. If after searching nothing is good enough, say so honestly and suggest a direction.
- Do not suggest what they have already read.

Talk like a person in a chat, not like a bot: natural sentences, a short paragraph or two, no
headings, no bullet lists except the numbered recommendations. Write in {language}.

Return JSON with one of these shapes:
  {{"search": {{"where": "papers", "query": "<English keywords>", "prefer": "classic" | "new" | "any"}}}}
  {{"search": {{"where": "web", "shelf": "<shelf>", "query": "<what to look for>"}}}}
      one shelf of the collection; only its sites are searched. Shelves:
{shelves}
  {{"search": {{"where": "facts", "query": "<what to find out>"}}}}
      the open web, to learn what happened (who won a prize this year, what a discovery was);
      it gives you facts to use, not readings to offer.
  {{"reply": "...", "prepare": "<url>"}}   the reader has picked a piece you offered earlier (or gave
      you a link): prepare it now. Never in the same reply where you first recommend it; wait for them.
  {{"reply": "..."}}
Any of them may also carry "remember": ["..."], short lasting facts about the reader worth keeping
(interests, projects, why they read, what they dislike, how much they know of a field). Only new ones.
{searches}"""

VET_SYSTEM = """You vet search results for a librarian, strictly. The reader wants: {want}
What is known about them: {who}
Today is {today}. Your own knowledge may be out of date: prizes, discoveries and events newer than your
training are real. What the search itself reported is below; trust it over your memory for recent facts.
For a prize or a discovery, the winners' original key papers (even decades old) and the official
explanations of the work are on topic.
What the search reported:
{report}

For each numbered result, decide whether it is genuinely about what they want and worth an evening:
a real, substantial piece (an article, essay, chapter or paper) from a credible source, on the topic in
the sense they mean it. Drop pages that only share a keyword (a paper on "demos" in political
philosophy is not about making a demo), index or listing or landing pages, news briefs, papers from an
unrelated field, and anything that looks like junk or mis-indexed. Keeping none is fine.

Return JSON: {{"keep": [{{"n": <number>, "why": "<one line: what it is and why it fits>"}}],
"advice": "<when little is kept: a better angle to search>"}}"""


@dataclass
class Reply:
    text: str
    prepare: str | None = None
    trace: list[str] = field(default_factory=list)


class Desk:
    def __init__(self, client, *, language: str = "English", model: str | None = None, searches: int = 5,
                 now: Callable[[], dt.datetime] | None = None, log: Callable[[str], None] | None = None) -> None:
        self.client, self.language, self.searches = client, language, searches
        self.model = model or os.environ.get("BIBLIOTHECARY_CHAT_MODEL") or None
        self.now = now or (lambda: dt.datetime.now().astimezone())
        self.log = log or (lambda _msg: None)

    # ---- memory ----------------------------------------------------------------------
    def remember(self, who: str, text: str) -> None:
        path = library.home() / "chat.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": self.now().isoformat(timespec="seconds"), "who": who, "text": text},
                               ensure_ascii=False) + "\n")

    def recent(self, n: int = 30) -> list[dict]:
        path = library.home() / "chat.jsonl"
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines()[-n:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    @property
    def _reader_file(self) -> Path:
        return library.home() / "reader.json"

    def reader(self) -> list[str]:
        """What the librarian has learned about the reader, oldest first."""
        try:
            return [n["text"] for n in json.loads(self._reader_file.read_text(encoding="utf-8")).get("notes", [])]
        except (OSError, json.JSONDecodeError, TypeError, KeyError):
            return []

    def learn(self, facts) -> None:
        if not isinstance(facts, list):
            return
        known = self.reader()
        new = [str(f).strip() for f in facts if str(f).strip() and str(f).strip() not in known]
        if not new:
            return
        notes = [{"text": t} for t in known] + [{"text": t, "t": self.now().date().isoformat()} for t in new]
        self._reader_file.parent.mkdir(parents=True, exist_ok=True)
        self._reader_file.write_text(json.dumps({"notes": notes[-60:]}, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")

    def context(self) -> str:
        lines = ["What you know about the reader:"]
        lines += [f"- {fact}" for fact in self.reader()] or ["- (nothing yet)"]
        lines.append("\nReadings so far (oldest first):")
        found = library.readings()
        lines += [f"- {f.name[:10]} [{library.status(f)}] {Lesson.load(f / 'lesson.json').title}"
                  for f in found[-20:]] or ["- (none yet)"]
        for folder in found[-3:]:
            summary = folder / "summary.json"
            if summary.is_file():
                data = json.loads(summary.read_text(encoding="utf-8"))
                title = Lesson.load(folder / "lesson.json").title
                if data.get("unclear"):
                    lines.append(f"Still unclear after “{title}”: " + "; ".join(data["unclear"]))
                if data.get("threads"):
                    lines.append(f"Threads from “{title}”: " + "; ".join(data["threads"]))
        lines.append(f"\nNow: {self.now():%A %Y-%m-%d %H:%M}.\n\nThe conversation so far:")
        for item in self.recent():
            lines.append(f"{'Reader' if item['who'] == 'reader' else 'You'}: {item['text']}")
        return "\n".join(lines)

    # ---- looking things up -----------------------------------------------------------
    def look_up(self, ask: dict) -> tuple[list[dict], str]:
        """Results, and what the search itself said (web searches only)."""
        if ask.get("where") == "papers":
            return search.papers(str(ask["query"]), str(ask.get("prefer") or "any"), limit=12), ""
        if ask.get("where") == "facts":
            return [], search.facts(self.client, str(ask["query"]))
        return search.web_report(self.client, str(ask["query"]), str(ask.get("shelf") or "science"))

    def vet(self, want: str, results: list[dict], report: str = "") -> tuple[list[dict], str]:
        """Only results that are really about it and worth reading, each with why; plus advice."""
        if not results:
            return [], ""
        who = "; ".join(self.reader()) or "nothing yet"
        system = VET_SYSTEM.format(want=want, who=who, today=f"{self.now():%Y-%m-%d}",
                                   report=report[:2000] or "(nothing beyond the list)")
        data = self.client.chat_json(system, search.describe(results),
                                     model=self.model, max_tokens=900)
        kept = []
        for item in data.get("keep") or []:
            try:
                n = int(item.get("n"))
            except (TypeError, ValueError, AttributeError):
                continue
            if 1 <= n <= len(results) and results[n - 1] not in kept:
                kept.append({**results[n - 1], "why": str(item.get("why") or "").strip()})
        advice = str(data.get("advice") or "").strip()
        kept, locked = self.openable(kept)
        if locked:
            advice = (f"Dropped because only an abstract or a paywall was reachable: "
                      f"{'; '.join(r['title'] for r in locked)}. Look for an open copy or another piece. "
                      + advice).strip()
        return kept, advice

    def openable(self, kept: list[dict]) -> tuple[list[dict], list[dict]]:
        """Split vetted pieces into those readable in full and those that are not (checked in parallel;
        a site too slow to answer gets the benefit of the doubt)."""
        if not kept:
            return [], []
        pool = ThreadPoolExecutor(max_workers=6)
        jobs = [pool.submit(search.readable, r["url"]) for r in kept]
        wait(jobs, timeout=25)
        pool.shutdown(wait=False, cancel_futures=True)
        ok = [not job.done() or job.exception() is not None or job.result() for job in jobs]
        return ([r for r, good in zip(kept, ok) if good], [r for r, good in zip(kept, ok) if not good])

    # ---- a turn of conversation ------------------------------------------------------
    def reply(self, text: str, *, choose: bool = False) -> Reply:
        """Answer what the reader just said (already in the chat log), searching as needed.

        ``choose``: ``text`` is the librarian's own task (the daily round: pick tonight's reading
        and prepare it), not something the reader said; a vetted piece may be prepared at once."""
        context, work, trace, allowed, learned = self.context(), "", [], set(), ""
        if choose:
            context += f"\n\n(Your own task now, not the reader speaking: {text})"
        shelves = "\n".join(f"        {name}: {shelf['about']}" for name, shelf in search.shelves().items())
        for left in range(self.searches, -1, -1):
            budget = (f"You may search {left} more time{'s' if left != 1 else ''} before replying." if left
                      else "No more searches now: reply with what you have.")
            system = CHAT_SYSTEM.format(language=self.language, shelves=shelves, searches=budget)
            data = self.client.chat_json(system, context + work, model=self.model, max_tokens=1500)
            self.learn(data.get("remember"))
            ask = data.get("search")
            if isinstance(ask, dict) and ask.get("query") and left > 0:
                where = ("papers, " + str(ask.get("prefer") or "any") if ask.get("where") == "papers"
                         else "facts" if ask.get("where") == "facts"
                         else f"shelf {ask.get('shelf') or 'science'}")
                try:
                    results, report = self.look_up(ask)
                    if report:
                        learned = (learned + "\n" + report)[-3000:]
                    kept, advice = self.vet(text, results, learned)
                except Exception as err:
                    self.log(f"search failed: {err}")
                    results, report, kept, advice = [], "", [], f"(the search failed: {err})"
                allowed.update(r["url"] for r in kept)
                trace.append(f"search {where}: {ask['query']!r} → {len(results)} found, {len(kept)} kept"
                             + "".join(f"\n    ✓ {r['title']} — {r['url']}\n      {r['why']}" for r in kept))
                work += (f"\n\nYou searched ({where}): {ask['query']}\n"
                         + (f"The search reported (facts you may use; its links are not offerable "
                            f"unless vetted below):\n{report[:1500]}\n" if report else "")
                         + f"Vetted: {len(kept)} of {len(results)} results are worth offering.\n"
                         + "".join(f"- {r['title']}"
                                   + (f" ({r.get('year')}, {r.get('venue')})" if r.get("venue") else "")
                                   + f"\n  {r['url']}\n  {r['why']}\n" for r in kept)
                         + (f"Advice: {advice}\n" if advice else ""))
                continue
            reply = str(data.get("reply") or "").strip()
            url = str(data.get("prepare") or "").strip()
            given = url and (url.rstrip("/") in context          # offered earlier, or the reader's own link
                             or (choose and url in allowed))         # or chosen on the daily round
            if url and not given:
                self.log(f"ignored a link that was neither found nor given: {url}")
            return Reply(reply, url if given else None, trace)
        return Reply("", None, trace)
