#!/usr/bin/env python3

from functools import lru_cache
from pathlib import Path
import re

import gi

gi.require_version("Playerctl", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, Playerctl


SCRIPT_DIR = Path(__file__).resolve().parent
COLORS_FILE = SCRIPT_DIR.parent / "colors.css"


def clean_text(value):
    return " ".join(str(value or "").replace("\n", " ").split())


def unpack(value):
    if hasattr(value, "unpack"):
        value = value.unpack()
    if isinstance(value, (list, tuple)):
        return [unpack(item) for item in value]
    return value


def metadata_value(metadata, key, default=""):
    try:
        metadata = unpack(metadata)
        return unpack(metadata.get(key, default))
    except (AttributeError, TypeError):
        return default


def theme_color(name, default=""):
    try:
        css = COLORS_FILE.read_text(encoding="utf-8")
    except OSError:
        return default
    match = re.search(rf"@define-color\s+{re.escape(name)}\s+([^;]+);", css)
    return match.group(1).strip() if match else default


@lru_cache(maxsize=32)
def mpris_process_identity(player_instance):
    """Resolve an MPRIS owner once per session without polling."""
    if not player_instance:
        return ""
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = connection.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "GetConnectionUnixProcessID",
            GLib.Variant("(s)", (f"org.mpris.MediaPlayer2.{player_instance}",)),
            GLib.VariantType.new("(u)"),
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        )
        pid = reply.unpack()[0]
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        return cmdline.replace(b"\0", b" ").decode(errors="replace").lower()
    except (GLib.Error, OSError, TypeError, ValueError):
        return ""


def source_identity(player_name, player_instance, metadata, process_identity=""):
    player_id = f"{player_name} {player_instance}".lower()
    process_identity = clean_text(process_identity).lower()
    url = clean_text(metadata_value(metadata, "xesam:url")).lower()
    title = clean_text(metadata_value(metadata, "xesam:title")).lower()
    album = clean_text(metadata_value(metadata, "xesam:album")).lower()
    identity = " ".join((player_id, url, title, album))

    if "pear-desktop/app.asar" in process_identity or "/pear-desktop/" in process_identity:
        return "\U000f05c3", "YouTube Music"
    if "music.youtube.com" in identity or "youtube music" in identity:
        return "\U000f05c3", "YouTube Music"
    if "youtube.com" in identity or "youtu.be" in identity:
        return "\U000f05c3", "YouTube"
    if "spotify" in identity:
        return "", "Spotify"
    if "firefox" in player_id or "zen" in player_id:
        return "", "Firefox" if "firefox" in player_id else "Zen Browser"
    if any(name in player_id for name in ("chromium", "chrome", "brave")):
        if "brave" in player_id:
            return "", "Brave"
        return "", "Chromium"
    if "vlc" in player_id:
        return chr(0xF057C), "VLC"
    if "mpv" in player_id:
        return chr(0xF0381), "mpv"

    technical = clean_text(player_name or player_instance)
    technical = technical.split(".instance", 1)[0]
    technical = technical.removeprefix("org.mpris.MediaPlayer2.")
    words = technical.replace("-", " ").replace("_", " ").split()
    display = " ".join(word.upper() if word.lower() in {"vlc", "mpv"} else word.title() for word in words)
    return chr(0xF075A), display or "Media"


def loop_name(value):
    if value == Playerctl.LoopStatus.TRACK:
        return "track"
    if value == Playerctl.LoopStatus.PLAYLIST:
        return "playlist"
    return "none"


def read_player(player):
    metadata = player.props.metadata or {}
    try:
        title = clean_text(player.get_title())
    except GLib.Error:
        title = clean_text(metadata_value(metadata, "xesam:title"))
    try:
        artist = clean_text(player.get_artist())
    except GLib.Error:
        artists = metadata_value(metadata, "xesam:artist", [])
        artist = clean_text(", ".join(artists) if isinstance(artists, list) else artists)

    player_instance = clean_text(player.props.player_instance)
    icon, source = source_identity(
        clean_text(player.props.player_name),
        player_instance,
        metadata,
        mpris_process_identity(player_instance),
    )
    length = metadata_value(metadata, "mpris:length", 0)
    try:
        length = int(length)
    except (TypeError, ValueError):
        length = 0

    return {
        "instance": player_instance,
        "player_name": clean_text(player.props.player_name),
        "status": clean_text(player.props.status).lower() or "stopped",
        "source": source,
        "icon": icon,
        "title": title or "Unknown track",
        "artist": artist,
        "album": clean_text(metadata_value(metadata, "xesam:album")),
        "url": clean_text(metadata_value(metadata, "xesam:url")),
        "art_url": clean_text(metadata_value(metadata, "mpris:artUrl")),
        "length_us": max(0, length),
        "can_play": bool(player.props.can_play),
        "can_pause": bool(player.props.can_pause),
        "can_next": bool(player.props.can_go_next),
        "can_previous": bool(player.props.can_go_previous),
        "can_seek": bool(player.props.can_seek),
        "shuffle": bool(player.props.shuffle),
        "loop": loop_name(player.props.loop_status),
    }


def priority(state):
    return {"playing": 3, "paused": 2, "stopped": 1}.get(state["status"], 0)


class MediaService:
    def __init__(self, on_change=None):
        self.manager = Playerctl.PlayerManager()
        self.on_change = on_change or (lambda: None)
        self.players = {}
        self.serial = 0

        self.manager.connect("name-appeared", self._on_name_appeared)
        self.manager.connect("player-vanished", self._on_player_vanished)
        for name in self.manager.props.player_names:
            self.add_player(name, notify=False)

    def add_player(self, name, notify=True):
        try:
            player = Playerctl.Player.new_from_name(name)
        except GLib.Error:
            return
        if clean_text(player.props.player_name).lower() == "playerctld":
            return
        key = clean_text(player.props.player_instance)
        if not key or key in self.players:
            return

        player.connect("metadata", self._on_player_changed)
        player.connect("playback-status", self._on_player_changed)
        player.connect("shuffle", self._on_player_changed)
        player.connect("loop-status", self._on_player_changed)
        player.connect("exit", self._on_player_exit)
        self.manager.manage_player(player)
        self.serial += 1
        self.players[key] = {
            "player": player,
            "state": read_player(player),
            "updated": self.serial,
        }
        if notify:
            self.on_change()

    def _remove_player(self, player):
        key = clean_text(player.props.player_instance)
        if self.players.pop(key, None) is not None:
            self.on_change()

    def _on_name_appeared(self, _manager, name):
        self.add_player(name)

    def _on_player_vanished(self, _manager, player):
        self._remove_player(player)

    def _on_player_exit(self, player, *_args):
        self._remove_player(player)

    def _on_player_changed(self, player, *_args):
        key = clean_text(player.props.player_instance)
        record = self.players.get(key)
        if record is None:
            return
        self.serial += 1
        record["state"] = read_player(player)
        record["updated"] = self.serial
        self.on_change()

    def active(self):
        if not self.players:
            return None, None
        record = max(
            self.players.values(),
            key=lambda item: (priority(item["state"]), item["updated"]),
        )
        return record["player"], dict(record["state"])


def available_players():
    manager = Playerctl.PlayerManager()
    players = []
    for name in manager.props.player_names:
        try:
            player = Playerctl.Player.new_from_name(name)
        except GLib.Error:
            continue
        if clean_text(player.props.player_name).lower() != "playerctld":
            players.append(player)
    return players


def perform_action(action):
    players = available_players()
    if not players:
        return 0
    player = max(players, key=lambda item: priority(read_player(item)))
    try:
        if action == "play-pause":
            player.play_pause()
        elif action == "next":
            player.next()
        elif action == "previous":
            player.previous()
    except GLib.Error:
        return 1
    return 0


def format_time(microseconds):
    seconds = max(0, int(microseconds // 1_000_000))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
