# Changelog

## 0.3.0 — 2026-09-16

- Removed the duplicate experimental `patches` package and its disconnected
  helpers, retired documentation aliases, compatibility shim, redundant fix
  verifier, and nonfunctional VGM command.
- Added a runnable live SID tone renderer using the maintained `SidChip` path.
- Reduced packaging and documentation to maintained APIs and commands only.

## 0.2.0 — 2026-09-16

- Repaired binary SID-PRO parsing: mandatory EOF, complete headers, CRC/flag,
  compression, trailing-data, and event-stream validation.
- Fixed BPM onset detection to use gate rises and made pattern identifiers
  stable across Python processes.
- Replaced misleading enhanced “cycle-exact” vectors with passing deterministic
  component smoke checks.
- Reworked the `patches` wrapper so every public option is applied to managed
  SID chips; unsupported full-C64 feature claims were removed.
- Added installable CLI entry points and included tools/top-level compatibility
  modules in wheels.
- Rewrote release documentation around supported behavior and Python 3.10+.

## 0.1.0

Initial experimental source release.
