#!/usr/bin/env bash

set -Eeuo pipefail

STAMP="$(date +%Y-%m-%d-%H%M%S)"
DRY_RUN=false
RESTORE=false
WITH_SDDM=false

usage() {
    cat <<'EOF'
Usage: ./uninstall.sh [options]

Without --restore-latest, installed targets are moved to *.removed-TIMESTAMP.
Nothing is permanently deleted.

Options:
  --dry-run          Show actions without changing anything
  --restore-latest   Restore the newest adjacent *.backup-TIMESTAMP per target
  --with-sddm        Also process the system-wide SDDM theme/config (uses sudo)
  -h, --help         Show this help
EOF
}

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --restore-latest) RESTORE=true ;;
        --with-sddm) WITH_SDDM=true ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$arg" >&2; usage >&2; exit 2 ;;
    esac
done

info() { printf '\033[1;35m==>\033[0m %s\n' "$*"; }
show_cmd() { printf '  '; printf '%q ' "$@"; printf '\n'; }
run() { show_cmd "$@"; "$DRY_RUN" || "$@"; }
exists() { [[ -e "$1" || -L "$1" ]]; }

latest_backup() {
    local target="$1" candidate latest=""
    shopt -s nullglob
    for candidate in "${target}.backup-"*; do
        if [[ -z "$latest" || "$candidate" > "$latest" ]]; then
            latest="$candidate"
        fi
    done
    shopt -u nullglob
    printf '%s' "$latest"
}

process_user_target() {
    local target="$1" backup=""
    if "$RESTORE"; then
        backup="$(latest_backup "$target")"
        if [[ -z "$backup" ]]; then
            info "No backup found for $target; leaving it untouched"
            return 0
        fi
        if exists "$target"; then
            run mv -- "$target" "${target}.removed-${STAMP}"
        fi
        run mv -- "$backup" "$target"
    elif exists "$target"; then
        run mv -- "$target" "${target}.removed-${STAMP}"
    fi
}

run systemctl --user disable --now \
    waybar-media-source.service \
    waybar-panel-menu.service \
    noctra-sddm-colors.path 2>/dev/null || true

for name in hypr quickshell waybar swaync matugen fish kitty rofi fastfetch cava btop gtk-3.0 qt6ct uwsm; do
    process_user_target "$HOME/.config/$name"
done

for name in lang-osd-daemon sync-sddm-colors sync-sddm-wallpaper wallpaper-menu wallpaper-menu.real wallpaper-picker; do
    process_user_target "$HOME/.local/bin/$name"
done
process_user_target "$HOME/.local/libexec/waybar"
process_user_target "$HOME/.local/share/icons/Moga-Black"
process_user_target "$HOME/Pictures/Wallpapers"

for unit in noctra-sddm-colors.path noctra-sddm-colors.service waybar-media-source.service waybar-panel-menu.service; do
    process_user_target "$HOME/.config/systemd/user/$unit"
done

run systemctl --user daemon-reload

if "$WITH_SDDM"; then
    for target in /usr/share/sddm/themes/noctra-material /etc/sddm.conf.d/10-noctra-theme.conf; do
        if "$RESTORE"; then
            backup="$(latest_backup "$target")"
            if [[ -z "$backup" ]]; then
                info "No system backup found for $target; leaving it untouched"
                continue
            fi
            if exists "$target"; then
                run sudo mv -- "$target" "${target}.removed-${STAMP}"
            fi
            run sudo mv -- "$backup" "$target"
        elif exists "$target"; then
            run sudo mv -- "$target" "${target}.removed-${STAMP}"
        fi
    done
fi

if "$RESTORE"; then
    info "Latest available backups restored. Current installed copies were moved to *.removed-$STAMP"
else
    info "Installed targets moved to *.removed-$STAMP; no user data was deleted."
fi
