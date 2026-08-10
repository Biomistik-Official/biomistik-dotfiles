#!/usr/bin/env python3

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from gi.repository import GLib

from media_common import MediaService, perform_action


RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
STATE_FILE = RUNTIME_DIR / "waybar-media-source.json"
HIDDEN_PAYLOAD = {"text": "", "tooltip": "", "class": ["hidden"]}


def encode(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def print_state():
    try:
        payload = STATE_FILE.read_text(encoding="utf-8")
        json.loads(payload)
    except (OSError, json.JSONDecodeError):
        payload = encode(HIDDEN_PAYLOAD)
    print(payload, flush=True)


class SourceService:
    def __init__(self):
        self.loop = GLib.MainLoop()
        self.current = ""
        self.hide_timer = None
        self.steady_timer = None
        self.service = MediaService(self.update)
        self.update(initial=True)

    @staticmethod
    def signal_waybar():
        subprocess.run(
            ["pkill", "-RTMIN+9", "-x", "waybar"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def publish(self, text, classes, tooltip="Click to open the media menu"):
        payload = encode({"text": text, "tooltip": tooltip, "class": classes})
        temporary = STATE_FILE.with_suffix(".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(STATE_FILE)
        self.signal_waybar()

    def cancel_timer(self, name):
        source = getattr(self, name)
        if source is not None:
            GLib.source_remove(source)
            setattr(self, name, None)

    def show_steady(self, text, status):
        self.steady_timer = None
        self.publish(text, [status])
        return False

    def hide(self):
        self.hide_timer = None
        self.current = ""
        self.publish("", ["hidden"], "")
        return False

    def update(self, initial=False):
        _player, state = self.service.active()
        self.cancel_timer("hide_timer")
        self.cancel_timer("steady_timer")

        if state is None:
            if self.current and not initial:
                self.publish(self.current, ["disappearing"])
                self.hide_timer = GLib.timeout_add(180, self.hide)
            else:
                self.hide()
            return

        text = f'{state["icon"]}  {state["source"]}'
        if text != self.current:
            self.current = text
            self.publish(text, [state["status"], "appearing"])
            self.steady_timer = GLib.timeout_add(35, self.show_steady, text, state["status"])
        else:
            self.publish(text, [state["status"]])

    def run(self):
        signal.signal(signal.SIGTERM, lambda *_: self.loop.quit())
        signal.signal(signal.SIGINT, lambda *_: self.loop.quit())
        self.loop.run()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", action="store_true")
    parser.add_argument("--print", dest="print_once", action="store_true")
    parser.add_argument("--action", choices=("play-pause", "next", "previous"))
    args = parser.parse_args()
    if args.action:
        return perform_action(args.action)
    if args.service:
        SourceService().run()
        return 0
    print_state()
    return 0


if __name__ == "__main__":
    sys.exit(main())
