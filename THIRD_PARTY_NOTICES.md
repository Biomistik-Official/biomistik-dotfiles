# Third-party notices

The root MIT license covers Biomistik's original configuration and scripts only.
It does not relicense the components and artwork listed below.

## SDDM theme

`sddm/noctra-material/` is a customized copy of **Sugar Candy** by Marian Arlt.
Sugar Candy is licensed under GPL-3.0-or-later. Its license is preserved at
`sddm/noctra-material/LICENSE` and its original author metadata remains in
`metadata.desktop`.

## HyprQuickPaper

`config/quickshell/hyprquickpaper/` is based on
[HyprQuickPaper](https://github.com/iamsurjog/hyprquickpaper), pinned from commit
`d380bee81a87e7581360f6b386b6dd72469092b1` and locally customized. The upstream
repository contained no license file at that commit and still had no license
file when this snapshot was prepared. Treat this directory as not covered by
the root MIT license and obtain permission from the upstream author before
public redistribution.

## Waybar

`local/libexec/waybar` is a local build of Waybar 0.15.0. Waybar is MIT-licensed.
The source-level local changes are preserved in
`patches/waybar/AModule-hover.patch`; use `scripts/build-patched-waybar.sh` to
rebuild instead of relying permanently on the bundled Arch x86_64 binary.

## Cursor and artwork

`local/share/icons/Moga-Black/` identifies its creator as Moyash but contains no
local license file. The wallpaper collection, Fastfetch character images and
the screenshot may contain third-party game/artwork assets whose redistribution
terms were not present in the local files. These assets are included for a
private personal backup and are not covered by the MIT license. Review or
replace them before making the repository public.
