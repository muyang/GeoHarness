'use strict';
let selectedProductResult='';
const resultBody=value=>{for(let n=0;n<3 && value && typeof value==='object';n++){if(value.outputs && !Array.isArray(value.outputs))return value.outputs;if(value.result && typeof value.result==='object')value=value.result;else return value;}return value||{};};
async function refreshProductResults(){
  const rows=await api('resource-results');
  $('product-result-select').innerHTML=rows.map(r=>`<option value="${esc(r.id)}">${esc(r.name)} · ${esc(new Date(r.created_at).toLocaleString())}</option>`).join('') || '<option value="">尚无产品运行结果</option>';
  if(!rows.some(r=>r.id===selectedProductResult))selectedProductResult=rows[0]?.id||'';
  $('product-result-select').value=selectedProductResult;
  if(!rows.length)$('workspace-result-view').innerHTML='<div class="empty"><h3>从产品市场安装并运行一个产品</h3><p>矢量边界、遥感栅格、人口数据与地理算子结果都会保存到此处。</p></div>';
}
async function renderProductHistory(id,host){
  try{const rows=await api('resource-results?product_id='+encodeURIComponent(id));if(!host.isConnected)return;
    host.innerHTML='<h3 class="spaced">已保存的产品结果</h3>'+(rows.length?'<div class="result-history">'+rows.slice(0,10).map(r=>`<button class="secondary" data-history-result="${esc(r.id)}">${esc(new Date(r.created_at).toLocaleString())} · ${r.map_available?'地图与结果':'结果记录'}</button>`).join('')+'</div><div class="history-result-view"></div>':'<p class="muted">首次运行后，可在此处或工作台重新打开结果。</p>');
    host.querySelectorAll('[data-history-result]').forEach(b=>b.onclick=()=>action(b,()=>showProductResult(b.dataset.historyResult,host.querySelector('.history-result-view'))));
  }catch(e){if(host.isConnected)host.textContent='结果历史读取失败：'+e.message;}
}
function resultTable(rows){
  if(!Array.isArray(rows)||!rows.length)return '';
  const keys=[...new Set(rows.flatMap(r=>Object.keys(r)))].slice(0,12);
  return '<div class="result-table"><table><thead><tr>'+keys.map(k=>`<th>${esc(k)}</th>`).join('')+'</tr></thead><tbody>'+rows.slice(0,100).map(r=>'<tr>'+keys.map(k=>`<td>${esc(typeof r[k]==='object'?JSON.stringify(r[k]):r[k])}</td>`).join('')+'</tr>').join('')+'</tbody></table></div>';
}
async function showProductResult(id,host){
  if(!host)return;host.innerHTML='<p class="muted" role="status">读取已保存结果…</p>';
  const data=await api('resource-results/'+id),r=data.record,value=resultBody(data.result);
  if(!host.isConnected)return;
  selectedProductResult=id;if($('product-result-select').querySelector(`option[value="${id}"]`))$('product-result-select').value=id;
  const summary=Object.entries(r.summary||{}).slice(0,10).map(([k,v])=>`<div><span>${esc(({region:'研究区域',width:'宽度（像元）',height:'高度（像元）',crs:'坐标参考系',bands:'波段',units:'单位',product:'OGE 产品',total_matching:'匹配影像',returned:'返回数量',operator:'算子',task_state:'任务状态',bbox:'地理范围',valid_pixels:'有效像元',city:'城市',features:'要素数',resolution_m:'分辨率（米）',shape:'网格尺寸',same_grid:'网格对齐',resampling:'重采样',transform:'仿射变换',mask_rule:'掩膜规则'})[k]||k)}</span><strong>${esc(typeof v==='object'?JSON.stringify(v):v)}</strong></div>`).join('');
  host.innerHTML=`<div class="product-result-card"><div class="panel-title"><h3>${esc(r.name)}</h3><span class="badge green">${r.synthetic===false?'真实结果':r.synthetic===true?'合成结果':'节点返回结果'}</span></div><p class="muted">${esc(new Date(r.created_at).toLocaleString())} · 已保存版本 ${esc(r.version)}${r.node_run_id?' · 节点结果 '+esc(r.node_run_id):''}</p><div class="result-metrics">${summary}</div>${value.task_state==='submitted'?'<p class="result-limitations">计算请求已提交，尚未确认完成；请用 OGE 任务查询核对最终状态。</p>':''}${value.provenance?.computation?'<p class="muted">'+esc(value.provenance.computation)+' · OGE 任务 '+esc(value.provenance.job_id)+'</p>':''}<div class="result-map-panel"><div class="panel-title"><strong>GeoLibre 地图</strong><span class="badge">默认查看器 · 本机</span></div><p class="map-status" role="status"></p><iframe class="product-map" title="GeoLibre 产品结果地图" referrerpolicy="no-referrer" hidden></iframe><div class="map-links"></div></div>${resultTable(value.statistics||value.records)}${r.limitations?.length?'<div class="result-limitations"><strong>使用范围与限制</strong><ul>'+r.limitations.map(x=>`<li>${esc(x)}</li>`).join('')+'</ul></div>':''}<div class="downloads">${r.artifacts.map(a=>`<a download href="${apiURL(`resource-results/${id}/artifacts/${encodeURIComponent(a.name)}`)}">↓ ${esc(a.name)}</a>`).join('')}</div><details><summary>来源与复现记录</summary>${jsonBlock({provenance:r.provenance,product_digest:r.digest,node_run_id:r.node_run_id,artifacts:r.artifacts})}</details><details><summary>完整返回结果</summary>${jsonBlock(data.result)}</details></div>`;
  const status=host.querySelector('.map-status'),frame=host.querySelector('iframe'),links=host.querySelector('.map-links');
  if(!r.map_available){status.textContent='本次返回没有可显示的地理要素。请查看上方结果和产物。';return;}
  const viewer=state.catalog.find(p=>p.id==='org.geonexus.geolibre');
  if(!viewer?.installed?.enabled){status.textContent='安装并启用 GeoLibre 公共产品后，即可在此查看地图。';const button=document.createElement('button');button.textContent='安装 GeoLibre';button.onclick=()=>{$('resource-detail').open && $('resource-detail').close();installDialog('org.geonexus.geolibre');};links.append(button);return;}
  status.textContent='正在校验地理产物并加载 GeoLibre…';
  try{const map=await api(`resource-results/${id}/map`,{});if(!host.isConnected)return;
    frame.src=map.viewer_url;frame.hidden=false;
    status.textContent=`${map.layers} 个地理图层 · GeoLibre ${map.viewer_version} · 可缩放、平移并查看要素。`;
    links.innerHTML=`<a target="_blank" rel="noopener" href="${esc(map.viewer_url)}">在独立窗口打开地图 ↗</a><a download="${esc(r.name)}.geolibre.json" href="${esc(map.project_url)}">下载 GeoLibre 项目</a>`;
  }catch(e){status.textContent='地图暂未生成：'+e.message;const button=document.createElement('button');button.textContent='重新加载地图';button.className='secondary';button.onclick=()=>action(button,()=>showProductResult(id,host));links.append(button);}
}
$('refresh-product-results').onclick=()=>action($('refresh-product-results'),async()=>{await refreshProductResults();if(selectedProductResult)await showProductResult(selectedProductResult,$('workspace-result-view'));});
$('product-result-select').onchange=()=>{selectedProductResult=$('product-result-select').value;if(selectedProductResult)showProductResult(selectedProductResult,$('workspace-result-view')).catch(e=>toast(e.message));};
// app.js initializes session state asynchronously; load history once it is ready.
const resultInit=setInterval(()=>{if(state?.catalog && csrf){clearInterval(resultInit);refreshProductResults().catch(e=>toast(e.message));}},100);
