pragma Singleton
import QtQuick

QtObject {
    property bool dark: true
    readonly property color background: dark ? "#171a1c" : "#eef1f0"
    readonly property color surface: dark ? "#202528" : "#ffffff"
    readonly property color raised: dark ? "#2b3134" : "#e5ebe8"
    readonly property color border: dark ? "#394145" : "#ced7d2"
    readonly property color text: dark ? "#ecf1ed" : "#192720"
    readonly property color muted: dark ? "#a1ada7" : "#5d6d63"
    readonly property color accent: dark ? "#91d6b0" : "#1d7047"
    readonly property color warning: dark ? "#e7c578" : "#8a5f11"
    readonly property color danger: dark ? "#f39b99" : "#b43636"
    readonly property string font: "Avenir Next"
    readonly property int gap: 12
    readonly property int radius: 6
}