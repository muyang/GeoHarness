<script setup>
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { createRenderer } from '../lib/renderers/index.js'
import { pluginsOfKind } from '../lib/plugins.js'

const props = defineProps({ layers: Array, pluginsVersion: Number })
const emit = defineEmits(['remove-layer'])
const box = ref(null)
const renderer = shallowRef(null)
const engineError = ref('')
/** 引擎列表 = **启用的渲染器插件**（不是写死的清单）：插件管理器里关掉就不出现。
 *  pluginsVersion 是父组件传入的"插件状态已变"信号，用于重算这个列表。 */
const engines = computed(() => {
  void props.pluginsVersion
  return pluginsOfKind('renderer').map((p) => p.renderer)
})
const engineId = ref(engines.value[0]?.id || '')

// 启用集合变化：当前引擎被关掉就切到第一个可用引擎重开，没有可用引擎则明说
watch(() => props.pluginsVersion, () => {
  const list = engines.value
  if (!list.length) {
    renderer.value?.destroy?.()
    renderer.value = null
    engineError.value = '没有启用的渲染器插件（到「插件 🧩」里打开一个地图引擎）'
    return
  }
  if (!list.some((e) => e.id === engineId.value)) {
    engineId.value = list[0].id
    boot(engineId.value)
  }
})


let bootPromise = null
async function boot(id) {
  engineError.value = ''
  renderer.value?.destroy?.()
  renderer.value = null
  bootPromise = createRenderer(id, box.value).then((inst) => {
    renderer.value = inst
    console.info('[mapview] 渲染器就绪:', id)
    return inst
  }).catch((e) => {
    engineError.value = `渲染器 ${id} 启动失败：${e.message}`
    console.error('[mapview] 启动失败:', id, e.message)
    return null
  })
  return bootPromise
}
onMounted(() => { boot(engineId.value) })
onBeforeUnmount(() => renderer.value?.destroy?.())

async function render(geojson, meta = {}) {
  // 启动是异步的：点击「上图」早于 boot 完成是常态，等它，而不是报"未就绪"
  if (!renderer.value && bootPromise) await bootPromise
  if (!renderer.value) { engineError.value = '渲染器未就绪'; return null }
  const l = renderer.value.renderGeoJSON(geojson, meta)
  // Cesium 的 renderGeoJSON 是异步的，统一成"能拿到就返回"
  if (l && typeof l.then === 'function') {
    return l.then((r) => ({ ...r, engine: engineId.value }))
  }
  return { ...l, engine: engineId.value }
}
function clearAll() { renderer.value?.clear?.(); emit('remove-layer', '*') }
function remove(layerId) {
  renderer.value?.removeLayer?.(layerId)
  emit('remove-layer', layerId)
}
defineExpose({ render, remove })
</script>

<template>
  <section class="mapwrap panel">
    <div class="mapbar">
      <h3>地图</h3>
      <select v-model="engineId" @change="boot(engineId)">
        <option v-for="e in engines" :key="e.id" :value="e.id">{{ e.name }}</option>
      </select>
      <span class="dim">{{ (layers || []).length }} 层</span>
      <button @click="clearAll">清空图层</button>
      <div v-if="(layers || []).length" class="chips">
        <span v-for="l in layers" :key="l.layerId" class="chip">
          {{ l.name }} <em class="dim">{{ l.node || '' }}</em>
          <button class="x" title="移除该层" @click="remove(l.layerId)">×</button>
        </span>
      </div>
    </div>
    <div ref="box" class="mapbox" />
    <p v-if="engineError" class="errline">{{ engineError }}</p>
  </section>
</template>

<style scoped>
.mapwrap { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.mapbar { display: flex; align-items: center; gap: 10px; padding: 9px 12px;
  border-bottom: 1px solid var(--line); }
.mapbar h3 { margin: 0; }
.mapbox { flex: 1; min-height: 320px; }
.errline { margin: 0; padding: 8px 12px; color: var(--rose); font-size: 12.5px;
  border-top: 1px solid var(--line); }
.chips { display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }
.chip { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px;
  border: 1px solid var(--line); border-radius: 999px; padding: 1px 8px; }
.chip .x { border: none; background: none; padding: 0 2px; color: var(--dim); }
.chip .x:hover { color: var(--rose); }
</style>
