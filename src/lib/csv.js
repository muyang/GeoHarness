/** 极简 CSV 解析（查看器用）：嗅探分隔符、首行表头、限行数。不引依赖。 */
export function parseCsv(text, { limit = 100 } = {}) {
  const head = text.slice(0, 8192)
  const counts = [',', ';', '\t', '|'].map((d) => [d, (head.match(new RegExp(`\\${d}`, 'g')) || []).length])
  counts.sort((a, b) => b[1] - a[1])
  const delim = counts[0][1] > 0 ? counts[0][0] : ','
  const rows = []
  let row = []; let cell = ''; let quote = false
  const push = () => { row.push(cell); cell = '' }
  const endRow = () => { push(); rows.push(row); row = [] }
  for (let i = 0; i < text.length && rows.length <= limit; i += 1) {
    const ch = text[i]
    if (quote) {
      if (ch === '"') {
        if (text[i + 1] === '"') { cell += '"'; i += 1 } else quote = false
      } else cell += ch
    } else if (ch === '"') quote = true
    else if (ch === delim) push()
    else if (ch === '\n') endRow()
    else if (ch !== '\r') cell += ch
  }
  if (cell || row.length) endRow()
  while (rows.length && rows[rows.length - 1].every((c) => c === '')) rows.pop()
  const [header, ...body] = rows
  return { header: header || [], body: body || [], delim, truncated: rows.length > limit }
}
