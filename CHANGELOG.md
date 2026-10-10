# Changelog

## Unreleased

### 0.5.0a1 preview

- Serialize reading handoff, restore checkpoints and context, merge stale book updates, and restrict protected answers to reached paragraphs.
- Keep every captured reader utterance before answering, including comments, tangents and interrupted turns. Preserve a verbatim transcript plus automatically organized notes with original evidence. Do not archive microphone audio.
- Add SQLite migration/backup, sourced and correctable memory, history retrieval, catalogue filtering/deduplication, explicit review evidence and learning plans.
- Move slow Telegram work to durable jobs; add cancellation, uncertain recovery, time zones, health and opt-in macOS startup without dependency upgrades at launch.
- Preserve the original magazine-like phone design. New capabilities primarily belong to the librarian's conversation.
- This is a preview; device and seven-day usage acceptance are pending. See [acceptance](docs/longterm-acceptance.md).

## 0.4.0 — 2026-10-09

### New: whole books

- Send an EPUB, TXT or PDF (in Telegram, or `biblio book add <file>`). It goes on the shelf in `~/Bibliothecary/books/`, cut into chapters along the book's own contents. Project Gutenberg's header and licence, Standard Ebooks' title page, imprint, colophon and endnotes, contents pages and indexes are left out. EPUB is read with the standard library (no AGPL dependency).
- The librarian keeps your place and prepares one part at a time. A part counts once you finish it; then your place moves on.
- Three ways to read, suggested from the kind of book and changed with `/mode`:
  - **text** (读原文): you read the text yourself; notes only where a reader gets stuck, the place moving at reading pace, one or two open questions at the end that are answered, not graded;
  - **digest** (拆书): a map of the whole book first (its question, its answer, how it is built, the chapters that matter), then a chapter at a time;
  - **excerpts** (精华原文): the few passages of a chapter most worth reading, whole paragraphs taken by number so nothing is ever misquoted, with a sentence on what lies between them.
- No spoilers: chapter notes are made only as far as you have read, and the "previously" and the answers during reading stay behind your place.
- Telegram: `/book`, `/books`, `/mode`, `/next`, `/book pause`, `/asbook`. While a book is open, the daily round prepares its next part instead of choosing an article, and the daily message says so.
- Command line: `biblio book add | list | show | next | mode | pause | resume`.
- The map, the notes and the choice of passages use `BIBLIOTHECARY_BOOK_MODEL` (else `BIBLIOTHECARY_CHAT_MODEL`); chapter summaries use the main model. Session length: `BIBLIOTHECARY_BOOK_MINUTES` (default 20).

### New: the library's own books

- A list of 27 public-domain books on two shelves, life and mind and civilization and essays (`catalog.toml`). Books are fetched only from Standard Ebooks, Project Gutenberg and Wikisource; each is public domain in the United States, and its author and translator died more than 70 years ago. Telegram `/library`, `/get <id>`; command line `biblio book catalog`, `biblio book get <id>`. Your own entries go in `~/Bibliothecary/catalog.toml`.
- A sample book ships with the project: Seneca, *On the Shortness of Life* (Aubrey Stewart, 1900), from the Standard Ebooks edition (CC0), made by `tools/make_sample_book.py`. `/get sample`.

### New: a daily round at your own time

- The librarian introduces itself once, asks when you usually read, greets you in the morning or evening and has a reading ready before that time. `/time` changes it.
- It offers only pieces that can be read in full, prepares one only once it is chosen, and can look up recent facts before choosing.

### While reading

- Questions about recent facts ("查一下", "最新", "今年" …) are answered after a web search.
- Phone captions show whole lines (three at most); a review answer may pause before it counts as finished; "再问一遍" asks a review question again.
- The voice is picked automatically, and the player says so when there is none.
- Open review questions (`margin.brain.OPEN`) are responded to, not graded; the report shows what to think about instead of a model answer. A lesson can carry a `guide` for the answering model.

### Filming and the mouth

- Every spoken line can be kept (`MARGIN_RECORD_DIR`), and `margin stitch --start` builds one track aligned to a screen recording; lines are stitched in full unless really interrupted. A rehearsed demo mode is included. Every problem met while filming the first demo is logged in `docs/logs/`.
- Mouth timing: no default visual lead and no 70 ms event floor, so short phonemes no longer overlap. Prepared clips check character timestamps against the decoded audio; the browser mouth rests during detected pauses.

### Fixed while trying it out (2026-10-09)

- A long paper sent as a PDF or TXT was taken for a book. Now a TXT or PDF is a book only when it is very long, or long with real chapters ("Chapter 3", "第三章"); `/asbook` turns the last file into a book when it really is one.
- With a book paused, the daily round and `biblio read` could still offer its waiting part (they took the oldest unread reading). Now the open book's part comes first, and parts of paused books are not pushed.
- `/next` while a part was still unread said "preparing" and sent the same part again; it now says the last part comes first.
- `/get` with a name not on the list said "fetching" before failing; it now answers at once.
- `biblio book next <name>` did not find a catalog book by its English title, author or id when the shelf name was Chinese.
- Chapter cutting, checked on all 27 books of the list: the contents level is chosen so no single piece holds most of the book (On Liberty came out as one chapter); a book whose contents name only the title is cut at its own chapter headings (Emerson's Nature); a numbered sub-chapter carries its part's name ("On Anger · I"); page numbers are taken off titles; "Chapter Summary" entries join their chapter; "Detailed table of contents", "Transcriber's notes", glossaries and endnotes are left out.
- Book sizes in Chinese read "约 2.7 万词" instead of "约 198 千词", ancient years read "公元前 380 年", and a book's word count is counted, not estimated.

## 0.3.0 — 2026-10-08

The project is now **Bibliothecary**, a personal librarian (Chinese: 图书管理员). Margin stays as the name of the reading room, and the mouth stays optional. See the [requirements](docs/requirements.md).

- `biblio` (also `bibliothecary`): `prepare` an article, `read` it, rewrite its `report`, list the `records`.
- One phone is enough: `/phone` shows the article above and the voice, microphone and mouth below, with a phone layout for the text (full width, notes as cards under their sentence). `biblio telegram` keeps a reading room open, and each prepared reading (and tonight's) comes with a **Read on this phone** button that opens it there; the Kindle shows whatever is open. Switching readings files the last one's report. `--no-room` turns this off.
- The reference desk: the librarian now asks what you have been thinking about and what the reading is for before recommending, explains why each piece suits you, and remembers what it learns (`reader.json`, `/profile`). Search results are vetted by a strict second pass (on topic in the sense you mean, substantial, credible); dropped results never reach the conversation, and it searches again from other angles rather than padding. "Interesting" or "light" requests go to the science and essays shelves before papers. Paratext and retracted works are excluded from paper searches.
- `BIBLIOTHECARY_CHAT_MODEL` / `--chat-model`: a separate, stronger model for conversation and vetting. `biblio chat` talks in the terminal with the same memory and prints each search with what was kept and why.
- The collection: web searches only look at the sites on one shelf of `shelves.toml` (science, news, essays, books), and results from any other site are dropped. Readers adjust it in `~/Bibliothecary/shelves.toml`. The librarian prefers primary sources (for a Nobel Prize, nobelprize.org's own explanations) and never offers market or celebrity news. Classic papers need at least 100 citations; new ones are the most noticed of the last year.
- The librarian can look things up: open-access papers through OpenAlex (arXiv as fallback), classic or new, and the web through OpenAI's web search. In the chat it suggests two or three with reasons and prepares the one you choose; only links it actually found can be prepared. PDF papers (links or files) are read with their reference lists left out.
- Reasoning models (gpt-5…, o-series) are given room to think on top of the reply, and an empty, cut-off reply is asked again without a limit. Before, the librarian's chat came back empty with gpt-5-mini. `MARGIN_REASONING_EFFORT` sets the effort.
- `biblio telegram`: the librarian in a Telegram chat, paired with one person. Links, files and voice messages are prepared and the guide is sent back; free chat knows your records; a daily question at noon, tonight's reading in the evening, and the reading report after each session. The chat is kept in `~/Bibliothecary/chat.jsonl`.
- Three-part sessions: background before the reading (preview), the reading, and review questions after it. The player waits for your answer to each review question; "继续 / go on" skips one. The Kindle shows YOUR TURN meanwhile.
- Circulation records: every question and answer is appended to the reading's `session.jsonl` as it is said, and a Markdown reading report is written when the session ends or the program is stopped. With a model, the report adds what still seems unclear and which threads are worth following, next to the verbatim record.
- Readings are kept in `~/Bibliothecary` (or `$BIBLIOTHECARY_HOME`), on this computer only.
- `margin build` takes `--no-preview` and `--review N`; the octopus example has a preview and two review questions.
- From the first real run: the background is no longer lost when the model writes it as plain sentences; the talk retells instead of translating sentence by sentence, with fewer, fuller steps and no notes about the article's structure; web pages go through trafilatura, so menus and news links no longer end up in the reading.
- The Python package is published as `bibliothecary`; the `margin` and `robot-lipsync` commands are unchanged.

## 0.2.2 — 2026-10-08

- One repository: the former robot-lipsync repository now holds Margin, with the mouth project's history kept. READMEs rewritten around the two parts (reading companion, mouth) that work alone or together.
- Phone and tablet: audio is uploaded one request at a time with whatever has piled up, to reduce queued microphone audio on slow Wi-Fi. The log notes when a question arrived late.
- Answers are voiced sentence by sentence, on their own voice workers, so the first sentence is not stuck behind longer text or lines prepared for later. The log records how long each answer line took to voice.
- A device that lost the microphone to another one says so at the top of the screen; tapping there takes over.
- Setup notes on keeping Safari from asking for the microphone every time.

## 0.2.1 — 2026-10-08

Smoothness fixes from the filming sessions (Kindle stopped moving, questions not heard, slow or
odd replies to simple commands):

- Kindle page: every request has a time limit, a drawing error triggers a full redraw, and a
  watchdog restarts a stalled update loop after a connection interruption or sleep. Saying "刷新" redraws every screen.
- Speaker page: the device tapped last becomes the one that listens and speaks, and reopening the
  home-screen app starts a new microphone and playback session. The microphone is reopened after the
  screen was locked; audio interrupted by a call or Siri resumes by itself when it can.
- A line that fails to play is tried once more and then skipped; the reading only pauses when no
  speaker page is there at all (a reloading page gets 12 seconds to come back).
- Missing character timestamps no longer stop a line: the mouth uses an estimate for it.
- No fixed 0.7 s wait before every line on a single speaker.
- Spoken commands ("继续", "等一下", "从头讲", also in traditional characters) are carried out at
  once on the realtime path instead of waiting for a model answer.
- A realtime answer that has not started within 6 s is asked again through speech-to-text and
  the text model, and the stale connection is replaced. The apology line follows the lesson's
  language.

## 0.2.0 — 2026-10-08

- Consolidated the Kindle reading companion and multilingual mouth into Margin.
- Included both Python namespaces, CLI commands, language dependencies, screen renderers, fixtures, schemas and optional OLED tools in one distribution.
- Included the current reader reliability and explicit voice-profile changes already developed locally: cached speech, bounded waits, playback-error pause, ordered microphone uploads, primary-device handling and audio-clock mouth timing.
- Added original bumblebee-play and neutrino lesson examples.
- Added English and Chinese project descriptions, setup, data handling, known issues, contribution guidance and unified offline CI.
- Documented intermittent real phone capture. Mobile capture remains under testing.

## Earlier mouth-module history

The original mouth project is retained at https://github.com/Muurrphy/robot-lipsync. Its MIT source was imported from commit `8b90e617de9af3bc5d8c33d94d40e19735abe951`; see [migration](docs/migration.md).
