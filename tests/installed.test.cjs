const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function logic(){const c={};vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(__dirname,'../Logic.js'),'utf8'),c);return c;}
test('only installed tools are selectable; stale default and removal fall back safely',()=>{
 const L=logic();const s=L.parseSnapshot(JSON.stringify({version:1,tools:[{id:'hermes',installed:true},{id:'codex',installed:true},{id:'opencode',installed:false,totals:{all:123}}]}));
 assert.equal(JSON.stringify(L.installedTools(s).map(t=>t.id)),JSON.stringify(['hermes','codex']));
 assert.equal(L.selectInstalled(s,'opencode'),'hermes');assert.equal(L.selectInstalled(s,'codex'),'codex');
 assert.equal(L.selectInstalled(L.parseSnapshot(''),'codex'),'');
 const q=fs.readFileSync(path.join(__dirname,'../Panel.qml'),'utf8');
 assert.ok(q.includes('labels: root.availableTools.map'));assert.ok(q.includes('onSnapshotChanged:'));
});
