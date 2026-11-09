# Changelog

What changed in each release of Sungrow Alive. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Releases before 1.0 are betas.

## [Unreleased]

## [0.1.1] - 2026-11-09

For testers. No change to readings, entities or writes.

- **Download diagnostics** (⋮ on the integration's page). It holds what the
  integration found, the read plan, the connection's counters and every last
  reading with its age. The Logger's address and every serial number are removed.
- Issue templates for a fault and for a setup report, and a
  [testing guide](docs/testing.md): start in *Read only*, check the search and
  the readings against the Sungrow app, then report.

## [0.1.0] - 2026-11-09

The first public release.

- Finds what sits behind the Logger: inverters, battery towers (and which
  inverter each belongs to), the meter and the Logger, with model, serial and
  firmware.
- One serialized Modbus connection, block reads, polling by need, and validated
  decoding.
- Control writes (EMS mode, forced charge and discharge, limits), confirmed by
  reading back. A *Read only* setting turns them off.
- A move from a Modbus YAML package keeps every entity id.
- A ready-made Sungrow dashboard.

[Unreleased]: https://github.com/code-imstillalive/sungrow-alive/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/code-imstillalive/sungrow-alive/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/code-imstillalive/sungrow-alive/releases/tag/v0.1.0
