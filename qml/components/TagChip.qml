import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: chip
    required property string label
    property bool removable: false
    property real maxWidth: 300
    implicitWidth: Math.min(maxWidth, row.implicitWidth + 18)
    implicitHeight: row.implicitHeight + 8
    radius: Theme.radius
    color: removable ? Theme.raised : "transparent"
    border.color: Theme.border
    RowLayout {
        id: row
        anchors.fill: parent
        anchors.leftMargin: 9
        anchors.rightMargin: 9
        spacing: 4
        Label { text: chip.label; color: Theme.text; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
        ToolButton { visible: chip.removable; text: "\u00d7"; implicitWidth: 24; implicitHeight: 24; onClicked: appController.removeTag(chip.label); ToolTip.visible: hovered; ToolTip.text: "Remove " + chip.label; Accessible.name: "Remove " + chip.label }
    }
}