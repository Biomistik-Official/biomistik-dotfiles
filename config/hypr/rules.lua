-- Layer rules
hl.layer_rule({
    name = "rofi-blur",
    match = { namespace = "rofi" },
    blur = true,
    ignore_alpha = 0.1,
})

hl.layer_rule({
    name = "waybar-blur",
    match = { namespace = "waybar" },
    blur = true,
    ignore_alpha = 0.2,
})

hl.layer_rule({
    name = "swaync-control-no-blur",
    match = { namespace = "swaync-control-center" },
    blur = false,
})

hl.layer_rule({
    name = "swaync-notification-no-blur",
    match = { namespace = "swaync-notification-window" },
    blur = false,
})

-- Window rules
hl.window_rule({
    name = "suppress-maximize",
    match = { class = ".*" },
    suppress_event = "maximize",
})

hl.window_rule({
    name = "utilities",
    match = { class = "^(pavucontrol|nm-connection-editor)$" },
    float = true,
    center = true,
    size = { 620, 440 },
})

hl.window_rule({
    name = "blueman",
    match = { class = "^(blueman-manager)$" },
    float = true,
    center = true,
})

hl.window_rule({
    name = "dialogs",
    match = { title = "^(Open File|Save File|Open Folder|File Chooser)$" },
    float = true,
    center = true,
})

hl.window_rule({
    name = "pip",
    match = { title = "^(Picture-in-Picture)$" },
    float = true,
    pin = true,
    size = { 480, 270 },
    no_initial_focus = true,
    move = { "(monitor_w-490)", "(monitor_h-280)" },
})

hl.window_rule({
    name = "fix-xwayland-drags",
    match = {
        class = "^$",
        title = "^$",
        xwayland = true,
        float = true,
    },
    no_focus = true,
})

hl.window_rule({
    name = "floating-nmtui",
    match = { class = "^(floating_nmtui)$" },
    float = true,
    center = true,
    size = { 700, 500 },
    dim_around = true,
})
