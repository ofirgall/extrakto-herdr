#!/usr/bin/env python3
"""Action script: captures the trigger pane ID and opens the extrakto overlay."""
import os
import subprocess
import sys

trigger_pane = os.environ.get("HERDR_PANE_ID", "")
subprocess.run(
    [
        "herdr", "plugin", "pane", "open",
        "--plugin", "extrakto-herdr",
        "--entrypoint", "picker",
        "--env", f"EXTRAKTO_TRIGGER_PANE={trigger_pane}",
    ],
    check=True,
)
