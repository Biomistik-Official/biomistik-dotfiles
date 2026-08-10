import Quickshell
import Quickshell.Io
import QtQuick
import Qt.labs.folderlistmodel
import Quickshell.Wayland

PanelWindow {
    id: main

    implicitHeight: 500
    implicitWidth: Screen.width
    color: "transparent"

    aboveWindows: true
    exclusionMode: "Ignore"
    exclusiveZone: 1

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

    property string pendingPreview: ""

    Component.onCompleted: {
        Quickshell.execDetached([
            "bash",
            Quickshell.shellPath("cache.sh"),
            Quickshell.shellDir
        ])

        Quickshell.execDetached([
            "bash",
            Quickshell.shellPath("preview.sh"),
            "--begin"
        ])

        focusDelay.start()
    }

    Timer {
        id: focusDelay
        interval: 10
        repeat: false

        onTriggered: keyboard.forceActiveFocus()
    }

    /*
     * Tiny debounce for mouse hover only.
     * Q/E preview does NOT wait for this.
     */
    Timer {
        id: hoverPreviewTimer
        interval: 18
        repeat: false

        onTriggered: {
            if (main.pendingPreview !== "") {
                Quickshell.execDetached([
                    "bash",
                    Quickshell.shellPath("preview.sh"),
                    "--hover",
                    main.pendingPreview
                ])
            }
        }
    }

    FileView {
        path: Quickshell.shellPath("config.json")
        watchChanges: true

        onFileChanged: reload()

        JsonAdapter {
            id: configs

            property string wallpaper_path
            property string cache_path
            property int number_of_pictures
            property string border_color
        }
    }

    FolderListModel {
        id: folderModel

        folder: "file://" + configs.wallpaper_path
        showDirs: false
        nameFilters: ["*.png", "*.jpg", "*.jpeg"]
        sortField: FolderListModel.Name
    }

    function originalPath(i) {
        if (i < 0 || i >= folderModel.count)
            return ""

        return folderModel.get(i, "filePath")
    }

    function fileNameFor(i) {
        const path = originalPath(i)

        if (path === "")
            return ""

        return path.substring(path.lastIndexOf("/") + 1)
    }

    function thumbnailPath(i) {
        const name = fileNameFor(i)

        if (name === "")
            return ""

        return configs.cache_path + name
    }

    function previewNow(i, direction) {
        const path = thumbnailPath(i)

        if (path === "")
            return

        Quickshell.execDetached([
            "bash",
            Quickshell.shellPath("preview.sh"),
            direction,
            path
        ])
    }

    function previewHover(i) {
        const path = thumbnailPath(i)

        if (path === "")
            return

        pendingPreview = path
        hoverPreviewTimer.restart()
    }

    function restoreWallpaper() {
        hoverPreviewTimer.stop()

        Quickshell.execDetached([
            "bash",
            Quickshell.shellPath("preview.sh"),
            "--restore"
        ])
    }

    FocusScope {
        id: keyboard

        anchors.fill: parent
        focus: true

        Keys.onPressed: function(event) {
            /*
             * E = next
             * Q = previous
             *
             * Q/E use previewNow(), so there is zero debounce.
             */

            const typed = event.text.toLowerCase()

            // Physical E key:
            // EN = e
            // RU = у
            if (event.key === Qt.Key_E || typed === "e" || typed === "у") {
                list.selectRelative(1)
                event.accepted = true
                return
            }

            // Physical Q key:
            // EN = q
            // RU = й
            if (event.key === Qt.Key_Q || typed === "q" || typed === "й") {
                list.selectRelative(-1)
                event.accepted = true
                return
            }

            // arrows also work
            if (event.key === Qt.Key_Right) {
                list.selectRelative(1)
                event.accepted = true
                return
            }

            if (event.key === Qt.Key_Left) {
                list.selectRelative(-1)
                event.accepted = true
                return
            }

            // whole page
            if (event.key === Qt.Key_D) {
                list.selectRelative(configs.number_of_pictures)
                event.accepted = true
                return
            }

            if (event.key === Qt.Key_A) {
                list.selectRelative(-configs.number_of_pictures)
                event.accepted = true
                return
            }

            if (event.key === Qt.Key_Return ||
                event.key === Qt.Key_Enter ||
                event.key === Qt.Key_Space) {
                list.activateCurrent()
                event.accepted = true
                return
            }

            if (event.key === Qt.Key_Escape) {
                main.restoreWallpaper()
                Qt.quit()
                event.accepted = true
                return
            }
        }

        ListView {
            id: list

            anchors.fill: parent

            model: folderModel
            orientation: ListView.Horizontal

            spacing: 10
            clip: true
            cacheBuffer: width * 2

            property int selectedIndex: 0
            property real tileWidth:
                width / Math.max(1, configs.number_of_pictures) - 14

            function clampIndex(i) {
                return Math.max(0, Math.min(i, count - 1))
            }

            function clampX(x) {
                return Math.max(
                    0,
                    Math.min(
                        x,
                        Math.max(0, contentWidth - width)
                    )
                )
            }

            function selectRelative(amount) {
                selectedIndex = clampIndex(selectedIndex + amount)

                ensureVisibleAnimated(selectedIndex)

                // Q/E = immediate wallpaper preview
                main.previewNow(
                    selectedIndex,
                    amount > 0 ? "--next" : "--prev"
                )

                keyboard.forceActiveFocus()
            }

            function activateCurrent() {
                const path = main.originalPath(selectedIndex)

                if (path === "")
                    return

                Quickshell.execDetached([
                    "bash",
                    Quickshell.shellPath("commands.sh"),
                    path
                ])

                Qt.quit()
            }

            function ensureVisibleAnimated(i) {
                const step = tileWidth + spacing
                const itemStart = i * step
                const itemEnd = itemStart + tileWidth

                if (itemStart < contentX) {
                    contentX = clampX(itemStart)
                } else if (itemEnd > contentX + width) {
                    contentX = clampX(
                        itemStart - (width - step)
                    )
                }
            }

            Behavior on contentX {
                NumberAnimation {
                    duration: 145
                    easing.type: Easing.OutCubic
                }
            }

            delegate: Item {
                id: tile

                required property int index
                required property string fileName

                property bool active:
                    index === list.selectedIndex

                width: list.tileWidth
                height: 500

                scale: active ? 1.0 : 0.90
                opacity: active ? 1.0 : 0.55

                Behavior on scale {
                    NumberAnimation {
                        duration: 130
                        easing.type: Easing.OutCubic
                    }
                }

                Behavior on opacity {
                    NumberAnimation {
                        duration: 120
                        easing.type: Easing.OutCubic
                    }
                }

                Text {
                    text: "Caching"
                    color: configs.border_color

                    anchors.centerIn: parent

                    font.pixelSize: 16
                }

                Image {
                    id: image

                    anchors.fill: parent

                    fillMode: Image.PreserveAspectCrop

                    asynchronous: true
                    cache: true
                    smooth: true

                    source:
                        "file://" +
                        configs.cache_path +
                        tile.fileName

                    sourceSize.width: tile.width
                    sourceSize.height: tile.height
                }

                Rectangle {
                    anchors.fill: parent

                    visible: tile.active

                    color: "transparent"

                    border.width: 4
                    border.color: configs.border_color

                    opacity: tile.active ? 1.0 : 0.0

                    Behavior on opacity {
                        NumberAnimation {
                            duration: 100
                        }
                    }
                }

                MouseArea {
                    anchors.fill: parent

                    hoverEnabled: true

                    onEntered: {
                        keyboard.forceActiveFocus()

                        list.selectedIndex = tile.index
                        list.ensureVisibleAnimated(tile.index)

                        /*
                         * Mouse hover gets tiny 18ms debounce,
                         * just enough to avoid firing 5 wallpapers
                         * while crossing cards.
                         */
                        main.previewHover(tile.index)
                    }

                    onClicked: {
                        keyboard.forceActiveFocus()

                        list.selectedIndex = tile.index
                        list.activateCurrent()
                    }

                    onWheel: function(wheel) {
                        keyboard.forceActiveFocus()

                        if (wheel.angleDelta.y < 0)
                            list.selectRelative(1)
                        else
                            list.selectRelative(-1)

                        wheel.accepted = true
                    }
                }
            }
        }
    }
}
