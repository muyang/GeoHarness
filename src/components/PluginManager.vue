<script setup>
/** 插件管理器：按类列出已注册插件，可启停。
 *  市场客户端平面的"安装"未实现（M4），这里如实说明，不给假按钮。 */
import { computed, ref } from 'vue'
import { PLUGIN_KINDS, listPlugins, setEnabled } from '../lib/plugins.js'

const emit = defineEmits(['close', 'changed'])
const version = ref(0)
const KIND_LABEL = {
  renderer: '渲染器（地图引擎）', panel: '面板', knowledge: '知识库', viewer: '查看器'
}

const grouped = computed(() => {
  void version.value
  const all = listPlugins()
  return PLUGIN_KINDS.map((k) => ({ kind: k, label: KIND_LABEL[k], items: all.filter((p) => p.kind === k) }))
    .filter((g) => g.items.length)
})

function toggle(p) {
  setEnabled(p.id, !p.enabled)
  version.value += 1
  emit('changed', p.id)
}
</script>

<template>
  <div class="mask" @click.self="emit('close')">
    <section class="dlg panel">
      <header>
        <h3>插件</h3>
        <button @click="emit('close')">关闭</button>
      </header>
      <p class="dim note">
        一切皆是插件：地图引擎、面板、知识库都由插件提供，可启停（状态存 localStorage）。
        经**公共产品市场**安装客户端插件排在 M4；服务端插件（pip）已可经平台市场审批安装。
      </p>
      <div v-for="g in grouped" :key="g.kind" class="group">
        <h4>{{ g.label }}</h4>
        <div v-for="p in g.items" :key="p.id" class="row">
          <label class="sw">
            <input type="checkbox" :checked="p.enabled" @change="toggle(p)" />
            <strong>{{ p.name }}</strong>
            <span class="mono dim">{{ p.id }} · v{{ p.version }}</span>
          </label>
          <p class="dim desc">{{ p.description }}</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.mask { position: fixed; inset: 0; background: rgba(3, 8, 14, .6); z-index: 60;
  display: flex; align-items: flex-start; justify-content: center; padding: 70px 16px; }
.dlg { width: 620px; max-width: 94vw; max-height: 78vh; overflow: auto; padding: 14px 16px; }
header { display: flex; align-items: center; margin-bottom: 6px; }
header h3 { margin: 0; color: var(--cyan); font-size: 14px; }
header button { margin-left: auto; }
.note { font-size: 12px; margin: 0 0 12px; line-height: 1.6; }
.group { border-top: 1px solid var(--line); padding: 10px 0; }
.group h4 { margin: 0 0 8px; font-size: 12.5px; color: var(--amber); }
.row { margin-bottom: 10px; }
.sw { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.sw strong { font-size: 13px; }
.sw .mono { font-size: 11.5px; }
.desc { font-size: 12px; margin: 2px 0 0 22px; }
</style>
