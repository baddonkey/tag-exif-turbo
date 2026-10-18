import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ColumnLayout {
    id: panel
    spacing: 10
    Label { text: "AI review"; font.pixelSize: 24; font.weight: Font.DemiBold }
    Label { text: appController.modelName; color: Theme.muted; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
    Label { text: appController.modelStatus; color: appController.modelReady ? Theme.accent : Theme.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
    TabBar {
        id: tabs
        objectName: "metadataTabs"
        Layout.fillWidth: true
        TabButton { text: "Tags" }
        TabButton { text: "Description" }
        TabButton { text: "Metadata" }
        readonly property Item activeUnderline: Rectangle {
            objectName: "activeMetadataTabUnderline"
            parent: tabs
            anchors.bottom: parent.bottom
            x: tabs.leftPadding + (tabs.currentItem ? tabs.currentItem.x : 0)
            width: tabs.currentItem ? tabs.currentItem.width : 0
            height: 3
            color: Theme.accent
            z: 2
        }
    }
    StackLayout {
        currentIndex: tabs.currentIndex
        Layout.fillWidth: true
        Layout.fillHeight: true
        ScrollView {
            id: tagScroll
            objectName: "tagReviewScroll"
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: tagScroll.availableWidth
                spacing: 12
                Label { objectName: "currentCustomTagsHeading"; text: "Current custom tags"; font.pixelSize: 17; font.weight: Font.DemiBold }
                Flow {
                    Layout.fillWidth: true
                    spacing: 7
                    Repeater {
                        id: customTags
                        objectName: "savedCustomTagRepeater"
                        model: appController.savedTagRows
                        delegate: TagChip {
                            required property var modelData
                            label: modelData.label
                            included: modelData.included
                            saved: true
                            removable: appController.tagReplaceAvailable
                            enabled: appController.canSkip
                            maxWidth: tagScroll.availableWidth
                        }
                    }
                }
                Label { visible: customTags.count === 0; text: "No custom tags"; color: Theme.muted }
                RowLayout {
                    objectName: "tagModeSelector"
                    Layout.fillWidth: true
                    ButtonGroup { id: tagModeGroup }
                    RadioButton {
                        objectName: "mergeTagMode"
                        Layout.fillWidth: true
                        ButtonGroup.group: tagModeGroup
                        text: "Merge"
                        checked: appController.tagMode === "merge"
                        enabled: appController.canSkip
                        onClicked: appController.setTagMode("merge")
                        ToolTip.visible: hovered
                        ToolTip.text: "Add reviewed tags and retain saved custom tags"
                    }
                    RadioButton {
                        objectName: "replaceTagMode"
                        Layout.fillWidth: true
                        ButtonGroup.group: tagModeGroup
                        text: "Replace"
                        checked: appController.tagMode === "replace"
                        enabled: appController.canSkip && appController.tagReplaceAvailable
                        onClicked: appController.setTagMode("replace")
                        ToolTip.visible: hovered
                        ToolTip.text: "Save exactly the reviewed custom tag list"
                    }
                    RadioButton {
                        objectName: "replaceAllTagMode"
                        Layout.fillWidth: true
                        ButtonGroup.group: tagModeGroup
                        text: "Replace All"
                        checked: appController.tagMode === "replace_all"
                        enabled: appController.canSkip && appController.tagReplaceAvailable
                        onClicked: appController.setTagMode("replace_all")
                        ToolTip.visible: hovered
                        ToolTip.text: "Save exactly the reviewed custom tag list; embedded exclusions stay unchanged"
                    }
                }
                TagEditor { objectName: "tagSuggestionEditor"; Layout.fillWidth: true }
                Label { visible: !appController.tagWriteAvailable && appController.mcpConnected; text: "Tag writing unavailable"; color: Theme.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }
                Label { text: "Embedded tags"; font.pixelSize: 17; font.weight: Font.DemiBold }
                Switch {
                    objectName: "ignoreAllEmbeddedTags"
                    text: "Ignore all embedded tags"
                    checked: appController.ignoreAllEmbeddedTags
                    enabled: appController.canSkip && appController.allTagsExclusionAvailable
                    onToggled: appController.setIgnoreAllEmbeddedTags(checked)
                    ToolTip.visible: hovered
                    ToolTip.text: "Exclude embedded tags from derivative copies"
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 7
                    Repeater {
                        id: embeddedRepeater
                        objectName: "embeddedTagRepeater"
                        model: appController.embeddedTagRows
                        delegate: TagChip {
                            required property var modelData
                            label: modelData.label
                            included: modelData.included
                            embedded: true
                            removable: appController.tagExclusionAvailable
                            maxWidth: tagScroll.availableWidth
                            enabled: appController.canSkip && !appController.ignoreAllEmbeddedTags
                            Accessible.name: label + (included ? ", included" : ", ignored")
                        }
                    }
                }
                Label { visible: embeddedRepeater.count === 0; text: "No embedded tags"; color: Theme.muted }
            }
        }
        ScrollView {
            id: descriptionScroll
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            DescriptionEditor { width: descriptionScroll.availableWidth }
        }
        ScrollView {
            id: rawScroll
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            TextArea {
                width: rawScroll.availableWidth
                text: appController.currentMetadata || "No metadata loaded"
                readOnly: true
                selectByMouse: true
                textFormat: TextEdit.PlainText
                wrapMode: TextEdit.WrapAnywhere
                font.family: "Menlo"
                font.pixelSize: 11
                color: Theme.muted
                background: Item {}
                Accessible.name: "Image metadata"
            }
        }
    }
    Rectangle { visible: tabs.currentIndex !== 2; Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }
    Label { visible: tabs.currentIndex !== 2; text: tabs.currentIndex === 0 ? "Custom tags to save" : "Proposed derivative description"; font.weight: Font.DemiBold }
    ScrollView {
        id: previewScroll
        visible: tabs.currentIndex !== 2
        Layout.fillWidth: true
        Layout.preferredHeight: tabs.currentIndex === 0 ? 160 : 110
        Layout.maximumHeight: Layout.preferredHeight
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            width: previewScroll.availableWidth
            Flow {
                objectName: "customTagsSavePreview"
                Layout.fillWidth: true
                visible: tabs.currentIndex === 0
                spacing: 7
                Repeater {
                    id: proposedCustomTags
                    objectName: "customTagsSaveRepeater"
                    model: appController.currentImageUrl.length > 0 ? appController.proposedCustomTags : []
                    delegate: TagChip {
                        required property string modelData
                        label: modelData
                        maxWidth: previewScroll.availableWidth
                    }
                }
            }
            Label {
                objectName: "emptyCustomTagsPreview"
                visible: tabs.currentIndex === 0 && proposedCustomTags.count === 0
                text: appController.currentImageUrl.length > 0 ? "No custom tags will be saved" : "No image loaded"
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: Theme.muted
            }
            Label {
                objectName: "proposedDerivativeTagsHeading"
                visible: tabs.currentIndex === 0
                text: "Proposed derivative tags"
                font.weight: Font.DemiBold
            }
            TextArea {
                objectName: "proposedMetadataPreview"
                Layout.fillWidth: true
                visible: tabs.currentIndex !== 2
                text: tabs.currentIndex === 1 ? (appController.proposedDescription || "No description") : (appController.proposedTags.join(", ") || "No tags")
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.WrapAnywhere
                color: Theme.text
                background: Rectangle { color: Theme.surface }
                Accessible.name: tabs.currentIndex === 0 ? "Proposed derivative tags" : "Proposed derivative description"
            }
        }
    }
}