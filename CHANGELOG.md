# Changelog

## 0.3.4 — 2026-09-16

- Integrated the concurrent public import's portable PCM buffer reset, which
  avoids relying on `array.clear` across supported Python runtimes.
- Rewrote lineage guidance around the public `c64-sid-py` project and restored
  comprehensive ignores for generated capture, export, and build artifacts.

## 0.3.3 — 2026-09-16

- Updated package repository and release URLs to the public `c64-sid-py`
  repository after the rename.
- Expanded the package description, keywords, README command reference,
  output expectations, and public-project status guidance.
- Audited tracked source and documentation; no further obsolete runtime code
  remained after the 0.3.0 cleanup.

## 0.3.2 — 2026-09-16

- Added `c64sid-inspect` and a parser API example for fast PSID/RSID metadata
  inspection, including machine-readable JSON output.
- Expanded the README with a feature map, quick-start workflow, commands,
  API usage, and example discovery.
- Added package classifiers, keywords, and repository/release metadata for
  clearer package and GitHub discoverability.

## 0.3.1 — 2026-09-16

- Added supported one-based subsong selection to the playback API and
  `c64sid-render --song`.
- Validated render and SID-PRO capture arguments, made command-line failures
  actionable, and report render progress through completion.
- Buffered PCM writing for substantially lower I/O overhead during long
  renders, while preserving standard little-endian WAV output.
- Made `c64sid-to-csv --all` derive an analysis CSV from a raw capture instead
  of silently omitting it.
- Expanded usage, API, and live-example documentation and added regression
  coverage for the playback contract.

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
