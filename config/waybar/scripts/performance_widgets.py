#!/usr/bin/env python3

"""Reusable GTK widgets used by the native performance panel."""

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk


def add_class(widget, name):
    widget.get_style_context().add_class(name)
    return widget


def text_label(text="", css=None, xalign=0):
    widget = Gtk.Label(label=text, xalign=xalign)
    if css:
        add_class(widget, css)
    return widget


class HistoryGraph(Gtk.DrawingArea):
    def __init__(self, css_class, height=68):
        super().__init__()
        add_class(self, "performance-graph")
        add_class(self, css_class)
        self.values = []
        self.set_size_request(-1, height)
        self.set_hexpand(True)
        self.connect("draw", self.on_draw)

    def set_values(self, values):
        self.values = list(values)
        self.queue_draw()

    def on_draw(self, _widget, context):
        allocation = self.get_allocation()
        width = max(1.0, float(allocation.width))
        height = max(1.0, float(allocation.height))
        color = self.get_style_context().get_color(Gtk.StateFlags.NORMAL)

        if len(self.values) < 2:
            return False
        values = self.values
        step = width / max(1, len(values) - 1)
        points = [
            (index * step, height - 4.0 - (height - 8.0) * max(0.0, min(100.0, value)) / 100.0)
            for index, value in enumerate(values)
        ]

        context.set_antialias(cairo.ANTIALIAS_BEST)
        context.move_to(points[0][0], height)
        for x, y in points:
            context.line_to(x, y)
        context.line_to(points[-1][0], height)
        context.close_path()
        context.set_source_rgba(color.red, color.green, color.blue, 0.15)
        context.fill()

        context.move_to(*points[0])
        for point in points[1:]:
            context.line_to(*point)
        context.set_source_rgba(color.red, color.green, color.blue, 0.95)
        context.set_line_width(2.0)
        context.set_line_join(cairo.LINE_JOIN_ROUND)
        context.set_line_cap(cairo.LINE_CAP_ROUND)
        context.stroke()
        return False


class StatCard(Gtk.Box):
    def __init__(self, title, icon):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        add_class(self, "info-card")
        add_class(self, "performance-card")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.pack_start(text_label(icon, "row-icon"), False, False, 0)
        header.pack_start(text_label(title, "card-title"), True, True, 0)
        self.header_end = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.pack_end(self.header_end, False, False, 0)
        self.pack_start(header, False, False, 0)


class UsageBar(Gtk.ProgressBar):
    def __init__(self, css_class=""):
        super().__init__()
        add_class(self, "usage-bar")
        if css_class:
            add_class(self, css_class)
        self.set_show_text(False)

    def set_percent(self, value):
        self.set_fraction(max(0.0, min(1.0, float(value) / 100.0)))
