/** LLM 多配置档（profiles）：端点/密钥/模型一组一档，可测连、可切换、持久化。
 *  不内置任何模型；配置存 localStorage，密钥只在本机。 */

const LS_PROFILES = 'gnx.llm.profiles'
const LS_ACTIVE = 'gnx.llm.active'
let storage = typeof localStorage !== 'undefined' ? localStorage : null
export function _setStorage(s) { storage = s }

export function loadProfiles() {
  try {
    const list = JSON.parse(storage?.getItem(LS_PROFILES) || 'null')
    if (Array.isArray(list) && list.length) return list
  } catch { /* 落回默认 */ }
  // 兼容旧单配置键
  try {
    const old = JSON.parse(storage?.getItem('gnx.llm') || 'null')
    if (old?.baseUrl) {
      return [{ id: 'p1', name: '默认', baseUrl: old.baseUrl, key: old.key || '', model: old.model || 'geo-model' }]
    }
  } catch { /* 忽略 */ }
  return [{ id: 'p1', name: '默认', baseUrl: 'http://127.0.0.1:8901/v1', key: '', model: 'geo-model' }]
}

export function saveProfiles(list) { storage?.setItem(LS_PROFILES, JSON.stringify(list)) }

export function activeProfile() {
  const list = loadProfiles()
  const id = storage?.getItem(LS_ACTIVE)
  return list.find((p) => p.id === id) || list[0]
}

export function setActive(id) { storage?.setItem(LS_ACTIVE, id) }

/** 测连：发一条最小对话，看端点是否真能回。错误说人话。 */
export async function testProfile(p, timeoutMs = 15000) {
  const url = `${String(p.baseUrl || '').replace(/\/$/, '')}/chat/completions`
  if (!p.baseUrl) return { ok: false, message: '端点为空' }
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(url, {
      method: 'POST', signal: ctrl.signal,
      headers: { 'content-type': 'application/json', ...(p.key ? { authorization: `Bearer ${p.key}` } : {}) },
      body: JSON.stringify({ model: p.model, messages: [{ role: 'user', content: 'ping' }], max_tokens: 8 })
    })
    if (!res.ok) return { ok: false, message: `HTTP ${res.status}：${(await res.text()).slice(0, 160)}` }
    const j = await res.json()
    if (!j.choices?.[0]?.message) return { ok: false, message: '响应缺少 choices[0].message（不像 OpenAI 兼容端点）' }
    return { ok: true, message: `OK（模型回：${String(j.choices[0].message.content || '[tool_calls]').slice(0, 40)}）` }
  } catch (e) {
    const corsHint = e.name === 'AbortError' ? '（超时）' : '（若端点在本机其它端口，注意 CORS/跨域）'
    return { ok: false, message: `${e.message} ${corsHint}` }
  } finally {
    clearTimeout(t)
  }
}
