# Testing Sungrow Alive

Thank you for trying it. This page says how to start safely, what to check, and what to send.

## Start read-only

1. Install through HACS (custom repository, category *Integration*) and restart Home Assistant.
2. **Settings → Devices & services → Add integration → Sungrow Alive**, and give the Logger's address.
3. Before anything else, open **Configure → Settings** and turn on **Read only**. Nothing is then
   written to any device, whatever a button or automation asks.

If the Logger is already read by something else (the Sungrow app is fine; another Modbus
integration, a YAML package or a VPP's own controller is what matters), also turn on **Gentle
pace**. The Logger has one shared bus behind it and answers slowly when several clients ask at once.

## What to check

- **The search.** It should list every inverter, battery tower, the meter and the Logger, with model
  and serial number, and put each tower under the right inverter. A missing or wrong device is the
  most useful thing you can report.
- **Readings against the Sungrow app.** Solar, battery and grid power, battery level, and today's
  energy totals should match the app (or the inverter's screen) within a few percent, allowing for
  the app's own delay.
- **Nothing stays unavailable.** An entity that never gets a value, or drops out often, is worth a
  report. Some entities read *unknown* by design on some setups: an inverter's own import and export
  power read nothing when the grid meter is connected to the Logger instead of the inverter.
- **The Sungrow dashboard** in the sidebar: every page should load and show your devices.

## Writing (only when you are ready)

Turn **Read only** off only once the readings look right. Then try one setting at a time from the
device page (for example the EMS mode or a battery limit) and check that the Sungrow app shows the
same value. Every write is read back, and a write that does not take shows in the log.

## What to send

Open an issue: **Something is wrong** for a fault, **My setup works** for a setup report. Attach the
diagnostics file (**⋮ → Download diagnostics** on the integration's page). It holds what the
integration found and its last readings, with serial numbers and the Logger's address removed.
For a fault, add the log lines filtered on `sungrow_sh_t`.
