#!/usr/bin/env bash

TARGET="$1"

# Координаты мышки
read -r CX CY <<< "$(hyprctl cursorpos | tr -d ',')"

# Текущий workspace
WS="$(hyprctl activeworkspace -j | jq -r '.id')"

# Ищем окно именно под мышкой и только на текущем workspace
ADDR="$(
    hyprctl clients -j | jq -r \
        --argjson x "$CX" \
        --argjson y "$CY" \
        --argjson ws "$WS" '
        [
            .[]
            | select(
                .workspace.id == $ws
                and $x >= .at[0]
                and $x < (.at[0] + .size[0])
                and $y >= .at[1]
                and $y < (.at[1] + .size[1])
            )
        ]
        | sort_by(.focusHistoryID)
        | .[0].address // empty
    '
)"

[ -z "$ADDR" ] && exit 0

# Новый Lua dispatcher Hyprland
hyprctl dispatch \
    "hl.dsp.window.move({ workspace = $TARGET, follow = false, window = \"address:$ADDR\" })"
