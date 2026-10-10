import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildTools, needsConfirm, pendingCalls, runTool } from '../src/lib/agent.js'

const caps = { skills: [{ name: 'demo-ndvi-stats' }, { name: 'demo-sample-points' }], geocards: ['c1'] }

test('工具表：四个工具，execute 的 skill 枚举来自 capabilities', () => {
  const tools = buildTools(caps)
  assert.deepEqual(tools.map((t) => t.function.name),
    ['geo_capabilities', 'geo_describe', 'geo_execute', 'geo_plan'])
  const exec = tools.find((t) => t.function.name === 'geo_execute')
  assert.deepEqual(exec.function.parameters.properties.skill.enum,
    ['demo-ndvi-stats', 'demo-sample-points'])
})

test('确认分类：读自动、写人在环', () => {
  assert.equal(needsConfirm('geo_capabilities'), false)
  assert.equal(needsConfirm('geo_describe'), false)
  assert.equal(needsConfirm('geo_execute'), true)
  assert.equal(needsConfirm('geo_plan'), true)
})

test('pendingCalls 解析参数且容忍坏 JSON', () => {
  const calls = pendingCalls({ tool_calls: [
    { id: 'a', function: { name: 'geo_execute', arguments: '{"skill":"s","params":{"n":2}}' } },
    { id: 'b', function: { name: 'geo_execute', arguments: '{oops' } }
  ] })
  assert.equal(calls[0].args.params.n, 2)
  assert.deepEqual(calls[1].args, { __raw: '{oops' })
})

test('runTool 把 bbox 装配成 spatial 并透传 contract_binding', async () => {
  const seen = []
  const client = {
    capabilities: async () => ({ ok: true }),
    describe: async (g) => ({ g }),
    execute: async (skill, opts) => { seen.push([skill, opts]); return { outputs: {} } },
    plan: async (r, p) => ({ r, p })
  }
  await runTool(client, 'geo_execute', { skill: 's', bbox: [1, 2, 3, 4], contract_binding: 'g.1' })
  assert.equal(seen[0][1].spatial.bbox[3], 4)
  assert.equal(seen[0][1].contractBinding, 'g.1')
  await runTool(client, 'geo_execute', { skill: 's' })
  assert.equal(seen[1][1].spatial, null)
})
