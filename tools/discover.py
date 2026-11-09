"""Run discovery from the command line (the simulator, or a real Logger only with its owner present).

    python tools/discover.py <host> <first port> [ports to try]
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "custom_components"))

from sungrow_sh_t.discovery import discover, open_ports
from sungrow_sh_t.scheduler import OwnTransport


async def main(host: str, first: int, count: int) -> None:
    t = OwnTransport(host, 1.5)
    try:
        ports = await open_ports(host, range(first, first + count))
        r = await discover(t.read, ports)
    finally:
        t.close()
    print(f"{len(r.devices)} devices, Logger says {r.expected}, {r.probes} probes, {r.seconds} s, complete: {r.complete}")
    for d in r.devices:
        print(f"  {d.key:10} port {d.port} unit {d.unit:3}  {d.model or ''} {d.serial or ''}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 8))
