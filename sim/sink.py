"""Receive live register values (one JSON line each) and keep them in one file for the simulator.

Each line is merged into the file, which is replaced atomically, so the
simulator never reads half a file.
"""

import json
import os
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
state: dict = json.loads(out.read_text()) if out.exists() else {}
for line in sys.stdin:
    try:
        update = json.loads(line)
    except ValueError:
        continue
    for key, regs in update.items():
        state.setdefault(key, {}).update(regs)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, out)
