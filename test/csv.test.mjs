import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseCsv } from '../src/lib/csv.js'

test('嗅探分隔符 + 表头 + 引号转义', () => {
  const { header, body } = parseCsv('id;name;note\n1;"Smith, J";""""q""""\n2;Li;ok\n')
  assert.deepEqual(header, ['id', 'name', 'note'])
  assert.deepEqual(body[0], ['1', 'Smith, J', '"q"'])
  assert.deepEqual(body[1], ['2', 'Li', 'ok'])
})

test('limit 截断并标记', () => {
  const text = 'a,b\n' + Array.from({ length: 150 }, (_, i) => `${i},${i + 1}`).join('\n')
  const r = parseCsv(text, { limit: 100 })
  assert.ok(r.body.length <= 101)
  assert.equal(r.truncated, true)
})

test('空输入不炸', () => {
  const r = parseCsv('')
  assert.deepEqual(r.header, [])
  assert.deepEqual(r.body, [])
})
