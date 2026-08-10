#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION=0.15.0
INSTALL=false
[[ "${1:-}" == "--install" ]] && INSTALL=true

for command in git meson ninja pkg-config; do
    command -v "$command" >/dev/null || {
        printf 'Missing build command: %s\nInstall packages from packages/waybar-build-pacman.txt first.\n' "$command" >&2
        exit 1
    }
done

work_dir="$(mktemp -d)"
source_dir="$work_dir/Waybar"
output="$ROOT/build/waybar-$VERSION-patched"

printf 'Build directory: %s\n' "$work_dir"
git clone --depth 1 --branch "$VERSION" https://github.com/Alexays/Waybar.git "$source_dir"
git -C "$source_dir" apply "$ROOT/patches/waybar/AModule-hover.patch"
meson setup "$source_dir/build" "$source_dir" --buildtype=release
meson compile -C "$source_dir/build"
mkdir -p -- "$ROOT/build"
install -m 0755 "$source_dir/build/waybar" "$output"
printf 'Built: %s\n' "$output"

if "$INSTALL"; then
    target="$HOME/.local/libexec/waybar"
    if [[ -e "$target" || -L "$target" ]]; then
        mv -- "$target" "${target}.backup-$(date +%Y-%m-%d-%H%M%S)"
    fi
    mkdir -p -- "$(dirname -- "$target")"
    install -m 0755 "$output" "$target"
    printf 'Installed: %s\n' "$target"
fi
