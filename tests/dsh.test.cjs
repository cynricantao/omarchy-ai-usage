const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const base=path.resolve(__dirname,'..');
function logic(){const c={};vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(base,'Logic.js'),'utf8'),c);return c;}
test('removed DSH is ignored even when installed in a legacy snapshot',()=>{
 const L=logic();const snapshot=L.parseSnapshot(JSON.stringify({version:1,tools:[{id:'hermes',installed:true},{id:'dsh',name:'DSH',installed:true,totals:{today:175,week:175,all:175},quotas:[]}]}));
 assert.equal(snapshot.tools.some(t=>t.id==='dsh'),false);
 assert.equal(L.installedTools(snapshot).some(t=>t.id==='dsh'),false);
 assert.equal(L.openTool({default_tool:'dsh'}),'hermes');
 assert.equal(L.selectInstalled(snapshot,'dsh'),'hermes');
 assert.equal(L.installedTools(snapshot).some(t=>t.id==='hermes'),true);
 const onlyRemoved=L.parseSnapshot(JSON.stringify({version:1,tools:[{id:'dsh',installed:true}]}));
 assert.equal(L.installedTools(onlyRemoved).length,0);
 assert.equal(L.selectInstalled(onlyRemoved,'dsh'),'');
});
