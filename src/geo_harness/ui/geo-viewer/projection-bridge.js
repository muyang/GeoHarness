// GeoLibre 3.3.0 host adapter. The store module and its digest are pinned in manifest.json.
// Only the map projection preference changes; layers and temporary raster handles stay intact.
import {ut as store} from 'geonexus-geolibre-store';
document.documentElement.dataset.geoProjectionAdapter='ready';
store.subscribe((state,previous)=>{
  if(state.preferences.map.projection!==previous.preferences.map.projection&&window.parent!==window)
    window.parent.postMessage({type:'geonexus:projection-state',projection:state.preferences.map.projection},location.origin);
});
window.addEventListener('message',event=>{
  if(event.source!==window.parent||event.origin!==location.origin)return;
  const message=event.data;
  if(message?.type!=='geonexus:projection'||typeof message.requestId!=='string')return;
  document.documentElement.dataset.geoProjectionRequest=message.method;
  const reply=(ok,value,error)=>event.source.postMessage({type:'geonexus:projection-result',requestId:message.requestId,ok,value,error},event.origin);
  try{
    const state=store.getState(),projection=message.params?.projection;
    if(message.method==='setProjection'){
      if(!['globe','mercator'].includes(projection))throw new Error('请选择 2D 或 3D 地图');
      state.setPreferences({...state.preferences,map:{...state.preferences.map,projection}});
    }else if(message.method!=='getProjection')throw new Error('不支持的地图操作');
    // The native store accepts this synchronously. Hidden iframe animation frames
    // can pause indefinitely; acknowledge accepted state without waiting for paint.
    reply(true,{projection:store.getState().preferences.map.projection});
  }catch(error){reply(false,null,error.message)}
});
