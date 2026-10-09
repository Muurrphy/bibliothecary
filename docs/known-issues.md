# Known issues — 2026-10-08 snapshot

Bibliothecary is an early personal prototype. Versions 0.2.1 and 0.2.2 update connection recovery and microphone uploads. These changes have offline tests and desktop-browser checks; long phone sessions remain under testing.

| Area | Current status |
|---|---|
| Phone microphone | Reloading pages, queued uploads and stalled realtime connections have recovery handling. Long sessions and missed turns still need checks on phones. |
| Mobile sessions | Safari may request microphone permission on each visit. After a call or Siri, the page may need a tap to resume. |
| Speech detection | Echo cancellation and voice thresholds can reject quiet speech or admit residual echo. |
| Provider / network | API or Wi-Fi interruptions can stall a turn. The service includes timeouts and playback-error handling. |
| Mouth alignment | Provider timestamps are checked against local waveform pauses when decoding is available. Only clearly matched phrase edges are adjusted; ambiguous timing remains unverified. Phonemes inside each character are estimated. Live phone/iPad synchronization still needs device testing. |
| Models | Timestamp availability and accepted settings depend on the voice model. Strict mode reports unsupported settings. |
| Languages | The companion selects Chinese or English. Spanish is available through the language-tagged mouth API and CLI. |
| Devices | Demonstrations used a Kindle 10th generation (firmware 5.16), iPhone and iPad. Phone capture has been intermittent. Android and other e-readers remain untested. |
| Reading room answers | The answering model in the reading room cannot search the web; asked to look something up, it says it cannot. |
| Starting over | Reloading the page redraws it but does not restart the reading; each Telegram button opens its own reading, and switching readings files the previous one. There is no "start this reading again" command yet (say "再问一遍 / ask me again" to repeat the review). |
| Filming on iPhone | iOS screen recording drops the sound of a page that holds the microphone. Set `MARGIN_RECORD_DIR` and join the lines with `python -m margin.stitch` (see the 2026-10-08 log). |
| Librarian speed | Choosing a reading in Telegram can take one to two minutes: several searches, then every link is opened to check it can be read in full. |

Use the computer's `/remote` page for text questions and playback controls when voice input is interrupted. Run the service in a foreground terminal to stop or restart it.

Offline tests cover code paths, fixtures and packaging. Mobile speech detection, acoustic echo and everyday reliability require device testing. Historical mouth traces and the simulated benchmark adapter are recorded separately from Margin end-to-end tests.

What went wrong while filming the first demo, and how each problem was fixed: [docs/logs/2026-10-08_第一次拍演示视频_问题全记录.md](logs/2026-10-08_第一次拍演示视频_问题全记录.md).

To report a problem, include the device, browser, foreground or home-screen mode, relevant settings and a short reproduction. Remove credentials, personal speech, private article text and local certificates from shared logs.
