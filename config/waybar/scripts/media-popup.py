#!/usr/bin/env python3

import atexit
import hashlib
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("Playerctl", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango, Playerctl

from media_common import MediaService, format_time, theme_color


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
CAVA_CONFIG = SCRIPT_DIR / "cava-media.conf"
CSS_FILE = SCRIPT_DIR / "media-popup.css"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "waybar-media"
PID_FILE = RUNTIME_DIR / "waybar-media-popup.pid"
BAR_COUNT = 48


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


def rgba(value, fallback):
    color = Gdk.RGBA()
    if not color.parse(value) and not color.parse(fallback):
        color.parse("white")
    return color


def rounded_rectangle(context, x, y, width, height, radius):
    radius = min(radius, width / 2, height / 2)
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    context.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    context.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    context.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    context.close_path()


class CavaEngine:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.levels_value = [0.0] * BAR_COUNT
        self.last_start = 0.0

    def running(self):
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def start(self):
        if self.running() or time.monotonic() - self.last_start < 2:
            return
        self.last_start = time.monotonic()
        try:
            process = subprocess.Popen(
                ["cava", "-p", str(CAVA_CONFIG)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return
        with self.lock:
            self.process = process
        threading.Thread(target=self.read_frames, args=(process,), daemon=True).start()

    def read_frames(self, process):
        while process.poll() is None and process.stdout is not None:
            frame = process.stdout.readline()
            if not frame:
                break
            try:
                values = [int(value) for value in frame.decode("ascii").split()]
            except (UnicodeDecodeError, ValueError):
                continue
            if len(values) != BAR_COUNT:
                continue
            with self.lock:
                if self.process is not process:
                    return
                self.levels_value = [min(8.0, float(value)) for value in values]

    def levels(self):
        with self.lock:
            return list(self.levels_value)

    def stop(self):
        with self.lock:
            process = self.process
            self.process = None
            self.levels_value = [0.0] * BAR_COUNT
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


class ArtworkLoader:
    def __init__(self, callback):
        self.callback = callback
        self.generation = 0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def load(self, url):
        self.generation += 1
        generation = self.generation
        if not url:
            self.callback(None, generation)
            return
        threading.Thread(target=self._worker, args=(url, generation), daemon=True).start()

    def _worker(self, url, generation):
        try:
            parsed = urlparse(url)
            if parsed.scheme == "file":
                path = Path(unquote(parsed.path))
            elif parsed.scheme in {"http", "https"}:
                digest = hashlib.sha256(url.encode()).hexdigest()
                path = CACHE_DIR / f"{digest}.art"
                if not path.exists():
                    request = Request(url, headers={"User-Agent": "Waybar Media Popup/1.0"})
                    with urlopen(request, timeout=8) as response:
                        data = response.read(12 * 1024 * 1024 + 1)
                    if len(data) > 12 * 1024 * 1024:
                        raise ValueError("Artwork is too large")
                    path.write_bytes(data)
            else:
                path = Path(url)
            if not path.is_file():
                raise FileNotFoundError(path)
            GLib.idle_add(self.callback, path, generation)
        except (OSError, ValueError):
            GLib.idle_add(self.callback, None, generation)


class ArtworkSpectrum(Gtk.DrawingArea):
    ART_SIZE = 154

    def __init__(self):
        super().__init__()
        self.set_size_request(430, 235)
        self.primary = rgba(theme_color("primary"), "#ffffff")
        self.surface_variant = rgba(theme_color("surface_variant"), "#333333")
        self.on_surface_variant = rgba(theme_color("on_surface_variant"), "#dddddd")
        self.cava = CavaEngine()
        self.playing = False
        self.current_levels = [0.0] * BAR_COUNT
        self.artwork = None
        self.previous_artwork = None
        self.art_transition = 1.0
        self.connect("draw", self.on_draw)
        self.tick_id = GLib.timeout_add(33, self.tick)

    def set_playing(self, playing):
        self.playing = playing
        if playing:
            self.cava.start()
        else:
            self.cava.stop()

    def set_artwork(self, pixbuf):
        self.previous_artwork = self.artwork
        self.artwork = pixbuf
        self.art_transition = 0.0
        self.queue_draw()

    def tick(self):
        target = self.cava.levels() if self.playing else [0.0] * BAR_COUNT
        moving = False
        for index, desired in enumerate(target):
            current = self.current_levels[index]
            factor = 0.62 if desired > current else 0.18
            updated = current + (desired - current) * factor
            if abs(updated) < 0.025:
                updated = 0.0
            moving = moving or abs(updated - current) > 0.01
            self.current_levels[index] = updated
        if self.art_transition < 1.0:
            self.art_transition = min(1.0, self.art_transition + 0.12)
            moving = True
            if self.art_transition >= 1.0:
                self.previous_artwork = None
        if moving or self.playing:
            self.queue_draw()
        return True

    def draw_art(self, context, pixbuf, alpha, x, y, size):
        if alpha <= 0:
            return
        context.save()
        rounded_rectangle(context, x, y, size, size, 28)
        context.clip()
        if pixbuf is None:
            context.set_source_rgba(
                self.surface_variant.red,
                self.surface_variant.green,
                self.surface_variant.blue,
                alpha,
            )
            context.rectangle(x, y, size, size)
            context.fill()
            context.set_source_rgba(
                self.on_surface_variant.red,
                self.on_surface_variant.green,
                self.on_surface_variant.blue,
                alpha,
            )
            triangle_size = 38
            center_x = x + size / 2 + 3
            center_y = y + size / 2
            context.move_to(center_x - triangle_size * 0.45, center_y - triangle_size * 0.62)
            context.line_to(center_x + triangle_size * 0.62, center_y)
            context.line_to(center_x - triangle_size * 0.45, center_y + triangle_size * 0.62)
            context.close_path()
            context.fill()
        else:
            Gdk.cairo_set_source_pixbuf(context, pixbuf, x, y)
            context.paint_with_alpha(alpha)
        context.restore()

    def on_draw(self, _widget, context):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        center_x = width / 2
        center_y = height / 2
        inner_radius = self.ART_SIZE / 2 + 18

        context.set_line_cap(cairo.LINE_CAP_ROUND)
        context.set_line_width(4)
        for index, level in enumerate(self.current_levels):
            angle = -math.pi / 2 + 2 * math.pi * index / BAR_COUNT
            length = 3 + level / 8 * 22
            start = inner_radius + 2
            end = start + length
            strength = 0.48 + level / 8 * 0.48
            context.set_source_rgba(
                self.primary.red,
                self.primary.green,
                self.primary.blue,
                strength,
            )
            context.move_to(center_x + math.cos(angle) * start, center_y + math.sin(angle) * start)
            context.line_to(center_x + math.cos(angle) * end, center_y + math.sin(angle) * end)
            context.stroke()

        x = center_x - self.ART_SIZE / 2
        y = center_y - self.ART_SIZE / 2
        if self.art_transition < 1.0:
            self.draw_art(context, self.previous_artwork, 1 - self.art_transition, x, y, self.ART_SIZE)
            self.draw_art(context, self.artwork, self.art_transition, x, y, self.ART_SIZE)
        else:
            self.draw_art(context, self.artwork, 1.0, x, y, self.ART_SIZE)
        return False

    def shutdown(self):
        if self.tick_id is not None:
            GLib.source_remove(self.tick_id)
            self.tick_id = None
        self.cava.stop()


class MediaPopup(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_name("media-popup")
        self.set_title("Waybar Media Popup")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(470, -1)
        self.closing = False
        self.dragging_progress = False
        self.track_key = None
        self.art_generation = 0
        self.metadata_page = None
        self.open_step = 0
        self.close_step = 0
        self.main_running = False

        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "waybar-media-popup")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 0)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, 10)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.card.get_style_context().add_class("media-card")
        self.card.get_style_context().add_class("opening")
        self.add(self.card)

        self.build_header()
        self.spectrum = ArtworkSpectrum()
        self.card.pack_start(self.spectrum, False, False, 0)
        self.build_metadata()
        self.build_progress()
        self.build_controls()

        self.art_loader = ArtworkLoader(self.on_artwork_path)
        self.service = MediaService(self.on_media_change)
        self.position_timer = GLib.timeout_add(500, self.update_position)

        self.connect("key-press-event", self.on_key_press)
        self.connect("destroy", self.on_destroy)
        self.on_media_change()
        GLib.timeout_add(25, self.animate_open)

    def build_header(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.source_icon = Gtk.Label(xalign=0)
        self.source_icon.get_style_context().add_class("source-icon")
        header.pack_start(self.source_icon, False, False, 0)
        self.source_label = Gtk.Label(xalign=0)
        self.source_label.set_hexpand(True)
        self.source_label.get_style_context().add_class("source-label")
        header.pack_start(self.source_label, True, True, 0)
        close = Gtk.Button(label="×")
        close.set_tooltip_text("Close")
        close.get_style_context().add_class("close-button")
        close.connect("clicked", lambda *_: self.begin_close())
        header.pack_end(close, False, False, 0)
        self.card.pack_start(header, False, False, 0)

    def build_metadata(self):
        self.metadata_stack = Gtk.Stack()
        self.metadata_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.metadata_stack.set_transition_duration(220)
        self.card.pack_start(self.metadata_stack, False, False, 0)

    def metadata_box(self, state):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label(label=state["title"], xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(42)
        title.get_style_context().add_class("track-title")
        box.pack_start(title, False, False, 0)
        artist_text = state["artist"] or state["album"] or state["source"]
        artist = Gtk.Label(label=artist_text, xalign=0)
        artist.set_ellipsize(Pango.EllipsizeMode.END)
        artist.set_max_width_chars(48)
        artist.get_style_context().add_class("track-artist")
        box.pack_start(artist, False, False, 0)
        return box

    def build_progress(self):
        self.progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.progress = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.1)
        self.progress.set_draw_value(False)
        self.progress.set_hexpand(True)
        self.progress.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.progress.connect("button-press-event", self.on_progress_press)
        self.progress.connect("button-release-event", self.on_progress_release)
        self.progress_box.pack_start(self.progress, False, False, 0)
        times = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.position_label = Gtk.Label(label="0:00", xalign=0)
        self.duration_label = Gtk.Label(label="0:00", xalign=1)
        self.position_label.get_style_context().add_class("time-label")
        self.duration_label.get_style_context().add_class("time-label")
        times.pack_start(self.position_label, True, True, 0)
        times.pack_end(self.duration_label, True, True, 0)
        self.progress_box.pack_start(times, False, False, 0)
        self.card.pack_start(self.progress_box, False, False, 0)

    @staticmethod
    def control_button(icon, css_class="control-button"):
        button = Gtk.Button(label=icon)
        button.get_style_context().add_class(css_class)
        return button

    def build_controls(self):
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.set_halign(Gtk.Align.CENTER)
        self.shuffle_button = self.control_button(chr(0xF049D))
        self.previous_button = self.control_button(chr(0xF04AE))
        self.play_button = self.control_button(chr(0xF040A), "play-button")
        self.next_button = self.control_button(chr(0xF04AD))
        self.repeat_button = self.control_button(chr(0xF0456))
        self.shuffle_button.set_tooltip_text("Shuffle")
        self.previous_button.set_tooltip_text("Previous")
        self.play_button.set_tooltip_text("Play/Pause")
        self.next_button.set_tooltip_text("Next")
        self.repeat_button.set_tooltip_text("Repeat")
        self.shuffle_button.connect("clicked", self.toggle_shuffle)
        self.previous_button.connect("clicked", lambda *_: self.player_action("previous"))
        self.play_button.connect("clicked", lambda *_: self.player_action("play-pause"))
        self.next_button.connect("clicked", lambda *_: self.player_action("next"))
        self.repeat_button.connect("clicked", self.cycle_repeat)
        for button in (
            self.shuffle_button,
            self.previous_button,
            self.play_button,
            self.next_button,
            self.repeat_button,
        ):
            controls.pack_start(button, False, False, 0)
        self.card.pack_start(controls, False, False, 0)

    def animate_open(self):
        if self.closing:
            return False
        self.open_step += 1
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, min(8, self.open_step * 2))
        if self.open_step == 2:
            self.card.get_style_context().remove_class("opening")
        return self.open_step < 4

    def begin_close(self):
        if self.closing:
            return False
        self.closing = True
        self.close_step = 5
        self.card.get_style_context().add_class("closing")
        GLib.timeout_add(35, self.animate_close)
        return False

    def animate_close(self):
        self.close_step -= 1
        GtkLayerShell.set_margin(
            self,
            GtkLayerShell.Edge.TOP,
            max(0, round(8 * self.close_step / 5)),
        )
        if self.close_step <= 0:
            self.destroy()
            return False
        return True

    def on_key_press(self, _window, event):
        if event.keyval == Gdk.KEY_Escape:
            self.begin_close()
            return True
        return False

    @staticmethod
    def set_active(widget, active):
        context = widget.get_style_context()
        if active:
            context.add_class("active")
        else:
            context.remove_class("active")

    def on_media_change(self):
        player, state = self.service.active()
        if state is None:
            self.spectrum.set_playing(False)
            GLib.timeout_add(120, self.begin_close)
            return

        self.source_icon.set_text(state["icon"])
        self.source_label.set_text(state["source"])
        self.spectrum.set_playing(state["status"] == "playing")
        self.play_button.set_label(chr(0xF03E4) if state["status"] == "playing" else chr(0xF040A))
        self.previous_button.set_sensitive(state["can_previous"])
        self.next_button.set_sensitive(state["can_next"])
        self.play_button.set_sensitive(state["can_play"] or state["can_pause"])
        browser_player = state["player_name"].lower() in {
            "firefox",
            "chromium",
            "chrome",
            "brave",
            "zen",
        }
        self.shuffle_button.set_sensitive(not browser_player)
        self.repeat_button.set_sensitive(not browser_player)
        self.progress.set_sensitive(state["can_seek"] and state["length_us"] > 0)
        self.set_active(self.shuffle_button, state["shuffle"])
        self.set_active(self.repeat_button, state["loop"] != "none")
        self.repeat_button.set_label(chr(0xF0457) if state["loop"] == "track" else chr(0xF0456))

        duration_seconds = state["length_us"] / 1_000_000
        self.progress_box.set_visible(duration_seconds > 0)
        self.progress.set_range(0, max(1, duration_seconds))
        self.duration_label.set_text(format_time(state["length_us"]))

        track_key = (state["instance"], state["title"], state["artist"], state["album"], state["art_url"])
        if track_key != self.track_key:
            self.track_key = track_key
            page = self.metadata_box(state)
            page_name = f"track-{time.monotonic_ns()}"
            old_page = self.metadata_page
            self.metadata_stack.add_named(page, page_name)
            page.show_all()
            self.metadata_stack.set_visible_child(page)
            self.metadata_page = page
            if old_page is not None:
                GLib.timeout_add(280, self.remove_metadata_page, old_page)
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
                    ArtworkSpectrum.ART_SIZE,
                    ArtworkSpectrum.ART_SIZE,
                    GdkPixbuf.InterpType.BILINEAR,
                )
            except GLib.Error:
                pixbuf = None
        self.spectrum.set_artwork(pixbuf)
        return False

    def update_position(self):
        if self.closing:
            return False
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
            if action == "play-pause":
                player.play_pause()
            elif action == "next":
                player.next()
            elif action == "previous":
                player.previous()
        except GLib.Error:
            pass

    def toggle_shuffle(self, *_args):
        player, state = self.service.active()
        if player is None or state is None:
            return
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

    def on_destroy(self, *_args):
        if self.position_timer is not None:
            GLib.source_remove(self.position_timer)
            self.position_timer = None
        self.spectrum.shutdown()
        if self.main_running:
            Gtk.main_quit()


def main():
    if toggle_existing_instance():
        return 0
    atexit.register(cleanup_pid_file)

    css = Gtk.CssProvider()
    css.load_from_path(str(CSS_FILE))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        css,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )

    window = MediaPopup()
    if window.service.active()[1] is None:
        window.destroy()
        return 0
    signal.signal(signal.SIGTERM, lambda *_: GLib.idle_add(window.begin_close))
    signal.signal(signal.SIGINT, lambda *_: GLib.idle_add(window.begin_close))
    window.show_all()
    window.main_running = True
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
