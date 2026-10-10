const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');const base=path.resolve(__dirname,'..');
test('daily bars use calendar days matching the selected range',()=>{
 const L={};vm.createContext(L);vm.runInContext(fs.readFileSync(path.join(base,'Logic.js'),'utf8'),L);
 assert.equal(typeof L.dailyRows,'function','daily bar selection must exist');
 const days=[{start:10,end:20,total:7},{start:20,end:30,total:null}];
 assert.equal(L.dailyRows(days,{buckets:[{start:20,end:21,total:4}]},'today').length,1);
 assert.equal(L.dailyRows(days,{buckets:[{start:20,end:21,total:4}]},'today')[0].total,null);
 assert.equal(L.dailyRows(days,{},'week').length,2);
 const all={buckets:[{start:0,end:10,total:12}]};assert.equal(L.dailyRows(days,all,'all')[0].total,12);
 const q=fs.readFileSync(path.join(base,'ActivityChart.qml'),'utf8'); assert.ok(q.includes('property var dailyBuckets')); assert.ok(q.includes('mode === 1 ? dailyBuckets'));
});
