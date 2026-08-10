local M = "SUPER"
local exec = hl.dsp.exec_cmd

-- Apps
hl.bind(M .. " + T", exec("kitty"))
hl.bind(M .. " + E", exec("thunar"))
hl.bind(M .. " + W", exec("zen-browser"))
hl.bind(M .. " + A", exec("pkill rofi || rofi -show drun"))
hl.bind(M .. " + SUPER_L", exec("pkill rofi || rofi -show drun"), { release = true })
hl.bind("CTRL + SHIFT + Escape", exec("kitty --class btop -e btop"))

-- Windows
hl.bind(M .. " + Q", hl.dsp.window.close())
hl.bind(M .. " + F", hl.dsp.window.fullscreen({ mode = "fullscreen", action = "toggle" }))
hl.bind(M .. " + ALT + F", hl.dsp.window.fullscreen({ mode = "maximized", action = "toggle" }))
hl.bind(M .. " + ALT + Space", hl.dsp.window.float({ action = "toggle" }))
hl.bind(M .. " + P", hl.dsp.window.pin())
hl.bind("ALT + Tab", hl.dsp.window.cycle_next({ next = true }))
hl.bind("ALT + SHIFT + Tab", hl.dsp.window.cycle_next({ next = false }))

local dirs = {
    Left = "l",
    Right = "r",
    Up = "u",
    Down = "d",
}
for key, dir in pairs(dirs) do
    hl.bind(M .. " + " .. key, hl.dsp.focus({ direction = dir }))
    hl.bind(M .. " + SHIFT + " .. key, hl.dsp.window.move({ direction = dir }))
end

hl.bind(M .. " + Minus", hl.dsp.window.resize({ x = -10, y = 0, relative = true }), { repeating = true })
hl.bind(M .. " + Equal", hl.dsp.window.resize({ x = 10, y = 0, relative = true }), { repeating = true })
hl.bind(M .. " + SHIFT + Minus", hl.dsp.window.resize({ x = 0, y = -10, relative = true }), { repeating = true })
hl.bind(M .. " + SHIFT + Equal", hl.dsp.window.resize({ x = 0, y = 10, relative = true }), { repeating = true })

hl.bind(M .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind(M .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

-- Workspaces
for i = 1, 10 do
    local key = i % 10
    hl.bind(M .. " + " .. key, hl.dsp.focus({ workspace = i }))
    hl.bind(M .. " + ALT + " .. key, hl.dsp.window.move({ workspace = i }))
end

hl.bind(M .. " + mouse_down", hl.dsp.focus({ workspace = "+1" }))
hl.bind(M .. " + mouse_up", hl.dsp.focus({ workspace = "-1" }))
hl.bind("CTRL + " .. M .. " + Right", hl.dsp.focus({ workspace = "+1" }))
hl.bind("CTRL + " .. M .. " + Left", hl.dsp.focus({ workspace = "-1" }))
hl.bind(M .. " + Page_Down", hl.dsp.focus({ workspace = "+1" }))
hl.bind(M .. " + Page_Up", hl.dsp.focus({ workspace = "-1" }))

hl.bind(M .. " + ALT + mouse_down", hl.dsp.window.move({ workspace = "+1" }))
hl.bind(M .. " + ALT + mouse_up", hl.dsp.window.move({ workspace = "-1" }))
hl.bind(M .. " + ALT + Page_Down", hl.dsp.window.move({ workspace = "+1" }))
hl.bind(M .. " + ALT + Page_Up", hl.dsp.window.move({ workspace = "-1" }))

-- System
hl.bind(M .. " + N", exec("swaync-client -t"))
hl.bind("CTRL + ALT + Delete", exec("$HOME/.config/waybar/scripts/sys-menu.sh"))
hl.bind(M .. " + Escape", exec("$HOME/.config/waybar/scripts/sys-menu.sh"))
hl.bind(M .. " + L", exec("hyprlock"))
hl.bind(M .. " + SHIFT + L", exec("systemctl suspend"), { locked = true })

-- Screenshots
hl.bind("Print", exec("$HOME/.config/hypr/scripts/screenshot.sh full"))
hl.bind(M .. " + SHIFT + S", exec("$HOME/.config/hypr/scripts/screenshot.sh area"))
hl.bind(M .. " + SHIFT + ALT + S", exec("$HOME/.config/hypr/scripts/screenshot.sh area"))

-- Screen recording
hl.bind("CTRL + ALT + R", exec("$HOME/.config/hypr/scripts/screen-record.sh full"))
hl.bind(M .. " + ALT + R", exec("$HOME/.config/hypr/scripts/screen-record.sh full"))
hl.bind(M .. " + SHIFT + ALT + R", exec("$HOME/.config/hypr/scripts/screen-record.sh area"))

-- Media
hl.bind("CTRL + " .. M .. " + Space", exec("playerctl play-pause"), { locked = true })
hl.bind("CTRL + " .. M .. " + Equal", exec("playerctl next"), { locked = true })
hl.bind("CTRL + " .. M .. " + Minus", exec("playerctl previous"), { locked = true })
hl.bind("CTRL + " .. M .. " + Backspace", exec("playerctl stop"), { locked = true })
hl.bind(M .. " + SHIFT + M", exec("swayosd-client --output-volume mute-toggle"), { locked = true })

-- Laptop keys
hl.bind("XF86AudioRaiseVolume", exec("swayosd-client --output-volume raise"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume", exec("swayosd-client --output-volume lower"), { locked = true, repeating = true })
hl.bind("XF86AudioMute", exec("swayosd-client --output-volume mute-toggle"), { locked = true })
hl.bind("XF86AudioMicMute", exec("swayosd-client --input-volume mute-toggle"), { locked = true })
hl.bind("XF86MonBrightnessUp", exec("swayosd-client --brightness raise"), { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown", exec("swayosd-client --brightness lower"), { locked = true, repeating = true })
hl.bind("XF86AudioPlay", exec("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPause", exec("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioNext", exec("playerctl next"), { locked = true })
hl.bind("XF86AudioPrev", exec("playerctl previous"), { locked = true })

-- Extras
hl.bind(M .. " + V", exec([[cliphist list | rofi -dmenu -p "Clipboard" | cliphist decode | wl-copy]]))
hl.bind(M .. " + ALT + V", exec([[cliphist list | rofi -dmenu -p "Delete clipboard item" | cliphist delete]]))
hl.bind(M .. " + period", exec("rofimoji --action type"))
hl.bind(M .. " + SHIFT + C", exec("hyprpicker -a"))
hl.bind(M .. " + C", exec("code"))
hl.bind(M .. " + SHIFT + W", exec("$HOME/.local/bin/wallpaper-menu"))

-- Move window under cursor to workspace, stay on current workspace
for i = 1, 10 do
    local key = i == 10 and "0" or tostring(i)
    hl.bind(M .. " + SHIFT + " .. key, exec("~/.config/hypr/scripts/move-hovered.sh " .. i))
end
