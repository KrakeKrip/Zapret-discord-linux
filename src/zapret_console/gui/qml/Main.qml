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
    title: qsTr("Zapret Manager")
    color: Theme.background

    // design/gui-v1/SPEC.md: узкое окно
    readonly property bool narrow: width < 960
    readonly property int pageIndex: navMain.checked ? 0 : navProfiles.checked ? 1 : navStrategies.checked ? 2 : navDiagnostics.checked ? 3 : 4
    readonly property var pageTitles: [qsTr("Главная"), qsTr("Профили"), qsTr("Стратегии"), qsTr("Диагностика"), qsTr("Журнал")]
    readonly property var pageSubtitles: [qsTr("Сервис и текущая настройка подключения"), qsTr("Сохранённые настройки для разных подключений"), qsTr("Выберите стратегию для вашего подключения"), qsTr("Проверка Discord и текущего сетевого пути"), qsTr("Последние сообщения сервиса")]

    onClosing: function (close) {
        if (!bridge.requestClose())
            close.accepted = false;
    }

    component ToneChip: Rectangle {
        property string label: ""
        property string tone: "ok"
        width: chipLabel.implicitWidth + 20
        height: 25
        radius: 6
        color: Theme.chip
        Label {
            id: chipLabel
            anchors.centerIn: parent
            text: parent.label
            color: Theme.toneColor(parent.tone)
            font.pixelSize: 11
            font.bold: true
        }
    }

    component Card: Rectangle {
        default property alias contentArea: content.data
        radius: 14
        color: Theme.card
        border.color: Theme.border
        implicitHeight: content.implicitHeight + 48
        ColumnLayout {
            id: content
            anchors.fill: parent
            anchors.margins: 24
            spacing: 10
        }
    }

    component CardTitle: Label {
        font.pixelSize: 17
        font.weight: Font.DemiBold
        color: Theme.text
    }

    component CardLabel: Label {
        font.pixelSize: 12
        color: Theme.muted
    }

    component AppTextField: TextField {
        selectByMouse: true
        color: Theme.text
        placeholderTextColor: Theme.muted
        implicitHeight: 44
        background: Rectangle {
            radius: 9
            color: Theme.input
            border.color: parent.activeFocus ? Theme.accent : Theme.border
        }
    }

    // ---------- Sidebar ----------
    Rectangle {
        id: sidebar
        objectName: "sidebar"
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: window.narrow ? 184 : 208
        color: Theme.sidebar

        Rectangle {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 1
            color: Theme.border
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: window.narrow ? 16 : 24
            spacing: 8

            RowLayout {
                spacing: 12
                Rectangle {
                    width: 36
                    height: 36
                    radius: 10
                    color: Theme.accent
                    Canvas {
                        anchors.fill: parent
                        antialiasing: true
                        onPaint: {
                            var ctx = getContext('2d');
                            ctx.reset();
                            ctx.strokeStyle = Theme.background;
                            ctx.lineWidth = 3;
                            ctx.lineCap = 'round';
                            ctx.lineJoin = 'round';
                            ctx.beginPath();
                            ctx.moveTo(10, 11);
                            ctx.lineTo(25, 11);
                            ctx.lineTo(10, 26);
                            ctx.lineTo(25, 26);
                            ctx.stroke();
                        }
                    }
                }
                ColumnLayout {
                    spacing: 0
                    Label {
                        text: qsTr("Zapret")
                        color: Theme.text
                        font.pixelSize: 19
                        font.bold: true
                    }
                    Label {
                        text: qsTr("Manager")
                        color: Theme.muted
                        font.pixelSize: 11
                    }
                }
            }

            Item {
                Layout.fillHeight: true
                Layout.maximumHeight: 24
            }
            Label {
                text: qsTr("УПРАВЛЕНИЕ")
                color: Theme.muted
                font.pixelSize: 10
                font.weight: Font.DemiBold
            }

            ButtonGroup {
                id: navGroup
            }

            NavButton {
                id: navMain
                objectName: "navMain"
                iconName: "home"
                text: qsTr("Главная")
                checked: true
            }
            NavButton {
                id: navProfiles
                objectName: "navProfiles"
                iconName: "folder"
                text: qsTr("Профили")
            }
            NavButton {
                id: navStrategies
                objectName: "navStrategies"
                iconName: "tune"
                text: qsTr("Стратегии")
            }

            NavButton {
                id: navDiagnostics
                objectName: "navDiagnostics"
                iconName: "diagnostic"
                text: qsTr("Диагностика")
            }
            NavButton {
                id: navJournal
                objectName: "navJournal"
                iconName: "journal"
                text: qsTr("Журнал")
            }

            Item {
                Layout.fillHeight: true
            }
            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Theme.border
            }
            Label {
                Layout.fillWidth: true
                text: qsTr("Изменения могут требовать системного подтверждения.")
                color: Theme.muted
                font.pixelSize: 10
                wrapMode: Text.Wrap
            }
        }
    }

    component NavButton: Button {
        id: navTemplate
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        property string iconName: ""
        checkable: true
        ButtonGroup.group: navGroup
        implicitHeight: 44
        Layout.fillWidth: true
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        background: Rectangle {
            radius: 10
            border.color: navTemplate.visualFocus ? Theme.accent : "transparent"
            border.width: navTemplate.visualFocus ? 2 : 0
            color: navTemplate.checked ? Theme.activeNav : (navTemplate.hovered ? Theme.card : "transparent")
            Rectangle {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 3
                height: 20
                radius: 1
                color: Theme.accent
                visible: navTemplate.checked
            }
        }
        contentItem: RowLayout {
            spacing: 10
            GuiIcon {
                name: navTemplate.iconName
                color: navTemplate.checked ? Theme.accent : Theme.muted
                Layout.leftMargin: 8
            }
            Label {
                text: navTemplate.text
                Layout.fillWidth: true
                elide: Text.ElideRight
                color: navTemplate.checked ? Theme.text : Theme.muted
                font.pixelSize: window.narrow ? 13 : 14
                font.weight: navTemplate.checked ? Font.DemiBold : Font.Normal
            }
        }
    }

    // ---------- Основная колонка ----------
    ColumnLayout {
        anchors.left: sidebar.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: window.narrow ? 20 : 32
        anchors.rightMargin: window.narrow ? 20 : 32
        spacing: 0

        RowLayout {
            Layout.topMargin: 24
            spacing: 16
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Label {
                    text: window.pageTitles[window.pageIndex]
                    color: Theme.text
                    font.pixelSize: 26
                    font.weight: Font.DemiBold
                }
                Label {
                    text: window.pageSubtitles[window.pageIndex]
                    color: Theme.muted
                    font.pixelSize: 12
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }
            }
            AppButton {
                text: qsTr("Обновить")
                visible: window.pageIndex < 3
                onClicked: bridge.refreshManual()
            }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: 12
            height: 1
            color: Theme.border
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.topMargin: 16
            currentIndex: window.pageIndex

            // ==================== Главная ====================
            ScrollView {
                id: mainScroll
                objectName: "mainScroll"
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                contentHeight: mainPage.implicitHeight + 24
                ColumnLayout {
                    id: mainPage
                    width: mainScroll.availableWidth
                    spacing: 24

                    Card {
                        Layout.fillWidth: true
                        RowLayout {
                            spacing: 28
                            Rectangle {
                                width: 58
                                height: 58
                                radius: 16
                                color: Theme.statusIconBg
                                GuiIcon {
                                    name: "power"
                                    anchors.centerIn: parent
                                    width: 28
                                    height: 28
                                    color: Theme.toneColor(bridge.serviceTone)
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: 4
                                Label {
                                    text: qsTr("СОСТОЯНИЕ СЕРВИСА")
                                    color: Theme.muted
                                    font.pixelSize: 10
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    text: bridge.loading ? qsTr("Читаем состояние…") : bridge.serviceText
                                    color: bridge.loading ? Theme.muted : Theme.text
                                    font.pixelSize: 27
                                    font.weight: Font.DemiBold
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                }
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            ToneChip {
                                visible: !bridge.loading
                                label: bridge.serviceChip
                                tone: bridge.serviceTone
                            }
                        }
                        Label {
                            text: qsTr("Проверка доступности Discord выполняется отдельно.")
                            color: Theme.muted
                            font.pixelSize: 12
                        }
                        Label {
                            visible: bridge.configError !== ""
                            text: bridge.configError
                            color: Theme.warning
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                        }
                        RowLayout {
                            spacing: 16
                            AppButton {
                                objectName: "serviceActionButton"
                                enabled: !bridge.busy && !bridge.closing
                                variant: "primary"
                                text: bridge.serviceRunning ? qsTr("Остановить") : qsTr("Запустить")
                                onClicked: bridge.serviceRunning ? bridge.stopService() : bridge.startService()
                            }
                            AppButton {
                                objectName: "restartButton"
                                enabled: !bridge.busy && !bridge.closing
                                text: qsTr("Перезапустить")
                                onClicked: bridge.restartService()
                            }
                        }
                    }

                    GridLayout {
                        id: settingsGrid
                        Layout.fillWidth: true
                        columns: window.narrow ? 1 : 2
                        columnSpacing: 20
                        rowSpacing: 24

                        Card {
                            id: connectionCard
                            objectName: "connectionCard"
                            Layout.preferredHeight: window.narrow ? implicitHeight : Math.max(connectionCard.implicitHeight, autostartCard.implicitHeight)
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            Layout.preferredWidth: window.narrow ? settingsGrid.width : (settingsGrid.width - 20) * 480 / 748
                            Layout.minimumWidth: 0
                            CardTitle {
                                text: qsTr("Текущая настройка")
                            }
                            Item {
                                height: 4
                            }
                            CardLabel {
                                text: qsTr("Сетевой интерфейс")
                            }
                            Label {
                                text: bridge.loading ? qsTr("…") : bridge.interfaceName
                                color: bridge.loading ? Theme.muted : Theme.text
                                font.pixelSize: 17
                                font.weight: Font.Medium
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                height: 1
                                color: Theme.border
                            }
                            CardLabel {
                                text: qsTr("Стратегия")
                            }
                            Label {
                                text: bridge.loading ? qsTr("…") : bridge.strategy
                                color: bridge.loading ? Theme.muted : Theme.text
                                font.pixelSize: 17
                                font.weight: Font.Medium
                                elide: Label.ElideMiddle
                                Layout.fillWidth: true
                            }
                            Item {
                                height: 4
                            }
                            AppButton {
                                text: qsTr("Выбрать стратегию")
                                objectName: "selectStrategyButton"
                                onClicked: navStrategies.checked = true
                            }
                        }

                        Card {
                            id: autostartCard
                            objectName: "autostartCard"
                            Layout.preferredHeight: window.narrow ? implicitHeight : Math.max(connectionCard.implicitHeight, autostartCard.implicitHeight)
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            Layout.preferredWidth: window.narrow ? settingsGrid.width : (settingsGrid.width - 20) * 268 / 748
                            Layout.minimumWidth: 0
                            CardTitle {
                                text: qsTr("Автозапуск")
                            }
                            Item {
                                height: 4
                            }
                            ToneChip {
                                label: bridge.autostartText
                                tone: bridge.autostartTone
                            }
                            Item {
                                height: 4
                            }
                            Label {
                                text: bridge.autostartActive ? qsTr("Сервис запускается при включении компьютера.") : bridge.autostartText === qsTr("Выключен") ? qsTr("Автоматический запуск выключен.") : qsTr("Состояние автозапуска: ") + bridge.autostartText
                                color: Theme.muted
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            Item {
                                Layout.fillHeight: true
                            }
                            AppButton {
                                objectName: "autostartButton"
                                enabled: !bridge.busy && !bridge.closing
                                text: bridge.autostartActive ? qsTr("Выключить автозапуск") : qsTr("Включить автозапуск")
                                onClicked: bridge.autostartActive ? bridge.disableAutostart() : bridge.enableAutostart()
                            }
                        }
                    }
                }
            }

            // ==================== Профили ====================
            ColumnLayout {
                id: profilesPage
                spacing: 12

                Rectangle {
                    visible: !bridge.canMutateFiles && !bridge.loading
                    Layout.fillWidth: true
                    radius: 10
                    color: Theme.card
                    border.color: Theme.warningBorder
                    implicitHeight: revisionLabel.implicitHeight + 24
                    Label {
                        id: revisionLabel
                        anchors.fill: parent
                        anchors.margins: 12
                        text: bridge.revisionError !== "" ? qsTr("Изменение профилей сейчас недоступно: ") + bridge.revisionError : qsTr("Изменение профилей сейчас недоступно: состояние прочитано не полностью.")
                        color: Theme.warning
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                    }
                }

                RowLayout {
                    spacing: 16
                    Label {
                        text: qsTr("Профилей: ") + bridge.profilesModel.count
                        color: Theme.muted
                        font.pixelSize: 12
                        visible: bridge.profilesModel.count > 0
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    AppButton {
                        objectName: "saveCurrentButton"
                        enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles
                        variant: "primary"
                        visible: bridge.profilesModel.count > 0
                        text: qsTr("Сохранить текущую настройку")
                        onClicked: {
                            saveDialog.baseRevision = bridge.revision;
                            saveDialog.open();
                        }
                    }
                }

                ColumnLayout {
                    objectName: "profilesEmptyLabel"
                    visible: bridge.profilesModel.count === 0 && bridge.canMutateFiles && !bridge.loading
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: 48
                    spacing: 12
                    GuiIcon {
                        name: "folder"
                        Layout.alignment: Qt.AlignHCenter
                        width: 40
                        height: 40
                        color: Theme.muted
                    }
                    Label {
                        Layout.alignment: Qt.AlignHCenter
                        text: qsTr("Пока нет профилей")
                        color: Theme.text
                        font.pixelSize: 17
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.alignment: Qt.AlignHCenter
                        text: qsTr("Сохраните текущую рабочую настройку, чтобы вернуться к ней позже.")
                        color: Theme.muted
                        font.pixelSize: 12
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }
                    AppButton {
                        objectName: "saveCurrentEmptyButton"
                        enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles
                        variant: "primary"
                        Layout.alignment: Qt.AlignHCenter
                        Layout.topMargin: 8
                        text: qsTr("Сохранить текущую настройку")
                        onClicked: {
                            saveDialog.baseRevision = bridge.revision;
                            saveDialog.open();
                        }
                    }
                }

                ListView {
                    id: profilesList
                    objectName: "profilesList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 12
                    model: bridge.profilesModel
                    delegate: Rectangle {
                        width: profilesList.width
                        height: profileCard.implicitHeight + 28
                        radius: 14
                        color: Theme.card
                        border.color: model.damaged ? Theme.warningBorder : Theme.border
                        ColumnLayout {
                            id: profileCard
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12
                                GuiIcon {
                                    name: "folder"
                                    color: model.damaged ? Theme.warning : Theme.muted
                                }
                                Label {
                                    text: model.name
                                    color: Theme.text
                                    font.pixelSize: 18
                                    font.weight: Font.DemiBold
                                    elide: Label.ElideRight
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    HoverHandler {
                                        id: nameHover
                                    }
                                    ToolTip.visible: nameHover.hovered
                                    ToolTip.text: model.name
                                }
                                ToneChip {
                                    visible: model.damaged
                                    label: qsTr("Повреждён")
                                    tone: "warn"
                                }
                                Item {
                                    Layout.fillWidth: true
                                }
                                AppButton {
                                    objectName: "restoreProfileButton"
                                    visible: !window.narrow
                                    text: qsTr("Восстановить")
                                    enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles && !model.damaged
                                    onClicked: bridge.restoreProfile(model.name, bridge.revision)
                                }
                            }
                            Label {
                                visible: !model.damaged
                                text: model.strategy + qsTr("  ·  ") + model.interface
                                Layout.fillWidth: true
                                elide: Text.ElideMiddle
                                HoverHandler {
                                    id: profileDetailsHover
                                }
                                ToolTip.visible: profileDetailsHover.hovered
                                ToolTip.text: text
                                color: Theme.muted
                                font.pixelSize: 12
                            }
                            Label {
                                visible: model.damaged
                                text: model.error
                                color: Theme.warning
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            Flow {
                                Layout.fillWidth: true
                                Layout.topMargin: 6
                                spacing: 12
                                AppButton {
                                    objectName: "restoreProfileCompactButton"
                                    visible: window.narrow
                                    text: qsTr("Восстановить")
                                    enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles && !model.damaged
                                    onClicked: bridge.restoreProfile(model.name, bridge.revision)
                                }
                                AppButton {
                                    objectName: "replaceProfileButton"
                                    enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles
                                    text: qsTr("Заменить")
                                    onClicked: {
                                        replaceDialog.baseRevision = bridge.revision;
                                        replaceDialog.targetName = model.name;
                                        replaceDialog.open();
                                    }
                                }
                                AppButton {
                                    variant: "danger"
                                    objectName: "deleteProfileButton"
                                    enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles
                                    text: qsTr("Удалить")
                                    onClicked: {
                                        deleteDialog.baseRevision = bridge.revision;
                                        deleteDialog.targetName = model.name;
                                        deleteDialog.open();
                                    }
                                }
                            }
                        }
                    }
                }

                Label {
                    text: qsTr("Восстановление применяет сохранённую настройку подключения.")
                    color: Theme.muted
                    font.pixelSize: 11
                }
            }

            // ==================== Стратегии ====================
            ColumnLayout {
                id: strategiesPage
                spacing: 12

                Rectangle {
                    visible: !bridge.canMutateFiles && !bridge.loading
                    Layout.fillWidth: true
                    radius: 10
                    color: Theme.card
                    border.color: Theme.warningBorder
                    implicitHeight: strategyRevisionLabel.implicitHeight + 24
                    Label {
                        id: strategyRevisionLabel
                        anchors.fill: parent
                        anchors.margins: 12
                        text: bridge.revisionError !== "" ? qsTr("Смена стратегии сейчас недоступна: ") + bridge.revisionError : qsTr("Смена стратегии сейчас недоступна: состояние прочитано не полностью.")
                        color: Theme.warning
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                    }
                }

                AppTextField {
                    id: strategySearch
                    objectName: "strategySearch"
                    Layout.fillWidth: true
                    placeholderText: qsTr("Поиск по имени стратегии")
                    leftPadding: 48
                    onTextChanged: bridge.setStrategyFilter(text)
                    GuiIcon {
                        name: "search"
                        anchors.left: parent.left
                        anchors.leftMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.muted
                    }
                }

                Rectangle {
                    objectName: "currentStrategyCard"
                    Layout.fillWidth: true
                    implicitHeight: currentStrategyColumn.implicitHeight + 32
                    radius: 12
                    color: Theme.activeStrategy
                    border.color: bridge.strategyInstalled ? Theme.activeStrategyBorder : Theme.warningBorder
                    ColumnLayout {
                        id: currentStrategyColumn
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 6
                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                text: qsTr("ТЕКУЩАЯ СТРАТЕГИЯ")
                                color: Theme.accent
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                            GuiIcon {
                                name: "check"
                                width: 20
                                height: 20
                                color: Theme.accent
                                visible: bridge.strategyInstalled
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            Label {
                                text: bridge.strategy
                                color: Theme.text
                                font.pixelSize: 18
                                font.weight: Font.DemiBold
                                elide: Label.ElideMiddle
                                Layout.fillWidth: true
                                HoverHandler {
                                    id: currentStrategyHover
                                }
                                ToolTip.visible: currentStrategyHover.hovered
                                ToolTip.text: bridge.strategy
                            }
                            ToneChip {
                                visible: !bridge.strategyInstalled
                                label: qsTr("Не установлена")
                                tone: "warn"
                            }
                        }
                    }
                }

                Label {
                    text: qsTr("Установленные стратегии")
                    color: Theme.muted
                    font.pixelSize: 13
                }

                Label {
                    visible: bridge.strategiesModel.count === 0 && !bridge.loading
                    text: strategySearch.text.length > 0 ? qsTr("Ничего не найдено. Попробуйте другое имя стратегии.") : qsTr("Установленные стратегии не найдены")
                    color: Theme.muted
                    font.pixelSize: 12
                }

                ListView {
                    id: strategiesList
                    objectName: "strategiesList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 10
                    model: bridge.strategiesModel
                    delegate: Rectangle {
                        width: strategiesList.width
                        height: 56
                        radius: 10
                        color: Theme.card
                        border.color: model.current ? Theme.accent : Theme.border
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 24
                            anchors.rightMargin: 24
                            spacing: 12
                            Label {
                                Layout.fillWidth: true
                                text: model.name
                                color: Theme.text
                                font.pixelSize: 14
                                font.weight: Font.Medium
                                elide: Label.ElideMiddle
                                HoverHandler {
                                    id: strategyNameHover
                                }
                                ToolTip.visible: strategyNameHover.hovered
                                ToolTip.text: model.name
                            }
                            ToneChip {
                                visible: model.current
                                label: qsTr("Текущая")
                                tone: "ok"
                            }
                            AppButton {
                                visible: !model.current
                                objectName: "applyStrategyButton"
                                text: qsTr("Применить")
                                enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles
                                onClicked: bridge.applyStrategy(model.name, bridge.revision)
                            }
                        }
                    }
                }

                Label {
                    text: qsTr("Остальные параметры подключения сохраняются.")
                    color: Theme.muted
                    font.pixelSize: 11
                }
            }
            // ==================== Диагностика ====================
            ColumnLayout {
                spacing: 14
                Label {
                    text: bridge.diagnosticStatus
                    color: Theme.toneColor(bridge.diagnosticTone)
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                }
                Label {
                    text: qsTr("Проверяется текущий сетевой путь. VPN может повлиять на результат; голос и трансляции проверяются отдельно.")
                    color: Theme.muted
                    font.pixelSize: 12
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                }
                CheckBox {
                    id: diagnosticElevate
                    objectName: "diagnosticElevate"
                    text: qsTr("Проверить firewall с правами администратора")
                    enabled: !bridge.busy && !bridge.closing
                    indicator: Rectangle {
                        implicitWidth: 20
                        implicitHeight: 20
                        y: (diagnosticElevate.height - height) / 2
                        radius: 5
                        color: Theme.input
                        border.color: diagnosticElevate.visualFocus || diagnosticElevate.checked ? Theme.accent : Theme.border
                        border.width: diagnosticElevate.visualFocus ? 2 : 1
                        GuiIcon {
                            anchors.centerIn: parent
                            width: 16
                            height: 16
                            name: "check"
                            color: Theme.accent
                            visible: diagnosticElevate.checked
                        }
                    }
                    contentItem: Label {
                        text: diagnosticElevate.text
                        color: diagnosticElevate.enabled ? Theme.text : Theme.muted
                        font.pixelSize: 12
                        leftPadding: diagnosticElevate.indicator.width + diagnosticElevate.spacing
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 12
                    AppButton {
                        objectName: "runDiagnosticsButton"
                        variant: "primary"
                        text: qsTr("Проверить Discord")
                        enabled: !bridge.busy && !bridge.closing
                        onClicked: bridge.runDiagnostics(diagnosticElevate.checked)
                    }
                    AppButton {
                        text: qsTr("Скопировать отчёт")
                        enabled: bridge.diagnosticReport.length > 0
                        onClicked: bridge.copyText(bridge.diagnosticReport)
                    }
                }
                Label {
                    visible: bridge.diagnosticReport.length > 0
                    text: qsTr("Результат последней завершённой проверки")
                    color: Theme.muted
                    font.pixelSize: 11
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    TextArea {
                        objectName: "diagnosticReportArea"
                        text: bridge.diagnosticReport
                        readOnly: true
                        selectByMouse: true
                        textFormat: TextEdit.PlainText
                        wrapMode: TextEdit.Wrap
                        color: Theme.text
                        font.pixelSize: 13
                        padding: 16
                        background: Rectangle {
                            color: Theme.input
                            radius: 10
                            border.color: Theme.border
                        }
                    }
                }
            }

            // ==================== Журнал ====================
            ColumnLayout {
                spacing: 14
                Label {
                    text: bridge.journalStatus
                    color: Theme.text
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                }
                Label {
                    text: qsTr("До 100 последних записей. Показаны сообщения, доступные вашему пользователю.")
                    color: Theme.muted
                    font.pixelSize: 12
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 12
                    AppButton {
                        objectName: "refreshJournalButton"
                        text: qsTr("Обновить журнал")
                        variant: "primary"
                        enabled: !bridge.busy && !bridge.closing
                        onClicked: bridge.refreshJournal()
                    }
                    AppButton {
                        objectName: "copyJournalButton"
                        text: qsTr("Скопировать журнал")
                        enabled: bridge.journalText.length > 0 || bridge.journalWarning.length > 0
                        onClicked: bridge.copyText(bridge.journalText + "\n" + bridge.journalWarning)
                    }
                }
                Label {
                    visible: bridge.journalWarning !== ""
                    text: bridge.journalWarning
                    color: Theme.warning
                    font.pixelSize: 12
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    maximumLineCount: 4
                    elide: Text.ElideRight
                    HoverHandler {
                        id: journalHintHover
                    }
                    ToolTip.visible: journalHintHover.hovered
                    ToolTip.text: bridge.journalWarning
                }
                Label {
                    visible: bridge.journalText.length > 0
                    text: qsTr("Последний полученный журнал")
                    color: Theme.muted
                    font.pixelSize: 11
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    TextArea {
                        objectName: "journalArea"
                        text: bridge.journalText
                        readOnly: true
                        selectByMouse: true
                        textFormat: TextEdit.PlainText
                        wrapMode: TextEdit.Wrap
                        color: Theme.text
                        font.family: "monospace"
                        font.pixelSize: 12
                        padding: 16
                        background: Rectangle {
                            color: Theme.input
                            radius: 10
                            border.color: Theme.border
                        }
                    }
                }
            }
        }

        // ---------- Footer ----------
        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: 12
            height: 1
            color: Theme.border
        }
        Item {
            Layout.fillWidth: true
            implicitHeight: 40
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                width: 6
                height: 6
                radius: 3
                color: bridge.loading ? Theme.muted : Theme.toneColor(bridge.eventTone)
            }
            Label {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.leftMargin: 18
                width: parent.width - 300
                text: bridge.closing ? qsTr("Завершаем текущую операцию…") : bridge.busy ? bridge.busyText : (bridge.loading ? qsTr("Читаем состояние…") : bridge.lastEvent)
                color: bridge.busy ? Theme.accent : Theme.muted
                font.pixelSize: 11
                elide: Label.ElideRight
                HoverHandler {
                    id: eventHover
                }
                ToolTip.visible: eventHover.hovered && text !== ""
                ToolTip.text: bridge.lastEvent
            }
            Label {
                anchors.verticalCenter: parent.verticalCenter
                anchors.right: parent.right
                text: bridge.loading ? qsTr("Состояние неизвестно") : bridge.serviceText
                color: Theme.muted
                font.pixelSize: 11
            }
        }
    }

    // ---------- Диалоги ----------
    component StyledDialog: Dialog {
        padding: 28
        modal: true
        width: Math.min(456, window.width - 48)
        anchors.centerIn: parent
        background: Rectangle {
            radius: 16
            color: Theme.dialogPanel
            border.color: Theme.dialogBorder
        }
        Overlay.modal: Rectangle {
            color: Theme.overlay
        }
    }

    StyledDialog {
        id: saveDialog
        objectName: "saveDialog"
        property string baseRevision: ""
        modal: true
        width: Math.min(456, window.width - 48)
        anchors.centerIn: parent
        background: Rectangle {
            radius: 16
            color: Theme.dialogPanel
            border.color: Theme.dialogBorder
        }
        onAboutToShow: nameField.text = ""
        onOpened: nameField.forceActiveFocus()
        footer: Item {
            implicitHeight: 68
            RowLayout {
                anchors.right: parent.right
                anchors.rightMargin: 28
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 28
                spacing: 12
                AppButton {
                    objectName: "saveCancelButton"
                    text: qsTr("Отмена")
                    focus: true
                    onClicked: saveDialog.reject()
                }
                AppButton {
                    objectName: "saveAcceptButton"
                    variant: "primary"
                    text: qsTr("Сохранить")
                    enabled: nameField.length > 0 && nameField.acceptableInput && !bridge.busy && !bridge.closing && bridge.canMutateFiles
                    onClicked: saveDialog.accept()
                }
            }
        }
        ColumnLayout {
            width: parent.width
            spacing: 8
            Label {
                text: qsTr("Сохранить настройку")
                color: Theme.text
                font.pixelSize: 21
                font.weight: Font.DemiBold
            }
            Label {
                text: qsTr("Профиль сохранит текущие параметры подключения.")
                color: Theme.muted
                font.pixelSize: 12
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            Item {
                height: 8
            }
            Label {
                text: qsTr("Имя профиля")
                color: Theme.text
                font.pixelSize: 12
                font.weight: Font.Medium
            }
            AppTextField {
                id: nameField
                onAccepted: {
                    if (nameField.acceptableInput && nameField.length > 0 && !bridge.busy && !bridge.closing && bridge.canMutateFiles)
                        saveDialog.accept();
                }
                objectName: "saveNameField"
                Layout.fillWidth: true
                focus: saveDialog.visible
                validator: RegularExpressionValidator {
                    regularExpression: /[A-Za-z0-9][A-Za-z0-9_-]{0,47}/
                }
            }
            Label {
                text: qsTr("1–48 символов: A–Z, a–z, 0–9, _ и -. Первый символ — буква или цифра.")
                color: Theme.muted
                font.pixelSize: 11
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
        }
        onAccepted: bridge.saveProfile(nameField.text, baseRevision)
    }

    StyledDialog {
        id: replaceDialog
        objectName: "replaceDialog"
        onOpened: replaceCancel.forceActiveFocus()
        property string baseRevision: ""
        property string targetName: ""
        modal: true
        width: Math.min(456, window.width - 48)
        anchors.centerIn: parent
        background: Rectangle {
            radius: 16
            color: Theme.dialogPanel
            border.color: Theme.dialogBorder
        }
        footer: Item {
            implicitHeight: 68
            RowLayout {
                anchors.right: parent.right
                anchors.rightMargin: 28
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 28
                spacing: 12
                AppButton {
                    id: replaceCancel
                    objectName: "replaceCancelButton"
                    text: qsTr("Отмена")
                    focus: true
                    onClicked: replaceDialog.reject()
                }
                AppButton {
                    objectName: "replaceAcceptButton"
                    text: qsTr("Заменить профиль")
                    enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles
                    onClicked: replaceDialog.accept()
                }
            }
        }
        ColumnLayout {
            width: parent.width
            spacing: 8
            Label {
                text: qsTr("Заменить профиль?")
                color: Theme.text
                font.pixelSize: 21
                font.weight: Font.DemiBold
            }
            Label {
                text: qsTr("Профиль «") + replaceDialog.targetName + qsTr("» будет заменён текущими настройками подключения. Прежнее содержимое будет потеряно.")
                color: Theme.text
                font.pixelSize: 13
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
        }
        onAccepted: bridge.replaceProfile(targetName, baseRevision)
    }

    StyledDialog {
        id: deleteDialog
        objectName: "deleteDialog"
        onOpened: deleteCancel.forceActiveFocus()
        property string baseRevision: ""
        property string targetName: ""
        modal: true
        width: Math.min(456, window.width - 48)
        anchors.centerIn: parent
        background: Rectangle {
            radius: 16
            color: Theme.dialogPanel
            border.color: Theme.dialogBorder
        }
        footer: Item {
            implicitHeight: 68
            RowLayout {
                anchors.right: parent.right
                anchors.rightMargin: 28
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 28
                spacing: 12
                AppButton {
                    id: deleteCancel
                    objectName: "deleteCancelButton"
                    text: qsTr("Отмена")
                    focus: true
                    onClicked: deleteDialog.reject()
                }
                AppButton {
                    objectName: "deleteAcceptButton"
                    variant: "destructive"
                    text: qsTr("Удалить профиль")
                    enabled: !bridge.busy && !bridge.closing && bridge.canMutateFiles
                    onClicked: deleteDialog.accept()
                }
            }
        }
        ColumnLayout {
            width: parent.width
            spacing: 8
            Label {
                text: qsTr("Удалить профиль?")
                color: Theme.text
                font.pixelSize: 21
                font.weight: Font.DemiBold
            }
            Label {
                text: qsTr("Профиль «") + deleteDialog.targetName + qsTr("» будет удалён. Восстановить его через меню будет нельзя. Сама настройка сервиса не изменится.")
                color: Theme.text
                font.pixelSize: 13
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
        }
        onAccepted: bridge.deleteProfile(targetName, baseRevision)
    }

    StyledDialog {
        id: messageDialog
        objectName: "messageDialog"
        property string infoText: ""
        header: Label {
            text: messageDialog.title
            color: Theme.text
            font.pixelSize: 21
            font.weight: Font.DemiBold
            leftPadding: 28
            rightPadding: 28
            topPadding: 28
            wrapMode: Text.WordWrap
        }
        modal: true
        width: Math.min(456, window.width - 48)
        anchors.centerIn: parent
        background: Rectangle {
            radius: 16
            color: Theme.dialogPanel
            border.color: Theme.dialogBorder
        }
        footer: Item {
            implicitHeight: 68
            RowLayout {
                anchors.right: parent.right
                anchors.rightMargin: 28
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 28
                spacing: 12
                AppButton {
                    objectName: "messageOkButton"
                    text: qsTr("Понятно")
                    focus: true
                    onClicked: messageDialog.accept()
                }
            }
        }
        Label {
            width: parent.width
            text: messageDialog.infoText
            color: Theme.text
            font.pixelSize: 13
            wrapMode: Text.Wrap
        }
    }

    Connections {
        target: bridge
        function onMessageRaised(title, text) {
            messageDialog.title = title;
            messageDialog.infoText = text;
            messageDialog.open();
        }
    }
}
