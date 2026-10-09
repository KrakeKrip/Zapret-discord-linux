pragma Singleton
import QtQuick

QtObject {
    readonly property color background: "#14181d"
    readonly property color panel: "#1b2229"
    readonly property color panelAlt: "#212a33"
    readonly property color line: "#2b3540"
    readonly property color text: "#e7ecef"
    readonly property color muted: "#9aa8b2"
    readonly property color accent: "#2fa89a"
    readonly property color accentDim: "#215f58"
    readonly property color danger: "#d96a6a"
    readonly property color warn: "#d9a55a"
    readonly property color ok: "#5cb270"

    function toneColor(tone) {
        if (tone === "ok")
            return ok
        if (tone === "warn")
            return warn
        if (tone === "error")
            return danger
        return muted
    }
}
