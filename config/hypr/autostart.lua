hl.on("hyprland.start", function()
    local commands = {
        "$HOME/.local/libexec/waybar",
        "swaync",
        "awww-daemon",
        "/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1",
        "dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP",
        "swayosd-server",
        "hypridle",
        "$HOME/.config/hypr/scripts/matugen-watcher.sh",
        "wl-paste --type text --watch cliphist store",
        "wl-paste --type image --watch cliphist store",
    }

    for _, cmd in ipairs(commands) do
        hl.exec_cmd(cmd)
    end
end)
