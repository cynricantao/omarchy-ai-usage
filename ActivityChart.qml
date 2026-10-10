pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import qs.Commons
import qs.Ui
import "Logic.js" as Logic

ColumnLayout {
    id: root
    property var range: ({buckets:[],models:[]})
    property int mode: 0
    property string rangeKey: "today"
    readonly property real plotPadding: Style.space(rangeKey === "all" ? 36 : 8)
    property bool active: true
    onActiveChanged: if (active) graph.requestPaint()
    property color foreground: Color.popups.text
    readonly property color muted: Qt.rgba(foreground.r,foreground.g,foreground.b,0.65)
    readonly property var colors: [Color.accent, foreground, Qt.tint(Color.accent, Qt.rgba(foreground.r,foreground.g,foreground.b,0.5)), muted]
    property var enabledSeries: [true,true,true,true]
    readonly property var keys: ["input","output","cache_read","cache_write"]
    property var dailyBuckets: []
    readonly property var buckets: mode === 1 ? dailyBuckets : (range.buckets || [])
    readonly property var models: Logic.ranked(range.models || [])
    readonly property var plotted: mode === 2 ? models : buckets
    readonly property bool hasObservations: plotted.some(function(b) { return Logic.known(b.total) || root.keys.some(function(k) { return Logic.known(b[k]) }) })
    readonly property var barValues: Logic.barValues(buckets, keys.filter(function(k,i) { return enabledSeries[i] }))
    readonly property real maximum: mode === 2 ? Logic.peak(models,["total"]) : Math.max(1, ...barValues.map(function(v) { return Logic.known(v) ? v : 0 }))
    property int selected: 0
    readonly property bool inspectionActive: active && mode !== 2 && (hover.containsMouse || chart.activeFocus)
    onSelectedChanged: graph.requestPaint()
    onInspectionActiveChanged: graph.requestPaint()
    onBucketsChanged: {
        selected = hover.containsMouse ? Logic.barBucket(hover.mouseX,chart.width,buckets.length,root.plotPadding) : Math.min(selected,Math.max(0,buckets.length-1))
        graph.requestPaint()
    }
    onRangeChanged: graph.requestPaint()
    onModeChanged: { selected=0; graph.requestPaint() }
    onColorsChanged: graph.requestPaint()
    onEnabledSeriesChanged: graph.requestPaint()
    onMaximumChanged: graph.requestPaint()
    onWidthChanged: graph.requestPaint()
    function inspect(index) { selected=Math.max(0,Math.min(buckets.length-1,index)); chart.forceActiveFocus() }
    spacing: Style.space(4)

    RowLayout {
        visible: root.mode !== 2
        Layout.fillWidth: true; spacing: 0
        Repeater {
            model: Logic.seriesIcons
            delegate: Controls.Button {
                id: seriesButton
                required property int index
                required property string modelData
                Layout.fillWidth: true
                implicitHeight: Style.space(25); padding: 0
                text: modelData
                Accessible.name: Logic.seriesNames[index]
                Accessible.checkable: true; Accessible.checked: root.enabledSeries[index]
                background: Item {}
                contentItem: Text {
                    text: seriesButton.text; font.family: Style.font.family; font.pixelSize: Style.font.body
                    color: root.colors[seriesButton.index]; opacity: root.enabledSeries[seriesButton.index] ? 1 : 0.3
                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                }
                onClicked: { var next=root.enabledSeries.slice(); next[index]=!next[index]; root.enabledSeries=next }
                PanelToolTip { visible: seriesButton.hovered || seriesButton.activeFocus; text: Logic.seriesNames[seriesButton.index] }
            }
        }
    }
    Item {
        id: chart
        Layout.fillWidth: true
        implicitHeight: Style.space(root.hasObservations ? 130 : 56)
        activeFocusOnTab: true
        Accessible.name: "Token activity. Left and right to inspect buckets."
        Accessible.description: Logic.tooltip(root.buckets[root.selected])
        Keys.onLeftPressed: root.selected=Math.max(0,root.selected-1)
        Keys.onRightPressed: root.selected=Math.min(root.plotted.length-1,root.selected+1)
        Canvas {
            id: graph
            anchors.fill: parent
            onPaint: {
                if (!root.active) return
                var ctx=getContext("2d")
                ctx.reset()
                if (!root.hasObservations) return
                var pad=root.plotPadding, yPad=Style.space(8), w=width-pad*2, h=height-yPad*2
                ctx.strokeStyle=Qt.rgba(root.foreground.r,root.foreground.g,root.foreground.b,0.12)
                ctx.lineWidth=1
                for (var g=0;g<3;g++) { ctx.beginPath();ctx.moveTo(pad,yPad+h*g/2);ctx.lineTo(pad+w,yPad+h*g/2);ctx.stroke() }
                if (root.mode === 2) return
                var step=w/Math.max(1,root.buckets.length), gap=Math.min(Style.space(3),step*0.2)
                for (var i=0;i<root.buckets.length;i++) {
                    var value=root.barValues[i]
                    if (!Logic.known(value) || value === 0) continue
                    var bottom=yPad+h
                    ctx.globalAlpha=Logic.focusOpacity(i,root.selected,root.inspectionActive)
                    for (var s=0;s<4;s++) {
                        if (!root.enabledSeries[s] || !Logic.known(root.buckets[i][root.keys[s]])) continue
                        var barHeight=h*root.buckets[i][root.keys[s]]/root.maximum
                        ctx.fillStyle=root.colors[s]
                        ctx.fillRect(Logic.barCenter(i,width,root.buckets.length,pad)-step/2+gap/2,bottom-barHeight,Math.max(1,step-gap),barHeight)
                        bottom-=barHeight
                    }
                }
                ctx.globalAlpha=1
            }
        }
        Flickable {
            id: modelScroll
            visible: root.mode===2
            anchors.fill: parent;clip: true
            contentWidth: width;contentHeight: modelColumn.height
            Column {
                id: modelColumn
                width: modelScroll.width;spacing: Style.space(4)
                Repeater {
                    model: root.models
                    delegate: Item {
                        id: modelRow
                        required property var modelData
                        required property int index
                        width: modelColumn.width;height: Style.space(26)
                        activeFocusOnTab: true
                        Accessible.name: String(modelData.model || "Unknown model")+", "+Logic.format(modelData.total)
                        Rectangle { anchors.fill: parent;color: Qt.rgba(root.foreground.r,root.foreground.g,root.foreground.b,0.05) }
                        Rectangle { height: parent.height;width: Logic.known(modelRow.modelData.total) ? parent.width*modelRow.modelData.total/root.maximum : 0;color: Qt.rgba(Color.accent.r,Color.accent.g,Color.accent.b,0.2) }
                        Text { anchors.left: parent.left;anchors.right: amount.left;anchors.margins: Style.space(6);anchors.verticalCenter: parent.verticalCenter;text: String(modelRow.modelData.model || "Unknown model");elide: Text.ElideMiddle;textFormat: Text.PlainText;color: root.foreground;font.family: Style.font.family;font.pixelSize: Style.font.caption }
                        Text { id: amount;anchors.right: parent.right;anchors.rightMargin: Style.space(6);anchors.verticalCenter: parent.verticalCenter;text: Logic.format(modelRow.modelData.total);color: root.foreground;font.family: Style.font.family;font.pixelSize: Style.font.caption }
                        MouseArea { id: modelHover;anchors.fill: parent;hoverEnabled: true;onClicked: {root.selected=modelRow.index;modelRow.forceActiveFocus()} }
                        PanelToolTip { visible: modelHover.containsMouse || modelRow.activeFocus;text: String(modelRow.modelData.model || "Unknown model")+"\nProvider: "+String(modelRow.modelData.provider || "Unknown")+"\nTotal: "+Logic.format(modelRow.modelData.total) }
                    }
                }
            }
            Controls.ScrollBar.vertical: Controls.ScrollBar {}
        }
        Text {
            anchors.centerIn: parent;visible: !root.hasObservations
            text: "No observations in this range";color: root.muted;font.family: Style.font.family;font.pixelSize: Style.font.bodySmall
        }
        MouseArea {
            id: hover
            enabled: root.mode!==2
            anchors.fill: parent;hoverEnabled: true
            onClicked: chart.forceActiveFocus()
            onPositionChanged: function(mouse) { root.selected=Logic.barBucket(mouse.x,width,root.buckets.length,root.plotPadding) }
        }
        Item {
            id: tooltipAnchor
            x: Math.max(0,Math.min(chart.width-width,Logic.barCenter(root.selected,chart.width,root.buckets.length,root.plotPadding)))
            y: chart.height/2;width: 1;height: 1
            PanelToolTip {
                id: bucketTip
                visible: root.inspectionActive && root.buckets.length>0
                text: Logic.tooltip(root.buckets[root.selected])
                x: Math.max(-tooltipAnchor.x,Math.min(8,chart.width-tooltipAnchor.x-width))
                y: -height-12;padding: Style.space(8)
                contentItem: Column {
                    width: Style.space(170);spacing: Style.space(4)
                    Text { width: parent.width;text: root.buckets[root.selected] ? Logic.displayDates(root.buckets[root.selected].label) : "";color: root.foreground;font.family: Style.font.family;font.pixelSize: Style.font.caption;font.bold: true }
                    Repeater {
                        model: Logic.tooltipRows(root.buckets[root.selected])
                        delegate: RowLayout {
                            id: metricRow
                            required property var modelData
                            width: Style.space(170)
                            Text { text: metricRow.modelData.icon;color: root.foreground;font.family: Style.font.family;font.pixelSize: Style.font.caption }
                            Text { Layout.fillWidth: true;text: metricRow.modelData.name;color: root.muted;font.family: Style.font.family;font.pixelSize: Style.font.caption }
                            Text { text: metricRow.modelData.value;color: root.foreground;font.family: Style.font.family;font.pixelSize: Style.font.caption }
                        }
                    }
                }
            }
        }
    }
    Item {
        id: bucketLabels
        Layout.fillWidth: true
        Layout.preferredHeight: Style.font.caption+Style.space(4)
        visible: root.mode !== 2 && root.buckets.length > 0
        Repeater {
            model: Logic.axisTicks(root.buckets,root.rangeKey,bucketLabels.width,root.plotPadding,Style.space(root.rangeKey === "today" ? 60 : root.rangeKey === "all" ? 88 : 40))
            delegate: Text {
                required property var modelData
                x: modelData.x-width/2
                text: modelData.label
                color: root.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
            }
        }
    }
    Text {
        Layout.fillWidth: true
        text: root.mode === 2 ? "Ranked by recorded total" : "Tokens · linear"
        horizontalAlignment: Text.AlignHCenter
        color: root.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
    }
}
