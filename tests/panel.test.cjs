const {test}=require('node:test'); const assert=require('node:assert/strict');const fs=require('node:fs'),path=require('node:path');const base=path.resolve(__dirname,'..');
test('native panel keeps lifecycle identity and watches only shared snapshot',()=>{
 assert.ok(fs.existsSync(path.join(base,'Panel.qml')),'native panel must exist');
 const q=fs.readFileSync(path.join(base,'Panel.qml'),'utf8');const m=JSON.parse(fs.readFileSync(path.join(base,'manifest.json')));
 assert.equal(m.id,'cynricantao.ai-usage');assert.equal(m.omarchy.clonedFrom,'omarchy.agents');assert.equal(m.entryPoints.barWidget,'Panel.qml');
 for(const s of ['moduleName: "cynricantao.ai-usage"','ipcTarget: "cynricantao.ai-usage"','FileView {','watchChanges: true','snapshot.json','KeyboardPanel {','BarIconButton {','text: "󱚣"','Style.space(420)','Token activity','onOpenedChanged:','Logic.openTool','Tabs {','Today','7 Days','All Time','reduced_motion','"configure", JSON.stringify','"rescan"'])assert.ok(q.includes(s),s);
 assert.ok(!fs.existsSync(path.join(base,'Main.qml'))); assert.doesNotMatch(q,/sh",\s*"-c|UsageService/);
});
