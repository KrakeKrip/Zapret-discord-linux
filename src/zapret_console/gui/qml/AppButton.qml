import QtQuick
import QtQuick.Controls

// Кнопки трёх вариантов из design/gui-v1/SPEC.md: primary/secondary/danger.
Button {
    id: control
    property string variant: "secondary"

    implicitHeight: 40
    implicitWidth: Math.max(contentItem.implicitWidth + leftPadding + rightPadding, 96)
    leftPadding: 18
    rightPadding: 18
    topPadding: 8
    bottomPadding: 8
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Keys.onReturnPressed: { if (enabled) click(); }
    Keys.onEnterPressed: { if (enabled) click(); }

    readonly property bool isPrimary: variant === "primary"
    readonly property bool isDanger: variant === "danger"
    readonly property bool isDestructive: variant === "destructive"

    background: Item {
        Rectangle {
            // явная контрастная рамка фокуса с отступом 2 px
            anchors.fill: parent
            radius: 12
            color: "transparent"
            border.color: Theme.accent
            border.width: control.visualFocus ? 1.4 : 0
            visible: control.visualFocus
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: 2
            radius: 9
            border.width: 1
            border.color: !control.enabled ? Theme.borderMuted : Theme.border
            Behavior on color {
                ColorAnimation {
                    duration: 120
                }
            }
            color: {
                if (!control.enabled)
                    return control.isPrimary ? Theme.activeNav : Theme.card;
                if (control.isDestructive)
                    return control.pressed ? "#d47777" : (control.hovered ? "#f4aaaa" : Theme.danger);
                if (control.isPrimary)
                    return control.pressed ? Theme.accentPress : (control.hovered ? Theme.accentHover : Theme.accent);
                if (control.down)
                    return Theme.activeNav;
                if (control.hovered)
                    return Theme.secondaryHover;
                return Theme.secondaryButton;
            }
        }
    }
    contentItem: Label {
        text: control.text
        font.pixelSize: 13
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: {
            if (!control.enabled)
                return Theme.muted;
            if (control.isPrimary || control.isDestructive)
                return Theme.background;
            if (control.isDanger)
                return Theme.danger;
            return Theme.text;
        }
        Behavior on color {
            ColorAnimation {
                duration: 120
            }
        }
    }
}
