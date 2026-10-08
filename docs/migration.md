# One project, one repository

In October 2026 the Kindle reading companion and the multilingual digital mouth became one project, **Margin**, in one repository.

- The repository is the former `Muurrphy/robot-lipsync`, renamed to `Muurrphy/margin`. GitHub redirects the old address, and the mouth project's full commit history is kept as an ancestor of the merged history.
- The mouth code lives in `src/robot_lipsync`. Its Python import and the `robot-lipsync` command work as before, so it can still be used on its own (robots, OLED screens, avatars). The old `[mouth]` extra remains as a harmless alias.
- `src/margin` is the reading companion. `pip install -e .` installs both.
- A short-lived separate `Muurrphy/margin` repository (two commits, 2026-10-08) was folded in here; its content is identical to the start of the merged history.

The public repository holds code, mouth data, sample lessons, tests, configuration templates, documentation and the optional OLED firmware. Keys, recordings, personal logs, private filming scripts, robot-arm trajectories, device calibration and local certificates are not included.
