# Contributing

Margin is an experimental multi-device reading companion. Small reproducible improvements, device reports and documentation corrections are welcome.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,elevenlabs,serial]"
python -m pytest
python -m build
```

Keep tests offline: no paid API calls, microphone recording or motor control. Preserve the `margin` and `robot_lipsync` APIs unless a migration is documented. Include the device/browser and a reproducible case for mobile changes. Do not treat a filmed demo or simulated trace as reliability evidence.

Use your own credentials in an ignored `.env`. Remove personal speech, local paths and secrets from shared logs. New third-party code or data needs a compatible license and attribution.

For mouth planning and optional hardware tools, preserve visible speech landmarks, the append-only event contract and the physical timing labels. See [mouth architecture](docs/architecture.md) and [research boundaries](docs/third-party.md).

## Keeping the changelog

Every change that a reader or user would notice goes into both [CHANGELOG.md](CHANGELOG.md) and [CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md), under "Unreleased" ("未发布"), in plain words: what you can now do, or what was wrong and is fixed. A release moves those lines under its version number and date, and gets a git tag (`v0.4.0`).
