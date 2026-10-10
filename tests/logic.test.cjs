const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const base=path.resolve(__dirname,'..');
function logic(){const p=path.join(base,'Logic.js'); assert.ok(fs.existsSync(p),'snapshot logic must exist'); const c={};vm.createContext(c);vm.runInContext(fs.readFileSync(p,'utf8'),c);return c;}
test('unknown snapshots remain identifiable and never become zero',()=>{
 const L=logic(); const s=L.parseSnapshot('broken');
 assert.equal(s.tools[0].id,'hermes');assert.equal(s.tools[0].totals.today,null);
 assert.equal(L.format(null),'—');assert.equal(L.format(0),'0');assert.equal(L.known(undefined),false);
 assert.equal(L.parseSnapshot('{"version":2}').tools[0].totals.all,null);
 assert.equal(L.pickTool({tools:[{id:'codex'}]},'hermes').id,'hermes');
 assert.equal(L.openTool({default_tool:'codex'}),'codex');assert.equal(L.openTool({}),'hermes');
 const b={label:'Monday',input:100,output:20,cache_read:null,cache_write:0,total:120};
 assert.match(L.tooltip(b),/Total: 120/);assert.match(L.tooltip(b),/Cache read: —/);
 assert.equal(L.parseSnapshot(JSON.stringify({version:1,tools:[{id:'hermes',totals:{today:123}}]})).tools[0].totals.today,123);
});
