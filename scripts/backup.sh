#!/usr/bin/env bash

set -Eeuo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true
STAMP="$(date +%Y-%m-%d-%H%M%S)"
DEST="$HOME/dotfiles-backups/biomistik-dotfiles-$STAMP"

sources=(
    "$HOME/.config/hypr"
    "$HOME/.config/quickshell"
    "$HOME/.config/waybar"
    "$HOME/.config/swaync"
    "$HOME/.config/matugen"
    "$HOME/.config/fish"
    "$HOME/.config/kitty"
    "$HOME/.config/rofi"
    "$HOME/.config/fastfetch"
    "$HOME/.config/cava"
    "$HOME/.config/btop"
    "$HOME/.config/gtk-3.0"
    "$HOME/.config/qt6ct"
    "$HOME/.config/uwsm"
    "$HOME/.config/systemd/user/noctra-sddm-colors.path"
    "$HOME/.config/systemd/user/noctra-sddm-colors.service"
    "$HOME/.config/systemd/user/waybar-media-source.service"
    "$HOME/.config/systemd/user/waybar-panel-menu.service"
    "$HOME/.local/bin/lang-osd-daemon"
    "$HOME/.local/bin/sync-sddm-colors"
    "$HOME/.local/bin/sync-sddm-wallpaper"
    "$HOME/.local/bin/wallpaper-menu"
    "$HOME/.local/bin/wallpaper-menu.real"
    "$HOME/.local/bin/wallpaper-picker"
    "$HOME/.local/libexec/waybar"
    "$HOME/.local/share/waybar-hover"
    "$HOME/.local/share/icons/Moga-Black"
    "$HOME/Pictures/Wallpapers"
    /etc/sddm.conf.d/10-noctra-theme.conf
    /usr/share/sddm/themes/noctra-material
)

existing=()
for source in "${sources[@]}"; do
    [[ -e "$source" || -L "$source" ]] && existing+=("$source")
done

printf 'Backup destination: %s\n' "$DEST"
printf 'Sources: %s\n' "${#existing[@]}"
if "$DRY_RUN"; then
    printf '  %s\n' "${existing[@]}"
    exit 0
fi

mkdir -p -- "$DEST"
rsync -aR "${existing[@]}" "$DEST/"
printf 'Backup complete: %s (%s)\n' "$DEST" "$(du -sh "$DEST" | cut -f1)"
