# Changelog

## Unreleased

- Whole books. An EPUB, TXT or PDF goes on the shelf (`~/Bibliothecary/books/`), cut into chapters along its own contents; Project Gutenberg's wrapper, contents pages and indexes are left out. EPUB is read with the standard library (no AGPL dependency). The librarian keeps your place and prepares one part at a time, read in one of three ways: the text itself (quiet, notes only on real difficulties, the place moving at reading pace, open questions with no right answer), a digest (a map of the whole book first, then a chapter at a time) or the best passages (whole paragraphs chosen by number, so never misquoted, with a sentence on what lies between them). No spoilers: chapter notes are made only as far as you have read, and the "previously" and the answers stay behind your place. `biblio book add|list|show|next|mode|pause|resume`; in Telegram send the file, then `/book`, `/books`, `/mode`, `/next`. While a book is open, the daily round continues it. A waiting part that will not be read (the way of reading changed) is moved to `readings/_set_aside/`, never deleted.
- Open review questions (`margin.brain.OPEN`): the answer is responded to, not graded, and the report shows what to think about instead of a model answer.
- A lesson can carry a `guide` for the answering model (which book, what was read before, no spoilers).
- The librarian introduces itself once, asks what time you usually read, and keeps a daily round around that time: a morning or evening greeting, then a reading chosen and prepared before you sit down. `/time` changes the time.
- While reading, questions about recent facts ("查一下", "最新", "今年" …) are answered after a web search.
- The librarian offers only pieces that can be read in full, prepares one only once it is chosen, and can look up recent facts before choosing.
- The voice is picked automatically, and the player says so when there is none.
- For filming: every spoken line can be kept (`MARGIN_RECORD_DIR`), and `margin stitch --start` builds one track aligned to a screen recording; lines are stitched in full unless they were really interrupted. A rehearsed demo mode is included.
- Phone captions show whole lines (three at most); a review answer may pause before it counts as finished; "再问一遍" asks a review question again.
- Every problem met while filming the first demo is logged in `docs/logs/`.
- Mouth timing: remove the default visual lead and the 70 ms event floor that let short phonemes overlap their neighbours. Serialized event boundaries remain non-overlapping after rounding.
- Prepared and cached reading-companion clips now check character timestamps against locally decoded audio. Clearly matched phrase boundaries can be corrected; uncertain matches retain provider timing. This is phrase-edge correction, not forced phoneme alignment.
- Send measured speech windows and timing status to the speaker page. The browser mouth returns to rest during detected pauses and continues to follow its audio output clock.
- Add offline regressions for short phonemes, invalid timing, waveform correction, silence and the shared browser renderer. No personal recordings or credentials are included.

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
