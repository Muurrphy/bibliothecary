# Demo video capture guide

Two videos serve different purposes and should both be kept.

## 1. Breadboard engineering evidence — record now

Goal: prove that real hardware, real audio, and real mouth motion run together without hiding the wiring or cutting around failures.

- Use one continuous 30–60 second take.
- Frame the OLED, controller boards, and speaker together; the laptop terminal may sit in the background.
- Run one short response, one rounded/open-vowel response, and one longer two-sentence response.
- Keep original audio. Do not replace it with a clean soundtrack.
- Put the commit SHA, board, display, sample rate, and test sentence in the caption.
- State clearly that this is a breadboard prototype, not the final industrial design.

This video belongs in the technical/benchmark section, not as the sole hero asset.

## 2. Installed robot hero — record after chest assembly

Goal: let a viewer understand the project in under 20 seconds.

- Show the complete head and chest; do not crop away the fixed mask.
- Begin with the robot listening/thinking, then capture the first audible response and synchronized chest mouth.
- Use two or three short uncut exchanges and one dramatic open-vowel moment.
- Keep the first response latency visible instead of trimming directly to speech.
- Target a 15–30 second main clip, plus the longer unedited source take.

Use this installed version at the top of the README. Link the longer breadboard evidence and raw benchmark separately.

## Phone settings for a blue OLED

- Prefer landscape 4K/30 fps or 1080p/30 fps. A 20 fps OLED can band or beat visibly against 60/120 fps capture.
- Stabilize the phone on a tripod or fixed surface.
- Tap/hold to lock focus and exposure on the OLED, then lower exposure until blue pixels retain shape instead of blooming into a rectangle.
- Use soft room light so wiring and the mask remain visible; do not film in complete darkness.
- Place the phone close enough for clean speaker audio, but avoid touching or moving jumper wires.
- If the native camera still shows rolling bands, try a manual camera app at 1/60 second shutter and 30 fps.

## Demo versus benchmark

A phone video is persuasive visual evidence but not a precise latency instrument. Camera/audio tracks may have their own offsets and frame quantization. Public latency numbers must come from the trace schema and physical device marks; a future microphone/photodiode fixture can provide stronger external verification.

## Repository assets

- Keep the original video outside Git history or attach it to a GitHub Release; video binaries make clones unnecessarily large.
- Put a short compressed WebP/GIF or poster image under `assets/` for the README.
- Link the original MP4 and raw benchmark JSONL next to the commit and hardware configuration that produced them.
