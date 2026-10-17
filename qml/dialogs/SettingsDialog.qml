import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    id: dialog
    title: "Settings"
    modal: true
    width: Math.min(560, parent.width - 40)
    standardButtons: Dialog.Save | Dialog.Cancel
    onOpened: { mcp.text = appController.mcpUrl; ollama.text = appController.ollamaUrl; model.text = appController.modelName; dark.checked = Theme.dark }
    onAccepted: { Theme.dark = dark.checked; appController.configure(mcp.text, ollama.text, model.text, dark.checked) }
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: "Exif Turbo MCP" }
        TextField { id: mcp; Layout.fillWidth: true; selectByMouse: true }
        Label { text: "Ollama API" }
        TextField { id: ollama; Layout.fillWidth: true; selectByMouse: true }
        Label { text: "Vision model" }
        TextField { id: model; Layout.fillWidth: true; selectByMouse: true }
        Switch { id: dark; text: "Dark theme" }
        Button { text: "Reset local review progress…"; enabled: !appController.busy; onClicked: confirmation.open() }
    }
    Dialog {
        id: confirmation
        title: "Reset local progress?"
        modal: true
        anchors.centerIn: parent
        standardButtons: Dialog.Yes | Dialog.No
        Label { text: "Discard local drafts and restart at the first image?\nExisting image tags will not be changed."; wrapMode: Text.Wrap }
        onAccepted: { appController.resetProgress(); dialog.close() }
    }
}