const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const path=require('node:path');
test('client viewer uses the same version-checked default renderer while retaining official asset imports',()=>{
 const root=path.join(__dirname,'../src/geo_harness/ui/geo-viewer');
 const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json'),'utf8'));
 const source=fs.readFileSync(path.join(root,manifest.adapter_module),'utf8');
 const sha=s=>require('node:crypto').createHash('sha256').update(s).digest('hex');
 assert.equal(sha(source),manifest.adapter_sha256);
 const restored=source.slice(source.indexOf('\n')+1).replaceAll('/viewer/assets/','./').replace('fr="maplibre-gl-raster",mr=','fr="cog-tiler-wasm",mr=');
 assert.equal(sha(restored),'f4bd9da339f5d11876b0cef617cc73494b1ce7a64c7e8b2d016fd0bae18cf8eb');
 const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
 const imports=JSON.parse(html.match(/<script type="importmap">(.*?)<\/script>/s)[1]).imports;
 assert.equal(imports['/viewer/assets/'+manifest.upstream_module],'/ui/geo-viewer/'+manifest.adapter_module);
});
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
test('official widget restores the scoped project, confirms state, then reads actual map context',async()=>{
 const frame=elements.get('wb-map'),commands=[],fetched=[];let projectSeq;
 frame.src='http://127.0.0.1:8810/accounts/123/viewer/';context.apiURL=path=>'/accounts/123/api/'+path;
 context.fetch=async url=>{fetched.push(url);return{ok:true,json:async()=>({version:'0.1.0',name:'Research',layers:[],mapView:{center:[114.3,30.57],zoom:12}})}};
 context.api=(route,body)=>{assert.equal(route,'workbench/map/sync');assert.deepEqual(JSON.parse(JSON.stringify(body.viewport.center)),[114.3,30.57]);return Promise.resolve({revision:16,layers:[],viewport:body.viewport})};
 frame.contentWindow={postMessage(message){commands.push(message);if(message.type==='geolibre:load-project'){projectSeq=message.seq;return}const data=message.type==='geolibre:request-state'?{type:'geolibre:state',seq:projectSeq,project:{layers:[]}}:{type:'geolibre:result',requestId:message.requestId,ok:true,value:message.method==='listLayers'?[]:{center:[114.3,30.57],zoom:12}};queueMicrotask(()=>listeners.get('message')({source:frame.contentWindow,origin:'http://127.0.0.1:8810',data}))}};
 listeners.get('message')({source:{},origin:'http://127.0.0.1:8810',data:{type:'geolibre:ready'}});assert.equal(commands.length,0);
 listeners.get('message')({source:frame.contentWindow,origin:'http://127.0.0.1:8810',data:{type:'geolibre:ready'}});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(fetched[0],'http://127.0.0.1:8810/accounts/123/api/workbench/project');assert.equal(commands[0].type,'geolibre:load-project');assert.equal(typeof commands[0].seq,'number');assert.equal(commands[1].type,'geolibre:request-state');assert.deepEqual(commands.slice(2).map(c=>c.method),['listLayers','getView']);assert.equal(elements.get('wb-map-status').textContent,'GeoLibre 已连接');
});
