/** GeoKG 结果的归一化与来源判定（纯函数，可单测）。
 *
 *  两条路都通，面板自动选：
 *   ① 节点上装了 GeoKG 插件（市场安装）→ 直接调 geo.execute('geokg-search')，
 *      零配置即插即用；
 *   ② 只有 geokg-api HTTP 服务 → 配端点走 /search。
 *  两者返回的都是 geokg.admin.search 的形状（CLI/HTTP/节点同源），这里再兜一层
 *  title/name 差异，避免上游换字段就白屏。
 */

export const KG_SKILL = 'geokg-search'

export function hasKgSkill(caps) {
  return (caps?.skills || []).some((s) => s.name === KG_SKILL)
}

export function normalizeKgResults(payload, { source = 'node' } = {}) {
  const results = payload?.results || []
  return {
    source,
    count: payload?.count ?? results.length,
    returned: payload?.returned ?? results.length,
    truncated: Boolean(payload?.truncated),
    fingerprint: payload?.dataset?.fingerprint || null,
    entities: payload?.dataset?.entities ?? null,
    items: results.map((r) => ({
      id: r.id,
      type: r.type || '',
      name: r.name || r.title || r.id,
      origin: r.provenance?.origin || '',
      license: r.provenance?.license || '',
      summary: r.summary || r.description
        || Object.entries(r.properties || {}).slice(0, 2).map(([k, v]) => `${k}=${v}`).join(' · ')
        || ''
    }))
  }
}
