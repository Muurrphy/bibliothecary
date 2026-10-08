# Bibliothecary — requirements

> Status: draft v0.2, 2026-10-08. v0.3 (records, three-part sessions), the rename and the Telegram chat of v0.5 are implemented; the rest is not yet.
> [中文](requirements.zh-CN.md)

## 0. In one sentence

**Bibliothecary is a personal librarian.** During the day it asks you in a chat what you'd like to read tonight. By evening it has the reading guide and notes ready. At bedtime it reads the piece with you on a Kindle or phone, and afterwards it files the evening's questions and answers as a reading report that shapes what it picks next.

It is not a tool that stops when the article ends. The loop is:

```
collection → choose together → prepare (guide, notes) → bedtime reading → reading report → update your knowledge map → next choice
```

## 1. Name and parts

| Name | What it is |
|---|---|
| **Bibliothecary** (Chinese: **图书管理员**) | The whole project. An older English word for librarian, in use since the 1610s, from Latin *bibliothecarius*. |
| Command | `bibliothecary`, short form `biblio` |
| **Margin** | The reading room: the existing Kindle page, prepared talk and interruptible questions. Keeps its name as a component. |
| **robot_lipsync** (the mouth) | The talking mouth on a phone, iPad or OLED. Kept as an optional component. |

## 2. Why it is built this way: what a librarian does

We start from what a good librarian does, not from what AI can do, and map each duty to a feature.

| A librarian's duty | What Bibliothecary does |
|---|---|
| **Collection development**: deciding what to collect and from where | A collection with taste: a curated list of trusted sources for papers, news and long-form journalism, books and essays. Only classics, or work that is both new and good |
| **Reference interview**: finding out what the reader actually wants to know | Asks you once a day in the chat what you'd like to read tonight; learns your interests and goals the first time you use it |
| **Readers' advisory**: recommending for a particular person, mixing classics with new work | Selection rules: classics alternate with new work, hard alternates with easy, a monthly rhythm, never a paper every night |
| **Cataloguing**: every item recorded and findable | Each item is catalogued on entry: source, type, topic, difficulty, read or not, so nothing is suggested twice |
| **Circulation records** | Every evening's questions and answers are kept in full and written up as that day's reading report |
| **Reader instruction**: teaching people to read and understand | A structured session: background first, then the text, then review with questions |
| **Knowing the reader's level** | A knowledge map built from daytime chats and past reading reports: what you know, where the gaps are |
| **Confidentiality** | A real librarian never discloses what you borrowed, so everything stays on your own machine |

### How the librarian's job has changed

- **Ancient to early modern** (Alexandria, medieval monasteries, the *bibliothecary* of the Bodleian in the 17th century): the core was **keeping, collecting and cataloguing**. Books were scarce and costly; the first duty was that none be lost or damaged, and some were chained to the shelves. Callimachus compiled the *Pinakes* at Alexandria, often called one of the first bibliographies. In 1627 Gabriel Naudé's *Advice on Establishing a Library* argued for collecting both the great old authors and the new ones — the ancestor of our "classics and new work" rule.
- **Modern** (from the late 19th century): the focus moved from guarding books to serving readers. Reference service, readers' advisory and reader instruction appeared, and reader confidentiality became part of the American Library Association's Code of Ethics (from 1939).
- **We take from both**: from the old librarian, careful cataloguing and a collection chosen with taste; from the modern one, service built around one particular person, and protection of their privacy.

> These historical details are written from general knowledge and must be checked against sources before publication.

## 3. How you talk to the librarian: three doors

Not everyone has a personal agent, so there are several doors to **the same librarian and the same collection**.

| Door | For whom | Priority |
|---|---|---|
| **Telegram bot** | People without a personal agent. The librarian lives in one chat: it messages you first, and you can drop links or talk any time | P0 (first release) |
| **MCP server** | People with a personal agent (Claude, ChatGPT, OpenClaw and others). The collection, reading reports and selection tools are exposed to your agent, which talks to you | P0 |
| **Local web page** | Browsing the collection and reports on the computer, adjusting the plan by hand. Extends the existing `/remote` page | P1 |
| WhatsApp, WeChat, email | Later. WhatsApp requires the Business API, with an application and possible fees; personal WeChat has no official API | P2 |

Requirements:

- R3.1 All doors share one backend and one data store; whatever you say through any door lands in the same record.
- R3.2 The Telegram bot answers only the one user it is paired with and ignores everyone else.
- R3.3 The MCP server offers at least: search the collection, add to the collection, see tonight's plan, change tonight's plan, read a given day's report, search past reports, query the knowledge map.
- R3.4 Proactive messages need the computer (or a small home server) to be running. The docs say so and explain how to start it at boot.

## 4. The collection (collection development and cataloguing)

### 4.1 Principles

- A **general framework** first; everyone can edit their own collection. The default collection should **have taste**: classics, or work that is both new and good.
- Default sources live in an editable list (YAML) that the community can extend by pull request. Each source states its type, language, whether it is free, its licence and a trust level.
- Prefer sources that are **free and legal to read**. For paywalled material, store only the link and metadata; the reader opens it themselves.

### 4.2 Default shelves (first draft, to be checked)

| Shelf | Default sources | How "classic" and "new and good" are judged |
|---|---|---|
| **Papers** | arXiv (new), OpenAlex and Semantic Scholar (metadata and citations), PubMed (biomedicine), table-of-contents feeds of Nature, Science, Cell and PNAS, Annual Reviews (surveys) | Classic: highly cited within its field and more than 10 years old. New: last 6 months, top venue or high attention, close to your interests |
| **News and long-form** | AP, Reuters (facts); Quanta Magazine, Knowable Magazine, Aeon, ProPublica (in depth, free); Chinese science media such as *The Intellectual* (知识分子) and *Fanpu* (返朴) | No breaking news. Pieces that take 20 minutes or more and are still worth reading a year later |
| **Books** | Standard Ebooks (carefully edited public-domain books), Project Gutenberg, Open Library (metadata), Wikisource, the Chinese Text Project; your own EPUB or Calibre library | Lists of classics plus your own books; a book is read over several nights, chapter by chapter |
| **Essays** | Public-domain essays (Montaigne, Lamb, Lu Xun and others), Aeon Essays | Curated by author and theme |
| **Your own** | Any link or file; optional sync from Wallabag or Readeck | You decide; the librarian catalogues and schedules |

### 4.3 Cataloguing

- R4.1 Each item records title, author, source, type, language, length (estimated reading minutes), topic tags, difficulty, classic or new, date added, and status (to read, in progress, read, paused).
- R4.2 Deduplication: different links to the same work (arXiv and journal version, reposts) are recognised as one item.
- R4.3 Items already read are not suggested again unless you ask to reread or they are due for review.
- R4.4 No separate shelves per language. Language is just a catalogue field; readers who want only one language can add a filter.

### 4.4 In progress and paused

A book usually takes many evenings, and switching to something else halfway is normal. Like a real librarian who remembers that you still have a book out, Bibliothecary remembers every unfinished book.

- R4.5 Progress is kept automatically: the chapter and paragraph reached, plus what was already explained and asked, all stored with the book's entry. When you return, it opens with a sentence or two on where you left off.
- R4.6 Once a day it checks the books in progress and mentions one when the moment is right, for example:
  - a book has been untouched for more than a week;
  - something you said today relates to it;
  - this week's rhythm has a free "book" evening.
  Reminders are restrained: at most once a week per book, and longer after you say "not now".
- R4.7 If you say you don't want to read it, the book moves to the **paused shelf**: greyed out in the collection, no more reminders, progress and records kept. You can take it back at any time.
- R4.8 After a few months the librarian may ask once whether you still want a paused book. If you say no, it doesn't ask again.

## 5. Choosing and scheduling (readers' advisory)

### 5.1 A day

| Time (default, adjustable) | What happens |
|---|---|
| Once during the day | The librarian messages you: what would you like to read tonight? It offers 2–3 suggestions, each with a one-line reason |
| During the day | You answer, change your mind, drop links, or just talk; it also learns how familiar you are with the ideas involved |
| Evening cut-off (e.g. 19:00) | Tonight's piece is settled. If you haven't replied, it picks one by the plan and prepares and reads as usual |
| Before bedtime | It sends the reading guide and notes to the chat, and prepares the talk for the reading room |
| Bedtime | The reading session on a Kindle, phone or iPad (section 6) |
| Afterwards | The evening's reading report is written and filed |

Bedtime is the default; it can be moved to the morning or any other time.

### 5.2 Monthly rhythm (default template, editable)

- One paper a week, alternating classic and new
- Two or three long-form pieces a week
- One book in chapters, about a month
- One essay a week
- One "review night" a week: nothing new, just this week's questions
- A book in progress is continued before a new one is started (see 4.4)
- A monthly report on the last day: what you read, where your questions clustered, how the knowledge map changed, suggestions for next month

Requirements:

- R5.1 The rhythm template is a config file.
- R5.2 Selection weighs the template, what you said today, the knowledge map (fill a gap or follow an interest) and deduplication.
- R5.3 Every suggestion comes with a reason ("you asked about X twice last week; this piece is about X").
- R5.4 "Not this one" and "too hard" are recorded as feedback.

## 6. The bedtime session (reader instruction)

Three parts, matching the reading report:

1. **Preview: background knowledge.** Ideas, context and terms you may not know before reading. Chosen from the knowledge map: skip what you already know, explain what you don't.
2. **Reading.** Margin's existing talk: what the piece is about, the background, the main points, why it matters. Interrupt with questions at any time.
3. **Review: questions.** Two or three questions after the reading; you answer and get feedback. Then it ends.

Requirements:

- R6.1 The preview can be shortened or skipped.
- R6.2 Review questions can be answered by voice, or in the chat the next day.
- R6.3 Good answers, weak answers and skipped questions all go into the report and the knowledge map.

## 7. Reading reports (circulation records)

### 7.1 One per evening

A Markdown file with a YAML header, readable by people and by agents.

```markdown
---
date: 2026-10-08
title: How octopuses sleep
source: https://...
shelf: long-form
kind: new
minutes: 22
concepts: [REM sleep, cephalopods, chromatophores]
mood: a bit tired, ended the review early
---

# 2026-10-08 · How octopuses sleep

## Why this piece
## Before you read: background
## Notes on the main points
## What I asked and what it answered (verbatim)
## Review questions and my answers
## What I still don't understand
## Threads worth following (possible future reading)
## Related to what I read before
```

### 7.2 Summaries

- Weekly and monthly summaries (monthly report in 5.2).
- The reports folder can be kept in git or opened in a note app such as Obsidian.

Requirements:

- R7.1 Questions and answers are kept verbatim, never replaced by a lossy summary; summaries sit alongside the originals.
- R7.2 The guide and notes are written before the session (the "before bedtime" step in section 5); the questions, answers and review are added after.
- R7.3 Reports can be read and searched over MCP; read access is on by default, write access needs the user's consent.
- R7.4 Reports are written in the explanation language, whatever language the reader asked it to explain in. Quotations from the article stay in the original.

## 8. The knowledge map (knowing the reader)

How does the librarian know whether you understand something?

- **Daytime chats**: a question or two while choosing tonight's piece, or what you happen to say.
- **Past reading reports**: what you asked, what you couldn't answer, which ideas came up several times.
- **Review answers.**

Requirements:

- R8.1 For each concept: where it first appeared, how often it was explained, how often you asked about it, how you did on review, when you last met it, and the current judgement (know, partly, don't know).
- R8.2 The preview uses this to decide which background to give.
- R8.3 Review scheduling borrows a spaced-repetition algorithm (such as the open-source FSRS), so old questions return at the right time.
- R8.4 The knowledge map is a file you can read and edit. When the librarian is wrong about you, you can correct it.

## 9. Devices: any combination

| Combination | Experience |
|---|---|
| Phone only | Read, listen and ask on the phone, with the mouth optional |
| Kindle + computer | Today's basic setup: the Kindle displays, the computer controls |
| Kindle + phone | The Kindle shows the article; the phone speaks, listens and shows the mouth |
| Phone + iPad | One shows the article, the other is the mouth |
| Any of these + more screens | Extra mouths speaking in sync |
| Chat only | No session; reading guides and reports arrive in Telegram, and you discuss them there |

Requirements:

- R9.1 Each combination starts with one command or one QR code.
- R9.2 The mouth (robot_lipsync) is always optional.
- R9.3 Every combination currently needs a computer or home server running in the background. The docs say so.

## 10. Privacy (confidentiality)

A real librarian never discloses what you borrowed, so everything stays on your own machine.

- R10.1 The collection, reports, knowledge map and chat history are stored in a local folder.
- R10.2 Calls to language and voice services send only what that call needs, never the whole archive. The docs list what each external service receives.
- R10.3 Fully local models (such as Ollama) are an option, at some cost in quality.
- R10.4 Telegram messages pass through Telegram's servers; users are told this plainly. Those who mind can use only the local web page or MCP.
- R10.5 One command exports all data; one command deletes it.

## 11. What we borrow

| Part | From | How |
|---|---|---|
| Paper metadata and citations | OpenAlex, Semantic Scholar, arXiv API | Public APIs |
| Scoring new papers against your reading history | The idea behind zotero-arxiv-daily | Borrow the idea, write our own |
| Review scheduling | FSRS (open source) | Library dependency |
| Saved-article sync | Wallabag and Readeck APIs | Optional plugin; call the API, copy no code |
| Telegram bot | A mature library such as python-telegram-bot | Library dependency |
| MCP server | The official MCP Python SDK | Library dependency |
| Memory and reports as Markdown in git | The format idea of The Librarian | Borrow the idea |

Each dependency's licence is recorded in `docs/third-party.md`. No copyleft code (such as AGPL) is copied into this repository; such projects are used only through their APIs.

## 12. Phases

| Phase | Scope |
|---|---|
| **v0.3 Records** | Reading reports written and filed after each session; Q&A never lost; three-part session (preview, reading, review) |
| **v0.4 Collection** | Cataloguing, deduplication, default shelves, adding by hand |
| **v0.5 The librarian starts work** | Telegram bot, daily question, evening preparation, monthly rhythm |
| **v0.6 Agents** | MCP server |
| **v0.7 Knowledge map** | Concept records, preview chosen per reader, spaced review, monthly report |
| Rename | Before v0.3: repository, package, commands, README |

## 13. Decisions

| Question | Decision |
|---|---|
| Command name | Both the full `bibliothecary` and the short `biblio` |
| No reply by the evening cut-off | Pick one by the plan; prepare and read as usual |
| Switching away from a half-read book | See 4.4: progress is kept, the librarian picks a good moment to suggest finishing; if you really don't want it, it goes to the paused shelf, greyed out |
| Separate shelves per language | No. Language is only a catalogue field (R4.4); readers who want to filter by language set that up themselves |
| Language of the reading reports | The explanation language (R7.4) |
