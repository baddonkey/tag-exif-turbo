import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "."
import "components"
import "dialogs"

ApplicationWindow {
    id: window
    width: 1280
    height: 820
    minimumWidth: 920
    minimumHeight: 640
    visible: true
    title: "Exif Turbo AI Tagger"
    color: Theme.background
    font.family: Theme.font
    font.pixelSize: 14
    palette.window: Theme.background
    palette.base: Theme.surface
    palette.button: Theme.raised
    palette.buttonText: Theme.text
    palette.text: Theme.text
    palette.windowText: Theme.text
    palette.highlight: Theme.accent
    palette.highlightedText: Theme.background

    property bool allowedToClose: false
    property real restoredSplitRatio: 0.65
    readonly property bool textEditing: activeFocusItem !== null && (activeFocusItem instanceof TextInput || activeFocusItem instanceof TextEdit)
    Component.onCompleted: {
        width = appController.windowWidth
        height = appController.windowHeight
        restoredSplitRatio = appController.splitRatio
        Theme.dark = appController.darkTheme
    }
    onClosing: function(close) {
        appController.saveUi(Theme.dark, width, height, viewer.width / Math.max(split.width, 1))
        if (!allowedToClose) { close.accepted = false; appController.requestQuit() }
    }
    Connections {
        target: appController
        function onApprovalRequested() { approval.open() }
        function onQuitApproved() { window.allowedToClose = true }
    }
    header: TopBar { onSettingsRequested: settings.open() }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: errorRow.implicitHeight + 20
            visible: appController.errorMessage.length > 0
            color: Theme.surface
            border.color: Theme.danger
            radius: Theme.radius
            RowLayout {
                id: errorRow
                anchors.fill: parent
                anchors.margins: 10
                Label { text: appController.errorMessage; color: Theme.danger; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Button { text: "Retry"; enabled: !appController.busy; onClicked: appController.retryLastOperation() }
                ToolButton { text: "?"; onClicked: errors.open(); ToolTip.visible: hovered; ToolTip.text: "Connection details" }
            }
        }
        SplitView {
            id: split
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: Rectangle {
                implicitWidth: 12
                color: "transparent"
                Rectangle { width: 2; height: 32; color: Theme.border; anchors.centerIn: parent; radius: 1 }
            }
            ImageViewer { id: viewer; SplitView.preferredWidth: split.width * window.restoredSplitRatio; SplitView.minimumWidth: 360 }
            MetadataPanel { SplitView.fillWidth: true; SplitView.minimumWidth: 320 }
        }
        RowLayout {
            Layout.fillWidth: true
            StatusIndicator { connected: appController.mcpConnected; text: appController.workflowState.replace(/_/g, " ") }
            Label { text: appController.statusMessage; color: Theme.muted; elide: Text.ElideRight; Layout.fillWidth: true }
        }
    }
    footer: ActionBar {}
    SettingsDialog { id: settings; anchors.centerIn: parent }
    ApprovalDialog { id: approval; anchors.centerIn: parent }
    ErrorDialog { id: errors; anchors.centerIn: parent }
    Shortcut { sequence: "Alt+Right"; enabled: !window.textEditing && appController.canNext; onActivated: appController.nextImage() }
    Shortcut { sequence: "Alt+Left"; enabled: !window.textEditing && appController.canPrevious; onActivated: appController.previousImage() }
    Shortcut { sequence: "Ctrl+Return"; enabled: appController.canApply; onActivated: appController.applyTags() }
    Shortcut { sequence: "Ctrl+R"; enabled: appController.canAnalyze; onActivated: appController.regenerateTags() }
    Shortcut { sequences: [StandardKey.Quit]; onActivated: appController.requestQuit() }
    Shortcut { sequence: "Ctrl+,"; onActivated: settings.open() }
}