pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import qs.Commons

RowLayout {
    id: root
    property var labels: []
    property int currentIndex: 0
    signal chosen(int index)
    spacing: Style.space(3)
    Repeater {
        model: root.labels
        delegate: Controls.Button {
            id: tab
            required property int index
            required property string modelData
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            implicitHeight: Style.space(28)
            padding: Style.space(2)
            text: modelData
            Accessible.name: modelData
            Accessible.role: Accessible.PageTab
            Accessible.selected: index === root.currentIndex
            onClicked: root.chosen(index)
            Keys.onLeftPressed: root.chosen(Math.max(0,index-1))
            Keys.onRightPressed: root.chosen(Math.min(root.labels.length-1,index+1))
            background: Item {
                Rectangle {
                    anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                    height: Style.space(2)
                    color: Color.accent
                    visible: tab.index === root.currentIndex
                }
            }
            contentItem: Text {
                text: tab.text; textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                font.family: Style.font.family; font.pixelSize: Style.font.caption
                font.bold: tab.index === root.currentIndex
                color: tab.index === root.currentIndex || tab.hovered || tab.activeFocus ? Color.accent : Color.popups.text
                opacity: tab.index === root.currentIndex || tab.hovered || tab.activeFocus ? 1 : 0.65
                elide: Text.ElideRight
            }
        }
    }
}
