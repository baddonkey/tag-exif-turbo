import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    title: "Resolve this image before leaving"
    modal: true
    closePolicy: Popup.NoAutoClose
    width: Math.min(500, parent.width - 40)
    ColumnLayout {
        anchors.fill: parent
        spacing: 16
        Label { text: appController.currentFilename; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
        RowLayout {
            Button { text: "Cancel"; onClicked: { appController.resolveApproval("cancel"); dialog.close() } }
            Button { text: "Skip without writing"; onClicked: { appController.resolveApproval("skip"); dialog.close() } }
            Button { text: "Apply Tags"; highlighted: true; enabled: appController.canApply; onClicked: { appController.resolveApproval("apply"); dialog.close() } }
        }
    }
}