# Security and data handling

## Scope

Bibliothecary runs on your computer. Its Margin reading room is intended for a trusted local network: reader and control endpoints do not implement user authentication. HTTPS enables mobile microphone access; it does not add account authentication. Keep the reading-room port off the public Internet.

## Local records and external services

- **Local archive:** source materials, reading progress, conversation text and reports are stored under `~/Bibliothecary` (or `$BIBLIOTHECARY_HOME`).
- **Configured model provider:** receives source text and the relevant reading history or conversation context for preparation, answers, recommendations and report organization. Realtime/transcription requests can include microphone audio.
- **Configured voice provider:** receives text to synthesize speech. With `MARGIN_ALIGN=elevenlabs` and non-strict fallback, generated audio can also be uploaded for alignment; the example configuration uses local alignment.
- **Telegram:** receives messages, voice messages, submitted documents, reading links and reports exchanged through the bot. They are subject to Telegram's storage and service policies.
- **Reading devices:** receive article text, highlights, notes, generated explanations and speech. The primary phone or tablet captures microphone input; the computer relays it to the configured speech/model service.

Keeping the archive locally does not make model, speech or Telegram features offline. External services handle requests under their own policies. The project does not promise that no data leaves the machine or that third-party services retain nothing.

## Records, backups and deletion

In the 0.5 preview, SQLite is the primary record store; JSON, JSONL and Markdown files are readable exports or compatibility files. `biblio export` creates a consistent backup and `biblio restore` restores into a new directory. Deleting a reading folder alone does not remove its database records or existing backups. Forgetting a derived preference removes it from personalization but preserves the original conversation. See [upgrade and acceptance](docs/longterm-acceptance.md) for migration and recovery.

## Logs, recordings and credentials

The reading archive keeps text rather than original microphone recordings by default. An explicitly configured filming/recording feature such as `MARGIN_RECORD_DIR` is separate. Optional speech caches contain generated audio, text and timing; `margin.log` can contain question text. Treat these files, backups and exported reports as private.

Keys come from environment variables, an ignored `.env`, or a user-configured macOS Keychain entry. Local HTTPS keys are stored in `~/.margin/tls`. Do not commit credentials, certificates, private source materials or reading records.

## Reporting

See the [README](README.md) and [changelog](CHANGELOG.md) for the current experimental release. Report non-sensitive security issues in the repository; use GitHub private vulnerability reporting for sensitive reports when available. Do not post credentials or private records in a public issue.

Optional OLED and serial tools do not supply an actuator safety system. Robot-head and mechanical-arm control from the filming setup is not included.
