const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const path=require('node:path');
const elements=new Map();
const listeners=new Map();
const context=vm.createContext({
  URL,URLSearchParams,Number,Map,crypto:require('node:crypto').webcrypto,
  location:{origin:'http://127.0.0.1:8810',href:'http://127.0.0.1:8810/',search:''},
  window:{addEventListener:(name,listener)=>listeners.set(name,listener)},document:{body:{classList:{add(){}}}},
  $:id=>{if(!elements.has(id))elements.set(id,{src:'',querySelectorAll:()=>[]});return elements.get(id);},
  setInterval:()=>0,clearInterval(){},setTimeout:()=>0,clearTimeout(){},
  apiURL:p=>'/api/'+p,esc:value=>String(value??''),
});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/geo_harness/ui/workbench.js'),'utf8'),context);
function normalize(view){return JSON.parse(JSON.stringify(vm.runInContext('normalizeViewerViewport('+JSON.stringify(view)+')',context)));}
test('world copies normalize to one full WGS84 world without mutating the view',()=>{
  const view={center:[474.3,30.57],bbox:[-220,-84,530,84],zoom:2,bearing:0,pitch:0};
  assert.deepEqual(normalize(view),{center:[114.29999999999995,30.57],bbox:[-180,-84,180,84],zoom:2,bearing:0,pitch:0});
  assert.deepEqual(view.bbox,[-220,-84,530,84]);
});
test('dateline-crossing view retains its narrow crossing extent',()=>{
  assert.deepEqual(normalize({center:[190,20],bbox:[170,10,210,30],zoom:6}),{center:[-170,20],bbox:[170,10,-150,30],zoom:6});
});
test('local scientific map extent stays unchanged; invalid input stays subject to server validation',()=>{
  const view={center:[114.3,30.57],bbox:[114.2,30.5,114.4,30.6],zoom:12};
  const actual=normalize(view);
  assert.deepEqual(actual,view);
  assert.deepEqual(normalize({center:['invalid',30],bbox:[1,2,3]}),{center:['invalid',30],bbox:[1,2,3]});
});
test('a slow third-party case catalogue does not hide local execution history or map context',async()=>{
  let releaseCases;
  const delayedCases=new Promise(resolve=>{releaseCases=resolve;});
  context.api=route=>({
    'workbench/context':Promise.resolve({revision:15,layers:[]}),
    'workbench/operators':Promise.resolve([]),
    'workbench/cases':delayedCases,
    'workbench/plans':Promise.resolve([]),
    'workbench/conversations':Promise.resolve([]),
    'workbench/executions':Promise.resolve([{id:'completed-case',name:'真实运行记录',status:'completed'}]),
  })[route];
  const refresh=vm.runInContext('refreshWorkbench()',context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(elements.get('wb-context').textContent,/'revision'|"revision": 15/);
  assert.match(elements.get('wb-execution').innerHTML,/真实运行记录/);
  releaseCases({templates:[],saved:[]});
  await refresh;
});
test('a fresh viewer restores the authenticated shared project before synchronizing its view',async()=>{
  const frame=elements.get('wb-map'),commands=[];
  frame.src='http://127.0.0.1:8810/accounts/123/viewer/';
  context.apiURL=path=>'/accounts/123/api/'+path;
  context.api=(route,body)=>{
    assert.equal(route,'workbench/map/sync');
    assert.deepEqual(JSON.parse(JSON.stringify(body.viewport.center)),[114.3,30.57]);
    return Promise.resolve({revision:16,layers:[],viewport:body.viewport});
  };
  frame.contentWindow={postMessage(message){
    commands.push(message);
    const result=message.type==='listLayers'?[]:message.type==='getViewport'?{center:[114.3,30.57],zoom:12}:{};
    queueMicrotask(()=>listeners.get('message')({source:frame.contentWindow,origin:'http://127.0.0.1:8810',data:{source:'geolibre',v:2,type:'ack',payload:{requestId:message.requestId,ok:true,result}}}));
  }};
  listeners.get('message')({source:frame.contentWindow,origin:'http://127.0.0.1:8810',data:{source:'geolibre',v:2,type:'ready'}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(commands.map(c=>c.type),['loadProject','listLayers','getViewport']);
  assert.equal(commands[0].payload.url,'http://127.0.0.1:8810/accounts/123/api/workbench/project');
  assert.ok(commands.every(c=>c.source==='geoharness'));
  assert.equal(elements.get('wb-map-status').textContent,'GeoLibre 已连接');
});
