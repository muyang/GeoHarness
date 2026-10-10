<script setup>
import { computed, reactive, ref } from 'vue'
import { GeoMCPClient, GeoMCPError } from './lib/geomcp.js'
import NodeBar from './components/NodeBar.vue'
import SkillPanel from './components/SkillPanel.vue'
import MapView from './components/MapView.vue'
import ResultPanel from './components/ResultPanel.vue'
import ChatPanel from './components/ChatPanel.vue'
import PluginManager from './components/PluginManager.vue'
import KnowledgePanel from './components/KnowledgePanel.vue'
import { isEnabled } from './lib/plugins.js'

/** 多节点：每个连过的节点留一份 health/caps，切换零成本（不重连）。 */
const nodes = ref([])
const activeUrl = ref('')
const busy = ref(false)
const connectError = ref('')
const lastRun = ref(null)
const mapRef = ref(null)
const layers = ref([])
const chatOpen = ref(false)
const kgOpen = ref(false)
const pluginOpen = ref(false)
const pluginsVersion = ref(0)   // 插件启停后强制重算启用集合
const chatOn = computed(() => isEnabled('panel.chat'))
const kgOn = computed(() => isEnabled('knowledge.geokg'))
function onPluginsChanged() {
  pluginsVersion.value += 1
  if (!chatOn.value) chatOpen.value = false
  if (!kgOn.value) kgOpen.value = false
}

const activeNode = computed(() => nodes.value.find((n) => n.url === activeUrl.value) || null)

async function connect(url) {
  busy.value = true
  connectError.value = ''
  try {
    const c = new GeoMCPClient(url)
    const [health, caps] = await Promise.all([c.health(), c.capabilities()])
    const found = nodes.value.find((n) => n.url === url)
    if (found) { found.health = health; found.caps = caps }
    else nodes.value.push({ url, health, caps })
    activeUrl.value = url
  } catch (e) {
    connectError.value = e instanceof GeoMCPError
      ? `${e.message}${e.hint ? ` —— ${e.hint}` : ''}` : e.message
  } finally {
    busy.value = false
  }
}

function switchTo(url) { activeUrl.value = url; lastRun.value = null }
function removeNode(url) {
  nodes.value = nodes.value.filter((n) => n.url !== url)
  if (activeUrl.value === url) activeUrl.value = nodes.value[0]?.url || ''
  lastRun.value = null
}

async function runSkill(req) {
  if (!activeUrl.value) return
  lastRun.value = { busy: true, requestId: req.requestId, baseUrl: activeUrl.value }
  try {
    const out = await new GeoMCPClient(activeUrl.value).execute(req.skill, {
      params: req.params, geocards: req.geocards, spatial: req.spatial,
      contractBinding: req.contractBinding
    })
    lastRun.value = { busy: false, ok: true, skill: req.skill, result: out,
      baseUrl: activeUrl.value, node: activeNode.value?.health?.node || activeUrl.value }
  } catch (e) {
    lastRun.value = {
      busy: false, ok: false, skill: req.skill, baseUrl: activeUrl.value,
      error: { code: e.code ?? null, message: e.message, hint: e.hint || '', data: e.data ?? null }
    }
  }
}

/** 结果面板发现 GeoJSON → 上图（渲染器插件画；图层带节点标签） */
async function plot(payload) {
  let l = mapRef.value?.render(payload.geojson, { ...payload, node: payload.node || lastRun.value?.node })
  if (l && typeof l.then === 'function') l = await l
  if (l) layers.value = [...layers.value, { ...l, node: payload.node || lastRun.value?.node }]
}

function onLayerRemoved(id) {
  layers.value = id === '*' ? [] : layers.value.filter((l) => l.layerId !== id)
}
</script>

<template>
  <div class="shell">
    <NodeBar :nodes="nodes" :active="activeUrl" :busy="busy" :error="connectError"
             @connect="connect" @switch="switchTo" @remove="removeNode" />
    <main class="grid">
      <SkillPanel class="col-left" :caps="activeNode?.caps" :disabled="!activeNode" @run="runSkill" />
      <MapView ref="mapRef" :layers="layers" :plugins-version="pluginsVersion"
               @remove-layer="onLayerRemoved" />
      <ResultPanel class="col-right" :run="lastRun" @plot="plot" />
    </main>
    <div class="fabs">
      <button v-if="kgOn" @click="kgOpen = !kgOpen; chatOpen = false">知识库 📚</button>
      <button v-if="chatOn" class="primary" @click="chatOpen = !chatOpen; kgOpen = false">
        {{ chatOpen ? '关闭会话' : '会话 💬' }}
      </button>
      <button @click="pluginOpen = true">插件 🧩</button>
    </div>
    <ChatPanel v-if="chatOn && chatOpen" :caps="activeNode?.caps" :active-url="activeUrl"
               :client-factory="(u) => new GeoMCPClient(u)" />
    <KnowledgePanel v-if="kgOn && kgOpen" class="kgfloat" :caps="activeNode?.caps"
                    :active-url="activeUrl" :client-factory="(u) => new GeoMCPClient(u)" />
    <PluginManager v-if="pluginOpen" @close="pluginOpen = false" @changed="onPluginsChanged" />
  </div>
</template>

<style scoped>
.shell { display: flex; flex-direction: column; height: 100%; }
.grid { flex: 1; min-height: 0; display: grid; gap: 10px; padding: 10px;
  grid-template-columns: 320px minmax(0, 1fr) 340px; }
.col-left, .col-right { min-height: 0; overflow: auto; }
.fabs { position: fixed; right: 16px; bottom: 16px; z-index: 50; display: flex; gap: 8px; }
.fabs button { border-radius: 999px; padding: 9px 16px; background: #0D1826; }
.kgfloat { position: fixed; right: 16px; bottom: 70px; z-index: 45; }
@media (max-width: 1100px) {
  .grid { grid-template-columns: 1fr; grid-template-rows: auto 420px auto; }
}
</style>
