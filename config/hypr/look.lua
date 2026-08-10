local c = require("colors")

hl.config({
    general = {
        gaps_in = 5,
        gaps_out = 10,
        border_size = 2,
        col = {
            active_border = {
                colors = { c.primary, c.secondary },
                angle = 45,
            },
            inactive_border = "rgba(00000000)",
        },
        resize_on_border = true,
        allow_tearing = false,
        layout = "dwindle",
    },

    decoration = {
        rounding = 14,
        rounding_power = 2.0,
        active_opacity = 1.0,
        inactive_opacity = 0.90,
        shadow = {
            enabled = true,
            range = 15,
            render_power = 3,
            color = "rgba(00000099)",
            offset = { 0, 4 },
        },
        blur = {
            enabled = true,
            size = 8,
            passes = 2,
            noise = 0.0117,
            contrast = 0.8916,
            brightness = 0.8172,
            vibrancy = 0.1696,
            new_optimizations = true,
            ignore_opacity = true,
            popups = true,
        },
    },
})
