import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ScrollView {
    id: panel
    clip: true
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ColumnLayout {
        width: panel.availableWidth
        spacing: 18
        Label { text: "AI review"; font.pixelSize: 24; font.weight: Font.DemiBold }
        Label { text: appController.modelName; color: Theme.muted; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
        Label { text: appController.modelStatus; color: appController.modelReady ? Theme.accent : Theme.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        TagEditor { Layout.fillWidth: true }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        Label { text: "Existing tags"; font.pixelSize: 17; font.weight: Font.DemiBold }
        Flow {
            Layout.fillWidth: true
            spacing: 7
            Repeater { id: existingRepeater; model: appController.existingTags; delegate: TagChip { maxWidth: panel.availableWidth } }
        }
        Label { visible: existingRepeater.count === 0; text: "No existing tags"; color: Theme.muted }
        Label { visible: !appController.tagWriteAvailable && appController.mcpConnected; text: "Tag writing is unavailable on this MCP server"; color: Theme.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        Label { text: "Image metadata"; font.pixelSize: 17; font.weight: Font.DemiBold }
        TextArea {
            Layout.fillWidth: true
            text: appController.currentMetadata || "No metadata loaded"
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.WrapAnywhere
            font.family: "Menlo"
            font.pixelSize: 11
            color: Theme.muted
            background: Item {}
            Accessible.name: "Image metadata"
        }
    }
}