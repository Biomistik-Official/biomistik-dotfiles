source /usr/share/cachyos-fish-config/cachyos-config.fish

# Disable CachyOS default Fastfetch greeting
function fish_greeting
end

# Random Fastfetch anime girl
if status is-interactive
    set anime (find ~/.config/fastfetch/images -type f | shuf -n 1)
    if test -n "$anime"
        fastfetch --logo-type kitty --logo "$anime"
    end
end

# Manual random Fastfetch
function fetch
    set anime (find ~/.config/fastfetch/images -type f | shuf -n 1)
    fastfetch --logo-type kitty --logo "$anime"
end
