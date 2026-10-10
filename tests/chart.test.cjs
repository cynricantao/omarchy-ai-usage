const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');const b=path.resolve(__dirname,'..');
test('chart leaves unknown gaps, sorts models and preserves authoritative totals',()=>{
 const L={};vm.createContext(L);vm.runInContext(fs.readFileSync(path.join(b,'Logic.js'),'utf8'),L);
 assert.equal(typeof L.chartPoints,'function','chart gap logic must exist');
 const rows=[{input:10,output:1,total:11},{input:null,output:2,total:null},{input:0,output:3,total:3}];
 const p=L.chartPoints(rows,'input',100,50,10);assert.equal(p.length,3);assert.equal(p[1],null);assert.equal(p[2].y,50);assert.equal(p[0].y,0);
 assert.equal(L.chartPoints([{input:1}], 'input',100,100,1000000,true)[0].y < 99,true,'log scale keeps small series visible');
 assert.equal(L.peak(rows,['input']),10);assert.equal(L.peak([{input:null}],['input']),1);
 assert.equal(L.ranked([{model:'a',total:null},{model:'b',total:9},{model:'c',total:0}])[0].model,'b');
 assert.match(L.tooltip(rows[1]),/Total: —/);
 const q=fs.readFileSync(path.join(b,'ActivityChart.qml'),'utf8');
 for(const s of ['Logic.barValues','activeFocusOnTab: true','Keys.onLeftPressed','Keys.onRightPressed','PanelToolTip','Logic.tooltip','cache_read','cache_write','Color.accent','Canvas','onColorsChanged','onRangeChanged'])assert.ok(q.includes(s),s);
 assert.doesNotMatch(q,/NumberAnimation|SequentialAnimation/);
});
