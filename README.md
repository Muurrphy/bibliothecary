# Margin

**An AI reading companion for an old Kindle, with a talking digital mouth on your phone.**

You read on the Kindle. Your phone (or an old iPad) is the companion's voice, ears and face: it reads the article to you in your language, underlines the sentence it is talking about on the e-ink screen, and stops when you ask a question out loud. A small multilingual mouth (Mandarin, English, Spanish) moves with every word.

No Kindle jailbreak, no app to install. The Kindle and the phone just open web pages; a program on your computer does the thinking.

[中文说明](README.zh-CN.md) · [Setup](docs/configuration.md) · [Known issues](docs/known-issues.md)

## Two parts: use them together or on their own

| Part | What it is | Use it alone for |
|---|---|---|
| **Reading companion** (`margin`) | Kindle page with highlights, circled words, margin notes and small diagrams; a prepared talk you can interrupt; spoken questions answered by a model. | Reading with an e-reader and asking questions by text or voice, no mouth needed. |
| **Mouth** (`robot_lipsync`) | Turns speech timing into mouth shapes for Mandarin, English and Spanish. Draws on a browser canvas or a 128×64 OLED (ESP32 firmware included). | Any robot, avatar or small screen that needs lips in step with a TTS voice. |

Together, the mouth runs on the phone while the companion speaks, so the phone on your bedside table becomes a small face that reads to you.

This repository used to be **robot-lipsync**. In October 2026 the mouth and the Kindle companion were merged here, because each makes most sense with the other. The full history of the mouth project is kept.

## What each device does

| Device | Job |
|---|---|
| Kindle (or any e-reader with a browser) | Shows the article, the underline, the notes. Does not record anything. |
| Phone or iPad | Plays the voice, listens for your questions, shows the mouth. |
| Computer | Runs the talk, calls the models, prepares voice and mouth timing. |
| More phones or tablets (optional) | Extra mouths, all speaking at the same moment, without their own microphone. |

All devices need to be on the same Wi-Fi.

## Quick start

Python 3.11 or newer.

```bash
git clone https://github.com/Muurrphy/margin.git
cd margin
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# no keys, no cost: open the reader with a sample lesson
margin serve examples/village.lesson.json --voice silent --paused
```

Open the printed `http://<computer>:8765/` on the Kindle (Experimental Browser) and `http://localhost:8765/remote` on the computer to play, pause or type a question.

Only the mouth:

```bash
robot-lipsync demo --text "你好，世界。" --language zh-CN --output build/mouth.html
```

This preview uses made-up timing; with a real voice the timing comes from the speech service. See the [mouth guide](docs/lipsync.md).

## With voice and spoken questions

```bash
cp .env.example .env      # add your OpenAI and ElevenLabs keys and a voice id
margin serve examples/octopus.lesson.json --voice elevenlabs --paused
```

On the phone, open the printed `https://…:8765/speaker` address and tap the screen once. The phone needs the computer's local certificate for the microphone (steps in [setup](docs/configuration.md#https-on-the-phone)). In Safari, set **Website Settings → Microphone → Allow** for this address, or it asks again every time the page opens.

Then just talk. Ask anything and it answers, then goes back to where it was. Short commands run at once without a model: **继续 / go on**, **等一下 / wait**, **再说一遍 / say that again**, **跳过 / skip**, **从头讲 / start over**, **刷新 / refresh**. The device you tapped last is the one that listens; the others stay quiet mouths.

## Your own article

```bash
margin build https://example.com/article --explain "Simplified Chinese" --bedtime -o tonight.json
margin serve tonight.json --voice elevenlabs --paused
```

The talk is prepared ahead (what the piece is about, the background, the main points in order, why it matters), so you get the whole story even if you never interrupt. Sample lessons: a village where everyone signs, how octopuses sleep, bumblebees playing with balls, and a short neutrino primer.

## How it works

```text
computer: lesson + your question → answer → voice + character timing
   ├─ Kindle: article, underline, notes      (one long-poll page, plain ES5)
   └─ phone:  voice + mouth (robot_lipsync)  microphone → realtime model
```

- **The Kindle is a thin page.** Text and about 200 lines of old-style JavaScript, so it runs in the Kindle browser. Every request has a time limit and the page redraws itself if anything goes wrong, so it does not freeze after a Wi-Fi blink.
- **The model never draws on the screen directly.** It returns the same small steps a hand-written lesson uses, and every step is checked against the article.
- **Questions are heard while you speak.** The phone streams your voice to the computer, which forwards it to an OpenAI realtime model; when you stop, the answer is already being written. If that path stalls, it falls back to speech-to-text plus a text model.
- **The answer is spoken sentence by sentence**, so the first sentence starts while the rest is still being voiced.
- **The mouth follows real timing.** The voice service returns when each character is spoken; the mouth module turns that into mouth shapes, and the phone draws them on its audio clock.

More: [architecture](docs/device-companion.md), [mouth module](docs/lipsync.md), [languages](docs/multilingual.md), [data handling](SECURITY.md).

## Status

Early prototype, used to film demos on a Kindle (10th gen, firmware 5.16), iPhone and iPad. Version 0.2.2 fixed the freezes and missed questions seen while filming; long everyday sessions on phones are still being tested. See [known issues](docs/known-issues.md).

## Development

```bash
pip install -e ".[dev,elevenlabs,serial]"
python -m pytest
```

Tests run offline: no API keys, microphones or motors. [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Merge history](docs/migration.md)

## License

MIT.
