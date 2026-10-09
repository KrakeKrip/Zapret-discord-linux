pragma Singleton
import QtQuick

QtObject {
    // Токены design/gui-v1/SPEC.md
    readonly property color background: "#0d1318"
    readonly property color sidebar: "#10191f"
    readonly property color input: "#10191f"
    readonly property color card: "#162129"
    readonly property color secondaryButton: "#1d2b34"
    readonly property color secondaryHover: "#273844"
    readonly property color border: "#293943"
    readonly property color borderMuted: "#223039"
    readonly property color text: "#ecf2f5"
    readonly property color muted: "#a1b1ba"
    readonly property color accent: "#73e2c2"
    readonly property color accentHover: "#8bebd0"
    readonly property color accentPress: "#59cdae"
    readonly property color accentDimText: "#233f39"
    readonly property color activeNav: "#213731"
    readonly property color activeStrategy: "#182c28"
    readonly property color activeStrategyBorder: "#36554a"
    readonly property color chip: "#1c302e"
    readonly property color statusIconBg: "#203c33"
    readonly property color warning: "#f0bd72"
    readonly property color warningBorder: "#65523b"
    readonly property color danger: "#ee9191"
    readonly property color overlay: "#cc080c10"
    readonly property color dialogPanel: "#18232c"
    readonly property color dialogBorder: "#384b58"

    function toneColor(tone) {
        if (tone === "ok" || tone === "accent")
            return accent;
        if (tone === "warn")
            return warning;
        if (tone === "error")
            return danger;
        return muted;
    }
}
