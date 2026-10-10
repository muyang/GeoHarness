/** GeoMCP JSON-RPC 客户端（浏览器侧，零依赖）。
 *
 *  协议面与 SDK 完全一致：POST {base}/geomcp，信封 {jsonrpc:"2.0",id,method,params}。
 *  错误不吞：JSON-RPC error → 抛 GeoMCPError(code,message,data)，界面负责说人话。
 *  base 默认 '/node'（vite 开发代理 → 127.0.0.1:8787）；也可填完整 URL，
 *  此时节点需设置 GEONODE_CORS_ORIGINS 允许本来源。
 */

export class GeoMCPError extends Error {
  constructor(code, message, data = null) {
    super(message)
    this.name = 'GeoMCPError'
    this.code = code
    this.data = data
  }
  /** 常见应用错误码 → 一句人话（错误码表见 docs/GEOMCP.md） */
  get hint() {
    return ({
      2000: '请求超出 GeoCard 合约（bbox/时间/波段）',
      2001: '节点上没有这个技能',
      2002: '引用的 GeoCard 不存在',
      2003: '技能执行失败（看 message/data）',
      2004: '参数不合法',
      2005: '方案不存在或未过审',
      2006: '方案参数越界',
      2007: 'GAAG 合约绑定被拒（授权验证不过或查无对证）',
      '-32601': '节点不支持该方法（版本过旧？）'
    })[this.code] || ''
  }
}

let seq = 0
export function makeRequestId() {
  seq += 1
  return `web-${Date.now().toString(36)}-${seq}`
}

export function buildRequest(method, params = {}, id = makeRequestId()) {
  return { jsonrpc: '2.0', id, method, params }
}

export class GeoMCPClient {
  constructor(baseUrl = '/node') {
    this.baseUrl = String(baseUrl || '/node').replace(/\/$/, '')
  }

  async request(method, params = {}, { timeoutMs = 60000 } = {}) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    let res
    try {
      res = await fetch(`${this.baseUrl}/geomcp`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(buildRequest(method, params)),
        signal: controller.signal
      })
    } catch (e) {
      throw new GeoMCPError(-32000, `节点不可达（${this.baseUrl}）：${e.message}`)
    } finally {
      clearTimeout(timer)
    }
    let body
    try {
      body = await res.json()
    } catch {
      throw new GeoMCPError(-32700, `节点响应不是 JSON（HTTP ${res.status}）`)
    }
    if (body?.error) {
      throw new GeoMCPError(body.error.code, body.error.message, body.error.data ?? null)
    }
    return body?.result
  }

  health() { return this.request('geo.health', {}) }
  capabilities() { return this.request('geo.capabilities', {}) }
  describe(geocards = []) { return this.request('geo.describe', { geocards }) }
  execute(skill, { params = {}, geocards = [], spatial = null, temporal = null, contractBinding = null } = {}) {
    const p = { skill, geocards, params }
    if (spatial) p.spatial = spatial
    if (temporal) p.temporal = temporal
    if (contractBinding) p.contract_binding = contractBinding
    return this.request('geo.execute', p, { timeoutMs: 300000 })
  }
  plan(recipe, params = {}) { return this.request('geo.plan', { recipe, params }) }
}
