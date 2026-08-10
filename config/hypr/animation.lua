hl.config({ animations = { enabled = true } })

hl.curve("spring", {
    type = "bezier",
    points = { { 0.13, 0.99 }, { 0.29, 1.10 } },
})

hl.curve("smooth", {
    type = "bezier",
    points = { { 0.25, 1.00 }, { 0.50, 1.00 } },
})

hl.curve("sharp", {
    type = "bezier",
    points = { { 0.40, 0.00 }, { 0.20, 1.00 } },
})

hl.animation({ leaf = "windows",     enabled = true, speed = 4,  bezier = "spring", style = "popin 80%" })
hl.animation({ leaf = "windowsOut",  enabled = true, speed = 3,  bezier = "sharp",  style = "popin 80%" })
hl.animation({ leaf = "windowsMove", enabled = true, speed = 4,  bezier = "spring" })
hl.animation({ leaf = "fade",        enabled = true, speed = 2,  bezier = "sharp" })
hl.animation({ leaf = "border",      enabled = true, speed = 5,  bezier = "smooth" })
hl.animation({ leaf = "borderangle", enabled = true, speed = 30, bezier = "smooth", style = "loop" })
hl.animation({ leaf = "workspaces",  enabled = true, speed = 4,  bezier = "smooth", style = "slidefade 20%" })
