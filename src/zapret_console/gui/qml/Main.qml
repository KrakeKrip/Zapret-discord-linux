import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1040
    height: 720
    minimumWidth: 800
    minimumHeight: 560
    visible: true
    title: qsTr("Zapret Console")
    color: Theme.background

    onClosing: function (close) {
        if (!bridge.requestClose())
            close.accepted = false
    }

    component ToneChip: Rectangle {
        property string label: ""
        property string tone: "muted"
        width: chipLabel.implicitWidth + 20
        height: 26
        radius: 13
        color: Theme.panelAlt
        border.color: Theme.toneColor(tone)
        border.width: 1
        Label {
            id: chipLabel
            anchors.centerIn: parent
            text: parent.label
            color: Theme.toneColor(parent.tone)
            font.bold: true
        }
    }

    component ActionButton: Button {
        enabled: !bridge.busy && !bridge.closing
        background: Rectangle {
            radius: 6
            color: parent.enabled
                    ? (parent.down || parent.checked ? Theme.accentDim : Theme.panelAlt)
                    : Theme.panel
            border.color: parent.enabled ? Theme.accent : Theme.line
        }
        contentItem: Label {
            text: parent.text
            color: parent.enabled ? Theme.text : Theme.muted
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    header: ToolBar {
        background: Rectangle { color: Theme.panel }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 12
            Label {
                text: qsTr("Zapret Console")
                font.pixelSize: 18
                font.bold: true
                color: Theme.text
            }
            Item { Layout.fillWidth: true }
            ToneChip {
                label: qsTr("Сервис: ") + bridge.serviceText
                tone: bridge.serviceTone
            }
            ToneChip {
                label: qsTr("Автозапуск: ") + bridge.autostartText
                tone: bridge.autostartTone
            }
            ActionButton {
                text: qsTr("Обновить")
                onClicked: bridge.refreshManual()
            }
        }
    }

    footer: ToolBar {
        background: Rectangle { color: Theme.panel }
        topPadding: 8
        bottomPadding: 8
        Label {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: 16
            text: bridge.busy ? bridge.busyText : bridge.lastEvent
            color: bridge.busy ? Theme.accent : Theme.muted
            elide: Label.ElideRight
            width: parent.width - 32
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        ColumnLayout {
            Layout.preferredWidth: 220
            Layout.fillHeight: true
            Layout.margins: 12
            spacing: 8

            ButtonGroup { id: navGroup }

            component NavButton: Button {
                checkable: true
                ButtonGroup.group: navGroup
                Layout.fillWidth: true
                background: Rectangle {
                    radius: 6
                    color: parent.checked ? Theme.accentDim : "transparent"
                    border.color: parent.checked ? Theme.accent : "transparent"
                }
                contentItem: Label {
                    text: parent.text
                    color: parent.checked ? Theme.text : Theme.muted
                    font.bold: parent.checked
                    leftPadding: 8
                }
            }

            NavButton {
                id: navMain
                text: qsTr("Главная")
                checked: true
            }
            NavButton {
                id: navProfiles
                objectName: "navProfiles"
                text: qsTr("Профили")
            }
            NavButton {
                id: navStrategies
                text: qsTr("Стратегии")
            }
            Item { Layout.fillHeight: true }
            Label {
                Layout.fillWidth: true
                text: qsTr("Для изменения настроек может потребоваться пароль — подтверждение в системном окне.")
                color: Theme.muted
                font.pixelSize: 11
                wrapMode: Label.WordWrap
            }
        }

        Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: Theme.line }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 16
            currentIndex: navMain.checked ? 0 : (navProfiles.checked ? 1 : 2)

            // ---------- Главная ----------
            ColumnLayout {
                spacing: 16

                GroupBox {
                    title: qsTr("Состояние")
                    Layout.fillWidth: true
                    label: Label { text: parent.title; color: Theme.muted }
                    background: Rectangle { color: Theme.panel; radius: 8; border.color: Theme.line }
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 10
                        GridLayout {
                            columns: 2
                            columnSpacing: 24
                            rowSpacing: 10
                            Layout.fillWidth: true
                            Label { text: qsTr("Сервис"); color: Theme.muted }
                            Label {
                                text: bridge.serviceText
                                color: Theme.toneColor(bridge.serviceTone)
                                font.bold: true
                            }
                            Label { text: qsTr("Интерфейс"); color: Theme.muted }
                            Label { text: bridge.interfaceName; color: Theme.text }
                            Label { text: qsTr("Стратегия"); color: Theme.muted }
                            Label { text: bridge.strategy; color: Theme.text }
                            Label { text: qsTr("Автозапуск"); color: Theme.muted }
                            Label {
                                text: bridge.autostartText
                                color: Theme.toneColor(bridge.autostartTone)
                                font.bold: true
                            }
                        }
                        Label {
                            visible: bridge.configError !== ""
                            text: bridge.configError
                            color: Theme.warn
                            wrapMode: Label.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }

                GroupBox {
                    title: qsTr("Действия")
                    Layout.fillWidth: true
                    label: Label { text: parent.title; color: Theme.muted }
                    background: Rectangle { color: Theme.panel; radius: 8; border.color: Theme.line }
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 12
                        RowLayout {
                            spacing: 12
                            ActionButton {
                                text: bridge.serviceRunning ? qsTr("Остановить") : qsTr("Запустить")
                                onClicked: bridge.serviceRunning ? bridge.stopService() : bridge.startService()
                            }
                            ActionButton {
                                text: qsTr("Перезапустить")
                                onClicked: bridge.restartService()
                            }
                        }
                        RowLayout {
                            spacing: 12
                            ActionButton {
                                visible: !bridge.autostartActive
                                text: qsTr("Включить автозапуск")
                                onClicked: bridge.enableAutostart()
                            }
                            ActionButton {
                                visible: bridge.autostartActive
                                text: qsTr("Выключить автозапуск")
                                onClicked: bridge.disableAutostart()
                            }
                        }
                        Label {
                            text: qsTr("Настройки применяются сразу; закрытие окна не останавливает сервис.")
                            color: Theme.muted
                            font.pixelSize: 11
                            wrapMode: Label.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }
                Item { Layout.fillHeight: true }
            }

            // ---------- Профили ----------
            ColumnLayout {
                spacing: 12

                Label {
                    visible: !bridge.canMutateFiles
                    text: bridge.revisionError !== ""
                            ? qsTr("Изменение профилей сейчас недоступно: ") + bridge.revisionError
                            : qsTr("Изменение профилей сейчас недоступно: состояние прочитано не полностью.")
                    color: Theme.warn
                    wrapMode: Label.WordWrap
                    Layout.fillWidth: true
                }

                RowLayout {
                    spacing: 12
                    ActionButton {
                        enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles
                        text: qsTr("Сохранить текущую настройку…")
                        onClicked: {
                            saveDialog.baseRevision = bridge.revision
                            saveDialog.open()
                        }
                    }
                    Label {
                        objectName: "profilesEmptyLabel"
                        Layout.fillWidth: true
                        visible: bridge.profilesModel.count === 0 && bridge.canMutateFiles
                        text: visible
                                ? qsTr("Именованных профилей нет. Сохрани текущую рабочую настройку под именем.")
                                : ""
                        color: Theme.muted
                        wrapMode: Label.WordWrap
                    }
                }

                ListView {
                    id: profilesList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 8
                    model: bridge.profilesModel
                    delegate: Rectangle {
                        width: profilesList.width
                        height: profileRow.implicitHeight + 20
                        radius: 8
                        color: Theme.panel
                        border.color: model.damaged ? Theme.warn : Theme.line
                        ColumnLayout {
                            id: profileRow
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 4
                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    text: model.name
                                    color: Theme.text
                                    font.bold: true
                                }
                                ToneChip {
                                    visible: model.damaged
                                    label: qsTr("повреждён")
                                    tone: "warn"
                                }
                                Item { Layout.fillWidth: true }
                            }
                            Label {
                                visible: !model.damaged
                                text: qsTr("Стратегия: ") + model.strategy + qsTr(" · интерфейс: ") + model.interface
                                color: Theme.muted
                            }
                            Label {
                                visible: model.damaged
                                text: model.error
                                color: Theme.warn
                                wrapMode: Label.WordWrap
                                Layout.fillWidth: true
                            }
                            RowLayout {
                                spacing: 8
                                ActionButton {
                                    text: qsTr("Восстановить")
                                    enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles && !model.damaged
                                    onClicked: bridge.restoreProfile(model.name, bridge.revision)
                                }
                                ActionButton {
                                    text: qsTr("Заменить")
                                    enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles
                                    onClicked: {
                                        replaceDialog.baseRevision = bridge.revision
                                        replaceDialog.targetName = model.name
                                        replaceDialog.open()
                                    }
                                }
                                ActionButton {
                                    text: qsTr("Удалить")
                                    enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles
                                    onClicked: {
                                        deleteDialog.baseRevision = bridge.revision
                                        deleteDialog.targetName = model.name
                                        deleteDialog.open()
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ---------- Стратегии ----------
            ColumnLayout {
                spacing: 12

                Label {
                    visible: !bridge.canMutateFiles
                    text: bridge.revisionError !== ""
                            ? qsTr("Применение стратегий недоступно: ") + bridge.revisionError
                            : qsTr("Применение стратегий недоступно: состояние прочитано не полностью.")
                    color: Theme.warn
                    wrapMode: Label.WordWrap
                    Layout.fillWidth: true
                }

                TextField {
                    id: strategySearch
                    Layout.fillWidth: true
                    placeholderText: qsTr("Поиск по имени стратегии")
                    selectByMouse: true
                    onTextChanged: bridge.setStrategyFilter(text)
                    color: Theme.text
                }

                ListView {
                    id: strategiesList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 8
                    model: bridge.strategiesModel
                    delegate: Rectangle {
                        width: strategiesList.width
                        height: 56
                        radius: 8
                        color: Theme.panel
                        border.color: model.current ? Theme.accent : Theme.line
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 12
                            Label {
                                Layout.fillWidth: true
                                text: model.name
                                color: Theme.text
                                elide: Label.ElideMiddle
                            }
                            ToneChip { visible: model.current; label: qsTr("текущая"); tone: "ok" }
                            ActionButton {
                                text: qsTr("Применить")
                                enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles && !model.current
                                onClicked: bridge.applyStrategy(model.name, bridge.revision)
                            }
                        }
                    }
                    Label {
                        anchors.centerIn: parent
                        visible: strategiesList.count === 0
                        text: qsTr("Стратегии не найдены")
                        color: Theme.muted
                    }
                }

                Label {
                    text: qsTr("Применение меняет только стратегию; интерфейс, GameFilter и firewall остаются прежними.")
                    color: Theme.muted
                    font.pixelSize: 11
                    wrapMode: Label.WordWrap
                    Layout.fillWidth: true
                }
            }
        }
    }

    // ---------- Диалоги ----------
    Dialog {
        id: saveDialog
        objectName: "saveDialog"
        property string baseRevision: ""
        modal: true
        title: qsTr("Сохранить текущую настройку")
        anchors.centerIn: parent
        onAboutToShow: nameField.text = ""
        footer: DialogButtonBox {
            Button {
                objectName: "saveAcceptButton"
                text: qsTr("Сохранить")
                enabled: nameField.length > 0 && nameField.acceptableInput
                         && !bridge.busy && !bridge.closing && bridge.canMutateFiles
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
            Button {
                objectName: "saveCancelButton"
                text: qsTr("Отмена")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
        }
        ColumnLayout {
            width: 420
            spacing: 8
            TextField {
                id: nameField
                objectName: "saveNameField"
                Layout.fillWidth: true
                selectByMouse: true
                focus: saveDialog.visible
                validator: RegularExpressionValidator { regularExpression: /[A-Za-z0-9][A-Za-z0-9_-]{0,47}/ }
            }
            Label {
                text: bridge.profileNameHint
                color: Theme.muted
                wrapMode: Label.WordWrap
                Layout.fillWidth: true
            }
        }
        onAccepted: bridge.saveProfile(nameField.text, baseRevision)
    }

    Dialog {
        id: replaceDialog
        objectName: "replaceDialog"
        property string baseRevision: ""
        property string targetName: ""
        modal: true
        title: qsTr("Заменить профиль?")
        width: 460
        anchors.centerIn: parent
        footer: DialogButtonBox {
            Button {
                objectName: "replaceAcceptButton"
                text: qsTr("Заменить")
                enabled: !bridge.busy && !bridge.closing
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
            Button {
                objectName: "replaceCancelButton"
                text: qsTr("Отмена")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
        }
        Label {
            width: parent.width
            text: qsTr("Заменить профиль «") + replaceDialog.targetName
                    + qsTr("» текущей настройкой? Прежнее содержимое будет потеряно.")
            color: Theme.text
            wrapMode: Label.WordWrap
        }
        onAccepted: bridge.replaceProfile(targetName, baseRevision)
    }

    Dialog {
        id: deleteDialog
        objectName: "deleteDialog"
        property string baseRevision: ""
        property string targetName: ""
        modal: true
        title: qsTr("Удалить профиль?")
        width: 460
        anchors.centerIn: parent
        footer: DialogButtonBox {
            Button {
                objectName: "deleteAcceptButton"
                text: qsTr("Удалить")
                enabled: !bridge.busy && !bridge.closing
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
            Button {
                objectName: "deleteCancelButton"
                text: qsTr("Отмена")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
        }
        Label {
            width: parent.width
            text: qsTr("Удалить профиль «") + deleteDialog.targetName
                    + qsTr("»? Восстановить его через меню будет нельзя. Сама настройка сервиса не изменится.")
            color: Theme.text
            wrapMode: Label.WordWrap
        }
        onAccepted: bridge.deleteProfile(targetName, baseRevision)
    }

    Dialog {
        id: messageDialog
        property string infoText: ""
        modal: true
        title: ""
        standardButtons: Dialog.Ok
        anchors.centerIn: parent
        Label {
            width: 460
            text: messageDialog.infoText
            color: Theme.text
            wrapMode: Label.WordWrap
        }
    }

    Connections {
        target: bridge
        function onMessageRaised(title, text) {
            messageDialog.title = title
            messageDialog.infoText = text
            messageDialog.open()
        }
    }

    // Ожидание операции и безопасного закрытия
    Rectangle {
        anchors.fill: parent
        visible: bridge.busy || bridge.closing
        color: "#cc14181d"
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 12
            BusyIndicator { Layout.alignment: Qt.AlignHCenter; running: true }
            Label {
                Layout.alignment: Qt.AlignHCenter
                text: bridge.closing
                        ? qsTr("Закрытие: ожидание завершения операции…")
                        : bridge.busyText
                color: Theme.text
            }
            Label {
                Layout.alignment: Qt.AlignHCenter
                text: qsTr("Ожидание изменения настроек; повторные действия заблокированы.")
                color: Theme.muted
            }
        }
    }
}
