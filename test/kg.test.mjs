import assert from 'node:assert/strict'
import { test } from 'node:test'
import { hasKgSkill, normalizeKgResults } from '../src/lib/kg.js'

test('hasKgSkill：认节点技能，不认就明说', () => {
  assert.equal(hasKgSkill({ skills: [{ name: 'geokg-search' }] }), true)
  assert.equal(hasKgSkill({ skills: [{ name: 'demo-ndvi-stats' }] }), false)
  assert.equal(hasKgSkill(null), false)
})

test('normalizeKgResults：保留溯源与数据集指纹', () => {
  const out = normalizeKgResults({
    count: 450, returned: 2, truncated: false,
    dataset: { fingerprint: 'abc123', entities: 14603 },
    results: [
      { id: 'sdg.goal.1', type: 'SDG_Goal', name: 'No Poverty',
        provenance: { origin: 'curated', license: '联合国公开文件' }, properties: { code: '1' } },
      { id: 'x', type: 'Concept', title: '仅 title 的兜底', properties: { a: 1, b: 2 } }
    ]
  })
  assert.equal(out.count, 450)
  assert.equal(out.fingerprint, 'abc123')
  assert.equal(out.items[0].name, 'No Poverty')
  assert.equal(out.items[0].license, '联合国公开文件')
  assert.equal(out.items[1].name, '仅 title 的兜底')
  assert.match(out.items[1].summary, /a=1/)
})

test('normalizeKgResults：空输入不炸', () => {
  const out = normalizeKgResults(null)
  assert.deepEqual(out.items, [])
  assert.equal(out.count, 0)
})
