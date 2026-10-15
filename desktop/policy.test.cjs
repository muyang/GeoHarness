const {test}=require('node:test');const assert=require('node:assert/strict');
const {clientURL,navigationAllowed}=require('./policy.cjs');
test('desktop connects only to an explicitly local root service',()=>{
  assert.equal(clientURL(),'http://127.0.0.1:8810/');
  for(const url of ['https://attacker.example/','file:///etc/passwd','http://user:secret@127.0.0.1:8810/','http://127.0.0.1:8810/?token=secret','http://127.0.0.1:8810/admin'])assert.throws(()=>clientURL(url));
});
test('account pages and same-origin maps work; external top-level navigation is blocked',()=>{
  const home=clientURL();for(const p of ['login','accounts/abc/','viewer/','api/result/1'])assert(navigationAllowed(home+p,home));
  for(const url of ['http://127.0.0.1:3301/','https://attacker.example/','javascript:alert(1)','file:///tmp/a','http://secret@127.0.0.1:8810/'])assert(!navigationAllowed(url,home));
});
