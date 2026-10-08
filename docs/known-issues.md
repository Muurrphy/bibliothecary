# Known issues — 2026-10-08 snapshot

Margin is an early personal prototype. Versions 0.2.1 and 0.2.2 update connection recovery and microphone uploads. These changes have offline tests and desktop-browser checks; long phone sessions remain under testing.

| Area | Current status |
|---|---|
| Phone microphone | Reloading pages, queued uploads and stalled realtime connections have recovery handling. Long sessions and missed turns still need checks on phones. |
| Mobile sessions | Safari may request microphone permission on each visit. After a call or Siri, the page may need a tap to resume. |
| Speech detection | Echo cancellation and voice thresholds can reject quiet speech or admit residual echo. |
| Provider / network | API or Wi-Fi interruptions can stall a turn. The service includes timeouts and playback-error handling. |
| Mouth alignment | Provider character timestamps anchor the mouth timeline. Phoneme timing within each character is estimated. |
| Models | Timestamp availability and accepted settings depend on the voice model. Strict mode reports unsupported settings. |
| Languages | The companion selects Chinese or English. Spanish is available through the language-tagged mouth API and CLI. |
| Devices | Demonstrations used a Kindle 10th generation (firmware 5.16), iPhone and iPad. Phone capture has been intermittent. Android and other e-readers remain untested. |

Use the computer's `/remote` page for text questions and playback controls when voice input is interrupted. Run the service in a foreground terminal to stop or restart it.

Offline tests cover code paths, fixtures and packaging. Mobile speech detection, acoustic echo and everyday reliability require device testing. Historical mouth traces and the simulated benchmark adapter are recorded separately from Margin end-to-end tests.

To report a problem, include the device, browser, foreground or home-screen mode, relevant settings and a short reproduction. Remove credentials, personal speech, private article text and local certificates from shared logs.
