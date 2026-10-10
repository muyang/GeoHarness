<script setup>
import { computed, ref } from 'vue'
import { parseCsv } from '../lib/csv.js'

const props = defineProps({ run: Object })
const emit = defineEmits(['plot'])
const fetchNote = ref('')
/** 内联查看器：csv → 表格；html → iframe(blob)。新标签永远是备选，不是唯一出路。 */
const viewer = ref(null)
const COLORS = ['#3CE6B0', '#57D7FF', '#FFC65C', '#FF7A90', '#B48BFF']
let colorIdx = 0

const outputs = computed(() => props.run?.result?.outputs || null)
const pretty = computed(() => outputs.value ? JSON.stringify(outputs.value, null, 2) : '')

/** 扫描 outputs：内联 GeoJSON 直接可上图；路径型产物走节点 /artifact 受控出口。 */
const inlineGeo = computed(() => {
  const found = []
  const walk = (v, key) => {
    if (v && typeof v === 'object') {
      if (v.type === 'FeatureCollection' || v.type === 'Feature') found.push({ key, geojson: v })
      else for (const [k, sub] of Object.entries(v)) walk(sub, `${key}.${k}`)
    }
  }
  if (outputs.value) walk(outputs.value, 'outputs')
  return found
})
const pathArtifacts = computed(() => {
  const found = []
  const walk = (v, key) => {
    if (typeof v === 'string' && /\.(geojson|html|csv|json|tif|tiff)$/i.test(v)) found.push({ key, path: v })
    else if (v && typeof v === 'object') for (const [k, sub] of Object.entries(v)) walk(sub, `${key}.${k}`)
  }
  if (outputs.value) walk(outputs.value, 'outputs')
  return found
})

function plotInline(item) {
  const color = COLORS[colorIdx++ % COLORS.length]
  emit('plot', { geojson: item.geojson, name: item.key, color })
}

async function fetchArtifact(item) {
  fetchNote.value = ''
  const base = String(props.run?.baseUrl || '/node').replace(/\/$/, '')
  try {
    const res = await fetch(`${base}/artifact?path=${encodeURIComponent(item.path)}`)
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      fetchNote.value = `拉取失败（HTTP ${res.status}）：${body.error || '节点未提供 /artifact（SDK 过旧？）或路径越界'}`
      return
    }
    const ctype = res.headers.get('content-type') || ''
    if (/\.geojson$/i.test(item.path)) {
      const fc = await res.json()
      emit('plot', { geojson: fc, name: item.key, color: COLORS[colorIdx++ % COLORS.length] })
      fetchNote.value = `${item.key} 已上图`
    } else if (/\.csv$/i.test(item.path) || ctype.includes('text/csv')) {
      const table = parseCsv(await res.text())
      viewer.value = { kind: 'csv', name: item.key, table }
      fetchNote.value = `${item.key} 内联预览（前 ${table.body.length} 行）`
    } else if (/\.html?$/i.test(item.path) || ctype.includes('text/html')) {
      const blob = await res.blob()
      viewer.value = { kind: 'html', name: item.key, url: URL.createObjectURL(blob) }
      fetchNote.value = `${item.key} 内联预览`
    } else if (/\.tif+f?$/i.test(item.path)) {
      // 诚实边界：浏览器里不解栅格，不假装能预览
      viewer.value = { kind: 'note', name: item.key,
        text: '栅格（GeoTIFF）不在浏览器内解码：请经平台交付物下载或本地工具打开。元数据见 outputs。' }
      fetchNote.value = ''
    } else {
      const blob = await res.blob()
      window.open(URL.createObjectURL(blob), '_blank')
      fetchNote.value = `${item.key} 已在新标签打开`
    }
  } catch (e) {
    fetchNote.value = `拉取失败：${e.message}`
  }
}
</script>

<template>
  <section class="panel wrap">
    <h3>运行结果</h3>
    <p v-if="!run" class="dim">选一个技能，填参数，执行。</p>
    <p v-else-if="run.busy" class="dim">执行中…（<span class="mono">{{ run.skill }}</span>）</p>

    <template v-else-if="run && !run.ok">
      <p class="errhead">✗ {{ run.skill }} 失败</p>
      <p v-if="run.error.code" class="dim">错误码 <span class="mono">{{ run.error.code }}</span>
        <span v-if="run.error.hint"> · {{ run.error.hint }}</span></p>
      <p class="msg">{{ run.error.message }}</p>
      <pre v-if="run.error.data" class="json">{{ JSON.stringify(run.error.data, null, 2) }}</pre>
    </template>

    <template v-else-if="run">
      <p class="okhead">✓ <span class="mono">{{ run.skill }}</span>
        <span class="dim"> · {{ run.result?.executed_by || 'node' }}</span></p>
      <div v-for="g in inlineGeo" :key="g.key" class="row">
        <button class="primary" @click="plotInline(g)">🗺 上图：{{ g.key }}</button>
      </div>
      <div v-for="a in pathArtifacts" :key="a.key" class="row">
        <span class="mono dim path" :title="a.path">{{ a.key }}</span>
        <button @click="fetchArtifact(a)">从节点拉取</button>
      </div>
      <p v-if="fetchNote" class="dim note">{{ fetchNote }}</p>
      <div v-if="viewer" class="viewer">
        <div class="vhead">
          <strong class="mono">{{ viewer.name }}</strong>
          <button v-if="viewer.kind === 'html'" @click="window.open(viewer.url, '_blank')">新标签打开</button>
          <button @click="viewer = null">关闭</button>
        </div>
        <iframe v-if="viewer.kind === 'html'" :src="viewer.url" class="vframe" sandbox="allow-same-origin" />
        <p v-else-if="viewer.kind === 'note'" class="dim note">{{ viewer.text }}</p>
        <div v-else-if="viewer.kind === 'csv'" class="vtable">
          <table>
            <thead><tr><th v-for="h in viewer.table.header" :key="h">{{ h }}</th></tr></thead>
            <tbody><tr v-for="(r, i) in viewer.table.body" :key="i">
              <td v-for="(c, j) in r" :key="j">{{ c }}</td></tr></tbody>
          </table>
          <p v-if="viewer.table.truncated" class="dim note">已截断（仅预览）</p>
        </div>
      </div>
      <pre class="json">{{ pretty }}</pre>
    </template>
  </section>
</template>

<style scoped>
.wrap { padding: 12px 14px; }
.okhead { color: var(--teal); margin: 2px 0 8px; }
.errhead { color: var(--rose); margin: 2px 0 4px; font-weight: 600; }
.msg { margin: 4px 0; font-size: 13px; }
.row { display: flex; align-items: center; gap: 8px; margin: 6px 0; flex-wrap: wrap; }
.path { font-size: 11.5px; max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.note { font-size: 12px; margin: 4px 0; }
.viewer { border: 1px solid var(--line); border-radius: 9px; margin: 8px 0; overflow: hidden; }
.vhead { display: flex; gap: 8px; align-items: center; padding: 6px 10px;
  border-bottom: 1px solid var(--line); background: #0A1420; }
.vhead strong { margin-right: auto; font-size: 12px; }
.vframe { width: 100%; height: 320px; border: none; background: #fff; }
.vtable { max-height: 300px; overflow: auto; }
.vtable table { border-collapse: collapse; width: 100%; font-size: 12px; }
.vtable th, .vtable td { border: 1px solid var(--line); padding: 3px 7px; text-align: left;
  white-space: nowrap; }
.vtable th { position: sticky; top: 0; background: #0A1420; color: var(--cyan); }
.json { background: #0A1420; border: 1px solid var(--line); border-radius: 9px; padding: 9px;
  font-size: 12px; max-height: 46vh; overflow: auto; white-space: pre-wrap; word-break: break-all; }
</style>
