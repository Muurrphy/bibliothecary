# Generic constrained-device protocol

`robot_lipsync.backends.encode_event()` produces one compact JSON object per line:

```json
{"v":1,"sid":"turn-1","t":42,"d":96,"p":"PRESS","a":[0.01,0.0,0.43,0.18,1.0,0.0,0.0,0.0]}
```

The articulation array order is:

```text
jaw_open, lip_separation, mouth_width, lip_round,
lip_press, lip_protrusion, lower_lip_tuck, asymmetry
```

This JSONL form is intended for bring-up and debugging. Production MCU firmware should negotiate a versioned binary or compact integer format, expose queue capacity, reject session mismatches, and anchor all event times to a declared physical playback start/sample counter.

Recommended message families:

```text
HELLO / CAPABILITIES
RESET <session>
EVENT <session> <relative-time> <duration> <channels>
START_AT <session> <sample-or-delay>
COUNT <session>
END <session>
DIAGNOSTICS
```

Audio writes and motion acknowledgements must use separate names and routing. A generic `OK` or `ERR` on a shared serial stream is not safe enough for concurrent audio, motion, and display control.
