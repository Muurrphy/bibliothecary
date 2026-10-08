# Margin · a reading companion across devices

I wanted to read on an old Kindle and ask questions without switching back to my computer. The Kindle does not need a microphone: a phone or iPad supplies the voice, listens to questions, and shows a small digital mouth while the companion speaks.

Margin brings these pieces into one project. The Kindle opens a lightweight reading page with highlights and notes; a computer runs the lesson and calls the AI services. **No Kindle jailbreak or application installation is required.**

[中文说明](README.zh-CN.md) · [Setup and configuration](docs/configuration.md) · [Known issues](docs/known-issues.md)

> **Experimental snapshot, v0.2.0.** Phone listening is currently intermittent: it sometimes misses speech or does not produce a reply. Playback and mouth timing can also need a page reload. The examples have been used in filmed demos; they are not evidence of reliable everyday hands-free use.

## What each device does

| Device | Role |
|---|---|
| Kindle | Article, sentence highlights, marked words, margin notes and simple diagrams. |
| Phone or iPad | Its own microphone captures your questions; its own speaker plays replies; its screen draws the mouth. |
| Computer | Hosts the pages, runs the lesson, calls the models and prepares speech timing. |
| Extra phone or tablet | Can display a muted mouth without opening another microphone. |

All devices connect to the same local network. The Kindle only needs its browser. It does not record audio. A robot head or mechanical arm is **optional** and is not needed for this project.

## Quick start

Python 3.11 or newer. On macOS or Linux:

```bash
git clone https://github.com/Muurrphy/margin.git
cd margin
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Inspect a lesson and open the reader without API keys or paid calls.
margin check examples/village.lesson.json
margin serve examples/village.lesson.json --voice silent --paused
```

Open the printed `http://<computer-address>:8765/` on the Kindle. Open `http://localhost:8765/remote` on the computer to play, pause or ask a text question. With no API key, the included scripted questions can be used.

The multilingual mouth is included in the same installation. This offline preview uses **synthetic timing**, so it is only a visual example:

```bash
robot-lipsync demo --text "你好，世界。" --language zh-CN --output build/mouth.html
```

Open `build/mouth.html`. No second repository or mouth package installation is required.

## Add voice and questions

Copy `.env.example` to `.env`, then enter your own OpenAI and ElevenLabs credentials and ElevenLabs voice ID. Set a TTS model your account supports if needed. Providers may charge for use.

```bash
cp .env.example .env
# Edit .env before starting.
margin serve examples/octopus.lesson.json --voice elevenlabs --paused
```

On the phone, open the printed HTTPS address with `/speaker?role=primary`, allow microphone access and tap **tap to begin**. The first tap unlocks browser audio. Keep the page visible and the device awake while trying voice questions.

Use `https://<computer-address>:8765/speaker?listen=0&mute=1` for an extra display. With `MARGIN_SINGLE_SPEAKER=1`, only the primary device sends questions and confirms playback.

Mobile microphone access needs HTTPS and a trusted certificate. Margin creates a local certificate using `openssl`; [the setup guide](docs/configuration.md#https-on-the-phone) explains the iPad/iPhone profile steps. Close the foreground terminal session or press Ctrl+C when finished.

The companion follows a prepared lesson and can attempt to answer spoken interruptions before continuing. Short commands include **继续 / go on**, **等一下 / wait**, **再说一遍 / say that again** and **跳过 / skip**. Voice capture remains unreliable in current testing; the computer's `/remote` page is available for text questions.

## Bring an article

```bash
margin build article.txt --explain "Simplified Chinese" --bedtime -o tonight.json
margin serve tonight.json --voice elevenlabs --paused
```

`margin build` can also take an article URL and needs an OpenAI-compatible chat API. Realtime voice questions use OpenAI; other compatible chat services can use the separate transcription-and-answer path with `MARGIN_REALTIME=0`. Transcription availability depends on the provider.

Included lessons cover a signing village, octopus sleep, bumblebee play and a short neutrino primer. These are sample lessons; generated explanations should be checked against their sources.

## Reading and mouth timing

```text
Computer: lesson + questions → speech audio + character timing
            ├─ Kindle: article, highlight, note
            └─ Phone: audio clock → multilingual mouth
                      microphone → question → answer
```

`src/margin` contains the reader, lesson player, voice and browser connection. `src/robot_lipsync` is the integrated mouth module, including Mandarin, English and Spanish articulation, canvas rendering and optional OLED tools. Its Python import and `robot-lipsync` command remain available for reuse.

The live reader currently selects Chinese or English timing heuristically. Spanish is supported by the mouth module's language-tagged API and CLI; automatic Spanish selection in the companion has not been validated.

The example configuration requires character timestamps returned with the generated audio and uses zero manual visual offset. Phoneme positions **within a character** are still estimated. If strict timing is disabled, the existing alignment fallbacks are available; `MARGIN_ALIGN=local` avoids sending generated recordings to a forced-alignment service.

See the [mouth module guide](docs/lipsync.md), [architecture](docs/device-companion.md), [language profiles](docs/multilingual.md) and [limitations](docs/known-issues.md).

## What is included

- Reader and phone pages, live and scripted question paths, voice adapters, example lessons.
- Multilingual mouth source, renderers, alignment fixtures, tests and schemas.
- Optional ESP32 OLED firmware and tools from the original mouth project.
- Historical latency tooling; simulated traces and old hardware measurements are labeled and do not establish this companion's response time.

Personal recordings, hardware calibration, robot trajectories, private filming scripts, keys and local certificates are not distributed. [Data handling](SECURITY.md) describes where speech and article text go during use.

## Development

```bash
pip install -e ".[dev,elevenlabs,serial]"
python -m pytest
python -m build
```

CI runs offline tests, checks lesson examples, builds the combined package and exercises the mouth preview. No API keys, microphones or motors are used by the tests.

[Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Merge history](docs/migration.md)

## License

MIT. The earlier [robot-lipsync repository](https://github.com/Muurrphy/robot-lipsync) is retained as a historical source; ongoing companion development is in this repository. Linked research and service providers retain their own terms. Third-party model weights, full articles and voice recordings are not bundled.
