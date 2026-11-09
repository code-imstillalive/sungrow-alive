# Sungrow Alive

A Home Assistant integration for Sungrow SH-T hybrid inverters, their battery towers and the grid
meter, all read and controlled over Modbus TCP through a Sungrow Logger (Logger1000, Logger3000,
Logger4000).

An independent project, not made or endorsed by Sungrow. Sungrow is a trademark of its owner.

> **Beta.** It runs a real three-phase site every day, but has been tested on few others. It can
> write to your inverters (EMS mode, forced charge and discharge, limits). Turn on *Read only* in
> its settings if you only want to watch.

## What it does

- One serialized Modbus connection to the Logger, so devices never compete for it.
- Block reads, polled by need: fast for power, slow for totals, once for identity.
- Typed, validated decoding: impossible readings are dropped before they reach Home Assistant.
- Control writes serialized, and confirmed by reading them back.
- Nothing about your site written in code: what sits behind the Logger is found by searching.
- A move from a Modbus YAML package keeps every entity id it had, so history, statistics,
  dashboards and automations carry on unchanged.
- A ready-made Sungrow dashboard for the devices it finds.

### Hardware

- **Inverters:** SH5T, SH6T, SH8T, SH10T, SH12T, SH15T, SH20T, SH25T.
- **Battery towers:** SBR064 to SBR256, SBH100 to SBH350.
- **Meter:** CHINT DTSU666 on the Logger.
- **Logger:** Logger1000, Logger3000, Logger4000, with Modbus TCP on.

Tested so far on a Logger1000 with two SH-T inverters, SBR and SBH towers and a DTSU666 meter.
Reports from other sites are very welcome.

## Installing

**HACS:** ⋮ → *Custom repositories* → add `https://github.com/code-imstillalive/sungrow-alive`,
category *Integration*. Install **Sungrow Alive**, then restart Home Assistant.

**By hand:** copy `custom_components/sungrow_sh_t` into your `config/custom_components/` and restart.

## Setting up

**Settings → Devices & services → Add integration → Sungrow Alive.** Give the Logger's address. The
integration asks each port and device address what it is, and shows what it found before anything is
kept: each inverter, battery tower, the meter and the Logger, with model and serial number, and which
inverter each tower is connected to. Nothing is written to any device during the search.

Every device then has its own page under the Logger: the inverters and the meter sit under the
Logger, and each battery tower under the inverter whose battery stack it is part of.

### Searching again (Reconfigure)

On the integration's page, **⋮ → Reconfigure** searches the Logger again, after adding or replacing a
device, or after a move from YAML (which records no serial numbers). A device found before keeps its
name and every entity id. It is matched by serial number, or by its address on the Logger's bus when
no serial was recorded. A new device is marked *(new)*. One that does not answer this time is kept as
it was, so a busy or switched-off device never loses its entities.

### Configure

- **Settings:** *Read only* (nothing is ever written), *Gentle pace* (for running beside another
  Modbus client on the same Logger), and *This integration's own entities*.
- **Battery towers:** which inverter each tower is connected to. A tower not yet placed shows the
  inverter whose battery voltage it matches right now.
- **Forget a device:** for a device taken away for good. It goes with its entities; a later search
  finds it again if it comes back.

### Moving from a Modbus YAML package

If your Sungrow entities come from `modbus:` YAML, change each hub's `modbus:` key to
`sungrow_sh_t:` and restart. The integration takes those entities over with the same entity ids, and
starts with its own entities off, so the house has exactly the entities it had. Turn them on under
*Configure* when you are ready.

### Writing a register

`sungrow_sh_t.write_register` writes holding registers through the integration's own connection, so
automations and other integrations never open a second Modbus client against the Logger.

## Development

The tests need no Home Assistant. They run the integration against a simulated Logger with an
invented site (`data/synthetic`, written by `tools/make_synthetic.py`):

```bash
pip install pytest
pytest -q tests
```

`python sim/simulator.py` serves the same invented site on local ports, for trying the integration
or `tools/discover.py` without real hardware.

## Credits

Built on Sungrow's published Modbus protocols. The 3D view uses [three.js](https://threejs.org) (MIT)
and Kenney's Car Kit (CC0).

## Licence

MIT. See [LICENSE](LICENSE).
