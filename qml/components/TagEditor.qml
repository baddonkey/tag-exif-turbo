import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ColumnLayout {
    id: editor
    spacing: 12
    Label { text: "Suggested tags"; font.pixelSize: 17; font.weight: Font.DemiBold }
    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        Button {
            objectName: "clearSuggestedTagsButton"
            text: "Clear all suggested tags"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 1
            Layout.preferredHeight: 52
            enabled: appController.canClearSuggestedTags
            onClicked: appController.clearSuggestedTags()
            contentItem: Label {
                text: parent.text
                font: parent.font
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: enabled ? Theme.text : Theme.muted
            }
        }
        Button {
            objectName: "generateSuggestedTagsButton"
            text: "Generate suggestions"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 1
            Layout.preferredHeight: 52
            enabled: appController.canAnalyze
            onClicked: appController.regenerateTags()
            contentItem: Label {
                text: parent.text
                font: parent.font
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: enabled ? Theme.text : Theme.muted
            }
        }
    }
    Flow {
        Layout.fillWidth: true
        spacing: 7
        Repeater {
            model: appController.suggestedTags
            delegate: TagChip { removable: true; maxWidth: editor.width; enabled: !appController.busy }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        TextField {
            id: tagInput
            Layout.fillWidth: true
            placeholderText: "Add a tag"
            maximumLength: 160
            enabled: !appController.busy && appController.currentImageUrl.length > 0
            onAccepted: { appController.addTag(text); clear() }
            Accessible.name: "Custom tag"
        }
        ToolButton {
            text: "+"
            enabled: tagInput.enabled && tagInput.text.trim().length > 0
            onClicked: { appController.addTag(tagInput.text); tagInput.clear() }
            ToolTip.visible: hovered
            ToolTip.text: "Add tag"
            Accessible.name: "Add tag"
        }
    }
}