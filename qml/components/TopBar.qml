import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ToolBar {
    signal settingsRequested()
    implicitHeight: 84
    background: Rectangle { color: Theme.surface; border.color: Theme.border }
    RowLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 18
        ColumnLayout {
            spacing: 3
            Label { text: "Exif Turbo AI Tagger"; font.pixelSize: 19; font.weight: Font.DemiBold }
            RowLayout {
                spacing: 12
                StatusIndicator { text: "MCP"; connected: appController.mcpConnected }
                StatusIndicator { text: "Ollama"; connected: appController.ollamaConnected }
            }
        }
        Item { Layout.fillWidth: true }
        ComboBox {
            id: imageSetSelector
            objectName: "imageSetSelector"
            Layout.preferredWidth: 200
            model: ["Current selected image"].concat(appController.imageSets)
            currentIndex: appController.selectedImageSet === "Current selected image" ? 0 : appController.imageSets.indexOf(appController.selectedImageSet) + 1
            enabled: !appController.busy && appController.mcpConnected
            onActivated: if (currentIndex === 0) appController.selectCurrentImage(); else appController.selectImageSet(currentText)
            Accessible.name: "Image source"
            delegate: ItemDelegate {
                id: setOption
                required property string modelData
                required property int index
                width: imageSetSelector.width
                highlighted: imageSetSelector.highlightedIndex === index
                contentItem: Text {
                    objectName: "imageSetOptionText-" + setOption.index
                    text: setOption.modelData
                    font: imageSetSelector.font
                    color: Theme.text
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    objectName: "imageSetOptionBackground-" + setOption.index
                    color: setOption.highlighted ? Theme.raised : Theme.surface
                }
            }
        }
        ToolButton {
            objectName: "reloadCurrentImageButton"
            text: "Reload image"
            visible: appController.selectedImageSet === "Current selected image"
            enabled: appController.canReloadCurrentImage
            onClicked: appController.reloadCurrentImage()
            ToolTip.visible: hovered
            ToolTip.text: "Load the image currently selected in Exif Turbo"
            Accessible.name: "Reload current image"
        }
        ColumnLayout {
            Layout.preferredWidth: 100
            Layout.minimumWidth: 100
            Layout.maximumWidth: 100
            Label { text: appController.totalImages > 0 ? (appController.currentOffset + 1) + " / " + appController.totalImages : "0 / 0"; Layout.alignment: Qt.AlignHCenter }
            ProgressBar {
                Layout.fillWidth: true
                from: 0
                to: Math.max(1, appController.totalImages)
                value: appController.workflowState === "COMPLETED" ? to : appController.currentOffset
                indeterminate: appController.busy
                implicitHeight: 5
            }
        }
        ToolButton { text: "\u21bb"; font.pixelSize: 22; enabled: !appController.busy; onClicked: appController.connectServices(); ToolTip.visible: hovered; ToolTip.text: "Reconnect services"; Accessible.name: "Reconnect services" }
        ToolButton { text: "\u2699"; font.pixelSize: 22; onClicked: settingsRequested(); ToolTip.visible: hovered; ToolTip.text: "Settings"; Accessible.name: "Settings" }
    }
}