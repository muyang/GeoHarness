<script setup>
/** GeoKG 知识库面板（知识类插件）。两条路自动选，都不通就明说怎么办：
 *  ① 节点装了 GeoKG 插件（市场安装）→ 调 geo.execute('geokg-search')，**零配置即插即用**；
 *  ② 仅有 geokg-api HTTP 服务 → 配端点走 /search。
 *  两者输出同源（geokg.admin.search），这里统一归一化。 */
import { computed, onMounted, ref, watch } from 'vue'
import { hasKgSkill, normalizeKgResults } from '../lib/kg.js'

const props = defineProps({ caps: Object, clientFactory: Function, activeUrl: String })

const LS = 'gnx.geokg'
const base = ref('')
const query = ref('')
const res = ref(null)
const state = ref('idle')   // idle | busy | error | ok
const error = ref('')

const nodeKg = computed(() => hasKgSkill(props.caps))

onMounted(() => {
  try { base.value = JSON.parse(localStorage.getItem(LS) || '{}').base || '' } catch { /* 空 */ }
})
watch(nodeKg, () => { res.value = null; state.value = 'idle' })
function save() { localStorage.setItem(LS, JSON.stringify({ base: base.value })) }

async function search() {
  save()
  state.value = 'busy'; error.value = ''
  try {
    if (nodeKg.value) {
      const client = props.clientFactory(props.activeUrl)
      const out = await client.execute('geokg-search', { params: { query: query.value, limit: 20 } })
      res.value = normalizeKgResults(out?.outputs, { source: 'node' })
    } else if (base.value) {
      const r = await fetch(`${base.value.replace(/\/$/, '')}/search?q=${encodeURIComponent(query.value)}&limit=20`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      res.value = normalizeKgResults(await r.json(), { source: 'http' })
    } else {
      throw new Error('没有可用的 GeoKG 来源')
    }
    state.value = 'ok'
  } catch (e) {
    state.value = 'error'
    error.value = e.message
  }
}
</script>

<template>
  <aside class="kg panel">
    <div class="head">
      <h3>GeoKG 知识库 <span class="dim">（知识类插件）</span></h3>
      <em class="tag" :class="nodeKg ? 'ok' : ''">
        {{ nodeKg ? '来源：节点技能 geokg-search ✓' : (base ? '来源：HTTP 端点' : '未接线') }}
      </em>
    </div>

    <p v-if="!nodeKg" class="dim note">
      该节点没有 GeoKG 插件。两条路：
      <strong>①（推荐）</strong>到平台「产品市场」申请安装 <code class="mono">geonexus-plugin-geokg</code>，
      审批装好后节点重启即出现 <code class="mono">geokg-search</code>，本面板零配置自动接上；
      <strong>②</strong>或在此配一个 geokg-api 服务端点。
    </p>
    <div v-if="!nodeKg" class="conf">
      <label>HTTP 端点 <input v-model="base" class="mono" placeholder="http://127.0.0.1:8801" @change="save" /></label>
    </div>

    <div class="composer">
      <input v-model="query" placeholder="查知识…（如 SDG / 湿地 / 中国）" @keyup.enter="search" />
      <button class="primary" :disabled="state === 'busy' || !activeUrl" @click="search">检索</button>
    </div>

    <p v-if="state === 'error'" class="errline">{{ error }}</p>

    <template v-else-if="res">
      <p class="meta dim">
        命中 <strong>{{ res.count }}</strong> · 返回 {{ res.returned }}
        <span v-if="res.truncated">（已截断）</span>
        <span v-if="res.entities"> · 图谱实体 {{ res.entities }}</span>
        <span v-if="res.fingerprint" class="mono"> · 指纹 {{ res.fingerprint.slice(0, 10) }}</span>
      </p>
      <ul v-if="res.items.length" class="hits">
        <li v-for="it in res.items" :key="it.id">
          <div class="hithead">
            <strong>{{ it.name }}</strong>
            <em class="tag">{{ it.type }}</em>
          </div>
          <span class="mono dim id">{{ it.id }}</span>
          <span v-if="it.summary" class="dim">{{ it.summary }}</span>
          <span v-if="it.origin" class="dim src">来源 {{ it.origin }}<template v-if="it.license"> · {{ it.license }}</template></span>
        </li>
      </ul>
      <p v-else class="dim note">没有命中。</p>
    </template>
  </aside>
</template>

<style scoped>
.kg { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px;
  width: 400px; max-width: 94vw; max-height: 74vh; }
.head { display: flex; align-items: center; gap: 8px; }
.head h3 { margin: 0; font-size: 13px; color: var(--cyan); }
.head .tag { margin-left: auto; font-size: 11px; }
.note { font-size: 11.5px; margin: 0; line-height: 1.6; }
.note code { font-size: 11px; color: var(--amber); }
.conf label { display: block; font-size: 12px; color: var(--dim); }
.conf input { width: 100%; margin-top: 4px; }
.composer { display: flex; gap: 8px; }
.composer input { flex: 1; }
.meta { font-size: 12px; margin: 0; }
.hits { list-style: none; margin: 0; padding: 0; overflow: auto; display: flex;
  flex-direction: column; gap: 6px; }
.hits li { border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; font-size: 12.5px;
  display: flex; flex-direction: column; gap: 2px; }
.hithead { display: flex; align-items: center; gap: 7px; }
.hithead .tag { font-size: 10.5px; }
.id { font-size: 11px; }
.src { font-size: 11px; }
.errline { color: var(--rose); font-size: 12px; margin: 0; }
</style>
