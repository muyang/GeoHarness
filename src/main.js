import { createApp } from 'vue'
import App from './App.vue'
import { registerPlugin } from './lib/plugins.js'
import { registerRenderer } from './lib/renderers/index.js'
import { maplibreRenderer } from './lib/renderers/maplibre.js'
import { cesiumRenderer } from './lib/renderers/cesium.js'
import './style.css'

/* ── 一切皆是插件 ────────────────────────────────────────────────────────
 *  内置能力也走插件注册：地图引擎、会话面板、知识库面板都是插件，
 *  插件管理器可启停；M4 的市场客户端平面安装就是往这个注册表里加东西。
 *  （"插件 JS 动态加载"未实现，见方案 §7 M4 —— 现在只插件化内置能力。）
 */

registerPlugin({
  id: 'renderer.maplibre', kind: 'renderer', name: 'GeoLibre · MapLibre 2D',
  description: '开源矢量/栅格底图 + 业务图层渲染（默认）', version: '0.1.0',
  renderer: maplibreRenderer
})
registerPlugin({
  id: 'renderer.cesium', kind: 'renderer', name: 'Cesium · 3D 地球',
  description: '三维地球，动态加载，不依赖 Cesium ion 令牌', version: '0.1.0',
  renderer: cesiumRenderer
})
registerPlugin({
  id: 'panel.chat', kind: 'panel', name: '会话面板（LLM）',
  description: 'OpenAI 兼容端点 + GeoMCP 工具集；执行类调用需人工确认', version: '0.2.0'
})
registerPlugin({
  id: 'knowledge.geokg', kind: 'knowledge', name: 'GeoKG 知识库',
  description: '节点装了 GeoKG 插件就零配置检索；否则退回 HTTP 端点或给出安装指引', version: '0.2.0'
})

// 渲染器工厂表由插件定义填充（MapView 只认"启用的渲染器插件"）
registerRenderer(maplibreRenderer)
registerRenderer(cesiumRenderer)

createApp(App).mount('#app')
