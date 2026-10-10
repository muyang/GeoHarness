/** geomcp.js 单测（node --test，无 DOM）：信封形状、错误映射、execute 参数装配。 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { GeoMCPClient, GeoMCPError, buildRequest, makeRequestId } from '../src/lib/geomcp.js'

function stubFetch(response, { status = 200 } = {}) {
  const calls = []
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, opts })
    return { status, ok: status < 300, json: async () => response }
  }
  return calls
}

test('信封是标准 JSON-RPC 2.0，id 唯一', () => {
  const a = buildRequest('geo.health', {}, 'x1')
  assert.deepEqual(a, { jsonrpc: '2.0', id: 'x1', method: 'geo.health', params: {} })
  assert.notEqual(makeRequestId(), makeRequestId())
})

test('成功响应取 result，请求确实发往 {base}/geomcp', async () => {
  const calls = stubFetch({ jsonrpc: '2.0', id: '1', result: { status: 'ok', node: 'n' } })
  const c = new GeoMCPClient('/node')
  const out = await c.health()
  assert.equal(out.node, 'n')
  assert.equal(calls[0].url, '/node/geomcp')
  assert.equal(calls[0].opts.method, 'POST')
})

test('JSON-RPC error → GeoMCPError(code,message,data)，hint 说人话', async () => {
  stubFetch({ jsonrpc: '2.0', id: '1', error: { code: 2007, message: 'rejected', data: { reason: 'no_gaag_registry' } } })
  const c = new GeoMCPClient('http://x:8787')
  await assert.rejects(() => c.execute('s', {}), (e) => {
    assert.ok(e instanceof GeoMCPError)
    assert.equal(e.code, 2007)
    assert.equal(e.data.reason, 'no_gaag_registry')
    assert.match(e.hint, /GAAG/)
    return true
  })
})

test('execute 只在给了值时携带 spatial/temporal/contract_binding', async () => {
  const calls = stubFetch({ jsonrpc: '2.0', id: '1', result: { status: 'ok', outputs: {} } })
  const c = new GeoMCPClient('/node')
  await c.execute('ndvi', { params: { a: 1 } })
  let body = JSON.parse(calls[0].opts.body)
  assert.deepEqual(body.params, { skill: 'ndvi', geocards: [], params: { a: 1 } })

  await c.execute('ndvi', {
    params: {}, geocards: ['card-a'],
    spatial: { bbox: [1, 2, 3, 4], crs: 'EPSG:4326' },
    contractBinding: 'gaag.x'
  })
  body = JSON.parse(calls[1].opts.body)
  assert.equal(body.params.spatial.bbox[0], 1)
  assert.equal(body.params.contract_binding, 'gaag.x', 'V2 字段在线上是 snake_case')
})

test('节点不可达 → -32000 且消息里带地址', async () => {
  globalThis.fetch = async () => { throw new TypeError('fetch failed') }
  const c = new GeoMCPClient('http://10.0.0.9:8787')
  await assert.rejects(() => c.health(), (e) => {
    assert.equal(e.code, -32000)
    assert.match(e.message, /10\.0\.0\.9/)
    return true
  })
})
