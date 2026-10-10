/** 渲染器插件平面：地图引擎不是写死的，是注册进来的。
 *
 *  一个渲染器 = { id, name, dims:'2d'|'3d', create(container, opts) → 实例 }。
 *  实例契约（MapView 只依赖这四件事）：
 *    renderGeoJSON(featureCollection, {name,color}) → layerId
 *    fit(bbox)         // [w,s,e,n]
 *    clear()           // 清掉所有业务图层
 *    destroy()
 *  内置两个：MapLibre（2D，npm 依赖）与 Cesium（3D，动态 import，未安装时报得清楚）。
 *  W4 嵌入平台后，平台可继续注册自己的渲染器 —— 接口不变。
 */

const registry = new Map()

export function registerRenderer(def) {
  if (!def?.id || typeof def.create !== 'function') {
    throw new Error('渲染器必须有 id 和 create(container, opts)')
  }
  registry.set(def.id, def)
}

export function listRenderers() {
  return [...registry.values()].map(({ id, name, dims }) => ({ id, name, dims }))
}

export async function createRenderer(id, container, opts = {}) {
  const def = registry.get(id)
  if (!def) throw new Error(`未注册的渲染器：${id}（可用：${[...registry.keys()].join(', ')}）`)
  return def.create(container, opts)
}
