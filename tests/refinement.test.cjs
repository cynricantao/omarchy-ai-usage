const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');const base=path.resolve(__dirname,'..');function logic(){const L={};vm.createContext(L);vm.runInContext(fs.readFileSync(path.join(base,'Logic.js'),'utf8'),L);return L;}
test('token hover and reset ages use compact units without zeroing unknowns',()=>{
 const L=logic();assert.equal(typeof L.duration,'function');
 assert.equal(L.duration(6680*60),'4d');assert.equal(L.duration(5*3600),'5h');assert.equal(L.duration(120),'2m');assert.equal(L.duration(null),'—');
 assert.equal(L.format(1200000000),'1.2B');assert.match(L.tooltip({total:1234567,input:34567,output:null}),/1.2M/);assert.doesNotMatch(L.tooltip({total:1234567}),/1234567/);
});
test('model rows aggregate per model, rank and expand only the selected range',()=>{
 const L=logic();assert.equal(typeof L.modelRows,'function');
 const today={models:[{model:'a',provider:'p',total:10},{model:'a',provider:'q',total:20},{model:'b',total:50},{model:'c',total:5},{model:'d',total:1}]};
 const top=L.modelRows(today,false);assert.equal(top.length,3);assert.equal(top[0].model,'b');assert.equal(top[1].total,30);
 assert.equal(L.modelRows(today,true).length,4);assert.equal(L.modelRows({models:[{model:'week-only',total:99}]},false)[0].model,'week-only');
 assert.equal(L.modelRows({models:[{model:'a',total:2},{model:'a',total:null}]},false)[0].total,null);
});
test('hover focus isolates nearest bucket and every metric has an icon',()=>{
 const L=logic();assert.equal(typeof L.focusOpacity,'function');assert.equal(typeof L.nearestBucket,'function');
 assert.equal(L.nearestBucket(-10,100,5,0),0);assert.equal(L.nearestBucket(55,100,5,0),2);assert.equal(L.nearestBucket(120,100,5,0),4);assert.equal(L.nearestBucket(50,100,0,0),-1);
 assert.equal(L.focusOpacity(2,2,true),1);assert.ok(L.focusOpacity(1,2,true)<0.3);assert.equal(L.focusOpacity(1,2,false),1);
 assert.equal(new Set(L.seriesIcons).size,4);const rows=L.tooltipRows({total:1200000,input:1000,output:null});assert.equal(rows[0].value,'1.2M');assert.equal(rows[2].value,'—');
 const q=fs.readFileSync(path.join(base,'ActivityChart.qml'),'utf8');for(const marker of ['onSelectedChanged','inspectionActive','Logic.focusOpacity','Logic.barBucket','Logic.seriesIcons','Logic.tooltipRows','ctx.globalAlpha'])assert.ok(q.includes(marker),marker);
});
test('panel uses tabs, fixed three totals, corner settings and expandable model section',()=>{
 const q=fs.readFileSync(path.join(base,'Panel.qml'),'utf8');
 assert.ok(!q.includes('Controls.ComboBox'),'no dropdown controls');
 for(const marker of ['id: toolTabs','id: rangeTabs','id: totalColumns','id: settingsButton','Tokens by model','Show all','font.underline: true','Logic.modelRows(root.range','Logic.duration','font.bold: totalColumn.index === 0'])assert.ok(q.includes(marker),marker);
 assert.ok(q.includes('width: (totalColumns.width - 2 * totalColumns.spacing) / 3'),'headline columns must divide the available width equally');
 assert.ok(fs.existsSync(path.join(base,'Tabs.qml')));
});
