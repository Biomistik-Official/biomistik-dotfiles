#!/usr/bin/env python3

import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import weakref

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("Playerctl", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango, Playerctl

from media_common import MediaService, format_time


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
CSS_FILE = SCRIPT_DIR / "panel-menu.css"
PALETTE_FILE = SCRIPT_DIR.parent / "colors.css"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
SOCKET_PATH = RUNTIME_DIR / "waybar-panel-menu.sock"
HYPR_SIGNATURE = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
HYPR_SOCKET = RUNTIME_DIR / "hypr" / HYPR_SIGNATURE / ".socket.sock"
OPEN_DELAY_MS = 110
CLOSE_DELAY_MS = 220


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MEDIA = load_script("waybar_media_popup", "media-popup.py")
AUDIO = load_script("waybar_audio_mixer", "audio-mixer.py")


def add_class(widget, name):
    widget.get_style_context().add_class(name)
    return widget


def label(text="", css=None, xalign=0):
    widget = Gtk.Label(label=text, xalign=xalign)
    if css:
        add_class(widget, css)
    return widget


def button(text, callback=None, css=None):
    widget = Gtk.Button(label=text)
    if css:
        add_class(widget, css)
    if callback:
        widget.connect("clicked", callback)
    return widget


def run_quiet(command):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def launch_quiet(command):
    """Launch a GUI/action process and always reap it when it exits."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    threading.Thread(target=process.wait, daemon=True).start()
    return process


class Page(Gtk.Box):
    def __init__(self, spacing=12):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        self.active = False

    def set_active(self, active):
        self.active = active

    def shutdown(self):
        pass


class MediaPage(Page):
    def __init__(self):
        super().__init__()
        self.track_key = None
        self.dragging_progress = False
        self.current_state = None
        self.art_generation = 0

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.source_icon = label(css="source-icon")
        self.source_label = label(css="page-title")
        header.pack_start(self.source_icon, False, False, 0)
        header.pack_start(self.source_label, True, True, 0)
        self.pack_start(header, False, False, 0)

        self.spectrum = MEDIA.ArtworkSpectrum()
        # Keep the reusable media page warm without a 30 FPS idle timer.
        if self.spectrum.tick_id is not None:
            GLib.source_remove(self.spectrum.tick_id)
            self.spectrum.tick_id = None
        self.pack_start(self.spectrum, False, False, 0)

        self.metadata_stack = Gtk.Stack()
        self.metadata_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.metadata_stack.set_transition_duration(180)
        self.metadata_page = None
        self.pack_start(self.metadata_stack, False, False, 0)

        self.progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.progress = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.1)
        self.progress.set_draw_value(False)
        self.progress.set_hexpand(True)
        self.progress.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.progress.connect("button-press-event", self.on_progress_press)
        self.progress.connect("button-release-event", self.on_progress_release)
        self.progress_box.pack_start(self.progress, False, False, 0)
        times = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.position_label = label("0:00", "time-label")
        self.duration_label = label("0:00", "time-label", xalign=1)
        times.pack_start(self.position_label, True, True, 0)
        times.pack_end(self.duration_label, True, True, 0)
        self.progress_box.pack_start(times, False, False, 0)
        self.pack_start(self.progress_box, False, False, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.set_halign(Gtk.Align.CENTER)
        self.shuffle_button = button(chr(0xF049D), self.toggle_shuffle, "round-button")
        self.previous_button = button(chr(0xF04AE), lambda *_: self.player_action("previous"), "round-button")
        self.play_button = button(chr(0xF040A), lambda *_: self.player_action("play-pause"), "play-button")
        self.next_button = button(chr(0xF04AD), lambda *_: self.player_action("next"), "round-button")
        self.repeat_button = button(chr(0xF0456), self.cycle_repeat, "round-button")
        for control in (
            self.shuffle_button,
            self.previous_button,
            self.play_button,
            self.next_button,
            self.repeat_button,
        ):
            controls.pack_start(control, False, False, 0)
        self.pack_start(controls, False, False, 0)

        self.art_loader = MEDIA.ArtworkLoader(self.on_artwork_path)
        self.service = MediaService(self.on_media_change)
        self.position_timer = GLib.timeout_add(500, self.update_position)
        self.on_media_change()

    def set_active(self, active):
        super().set_active(active)
        if active and self.spectrum.tick_id is None:
            self.spectrum.tick_id = GLib.timeout_add(33, self.spectrum.tick)
        elif not active and self.spectrum.tick_id is not None:
            GLib.source_remove(self.spectrum.tick_id)
            self.spectrum.tick_id = None
        playing = bool(self.current_state and self.current_state["status"] == "playing")
        self.spectrum.set_playing(active and playing)
        if active:
            self.on_media_change()
            self.update_position()

    def metadata_box(self, state):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_widget = label(state["title"], "track-title")
        title_widget.set_ellipsize(Pango.EllipsizeMode.END)
        title_widget.set_max_width_chars(42)
        box.pack_start(title_widget, False, False, 0)
        artist_text = state["artist"] or state["album"] or state["source"]
        artist_widget = label(artist_text, "track-artist")
        artist_widget.set_ellipsize(Pango.EllipsizeMode.END)
        artist_widget.set_max_width_chars(48)
        box.pack_start(artist_widget, False, False, 0)
        return box

    @staticmethod
    def set_button_active(widget, active):
        context = widget.get_style_context()
        context.add_class("active") if active else context.remove_class("active")

    def on_media_change(self):
        _player, state = self.service.active()
        self.current_state = state
        if state is None:
            self.spectrum.set_playing(False)
            return
        self.source_icon.set_text(state["icon"])
        self.source_label.set_text(state["source"])
        self.spectrum.set_playing(self.active and state["status"] == "playing")
        self.play_button.set_label(chr(0xF03E4) if state["status"] == "playing" else chr(0xF040A))
        self.previous_button.set_sensitive(state["can_previous"])
        self.next_button.set_sensitive(state["can_next"])
        self.play_button.set_sensitive(state["can_play"] or state["can_pause"])
        browser = state["player_name"].lower() in {"firefox", "chromium", "chrome", "brave", "zen"}
        self.shuffle_button.set_sensitive(not browser)
        self.repeat_button.set_sensitive(not browser)
        self.progress.set_sensitive(state["can_seek"] and state["length_us"] > 0)
        self.set_button_active(self.shuffle_button, state["shuffle"])
        self.set_button_active(self.repeat_button, state["loop"] != "none")
        self.repeat_button.set_label(chr(0xF0457) if state["loop"] == "track" else chr(0xF0456))
        duration = state["length_us"] / 1_000_000
        self.progress_box.set_visible(duration > 0)
        self.progress.set_range(0, max(1, duration))
        self.duration_label.set_text(format_time(state["length_us"]))

        track_key = (state["instance"], state["title"], state["artist"], state["album"], state["art_url"])
        if track_key != self.track_key:
            self.track_key = track_key
            new_page = self.metadata_box(state)
            old_page = self.metadata_page
            self.metadata_stack.add(new_page)
            new_page.show_all()
            self.metadata_stack.set_visible_child(new_page)
            self.metadata_page = new_page
            if old_page is not None:
                GLib.timeout_add(230, self.remove_metadata_page, old_page)
            self.art_loader.load(state["art_url"])

    def remove_metadata_page(self, page):
        if page is not self.metadata_page and page.get_parent() is self.metadata_stack:
            self.metadata_stack.remove(page)
        return False

    def on_artwork_path(self, path, generation):
        if generation < self.art_generation:
            return False
        self.art_generation = generation
        pixbuf = None
        if path is not None:
            try:
                original = GdkPixbuf.Pixbuf.new_from_file(str(path))
                side = min(original.get_width(), original.get_height())
                cropped = original.new_subpixbuf(
                    (original.get_width() - side) // 2,
                    (original.get_height() - side) // 2,
                    side,
                    side,
                )
                pixbuf = cropped.scale_simple(
                    MEDIA.ArtworkSpectrum.ART_SIZE,
                    MEDIA.ArtworkSpectrum.ART_SIZE,
                    GdkPixbuf.InterpType.BILINEAR,
                )
            except GLib.Error:
                pixbuf = None
        self.spectrum.set_artwork(pixbuf)
        return False

    def update_position(self):
        if not self.active:
            return True
        player, state = self.service.active()
        if player is None or state is None:
            return True
        try:
            position = max(0, int(player.get_position()))
        except GLib.Error:
            position = 0
        if not self.dragging_progress:
            self.progress.set_value(position / 1_000_000)
            self.position_label.set_text(format_time(position))
        return True

    def on_progress_press(self, *_args):
        self.dragging_progress = True
        return False

    def on_progress_release(self, *_args):
        self.dragging_progress = False
        player, state = self.service.active()
        if player is not None and state and state["can_seek"]:
            try:
                player.set_position(int(self.progress.get_value() * 1_000_000))
            except GLib.Error:
                pass
        return False

    def player_action(self, action):
        player, _state = self.service.active()
        if player is None:
            return
        try:
            {"play-pause": player.play_pause, "next": player.next, "previous": player.previous}[action]()
        except GLib.Error:
            pass

    def toggle_shuffle(self, *_args):
        player, state = self.service.active()
        if player is not None and state:
            try:
                player.set_shuffle(not state["shuffle"])
            except GLib.Error:
                pass

    def cycle_repeat(self, *_args):
        player, state = self.service.active()
        if player is None or state is None:
            return
        next_status = {
            "none": Playerctl.LoopStatus.PLAYLIST,
            "playlist": Playerctl.LoopStatus.TRACK,
            "track": Playerctl.LoopStatus.NONE,
        }[state["loop"]]
        try:
            player.set_loop_status(next_status)
        except GLib.Error:
            pass

    def shutdown(self):
        if self.position_timer is not None:
            GLib.source_remove(self.position_timer)
            self.position_timer = None
        self.spectrum.shutdown()


class AudioPage(Page):
    def __init__(self):
        super().__init__()
        self.signature = None
        self.controls = {}
        self.pending = {}
        self.refreshing = False
        self.pack_start(label("Volume Mixer", "page-title"), False, False, 0)
        self.master_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.pack_start(self.master_box, False, False, 0)
        self.pack_start(Gtk.Separator(), False, False, 0)
        self.pack_start(label("Applications", "section-title"), False, False, 0)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_max_content_height(390)
        self.streams_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scrolled.add(self.streams_box)
        self.pack_start(scrolled, True, True, 0)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.pack_end(button("Open pavucontrol", self.open_pavucontrol), False, False, 0)
        self.pack_start(footer, False, False, 0)
        self.timer = GLib.timeout_add(1200, self.request_refresh)
        self.request_refresh(force=True)

    def set_active(self, active):
        super().set_active(active)
        if active:
            self.request_refresh(force=True)

    @staticmethod
    def clear_box(box):
        for child in box.get_children():
            child.destroy()

    def add_control(self, parent, state, master=False):
        row = add_class(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10), "menu-row")
        row.pack_start(label("󰕾" if master else "󰎆", "row-icon"), False, False, 0)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        content.set_hexpand(True)
        title_widget = label(state["title"], "row-title")
        title_widget.set_ellipsize(Pango.EllipsizeMode.END)
        content.pack_start(title_widget, False, False, 0)
        if state["subtitle"]:
            subtitle = label(state["subtitle"], "secondary")
            subtitle.set_ellipsize(Pango.EllipsizeMode.END)
            content.pack_start(subtitle, False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1.5, 0.01)
        scale.set_value(state["volume"])
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.connect("format-value", lambda _scale, value: f"{round(value * 100)}%")
        content.pack_start(scale, False, False, 0)
        row.pack_start(content, True, True, 0)
        mute = button("󰝟" if state["muted"] else "󰕾", css="round-button")
        row.pack_end(mute, False, False, 0)
        control = {"state": state, "scale": scale, "mute": mute, "muted": state["muted"]}
        control["handler"] = scale.connect("value-changed", self.on_volume_changed, state["key"])
        mute.connect("clicked", self.on_mute_clicked, state["key"])
        self.controls[state["key"]] = control
        parent.pack_start(row, False, False, 0)

    def rebuild(self, output, streams):
        self.clear_box(self.master_box)
        self.clear_box(self.streams_box)
        self.controls = {}
        if output:
            self.add_control(self.master_box, output, master=True)
        if streams:
            for stream in streams:
                self.add_control(self.streams_box, stream)
        else:
            self.streams_box.pack_start(add_class(label("No active audio streams"), "info-card"), False, False, 0)
        self.show_all()

    def update_control(self, state):
        control = self.controls.get(state["key"])
        if control is None:
            return
        scale = control["scale"]
        scale.handler_block(control["handler"])
        scale.set_value(state["volume"])
        scale.handler_unblock(control["handler"])
        control["state"] = state
        control["muted"] = state["muted"]
        control["mute"].set_label("󰝟" if state["muted"] else "󰕾")

    def request_refresh(self, force=False):
        if not self.active and not force:
            return True
        if self.refreshing:
            return True
        self.refreshing = True
        threading.Thread(target=self.refresh_worker, args=(force,), daemon=True).start()
        return True

    def refresh_worker(self, force):
        try:
            output, streams = AUDIO.audio_state()
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
            GLib.idle_add(self.finish_refresh_error)
            return
        GLib.idle_add(self.apply_refresh, output, streams, force)

    def finish_refresh_error(self):
        self.refreshing = False
        return False

    def apply_refresh(self, output, streams, force=False):
        self.refreshing = False
        signature = (output["key"] if output else None, tuple((x["key"], x["title"], x["subtitle"]) for x in streams))
        if force or signature != self.signature:
            self.signature = signature
            self.rebuild(output, streams)
        else:
            if output:
                self.update_control(output)
            for stream in streams:
                self.update_control(stream)
        return False

    def on_volume_changed(self, scale, key):
        old = self.pending.pop(key, None)
        if old:
            GLib.source_remove(old)
        self.pending[key] = GLib.timeout_add(90, self.apply_volume, key, scale.get_value())

    def apply_volume(self, key, value):
        self.pending.pop(key, None)
        control = self.controls.get(key)
        if not control:
            return False
        state = control["state"]
        command = "set-sink-volume" if state["kind"] == "sink" else "set-sink-input-volume"
        launch_quiet(["pactl", command, str(state["index"]), f"{round(value * 100)}%"])
        return False

    def on_mute_clicked(self, _button, key):
        control = self.controls.get(key)
        if not control:
            return
        state = control["state"]
        command = "set-sink-mute" if state["kind"] == "sink" else "set-sink-input-mute"
        launch_quiet(["pactl", command, str(state["index"]), "toggle"])
        GLib.timeout_add(180, self.refresh_once)

    def refresh_once(self):
        self.request_refresh()
        return False

    def open_pavucontrol(self, *_args):
        launch_quiet(["pavucontrol"])


class ClockPage(Page):
    def __init__(self):
        super().__init__()
        self.heading = label(css="page-title")
        self.subheading = label(css="secondary")
        self.pack_start(self.heading, False, False, 0)
        self.pack_start(self.subheading, False, False, 0)
        self.calendar = Gtk.Calendar()
        self.calendar.set_property("show-week-numbers", True)
        self.pack_start(self.calendar, False, False, 0)
        self.timer = GLib.timeout_add(1000, self.update_time)
        self.update_time()

    def set_active(self, active):
        super().set_active(active)
        if active:
            self.update_time()

    def update_time(self):
        now = time.localtime()
        self.heading.set_text(time.strftime("%H:%M:%S", now))
        self.subheading.set_text(time.strftime("%A, %d %B %Y", now))
        return True


class NetworkPage(Page):
    def __init__(self):
        super().__init__()
        self.refreshing = False
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.pack_start(label("Wi-Fi Networks", "page-title"), True, True, 0)
        header.pack_end(button("󰑐", self.rescan, "round-button"), False, False, 0)
        self.pack_start(header, False, False, 0)
        self.status = label("Loading…", "status-label")
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_max_width_chars(48)
        self.pack_start(self.status, False, False, 0)
        self.networks = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.pack_start(self.networks, False, False, 0)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.pack_end(button("Full Network Menu", self.open_full_menu), False, False, 0)
        self.pack_start(footer, False, False, 0)
        self.timer = GLib.timeout_add_seconds(5, self.request_refresh)
        self.request_refresh(force=True)

    def set_active(self, active):
        super().set_active(active)
        if active:
            self.request_refresh(force=True)

    def request_refresh(self, force=False):
        if not self.active and not force:
            return True
        if self.refreshing:
            return True
        self.refreshing = True
        threading.Thread(target=self.refresh_worker, daemon=True).start()
        return True

    def refresh_worker(self):
        result = run_quiet(["nmcli", "-t", "-e", "yes", "-f", "IN-USE,SSID,SIGNAL,SECURITY,DEVICE", "device", "wifi", "list", "--rescan", "no"])
        GLib.idle_add(self.apply_refresh, result)

    @staticmethod
    def split_nmcli_line(raw):
        fields = []
        current = []
        escaped = False
        for character in raw:
            if escaped:
                current.append(character)
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == ":" and len(fields) < 4:
                fields.append("".join(current))
                current = []
            else:
                current.append(character)
        current.append("\\" if escaped else "")
        fields.append("".join(current))
        return fields

    def apply_refresh(self, result):
        self.refreshing = False
        if result.returncode != 0:
            self.status.set_text("Failed to get network list")
            return False
        unique = {}
        active_name = ""
        for raw in result.stdout.splitlines():
            fields = self.split_nmcli_line(raw)
            if len(fields) != 5 or not fields[1]:
                continue
            active, ssid, strength, security, device = fields
            try:
                signal_value = int(strength)
            except ValueError:
                signal_value = 0
            item = {"active": active == "*" or active == "yes", "ssid": ssid, "signal": signal_value, "security": security, "device": device}
            if item["active"]:
                active_name = ssid
            if ssid not in unique or signal_value > unique[ssid]["signal"]:
                unique[ssid] = item
        for child in self.networks.get_children():
            child.destroy()
        ordered = sorted(unique.values(), key=lambda item: (not item["active"], -item["signal"], item["ssid"].casefold()))[:8]
        self.status.set_text(f"Connected: {active_name}" if active_name else "No active Wi-Fi connection")
        for item in ordered:
            icon = "󰤨" if item["signal"] >= 65 else "󰤥" if item["signal"] >= 35 else "󰤟"
            lock = " 󰌾" if item["security"] else ""
            row = button(f"{icon}  {item['ssid']}    {item['signal']}%{lock}", lambda _button, data=item: self.activate_network(data))
            row.set_halign(Gtk.Align.FILL)
            row_label = row.get_child()
            if isinstance(row_label, Gtk.Label):
                row_label.set_ellipsize(Pango.EllipsizeMode.END)
                row_label.set_max_width_chars(44)
            if item["active"]:
                add_class(row, "active")
            self.networks.pack_start(row, False, False, 0)
        self.show_all()
        return False

    def activate_network(self, item):
        self.status.set_text(f"Connecting to {item['ssid']}…")
        command = ["nmcli", "device", "disconnect", item["device"]] if item["active"] else ["nmcli", "device", "wifi", "connect", item["ssid"]]
        threading.Thread(target=self.network_worker, args=(command,), daemon=True).start()

    def network_worker(self, command):
        result = run_quiet(command)
        message = result.stdout.strip() or result.stderr.strip()
        GLib.idle_add(self.network_done, result.returncode, message)

    def network_done(self, returncode, message):
        self.status.set_text(message if message else ("Ready" if returncode == 0 else "Connection failed"))
        GLib.timeout_add(700, self.refresh_once)
        return False

    def rescan(self, *_args):
        threading.Thread(target=self.rescan_worker, daemon=True).start()

    def rescan_worker(self):
        run_quiet(["nmcli", "device", "wifi", "rescan"])
        GLib.idle_add(self.refresh_once)

    def refresh_once(self):
        self.request_refresh(force=True)
        return False

    def open_full_menu(self, *_args):
        PanelMenu.instance.close_menu()
        launch_quiet(["networkmanager_dmenu"])


class BatteryPage(Page):
    def __init__(self):
        super().__init__()
        self.refreshing = False
        self.pack_start(label("Power & Battery", "page-title"), False, False, 0)
        self.info = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5), "info-card")
        self.charge = label(css="row-title")
        self.health = label(css="secondary")
        self.state = label(css="secondary")
        self.info.pack_start(self.charge, False, False, 0)
        self.info.pack_start(self.health, False, False, 0)
        self.info.pack_start(self.state, False, False, 0)
        self.pack_start(self.info, False, False, 0)
        self.pack_start(label("Power Mode", "section-title"), False, False, 0)
        self.profile_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pack_start(self.profile_box, False, False, 0)
        self.timer = GLib.timeout_add_seconds(10, self.request_refresh)
        self.request_refresh(force=True)

    def set_active(self, active):
        super().set_active(active)
        if active:
            self.request_refresh(force=True)

    @staticmethod
    def parse_upower(text):
        values = {}
        for line in text.splitlines():
            if ":" in line:
                key, value = line.strip().split(":", 1)
                values[key.strip()] = value.strip()
        return values

    def request_refresh(self, force=False):
        if not self.active and not force:
            return True
        if self.refreshing:
            return True
        self.refreshing = True
        threading.Thread(target=self.refresh_worker, daemon=True).start()
        return True

    def refresh_worker(self):
        devices = run_quiet(["upower", "-e"]).stdout.splitlines()
        battery = next((item for item in devices if "battery_" in item), None)
        values = self.parse_upower(run_quiet(["upower", "-i", battery]).stdout) if battery else {}
        profiles = run_quiet(["powerprofilesctl", "list"]).stdout
        current = run_quiet(["powerprofilesctl", "get"]).stdout.strip()
        GLib.idle_add(self.apply_refresh, values, profiles, current)

    def apply_refresh(self, values, profiles, current):
        self.refreshing = False
        percentage = values.get("percentage", "—")
        capacity = values.get("capacity", "—")
        state_key = values.get("state", "unknown")
        state = {
            "fully-charged": "Fully charged",
            "discharging": "Discharging",
            "charging": "Charging",
            "pending-charge": "Pending charge",
            "pending-discharge": "Pending discharge",
            "empty": "Empty",
            "unknown": "Unknown",
        }.get(state_key, state_key.replace("-", " ").capitalize())
        cycles = values.get("charge-cycles", "—")
        self.charge.set_text(f"󰁹  Charge: {percentage}")
        self.health.set_text(f"Health: {capacity} · cycles: {cycles}")
        self.state.set_text(f"State: {state}")
        for child in self.profile_box.get_children():
            child.destroy()
        choices = [("power-saver", "󰌪 Power Saver"), ("balanced", "󰾅 Balanced"), ("performance", "󰓅 Performance")]
        for profile, title in choices:
            control = button(title, lambda _button, value=profile: self.set_profile(value))
            control.set_sensitive(f"{profile}:" in profiles)
            if profile == current:
                add_class(control, "active")
            self.profile_box.pack_start(control, True, True, 0)
        self.show_all()
        return False

    def set_profile(self, profile):
        threading.Thread(target=self.set_profile_worker, args=(profile,), daemon=True).start()

    def set_profile_worker(self, profile):
        run_quiet(["powerprofilesctl", "set", profile])
        GLib.idle_add(self.refresh_once)

    def refresh_once(self):
        self.request_refresh(force=True)
        return False


class NotificationsPage(Page):
    def __init__(self):
        super().__init__()
        self.updating = False
        self.refreshing = False
        self.pack_start(label("Notifications", "page-title"), False, False, 0)
        row = add_class(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10), "menu-row")
        self.count = label(css="row-title")
        self.count.set_hexpand(True)
        row.pack_start(self.count, True, True, 0)
        row.pack_end(button("Clear", self.clear_all), False, False, 0)
        self.pack_start(row, False, False, 0)
        dnd_row = add_class(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10), "menu-row")
        dnd_row.pack_start(label("Do Not Disturb", "row-title"), True, True, 0)
        self.dnd = Gtk.Switch()
        self.dnd.connect("notify::active", self.toggle_dnd)
        dnd_row.pack_end(self.dnd, False, False, 0)
        self.pack_start(dnd_row, False, False, 0)
        self.request_refresh(force=True)

    def set_active(self, active):
        super().set_active(active)
        if active:
            self.request_refresh(force=True)

    def request_refresh(self, force=False):
        if not self.active and not force:
            return True
        if self.refreshing:
            return True
        self.refreshing = True
        threading.Thread(target=self.refresh_worker, daemon=True).start()
        return True

    def refresh_worker(self):
        count = run_quiet(["swaync-client", "-c"]).stdout.strip() or "0"
        dnd = run_quiet(["swaync-client", "-D"]).stdout.strip().lower()
        GLib.idle_add(self.apply_refresh, count, dnd)

    def apply_refresh(self, count, dnd):
        self.refreshing = False
        self.updating = True
        self.count.set_text(f"Unread: {count}")
        self.dnd.set_active(dnd in {"true", "1", "yes"})
        self.updating = False
        return False

    def toggle_dnd(self, *_args):
        if not self.updating:
            threading.Thread(target=run_quiet, args=(["swaync-client", "-d"],), daemon=True).start()

    def clear_all(self, *_args):
        threading.Thread(target=self.clear_worker, daemon=True).start()

    def clear_worker(self):
        run_quiet(["swaync-client", "-C"])
        GLib.idle_add(self.refresh_once)

    def refresh_once(self):
        self.request_refresh(force=True)
        return False

class PowerPage(Page):
    ACTIONS = [
        ("  Lock", ["hyprlock"], False),
        ("⏾  Sleep", ["systemctl", "suspend"], False),
        ("󰍃  Log Out", ["hyprctl", "dispatch", "hl.dsp.exit()"], True),
        ("⟳  Restart", ["systemctl", "reboot"], True),
        ("⏻  Shut Down", ["systemctl", "poweroff"], True),
    ]

    def __init__(self):
        super().__init__()
        self.pending_action = None
        self.pending_timer = None
        self.pack_start(label("System Menu", "page-title"), False, False, 0)
        self.actions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.pack_start(self.actions_box, False, False, 0)
        self.hint = label("Destructive actions require a second click", "status-label")
        self.pack_start(self.hint, False, False, 0)
        self.build_actions()

    def build_actions(self):
        for child in self.actions_box.get_children():
            child.destroy()
        for title, command, dangerous in self.ACTIONS:
            control = button(title, lambda _button, name=title, cmd=command, risk=dangerous: self.activate(name, cmd, risk))
            if dangerous:
                add_class(control, "destructive-action")
            self.actions_box.pack_start(control, False, False, 0)
        self.show_all()

    def activate(self, title, command, dangerous):
        if not dangerous:
            PanelMenu.instance.close_menu()
            launch_quiet(command)
            return
        key = tuple(command)
        if self.pending_action == key:
            PanelMenu.instance.close_menu()
            launch_quiet(command)
            return
        self.pending_action = key
        self.hint.set_text(f"Click again: {title.strip()}")
        if self.pending_timer:
            GLib.source_remove(self.pending_timer)
        self.pending_timer = GLib.timeout_add_seconds(4, self.clear_confirmation)

    def clear_confirmation(self):
        self.pending_action = None
        self.pending_timer = None
        self.hint.set_text("Destructive actions require a second click")
        return False


class PanelMenu(Gtk.Window):
    instance = None
    PAGE_FACTORIES = {
        "media": MediaPage,
        "audio": AudioPage,
        "clock": ClockPage,
        "network": NetworkPage,
        "battery": BatteryPage,
        "notifications": NotificationsPage,
        "power": PowerPage,
    }
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        PanelMenu.instance = self
        self.set_name("panel-menu")
        self.set_title("Waybar Panel Menu")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(470, -1)
        geometry = Gdk.Geometry()
        geometry.min_width = 470
        geometry.max_width = 470
        self.set_geometry_hints(
            None,
            geometry,
            Gdk.WindowHints.MIN_SIZE | Gdk.WindowHints.MAX_SIZE,
        )
        self.set_focus_on_map(False)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "waybar-panel-menu")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        # Waybar's exclusive zone already starts this overlay below the 38 px bar.
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 0)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        self.surface = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "panel-surface")
        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.revealer.set_transition_duration(180)
        self.stack = Gtk.Stack()
        self.stack.set_hhomogeneous(True)
        self.stack.set_vhomogeneous(False)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(160)
        self.surface.pack_start(self.stack, True, True, 0)
        self.revealer.add(self.surface)
        self.add(self.revealer)

        self.pages = {}
        self.current_name = None
        self.trigger_hovered = set()
        self.trigger_centers = {}
        self.menu_hovered = False
        self.open_timer = None
        self.close_timer = None
        self.hide_timer = None
        self.pointer_watch = None
        self.external_notifications_open = False
        self.hover_widgets = weakref.WeakSet()
        self.menu_origin = (0, 38)
        self.monitor_geometry = (0, 0, 1920, 1080)

        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("enter-notify-event", self.on_menu_enter)
        self.connect("leave-notify-event", self.on_menu_leave)
        self.connect("key-press-event", self.on_key_press)
        self.connect("destroy", lambda *_: Gtk.main_quit())
        self.install_hover_events(self.surface)

        # Prebuild pages so the first hover never waits for widget construction.
        # MediaPage explicitly suspends its 30 FPS timer while hidden.
        for name in self.PAGE_FACTORIES:
            self.get_page(name)

    def get_page(self, name):
        page = self.pages.get(name)
        if page is None:
            page = self.PAGE_FACTORIES[name]()
            self.pages[name] = page
            self.stack.add_named(page, name)
            page.show_all()
            self.install_hover_events(page)
        return page

    def install_hover_events(self, widget):
        if widget in self.hover_widgets:
            return
        self.hover_widgets.add(widget)
        widget.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        widget.connect("enter-notify-event", self.on_child_enter)
        widget.connect("leave-notify-event", self.on_child_leave)
        if isinstance(widget, Gtk.Container):
            widget.connect("add", self.on_child_added)
            for child in widget.get_children():
                self.install_hover_events(child)

    def on_child_added(self, _container, child):
        self.install_hover_events(child)

    def on_child_enter(self, *_args):
        self.menu_hovered = True
        self.cancel_timer("close_timer")
        return False

    def on_child_leave(self, *_args):
        self.menu_hovered = False
        self.schedule_close()
        return False

    def position_for(self, name):
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geometry = monitor.get_geometry()
        self.monitor_geometry = (geometry.x, geometry.y, geometry.width, geometry.height)
        width = 470
        trigger_center = self.trigger_centers.get(name)
        if trigger_center is None:
            position = self.cursor_position()
            trigger_center = position[0] if position is not None else geometry.x + geometry.width // 2
        local_center = trigger_center - geometry.x
        left_margin = max(0, min(geometry.width - width, local_center - width // 2))
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, left_margin)
        self.menu_origin = (geometry.x + left_margin, geometry.y + 38)

    def cancel_timer(self, attribute):
        source = getattr(self, attribute)
        if source is not None:
            GLib.source_remove(source)
            setattr(self, attribute, None)

    def command(self, action, name, trigger_center=None):
        if name not in self.PAGE_FACTORIES:
            return
        if action == "enter":
            if trigger_center is not None:
                self.trigger_centers[name] = trigger_center
            self.trigger_hovered = {name}
            self.cancel_timer("close_timer")
            if self.current_name == name and self.menu_is_open():
                self.position_for(name)
            if self.current_name and self.current_name != name and self.menu_is_open():
                self.show_page(name)
            elif not self.menu_is_open():
                self.cancel_timer("open_timer")
                self.open_timer = GLib.timeout_add(OPEN_DELAY_MS, self.delayed_open, name)
        elif action == "leave":
            position = self.cursor_position()
            if position is not None and position[1] < self.menu_origin[1]:
                return
            self.trigger_hovered.discard(name)
            if name == self.current_name:
                self.schedule_close()
            elif self.open_timer is not None:
                self.cancel_timer("open_timer")
        elif action == "toggle":
            if self.current_name == name and self.menu_is_open():
                self.close_menu()
            else:
                self.cancel_timer("open_timer")
                self.show_page(name)

    def menu_is_open(self):
        if self.current_name == "notifications":
            return self.external_notifications_open
        return self.get_visible() and self.revealer.get_reveal_child()

    def delayed_open(self, name):
        self.open_timer = None
        position = self.cursor_position()
        if name in self.trigger_hovered and position is not None and position[1] < self.menu_origin[1]:
            self.show_page(name)
        elif position is not None and position[1] >= self.menu_origin[1]:
            self.trigger_hovered.discard(name)
        return False

    def show_page(self, name):
        if name == "notifications":
            self.show_notifications()
            return
        if self.external_notifications_open:
            self.close_notifications(reset_name=False)
        self.cancel_timer("close_timer")
        self.cancel_timer("hide_timer")
        self.cancel_timer("pointer_watch")
        self.menu_hovered = False
        previous = self.pages.get(self.current_name)
        if previous and self.current_name != name:
            previous.set_active(False)
        self.position_for(name)
        page = self.get_page(name)
        self.current_name = name
        self.stack.set_visible_child_name(name)
        page.set_active(True)
        self.surface.get_style_context().remove_class("closing")
        if not self.get_visible():
            self.show_all()
        self.revealer.set_reveal_child(True)
        if self.pointer_watch is None:
            self.pointer_watch = GLib.timeout_add(80, self.watch_menu_pointer)

    def show_notifications(self):
        self.cancel_timer("close_timer")
        self.cancel_timer("hide_timer")
        self.cancel_timer("pointer_watch")
        previous = self.pages.get(self.current_name)
        if previous:
            previous.set_active(False)
        if self.get_visible():
            self.revealer.set_reveal_child(False)
            self.hide()
        self.position_for("notifications")
        self.current_name = "notifications"
        self.external_notifications_open = True
        launch_quiet(["swaync-client", "-op", "-sw"])
        self.pointer_watch = GLib.timeout_add(80, self.watch_menu_pointer)

    def close_notifications(self, reset_name=True):
        if self.external_notifications_open:
            launch_quiet(["swaync-client", "-cp", "-sw"])
        self.external_notifications_open = False
        if reset_name:
            self.current_name = None

    def schedule_close(self):
        if self.menu_hovered or self.trigger_hovered:
            return
        self.cancel_timer("close_timer")
        self.close_timer = GLib.timeout_add(CLOSE_DELAY_MS, self.close_after_hover)

    def cursor_position(self):
        response = self.hypr_request("cursorpos", 128)
        if response is None:
            return None
        try:
            x_text, y_text = response.split(",", 1)
            return int(x_text.strip()), int(y_text.strip())
        except ValueError:
            return None

    def hypr_request(self, request, response_size=65536):
        path = HYPR_SOCKET
        if not path.exists():
            candidates = sorted((RUNTIME_DIR / "hypr").glob("*/.socket.sock"))
            if not candidates:
                return None
            path = candidates[-1]
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.05)
        try:
            client.connect(str(path))
            client.sendall(request.encode("ascii"))
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = client.recv(response_size)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(map(len, chunks)) >= response_size:
                    break
            return b"".join(chunks).decode("utf-8", errors="replace").strip()
        except OSError:
            return None
        finally:
            client.close()

    def notification_bounds(self):
        response = self.hypr_request("j/layers")
        if not response:
            return None
        try:
            monitors = json.loads(response)
            for monitor in monitors.values():
                for layers in monitor.get("levels", {}).values():
                    for layer in layers:
                        if layer.get("namespace") == "swaync-control-center":
                            left, top, width, height = (
                                layer["x"], layer["y"], layer["w"], layer["h"]
                            )
                            # SwayNC may keep a transparent monitor-sized layer
                            # until its next full restart. Only the centered card
                            # is part of the hover bridge, never that invisible area.
                            monitor_x, _monitor_y, monitor_width, _monitor_height = self.monitor_geometry
                            if width > 700:
                                width = 510
                                left = monitor_x + (monitor_width - width) // 2
                            return left, top, width, height
        except (json.JSONDecodeError, KeyError, TypeError):
            return None
        return None

    def pointer_inside(self, position=None):
        position = position or self.cursor_position()
        if position is None:
            return False
        x, y = position
        if self.current_name == "notifications" and self.external_notifications_open:
            bounds = self.notification_bounds()
            if bounds is not None:
                left, top, width, height = bounds
                return left <= x < left + width and top <= y < top + height
        left, top = self.menu_origin
        return (
            left <= x < left + self.get_allocated_width()
            and top <= y < top + self.get_allocated_height()
        )

    def page_at_bar_position(self, x, y):
        monitor_x, monitor_y, width, _height = self.monitor_geometry
        if not monitor_y <= y < monitor_y + 38:
            return None
        local_x = x - monitor_x
        center = width / 2
        right = width
        ranges = (
            (240, 460, "media"),
            (center - 170, center + 170, "clock"),
            (right - 510, right - 420, "audio"),
            (right - 420, right - 250, "network"),
            (right - 250, right - 165, "battery"),
            (right - 105, right - 55, "notifications"),
            (right - 55, right, "power"),
        )
        return next((name for start, end, name in ranges if start <= local_x < end), None)

    def close_after_hover(self):
        self.close_timer = None
        if self.pointer_inside():
            self.menu_hovered = True
            if self.pointer_watch is None:
                self.pointer_watch = GLib.timeout_add(80, self.watch_menu_pointer)
            return False
        return self.close_menu()

    def watch_menu_pointer(self):
        position = self.cursor_position()
        if position is not None:
            target = self.page_at_bar_position(*position)
            if target is not None:
                self.trigger_hovered = {target}
                self.menu_hovered = False
                self.cancel_timer("close_timer")
                if target != self.current_name:
                    self.pointer_watch = None
                    GLib.idle_add(self.show_page, target)
                    return False
                return True
        inside = self.pointer_inside(position)
        if inside:
            self.menu_hovered = True
            self.cancel_timer("close_timer")
            return True
        if self.menu_hovered:
            self.menu_hovered = False
        if position is not None and position[1] >= self.menu_origin[1]:
            self.trigger_hovered.clear()
        if not self.trigger_hovered and self.close_timer is None:
            self.close_timer = GLib.timeout_add(CLOSE_DELAY_MS, self.close_after_hover)
        return True

    def close_menu(self):
        self.cancel_timer("open_timer")
        self.cancel_timer("close_timer")
        self.cancel_timer("pointer_watch")
        if self.external_notifications_open:
            self.close_notifications()
            return False
        page = self.pages.get(self.current_name)
        if page:
            page.set_active(False)
        self.surface.get_style_context().add_class("closing")
        self.revealer.set_reveal_child(False)
        self.cancel_timer("hide_timer")
        self.hide_timer = GLib.timeout_add(190, self.finish_hide)
        return False

    def finish_hide(self):
        self.hide_timer = None
        self.hide()
        self.current_name = None
        self.surface.get_style_context().remove_class("closing")
        return False

    def on_menu_enter(self, _widget, event):
        self.menu_hovered = True
        self.cancel_timer("close_timer")
        return False

    def on_menu_leave(self, _widget, event):
        if event.detail != Gdk.NotifyType.INFERIOR:
            self.menu_hovered = False
            self.schedule_close()
        return False

    def on_key_press(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_menu()
            return True
        return False

    def shutdown(self):
        self.close_notifications()
        for page in self.pages.values():
            page.shutdown()


class CommandSocket:
    def __init__(self, menu):
        self.menu = menu
        try:
            SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.socket.bind(str(SOCKET_PATH))
        os.chmod(SOCKET_PATH, 0o600)
        self.channel = GLib.IOChannel.unix_new(self.socket.fileno())
        self.channel.set_close_on_unref(False)
        self.watch = GLib.io_add_watch(self.channel, GLib.IO_IN, self.on_message)

    def on_message(self, _channel, _condition):
        while True:
            try:
                message = self.socket.recv(256).decode("utf-8", errors="replace").strip()
            except BlockingIOError:
                break
            parts = message.split()
            if len(parts) >= 2:
                try:
                    trigger_center = int(parts[2]) if len(parts) >= 3 else None
                    self.menu.command(parts[0], parts[1], trigger_center)
                except Exception:
                    traceback.print_exc()
        return True

    def close(self):
        if self.watch:
            source = GLib.MainContext.default().find_source_by_id(self.watch)
            if source is not None:
                source.destroy()
            self.watch = None
        self.socket.close()
        try:
            SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass


class PaletteWatcher:
    def __init__(self, provider):
        self.provider = provider
        self.reload_timer = None
        directory = Gio.File.new_for_path(str(PALETTE_FILE.parent))
        self.monitor = directory.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self.on_changed)

    def on_changed(self, _monitor, file, other_file, _event):
        names = {
            candidate.get_basename()
            for candidate in (file, other_file)
            if candidate is not None
        }
        if PALETTE_FILE.name not in names:
            return
        if self.reload_timer is not None:
            GLib.source_remove(self.reload_timer)
        # Matugen can replace the palette atomically; wait until the write settles.
        self.reload_timer = GLib.timeout_add(160, self.reload)

    def reload(self):
        self.reload_timer = None
        try:
            self.provider.load_from_path(str(CSS_FILE))
        except GLib.Error:
            traceback.print_exc()
            return False
        launch_quiet(["swaync-client", "-rs"])
        launch_quiet(["pkill", "-USR2", "-x", "waybar"])
        return False

    def close(self):
        if self.reload_timer is not None:
            GLib.source_remove(self.reload_timer)
            self.reload_timer = None
        self.monitor.cancel()


def main():
    css = Gtk.CssProvider()
    css.load_from_path(str(CSS_FILE))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    palette_watcher = PaletteWatcher(css)
    menu = PanelMenu()
    command_socket = CommandSocket(menu)

    def quit_main(*_args):
        GLib.idle_add(Gtk.main_quit)

    signal.signal(signal.SIGTERM, quit_main)
    signal.signal(signal.SIGINT, quit_main)
    Gtk.main()
    menu.shutdown()
    command_socket.close()
    palette_watcher.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
