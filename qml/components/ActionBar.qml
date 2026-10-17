import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ToolBar {
    implicitHeight: 66
    background: Rectangle { color: Theme.surface; border.color: Theme.border }
    RowLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10
        Button { text: "\u2190  Previous"; enabled: appController.canPrevious; onClicked: appController.previousImage() }
        Button { text: "Next  \u2192"; enabled: appController.canNext; onClicked: appController.nextImage() }
        Item { Layout.fillWidth: true }
        Button { text: "Regenerate"; enabled: appController.canAnalyze; onClicked: appController.regenerateTags() }
        Button { text: "Skip"; enabled: appController.canSkip; onClicked: appController.skipImage() }
        Button { text: "Apply Tags"; highlighted: true; enabled: appController.canApply; onClicked: appController.applyTags(); ToolTip.visible: hovered; ToolTip.text: "Append the approved tags to this image" }
        Button { text: "Quit"; enabled: !appController.busy; onClicked: appController.requestQuit() }
    }
}