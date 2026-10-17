const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {JSDOM}=require('jsdom');
const ui=path.join(__dirname,'../src/geo_harness/ui');
const tick=()=>new Promise(resolve=>setImmediate(resolve));

async function workspace(surface='platform',{lateScript=false}={}){
 const dom=new JSDOM(fs.readFileSync(path.join(ui,'index.html'),'utf8'),{
  url:surface==='platform'?'http://localhost:3301/api/workbench/runtime/?surface=platform&theme=dark#workbench':'http://localhost:8810/accounts/abc/?surface=client#workbench',runScripts:'outside-only'});
 const w=dom.window,calls=[];let releaseCatalogue;
 const slowCatalogue=new Promise(resolve=>{releaseCatalogue=resolve});
 const settings={llm:{enabled:false,provider:'openai-compatible',model:'test',base_url:'https://example.org/v1',temperature:.2},viewer_url:''};
 w.fetch=async url=>{
  const route=String(url).split('/api/').pop();calls.push(route);
  let data;
  if(route==='session')data={csrf:'test-csrf',settings,account:{principal:'member',scoped:true},providers:[],version:'0.2.9',platform_url:'http://localhost:3301'};
  else if(route==='bootstrap')data=await slowCatalogue;
  else if(route==='workbench/context')data={revision:0,layers:[]};
  else if(route==='workbench/cases')data={templates:[],saved:[]};
  else data=[];
  return{ok:true,json:async()=>data};
 };
 vm.runInContext(fs.readFileSync(path.join(ui,'app.js'),'utf8'),dom.getInternalVMContext());
 if(lateScript)await tick();
 vm.runInContext(fs.readFileSync(path.join(ui,'workbench.js'),'utf8'),dom.getInternalVMContext());
 await tick();await tick();
 return{w,calls,close:()=>w.close(),release:()=>releaseCatalogue({csrf:'test-csrf',settings,account:{principal:'member',scoped:true},catalog:[],cards:[],catalog_cards:{},resource_nodes:[]})};
}
test('workspace starts its map from the lightweight session, without waiting for catalogue verification',async()=>{
 const app=await workspace();try{
  assert.equal(app.w.document.getElementById('wb-map').getAttribute('src'),'/map-viewer.html?surface=workbench&theme=dark');
  assert.equal(app.calls.filter(p=>p==='session').length,1);
  assert.equal(app.calls.includes('bootstrap'),false);
  assert.equal(app.calls.filter(p=>p==='workbench/context').length,1);
  assert.equal(app.calls.filter(p=>p==='workbench/cases').length,1);
  app.w.dispatchEvent(new app.w.Event('geoharness-ready'));await tick();
  assert.equal(app.calls.filter(p=>p==='workbench/context').length,1);
 }finally{app.close()}
});
test('market access starts one lazy catalogue refresh while the map remains present',async()=>{
 const app=await workspace();try{
  const before=app.w.document.getElementById('wb-map').getAttribute('src');
  app.w.document.querySelector('[data-page="market"]').click();await tick();
  app.w.document.querySelector('[data-page="market"]').click();await tick();
  assert.equal(app.calls.filter(p=>p==='bootstrap').length,1);
  assert.equal(app.w.document.getElementById('wb-map').getAttribute('src'),before);
 }finally{app.close()}
});
test('standalone client starts the same pinned GeoLibre renderer directly',async()=>{
 const app=await workspace('client');try{
  assert.match(app.w.document.getElementById('wb-map').getAttribute('src'),/^\/accounts\/abc\/ui\/geo-viewer\/index.html\?maponly=1/);
  assert.equal(app.calls.includes('bootstrap'),false);
 }finally{app.close()}
});
test('a fast cached session still starts the map when the workbench script arrives later',async()=>{
 const app=await workspace('platform',{lateScript:true});try{
  assert.match(app.w.document.getElementById('wb-map').getAttribute('src'),/^\/map-viewer.html/);
  assert.equal(app.calls.filter(p=>p==='workbench/context').length,1);
 }finally{app.close()}
});
