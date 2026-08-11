#!/usr/bin/env python3

"""Native layer-shell Performance / System Monitor panel."""

from collections import deque
import threading

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango

from performance_widgets import HistoryGraph, StatCard, UsageBar, add_class, text_label
from system_stats import SystemStats


POLL_INTERVAL_MS = 1000
HISTORY_LENGTH = 60
HOTSPOT_WIDTH = 6
HOTSPOT_HEIGHT = 220
HOTSPOT_DELAY_MS = 110


def format_bytes(value, precision=1):
    value = float(value or 0)
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if abs(value) < 1024.0 or unit == units[-1]:
            digits = 0 if unit in {"B", "KB"} else precision
            return f"{value:.{digits}f} {unit}"
        value /= 1024.0


def format_rate(value):
    return f"{format_bytes(value)}/s"


def temperature_text(value):
    return f"{value:.0f}°C" if value is not None else ""


class PerformancePage(Gtk.Box):
    def __init__(self, close_callback):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.active = False
        self.refreshing = False
        self.timer = None
        self.stats = SystemStats()
        self.histories = {
            "cpu": deque(maxlen=HISTORY_LENGTH),
            "gpu": deque(maxlen=HISTORY_LENGTH),
            "ram": deque(maxlen=HISTORY_LENGTH),
        }

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        header.pack_start(text_label("󰍛", "performance-title-icon"), False, False, 0)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_box.pack_start(text_label("System Performance", "page-title"), False, False, 0)
        title_box.pack_start(text_label("Realtime system monitor", "secondary"), False, False, 0)
        header.pack_start(title_box, True, True, 0)
        close_button = Gtk.Button(label="󰅖")
        add_class(close_button, "round-button")
        close_button.connect("clicked", lambda *_: close_callback())
        header.pack_end(close_button, False, False, 0)
        self.pack_start(header, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_overlay_scrolling(True)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.content.set_margin_end(4)
        scrolled.add(self.content)
        self.pack_start(scrolled, True, True, 0)

        self._build_overview()
        self._build_cpu()
        self._build_gpu()
        self._build_memory()
        self._build_temperatures()
        self._build_storage()
        self._build_network()

    def _build_overview(self):
        self.overview = add_class(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8), "overview-card")
        self.overview_values = {}
        self.overview_details = {}
        self.overview_cells = {}
        for key, title in (("cpu", "CPU"), ("gpu", "GPU"), ("ram", "RAM")):
            cell = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2), "overview-cell")
            cell.pack_start(text_label(title, "secondary", xalign=0.5), False, False, 0)
            value = text_label("—", "overview-value", xalign=0.5)
            detail = text_label("", "overview-detail", xalign=0.5)
            cell.pack_start(value, False, False, 0)
            cell.pack_start(detail, False, False, 0)
            self.overview.pack_start(cell, True, True, 0)
            self.overview_cells[key] = cell
            self.overview_values[key] = value
            self.overview_details[key] = detail
        self.overview_cells["gpu"].set_visible(self.stats.gpu is not None)
        self.content.pack_start(self.overview, False, False, 0)

    @staticmethod
    def _model_label():
        widget = text_label("", "secondary")
        widget.set_ellipsize(Pango.EllipsizeMode.END)
        widget.set_max_width_chars(46)
        return widget

    def _build_cpu(self):
        self.cpu_card = StatCard("CPU", "󰍛")
        self.cpu_model = self._model_label()
        self.cpu_card.pack_start(self.cpu_model, False, False, 0)
        metrics = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.cpu_usage = text_label("—", "metric-large")
        self.cpu_frequency = text_label("", "metric-secondary")
        self.cpu_temperature = text_label("", "metric-temperature", xalign=1)
        metrics.pack_start(self.cpu_usage, True, True, 0)
        metrics.pack_start(self.cpu_frequency, False, False, 0)
        metrics.pack_end(self.cpu_temperature, False, False, 0)
        self.cpu_card.pack_start(metrics, False, False, 0)
        self.cpu_details = text_label("", "secondary")
        self.cpu_card.pack_start(self.cpu_details, False, False, 0)
        self.cpu_graph = HistoryGraph("cpu-graph")
        self.cpu_card.pack_start(self.cpu_graph, False, False, 0)
        self.content.pack_start(self.cpu_card, False, False, 0)

    def _build_gpu(self):
        self.gpu_card = StatCard("GPU", "󰢮")
        self.gpu_model = self._model_label()
        self.gpu_card.pack_start(self.gpu_model, False, False, 0)
        metrics = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.gpu_usage = text_label("—", "metric-large")
        self.gpu_clock = text_label("", "metric-secondary")
        self.gpu_temperature = text_label("", "metric-temperature", xalign=1)
        metrics.pack_start(self.gpu_usage, True, True, 0)
        metrics.pack_start(self.gpu_clock, False, False, 0)
        metrics.pack_end(self.gpu_temperature, False, False, 0)
        self.gpu_card.pack_start(metrics, False, False, 0)
        self.gpu_vram = text_label("", "secondary")
        self.gpu_card.pack_start(self.gpu_vram, False, False, 0)
        self.gpu_graph = HistoryGraph("gpu-graph")
        self.gpu_card.pack_start(self.gpu_graph, False, False, 0)
        self.gpu_card.set_visible(self.stats.gpu is not None)
        self.content.pack_start(self.gpu_card, False, False, 0)

    def _build_memory(self):
        self.memory_card = StatCard("Memory", "󰘚")
        metrics = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.memory_usage = text_label("—", "metric-value")
        self.memory_percent = text_label("—", "metric-temperature", xalign=1)
        metrics.pack_start(self.memory_usage, True, True, 0)
        metrics.pack_end(self.memory_percent, False, False, 0)
        self.memory_card.pack_start(metrics, False, False, 0)
        self.memory_bar = UsageBar("ram-bar")
        self.memory_card.pack_start(self.memory_bar, False, False, 0)
        self.memory_details = text_label("", "secondary")
        self.memory_card.pack_start(self.memory_details, False, False, 0)
        self.memory_graph = HistoryGraph("ram-graph", height=54)
        self.memory_card.pack_start(self.memory_graph, False, False, 0)
        self.content.pack_start(self.memory_card, False, False, 0)

    def _build_temperatures(self):
        self.temperature_card = StatCard("Temperatures", "󰔏")
        self.temperature_rows = {}
        for key, title, icon in (("cpu", "CPU", "󰍛"), ("gpu", "GPU", "󰢮"), ("ssd", "SSD", "󰋊")):
            row = add_class(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8), "temperature-row")
            row.pack_start(text_label(icon, "row-icon"), False, False, 0)
            row.pack_start(text_label(title, "row-title"), True, True, 0)
            value = text_label("", "temperature-value", xalign=1)
            row.pack_end(value, False, False, 0)
            row.set_visible(False)
            self.temperature_card.pack_start(row, False, False, 0)
            self.temperature_rows[key] = (row, value)
        self.temperature_card.set_visible(False)
        self.content.pack_start(self.temperature_card, False, False, 0)

    def _build_storage(self):
        self.storage_card = StatCard("System Disk", "󰋊")
        metrics = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.storage_usage = text_label("—", "metric-value")
        self.storage_percent = text_label("—", "metric-temperature", xalign=1)
        metrics.pack_start(self.storage_usage, True, True, 0)
        metrics.pack_end(self.storage_percent, False, False, 0)
        self.storage_card.pack_start(metrics, False, False, 0)
        self.storage_bar = UsageBar("storage-bar")
        self.storage_card.pack_start(self.storage_bar, False, False, 0)
        self.storage_free = text_label("", "secondary")
        self.storage_card.pack_start(self.storage_free, False, False, 0)
        self.content.pack_start(self.storage_card, False, False, 0)

    def _build_network(self):
        self.network_card = StatCard("Network", "󰛳")
        speeds = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.network_down = text_label("󰇚  —", "network-down")
        self.network_up = text_label("󰕒  —", "network-up")
        speeds.pack_start(self.network_down, True, True, 0)
        speeds.pack_start(self.network_up, True, True, 0)
        self.network_card.pack_start(speeds, False, False, 0)
        self.network_interface = text_label("", "secondary")
        self.network_card.pack_start(self.network_interface, False, False, 0)
        self.content.pack_start(self.network_card, False, False, 0)

    def set_active(self, active):
        if self.active == active:
            return
        self.active = active
        if active:
            self.request_sample()
            if self.timer is None:
                self.timer = GLib.timeout_add(POLL_INTERVAL_MS, self.request_sample)
        elif self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None

    def request_sample(self):
        if not self.active:
            self.timer = None
            return False
        if not self.refreshing:
            self.refreshing = True
            threading.Thread(target=self._sample_worker, daemon=True).start()
        return True

    def _sample_worker(self):
        try:
            sample = self.stats.sample()
        except Exception as error:
            GLib.idle_add(self._sample_failed, str(error))
            return
        GLib.idle_add(self.apply_sample, sample)

    def _sample_failed(self, _message):
        self.refreshing = False
        return False

    def apply_sample(self, sample):
        self.refreshing = False
        if not self.active:
            return False
        cpu = sample["cpu"]
        self.histories["cpu"].append(cpu["percent"])
        self.cpu_graph.set_values(self.histories["cpu"])
        self.cpu_model.set_text(cpu["name"])
        self.cpu_usage.set_text(f"{cpu['percent']:.0f}%")
        self.cpu_frequency.set_text(f"{cpu['frequency_ghz']:.2f} GHz" if cpu["frequency_ghz"] is not None else "")
        self.cpu_temperature.set_text(temperature_text(cpu["temperature"]))
        load_text = " ".join(f"{value:.2f}" for value in cpu["load"])
        self.cpu_details.set_text(f"{cpu['cores']} cores · {cpu['threads']} threads   Load {load_text}")

        memory = sample["memory"]
        self.histories["ram"].append(memory["percent"])
        self.memory_graph.set_values(self.histories["ram"])
        self.memory_usage.set_text(f"{format_bytes(memory['used'])} / {format_bytes(memory['total'])}")
        self.memory_percent.set_text(f"{memory['percent']:.0f}%")
        self.memory_bar.set_percent(memory["percent"])
        self.memory_details.set_text(f"Available {format_bytes(memory['available'])} · Cached {format_bytes(memory['cached'])}")

        gpu = sample.get("gpu")
        self.gpu_card.set_visible(gpu is not None)
        self.overview_cells["gpu"].set_visible(gpu is not None)
        if gpu is not None:
            gpu_percent = gpu.get("percent")
            if gpu_percent is not None:
                self.histories["gpu"].append(gpu_percent)
                self.gpu_usage.set_text(f"{gpu_percent:.0f}%")
            else:
                self.gpu_usage.set_text("")
            self.gpu_graph.set_values(self.histories["gpu"])
            self.gpu_graph.set_visible(gpu_percent is not None)
            self.gpu_model.set_text(gpu["name"])
            self.gpu_clock.set_text(f"{gpu['clock_mhz']:.0f} MHz" if gpu.get("clock_mhz") is not None else "")
            self.gpu_temperature.set_text(temperature_text(gpu.get("temperature")))
            used, total = gpu.get("vram_used"), gpu.get("vram_total")
            self.gpu_vram.set_visible(used is not None and total is not None)
            if used is not None and total is not None:
                self.gpu_vram.set_text(f"VRAM {format_bytes(used)} / {format_bytes(total)}")

        temperatures = sample["temperatures"]
        useful_temperatures = False
        for key, (row, value_label) in self.temperature_rows.items():
            value = temperatures.get(key)
            row.set_visible(value is not None)
            if value is not None:
                useful_temperatures = True
                value_label.set_text(temperature_text(value))
        self.temperature_card.set_visible(useful_temperatures)

        storage = sample["storage"]
        self.storage_usage.set_text(f"{format_bytes(storage['used'])} / {format_bytes(storage['total'])}")
        self.storage_percent.set_text(f"{storage['percent']:.0f}%")
        self.storage_bar.set_percent(storage["percent"])
        self.storage_free.set_text(f"{format_bytes(storage['free'])} free on {storage['mount']}")

        network = sample["network"]
        self.network_down.set_text(f"󰇚  {format_rate(network['down'])}")
        self.network_up.set_text(f"󰕒  {format_rate(network['up'])}")
        self.network_interface.set_text(network["interface"])

        self.overview_values["cpu"].set_text(f"{cpu['percent']:.0f}%")
        self.overview_details["cpu"].set_text(temperature_text(cpu["temperature"]))
        self.overview_values["ram"].set_text(f"{memory['percent']:.0f}%")
        self.overview_details["ram"].set_text(format_bytes(memory["used"]))
        if gpu is not None:
            self.overview_values["gpu"].set_text(f"{gpu['percent']:.0f}%" if gpu.get("percent") is not None else "GPU")
            self.overview_details["gpu"].set_text(temperature_text(gpu.get("temperature")))
        return False

    def shutdown(self):
        self.set_active(False)


class PerformancePanelWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_name("performance-panel")
        self.set_title("System Performance")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_app_paintable(True)
        self.set_accept_focus(True)
        self.set_focus_on_map(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "waybar-panel-menu")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        overlay = Gtk.Overlay()
        backdrop = add_class(Gtk.EventBox(), "performance-backdrop")
        backdrop.set_visible_window(False)
        backdrop.set_hexpand(True)
        backdrop.set_vexpand(True)
        backdrop.connect("button-press-event", self.on_backdrop_click)
        overlay.add(backdrop)

        self.surface = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "panel-surface")
        add_class(self.surface, "performance-surface")
        self.surface.set_size_request(388, -1)
        self.page = PerformancePage(self.close_panel)
        self.surface.pack_start(self.page, True, True, 0)
        panel_events = Gtk.EventBox()
        panel_events.set_visible_window(False)
        panel_events.add(self.surface)
        panel_events.connect("button-press-event", lambda *_: False)

        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.revealer.set_transition_duration(210)
        self.revealer.set_halign(Gtk.Align.END)
        self.revealer.set_valign(Gtk.Align.FILL)
        self.revealer.set_margin_top(12)
        self.revealer.set_margin_bottom(12)
        self.revealer.set_margin_end(0)
        self.revealer.add(panel_events)
        overlay.add_overlay(self.revealer)
        self.add(overlay)

        self.hide_timer = None
        self.connect("key-press-event", self.on_key_press)
        self.connect("delete-event", lambda *_: self.close_panel())

    def is_open(self):
        return self.get_visible() and self.revealer.get_reveal_child()

    def show_panel(self):
        if self.hide_timer is not None:
            GLib.source_remove(self.hide_timer)
            self.hide_timer = None
        self.surface.get_style_context().remove_class("closing")
        if not self.get_visible():
            self.show_all()
        self.page.set_active(True)
        self.revealer.set_reveal_child(True)
        self.present()
        return False

    def close_panel(self):
        if not self.get_visible():
            return False
        self.page.set_active(False)
        self.surface.get_style_context().add_class("closing")
        self.revealer.set_reveal_child(False)
        if self.hide_timer is not None:
            GLib.source_remove(self.hide_timer)
        self.hide_timer = GLib.timeout_add(230, self.finish_hide)
        return True

    def toggle(self):
        self.close_panel() if self.is_open() else self.show_panel()

    def finish_hide(self):
        self.hide_timer = None
        self.hide()
        self.surface.get_style_context().remove_class("closing")
        return False

    def on_backdrop_click(self, *_args):
        self.close_panel()
        return True

    def on_key_press(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_panel()
            return True
        return False

    def shutdown(self):
        if self.hide_timer is not None:
            GLib.source_remove(self.hide_timer)
            self.hide_timer = None
        self.page.shutdown()


class PerformanceHotspotWindow(Gtk.Window):
    """Tiny invisible right-edge hover target; no polling while armed."""

    def __init__(self, open_callback):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.open_callback = open_callback
        self.hover_timer = None
        self.rearm_timer = None
        self.pointer_inside = False
        self.blocked = False
        self.set_name("performance-hotspot")
        self.set_title("Performance edge hotspot")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_default_size(HOTSPOT_WIDTH, HOTSPOT_HEIGHT)
        geometry = Gdk.Geometry()
        geometry.min_width = HOTSPOT_WIDTH
        geometry.max_width = HOTSPOT_WIDTH
        geometry.min_height = HOTSPOT_HEIGHT
        geometry.max_height = HOTSPOT_HEIGHT
        self.set_geometry_hints(
            None,
            geometry,
            Gdk.WindowHints.MIN_SIZE | Gdk.WindowHints.MAX_SIZE,
        )
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "waybar-performance-hotspot")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 0)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

        target = add_class(Gtk.EventBox(), "performance-hotspot")
        target.set_visible_window(True)
        target.set_size_request(HOTSPOT_WIDTH, HOTSPOT_HEIGHT)
        target.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        target.connect("enter-notify-event", self.on_enter)
        target.connect("leave-notify-event", self.on_leave)
        self.add(target)
        self.show_all()

    def cancel_hover_timer(self):
        if self.hover_timer is not None:
            GLib.source_remove(self.hover_timer)
            self.hover_timer = None

    def on_enter(self, *_args):
        self.pointer_inside = True
        if not self.blocked and self.hover_timer is None:
            self.hover_timer = GLib.timeout_add(HOTSPOT_DELAY_MS, self.activate)
        return False

    def on_leave(self, *_args):
        self.pointer_inside = False
        self.cancel_hover_timer()
        return False

    def activate(self):
        self.hover_timer = None
        if not self.pointer_inside or self.blocked:
            return False
        self.blocked = True
        self.open_callback()
        if self.rearm_timer is None:
            self.rearm_timer = GLib.timeout_add(160, self.watch_rearm)
        return False

    def pointer_still_on_hotspot(self):
        display = Gdk.Display.get_default()
        seat = display.get_default_seat() if display else None
        pointer = seat.get_pointer() if seat else None
        if pointer is None:
            return False
        position = pointer.get_position()
        x, y = position[-2], position[-1]
        monitor = display.get_monitor_at_point(x, y)
        if monitor is None:
            return False
        geometry = monitor.get_geometry()
        workarea = monitor.get_workarea()
        left = geometry.x + geometry.width - HOTSPOT_WIDTH
        top = workarea.y + (workarea.height - HOTSPOT_HEIGHT) // 2
        return (
            left <= x < left + HOTSPOT_WIDTH
            and top <= y < top + HOTSPOT_HEIGHT
        )

    def watch_rearm(self):
        if self.pointer_still_on_hotspot():
            return True
        self.blocked = False
        self.rearm_timer = None
        return False

    def shutdown(self):
        self.cancel_hover_timer()
        if self.rearm_timer is not None:
            GLib.source_remove(self.rearm_timer)
            self.rearm_timer = None
        self.hide()
