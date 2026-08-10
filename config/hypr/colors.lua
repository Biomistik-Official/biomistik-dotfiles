local path = os.getenv("HOME") .. "/.config/hypr/colors.conf"
local colors = {
    primary = "rgb(ffb4a8)",
    secondary = "rgb(e7bdb6)",
    tertiary = "rgb(dec48c)",
    surface = "rgb(1a1110)",
    error = "rgb(ffb4ab)",
}

local f = io.open(path, "r")
if f then
    for line in f:lines() do
        local name, value = line:match("^%s*%$([%w_]+)%s*=%s*(.-)%s*$")
        if name and value then
            colors[name] = value
        end
    end
    f:close()
end

return colors
