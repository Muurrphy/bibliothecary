# Recording a mouth demonstration

Capture a continuous 30–60 second exchange with the display, controller and speaker visible. Include short and longer responses with different vowel shapes. Retain the recorded audio and report the commit, board, display, sample rate and test sentences alongside the clip.

## Camera settings for a blue OLED

- Use a tripod or fixed support.
- Try 4K/30 fps or 1080p/30 fps. A 20 fps OLED can produce bands at higher camera frame rates.
- Lock focus and lower exposure until individual pixels are visible.
- Use room lighting that shows the assembled hardware.
- Keep the phone near the speaker without moving wires.
- If bands remain, try a manual camera app at 1/60 second shutter and 30 fps.

## Timing measurements

Camera and audio tracks can have different offsets. Use the trace schema and device timing marks for latency measurements. A microphone and photodiode on the same acquisition clock can measure acoustic and visible onset directly.

## Repository assets

Keep large original videos outside Git history or attach them to a release. Use a compressed preview or poster in the README, and link the original recording and trace data with their hardware configuration.
