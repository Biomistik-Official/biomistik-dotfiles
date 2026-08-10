#!/usr/bin/env bash

WALL="$1"
[ -f "$WALL" ] || exit 1

# Preview теперь подтверждён
"$HOME/.config/quickshell/hyprquickpaper/preview.sh" --commit

# Full-resolution wallpaper
awww img "$WALL" \
    --transition-type fade \
    --transition-duration 0.14 \
    --transition-fps 60

# Перекрашиваем Noctra
matugen image --source-color-index 0 "$WALL"

# Запоминаем выбранные обои
mkdir -p "$HOME/.local/state/noctra"
printf '%s\n' "$WALL" > "$HOME/.local/state/noctra/current-wallpaper"

hyprctl reload
pkill -USR2 waybar 2>/dev/null || true
