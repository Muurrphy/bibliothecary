# Roadmap and release gates

## v0.1 — independent engineering core

- [x] versioned Articulation IR v1;
- [x] causal incremental compiler;
- [x] visible-speech landmarks and antagonistic width/open constraint;
- [x] dependency-free HTML demo;
- [x] offline alignment provider;
- [x] optional ElevenLabs HTTP timestamp provider;
- [x] latency trace schema and summary CLI;
- [x] deterministic tests and CI;
- [ ] generic ESP32/OLED reference firmware;
- [ ] recorded demo video and hardware timing diagram;
- [ ] controlled 100-turn reference benchmark.

Release gate: one new user can run the demo in five minutes without credentials, understand the IR, and reproduce all tests.

## v0.2 — ecosystem integration

- Pipecat frame processor;
- LiveKit Agents adapter;
- generic serial scheduler with acknowledgements and queue budget;
- optional Rhubarb offline provider;
- Canvas/SVG embedding API;
- OpenTelemetry-compatible trace export.

Release gate: at least two provider paths and two backends pass the same fixtures.

## v0.3 — constrained articulation benchmark

- fixed English landmark-balanced corpus;
- 1/3/4/6-DoF software projections;
- closure, labiodental, rounding, opening, jerk, dwell, event-rate, and sync metrics;
- amplitude-only and discrete-viseme baselines;
- paired perceptual evaluation protocol.

Release gate: public raw results and failure cases, not only a showcase video.

## v0.4 — learned residual

- legally reusable training targets;
- small causal TCN/GRU residual over the rule baseline;
- ONNX/CPU export;
- ablation against pure rules;
- safety projection remains after the model.

Release gate: measurable benefit under a declared metric and no latency/closure regression.

## v0.5 — LeRobot soft mouth

- printable 4-DoF reference CAD;
- LeRobot custom hardware plugin;
- motor-babbling dataset;
- forward model and visual closed-loop controller;
- same sentence on browser, OLED, and physical mouth.

Release gate: the physical mouth beats volume-only and hand-authored baselines on declared landmarks and synchronization.

## Stop rules

- Do not add ML only for marketing.
- Do not add an actuator unless ablation predicts a measurable benefit.
- Do not optimize one latency number while audio quality or turn integrity regresses.
- Do not split the repository until a component has independent users and release cadence.
