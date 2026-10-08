# Changelog

## 0.3.0 — 2026-10-08

The project is now **Bibliothecary**, a personal librarian (Chinese: 图书管理员). Margin stays as the name of the reading room, and the mouth stays optional. See the [requirements](docs/requirements.md).

- `biblio` (also `bibliothecary`): `prepare` an article, `read` it, rewrite its `report`, list the `records`.
- Three-part sessions: background before the reading (preview), the reading, and review questions after it. The player waits for your answer to each review question; "继续 / go on" skips one. The Kindle shows YOUR TURN meanwhile.
- Circulation records: every question and answer is appended to the reading's `session.jsonl` as it is said, and a Markdown reading report is written when the session ends or the program is stopped. With a model, the report adds what still seems unclear and which threads are worth following, next to the verbatim record.
- Readings are kept in `~/Bibliothecary` (or `$BIBLIOTHECARY_HOME`), on this computer only.
- `margin build` takes `--no-preview` and `--review N`; the octopus example has a preview and two review questions.
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
