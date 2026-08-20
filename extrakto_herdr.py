#!/usr/bin/env python3
"""
extrakto-herdr — extract tokens from herdr pane content and fuzzy-pick them.

Inspired by extrakto for tmux (https://github.com/laktak/extrakto).

Flow:
  1. Read pane content via `herdr pane read`.
  2. Extract tokens (words, paths, URLs, lines, quotes).
  3. Pipe through fzf for fuzzy selection.
  4. Copy to clipboard or insert into the pane.
"""

import os
import re
import subprocess
import sys
from collections import OrderedDict
from configparser import ConfigParser

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PANE_ID = os.environ.get("HERDR_PANE_ID", "")
TRIGGER_PANE = os.environ.get("EXTRAKTO_TRIGGER_PANE", PANE_ID)

MIN_LENGTH_DEFAULT = 5

# --- Filter definitions (from extrakto.conf) ---

BUILTIN_FILTERS = {
    "word": {
        "regex": r"([^][(){}=$\u2500-\u27BF\uE000-\uF8FF\u22C5\u21B4\u2502 \t\n\r]+)",
        "lstrip": ",:;()[]{}<>'\"|",
        "rstrip": ",:;()[]{}<>'\"|.",
        "in_all": False,
        "min_length": 5,
    },
    "path": {
        "regex": r"(?:[ \t\n\"([<':]|^)(~|/)?([-~a-zA-Z0-9_+-,.]+/[^ \t\n\r|:\"'$%&)>\]]*)",
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


def load_filters():
    """Load builtin + user filters from ~/.config/extrakto/extrakto.conf."""
    filters = dict(BUILTIN_FILTERS)

    user_conf_path = os.path.expanduser("~/.config/extrakto/extrakto.conf")
    if os.path.exists(user_conf_path):
        conf = ConfigParser(interpolation=None)
        conf.read(user_conf_path, encoding="utf-8")
        for name in conf.sections():
            sect = conf[name]
            if name in filters:
                if sect.get("regex"):
                    filters[name]["regex"] = sect["regex"]
                if sect.get("exclude"):
                    filters[name]["exclude"] = sect["exclude"]
                if sect.get("lstrip"):
                    filters[name]["lstrip"] = sect["lstrip"]
                if sect.get("rstrip"):
                    filters[name]["rstrip"] = sect["rstrip"]
                if sect.get("min_length"):
                    filters[name]["min_length"] = int(sect["min_length"])
            else:
                filters[name] = {
                    "regex": sect.get("regex", ""),
                    "exclude": sect.get("exclude", ""),
                    "lstrip": sect.get("lstrip", ""),
                    "rstrip": sect.get("rstrip", ""),
                    "in_all": sect.getboolean("in_all", True),
                    "min_length": int(sect.get("min_length", MIN_LENGTH_DEFAULT)),
                }

    return filters


def extract_filter(text, filt):
    """Apply a single filter and return matches."""
    regex = filt.get("regex")
    if not regex:
        return []

    results = []
    exclude = filt.get("exclude", "")
    lstrip = filt.get("lstrip", "")
    rstrip = filt.get("rstrip", "")
    min_length = filt.get("min_length", MIN_LENGTH_DEFAULT)

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


def extract_lines(text, min_length=MIN_LENGTH_DEFAULT):
    """Extract full lines."""
    return [line.strip() for line in text.splitlines() if len(line.strip()) >= min_length]


def extract_all(text, filters, filter_name="all"):
    """Extract using specified filter or all filters."""
    results = []

    if filter_name == "all":
        for name, filt in filters.items():
            if filt.get("in_all", True):
                results.extend(extract_filter(text, filt))
        results.extend(extract_lines(text))
    elif filter_name == "line":
        results = extract_lines(text)
    elif filter_name == "word":
        results = extract_filter(text, filters.get("word", BUILTIN_FILTERS["word"]))
    elif filter_name in filters:
        results = extract_filter(text, filters[filter_name])

    # deduplicate preserving order, most recent first
    results.reverse()
    return list(OrderedDict.fromkeys(results))


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

    # Fallback: try recent (default)
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
    """Copy text to system clipboard."""
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
    """Send text as keys to the pane."""
    try:
        import json

        sock_path = os.environ.get("HERDR_SOCKET_PATH", "")
        if not sock_path:
            home = os.environ.get("HOME", "")
            sock_path = f"{home}/.config/herdr/herdr.sock"

        import socket

        addr = sock_path
        req = json.dumps(
            {
                "id": "extrakto-insert",
                "method": "pane.send_keys",
                "params": {"pane_id": pane_id, "keys": list(text)},
            }
        )
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(addr)
        s.sendall((req + "\n").encode())
        s.recv(256)
        s.close()
    except Exception:
        pass


def run_fzf(items, filter_name):
    """Run fzf and return (action, selection)."""
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

    filters = load_filters()
    current_filter = "all"

    while True:
        items = extract_all(text, filters, current_filter)
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
