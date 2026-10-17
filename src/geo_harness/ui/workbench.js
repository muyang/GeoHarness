'use strict';
// GeoLibre's documented embed protocol drives the actual viewer, with origin/source checks.
let wbContext, wbOperators=[], wbJobs=[], wbJob='', wbCases, wbDescription, wbReady=false;
let wbConversation='',wbPlanRows=[],wbChatting=false;
const wbFrame=$('wb-map'), wbPending=new Map();
const wbStatus={queued:'已排队',running:'运行中',completed:'已完成',failed:'失败',interrupted:'已停止等待'};
const wbLabels={input:'输入图层',input1:'第一输入',input2:'第二输入',inputs:'输入图层列表',polygons:'裁剪多边形',base:'对齐参考栅格',distance:'缓冲距离',units:'单位',z_factor:'高程换算系数',stat_type:'统计方法',features:'分区栅格',index:'遥感指数',red:'红光波段编号',nir:'近红外波段编号',method:'处理方法',cell_size:'目标像元大小',epsg:'目标 EPSG',field:'属性字段',mode:'执行方式'};
const wbEndpoint=path=>apiURL('workbench/'+path);
const wbOrigin=()=>new URL(wbFrame.src || location.href).origin;

function workbenchProject(project){
 // Only the basemap presentation changes; retain the account's layers, camera and preferences.
 const platform=location.pathname.startsWith('/api/workbench/runtime/') && new URLSearchParams(location.search).get('surface')==='platform';
 return {...project,basemapStyleUrl:new URL(platform?'/basemap-local/geo-dark.json':'/ui/basemap-local/geo-dark.json',location.origin).href};
}

function nativeCommand(method,params={}){
 return new Promise((resolve,reject)=>{if(!wbReady||!wbFrame.contentWindow)return reject(new Error('GeoLibre 正在加载，请稍后重试。'));const id=crypto.randomUUID(),timer=setTimeout(()=>{wbPending.delete(id);reject(new Error('查看器尚未确认地图操作。'));},30000);wbPending.set(id,{resolve,reject,timer});wbFrame.contentWindow.postMessage({type:['setProjection','getProjection'].includes(method)?'geonexus:projection':'geolibre:command',method,params,requestId:id},wbOrigin());});
}
async function viewerCommand(command){
 const params=command.payload||{};
 if(command.type==='loadProject'){
  const url=new URL(params.url,location.origin);if(url.origin!==location.origin||!url.pathname.startsWith('/api/')&&!url.pathname.startsWith('/accounts/'))throw new Error('项目地址须来自当前账号接口');
  const response=await fetch(url.href);if(!response.ok)throw new Error('项目读取失败（'+response.status+'）');const project=workbenchProject(await response.json()),seq=++wbProjectSeq;
  return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{wbPending.delete(seq);reject(new Error('GeoLibre 项目加载等待超时'));},30000);wbPending.set(seq,{resolve,reject,timer,project:true});wbFrame.contentWindow.postMessage({type:'geolibre:load-project',project,seq,trustedWidget:true},wbOrigin());wbFrame.contentWindow.postMessage({type:'geolibre:request-state'},wbOrigin());});
 }
 if(command.type==='setView'&&params.bbox)return nativeCommand('fitBounds',{bounds:params.bbox});
 return nativeCommand(({getViewport:'getView',setLayerVisibility:'setVisibility'})[command.type]||command.type,params);
}
function normalizeViewerViewport(viewport){
  const view={...viewport},longitude=n=>n>=-180&&n<=180?n:((n+180)%360+360)%360-180,latitude=n=>Math.max(-90,Math.min(90,n));
  if(Array.isArray(view.center)&&view.center.length===2&&view.center.every(Number.isFinite))view.center=[longitude(view.center[0]),latitude(view.center[1])];
  if(Array.isArray(view.bbox)&&view.bbox.length===4&&view.bbox.every(Number.isFinite)){
    const [west,south,east,north]=view.bbox;
    // Wrapped world copies use WGS84 longitudes; west > east denotes a dateline crossing.
    view.bbox=Math.abs(east-west)>=360?[-180,latitude(south),180,latitude(north)]:[longitude(west),latitude(south),longitude(east),latitude(north)];
  }
  return view;
}
async function mapSync(viewport){
  if(!wbReady)return;
  try{const layers=await viewerCommand({type:'listLayers'});const view=normalizeViewerViewport(viewport||await viewerCommand({type:'getViewport'}));wbContext=await api('workbench/map/sync',{viewport:view,layers});renderMapContext();$('wb-map-status').textContent='GeoLibre 已连接';}catch(e){$('wb-map-status').textContent=e.message;}
}
window.addEventListener('message',event=>{
  if(event.source!==wbFrame.contentWindow||event.origin!==wbOrigin())return;
  const data=event.data;if(!data||typeof data!=='object')return;
  if(data.type==='geonexus:projection-state'){setProjectionButtons(data.projection);return;}
  if(['geolibre:result','geonexus:projection-result'].includes(data.type)){
   const pending=wbPending.get(data.requestId);if(!pending)return;clearTimeout(pending.timer);wbPending.delete(data.requestId);data.ok?pending.resolve(data.value):pending.reject(new Error(data.error||'地图动作未完成。'));
  }else if(data.type==='geolibre:ready'&&!wbReady){
   wbReady=true;$('wb-map-status').textContent='正在恢复共享地图…';viewerCommand({type:'loadProject',payload:{url:location.origin+wbEndpoint('project')}}).then(()=>mapSync()).catch(e=>{$('wb-map-status').textContent=e.message;});
  }else if(data.type==='geolibre:state'){
   const pending=wbPending.get(data.seq);if(pending){clearTimeout(pending.timer);wbPending.delete(data.seq);pending.resolve(data.project);}clearTimeout(wbSyncTimer);wbSyncTimer=setTimeout(()=>mapSync(),300);
  }else if(data.type==='geolibre:error'){
   for(const [id,p]of wbPending)if(p.project){clearTimeout(p.timer);wbPending.delete(id);p.reject(new Error(data.message));}
  }else if(data.type==='geolibre:event'&&data.event==='selection-change')api('workbench/map/sync',{selection:data.payload}).then(context=>{wbContext=context;renderMapContext();}).catch(e=>toast(e.message));
});
let wbSyncTimer,wbProjectSeq=0;

function setProjectionButtons(projection){for(const id of ['wb-2d','wb-3d']){const button=$(id);button?.setAttribute?.('aria-pressed',String(projection===(id==='wb-2d'?'mercator':'globe')));}}
for(const [id,projection] of [['wb-2d','mercator'],['wb-3d','globe']])$(id).onclick=()=>action($(id),()=>mapAction('view.projection',{projection}));
$('wb-asia').onclick=()=>action($('wb-asia'),()=>mapAction('view.set',{center:[125,25],zoom:2.6}));

function renderMapContext(){
  if(!wbContext)return;setProjectionButtons(wbContext.projection);$('wb-context').textContent=JSON.stringify(wbContext,null,2);
  $('wb-layers').innerHTML=wbContext.layers.map(layer=>`<label class="wb-layer"><input type="checkbox" data-layer="${esc(layer.id)}" ${layer.visible?'checked':''}><span>${esc(layer.name)}</span><small>${esc(layer.type)}</small></label>`).join('')||'<span class="muted">运行案例或工具后，成果图层会出现在这里。</span>';
  $('wb-layers').querySelectorAll('[data-layer]').forEach(input=>input.onchange=()=>mapAction('layer.visibility',{layer_id:input.dataset.layer,visible:input.checked}).catch(e=>toast(e.message)));
}
async function applyMapAction(action){
  let ok=true,error='';
  try{for(const command of action.commands)await viewerCommand(command);}catch(e){ok=false;error=e.message;}
  await api('workbench/map/ack/'+action.id,{ok,error});
  wbContext=await api('workbench/context');renderMapContext();
  if(ok)await mapSync();else throw new Error(error);
}
async function mapAction(action,args){
  wbContext=await api('workbench/context');
  const result=await api('workbench/action',{action,arguments:args,expected_revision:wbContext.revision});
  await applyMapAction(result);return result;
}
async function openJobResult(){
  const job=wbJobs.find(j=>j.id===wbJob);if(!job?.result_id)return;
  await mapAction('result.open',{result_id:job.result_id});
  $('wb-map').scrollIntoView({behavior:'smooth',block:'center'});
}
function artifactOptions(){
  const pairs=[];for(const j of wbJobs.filter(j=>j.status==='completed'))for(const [name,ref] of Object.entries(j.artifacts||{}))if(typeof ref==='string')pairs.push({name:j.name+' · '+name,ref});return pairs;
}
function renderOperatorFields(){
  const schema=wbDescription?.input_schema||{},options=artifactOptions();
  $('wb-schema').textContent=JSON.stringify(schema,null,2);
  $('wb-fields').innerHTML=Object.entries(schema.properties||{}).map(([name,p])=>{
    const title=p.title||wbLabels[name]||name,required=(schema.required||[]).includes(name);
    let field;
    if(p.enum)field=`<select data-parameter="${esc(name)}">${p.enum.map(v=>`<option value="${esc(v)}" ${v===p.default?'selected':''}>${esc(v)}</option>`).join('')}</select>`;
    else if(p.type==='boolean')field=`<input type="checkbox" data-parameter="${esc(name)}" ${p.default?'checked':''}>`;
    else if(p.type==='number'||p.type==='integer')field=`<input type="number" data-parameter="${esc(name)}" ${p.minimum!==undefined?'min="'+esc(p.minimum)+'"':''} ${p.maximum!==undefined?'max="'+esc(p.maximum)+'"':''} step="${p.type==='integer'?'1':'any'}" value="${esc(p.default??'')}">`;
    else if(p.type==='array'||p.type==='object')field=`<textarea data-parameter="${esc(name)}" rows="2" placeholder="${p.type==='array'?'选择或填写输入引用列表':'按契约填写参数'}">${esc(p.default!==undefined?JSON.stringify(p.default):'')}</textarea>`;
    else if(p.pattern?.includes('artifact')||p.description?.includes('artifact:'))field=`<select data-parameter="${esc(name)}"><option value="">选择已上传输入或已完成成果</option>${options.map(o=>`<option value="${esc(o.ref)}">${esc(o.name)}</option>`).join('')}</select>`;
    else field=`<input data-parameter="${esc(name)}" value="${esc(p.default??'')}">`;
    return `<label class="field">${esc(title)}${required?' *':''}${field}<small>${esc(p.description||'')}</small></label>`;
  }).join('')||'<p class="muted">该能力使用固定、可复现的案例输入。</p>';
}
function operatorArguments(){
  const args={},schema=wbDescription.input_schema;
  for(const input of $('wb-fields').querySelectorAll('[data-parameter]')){
    const name=input.dataset.parameter,p=schema.properties[name],value=input.type==='checkbox'?input.checked:input.value;
    if(value===''&&!(schema.required||[]).includes(name))continue;
    args[name]=p.type==='boolean'?value:p.type==='number'||p.type==='integer'?Number(value):p.type==='array'||p.type==='object'?JSON.parse(value):value;
  }
  return args;
}
async function selectOperator(){
  const id=$('wb-operator').value;wbDescription=id?await api('workbench/operators/'+encodeURIComponent(id)):null;
  $('wb-operator-info').textContent=wbDescription?wbDescription.description:'在产品市场安装并启用能力后，可以在此配置。';renderOperatorFields();
}
async function installRows(rows){
  for(const row of rows)await api('resource-catalog/'+encodeURIComponent(row.id)+'/install',{granted:row.permissions});
  await reload();await refreshWorkbench();
}
async function prepareCase(productId){
  const catalogue=await api('resource-catalog');resourceCatalog=catalogue.items;
  const chosen=resourceCatalog.find(e=>e.id===productId);if(!chosen)throw new Error('案例已撤回，请刷新目录。');
  const control=resourceCatalog.filter(e=>e.node_ref===chosen.node_ref && /job[._-]?status/i.test(e.state?.tool||''));
  const rows=[chosen,...control].filter(e=>!state.catalog.find(p=>p.id===e.id)?.installed?.enabled);
  if(rows.length)await installRows(rows);
  if(!state.catalog.find(p=>p.id==='org.geonexus.geolibre')?.installed?.enabled){const viewer=state.catalog.find(p=>p.id==='org.geonexus.geolibre');await api('products/org.geonexus.geolibre/install',{granted:viewer.permissions});await reload();}
  const description=await api('workbench/operators/'+encodeURIComponent(productId));
  const args={};for(const [n,p]of Object.entries(description.input_schema.properties||{}))if(p.default!==undefined)args[n]=p.default;
  if(description.input_schema.properties?.mode)args.mode='submit';
  const job=await api('workbench/executions',{product_id:productId,arguments:args,expected_digest:description.digest,authorized:true});wbJob=job.id;await refreshJobs();
}
function renderCases(){
  $('wb-case-list').innerHTML=(wbCases?.templates||[]).map(c=>`<article class="wb-case"><span class="badge green">真实公开数据</span><h3>${esc(c.name)}</h3><p>${esc(c.description)}</p><label class="checkbox"><input type="checkbox" data-case-approve="${esc(c.product_id)}">授权启用案例、任务查询与本机地图，并在声明节点运行</label><button data-case-run="${esc(c.product_id)}">${c.installed?'运行案例 →':'启用并运行 →'}</button></article>`).join('')||'<p class="muted">尚未发现真实案例。请检查 Platform 节点目录与调用权限。</p>';
  $('wb-case-list').querySelectorAll('[data-case-run]').forEach(b=>b.onclick=()=>action(b,async()=>{if(!$('wb-case-list').querySelector(`[data-case-approve="${b.dataset.caseRun}"]`).checked)throw new Error('请先授权本次案例。');await prepareCase(b.dataset.caseRun);}));
  $('wb-saved-cases').innerHTML=(wbCases?.saved||[]).map(c=>`<article class="wb-saved-case"><div><strong>${esc(c.name)}</strong><small>${esc(new Date(c.created_at).toLocaleString())} · ${c.status==='replayable'?'可以重跑':'需重新提供输入'}</small></div><a download href="${esc(wbEndpoint('cases/'+c.id+'/export'))}">下载案例卡与流程</a>${c.status==='replayable'?`<button class="secondary compact" data-case-replay="${esc(c.id)}">重跑</button>`:''}</article>`).join('')||'<p class="muted">成功执行后，保存案例卡以复用方法和核验来源。</p>';
  $('wb-saved-cases').querySelectorAll('[data-case-replay]').forEach(b=>b.onclick=()=>action(b,async()=>{if(!$('wb-authorized').checked)throw new Error('请勾选本次执行授权。');const job=await api('workbench/cases/'+b.dataset.caseReplay+'/replay',{authorized:true});if(job.steps)await refreshPlans();else{wbJob=job.id;await refreshJobs();}}));
}
async function refreshJobs(){
  wbJobs=await api('workbench/executions');
  $('wb-execution').innerHTML=wbJobs.map(j=>`<option value="${esc(j.id)}">${esc(j.name)} · ${esc(wbStatus[j.status]||j.status)}</option>`).join('')||'<option value="">尚无记录</option>';
  if(!wbJobs.some(j=>j.id===wbJob))wbJob=wbJobs[0]?.id||'';$('wb-execution').value=wbJob;renderJob();
}
function renderJob(){
  const job=wbJobs.find(j=>j.id===wbJob);if(!job)return;
  $('wb-job-status').textContent=wbStatus[job.status]||job.status;
  const steps=job.node_steps?.length?job.node_steps:job.events;
  $('wb-events').innerHTML=(steps||[]).map((e,i)=>`<details class="wb-step"><summary><span>${i+1}</span>${esc(e.name||e.tool||e.step||wbStatus[e.status]||e.status||'处理步骤')}</summary><pre>${esc(JSON.stringify(e,null,2))}</pre></details>`).join('');
  const summary=job.result?.summary||{};
  const labels={title:'成果',estimated_population:'局部窗口估计人口（人）',valid_pixels:'有效像元',min:'最小值',max:'最大值',mean:'平均值',scope:'统计范围',datetime:'影像时间',unit:'数值单位',count:'数量'};
  const format=(key,value)=>typeof value==='number'?value.toLocaleString('zh-CN',{maximumFractionDigits:key==='estimated_population'?2:6}):key==='datetime'?String(value).slice(0,10):key==='unit'?(value==='persons/pixel'?'人 / 像元':value==='dimensionless NDVI'?'NDVI · 无量纲':value):value;
  const metrics=Object.entries(summary).filter(([k])=>k in labels);
  $('wb-result-summary').innerHTML=(job.error?`<p class="result-limitations">${esc(job.error)}</p>`:'')+`<div class="result-metrics">${metrics.map(([k,v])=>`<div><span>${esc(labels[k])}</span><strong>${esc(format(k,v))}</strong></div>`).join('')}</div>`+(Object.keys(summary).length?`<details class="wb-step"><summary>查看完整数值与技术元数据</summary><pre>${esc(JSON.stringify(summary,null,2))}</pre></details>`:'')+(job.result?.limitations?.length?'<div class="result-limitations"><strong>使用范围与限制</strong><ul>'+job.result.limitations.map(l=>`<li>${esc(l)}</li>`).join('')+'</ul></div>':'')+(job.result?.artifacts?.length?'<div class="downloads">'+job.result.artifacts.map(a=>`<a download href="${apiURL('resource-results/'+job.result_id+'/artifacts/'+encodeURIComponent(a.name))}">↓ ${esc(a.name)}</a>`).join('')+'</div>':'');
  $('wb-open-result').hidden=job.status!=='completed'||!job.result?.map_available;$('wb-save-case').hidden=job.status!=='completed';$('wb-stop').hidden=!['running','queued'].includes(job.status);
}
async function refreshWorkbench(){
  await Promise.all([
    api('workbench/context').then(context=>{wbContext=context;renderMapContext();}),
    api('workbench/operators').then(async ops=>{
      wbOperators=ops;const previous=$('wb-operator').value;
      $('wb-operator').innerHTML=ops.map(o=>`<option value="${esc(o.product_id)}">${esc(o.name)}</option>`).join('')||'<option value="">尚无已安装能力</option>';
      if(ops.some(o=>o.product_id===previous))$('wb-operator').value=previous;await selectOperator();
    }),
    api('workbench/cases').then(cases=>{wbCases=cases;renderCases();}),
    refreshJobs(),refreshPlans(),refreshConversations(false),
  ]);
}
$('wb-operator').onchange=()=>selectOperator().catch(e=>toast(e.message));
$('wb-execution').onchange=()=>{wbJob=$('wb-execution').value;renderJob();};
$('wb-refresh').onclick=()=>action($('wb-refresh'),async()=>{await api('resource-catalog');await refreshWorkbench();});
$('wb-undo').onclick=()=>action($('wb-undo'),()=>mapAction('undo',{}));
$('wb-open-result').onclick=()=>action($('wb-open-result'),openJobResult);
$('wb-fit').onclick=()=>action($('wb-fit'),async()=>{const job=wbJobs.find(j=>j.id===wbJob);if(job?.result_id)await openJobResult();else throw new Error('请先运行一个案例或工具。');});
$('wb-model-settings').onclick=()=>page('settings');
$('wb-link-account').onclick=()=>action($('wb-link-account'),async()=>{const data=await api('workbench/link-platform',{confirm:true});location.href=data.workspace_url;});
$('wb-run-operator').onclick=()=>action($('wb-run-operator'),async()=>{if(!$('wb-authorized').checked)throw new Error('请先授权本次计算。');if(!wbDescription)throw new Error('请安装一个能力产品。');const job=await api('workbench/executions',{product_id:wbDescription.product_id,arguments:operatorArguments(),expected_digest:wbDescription.digest,authorized:true});wbJob=job.id;await refreshJobs();});
$('wb-upload').onclick=()=>action($('wb-upload'),async()=>{
  if(!$('wb-authorized').checked)throw new Error('请先授权将输入交给节点。');const file=$('wb-input-file').files[0];if(!file||!wbDescription)throw new Error('请先选择工具和输入文件。');if(file.size>1024*1024)throw new Error('本轮输入上传最多1 MiB。');
  const bytes=new Uint8Array(await file.arrayBuffer());let text='';for(let i=0;i<bytes.length;i+=16384)text+=String.fromCharCode(...bytes.subarray(i,i+16384));
  const suffix=file.name.toLowerCase().endsWith('.geojson')?'.geojson':file.name.toLowerCase().endsWith('.json')?'.json':'.tif';
  const result=await api('workbench/inputs',{product_id:wbDescription.product_id,expected_digest:wbDescription.digest,name:'input-'+crypto.randomUUID().replaceAll('-','').slice(0,12)+suffix,original_name:file.name,content_base64:btoa(text),authorized:true});
  const ref=result.artifact_ref;$('wb-upload-status').textContent='输入已保存到声明节点，可用于本次计算。';
  for(const select of $('wb-fields').querySelectorAll('select[data-parameter]'))if(wbDescription.input_schema.properties[select.dataset.parameter].pattern?.includes('artifact')){const o=document.createElement('option');o.value=ref;o.textContent=file.name;select.append(o);if(!select.value)select.value=ref;}
});
$('wb-save-case').onclick=()=>action($('wb-save-case'),async()=>{const job=wbJobs.find(j=>j.id===wbJob);await api('workbench/cases/save',{execution_id:job.id,name:job.name+' · 我的案例'});wbCases=await api('workbench/cases');renderCases();toast('已保存案例卡、执行契约与来源记录。');});
$('wb-stop').onclick=()=>action($('wb-stop'),async()=>{const r=await api('workbench/executions/'+wbJob+'/stop',{});toast(r.notice);await refreshJobs();});
$('wb-install-tools').onclick=()=>action($('wb-install-tools'),async()=>{if(!$('wb-authorized').checked)throw new Error('请先勾选执行授权，再启用已审核工具。');const cat=await api('resource-catalog');resourceCatalog=cat.items;const rows=cat.items.filter(e=>e.geocard.id.startsWith('geolibre.skill.')&&e.state?.executable);if(!rows.length)throw new Error('尚未发现已审核 GeoLibre 工具。');await installRows(rows);toast('已启用 '+rows.length+' 项已审核工具。');});
const wbToolNames={map_context:'读取地图',map_action:'调整地图',operator_search:'发现能力',operator_describe:'读取产品契约',operator_execute:'提交计算',execution_status:'查看进度',workflow_plan:'组织任务计划',workflow_repair:'修正计划并复用上游',workflow_execute:'执行多步骤计划',workflow_status:'等待真实成果',workflow_case_save:'保存完整案例',case_list:'检索案例',case_save:'保存案例',product_search:'检索产品市场',knowledge_search:'检索知识证据'};
async function refreshConversations(restore){
 const rows=await api('workbench/conversations');
 $('wb-conversations').innerHTML='<option value="">新对话</option>'+rows.map(r=>`<option value="${esc(r.id)}">${esc(r.title||'对话记录')}</option>`).join('');
 if(!wbConversation&&restore&&rows.length)wbConversation=rows[0].id;
 $('wb-conversations').value=wbConversation;
 if(restore&&wbConversation){const r=await api('workbench/conversations/'+wbConversation);$('conversation').replaceChildren();for(const turn of r.turns||[]){message('user',turn.question);if(turn.answer)message('assistant',turn.answer);} }
}
$('wb-conversations').onchange=async()=>{if(wbChatting)return;wbConversation=$('wb-conversations').value;$('conversation').replaceChildren();if(wbConversation)await refreshConversations(true);};
$('wb-new-conversation').onclick=()=>{if(wbChatting)return;wbConversation='';$('wb-conversations').value='';$('conversation').replaceChildren();$('wb-chat-status').textContent='开始新的研究对话。';};
async function refreshPlans(){
 wbPlanRows=await api('workbench/plans');
 $('wb-plans').innerHTML=wbPlanRows.map(p=>`<article class="wb-plan"><h3>${esc(p.name)} <span class="badge">${esc(wbStatus[p.status]||({planned:'待执行',stopping:'正在停止'})[p.status]||p.status)}</span></h3><ol>${p.steps.map(s=>`<li>${esc(s.name)} · ${esc(wbStatus[s.status]||'待执行')}${s.depends_on.length?' · 依赖 '+s.depends_on.map(esc).join('、'):''}</li>`).join('')}</ol>${p.error?`<p class="result-limitations">${esc(p.error)}</p>`:''}<details><summary>查看步骤参数与来源版本</summary><pre>${esc(JSON.stringify(p.steps,null,2))}</pre></details><div class="button-row">${p.status==='planned'?`<button data-plan-run="${esc(p.id)}">按计划执行</button>`:''}${p.status==='completed'?`<button data-plan-map="${esc(p.id)}" class="secondary">查看最后成果地图</button><button data-plan-case="${esc(p.id)}">保存完整案例</button>`:''}${['running','queued'].includes(p.status)?`<button data-plan-stop="${esc(p.id)}" class="secondary">停止后续步骤</button>`:''}</div></article>`).join('');
 $('wb-plans').querySelectorAll('[data-plan-run]').forEach(b=>b.onclick=()=>action(b,async()=>{const p=wbPlanRows.find(p=>p.id===b.dataset.planRun);await api('workbench/plans/'+p.id+'/run',{authorized:true,expected_digest:p.digest});await refreshPlans();}));
 $('wb-plans').querySelectorAll('[data-plan-map]').forEach(b=>b.onclick=()=>action(b,async()=>{const p=wbPlanRows.find(p=>p.id===b.dataset.planMap);wbJob=p.steps.at(-1).execution_id;await refreshJobs();await openJobResult();}));
 $('wb-plans').querySelectorAll('[data-plan-case]').forEach(b=>b.onclick=()=>action(b,async()=>{const p=wbPlanRows.find(p=>p.id===b.dataset.planCase);await api('workbench/plans/'+p.id+'/case',{name:p.name+' · 完整案例'});await refreshWorkbench();toast('已保存全部步骤、依赖和来源版本。');}));
 $('wb-plans').querySelectorAll('[data-plan-stop]').forEach(b=>b.onclick=()=>action(b,async()=>{await api('workbench/plans/'+b.dataset.planStop+'/stop',{});await refreshPlans();}));
}
$('send-chat').onclick=()=>action($('send-chat'),async()=>{
 const text=$('prompt').value.trim();if(!text)return;
 state.settings=await api('settings');renderSettings();
 if(!state.settings.llm.enabled){page('settings');throw new Error('请先配置并启用自己的模型；真实案例可直接运行。');}
 wbChatting=true;$('wb-conversations').disabled=true;$('wb-new-conversation').disabled=true;
 $('conversation').querySelector('.welcome')?.remove();message('user',text);$('prompt').value='';await mapSync();let terminal=false;
 try{
  const response=await fetch(wbEndpoint('chat/stream'),{method:'POST',headers:{'Content-Type':'application/json','X-Geo-CSRF':csrf},body:JSON.stringify({message:text,conversation_id:wbConversation||undefined,allow_execution:$('allow-execution').checked})});
  if(!response.ok){const d=await response.json().catch(()=>({}));throw new Error(d.error||'对话连接失败，请重新打开当前账号工作台。');}
  const reader=response.body.getReader(),decoder=new TextDecoder();let pending='';
  const handle=async event=>{
   if(event.conversation_id)wbConversation=event.conversation_id;
   if(event.type==='thinking')$('wb-chat-status').textContent='模型正在理解任务与已有结果…';
   else if(event.type==='tool_started'){$('wb-chat-status').textContent=wbToolNames[event.tool]||'正在处理研究任务…';message('assistant',(wbToolNames[event.tool]||event.tool)+'…');}
   else if(event.type==='tool_result'){const node=document.createElement('details');node.className='wb-step';const summary=document.createElement('summary');summary.textContent=(event.status==='failed'?'未完成 · ':'步骤返回 · ')+(wbToolNames[event.tool]||event.tool);const pre=document.createElement('pre');pre.textContent=JSON.stringify({arguments:event.arguments,result:event.result},null,2);node.append(summary,pre);$('conversation').append(node);if(event.tool.startsWith('workflow_'))await refreshPlans();}
   else if(event.type==='map_command'){try{await applyMapAction(event.command);}catch(e){toast(e.message);}}
   else if(event.type==='done'){terminal=true;message('assistant',event.answer);$('wb-chat-status').textContent='本轮回复完成，可以继续追问。';}
   else if(event.type==='error'){terminal=true;message('assistant',event.error);$('wb-chat-status').textContent='本轮未完成，已有任务保留在执行计划中。';}
  };
  while(true){const {value,done}=await reader.read();pending+=decoder.decode(value||new Uint8Array(),{stream:!done});let i;while((i=pending.indexOf('\n'))>=0){const line=pending.slice(0,i);pending=pending.slice(i+1);if(line)await handle(JSON.parse(line));}if(done){if(pending.trim())await handle(JSON.parse(pending));break;}}
  if(!terminal)throw new Error('对话连接中断；已提交的任务仍可在计划中查看。');
 }catch(e){$('wb-chat-status').textContent=e.message;message('assistant',e.message);throw e;}
 finally{wbChatting=false;$('wb-conversations').disabled=false;$('wb-new-conversation').disabled=false;await refreshConversations(false);await refreshWorkbench();}
});
function updatePlatformLinks(){
  // The lightweight session can arrive before bootstrap has supplied Platform's URL.
  if(!state?.platform_url)return;
  document.querySelectorAll?.('[data-platform-path]').forEach(link=>{link.href=new URL(link.dataset.platformPath,state.platform_url).href;});
}
const wbInitialize=setInterval(()=>{if(!state||!csrf)return;clearInterval(wbInitialize);
  $('wb-account').textContent=state.account?.scoped?'当前账号的独立共享工作空间':'本机工作空间 · 关联 Platform 后，两种入口共享同一账号的地图与案例';$('wb-link-account').hidden=Boolean(state.account?.scoped);
  if(state.account?.scoped){$('platform-signin').disabled=true;$('platform-signin-status').textContent='身份由当前共享会话固定；请在主入口切换账号。';}
  updatePlatformLinks();
  wbFrame.src=location.pathname.startsWith('/api/workbench/runtime/') && new URLSearchParams(location.search).get('surface')==='platform' ? '/map/viewer?surface=workbench' : BASE+'ui/geo-viewer/index.html?maponly=1&embed=1&lang=zh&adapter=projection-0f18e9b7d65a';
  refreshWorkbench().then(()=>refreshConversations(true)).catch(e=>toast(e.message));
  setInterval(()=>{if(wbJobs.some(j=>['running','queued'].includes(j.status)))refreshJobs().catch(e=>toast(e.message));if(wbPlanRows.some(p=>['running','queued'].includes(p.status)))refreshPlans().catch(e=>toast(e.message));},1500);
},100);

window.addEventListener('geoharness-ready',()=>{updatePlatformLinks();refreshWorkbench().catch(e=>toast(e.message));});
