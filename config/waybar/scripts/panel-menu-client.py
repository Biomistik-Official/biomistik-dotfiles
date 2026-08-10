#!/usr/bin/env python3

import os
from pathlib import Path
import socket
import subprocess
import sys
import time


SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "waybar-panel-menu.sock"


def send(message):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        client.sendto(message.encode("utf-8"), str(SOCKET_PATH))
        return True
    except OSError:
        return False
    finally:
        client.close()


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {"enter", "leave", "toggle"}:
        return 2
    message = f"{sys.argv[1]} {sys.argv[2]}"
    if sys.argv[1] == "enter":
        center_x = os.environ.get("WAYBAR_HOVER_CENTER_X", "")
        if center_x.isdigit():
            message += f" {center_x}"
    if send(message):
        return 0
    subprocess.run(
        ["systemctl", "--user", "start", "waybar-panel-menu.service"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=2,
        check=False,
    )
    for _attempt in range(8):
        time.sleep(0.025)
        if send(message):
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
