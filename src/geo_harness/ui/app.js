'use strict';
const BASE = location.pathname.replace(/[^/]*$/, '');
const apiURL = path => BASE + 'api/' + path;
if (new URLSearchParams(location.search).get('embedded') === '1') document.body.classList.add('embedded');
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state, csrf, filter = '', selectedRun = '', pendingProduct, connectorProduct, viewerURL;
let resourceCatalog = [], resourceNodes = [], selectedResource, detailTab = '概览', discovery, resourceTab = 'installed';
let catalogReady = false, reloadPending;
const demoID = 'org.geonexus.synthetic-wetland';
let toastTimer, settingsDirty = false;
function toast(message) { $('toast').textContent = message; $('toast').style.display = 'block'; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').style.display = 'none', 7000); }
async function api(path, body) {
  const response = await fetch(apiURL(path), {method: body === undefined ? 'GET' : 'POST', headers: body === undefined ? {} : {'Content-Type':'application/json','X-Geo-CSRF':csrf}, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json(); if (!response.ok) { if(data.login_required && new URLSearchParams(location.search).get('surface')==='client') location.assign(data.login_url || '/login'); throw new Error(data.error || '请求失败'); } return data;
}
async function action(button, fn) { button.disabled = true; try { await fn(); } catch(error) { toast(error.message); } finally { button.disabled = false; } }
function resourcePane(name) {
  resourceTab = ['installed','nodes'].includes(name) ? name : 'installed';
  document.querySelectorAll('.resource-pane').forEach(el => el.hidden = el.id !== 'resource-' + resourceTab);
  document.querySelectorAll('[data-resource-tab]').forEach(el => { el.classList.toggle('active', el.dataset.resourceTab === resourceTab); el.setAttribute('aria-selected', String(el.dataset.resourceTab === resourceTab)); });
  location.hash = 'resources/' + resourceTab;
}
function page(name) {
  let pane;
  if (name === 'tools' || name === 'resources/tools') name = 'market';
  if (name.startsWith('resources/')) { pane = name.split('/')[1]; name = 'resources'; }
  if (!['workbench','market','register','resources','settings'].includes(name)) name = 'workbench';
  if(name==='market'){$('market-tools').hidden=true;$('products').hidden=false;}
  location.hash = name;
  document.querySelectorAll('.page').forEach(el => el.hidden = el.id !== name);
  document.querySelectorAll('nav button[data-page]').forEach(el => el.classList.toggle('active', el.dataset.page === name));
  $('breadcrumb').textContent = '工作空间 / ' + ({workbench:'工作台',market:'产品市场',register:'资源登记',resources:'我的资源',settings:'模型与设置'}[name]);
  if (name === 'resources') resourcePane(pane || resourceTab);
  if (name === 'settings' && state) { settingsDirty=false; api('session').then(data=>{state.settings=data.settings;state.llm_providers=data.providers;renderSettings();}).catch(error=>toast(error.message)); }
  if (state && ['market','resources','register'].includes(name)) ensureCatalog().catch(error=>toast(error.message));
}
document.querySelectorAll('[data-page]').forEach(el => el.onclick = () => page(el.dataset.page));
function renderSettings() {
  const config = state.settings.llm;
  $('llm-status').textContent = config.enabled ? config.model : 'LLM 未启用';
  $('chat-model').textContent = config.enabled ? config.model : '自选 LLM';
  if (settingsDirty) return;
  const providers = state.llm_providers || [];
  if (providers.length) $('provider').replaceChildren(...providers.map(p => { const option = document.createElement('option'); option.value = p.id; option.textContent = p.name; return option; }));
  $('llm-status').textContent = config.enabled ? config.model : 'LLM 未启用';
  $('chat-model').textContent = config.enabled ? config.model : '自选 LLM';
  $('llm-enabled').checked = config.enabled; $('provider').value = config.provider; $('base-url').value = config.base_url;
  $('model').value = config.model; $('temperature').value = config.temperature;
  $('key-state').textContent = config.api_key_configured ? '已设置（隐藏）' : '未设置'; $('viewer-url').value = state.settings.viewer_url;
  $('api-key').value = ''; $('clear-key').checked = false;
  $('provider-hint').textContent = providers.find(p=>p.id===config.provider)?.hint || '填写服务提供的准确模型 ID。';
  $('settings-scope').textContent = state.account?.scoped ? '此账号与 Platform 地图页及工作台共享同一份模型配置，密钥不会返回浏览器。' : '当前为本机独立设置；关联 Platform 账号后，在该账号的共享工作空间配置模型。';
  $('settings-account-panel').hidden = Boolean(state.account?.scoped);
  $('account-name').textContent = state.account?.scoped ? (state.account.name || state.account.principal) : '本机设置';
  $('account-logout').hidden = !state.account?.scoped || new URLSearchParams(location.search).get('surface')!=='client';
}
function localEntries() {
  return state.catalog.filter(p => !p.catalog_snapshot).map(p => {
    const card = state.catalog_cards?.[p.id]?.[0] || {id:p.id,name:p.name,description:p.description,type:p.kind,tags:[],license:p.license};
    const binding=state.cards.find(c=>c.product_id===p.id)?.binding || {};
    const typeMap = {case:'Solution',operator:'Skill',viewer:'Skill',plugin:'Skill'};
    return {...p,geocard:card,kind:({'org.geonexus.stac':'Data','org.geonexus.geokg':'Knowledge'})[p.id] || typeMap[p.kind] || (card.type || 'data').replace(/^./,x=>x.toUpperCase()),source_id:'local',source_name:'本地插件与已有产品',state:{tool:p.id.startsWith('local.sdgnode.real.')?binding.tool:undefined,input_schema:card['x-geonexus']?.input_schema,parameter_envelope:binding.tool==='geo_execute'?'params':undefined,executable:!!p.binding || p.id === demoID || p.id === 'org.geonexus.geolibre',mode:'Local'},local:true};
  });
}
function allEntries() { return [...resourceCatalog,...localEntries()]; }
function resourceNeedsUpdate(item) { if(item?.local){const p=state.catalog.find(p=>p.id===item.id);return !!(p?.installed && p.package_digest!==p.installed.digest);}const saved=state.cards.find(c=>c.product_id===item.id)?.binding?.contract_digest;return !!(saved && item.contract_digest && saved!==item.contract_digest); }
function resourceCard(item, installedView=false) {
  const card = item.geocard, live = item.state || {}, installed = state.catalog.find(p=>p.id===item.id)?.installed || item.installed;
  const canCall = live.executable && (item.local || live.tool);
  const status = item.id==='org.geonexus.geolibre'?'默认地图查看器':canCall ? '可调用' : live.executable ? 'Platform 工作台' : '目录描述';
  return `<article class="product-card resource-card"><button class="resource-open" data-detail="${esc(item.id)}" aria-label="查看 ${esc(card.name)} 详情"><div class="resource-thumbnail ${esc(card.type)}"><span>${item.kind==='Data'?'▦':item.kind==='Solution'?'⌘':'ƒ'}</span><em>${esc(live.mode==='Demo'?'Demo':live.synthetic?'合成案例':item.source_name)}</em></div><div class="resource-copy"><span class="resource-kind">${esc(item.kind)}</span><h3>${esc(card.name)}</h3><p>${esc(card.description)}</p><div class="resource-tags">${(card.tags||[]).slice(0,4).map(tag=>`<span>${esc(tag)}</span>`).join('')}</div><div class="product-meta"><span>${esc(card.spatial?.crs || '范围见契约')}</span><span>${esc(live.node_name || item.source_name)}</span><span>${status}</span></div></div></button><div class="product-actions"><button class="secondary" data-detail="${esc(item.id)}">查看详情</button><button data-install="${esc(item.id)}">${installed?.enabled?(resourceNeedsUpdate(item)?'更新安装':'已安装 · 使用'):'安装资源'}</button>${installed ? `<button class="secondary" data-disable="${esc(item.id)}">停用</button><button class="secondary" data-uninstall="${esc(item.id)}">卸载</button>${installed.history?.length?`<button class="secondary" data-rollback="${esc(item.id)}">回退版本</button>`:''}`:''}</div></article>`;
}
function attachResourceActions(root) {
  root.querySelectorAll('[data-detail]').forEach(el=>el.onclick=()=>showResource(el.dataset.detail));
  root.querySelectorAll('[data-install]').forEach(el=>el.onclick=()=> { const item=allEntries().find(i=>i.id===el.dataset.install) || installedEntry(el.dataset.install); const installed=state.catalog.find(p=>p.id===el.dataset.install)?.installed; if(installed?.enabled && !resourceNeedsUpdate(item)) {showResource(item.id);detailTab='预览与使用';renderDetail();} else installDialog(item.id); });
  ['disable','uninstall','rollback'].forEach(name=>root.querySelectorAll('[data-'+name+']').forEach(el=>el.onclick=()=>action(el,async()=>{await api(`products/${encodeURIComponent(el.dataset[name])}/${name}`,{});await reload();toast('资源状态已更新；已有运行结果保留。')})));
}
function renderProducts() {
  if(!state) return;
  const query = $('product-search').value.trim().toLowerCase(), source = $('catalog-source').value || 'platform';
  const entries = allEntries().filter(item => (source==='all' || item.source_id===source || (source==='platform' && item.id==='org.geonexus.geolibre')) && (!filter || item.kind===filter) && [item.geocard.id,item.name,item.description,...(item.geocard.tags||[])].join(' ').toLowerCase().includes(query));
  $('products').innerHTML = entries.map(item=>resourceCard(item)).join('') || '<div class="empty">没有符合筛选条件的资源。请检查来源或刷新节点目录。</div>';
  $('result-count').textContent = entries.length + ' 个结果';
  $('catalog-count').textContent = resourceNodes.find(n=>n.id==='platform')?.error ? 'Platform 目录未连接' : resourceCatalog.filter(i=>i.source_id==='platform').length + ' 个 Platform 已发布产品';
  const selectedNode=resourceNodes.find(n=>n.id===source);
  $('catalog-status').textContent = selectedNode?.error ? selectedNode.name+'：'+selectedNode.error : source==='local' ? '本地已配置插件与历史产品，独立于 Platform 已发布目录。' : '与 Platform 使用相同 GeoCard 名称、分类、标签及说明。安装目录快照不会下载整份数据。';
  attachResourceActions($('products'));
  $('case-install').textContent = state.catalog.find(item => item.id === demoID)?.installed?.enabled ? '案例已启用 · 执行经官方 MCP，固定版本已锁定' : '先在产品市场选择“本地插件与已有产品”，安装“四类资源 · 合成分类案例”。';
  renderCards();
}
let installedFilter='';
function renderCards() {
  if(!state){$('cards').textContent='正在读取已安装产品…';return;}
  const entries=state.catalog.filter(p=>p.installed?.enabled).map(p=>allEntries().find(i=>i.id===p.id) || installedEntry(p.id)).filter(Boolean).filter(p=>!installedFilter || p.kind===installedFilter);
  $('cards').innerHTML=entries.map(item=>resourceCard(item,true)).join('') || '<div class="empty">此类型尚无已安装产品。前往产品市场发现与安装。</div>';
  attachResourceActions($('cards'));
}
function installDialog(id) {
  pendingProduct = allEntries().find(item => item.id === id) || state.catalog.find(item=>item.id===id);
  $('permission-product').textContent = pendingProduct.name + ' · v' + pendingProduct.version;
  const names = {'workspace:artifacts':'在本地保存派生结果与复现记录','fixture:execute':'运行固定合成案例的算子与模型','viewer:network':'按用户操作加载已配置的地图 Viewer','connector:read':'连接已声明的能力节点并读取契约','connector:execute':'在用户明确授权后调用产品声明的工具','plugin:launch':'由 GeoHarness 启动应用内置的 MCP 插件服务'};
  $('permission-list').innerHTML = pendingProduct.permissions.map(p => `<label><input type="checkbox" value="${esc(p)}"> ${esc(names[p] || p)}</label>`).join('');
  $('permissions-dialog').showModal();
}
$('permission-cancel').onclick = () => $('permissions-dialog').close();
$('permission-approve').onclick = () => action($('permission-approve'), async () => { const granted = [...$('permission-list').querySelectorAll('input:checked')].map(el => el.value); await api(pendingProduct.local === false || pendingProduct.source_id && pendingProduct.source_id !== 'local' ? `resource-catalog/${encodeURIComponent(pendingProduct.id)}/install` : `products/${encodeURIComponent(pendingProduct.id)}/install`, {granted}); $('permissions-dialog').close(); await reload(); toast('产品已校验、安装并启用。'); });
$('product-search').oninput = renderProducts;
document.querySelectorAll('[data-filter]').forEach(el => el.onclick = () => { filter = el.dataset.filter; document.querySelectorAll('[data-filter]').forEach(e => e.classList.toggle('active', e === el)); renderProducts(); });
$('threshold').oninput = () => $('threshold-value').textContent = Number($('threshold').value).toFixed(2);
const params = () => ({threshold:Number($('threshold').value)});
$('plan-case').onclick = () => action($('plan-case'), async () => { const plan = await api('cases/plan',{params:params()}); $('plan-output').innerHTML = `<pre>${esc(plan.tasks.map(t => `${t.step} · ${t.kind} · ${t.declared_uses}\n参数 ${JSON.stringify(t.params)}`).join('\n\n'))}</pre>`; toast('参数校验通过；此操作只生成计划。'); });
$('run-case').onclick = () => action($('run-case'), async () => { const run = await api('runs',{params:params()}); selectedRun = run.id; await refreshRuns(); toast('运行已提交，正在执行节点上计算。'); });
const statuses = {queued:'已排队',running:'运行中',completed:'已完成',failed:'失败',cancel_requested:'请求停止',cancelled_before_next_step:'后续步骤已停止',completed_after_cancel_request:'当前步骤已完成',interrupted:'退出时中断'};
async function refreshRuns() {
  state.runs = await api('runs'); $('run-select').innerHTML = state.runs.map(r => `<option value="${esc(r.id)}">${esc(statuses[r.status] || r.status)} · ${esc(r.created_at.slice(11,19))} · ${esc(r.id.slice(0,8))}</option>`).join('') || '<option value="">尚无运行记录</option>';
  if (!selectedRun && state.runs.length) selectedRun = state.runs[0].id;
  $('run-select').value = selectedRun;
  await renderRun();
}
async function renderRun() {
  const run = state.runs.find(r => r.id === selectedRun); $('results-empty').hidden = Boolean(run); $('run-result').hidden = !run; if (!run) return;
  $('run-stats').innerHTML = [{label:'运行状态',value:statuses[run.status] || run.status},{label:'合成样本',value:run.summary?.count ?? '—'},{label:'正类 / 负类',value:run.summary ? `${run.summary.positive} / ${run.summary.negative}` : '—'},{label:'分类阈值',value:run.params.threshold}].map(s => `<div class="stat"><small>${esc(s.label)}</small><strong>${esc(s.value)}</strong></div>`).join('');
  $('run-events').innerHTML = run.events.map(e => `<div>${e.state === 'completed' ? '✓' : '◌'} ${esc(e.step)} · ${esc(e.state === 'completed' ? '已完成' : '执行中')}</div>`).join('') + (run.error ? `<p>${esc(run.error)}</p>` : '');
  $('downloads').innerHTML = (run.outputs || []).map(file => `<a href="${apiURL(`runs/${encodeURIComponent(run.id)}/files/${encodeURIComponent(file)}`)}" download>${esc(file)}</a>`).join('');
  $('cancel-run').hidden = !['queued','running'].includes(run.status); $('make-map').disabled = !run.outputs?.includes('classification.geojson');
  if (run.outputs?.includes('classification.geojson')) {
    const response = await fetch(apiURL(`runs/${run.id}/files/classification.geojson`)); const data = await response.json(); drawMap(data);
  } else { $('local-map').innerHTML = '<text x="340" y="145" text-anchor="middle" fill="#8198a1" font-size="13">执行完成后展示结果</text>'; }
}
function drawMap(data) {
  const points = data.features.map(item => `<circle cx="${45 + (item.geometry.coordinates[0] - 120) / .385 * 580}" cy="${248 - (item.geometry.coordinates[1] - 30) / .245 * 202}" r="7" fill="${item.properties.classification ? '#168b80' : '#d69a48'}" stroke="white" stroke-width="1.5"><title>点 ${esc(item.id)} · NDVI ${item.properties.ndvi.toFixed(3)} · 概率 ${item.properties.probability}</title></circle>`).join('');
  let grid = ''; for(let i = 0; i < 6; i++) grid += `<path d="M ${45+i*116} 30 V 248 M 45 ${46+i*40.4} H 625" stroke="#dce6e7" stroke-width="1"/>`;
  $('local-map').innerHTML = grid + points + '<text x="45" y="278" fill="#80979f" font-size="11">120.00°E</text><text x="570" y="278" fill="#80979f" font-size="11">120.39°E</text><text x="16" y="20" fill="#80979f" font-size="10">30.25°N</text>';
}
$('run-select').onchange = async () => { selectedRun = $('run-select').value; $('viewer').hidden = true; $('local-map').hidden = false; viewerURL = null; $('open-viewer').hidden = true; await renderRun(); };
$('refresh-runs').onclick = () => action($('refresh-runs'), refreshRuns);
$('cancel-run').onclick = () => action($('cancel-run'), async () => { await api(`runs/${selectedRun}/cancel`,{}); await refreshRuns(); toast('已请求停止后续步骤。当前节点调用可能继续。'); });
$('make-map').onclick = () => action($('make-map'), async () => { const data = await api(`runs/${selectedRun}/map`,{renderer:$('renderer').value}); viewerURL = data.viewer_url; $('open-viewer').hidden = false; await refreshRuns(); toast('已通过 GeoLibre MCP 生成真实地图项目。可下载项目或加载 Viewer。'); });
$('open-viewer').onclick = () => { if (viewerURL) { $('viewer').src = viewerURL; $('viewer').hidden = false; $('local-map').hidden = true; toast('正在加载配置的 Viewer；如外部服务限制本机数据，请下载项目在 GeoLibre 中打开。'); } };
function message(role, text) { const el = document.createElement('div'); el.className = 'message ' + role; const label = document.createElement('strong'); label.textContent = role === 'user' ? '你' : 'Geo 助手'; el.append(label);if(role==='assistant'){const body=document.createElement('div');body.className='assistant-text';renderAssistantText(body,text);el.append(body);}else el.append(document.createTextNode(text)); $('conversation').append(el); $('conversation').scrollTop = $('conversation').scrollHeight; }
$('send-chat').onclick = () => action($('send-chat'), async () => { const prompt = $('prompt').value.trim(); if (!prompt) return; if (!state.settings.llm.enabled) { page('settings'); throw new Error('请先配置并启用自己的 LLM，或直接运行确定性案例。'); } $('conversation').querySelector('.welcome')?.remove(); message('user',prompt); $('prompt').value = ''; const data = await api('chat',{message:prompt,allow_execution:$('allow-execution').checked}); message('assistant',data.answer); if (data.events.length) message('assistant','工具记录：' + data.events.map(e => e.tool).join(' → ')); await refreshRuns(); renderNodeProducts(); await renderPluginStatus(); });
document.querySelectorAll('[data-prompt]').forEach(el => el.onclick = () => { $('prompt').value = el.dataset.prompt; $('prompt').focus(); });
function modelDraft() { return {llm:{enabled:$('llm-enabled').checked,provider:$('provider').value,base_url:$('base-url').value.trim(),model:$('model').value.trim(),api_key:$('api-key').value,clear_api_key:$('clear-key').checked,temperature:Number($('temperature').value)}}; }
$('save-settings').onclick = () => action($('save-settings'), async () => { state.settings = await api('settings',modelDraft()); settingsDirty=false; renderSettings(); $('connection-status').textContent = '设置已保存，尚未验证连接。'; toast('模型设置已保存。'); });
$('test-settings').onclick = () => action($('test-settings'), async () => { $('connection-status').textContent = '正在测试当前填写的配置…'; try { const data = await api('settings/test',modelDraft()); $('connection-status').textContent = `连接成功 · ${data.model} · ${data.response || '已收到模型响应'}（当前配置尚未保存）`; } catch (error) { $('connection-status').textContent = '连接未通过 · ' + error.message; throw error; } });
$('settings-platform-login').onclick=()=>action($('settings-platform-login'),async()=>{try{await api('resource-nodes/platform/login',{email:$('settings-platform-email').value.trim(),password:$('settings-platform-password').value});const data=await api('workbench/link-platform',{confirm:true,import_local_model:$('settings-import-local-model').checked});location.href=data.workspace_url.replace('#workbench','#settings');}finally{$('settings-platform-password').value='';}});
$('settings-link-account').onclick = () => action($('settings-link-account'), async () => { const data=await api('workbench/link-platform',{confirm:true,import_local_model:$('settings-import-local-model').checked}); location.href=data.workspace_url.replace('#workbench','#settings'); });
window.addEventListener('focus',async()=>{if(!$('settings').hidden) return;try{const data=await api('session');state.settings=data.settings;renderSettings();}catch{}});
$('save-viewer').onclick = () => action($('save-viewer'), async () => { state.settings = await api('settings',{viewer_url:$('viewer-url').value.trim()}); toast('地图 Viewer 地址已保存。'); });
$('provider').onchange = () => { const preset=state.llm_providers?.find(p=>p.id===$('provider').value); if(preset){if(preset.base_url)$('base-url').value=preset.base_url;if(preset.model)$('model').value=preset.model;$('provider-hint').textContent=preset.hint;}$('connection-status').textContent='服务或参数已修改，请测试当前配置后保存。'; };

const samples = {
  data:{id:'example.dataset',name:'第三方数据样例',description:'示例元数据，实际地址和许可证需提供者核验。',access:{protocol:'https',endpoint:'https://example.org/data.geojson'},spatial:{crs:'EPSG:4326'},license:'CC-BY-4.0',provenance:{provider:'Example provider'},'x-geonexus':{revision:'1.0.0'}},
  operator:{id:'example.operator',name:'第三方 MCP 算子',description:'将工具契约登记为算子 GeoCard。',access:{protocol:'mcp',endpoint:'http://127.0.0.1:9000/mcp'},license:'MIT',provenance:{provider:'Example provider'},'x-geonexus':{revision:'1.0.0'},inputSchema:{type:'object',properties:{value:{type:'number'}},required:['value']},outputSchema:{type:'object',properties:{result:{type:'number'}}}},
  model:{id:'example.model',name:'第三方模型',description:'登记模型契约，不下载或迁移权重。',access:{protocol:'mcp',endpoint:'http://127.0.0.1:9000/mcp'},license:'Apache-2.0',provenance:{provider:'Example provider'},'x-geonexus':{revision:'1.0.0'},model_id:'example-model',runtime:{cpu:1,memory:'1Gi',gpu:'none'},input_schema:{type:'object',properties:{input_ref:{type:'string'}},required:['input_ref']},output_schema:{type:'object',properties:{output_ref:{type:'string'}}}},
  compute:{id:'example.compute',name:'第三方算力',description:'登记容量与执行后端，实时可用性另行探测。',access:{protocol:'mcp',endpoint:'http://127.0.0.1:9000/mcp'},license:'Provider-Terms',provenance:{provider:'Example provider'},'x-geonexus':{revision:'1.0.0'},runtime:{cpu:4,memory:'8Gi',gpu:'none'},backends:['python']}
};
$('sample-metadata').onclick = () => { $('metadata').value = JSON.stringify(samples[$('resource-kind').value],null,2); $('node-url').value = 'http://127.0.0.1:9000'; };
$('build-draft').onclick = () => action($('build-draft'), async () => { const metadata = JSON.parse($('metadata').value); if ($('license').value.trim()) metadata.license = metadata.license || $('license').value.trim(); if ($('provider').value.trim()) metadata.provenance = {...(metadata.provenance||{}), provider: (metadata.provenance&&metadata.provenance.provider) || $('provider').value.trim()}; if ($('revision').value.trim()) metadata['x-geonexus'] = {...(metadata['x-geonexus']||{}), revision: (metadata['x-geonexus']&&metadata['x-geonexus'].revision) || $('revision').value.trim()}; if ($('access-url').value.trim()) metadata.access = {...(metadata.access||{}), endpoint: (metadata.access&&metadata.access.endpoint) || $('access-url').value.trim(), protocol: (metadata.access&&metadata.access.protocol) || ($('access-url').value.trim().endsWith('/mcp') ? 'mcp' : new URL($('access-url').value.trim()).protocol.replace(':',''))}; const draft = await api('register/draft',{metadata,kind:$('resource-kind').value,operation:$('operation').value || undefined,node_url:$('node-url').value.trim()}); $('draft-empty').hidden = true; $('draft-result').hidden = false; $('draft-json').value = JSON.stringify(draft,null,2); $('validation-summary').className = draft.validation.valid ? 'validation-good' : 'validation-bad'; $('validation-summary').textContent = draft.validation.valid ? '✓ 契约校验通过，可登记或保存为本地产品。' : JSON.stringify(draft.validation,null,2); });
$('submit-draft').onclick = () => action($('submit-draft'), async () => { await api('register/submit',JSON.parse($('draft-json').value)); toast('已登记为 pending；需独立审核后公开。'); });
$('local-product').onclick = () => action($('local-product'), async () => { await api('register/local-product',JSON.parse($('draft-json').value)); await reload(); page('market'); toast('已保存本地资源产品，请查看权限并安装。'); });
$('save-connector').onclick = () => action($('save-connector'),async () => { await api('connections',{product_id:connectorProduct,api_key:$('connector-key').value}); $('connector-key').value = ''; toast('连接凭据已单独保存。'); });
$('connector-tools').onclick = () => action($('connector-tools'),async () => { const data = await api(`resources/${connectorProduct}/tools`,{}); $('connector-schema').textContent = JSON.stringify(data,null,2); $('connector-tool').replaceChildren(...data.map(tool => { const option = document.createElement('option'); option.value = tool.name; option.textContent = tool.name; return option; })); });
$('connector-call').onclick = () => action($('connector-call'),async () => { const data = await api(`resources/${connectorProduct}/call`,{tool:$('connector-tool').value || undefined,arguments:JSON.parse($('connector-args').value),confirm_execution:$('connector-confirm').checked}); $('connector-result').textContent = JSON.stringify(data,null,2);if(data._harness){await showProductResult(data._harness.id,$('connector-result-view'));await refreshProductResults();} });
function ensureCatalog() {
  if(catalogReady)return Promise.resolve();
  $('catalog-status').textContent='正在读取已审核产品目录，地图可继续使用…';
  return reload();
}
async function reload() {
  if (reloadPending) return reloadPending;
  const pending=(async()=>{
    const snapshot=await api('bootstrap');
    // A catalogue refresh must not overwrite newer model settings edited in this session.
    state={...snapshot,settings:state.settings};csrf=state.csrf;resourceNodes=state.resource_nodes||resourceNodes;
    renderResourceNodes();for(const id of ['discover-node','platform-signin','save-node-token'])$(id).disabled=id==='platform-signin' && Boolean(state.account?.scoped);
    renderProducts();renderSettings();renderNodeProducts();
    await Promise.all([renderPluginStatus(),refreshRuns(),loadResourceCatalog()]);
    catalogReady=true;renderProducts();window.dispatchEvent(new Event('geoharness-catalog-ready'));
  })();
  reloadPending=pending;
  try { await pending; } finally { if(reloadPending===pending)reloadPending=undefined; }
}
window.addEventListener('geoharness-map-ready',()=>ensureCatalog().catch(error=>toast(error.message)),{once:true});
initResourceUI();
page(location.hash.slice(1) || 'workbench');
(async()=>{
  const data=await api('session');csrf=data.csrf;
  state={settings:data.settings,account:data.account,llm_providers:data.providers,version:data.version,platform_url:data.platform_url,catalog:[],catalog_cards:{},cards:[],runs:[],plugins:[],resource_nodes:[],resource_results:[]};
  renderSettings();window.dispatchEvent(new Event('geoharness-ready'));
  const wanted=new URLSearchParams(location.search).get('product');
  if(wanted || ['market','resources','register'].includes(location.hash.slice(1).split('/')[0])) {
    await ensureCatalog();
    if(wanted){const entry=allEntries().find(x=>x.id===wanted || x.geocard.id===wanted);if(entry)$('catalog-source').value=entry.source_id;$('product-search').value=entry?.geocard.id || wanted;renderProducts();}
  }
})().catch(error=>toast(error.message));
setInterval(() => { if (state?.runs?.some(r => ['queued','running','cancel_requested'].includes(r.status))) refreshRuns().catch(error => toast(error.message)); }, 2000);

$('knowledge-search').onclick = () => action($('knowledge-search'), async () => {
  const result = await api('knowledge/query',{tool:'knowledge.search',arguments:{query:$('knowledge-query').value,limit:10}});
  $('knowledge-result').textContent = JSON.stringify(result,null,2);
});
$('knowledge-citations').onclick = () => action($('knowledge-citations'), async () => {
  const result = await api('knowledge/query',{tool:'knowledge.case_citations',arguments:{case_id:'case.flightway-wetland'}});
  $('knowledge-result').textContent = JSON.stringify(result,null,2);
});

function renderNodeProducts(){
  const installed=state.catalog.filter(p=>p.installed?.enabled);
  for (const [target,kind] of [['eo-product','data'],['qgis-product','operator']]){
    $(target).replaceChildren(...installed.filter(p=>p.kind===kind).map(p=>{const o=document.createElement('option');o.value=p.id;o.textContent=p.name;return o}));
    if(!$(target).options.length){const o=document.createElement('option');o.value='';o.textContent='先在产品市场安装对应产品';$(target).append(o)}
  }
}
async function renderPluginStatus(){
  const rows=await api('plugins');
  $('plugin-status').innerHTML=rows.filter(r=>!workspacePlugin || r.product_id===workspacePlugin).map(r=>`<div><strong>${esc(({ 'org.geonexus.geokg':'GeoKG 知识服务','org.geonexus.qgis':'QGIS 处理节点','org.geonexus.stac':'开放遥感数据连接器'})[r.product_id])}</strong><span>${r.installed?(r.status==='running'?'运行中':'已安装 · 未启动'):'尚未安装'}</span><button data-plugin="${esc(r.product_id)}" data-plugin-action="${r.status==='running'?'stop':'start'}" ${!r.installed?'disabled':''}>${r.status==='running'?'停止':'启动'}</button></div>`).join('');
  document.querySelectorAll('[data-plugin]').forEach(el=>el.onclick=()=>action(el,async()=>{await api(`plugins/${el.dataset.plugin}/${el.dataset.pluginAction}`,{});await renderPluginStatus()}));
}
const callResource=(id,tool,args)=>api(`resources/${encodeURIComponent(id)}/call`,{tool,arguments:args,confirm_execution:true});
let eoResult,eoQuery,qgisDetail,qgisRun,qgisTimer;
async function searchEO(cursor){
 const id=$('eo-product').value;if(!id)throw new Error('先安装开放遥感连接器及数据产品');
 const args={bbox:JSON.parse($('eo-bbox').value),datetime:$('eo-start').value+'T00:00:00Z/'+$('eo-end').value+'T00:00:00Z',limit:10};
 if($('eo-cloud').value!=='')args.cloud_cover=Number($('eo-cloud').value);
 if(cursor)args.cursor=cursor;eoQuery=args;
 eoResult=await callResource(id,'data.search',args);
 $('eo-next').hidden=!eoResult.next_cursor;
 $('eo-result').innerHTML=eoResult.items.map((x,i)=>`<article class="eo-item"><strong>${esc(x.id)}</strong><small>${esc(x.properties.datetime||x.properties.start_datetime)} · 云量 ${esc(x.properties['eo:cloud_cover']??'不适用')}</small><p>波段/资产：${esc(Object.keys(x.assets).join('、'))}</p><details><summary>资产元数据（质量、比例系数、访问条件）</summary><pre>${esc(JSON.stringify(x.assets,null,2))}</pre></details><button class="secondary" data-eo-lock="${i}">保存当前影像元数据锁</button><select id="eo-asset-${i}">${Object.keys(x.assets).map(k=>`<option value="${esc(k)}">${esc(k)}</option>`).join('')}</select><button class="secondary" data-eo-access="${i}">获取所选资产访问入口</button><div id="eo-access-${i}"></div></article>`).join('')||'<p>查询范围内没有影像；请调整时间或范围。</p>';
 document.querySelectorAll('[data-eo-lock]').forEach(el=>el.onclick=()=>action(el,async()=>{const x=eoResult.items[Number(el.dataset.eoLock)];const r=await callResource(id,'data.item_lock',{item_id:x.id});$('eo-lock').textContent=JSON.stringify(r,null,2)}));
 document.querySelectorAll('[data-eo-access]').forEach(el=>el.onclick=()=>action(el,async()=>{const i=Number(el.dataset.eoAccess),x=eoResult.items[i];const r=await callResource(id,'data.asset',{item_id:x.id,asset_key:$('eo-asset-'+i).value,sign:eoResult.provider==='planetary-computer'});const url=r.access_url||r.asset.href;if(/^https:\/\//.test(url))$('eo-access-'+i).innerHTML=`<a target="_blank" rel="noopener noreferrer" href="${esc(url)}">打开资产入口</a><small>${r.ephemeral?'此链接会过期，不写入元数据锁。':'访问与费用条件以数据来源为准。'}</small>`;else $('eo-access-'+i).textContent='此资产通过 '+url.split(':')[0]+' 协议提供，请使用数据源支持的客户端。';}));
}
$('eo-search').onclick=()=>action($('eo-search'),()=>searchEO());$('eo-next').onclick=()=>action($('eo-next'),()=>searchEO(eoResult.next_cursor));
$('qgis-discover').onclick=()=>action($('qgis-discover'),async()=>{const r=await api('nodes/qgis/catalog-refresh',{});$('qgis-state').textContent=r.available?`节点已发现 ${r.updated} 个 Processing 算子；新增描述可在市场安装。`:r.reason;await reload()});
$('qgis-describe').onclick=()=>action($('qgis-describe'),async()=>{
 const id=$('qgis-product').value;if(!id)throw new Error('先安装 QGIS 处理节点及一个算子');
 qgisDetail=await callResource(id,'qgis.describe',{});$('qgis-state').textContent=qgisDetail.execution_supported?'真实参数已取得，填写输入并确认计算。':'已取得描述；此算法需要额外的节点执行策略。';
 const defaults={};$('qgis-fields').replaceChildren();
 for(const [name,p] of Object.entries(qgisDetail.input_schema.properties)){
  if(p.default!==undefined)defaults[name]=p.default;
  const label=document.createElement('label');label.className='field';label.textContent=p.title+' · '+name+(qgisDetail.input_schema.required.includes(name)?' *':'');
  let input;
  if(p.enum){input=document.createElement('select');const empty=document.createElement('option');empty.value='';empty.textContent='请选择';input.append(empty);for(const value of p.enum){const option=document.createElement('option');option.value=String(value);option.textContent=p['x-qgis-definition']?.available_options?.[value]||String(value);input.append(option)}}
  else {input=document.createElement('input');input.type=p.type==='boolean'?'checkbox':['number','integer'].includes(p.type)?'number':'text';if(input.type==='number')input.step=p.type==='integer'?'1':'any'}
  input.dataset.qgisName=name;input.dataset.qgisType=p.type||'json';if(p.default!==undefined){if(input.type==='checkbox')input.checked=p.default;else input.value=typeof p.default==='object'?JSON.stringify(p.default):p.default}
  input.oninput=()=>{let values=JSON.parse($('qgis-inputs').value);if(input.value==='')delete values[name];else values[name]=input.type==='checkbox'?input.checked: ['number','integer'].includes(p.type)?Number(input.value):p.enum?Number(input.value):p.type==='array'||!p.type?JSON.parse(input.value):input.value;$('qgis-inputs').value=JSON.stringify(values,null,2)};
  label.append(input);$('qgis-fields').append(label)
 }
 $('qgis-inputs').value=JSON.stringify(defaults,null,2);$('qgis-run').disabled=!qgisDetail.execution_supported;
});
$('qgis-product').onchange=()=>{qgisDetail=null;$('qgis-fields').replaceChildren();$('qgis-run').disabled=true};
$('qgis-upload').onchange=()=>action($('qgis-upload'),async()=>{const file=$('qgis-upload').files[0];if(!file)return;if(file.size>1500000)throw new Error('GeoJSON 上传应小于 1.5 MiB');const r=await api('nodes/qgis/input',{geojson:JSON.parse(await file.text())});$('qgis-input-path').textContent='节点输入路径：'+r.path+'。将此路径填入对应 INPUT 字段。'});
async function pollQGIS(){
 if(!qgisRun)return;const r=await callResource($('qgis-product').value,'qgis.status',{run_id:qgisRun});$('qgis-result').textContent=JSON.stringify(r,null,2);
 $('qgis-cancel').hidden=!['queued','running'].includes(r.status);
 if(!['queued','running','cancel_requested'].includes(r.status)){
  clearInterval(qgisTimer);$('qgis-downloads').innerHTML=(r.outputs||[]).map(x=>`<a download href="${apiURL(`nodes/qgis/runs/${encodeURIComponent(r.id)}/files/${x.name.split('/').map(encodeURIComponent).join('/')}`)}">${esc(x.name)}</a>`).join(' · ');
 }
}
$('qgis-run').onclick=()=>action($('qgis-run'),async()=>{if(!$('qgis-confirm').checked)throw new Error('请确认本次 QGIS 执行');if(!qgisDetail)throw new Error('先读取真实参数');const r=await callResource($('qgis-product').value,'qgis.submit',{inputs:JSON.parse($('qgis-inputs').value),expected_contract:qgisDetail.contract_digest});qgisRun=r.id;clearInterval(qgisTimer);await pollQGIS();qgisTimer=setInterval(()=>pollQGIS().catch(e=>{clearInterval(qgisTimer);toast(e.message)}),2000)});
$('qgis-cancel').onclick=()=>action($('qgis-cancel'),async()=>{await callResource($('qgis-product').value,'qgis.cancel',{run_id:qgisRun});await pollQGIS()});

async function loadResourceCatalog() {
  try {
    const data = await api('resource-catalog'); resourceCatalog=data.items; resourceNodes=data.nodes;
  } catch(error) { resourceCatalog=[]; resourceNodes=await api('resource-nodes'); toast('资源目录读取失败：'+error.message); }
  const previous=$('catalog-source').value || 'platform';
  $('catalog-source').innerHTML=resourceNodes.map(n=>`<option value="${esc(n.id)}">${esc(n.name)}${n.protected?' · 默认节点':''}</option>`).join('')+'<option value="all">所有能力节点</option><option value="local">本地插件与已有产品</option>';
  $('catalog-source').value=[...$('catalog-source').options].some(o=>o.value===previous)?previous:'platform';
  renderResourceNodes();
}
function installedEntry(id) {
  const value=state.cards.find(c=>c.product_id===id), manifest=state.catalog.find(c=>c.id===id);
  if (!value) return undefined;
  return {id,geocard:value.card,name:value.card.name,description:value.card.description,source_id:value.binding?.source_id || 'local',source_name:resourceNodes.find(n=>n.id===value.binding?.source_id)?.name || '已安装快照',kind:(value.card.type||'data').replace(/^./,x=>x.toUpperCase()),local:!value.binding?.source_id,permissions:manifest?.permissions||[],version:value.version,state:{tool:value.binding?.tool,input_schema:value.binding?.input_schema,executable:!!value.binding?.tool}};
}
function showResource(id) {
  selectedResource=allEntries().find(p=>p.id===id) || installedEntry(id);
  if(!selectedResource){toast('资源已不在目录中，请刷新。');return;}
  detailTab='概览';renderDetail();$('resource-detail').showModal();
}
const jsonBlock=value=>`<pre>${esc(JSON.stringify(value ?? {},null,2))}</pre>`;
function renderDetail() {
  const item=selectedResource,card=item.geocard,live=item.state||{},installed=state.catalog.find(p=>p.id===item.id)?.installed;
  $('detail-kind').textContent=item.kind;$('detail-name').textContent=card.name;
  const tabs=['概览','时空范围','数据与模型契约','访问方式','关联资源','溯源','合规','预览与使用'];
  $('detail-tabs').innerHTML=tabs.map(t=>`<button role="tab" aria-selected="${detailTab===t}" data-detail-tab="${t}" class="${detailTab===t?'active':''}">${t}</button>`).join('');
  $('detail-tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>{detailTab=b.dataset.detailTab;renderDetail();});
  let html='';
  if(detailTab==='概览') html=`<p>${esc(card.description)}</p><div class="resource-tags">${(card.tags||[]).map(t=>`<span>${esc(t)}</span>`).join('')}</div><dl class="resource-summary"><dt>GeoCard</dt><dd>${esc(card.id)}</dd><dt>来源</dt><dd>${esc(live.node_name||item.source_name)}</dd><dt>调用状态</dt><dd>${item.id==='org.geonexus.geolibre'?'默认 GeoLibre 查看器':live.tool?'已接入执行工具':live.executable?(item.local?'本地插件 · 配置使用':'通过 Platform 工作台使用'):'目录描述 · 尚无可调用工具'}</dd><dt>安装</dt><dd>${installed?.enabled?'已安装并锁定内容摘要':'尚未安装'}</dd></dl><details><summary>静态 GeoCard 完整说明</summary>${jsonBlock(card)}</details>`;
  if(detailTab==='时空范围') html=`<p>坐标参考系：${esc(card.spatial?.crs||'未声明')}</p><p>空间范围：${esc(card.spatial?.bbox?.join(', ')||'未声明')}</p><p>时间：${esc(card.temporal?.start||'未声明')} — ${esc(card.temporal?.end||'未声明')}</p>${jsonBlock({spatial:card.spatial,temporal:card.temporal})}`;
  if(detailTab==='数据与模型契约') html=`<p>数据波段、输入、输出与运行输入契约分别列出。</p>${jsonBlock({bands:card.bands,inputs:card.inputs,outputs:card.outputs,input_schema:live.input_schema})}`;
  if(detailTab==='访问方式') html=`<p>${item.source_id==='platform'?'Platform 身份网关 → 已登记的执行节点':item.local?'本地已安装插件 / MCP 服务绑定':'GeoHarness → 已配置的 GeoNode 能力服务'}</p><p>源数据入口：${esc(card.access?.endpoint||'由组成资源声明')}</p><p>计算在能力节点执行；安装仅保存卡片与服务绑定。</p>${item.source_id==='platform'?'<p>调用需配置 Platform Token，并具有相应权限。</p>':''}`;
  if(detailTab==='关联资源') html=jsonBlock({composition:card.composition,knowledge_refs:card.knowledge_refs,recipe_ref:card.recipe_ref});
  if(detailTab==='溯源') html=`<p>许可：${esc(typeof card.license==='object'?card.license.name:card.license)}</p>${jsonBlock(card.provenance)}<p>本地内容摘要：${esc(installed?.digest||item.contract_digest||'安装后记录')}</p>`;
  if(detailTab==='合规') html=jsonBlock(card.compliance);
  if(detailTab==='预览与使用') {
    if(resourceNeedsUpdate(item)) html='<p>节点契约已更新。请更新安装并重新确认权限，再使用新契约。</p>';
    else if(!installed?.enabled) html='<p>先安装资源并明确授权，再配置输入和执行。</p>';
    else if(item.local && !live.tool) html='<p>使用已安装产品原有的 MCP 或工具界面。</p><button id="open-existing-tool">打开资源工具</button>';
    else if(!live.tool) html=live.executable&&item.source_id==='platform'?'<p>此内置 Demo 使用 Platform 工作流。</p><a href="'+esc(resourceNodes.find(n=>n.id==='platform')?.endpoint||'http://127.0.0.1:3301')+'/workbench" target="_blank" rel="noopener">打开 Platform 工作台 ↗</a>':'<p>已安装 GeoCard 目录快照。此资源尚无可调用工具，不能直接执行。</p>';
    else html=`<p>${live.synthetic?'当前工具使用合成输入。':'当前能力的数据来源和范围以契约为准。'}计算留在节点。</p><div id="resource-input-fields" class="field-grid"></div><details><summary>完整调用参数</summary><textarea id="resource-input-json" rows="6" class="code-input">{}</textarea></details><label class="checkbox spaced"><input id="resource-confirm" type="checkbox">确认使用当前参数调用已安装资源</label><div class="button-row"><button id="resource-run">运行资源</button><button id="resource-credential" class="secondary">配置节点凭据</button></div><p id="resource-run-status" role="status"></p><div id="resource-result-view"></div>`;
  }
  $('detail-content').innerHTML=html;if(detailTab==='预览与使用' && installed?.enabled){const history=document.createElement('div');history.id='detail-result-history';$('detail-content').append(history);renderProductHistory(item.id,history);}
  $('detail-status').textContent=installed?.enabled?'已安装 · v'+installed.version:'安装保留固定快照与来源';
  $('detail-install').hidden=!!installed?.enabled && !resourceNeedsUpdate(item);$('detail-install').textContent=resourceNeedsUpdate(item)?'更新安装':'安装资源';$('detail-install').onclick=()=>{ $('resource-detail').close();installDialog(item.id); };
  $('detail-use').hidden=detailTab==='预览与使用';$('detail-use').onclick=()=>{detailTab='预览与使用';renderDetail();};
  if($('open-existing-tool')) $('open-existing-tool').onclick=()=>{
    $('resource-detail').close();
    if(item.id===demoID || item.id==='org.geonexus.geolibre') {page('workbench');$('product-results').scrollIntoView({behavior:'smooth'});}
    else if(item.id.startsWith('org.geonexus.data.') || item.id.startsWith('org.geonexus.qgis') || item.id==='org.geonexus.stac') openProductWorkspace(item);
    else { page('resources/installed');connectorProduct=item.id;$('connector-panel').hidden=false;$('connector-name').textContent=card.name;$('connector-key').value='';$('connector-schema').textContent='';$('connector-result').textContent='';$('connector-panel').scrollIntoView({behavior:'smooth'}); }
  };
  if($('resource-run')) {
    const schema=live.input_schema||{},defaults={};
    for(const [key,p] of Object.entries(schema.properties||{})) {
      if(p['x-internal'] || p.writeOnly) continue;
      if(p.default!==undefined || p.const!==undefined) defaults[key]=p.default??p.const;
      const label=document.createElement('label');label.className='field';label.textContent=(p.title||key)+(schema.required?.includes(key)?' *':'');
      let input;
      if(p.enum){input=document.createElement('select');const blank=document.createElement('option');blank.value='';blank.textContent='请选择';input.append(blank);p.enum.forEach(v=>{const o=document.createElement('option');o.value=JSON.stringify(v);o.textContent=String(v);input.append(o);});if(key in defaults) input.value=JSON.stringify(defaults[key]);}
      else {input=document.createElement('input');input.type=p.type==='boolean'?'checkbox':['integer','number'].includes(p.type)?'number':'text';if(input.type==='number'){input.step=p.type==='integer'?'1':'any';if(p.minimum!==undefined)input.min=p.minimum;if(p.maximum!==undefined)input.max=p.maximum;}if(key in defaults){if(input.type==='checkbox')input.checked=defaults[key];else input.value=typeof defaults[key]==='object'?JSON.stringify(defaults[key]):defaults[key];}}
      input.setAttribute('aria-label',p.title||key);if(p.const!==undefined) input.disabled=true;
      input.onchange=()=>{try {const args=JSON.parse($('resource-input-json').value);if(input.type==='checkbox')args[key]=input.checked;else if(input.value==='')delete args[key];else args[key]=p.enum?JSON.parse(input.value):['integer','number'].includes(p.type)?Number(input.value):['object','array'].includes(p.type)?JSON.parse(input.value):input.value;$('resource-input-json').value=JSON.stringify(args,null,2);}catch(error){toast('参数格式错误：'+error.message);}};
      label.append(input);$('resource-input-fields').append(label);
    }
    $('resource-input-json').value=JSON.stringify(defaults,null,2);
    $('resource-credential').onclick=()=>{$('resource-detail').close();if(item.local){page('resources/installed');connectorProduct=item.id;$('connector-panel').hidden=false;$('connector-name').textContent=card.name;$('connector-panel').scrollIntoView({behavior:'smooth'});return;}page('resources/nodes');$('credential-node').value=item.source_id;$('credential-node').onchange();($('credential-node').value==='platform'?$('platform-email'):$('node-token')).focus();};
    $('resource-run').onclick=()=>action($('resource-run'),async()=>{if(!$('resource-confirm').checked)throw new Error('请先确认本次资源调用。');$('resource-run-status').textContent='节点正在执行…';try{const result=await api(`resources/${encodeURIComponent(item.id)}/call`,{tool:live.tool,arguments:live.parameter_envelope?{[live.parameter_envelope]:JSON.parse($('resource-input-json').value)}:JSON.parse($('resource-input-json').value),confirm_execution:true});$('resource-run-status').textContent='结果已保存，可在地图或工作台中查看。';await showProductResult(result._harness.id,$('resource-result-view'));await refreshProductResults();await renderProductHistory(item.id,$('detail-result-history'));}catch(error){$('resource-run-status').textContent='调用未完成：'+error.message;throw error;}});
  }
}
function renderResourceNodes() {
  const credentialSelection=$('credential-node').value;
  $('node-list').innerHTML=resourceNodes.map(n=>`<article class="panel node-card"><div class="panel-title"><h2>${esc(n.name)}</h2><span class="badge ${n.protected?'green':''}">${n.protected?'默认 · 受保护':'第三方 GeoNode'}</span></div><p class="node-endpoint">${esc(n.endpoint)}</p><p>${esc(n.protocol)} · ${n.reachable?'目录连接正常':n.error?'连接未通过':'尚未读取'} · ${n.count??0} 个资源</p>${n.error?`<p class="node-error">${esc(n.error)}</p>`:''}${n.protected?'<p>默认 Platform 节点不可修改或删除。</p>':`<label class="field">显示名称<input id="rename-${esc(n.id)}" value="${esc(n.name)}"></label><div class="button-row"><button class="secondary" data-rename-node="${esc(n.id)}">保存名称</button><button class="secondary" data-remove-node="${esc(n.id)}">移除节点</button></div><small>更换服务入口需重新发现。移除保留安装快照，停止此节点调用。</small>`}</article>`).join('');
  $('credential-node').innerHTML=resourceNodes.map(n=>`<option value="${esc(n.id)}">${esc(n.name)} · ${n.credential_configured?'已设置凭据':'未设置凭据'}</option>`).join('');
  if(resourceNodes.some(n=>n.id===credentialSelection))$('credential-node').value=credentialSelection;
  $('platform-node-login').hidden=$('credential-node').value!=='platform';
  document.querySelectorAll('[data-rename-node]').forEach(b=>b.onclick=()=>action(b,async()=>{await api(`resource-nodes/${b.dataset.renameNode}/rename`,{name:$('rename-'+b.dataset.renameNode).value});await loadResourceCatalog();renderProducts();toast('节点名称已保存。');}));
  document.querySelectorAll('[data-remove-node]').forEach(b=>b.onclick=()=>action(b,async()=>{await api(`resource-nodes/${b.dataset.removeNode}/remove`,{});await loadResourceCatalog();renderProducts();toast('节点已移除；安装快照与运行结果保留。');}));
}
function initResourceUI() {
  for(const id of ['discover-node','platform-signin','save-node-token'])$(id).disabled=true;
  document.querySelectorAll('[data-resource-tab]').forEach(b=>b.onclick=()=>resourcePane(b.dataset.resourceTab));
  $('catalog-source').onchange=renderProducts;
  $('configure-nodes').onclick=()=>page('resources/nodes');
  $('refresh-catalog').onclick=()=>action($('refresh-catalog'),async()=>{await loadResourceCatalog();renderProducts();toast('目录已刷新。');});
  $('close-detail').onclick=()=>$('resource-detail').close();
  $('discover-node').onclick=()=>action($('discover-node'),async()=>{discovery=null;$('add-node').hidden=true;$('node-discovery').textContent='正在读取节点能力…';try{discovery=await api('resource-nodes/discover',{name:$('new-node-name').value,endpoint:$('new-node-endpoint').value,protocol:$('new-node-protocol').value});$('node-discovery').textContent=`已发现 ${discovery.count} 个公开 GeoCard，其中 ${discovery.executable_count} 个声明了调用工具。确认加入后可在市场筛选此节点。`;$('add-node').hidden=false;}catch(error){$('node-discovery').textContent='发现未通过：'+error.message;throw error;}});
  for(const id of ['new-node-name','new-node-endpoint','new-node-protocol']) $(id).oninput=()=>{discovery=null;$('add-node').hidden=true;};
  $('add-node').onclick=()=>action($('add-node'),async()=>{if(!discovery)throw new Error('请先发现节点。');await api('resource-nodes/add',{discovery_id:discovery.discovery_id});discovery=null;$('add-node').hidden=true;await loadResourceCatalog();renderProducts();$('node-discovery').textContent='节点已加入，可在产品市场选择此节点。';});
  $('credential-node').onchange=()=>{ $('platform-node-login').hidden=$('credential-node').value!=='platform';$('node-token').value='';$('clear-node-token').checked=false; };
  $('platform-signin').onclick=()=>action($('platform-signin'),async()=>{try{await api('resource-nodes/platform/login',{email:$('platform-email').value.trim(),password:$('platform-password').value});$('platform-password').value='';$('platform-signin-status').textContent='已登录 Platform；调用仍遵循账号权限。';resourceNodes=await api('resource-nodes');renderResourceNodes();}catch(error){$('platform-password').value='';$('platform-signin-status').textContent='登录未通过：'+error.message;throw error;}});
  $('save-node-token').onclick=()=>action($('save-node-token'),async()=>{await api(`resource-nodes/${$('credential-node').value}/credential`,{token:$('node-token').value,clear:$('clear-node-token').checked});$('node-token').value='';$('clear-node-token').checked=false;resourceNodes=await api('resource-nodes');renderResourceNodes();toast('节点调用凭据已单独保存。');});
}

let workspacePlugin;
function openProductWorkspace(item){
  page('market');$('catalog-source').value=item.source_id;filter=item.kind;$('product-search').value=item.geocard.id;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter===filter));renderProducts();$('market-tools').hidden=false;$('products').hidden=true;$('workspace-product-name').textContent=item.name;
  const eo=item.id.startsWith('org.geonexus.data.') || item.id==='org.geonexus.stac';
  $('eo-workspace').hidden=!eo;$('qgis-workspace').hidden=eo;workspacePlugin=eo?'org.geonexus.stac':'org.geonexus.qgis';
  if(eo && item.id.startsWith('org.geonexus.data.'))$('eo-product').value=item.id;
  if(!eo && item.id.startsWith('org.geonexus.qgis.'))$('qgis-product').value=item.id;
  renderPluginStatus().catch(e=>toast(e.message));$('market-tools').scrollIntoView({behavior:'smooth'});
}
$('close-product-workspace').onclick=()=>{$('market-tools').hidden=true;$('products').hidden=false;workspacePlugin=undefined;};
document.querySelectorAll('[data-installed-filter]').forEach(b=>b.onclick=()=>{installedFilter=b.dataset.installedFilter;document.querySelectorAll('[data-installed-filter]').forEach(e=>e.classList.toggle('active',e===b));renderCards();});

window.addEventListener('message',event=>{if(event.source!==window.parent || event.origin!==location.origin || event.data?.source!=='geonexus-platform' || event.data?.type!=='prefillPrompt')return;const text=event.data.message;if(typeof text==='string' && text.length<=10000){$('prompt').value=text;page('workbench');}});

for (const id of ['llm-enabled','provider','base-url','model','api-key','clear-key','temperature']) $(id).addEventListener('input',()=>{settingsDirty=true;$('connection-status').textContent='配置已修改，连接测试将使用当前填写值。';});

$('account-logout').onclick = () => action($('account-logout'), async () => { const session = await (await fetch('/api/session')).json(); const response = await fetch('/api/account/logout', {method:'POST',headers:{'Content-Type':'application/json','X-Geo-CSRF':session.csrf},body:'{}'}); if(!response.ok) throw new Error('退出未完成，请重试。'); location.replace('/login'); });
