#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date +%Y-%m-%d-%H%M%S)"
DRY_RUN=false
INSTALL_PACKAGES=true
INSTALL_SDDM=true

usage() {
    cat <<'EOF'
Usage: ./install.sh [options]

Options:
  --dry-run       Show every action without changing the system
  --no-packages   Do not install pacman/AUR dependencies
  --no-sddm       Do not install the system-wide SDDM theme
  -h, --help      Show this help
EOF
}

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --no-packages) INSTALL_PACKAGES=false ;;
        --no-sddm) INSTALL_SDDM=false ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$arg" >&2; usage >&2; exit 2 ;;
    esac
done

info() { printf '\033[1;35m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }

show_cmd() {
    printf '  '
    printf '%q ' "$@"
    printf '\n'
}

run() {
    show_cmd "$@"
    "$DRY_RUN" || "$@"
}

exists() {
    [[ -e "$1" || -L "$1" ]]
}

same_content() {
    exists "$2" || return 1
    local escaped_home
    escaped_home="$(printf '%s' "$HOME" | sed 's/[&|]/\\&/g')"
    if [[ "$1" == "$ROOT/config/quickshell" ]]; then
        diff -qr --no-dereference --exclude=config.json "$1" "$2" >/dev/null 2>&1 &&
            cmp -s <(sed "s|__HOME__|$escaped_home|g" "$1/hyprquickpaper/config.json") \
                "$2/hyprquickpaper/config.json"
        return
    fi
    if [[ "$1" == "$ROOT/config/fish" ]]; then
        diff -qr --no-dereference --exclude=fish_variables "$1" "$2" >/dev/null 2>&1 &&
            cmp -s <(sed "s|__HOME__|$escaped_home|g" "$1/fish_variables") \
                "$2/fish_variables"
        return
    fi
    diff -qr --no-dereference "$1" "$2" >/dev/null 2>&1
}

backup_existing() {
    local target="$1"
    exists "$target" || return 0
    local backup="${target}.backup-${STAMP}"
    info "Backup: $target -> $backup"
    run mv -- "$target" "$backup"
}

install_tree() {
    local source="$1" target="$2"
    if same_content "$source" "$target"; then
        info "Already current: $target"
        return 0
    fi
    backup_existing "$target"
    run mkdir -p -- "$(dirname -- "$target")"
    info "Install directory: $target"
    run cp -a -- "$source" "$target"
}

install_file() {
    local source="$1" target="$2" mode="${3:-0644}"
    if [[ -f "$target" ]] && cmp -s "$source" "$target"; then
        info "Already current: $target"
        "$DRY_RUN" || chmod "$mode" "$target"
        return 0
    fi
    backup_existing "$target"
    run mkdir -p -- "$(dirname -- "$target")"
    info "Install file: $target"
    run install -m "$mode" -- "$source" "$target"
}

read_package_file() {
    local file="$1" line
    local -n output="$2"
    output=()
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%%#*}"
        line="${line//[[:space:]]/}"
        [[ -n "$line" ]] && output+=("$line")
    done < "$file"
    return 0
}

install_dependencies() {
    local os_id="" os_like=""
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
        os_id="${ID:-}"
        os_like="${ID_LIKE:-}"
    fi
    if [[ "$os_id" != "cachyos" && "$os_id" != "arch" && "$os_like" != *arch* ]]; then
        warn "This installer targets CachyOS/Arch; detected ID=$os_id ID_LIKE=$os_like"
    fi
    command -v pacman >/dev/null || { printf 'pacman is required.\n' >&2; exit 1; }

    local -a pacman_packages aur_packages
    read_package_file "$ROOT/packages/rice-pacman.txt" pacman_packages
    read_package_file "$ROOT/packages/rice-aur.txt" aur_packages

    info "Install ${#pacman_packages[@]} repository dependencies with pacman"
    run sudo pacman -S --needed "${pacman_packages[@]}"

    local helper=""
    if command -v paru >/dev/null; then
        helper=paru
    elif command -v yay >/dev/null; then
        helper=yay
    fi
    if [[ -n "$helper" ]]; then
        info "Install ${#aur_packages[@]} AUR dependencies with $helper"
        run "$helper" -S --needed "${aur_packages[@]}"
    else
        warn "Neither paru nor yay was found. Install these AUR packages manually: ${aur_packages[*]}"
    fi
}

install_sddm_theme() {
    local source_theme="$ROOT/sddm/noctra-material"
    local target_theme="/usr/share/sddm/themes/noctra-material"
    local source_conf="$ROOT/sddm/config/10-noctra-theme.conf"
    local target_conf="/etc/sddm.conf.d/10-noctra-theme.conf"

    info "Install SDDM theme (the following operations require sudo)"
    if exists "$target_theme"; then
        if ! diff -qr --no-dereference "$source_theme" "$target_theme" >/dev/null 2>&1; then
            run sudo mv -- "$target_theme" "${target_theme}.backup-${STAMP}"
            run sudo mkdir -p -- /usr/share/sddm/themes
            run sudo cp -a -- "$source_theme" "$target_theme"
        else
            info "Already current: $target_theme"
        fi
    else
        run sudo mkdir -p -- /usr/share/sddm/themes
        run sudo cp -a -- "$source_theme" "$target_theme"
    fi

    if [[ -f "$target_conf" ]]; then
        if ! cmp -s "$source_conf" "$target_conf"; then
            run sudo mv -- "$target_conf" "${target_conf}.backup-${STAMP}"
            run sudo mkdir -p -- /etc/sddm.conf.d
            run sudo install -m 0644 -- "$source_conf" "$target_conf"
        else
            info "Already current: $target_conf"
        fi
    else
        run sudo mkdir -p -- /etc/sddm.conf.d
        run sudo install -m 0644 -- "$source_conf" "$target_conf"
    fi

    # The live rice updates these two files from user services after Matugen runs.
    local login_user login_group
    login_user="$(id -un)"
    login_group="$(id -gn)"
    run sudo chown "$login_user:$login_group" \
        "$target_theme/theme.conf.user" \
        "$target_theme/Backgrounds/current.png"
}

if "$INSTALL_PACKAGES"; then
    install_dependencies
else
    info "Package installation skipped"
fi

info "Install user configuration"
for name in hypr quickshell waybar swaync matugen fish kitty rofi fastfetch cava btop gtk-3.0 qt6ct uwsm; do
    install_tree "$ROOT/config/$name" "$HOME/.config/$name"
done

info "Install rice scripts"
for source in "$ROOT/local/bin/"*; do
    install_file "$source" "$HOME/.local/bin/$(basename -- "$source")" 0755
done
install_file "$ROOT/local/libexec/waybar" "$HOME/.local/libexec/waybar" 0755
install_tree "$ROOT/local/share/icons/Moga-Black" "$HOME/.local/share/icons/Moga-Black"
install_tree "$ROOT/wallpapers" "$HOME/Pictures/Wallpapers"

info "Install systemd user units"
for source in "$ROOT/systemd/user/"*; do
    install_file "$source" "$HOME/.config/systemd/user/$(basename -- "$source")" 0644
done

if ! "$DRY_RUN"; then
    escaped_home="$(printf '%s' "$HOME" | sed 's/[&|]/\\&/g')"
    sed -i "s|__HOME__|$escaped_home|g" \
        "$HOME/.config/quickshell/hyprquickpaper/config.json" \
        "$HOME/.config/fish/fish_variables"
fi

run systemctl --user daemon-reload
run systemctl --user enable --now \
    waybar-media-source.service \
    waybar-panel-menu.service \
    noctra-sddm-colors.path

if command -v gsettings >/dev/null; then
    run gsettings set org.gnome.desktop.interface gtk-theme Adwaita-dark
    run gsettings set org.gnome.desktop.interface icon-theme Adwaita
    run gsettings set org.gnome.desktop.interface cursor-theme Moga-Black
fi

if "$INSTALL_SDDM"; then
    install_sddm_theme
else
    info "SDDM installation skipped"
fi

if ! "$DRY_RUN" && ldd "$HOME/.local/libexec/waybar" 2>&1 | grep -q 'not found'; then
    warn "The bundled patched Waybar has missing shared libraries. Rebuild it with scripts/build-patched-waybar.sh --install."
fi

info "Done. Existing targets were preserved as *.backup-$STAMP"
info "Log out and back in (or reboot) to load the complete Hyprland/UWSM session."
