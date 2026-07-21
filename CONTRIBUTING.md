# Contributing

Evidence-backed issues and small, testable pull requests are welcome.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,english]"
pytest
ruff check src tests examples
ruff format --check src tests examples
```

## Design rules

- Keep providers, Articulation IR, planners, and backends separate.
- Never make paid network calls from tests or CI.
- Preserve the append-only hardware contract.
- Protect closure and other visible-speech landmarks before optimizing smoothness.
- Report P50/P95/P99 and failure counts; do not submit a fastest single sample as proof.
- New biological or perceptual claims require a method, comparator, data source, and limitations.
- Do not add third-party code, weights, or data without a verified compatible license.

## Pull requests

Describe the user-visible problem, the chosen trade-off, tests, benchmark configuration, and any regression risk. Include raw traces for performance claims.
