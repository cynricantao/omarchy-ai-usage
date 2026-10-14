pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Logic.js" as Logic

Panel {
    id: root
    moduleName: "cynricantao.ai-usage"
    ipcTarget: "cynricantao.ai-usage"
    manageIpc: false
    IpcHandler {
        target: root.ipcTarget
        function open(): void { root.open() }
        function close(): void { root.close() }
        function toggle(): void { root.toggle() }
        function show(): void { root.open() }
        function hide(): void { root.close() }
        function refresh(): string { root.run(["rescan"]); return "requested" }
        function next(): string { if (root.availableToolIds.length) root.selectedToolId=root.availableToolIds[(root.availableToolIds.indexOf(root.selectedToolId)+1)%root.availableToolIds.length]; return root.selectedToolId }
        function selectTool(id: string): string { if (root.availableToolIds.indexOf(id)>=0) root.selectedToolId=id; return root.selectedToolId }
        function selectRange(id: string): string { if (["today","week","all"].indexOf(id)>=0) root.rangeKey=id; return root.rangeKey }
        function selectChart(index: int): int { if (index === 0 || index === 2) root.chartMode=index; return root.chartMode }
        function showAllModels(show: bool): void { root.showAllModels=show }
        function inspectBucket(index: int): void { activityChart.inspect(index) }
        function status(): string { return JSON.stringify({opened:root.opened,tool:root.selectedToolId,range:root.rangeKey,chart:root.chartMode,modelRows:root.modelRows.length,showAllModels:root.showAllModels,installedTools:root.availableToolIds,chartStyle:"hourly-bars",quotaRows:root.quotaRows.map(function(q) { return {label:q.label,used_percent:q.used_percent,status:q.status} }),updated_at:root.snapshot.updated_at}) }
    }
    readonly property color foreground: Color.popups.text
    readonly property color dim: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.65)
    readonly property color track: Style.selectedFillFor(foreground, Color.accent)
    readonly property string home: Quickshell.env("HOME")
    readonly property string dataHome: Quickshell.env("XDG_DATA_HOME") || home + "/.local/share"
    property var snapshot: Logic.parseSnapshot("")
    property string selectedToolId: "hermes"
    readonly property var availableTools: Logic.installedTools(snapshot)
    readonly property var availableToolIds: availableTools.map(function(t) { return t.id })
    onSnapshotChanged: selectedToolId = Logic.selectInstalled(snapshot, selectedToolId)
    property string rangeKey: "today"
    property int chartMode: 0
    property bool showAllModels: false
    onRangeKeyChanged: showAllModels=false
    onSelectedToolIdChanged: showAllModels=false
    property bool showSettings: false
    property string feedback: ""
    property double now: Date.now() / 1000
    readonly property var config: snapshot.settings || ({})
    readonly property bool reducedMotion: !!config.reduced_motion
    readonly property var tool: Logic.pickTool(snapshot, selectedToolId)
    readonly property var range: (tool.ranges || {})[rangeKey] || ({buckets:[],models:[]})
    readonly property var modelRows: Logic.modelRows(root.range, root.showAllModels)
    readonly property var quotaRows: Logic.quotaRows(tool)
    readonly property var days: tool.days || []
    readonly property real dayScale: config.daily_budget > 0 ? config.daily_budget : Math.max(1, ...days.map(function(d) { return Logic.known(d.total) ? d.total : 0 }))
    readonly property bool working: !snapshot.unavailable && Logic.known(snapshot.updated_at) && now - snapshot.updated_at < 120 && snapshot.tools.some(function(t) { return t.activity === "working" })
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    function run(args) {
        if (request.running) return
        feedback = ""
        request.command = [home + "/.local/bin/token-activity"].concat(args)
        request.running = true
    }
    function iconFor(id, surface) {
        // Public distribution uses the existing named fallback: no bundled
        // provider logos with unclear redistribution rights.
        return ""
    }
    function age(timestamp) {
        if (!Logic.known(timestamp)) return "unknown"
        var seconds = Math.max(0, now-timestamp)
        return seconds < 60 ? "just now" : Logic.duration(seconds) + " ago"
    }
    function resetText(timestamp) {
        if (!Logic.known(timestamp)) return "reset unknown"
        var seconds = timestamp-now
        return seconds <= 0 ? "reset due; refresh" : "resets in " + Logic.duration(seconds)
    }
    onOpenedChanged: if (opened) {
        selectedToolId = Logic.selectInstalled(snapshot, Logic.openTool(config))
        showSettings = false
        now = Date.now() / 1000
        snapshotFile.reload()
        scroll.contentY = 0
    }
    FileView {
        id: snapshotFile
        path: root.dataHome + "/token-activity/snapshot.json"
        watchChanges: true
        onFileChanged: reload()
        // Never install the unavailable stub over good data: a failed or
        // invalid read must not blank every list, including Tokens by model.
        onLoaded: {
            var next = Logic.parseSnapshot(text())
            if (next.unavailable !== true || root.snapshot.unavailable === true) root.snapshot = next
        }
    }
    Process {
        id: request
        onExited: function(exitCode) {
            root.feedback = exitCode === 0 ? "Saved / refresh requested" : "Command failed; check token-activity status"
            snapshotFile.reload()
        }
    }
    // Text freshness only; no collector, idle animation, or periodic process.
    Timer { interval: 30000; running: true; repeat: true; onTriggered: root.now = Date.now() / 1000 }
    BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: "󱚣"
        tooltipText: {
            var h = Logic.pickTool(root.snapshot, "hermes")
            return "Hermes · " + (h.activity === "working" ? "Working" : "Last used") + "\n" + (h.last_model || "Model not observed") + "\nToday · " + Logic.format(h.totals.today) + " tokens"
        }
        onPressed: root.toggle()
    }
    KeyboardPanel {
        id: panel
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        focusTarget: panelFocus
        // All custom visuals are static; native shell owns popup transitions.
        contentWidth: panel.fittedContentWidth(Style.space(420))
        contentHeight: panel.fittedContentHeight(body.implicitHeight, Style.space(960))
        FocusScope {
            id: panelFocus
            anchors.fill: parent
            Keys.onEscapePressed: root.close()
            Flickable {
                id: scroll
                anchors.fill: parent
                contentWidth: width
                contentHeight: body.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Controls.ScrollBar.vertical: Controls.ScrollBar {}
                ColumnLayout {
                    id: body
                    width: scroll.width
                    spacing: Style.space(9)
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Token activity"; font.bold: true; Layout.fillWidth: true }
                        Controls.Button {
                            id: settingsButton
                            Layout.preferredWidth: Style.space(28); Layout.preferredHeight: Style.space(28)
                            padding: 0; Accessible.name: "Settings"
                            onClicked: root.showSettings = !root.showSettings
                            background: Item {}
                            contentItem: Text { text: "\uf013"; font.family: Style.font.family; font.pixelSize: Style.font.body; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; color: settingsButton.hovered || root.showSettings ? Color.accent : root.foreground }
                        }
                    }
                    Tabs {
                        id: toolTabs
                        Layout.fillWidth: true
                        labels: root.availableTools.map(function(t) { return t.name })
                        currentIndex: root.availableToolIds.indexOf(root.selectedToolId)
                        onChosen: function(index) { root.selectedToolId=root.availableToolIds[index] }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Image {
                            id: toolImage
                            Layout.preferredWidth: Style.space(26); Layout.preferredHeight: Style.space(26)
                            source: root.iconFor(root.tool.id, Color.popups.background)
                            fillMode: Image.PreserveAspectFit
                            visible: root.tool.id !== "hermes" && source.toString() !== "" && status !== Image.Error
                        }
                        Label {
                            visible: root.tool.id === "hermes"
                            text: "󱚣"
                            Layout.preferredWidth: Style.space(26)
                            Layout.preferredHeight: Style.space(26)
                            font.pixelSize: Style.space(24)
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 2
                            Label { text: (root.tool.name || "No installed agents detected") + " · " + (root.tool.activity || "unknown"); font.bold: true; Layout.fillWidth: true }
                            Label {
                                text: root.tool.active_models.length > 1 ? "Multiple models" : (root.tool.activity === "working" ? "Current · " : "Last used · ") + (root.tool.active_models[0] || root.tool.last_model || "Not observed")
                                color: root.dim; Layout.fillWidth: true; elide: Text.ElideMiddle
                                MouseArea { id: modelDetail; anchors.fill: parent; hoverEnabled: true }
                                PanelToolTip { visible: modelDetail.containsMouse; text: root.tool.active_models.length ? root.tool.active_models.join("\n") : root.tool.last_model || "No model observed" }
                            }
                        }
                        Label { text: root.tool.installed ? String(root.tool.state || "") : "Not detected"; color: root.dim; font.pixelSize: Style.font.caption }
                    }
                    Row {
                        id: totalColumns
                        Layout.fillWidth: true
                        spacing: Style.space(8)
                        Repeater {
                            model: ["Today", "7 Days", "All Time"]
                            delegate: Column {
                                id: totalColumn
                                required property int index
                                required property string modelData
                                width: (totalColumns.width - 2 * totalColumns.spacing) / 3
                                spacing: Style.space(4)
                                Label { text: totalColumn.modelData; color: totalColumn.index === 0 ? Color.accent : root.dim; font.bold: totalColumn.index === 0 }
                                Label { text: Logic.format(root.tool.totals[["today","week","all"][totalColumn.index]]); color: totalColumn.index === 0 ? Color.accent : root.foreground; font.pixelSize: Style.font.display; font.bold: totalColumn.index === 0 }
                            }
                        }
                    }
                    Label { text: root.config.daily_budget > 0 ? "7 days · personal daily budget " + Logic.format(root.config.daily_budget) : "7 days · relative to busiest day, not quota"; color: root.dim; font.pixelSize: Style.font.caption }
                    RowLayout {
                        id: miniStrip
                        Layout.fillWidth: true; spacing: Style.space(5)
                        Repeater {
                            model: root.days
                            delegate: Item {
                                id: dayRow
                                required property var modelData
                                required property int index
                                Layout.fillWidth: true; Layout.preferredWidth: 1; implicitHeight: Style.space(40)
                                activeFocusOnTab: true
                                Accessible.name: Logic.tooltip(modelData)
                                Text { id: dayLabel; anchors.bottom: parent.bottom; width: parent.width; horizontalAlignment: Text.AlignHCenter; fontSizeMode: Text.Fit; minimumPixelSize: Style.space(6); text: dayRow.index === 6 ? "Today" : Logic.displayDates(dayRow.modelData.label); color: dayRow.index === 6 ? Color.accent : root.dim; font.family: Style.font.family; font.pixelSize: Style.font.caption }
                                Rectangle {
                                    anchors.top: parent.top; width: parent.width; height: Style.space(19); color: root.track; radius: Style.space(2)
                                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: Logic.known(dayRow.modelData.total) ? Math.max(1,parent.height * Math.min(1, dayRow.modelData.total / root.dayScale)) : 0; color: dayRow.index === 6 ? Color.accent : root.dim; radius: parent.radius }
                                }
                                MouseArea { id: dayHover; anchors.fill: parent; hoverEnabled: true; onClicked: dayRow.forceActiveFocus() }
                                PanelToolTip { visible: dayHover.containsMouse || dayRow.activeFocus; text: Logic.tooltip(dayRow.modelData) + (root.config.daily_budget > 0 && Logic.known(dayRow.modelData.total) ? "\nPersonal budget · " + (100 * dayRow.modelData.total / root.config.daily_budget).toFixed(1) + "%" : "") }
                            }
                        }
                        Label { visible: root.days.length === 0; text: "No dated observations"; color: root.dim }
                    }
                    Tabs {
                        id: chartTabs
                        Layout.fillWidth: true
                        labels: ["Token activity", "Model breakdown"]
                        currentIndex: [0, 2].indexOf(root.chartMode)
                        onChosen: function(index) { root.chartMode=[0, 2][index] }
                    }
                    Tabs {
                        id: rangeTabs
                        Layout.fillWidth: true
                        labels: ["Today", "7 Days", "All Time"]
                        currentIndex: ["today", "week", "all"].indexOf(root.rangeKey)
                        onChosen: function(index) { root.rangeKey=["today", "week", "all"][index] }
                    }
                    Label { visible: root.chartMode !== 2; text: root.rangeKey === "today" ? "Hourly token usage" : "Daily token usage"; color: root.dim; font.pixelSize: Style.font.caption }
                    ActivityChart {
                        id: activityChart
                        active: root.opened
                        Layout.fillWidth: true
                        range: root.range
                        rangeKey: root.rangeKey
                        dailyBuckets: Logic.dailyRows(root.days, root.range, root.rangeKey)
                        mode: root.chartMode
                        foreground: root.foreground
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: Style.space(4)
                        visible: root.chartMode !== 2
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "Tokens by model"; Layout.fillWidth: true }
                            Controls.Button {
                                id: expandModels
                                visible: root.modelRows.length > 0
                                text: root.showAllModels ? "Show less" : "Show all"
                                implicitHeight: Style.space(24); padding: 0
                                background: Item {}
                                contentItem: Text { text: expandModels.text; font.underline: true; font.family: Style.font.family; font.pixelSize: Style.font.caption; color: expandModels.hovered ? Color.accent : root.dim; verticalAlignment: Text.AlignVCenter }
                                onClicked: root.showAllModels=!root.showAllModels
                            }
                        }
                        Flickable {
                            Layout.fillWidth: true
                            implicitHeight: Math.min(modelColumn.implicitHeight,Style.space(156))
                            contentWidth: width; contentHeight: modelColumn.implicitHeight
                            clip: true; boundsBehavior: Flickable.StopAtBounds
                            Controls.ScrollBar.vertical: Controls.ScrollBar {}
                            Column {
                                id: modelColumn
                                width: parent.width; spacing: Style.space(3)
                                Repeater {
                                    model: root.modelRows
                                    delegate: Item {
                                        id: modelEntry
                                        required property var modelData
                                        width: modelColumn.width; height: Style.space(25)
                                        activeFocusOnTab: true
                                        Accessible.name: modelData.model + ", " + Logic.format(modelData.total) + " tokens"
                                        Rectangle { anchors.bottom: parent.bottom; height: 1; width: Logic.known(modelEntry.modelData.total) && root.modelRows[0].total > 0 ? parent.width * modelEntry.modelData.total / root.modelRows[0].total : 0; color: Color.accent; opacity: 0.25 }
                                        Label { anchors.left: parent.left; anchors.right: modelTotal.left; anchors.rightMargin: Style.space(8); anchors.verticalCenter: parent.verticalCenter; text: modelEntry.modelData.model; elide: Text.ElideMiddle }
                                        Label { id: modelTotal; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: Logic.format(modelEntry.modelData.total) }
                                        MouseArea { id: rowHover; anchors.fill: parent; hoverEnabled: true; onClicked: modelEntry.forceActiveFocus() }
                                        PanelToolTip { visible: rowHover.containsMouse || modelEntry.activeFocus; text: modelEntry.modelData.model + "\n" + modelEntry.modelData.providers.join(", ") + "\n" + Logic.format(modelEntry.modelData.total) + " tokens" }
                                    }
                                }
                            }
                        }
                        Label { visible: root.modelRows.length === 0; text: "No model usage in this range"; color: root.dim; font.pixelSize: Style.font.caption }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: Style.space(8)
                        visible: root.quotaRows.length > 0
                        Label { text: "Usage limits"; font.bold: true }
                        Repeater {
                            model: root.quotaRows
                            delegate: ColumnLayout {
                                id: quotaRow
                                required property var modelData
                                readonly property var fraction: Logic.quotaFraction(modelData)
                                Layout.fillWidth: true; spacing: Style.space(4)
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { Layout.fillWidth: true; text: String(quotaRow.modelData.label || "Provider limit"); font.pixelSize: Style.font.caption; color: root.dim; elide: Text.ElideMiddle }
                                    Label { text: quotaRow.fraction === null ? "Unavailable" : (quotaRow.fraction > 0 && quotaRow.fraction < 0.01 ? "<1" : (quotaRow.fraction*100).toFixed(0)) + "% used"; font.pixelSize: Style.font.caption }
                                }
                                Row {
                                    id: quotaTrack
                                    Layout.fillWidth: true
                                    spacing: Style.space(3)
                                    Layout.preferredHeight: Style.space(14)
                                    Repeater {
                                        model: 24
                                        delegate: Rectangle {
                                            id: quotaSegment
                                            required property int index
                                            width: Math.max(0,(quotaTrack.width-23*quotaTrack.spacing)/24)
                                            height: Style.space(14)
                                            color: root.track
                                            opacity: quotaRow.fraction === null ? 0.45 : 1
                                            Rectangle {
                                                height: parent.height
                                                width: parent.width*(quotaRow.fraction === null ? 0 : Math.max(0,Math.min(1,quotaRow.fraction*24-quotaSegment.index)))
                                                color: quotaRow.fraction !== null && quotaRow.fraction >= 0.9 ? root.foreground : Color.accent
                                            }
                                        }
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: quotaRow.fraction === null ? "Provider quota not available" : root.resetText(quotaRow.modelData.resets_at) + " · " + root.age(quotaRow.modelData.observed_at) + " · " + String(quotaRow.modelData.status || "unknown")
                                    color: root.dim; font.pixelSize: Style.font.caption
                                    MouseArea { id: resetHover; anchors.fill: parent; hoverEnabled: true }
                                    PanelToolTip { visible: resetHover.containsMouse; text: String(quotaRow.modelData.source || root.tool.name + " provider quota") + (quotaRow.fraction !== null ? "\nUsed · " + (quotaRow.fraction*100).toFixed(3) + "%" : "") + (quotaRow.modelData.model_scope === "shared_group" ? "\nShared budget · " + String(quotaRow.modelData.models_description || quotaRow.modelData.model) : "") + "\n" + (Logic.known(quotaRow.modelData.resets_at) ? Logic.displayDates(new Date(quotaRow.modelData.resets_at * 1000).toISOString()) : "Reset unavailable") }
                                }
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            Layout.fillWidth: true; font.pixelSize: Style.font.caption; color: root.dim; elide: Text.ElideRight
                            text: "Partial history" + (root.tool.coverage.earliest ? " · " + Logic.displayDates(root.tool.coverage.earliest) : "")
                            MouseArea { id: coverageHover; anchors.fill: parent; hoverEnabled: true }
                            PanelToolTip {
                                id: coverageTip
                                visible: coverageHover.containsMouse
                                text: Logic.displayDates(root.tool.coverage.note || "") + "\nUndated · " + Logic.format(root.tool.coverage.undated_tokens)
                                contentItem: Text { width: Style.space(310); text: coverageTip.text; textFormat: Text.PlainText; color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.font.caption; wrapMode: Text.Wrap; padding: Style.space(8) }
                            }
                        }
                        Action { text: root.age(root.snapshot.updated_at) + " ↻"; Accessible.name: "Refresh local collection"; enabled: !request.running; onClicked: { snapshotFile.reload(); root.run(["rescan"]) } }
                    }
                    Label { visible: root.feedback !== ""; text: root.feedback; color: root.dim; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    ColumnLayout {
                        id: settingsBox
                        visible: root.showSettings; Layout.fillWidth: true; spacing: Style.space(6)
                        Label { text: "Settings"; font.bold: true }
                        Label { text: "Default tool" }
                        Tabs { id: defaultChoice; Layout.fillWidth: true; labels: root.availableTools.map(function(t) { return t.name }); currentIndex: root.availableToolIds.indexOf(Logic.selectInstalled(root.snapshot, Logic.openTool(root.config))); onChosen: function(index) { currentIndex=index } }
                        Field { id: timezone; Layout.fillWidth: true; placeholderText: "Timezone (IANA)"; text: root.config.timezone || "UTC"; Accessible.name: "Timezone" }
                        Field { id: budget; Layout.fillWidth: true; placeholderText: "Daily personal token budget (blank = relative)"; text: root.config.daily_budget > 0 ? String(root.config.daily_budget) : ""; Accessible.name: "Personal daily token budget" }
                        Controls.CheckBox { id: motion; text: "Reduced motion"; checked: root.reducedMotion; palette.windowText: root.foreground; palette.text: root.foreground }
                        Label { text: "Path override · " + root.tool.name; color: root.dim }
                        Field { id: pathOverride; Layout.fillWidth: true; placeholderText: "Absolute directory (blank keeps current)"; text: (root.config.paths || {})[root.selectedToolId] || ""; Accessible.name: "Tool path override" }
                        RowLayout {
                            Action {
                                text: "Save"; enabled: !request.running
                                onClicked: {
                                    var patch = {default_tool:root.availableToolIds[defaultChoice.currentIndex], timezone:timezone.text.trim(), daily_budget:budget.text.trim() === "" ? null : Number(budget.text), reduced_motion:motion.checked}
                                    if (budget.text.trim() !== "" && (!isFinite(patch.daily_budget) || patch.daily_budget <= 0)) { root.feedback = "Budget must be a positive number"; return }
                                    if (pathOverride.text.trim() !== "") {
                                        if (pathOverride.text.charAt(0) !== "/") { root.feedback = "Path must be absolute"; return }
                                        patch.paths = {}; patch.paths[root.selectedToolId] = pathOverride.text.trim()
                                    }
                                    root.run(["configure", JSON.stringify(patch)])
                                }
                            }
                            Action { text: "Rescan"; enabled: !request.running; onClicked: root.run(["rescan"]) }
                            Label { text: "Resets tool on open"; color: root.dim; font.pixelSize: Style.font.caption }
                        }
                    }
                }
            }
        }
    }
    component Label: Text { textFormat: Text.PlainText; color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall }

    component Action: Controls.Button {
        font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
        implicitHeight: Style.space(28)
        palette.button: Color.popups.background; palette.buttonText: root.foreground; palette.highlight: Color.accent
    }
    component Field: Controls.TextField {
        font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
        color: root.foreground; palette.base: Color.popups.background; palette.text: root.foreground
        palette.placeholderText: root.dim; implicitHeight: Style.space(30)
    }
}
