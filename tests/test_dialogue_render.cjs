const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="text"></div>'),context=vm.createContext({document:dom.window.document});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/geo_harness/ui/dialogue.js'),'utf8'),context);
test('model content cannot inject markup or executable links',()=>{
 const parent=dom.window.document.getElementById('text');context.parent=parent;vm.runInContext('renderAssistantText(parent,"<img src=x onerror=alert(1)>\\n[click](javascript:alert(1))\\n**重点** `text`")',context);
 assert.equal(parent.querySelector('img'),null);assert.equal(parent.querySelector('a'),null);assert.match(parent.textContent,/onerror/);assert.equal(parent.querySelector('b').textContent,'重点');
});
test('real research statistics remain readable as a table',()=>{
 const parent=dom.window.document.createElement('div');context.parent=parent;vm.runInContext('renderAssistantText(parent,"## 研究结果\\n| 分区 | 人数 |\\n|---|---|\\n| 西半区 | 212919 |\\n| 东半区 | 320136 |")',context);
 assert.equal(parent.querySelectorAll('table tr').length,3);assert.equal(parent.querySelectorAll('td').length,4);assert.match(parent.textContent,/212919/);
});
