# One project, one repository

On 2026-10-08 the Kindle reading companion and multilingual digital mouth were consolidated under **Margin**.

The mouth implementation was imported from `Muurrphy/robot-lipsync` at commit `8b90e617de9af3bc5d8c33d94d40e19735abe951`, under the same MIT license. Source, renderers, articulation data, language rules, fixtures, tests, schemas, OLED firmware, generators and benchmark tools are included. The earlier repository remains available for its history.

`pip install -e .` now installs both `margin` and `robot_lipsync`, plus the English and Mandarin language dependencies. `margin` and `robot-lipsync` command names are retained. The old `[mouth]` extra remains as a compatibility alias and no longer fetches a second GitHub repository.

The original local reader history is retained locally. The public repository starts with a clean combined source snapshot and GitHub noreply commit metadata. Previously developed reliability and voice-profile changes are published with this snapshot. They do not constitute a new fix for the observed intermittent phone capture. The public examples are original lesson texts; private recordings, calibration, account-specific settings and filming archives stay local.
