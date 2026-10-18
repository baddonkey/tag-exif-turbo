import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ToolBar {
    signal applyRequested()
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
        Button { objectName: "applyChangesButton"; text: "Apply Changes"; highlighted: true; enabled: appController.canApply; onClicked: applyRequested(); ToolTip.visible: hovered; ToolTip.text: "Save approved tags, description and embedded metadata exclusions" }
        Button { text: "Quit"; enabled: !appController.busy; onClicked: appController.requestQuit() }
    }
}