# Security policy

## Credentials

Never commit TTS, LLM, or GitHub credentials. Use environment variables and restricted-scope keys. The core demo and CI require no secrets.

## Reporting

While the repository is private, report security concerns directly to the owner. Before public release, GitHub private vulnerability reporting should be enabled and this section updated with the supported-version policy.

## Physical safety

The software may eventually control actuators. Backends must implement mechanical limits, velocity/acceleration limits, queue bounds, session isolation, and an independent emergency stop. Do not run motor babbling on equipment touching a person.
