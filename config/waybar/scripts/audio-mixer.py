#!/usr/bin/env python3

import atexit
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")

from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango


SCRIPT_PATH = Path(__file__).resolve()
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
PID_FILE = RUNTIME_DIR / "waybar-audio-mixer.pid"
CSS_FILE = SCRIPT_PATH.with_name("audio-mixer.css")


def toggle_existing_instance():
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        if str(SCRIPT_PATH).encode() in cmdline:
            os.kill(pid, signal.SIGTERM)
            return True
    except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
        pass

    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return False


def cleanup_pid_file():
    try:
        if PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except (FileNotFoundError, PermissionError):
        pass


def run_pactl_json(*args):
    result = subprocess.run(
        ["pactl", "-f", "json", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=3,
    )
    return json.loads(result.stdout)


def average_volume(item):
    channels = item.get("volume", {}).values()
    values = [channel.get("value", 0) / 65536 for channel in channels]
    return sum(values) / len(values) if values else 0.0


def useful_text(value):
    value = str(value or "").strip()
    return "" if value in {"", "(null)", "null"} else value


def audio_state():
    default_sink = subprocess.run(
        ["pactl", "get-default-sink"],
        check=True,
        capture_output=True,
        text=True,
        timeout=3,
    ).stdout.strip()

    sinks = run_pactl_json("list", "sinks")
    sink = next((item for item in sinks if item.get("name") == default_sink), None)
    if sink is None and sinks:
        sink = sinks[0]

    output = None
    if sink is not None:
        properties = sink.get("properties", {})
        description = useful_text(sink.get("description"))
        if not description:
            description = useful_text(properties.get("device.description"))
        output = {
            "key": ("sink", int(sink["index"])),
            "index": int(sink["index"]),
            "title": "System Volume",
            "subtitle": description or "Main Output",
            "volume": average_volume(sink),
            "muted": bool(sink.get("mute", False)),
            "kind": "sink",
        }

    streams = []
    for item in run_pactl_json("list", "sink-inputs"):
        properties = item.get("properties", {})
        app_name = useful_text(properties.get("application.name"))
        media_name = useful_text(properties.get("media.name"))
        binary_name = useful_text(properties.get("application.process.binary"))
        title = app_name or binary_name or "Application"
        subtitle = media_name if media_name and media_name != title else ""
        if item.get("corked"):
            subtitle = f"{subtitle} · Paused" if subtitle else "Paused"

        streams.append({
            "key": ("input", int(item["index"])),
            "index": int(item["index"]),
            "title": title,
            "subtitle": subtitle,
            "volume": average_volume(item),
            "muted": bool(item.get("mute", False)),
            "kind": "input",
        })

    streams.sort(key=lambda item: (item["title"].casefold(), item["index"]))
    return output, streams


class AudioMixer(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_name("audio-mixer")
        self.set_title("Waybar Audio Mixer")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(430, -1)

        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "waybar-audio-mixer")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 8)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 10)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        self.controls = {}
        self.pending_volume = {}
        self.signature = None

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.get_style_context().add_class("audio-card")
        self.add(card)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Volume Mixer", xalign=0)
        title.get_style_context().add_class("mixer-title")
        title.set_hexpand(True)
        header.pack_start(title, True, True, 0)

        close_button = Gtk.Button(label="×")
        close_button.set_tooltip_text("Close")
        close_button.get_style_context().add_class("close-button")
        close_button.connect("clicked", lambda *_: self.close())
        header.pack_end(close_button, False, False, 0)
        card.pack_start(header, False, False, 0)

        self.master_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.pack_start(self.master_box, False, False, 0)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        card.pack_start(separator, False, False, 0)

        apps_title = Gtk.Label(label="Applications", xalign=0)
        apps_title.get_style_context().add_class("section-title")
        card.pack_start(apps_title, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_max_content_height(420)
        self.streams_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scrolled.add(self.streams_box)
        card.pack_start(scrolled, True, True, 0)

        hint = Gtk.Label(label="Left-click the icon to close · Right-click for pavucontrol", xalign=0)
        hint.get_style_context().add_class("hint")
        card.pack_start(hint, False, False, 0)

        self.connect("destroy", lambda *_: Gtk.main_quit())
        self.connect("key-press-event", self.on_key_press)
        GLib.timeout_add(1200, self.refresh)
        self.refresh(force=True)

    def on_key_press(self, _window, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    @staticmethod
    def clear_box(box):
        for child in box.get_children():
            child.destroy()

    def add_control(self, parent, state, master=False):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.get_style_context().add_class("volume-row")

        icon = Gtk.Label(label="󰕾" if master else "󰎆")
        icon.get_style_context().add_class("row-icon")
        row.pack_start(icon, False, False, 0)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        content.set_hexpand(True)

        title = Gtk.Label(label=state["title"], xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.get_style_context().add_class("row-title")
        content.pack_start(title, False, False, 0)

        if state["subtitle"]:
            subtitle = Gtk.Label(label=state["subtitle"], xalign=0)
            subtitle.set_ellipsize(Pango.EllipsizeMode.END)
            subtitle.get_style_context().add_class("row-subtitle")
            content.pack_start(subtitle, False, False, 0)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1.5, 0.01)
        scale.set_value(state["volume"])
        scale.set_hexpand(True)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.connect("format-value", lambda _scale, value: f"{round(value * 100)}%")
        content.pack_start(scale, False, False, 0)
        row.pack_start(content, True, True, 0)

        mute = Gtk.Button(label="󰝟" if state["muted"] else "󰕾")
        mute.set_tooltip_text("Unmute" if state["muted"] else "Mute")
        mute.get_style_context().add_class("mute-button")
        row.pack_end(mute, False, False, 0)

        control = {
            "state": state,
            "scale": scale,
            "mute": mute,
            "muted": state["muted"],
        }
        control["scale_handler"] = scale.connect(
            "value-changed", self.on_volume_changed, state["key"]
        )
        mute.connect("clicked", self.on_mute_clicked, state["key"])
        self.controls[state["key"]] = control
        parent.pack_start(row, False, False, 0)

    def rebuild(self, output, streams):
        self.clear_box(self.master_box)
        self.clear_box(self.streams_box)
        self.controls = {}

        if output is not None:
            self.add_control(self.master_box, output, master=True)

        if streams:
            for stream in streams:
                self.add_control(self.streams_box, stream)
        else:
            empty = Gtk.Label(
                label="No active audio streams",
                xalign=0,
            )
            empty.set_line_wrap(True)
            empty.get_style_context().add_class("empty-state")
            self.streams_box.pack_start(empty, False, False, 0)

        self.show_all()

    def update_control(self, state):
        control = self.controls.get(state["key"])
        if control is None:
            return

        scale = control["scale"]
        scale.handler_block(control["scale_handler"])
        scale.set_value(state["volume"])
        scale.handler_unblock(control["scale_handler"])

        control["muted"] = state["muted"]
        control["state"] = state
        control["mute"].set_label("󰝟" if state["muted"] else "󰕾")
        control["mute"].set_tooltip_text(
            "Unmute" if state["muted"] else "Mute"
        )

    def refresh(self, force=False):
        try:
            output, streams = audio_state()
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
            if force:
                self.clear_box(self.streams_box)
                error = Gtk.Label(label="Failed to get PipeWire state", xalign=0)
                error.get_style_context().add_class("empty-state")
                self.streams_box.pack_start(error, False, False, 0)
                self.show_all()
            return True

        signature = (
            output["key"] if output else None,
            tuple((item["key"], item["title"], item["subtitle"]) for item in streams),
        )
        if force or signature != self.signature:
            self.signature = signature
            self.rebuild(output, streams)
        else:
            if output:
                self.update_control(output)
            for stream in streams:
                self.update_control(stream)
        return True

    def on_volume_changed(self, scale, key):
        source_id = self.pending_volume.pop(key, None)
        if source_id is not None:
            GLib.source_remove(source_id)
        self.pending_volume[key] = GLib.timeout_add(
            90, self.apply_volume, key, scale.get_value()
        )

    def apply_volume(self, key, value):
        self.pending_volume.pop(key, None)
        control = self.controls.get(key)
        if control is None:
            return False
        state = control["state"]
        command = "set-sink-volume" if state["kind"] == "sink" else "set-sink-input-volume"
        subprocess.Popen(
            ["pactl", command, str(state["index"]), f"{round(value * 100)}%"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return False

    def on_mute_clicked(self, _button, key):
        control = self.controls.get(key)
        if control is None:
            return
        state = control["state"]
        command = "set-sink-mute" if state["kind"] == "sink" else "set-sink-input-mute"
        subprocess.Popen(
            ["pactl", command, str(state["index"]), "toggle"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        control["muted"] = not control["muted"]
        control["mute"].set_label("󰝟" if control["muted"] else "󰕾")
        GLib.timeout_add(180, self.refresh)


def main():
    if toggle_existing_instance():
        return 0

    atexit.register(cleanup_pid_file)
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    signal.signal(signal.SIGINT, lambda *_: Gtk.main_quit())

    css = Gtk.CssProvider()
    css.load_from_path(str(CSS_FILE))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        css,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )

    window = AudioMixer()
    window.show_all()
    Gtk.main()
    window.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
