import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: chip
    required property string label
    property bool removable: false
    property bool saved: false
    property bool embedded: false
    property bool included: true
    signal removeRequested()
    onRemoveRequested: {
        if (embedded) appController.setEmbeddedTagIncluded(label, !included)
        else if (saved) appController.setSavedTagIncluded(label, !included)
        else appController.removeTag(label)
    }
    property real maxWidth: 300
    implicitWidth: Math.min(maxWidth, row.implicitWidth + 18)
    implicitHeight: row.implicitHeight + 8
    radius: Theme.radius
    color: removable ? Theme.raised : "transparent"
    border.color: Theme.border
    MouseArea {
        anchors.fill: parent
        enabled: chip.embedded && chip.removable
        cursorShape: Qt.PointingHandCursor
        onClicked: chip.removeRequested()
    }
    RowLayout {
        id: row
        anchors.fill: parent
        anchors.leftMargin: 9
        anchors.rightMargin: 9
        spacing: 4
        Label { objectName: "tagChipLabel"; text: chip.label; color: chip.included ? Theme.text : Theme.danger; font.strikeout: !chip.included; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
        ToolButton {
            objectName: "tagChipToggle"
            visible: chip.removable
            text: chip.embedded || chip.included ? "\u00d7" : "\u21b6"
            implicitWidth: 24
            implicitHeight: 24
            onClicked: chip.removeRequested()
            ToolTip.visible: hovered
            ToolTip.text: (chip.embedded ? (chip.included ? "Ignore " : "Include ") : (chip.included ? "Remove " : "Restore ")) + chip.label
            Accessible.name: ToolTip.text
        }
    }
}