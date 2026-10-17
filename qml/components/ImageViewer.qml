import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root
    color: Theme.surface
    radius: Theme.radius
    border.color: Theme.border
    property real zoom: 1
    readonly property real fitWidth: Math.max(1, viewport.width - 32)
    readonly property real fitHeight: Math.max(1, viewport.height - 32)
    function zoomAt(factor, pointX, pointY) {
        let relativeX = (viewport.contentX + pointX) / Math.max(1, viewport.contentWidth)
        let relativeY = (viewport.contentY + pointY) / Math.max(1, viewport.contentHeight)
        zoom = Math.max(1, Math.min(12, zoom * factor))
        viewport.contentX = Math.max(0, Math.min(viewport.contentWidth - viewport.width, relativeX * viewport.contentWidth - pointX))
        viewport.contentY = Math.max(0, Math.min(viewport.contentHeight - viewport.height, relativeY * viewport.contentHeight - pointY))
        viewport.returnToBounds()
    }
    function fit() { zoom = 1; viewport.contentX = 0; viewport.contentY = 0 }
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 16
            Label { text: appController.currentFilename || "Image preview"; font.weight: Font.DemiBold; elide: Text.ElideMiddle; Layout.fillWidth: true }
            Label { text: appController.currentDimensions; color: Theme.muted; font.pixelSize: 12 }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            Flickable {
                id: viewport
                anchors.fill: parent
                contentWidth: Math.max(width, root.fitWidth * root.zoom)
                contentHeight: Math.max(height, root.fitHeight * root.zoom)
                boundsBehavior: Flickable.StopAtBounds
                interactive: root.zoom > 1
                Image {
                    id: preview
                    objectName: "imagePreview"
                    anchors.centerIn: parent
                    width: root.fitWidth * root.zoom
                    height: root.fitHeight * root.zoom
                    source: appController.currentImageUrl
                    fillMode: Image.PreserveAspectFit
                    cache: false
                    asynchronous: true
                    smooth: true
                    opacity: status === Image.Ready ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 120 } }
                    onSourceChanged: root.fit()
                }
                ScrollBar.horizontal: ScrollBar { policy: root.zoom > 1 ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
                ScrollBar.vertical: ScrollBar { policy: root.zoom > 1 ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
                WheelHandler { onWheel: function(event) { root.zoomAt(Math.pow(1.0015, event.angleDelta.y || event.pixelDelta.y), event.x, event.y); event.accepted = true } }
                PinchHandler { target: null; onScaleChanged: function(delta) { if (active) root.zoomAt(delta, centroid.position.x, centroid.position.y) } }
            }
            ColumnLayout {
                anchors.centerIn: parent
                visible: !appController.currentImageUrl || preview.status === Image.Error || preview.status === Image.Loading
                spacing: 12
                BusyIndicator { running: appController.busy || preview.status === Image.Loading; visible: running; Layout.alignment: Qt.AlignHCenter }
                Label { text: preview.status === Image.Error ? "Preview could not be displayed" : appController.busy ? "Loading image" : "No image loaded"; color: Theme.muted; Layout.alignment: Qt.AlignHCenter }
                Button { text: "Connect services"; visible: !appController.mcpConnected; enabled: !appController.busy; onClicked: appController.connectServices() }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 10
            Label { text: appController.currentImageUrl ? "Preview " + appController.previewDimensions : ""; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
            ToolButton { text: "\u2212"; enabled: root.zoom > 1; onClicked: root.zoomAt(1 / 1.25, viewport.width / 2, viewport.height / 2); ToolTip.visible: hovered; ToolTip.text: "Zoom out"; Accessible.name: "Zoom out" }
            Label { text: Math.round(root.zoom * 100) + "%"; horizontalAlignment: Text.AlignHCenter; Layout.preferredWidth: 48 }
            ToolButton { text: "+"; enabled: root.zoom < 12; onClicked: root.zoomAt(1.25, viewport.width / 2, viewport.height / 2); ToolTip.visible: hovered; ToolTip.text: "Zoom in"; Accessible.name: "Zoom in" }
            ToolButton { text: "\u2922"; onClicked: root.fit(); ToolTip.visible: hovered; ToolTip.text: "Fit to window"; Accessible.name: "Fit to window" }
        }
    }
}