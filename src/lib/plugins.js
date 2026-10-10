/** 客户端插件核心：一切皆是插件（渲染器/面板/知识库/查看器）。
 *
 *  与 DSH 的设计原则对齐：能力不写死在壳里，而是可注册、可启停、可经市场分发的插件。
 *  服务端平面（pip 包）与客户端平面（JS 插件）共用同一套"条目+审批+校验和"纪律；
 *  客户端平面的市场安装（下载 bundle + 动态 import）排在 M4，这里先把
 *  **内置能力全部插件化**，管理器可启停，状态持久化。
 */

export const PLUGIN_KINDS = ['renderer', 'panel', 'knowledge', 'viewer']

const registry = new Map()
let storage = typeof localStorage !== 'undefined' ? localStorage : null
const LS_KEY = 'gnx.plugins'

export function _setStorage(s) { storage = s }   // 测试注入

function loadState() {
  try { return JSON.parse(storage?.getItem(LS_KEY) || '{}') } catch { return {} }
}
function saveState(state) { storage?.setItem(LS_KEY, JSON.stringify(state)) }

export function registerPlugin(def) {
  if (!def?.id || !PLUGIN_KINDS.includes(def.kind)) {
    throw new Error(`插件必须有 id 与合法 kind（${PLUGIN_KINDS.join('/')}）`)
  }
  registry.set(def.id, { enabledByDefault: true, version: '0.1.0', ...def })
}

export function listPlugins() {
  const state = loadState()
  return [...registry.values()].map((p) => ({
    ...p, enabled: state[p.id] ?? p.enabledByDefault
  }))
}

export function isEnabled(id) {
  const p = registry.get(id)
  if (!p) return false
  return loadState()[id] ?? p.enabledByDefault
}

export function setEnabled(id, on) {
  if (!registry.has(id)) throw new Error(`未注册插件：${id}`)
  const state = loadState()
  state[id] = Boolean(on)
  saveState(state)
}

export function pluginsOfKind(kind) {
  return listPlugins().filter((p) => p.kind === kind && p.enabled)
}

export function getPlugin(id) {
  return registry.get(id) || null
}
