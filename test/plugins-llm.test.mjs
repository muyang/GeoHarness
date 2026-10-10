import assert from 'node:assert/strict'
import { test } from 'node:test'
import { registerPlugin, listPlugins, setEnabled, isEnabled, pluginsOfKind, _setStorage as setPS } from '../src/lib/plugins.js'
import { loadProfiles, saveProfiles, activeProfile, setActive, testProfile, _setStorage as setLS } from '../src/lib/llm.js'

function memStorage() {
  const m = new Map()
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }
}

test('插件注册/启停/按类过滤，状态持久化', () => {
  setPS(memStorage())
  registerPlugin({ id: 'renderer.a', kind: 'renderer', name: 'A' })
  registerPlugin({ id: 'panel.b', kind: 'panel', name: 'B' })
  assert.equal(isEnabled('renderer.a'), true)
  setEnabled('renderer.a', false)
  assert.equal(isEnabled('renderer.a'), false)
  assert.deepEqual(pluginsOfKind('renderer').map((p) => p.id), [])
  assert.deepEqual(pluginsOfKind('panel').map((p) => p.id), ['panel.b'])
  assert.throws(() => registerPlugin({ id: 'x', kind: 'nope' }))
})

test('profiles：增删改、active 切换、旧键兼容', () => {
  const st = memStorage()
  setLS(st)
  st.setItem('gnx.llm', JSON.stringify({ baseUrl: 'http://old:1/v1', model: 'm0' }))
  let list = loadProfiles()
  assert.equal(list[0].baseUrl, 'http://old:1/v1', '旧单配置要能迁移')
  list.push({ id: 'p2', name: '备用', baseUrl: 'http://new:2/v1', key: 'k', model: 'm1' })
  saveProfiles(list)
  setActive('p2')
  assert.equal(activeProfile().name, '备用')
})

test('testProfile：空端点与坏响应都说人话', async () => {
  setLS(memStorage())
  const empty = await testProfile({ baseUrl: '', model: 'm' })
  assert.equal(empty.ok, false)
  assert.match(empty.message, /端点为空/)
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ nope: 1 }) })
  const bad = await testProfile({ baseUrl: 'http://x/v1', model: 'm' })
  assert.equal(bad.ok, false)
  assert.match(bad.message, /不像 OpenAI 兼容端点/)
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ choices: [{ message: { content: 'pong' } }] }) })
  const good = await testProfile({ baseUrl: 'http://x/v1', model: 'm' })
  assert.equal(good.ok, true)
})
