import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

RowLayout {
    property bool connected: false
    property string text: ""
    spacing: 6
    Rectangle { width: 7; height: 7; radius: 3.5; color: parent.connected ? Theme.accent : Theme.warning }
    Label { text: parent.text; color: Theme.muted; font.pixelSize: 12 }
}