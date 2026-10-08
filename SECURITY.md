# Security and data handling

## Current scope

Margin is an experimental service for a trusted local network. Its reader and control endpoints do not implement user authentication. Do not expose it directly to the public Internet. HTTPS enables mobile microphone access; it does not add account authentication.

## Where data goes

- Kindle: receives article text, highlights, notes and generated explanations.
- Primary phone/iPad: plays speech and captures questions through its microphone.
- Computer: receives microphone audio and runs the companion.
- Configured model provider: receives question audio for realtime/transcription and article context for answers or lesson creation.
- Configured voice provider: receives text to synthesize speech.
- With `MARGIN_ALIGN=elevenlabs` and non-strict fallback, generated audio can be uploaded for forced alignment. The example uses `MARGIN_ALIGN=local` instead.

Reading records are kept in `~/Bibliothecary` (or `$BIBLIOTHECARY_HOME`): each reading's lesson, a verbatim log of your questions and answers, and the reading report. They never leave the computer except as the context of a single model request (the summary at the end of a session sends the article, the talk and that session's questions and answers). Delete a reading's folder to delete its records.

`margin.log` can contain question text. Optional speech caches contain generated audio, spoken text and timing. Store and delete them locally as appropriate; they are ignored by the repository.

Keys come from environment variables, an ignored `.env`, or your own macOS Keychain entry. Local HTTPS keys are stored in `~/.margin/tls`. Do not commit keys, certificates, recordings or private articles.

## Supported snapshot and reporting

This is the experimental 0.3 series. Report non-sensitive security issues in the repository; for a sensitive vulnerability, use GitHub private vulnerability reporting if enabled. Do not post credentials or recordings in a public issue.

Optional OLED and serial tools do not supply a full actuator safety system. Robot-head and mechanical-arm control from the filming setup is not included.
