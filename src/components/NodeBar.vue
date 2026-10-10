<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ nodes: Array, active: String, busy: Boolean, error: String })
const emit = defineEmits(['connect', 'switch', 'remove'])
const url = ref('/node')
const current = computed(() => props.nodes.find((n) => n.url === props.active) || null)
const plugins = computed(() => current.value?.health?.plugins || [])
</script>

<template>
  <header class="bar panel">
    <div class="brand">
      <span class="dot" :class="{ on: !!current }" />
      <strong>GeoHarness</strong><span class="dim">· GeoNexus 客户端</span>
    </div>
    <select v-if="nodes.length" class="switcher mono" :value="active"
            @change="emit('switch', $event.target.value)">
      <option v-for="n in nodes" :key="n.url" :value="n.url">
        {{ n.health?.node || n.url }}
      </option>
    </select>
    <input v-model="url" class="url mono" spellcheck="false"
           placeholder="节点地址：/node（开发代理）或 http://192.168.100.101:8787"
           @keyup.enter="emit('connect', url)" />
    <button class="primary" :disabled="busy" @click="emit('connect', url)">
      {{ busy ? '连接中…' : '连接' }}
    </button>
    <button v-if="current" title="断开该节点" @click="emit('remove', active)">断开</button>
    <div v-if="current" class="facts">
      <span class="tag ok">{{ current.health.node }}</span>
      <span class="tag">协议 {{ current.health.protocol }} v{{ current.health.version }}</span>
      <span class="tag">{{ current.caps.skills?.length || 0 }} 技能</span>
      <span class="tag">{{ current.caps.geocards?.length || 0 }} 卡</span>
      <span v-for="p in plugins" :key="p.name" class="tag" :class="p.ok ? 'ok' : 'err'"
            :title="p.error || ''">插件 {{ p.name }} {{ p.ok ? '✓' : '✗' }}</span>
      <span v-if="current.caps.v2?.contract_binding" class="tag">V2 合约 ✓</span>
      <span v-if="current.caps.v2?.federation" class="tag">V2 联邦 ✓</span>
    </div>
    <div v-else-if="error" class="facts"><span class="tag err">{{ error }}</span></div>
  </header>
</template>

<style scoped>
.bar { display: flex; align-items: center; gap: 10px; padding: 10px 14px; margin: 10px 10px 0;
  border-radius: 12px; flex-wrap: wrap; }
.brand { display: flex; align-items: center; gap: 7px; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: #33475C; }
.dot.on { background: var(--teal); box-shadow: 0 0 8px rgba(60, 230, 176, .7); }
.switcher { max-width: 200px; }
.url { flex: 1; min-width: 240px; }
.facts { display: flex; gap: 6px; flex-wrap: wrap; width: 100%; }
</style>
