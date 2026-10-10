const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
test('Command Code survives snapshot parsing and installed-only selection', () => {
  const L = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../Logic.js'), 'utf8'), L);
  const s = L.parseSnapshot(JSON.stringify({version:1, tools:[{id:'commandcode', installed:true, name:'Command Code', totals:{all:120}}]}));
  assert.equal(L.installedTools(s).length, 1);
  assert.equal(L.selectInstalled(s, 'commandcode'), 'commandcode');
  assert.equal(L.pickTool(s, 'commandcode').totals.all, 120);
  assert.equal(L.openTool({default_tool:'commandcode'}), 'commandcode');
});
