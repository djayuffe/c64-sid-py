# Changelog

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
