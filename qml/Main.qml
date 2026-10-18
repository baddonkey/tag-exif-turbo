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
    property bool applyFromApproval: false
    function requestApply(fromApproval) {
        applyFromApproval = fromApproval
        if (appController.removedCustomTags.length > 0) removeTags.open()
        else confirmDescriptionClear()
    }
    function confirmDescriptionClear() {
        if (appController.descriptionWillClear) clearDescription.open()
        else performApply()
    }
    function performApply() {
        if (applyFromApproval) appController.resolveApproval("apply")
        else appController.applyChanges()
    }
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
    footer: ActionBar { onApplyRequested: window.requestApply(false) }
    SettingsDialog { id: settings; anchors.centerIn: parent }
    ApprovalDialog { id: approval; anchors.centerIn: parent; onApplyRequested: window.requestApply(true) }
    Dialog {
        id: removeTags
        objectName: "removeCustomTagsConfirmation"
        title: "Remove saved custom tags?"
        modal: true
        anchors.centerIn: parent
        width: Math.min(440, window.width - 40)
        standardButtons: Dialog.Yes | Dialog.Cancel
        ScrollView {
            anchors.fill: parent
            implicitHeight: Math.min(180, removedLabels.implicitHeight)
            contentWidth: availableWidth
            clip: true
            Label {
                id: removedLabels
                width: parent.availableWidth
                text: appController.removedCustomTags.join(", ")
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
            }
        }
        onAccepted: window.confirmDescriptionClear()
        onRejected: { if (window.applyFromApproval) appController.resolveApproval("cancel") }
    }
    Dialog {
        id: clearDescription
        objectName: "clearDescriptionConfirmation"
        title: "Clear saved custom description?"
        modal: true
        anchors.centerIn: parent
        standardButtons: Dialog.Yes | Dialog.Cancel
        onAccepted: window.performApply()
        onRejected: { if (window.applyFromApproval) appController.resolveApproval("cancel") }
    }
    ErrorDialog { id: errors; anchors.centerIn: parent }
    Shortcut { sequence: "Alt+Right"; enabled: !window.textEditing && appController.canNext; onActivated: appController.nextImage() }
    Shortcut { sequence: "Alt+Left"; enabled: !window.textEditing && appController.canPrevious; onActivated: appController.previousImage() }
    Shortcut { sequence: "Ctrl+Return"; enabled: appController.canApply; onActivated: window.requestApply(false) }
    Shortcut { sequence: "Ctrl+R"; enabled: appController.canAnalyze; onActivated: appController.regenerateTags() }
    Shortcut { sequences: [StandardKey.Quit]; onActivated: appController.requestQuit() }
    Shortcut { sequence: "Ctrl+,"; onActivated: settings.open() }
}