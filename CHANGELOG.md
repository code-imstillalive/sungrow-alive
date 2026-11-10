# Changelog

What changed in each release of Sungrow Alive. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Releases before 1.0 are betas.

## [Unreleased]

## [0.1.4] - 2026-11-10

- **No more "Custom element doesn't exist: sungrow-app" after a refresh.** The
  cards were loaded as Home Assistant's extra module, which can arrive after a
  dashboard is built; on a panel view Home Assistant then never builds the card
  again. The integration now registers the cards as a **dashboard resource**,
  the way HACS cards load, and adds the extra module only where there is no
  resource store (a dashboard in YAML mode). A resource for the file added by
  hand is updated to the current version, not added twice. Adding that resource
  by hand stopped the fault on the install where it happened.
- The 0.1.2 and 0.1.3 rebuild and swap workarounds are removed; neither worked
  on Home Assistant 2026.10's panel view.
- **3D house: the grid line shows which way power goes**: red while importing,
  green while exporting (the cards' own import and export colours), and the
  usual faint blue when the grid is idle.
- The integration now depends on Home Assistant's `lovelace`, so its resource
  store is ready first.

## [0.1.3] - 2026-11-10

- **The stuck "Custom element doesn't exist: sungrow-app" after a refresh, fixed
  properly.** 0.1.2 asked the error card to rebuild; on Home Assistant 2026.10's
  panel view that request is ignored (tested on the install: the error card was
  found and asked, and stayed). The cards now replace such an error card with
  the real one themselves and keep it fed with Home Assistant's live state,
  looking every second for 30 s after loading and after each move between
  dashboards.

## [0.1.2] - 2026-11-10

- **The Sungrow dashboard no longer sticks on "Custom element doesn't exist:
  sungrow-app"** after a refresh. A dashboard built before the cards finished
  loading showed Home Assistant's "Configuration error" and, on a panel view,
  did not build the card again once it had loaded (a resize or a hard refresh
  brought it back). The cards now ask any such error card to rebuild as soon as
  they are loaded.
- The dashboard the integration lays out is titled **Sungrow Alive**, and so is
  the app's own heading when the dashboard sets no title.

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

[Unreleased]: https://github.com/code-imstillalive/sungrow-alive/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/code-imstillalive/sungrow-alive/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/code-imstillalive/sungrow-alive/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/code-imstillalive/sungrow-alive/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/code-imstillalive/sungrow-alive/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/code-imstillalive/sungrow-alive/releases/tag/v0.1.0
