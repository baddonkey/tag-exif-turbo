import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    title: "Connection details"
    modal: true
    width: Math.min(660, parent.width - 40)
    height: Math.min(500, parent.height - 40)
    standardButtons: Dialog.Close
    contentItem: ScrollView {
        implicitWidth: 600
        implicitHeight: 300
        contentWidth: availableWidth
        TextArea { text: appController.errorMessage + "\n\nMCP: " + appController.mcpUrl + "\nOllama: " + appController.ollamaUrl + "\nModel: " + appController.modelName + "\n\nDiscovered tool schemas\n" + appController.discoveredTools; readOnly: true; selectByMouse: true; wrapMode: TextEdit.WrapAnywhere }
    }
}