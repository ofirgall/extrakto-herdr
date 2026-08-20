#!/usr/bin/env python3
"""
extrakto-herdr — extract tokens from herdr pane content and fuzzy-pick them.

Inspired by extrakto for tmux (https://github.com/laktak/extrakto).
Uses extrakto's own extraction library if available, otherwise falls back
to bundled filters.

Flow:
  1. Read pane content via `herdr pane read`.
  2. Extract tokens using extrakto.
  3. Pipe through fzf for fuzzy selection.
  4. Copy to clipboard or insert into the pane.
"""

import os
import re
import subprocess
import sys
from collections import OrderedDict

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PANE_ID = os.environ.get("HERDR_PANE_ID", "")
TRIGGER_PANE = os.environ.get("EXTRAKTO_TRIGGER_PANE", PANE_ID)

# Try to import extrakto from the tmux plugin (reuse its filters/config)
EXTRAKTO_PATH = os.path.expanduser("~/.tmux/plugins/extrakto")
if os.path.isdir(EXTRAKTO_PATH):
    sys.path.insert(0, EXTRAKTO_PATH)

try:
    from extrakto import Extrakto, get_lines
    HAS_EXTRAKTO = True
except ImportError:
    HAS_EXTRAKTO = False


def extract_with_extrakto(text, filter_name="all"):
    """Use the real extrakto library."""
    extrakto = Extrakto(alt=True)
    results = []

    if filter_name == "all":
        for name in extrakto.all():
            results += extrakto[name].filter(text)
        results += get_lines(text)
    elif filter_name == "line":
        results = get_lines(text)
    elif filter_name == "word":
        results = extrakto["word"].filter(text)
    else:
        try:
            results = extrakto[filter_name].filter(text)
        except Exception:
            results = get_lines(text)

    results.reverse()
    return list(OrderedDict.fromkeys(results))


# --- Fallback extraction (if extrakto not installed) ---

BUILTIN_FILTERS = {
    "word": {
        "regex": r"([^][(){}=$\u2500-\u27BF\uE000-\uF8FF\u22C5\u21B4\u2502 \t\n\r]+)",
        "lstrip": ",:;()[]{}<>'\"|",
        "rstrip": ",:;()[]{}<>'\"|.",
        "in_all": False,
        "min_length": 5,
    },
    "path": {
        "regex": r'(?:[ \t\n"([<\':]|^)(~|/)?([-~a-zA-Z0-9_+-,.]+/[^ \t\n\r|:"\'$%&)>\]]*)',
        "exclude": r"[kmgKMG]/s$|^\d+/\d+$",
        "rstrip": '",):"',
        "in_all": True,
        "min_length": 5,
    },
    "url": {
        "regex": r"(https?://|git@|git://|ssh://|s*ftp://|file:///)([a-zA-Z0-9?=%/_.:,;~@!#$&()*+-]*)",
        "in_all": True,
        "rstrip": '",):"',
        "min_length": 10,
    },
    "quote": {
        "regex": r'("[^"\n\r]+")',
        "in_all": True,
        "min_length": 3,
    },
    "s-quote": {
        "regex": r"('[^'\n\r]+')",
        "in_all": True,
        "min_length": 3,
    },
}


def extract_filter(text, filt):
    regex = filt.get("regex")
    if not regex:
        return []
    results = []
    exclude = filt.get("exclude", "")
    lstrip = filt.get("lstrip", "")
    rstrip = filt.get("rstrip", "")
    min_length = filt.get("min_length", 5)

    for m in re.finditer(regex, "\n" + text, flags=re.I):
        item = "".join(filter(None, m.groups()))
        if lstrip:
            item = item.lstrip(lstrip)
        if rstrip:
            item = item.rstrip(rstrip)
        if len(item) >= min_length:
            if not exclude or not re.search(exclude, item, re.I):
                results.append(item)
    return results


def extract_lines_fallback(text, min_length=5):
    return [line.strip() for line in text.splitlines() if len(line.strip()) >= min_length]


def extract_fallback(text, filter_name="all"):
    results = []
    if filter_name == "all":
        for name, filt in BUILTIN_FILTERS.items():
            if filt.get("in_all", True):
                results.extend(extract_filter(text, filt))
        results.extend(extract_lines_fallback(text))
    elif filter_name == "line":
        results = extract_lines_fallback(text)
    elif filter_name in BUILTIN_FILTERS:
        results = extract_filter(text, BUILTIN_FILTERS[filter_name])
    else:
        results = extract_lines_fallback(text)

    results.reverse()
    return list(OrderedDict.fromkeys(results))


def extract_all(text, filter_name="all"):
    if HAS_EXTRAKTO:
        return extract_with_extrakto(text, filter_name)
    return extract_fallback(text, filter_name)


# --- Herdr integration ---

def get_pane_content(pane_id):
    """Read pane content via herdr CLI."""
    try:
        result = subprocess.run(
            ["herdr", "pane", "read", pane_id, "--source", "visible"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except FileNotFoundError:
        pass

    try:
        result = subprocess.run(
            ["herdr", "pane", "read", pane_id],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except FileNotFoundError:
        pass

    return ""


def copy_to_clipboard(text):
    import platform
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
    elif system == "Linux":
        session_type = os.environ.get("XDG_SESSION_TYPE", "")
        if session_type == "wayland":
            subprocess.run(["wl-copy"], input=text.encode(), check=True)
        else:
            subprocess.run(
                ["xclip", "-i", "-selection", "clipboard"],
                input=text.encode(),
                check=True,
            )


def insert_to_pane(text, pane_id):
    try:
        import json
        import socket

        sock_path = os.environ.get("HERDR_SOCKET_PATH", "")
        if not sock_path:
            home = os.environ.get("HOME", "")
            sock_path = f"{home}/.config/herdr/herdr.sock"

        req = json.dumps({
            "id": "extrakto-insert",
            "method": "pane.send_keys",
            "params": {"pane_id": pane_id, "keys": list(text)},
        })
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sock_path)
        s.sendall((req + "\n").encode())
        s.recv(256)
        s.close()
    except Exception:
        pass


def run_fzf(items, filter_name):
    filter_order = ["all", "word", "path", "url", "line", "quote", "s-quote"]
    header = f"enter=copy, tab=insert, ctrl-f=filter [{filter_name}]"

    fzf_cmd = [
        "fzf",
        "--multi",
        "--no-sort",
        f"--header={header}",
        "--expect=ctrl-c,esc,tab,ctrl-f",
        "--tiebreak=index",
        "--layout=reverse",
        "--no-info",
    ]

    input_data = "\n".join(items)
    p = subprocess.Popen(
        fzf_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None
    )
    stdout, _ = p.communicate(input_data.encode())

    if p.returncode == 130:
        return ("cancel", [])

    lines = stdout.decode().split("\n")
    if len(lines) < 2:
        return ("cancel", [])

    key = lines[0]
    selection = [l for l in lines[1:] if l]

    if key == "ctrl-f":
        idx = filter_order.index(filter_name) if filter_name in filter_order else 0
        next_filter = filter_order[(idx + 1) % len(filter_order)]
        return ("switch_filter", [next_filter])
    elif key == "tab":
        return ("insert", selection)
    elif key in ("ctrl-c", "esc"):
        return ("cancel", [])
    else:
        return ("copy", selection)


def main():
    if not TRIGGER_PANE:
        print("Error: EXTRAKTO_TRIGGER_PANE or HERDR_PANE_ID not set", file=sys.stderr)
        sys.exit(1)

    text = get_pane_content(TRIGGER_PANE)
    if not text:
        print("No pane content found", file=sys.stderr)
        sys.exit(1)

    current_filter = "all"

    while True:
        items = extract_all(text, current_filter)
        if not items:
            items = ["NO MATCH - try a different filter"]

        action, selection = run_fzf(items, current_filter)

        if action == "cancel":
            break
        elif action == "switch_filter":
            current_filter = selection[0]
            continue
        elif action == "copy":
            result = "\n".join(selection) if current_filter in ("all", "line") else " ".join(selection)
            copy_to_clipboard(result)
            break
        elif action == "insert":
            result = "\n".join(selection) if current_filter in ("all", "line") else " ".join(selection)
            insert_to_pane(result, TRIGGER_PANE)
            break


if __name__ == "__main__":
    main()
