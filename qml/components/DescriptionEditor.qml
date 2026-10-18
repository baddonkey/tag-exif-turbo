import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ColumnLayout {
    id: editor
    spacing: 12
    Label { text: "Custom description"; font.pixelSize: 17; font.weight: Font.DemiBold }
    TextArea {
        id: description
        objectName: "descriptionDraft"
        Layout.fillWidth: true
        Layout.minimumHeight: 130
        text: appController.currentDescription
        placeholderText: "No custom description"
        enabled: appController.canSkip && appController.descriptionWriteAvailable
        selectByMouse: true
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.WrapAnywhere
        color: Theme.text
        background: Rectangle { color: Theme.surface; border.color: description.activeFocus ? Theme.accent : Theme.border; radius: Theme.radius }
        onTextChanged: { if (activeFocus && text !== appController.currentDescription) appController.setDescription(text) }
        Accessible.name: "Custom description draft"
    }
    Label { visible: !appController.descriptionWriteAvailable && appController.mcpConnected; text: "Description editing unavailable"; color: Theme.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
    Label { text: "AI suggestion"; font.pixelSize: 17; font.weight: Font.DemiBold }
    Button {
        objectName: "generateDescriptionSuggestion"
        text: appController.descriptionSuggestion.length > 0 ? "Regenerate suggestion" : "Generate suggestion"
        enabled: appController.canAnalyze
        onClicked: appController.generateDescriptionSuggestion()
    }
    Label {
        Layout.fillWidth: true
        text: appController.descriptionSuggestion || "No suggestion"
        textFormat: Text.PlainText
        wrapMode: Text.WrapAnywhere
        color: Theme.muted
    }
    RowLayout {
        Layout.fillWidth: true
        Button {
            objectName: "useDescriptionSuggestion"
            text: "Use suggestion"
            enabled: appController.canSkip && appController.descriptionWriteAvailable && appController.descriptionSuggestion.length > 0
            onClicked: { if (appController.currentDescription.length > 0 && appController.currentDescription !== appController.descriptionSuggestion) replaceSuggestion.open(); else appController.useDescriptionSuggestion(false) }
        }
        Button {
            text: "Append"
            enabled: appController.canSkip && appController.descriptionWriteAvailable && appController.descriptionSuggestion.length > 0
            onClicked: appController.useDescriptionSuggestion(true)
        }
    }
    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }
    Label { text: "Embedded description"; font.pixelSize: 17; font.weight: Font.DemiBold }
    Switch {
        objectName: "ignoreEmbeddedDescription"
        text: "Ignore embedded description"
        checked: appController.ignoreEmbeddedDescription
        enabled: appController.canSkip && appController.descriptionExclusionAvailable
        onToggled: appController.setIgnoreEmbeddedDescription(checked)
        ToolTip.visible: hovered
        ToolTip.text: "Exclude embedded descriptions from derivative copies"
    }
    TextArea {
        Layout.fillWidth: true
        text: appController.embeddedDescription || "No embedded description"
        readOnly: true
        selectByMouse: true
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.WrapAnywhere
        font.strikeout: appController.ignoreEmbeddedDescription
        color: Theme.muted
        background: Item {}
        Accessible.name: "Embedded description"
    }
    Dialog {
        id: replaceSuggestion
        title: "Replace description draft?"
        modal: true
        width: Math.min(400, editor.width)
        standardButtons: Dialog.Yes | Dialog.Cancel
        onAccepted: appController.useDescriptionSuggestion(false)
    }
}