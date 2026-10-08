# Known issues — 2026-10-08 snapshot

This is an early personal prototype. Version 0.2.1 addresses the freezes and missed turns seen while filming (see the changelog); those fixes are tested offline and in a desktop browser, not yet over a long session on a real phone.

| Area | Current limitation |
|---|---|
| Phone microphone | In real use, the phone sometimes captures a question and sometimes misses it or produces no reply. The cause has not been conclusively established. |
| Mobile sessions | Audio permission, foreground state, interruptions or session loss can require tapping again or reloading. Do not infer continuous reliable listening from a filmed take. |
| Speech detection | Browser echo cancellation and voice thresholds are present, but can reject quiet speech or allow residual echo. Their contribution to the observed failures is unconfirmed. |
| Provider / network | API calls and local Wi-Fi can fail. Existing timeout and playback-error handling are included; this does not resolve every stalled or missed turn. |
| Mouth alignment | Native character timing is used when available; phonemes within a character are estimated. Exact human articulation is not demonstrated. |
| Models | Not every voice model offers timestamps or accepts the same settings. Strict mode reports a failure rather than substituting estimated timing or changed voice settings. |
| Language selection | The companion selects Chinese or English heuristically. Spanish support belongs to the explicit language-tagged mouth API/CLI. |
| Devices | A Kindle 10th generation (firmware 5.16) and iPad Safari have been used. Phone capture is intermittent; Android and other e-readers do not have a completed compatibility evaluation. |

The computer's `/remote` page offers text questions and controls when voice input fails. Keep the service in a foreground terminal so it can be stopped and reopened. These are fallback controls, not a claim that mobile listening is fixed.

The repository includes deterministic offline tests and package checks. Those verify particular code paths and fixtures; they do not measure real phone speech detection, acoustic echo behaviour or everyday reliability. Historical mouth-project traces and simulated benchmark results are not Margin end-to-end measurements.

To report a problem, include device/browser, foreground or home-screen mode, the relevant settings and a short reproduction. Remove keys, personal speech, full article text and local certificates from any logs you share.
