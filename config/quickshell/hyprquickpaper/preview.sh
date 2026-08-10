#!/usr/bin/env bash

STATE="$HOME/.local/state/noctra/current-wallpaper"
TMP="${XDG_RUNTIME_DIR:-/tmp}/noctra-wallpaper-preview-$UID"

preview_next() {
    awww img "$1" \
        --filter Bilinear \
        --transition-type right \
        --transition-duration 0.12 \
        --transition-fps 60
}

preview_prev() {
    awww img "$1" \
        --filter Bilinear \
        --transition-type left \
        --transition-duration 0.12 \
        --transition-fps 60
}

preview_hover() {
    awww img "$1" \
        --filter Bilinear \
        --transition-type grow \
        --transition-pos center \
        --transition-duration 0.10 \
        --transition-fps 60
}

case "$1" in
    --begin)
        if [ -f "$STATE" ]; then
            cp "$STATE" "$TMP"
        else
            rm -f "$TMP"
        fi
        ;;

    --restore)
        if [ -f "$TMP" ]; then
            WALL="$(cat "$TMP")"

            if [ -f "$WALL" ]; then
                awww img "$WALL" \
                    --transition-type fade \
                    --transition-duration 0.10 \
                    --transition-fps 60
            fi

            rm -f "$TMP"
        fi
        ;;

    --commit)
        rm -f "$TMP"
        ;;

    --next)
        [ -f "$2" ] && preview_next "$2"
        ;;

    --prev)
        [ -f "$2" ] && preview_prev "$2"
        ;;

    --hover)
        [ -f "$2" ] && preview_hover "$2"
        ;;
esac
