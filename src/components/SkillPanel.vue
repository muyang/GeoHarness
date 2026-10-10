<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { makeRequestId } from '../lib/geomcp.js'

const props = defineProps({ caps: Object, disabled: Boolean })
const emit = defineEmits(['run'])

const skills = computed(() => props.caps?.skills || [])
const cards = computed(() => props.caps?.geocards || [])
const supportsBinding = computed(() => Boolean(props.caps?.v2?.contract_binding))

const selected = ref(null)
const jsonMode = ref(false)
const form = reactive({})
const rawJson = ref('{}')
const geocards = ref('')
const bbox = ref('')
const binding = ref('')
const busy = ref(false)
const formError = ref('')

watch(selected, (skill) => {
  formError.value = ''
  const schema = skill?.input_schema || {}
  const props_ = schema.properties || null
  jsonMode.value = !props_
  for (const k of Object.keys(form)) delete form[k]
  if (props_) {
    for (const [k, spec] of Object.entries(props_)) {
      form[k] = spec.default ?? (spec.type === 'number' || spec.type === 'integer' ? null
        : spec.type === 'boolean' ? false
        : spec.type === 'array' || spec.type === 'object' ? '' : '')
    }
  } else {
    rawJson.value = '{}'
  }
})

function select(skill) { selected.value = skill }

function collectParams() {
  if (!jsonMode.value) {
    const schema = selected.value?.input_schema?.properties || {}
    const out = {}
    for (const [k, v] of Object.entries(form)) {
      if (v === null || v === '') continue
      const t = schema[k]?.type
      if (t === 'number' || t === 'integer') {
        const n = Number(v)
        if (Number.isNaN(n)) throw new Error(`${k} 需要数字，收到 "${v}"`)
        out[k] = n
      } else if (t === 'array' || t === 'object') {
        try { out[k] = JSON.parse(v) } catch { throw new Error(`${k} 需要合法 JSON（${t}）`) }
      } else if (t === 'boolean') {
        out[k] = Boolean(v)
      } else out[k] = v
    }
    return out
  }
  try {
    const p = JSON.parse(rawJson.value || '{}')
    if (typeof p !== 'object' || Array.isArray(p)) throw new Error('params 必须是对象')
    return p
  } catch (e) {
    throw new Error(`params JSON 不合法：${e.message}`)
  }
}

function submit() {
  formError.value = ''
  let params
  try { params = collectParams() } catch (e) { formError.value = e.message; return }
  const required = selected.value?.input_schema?.required || []
  const missing = required.filter((k) => params[k] === undefined)
  if (missing.length) { formError.value = `缺少必填参数：${missing.join(', ')}`; return }
  let spatial = null
  if (bbox.value.trim()) {
    const n = bbox.value.split(',').map((x) => Number(x.trim()))
    if (n.length !== 4 || n.some(Number.isNaN)) { formError.value = 'bbox 需要 4 个数字：西,南,东,北'; return }
    spatial = { bbox: n, crs: 'EPSG:4326' }
  }
  busy.value = true
  emit('run', {
    skill: selected.value.name, params, spatial,
    geocards: geocards.value.split(',').map((x) => x.trim()).filter(Boolean),
    contractBinding: binding.value.trim() || null,
    requestId: makeRequestId()
  })
  // busy 由结果到达后解除（App 重渲染 lastRun）
  setTimeout(() => { busy.value = false }, 400)
}
</script>

<template>
  <section class="panel wrap">
    <h3>技能（{{ skills.length }}）</h3>
    <p v-if="disabled" class="dim">先连接节点。</p>
    <ul class="skill-list">
      <li v-for="s in skills" :key="s.name" :class="{ sel: selected?.name === s.name }"
          @click="select(s)">
        <strong class="mono">{{ s.name }}</strong>
        <span class="dim">{{ s.description }}</span>
      </li>
    </ul>

    <template v-if="selected">
      <h3 class="mt">参数 <span class="dim mono">{{ selected.name }}</span></h3>
      <div v-if="!jsonMode" class="fields">
        <label v-for="(spec, k) in selected.input_schema?.properties" :key="k" class="field">
          <span class="fname mono">{{ k }}<em v-if="selected.input_schema?.required?.includes(k)" class="req">*</em></span>
          <input v-if="spec.type === 'boolean'" type="checkbox" v-model="form[k]" />
          <textarea v-else-if="spec.type === 'array' || spec.type === 'object'" v-model="form[k]"
                    rows="2" :placeholder="spec.type === 'array' ? '[1,2,3]' : '{&quot;a&quot;:1}'" />
          <input v-else v-model="form[k]" :type="spec.type === 'number' || spec.type === 'integer' ? 'number' : 'text'"
                 :placeholder="spec.description || ''" />
          <small v-if="spec.description" class="dim">{{ spec.description }}</small>
        </label>
      </div>
      <div v-else class="fields">
        <label class="field">
          <span class="fname">params（JSON 对象）<em v-if="selected.input_schema?.required?.length" class="req">
            必填: {{ selected.input_schema.required.join(', ') }}</em></span>
          <textarea v-model="rawJson" rows="5" class="mono" spellcheck="false" />
        </label>
      </div>
      <div class="fields">
        <label class="field"><span class="fname">GeoCards（逗号分隔，可选）</span>
          <input v-model="geocards" class="mono" placeholder="geocard.demo.ndvi-sample" /></label>
        <label class="field"><span class="fname">空间范围 bbox（西,南,东,北，可选）</span>
          <input v-model="bbox" class="mono" placeholder="120.2,30.2,120.8,30.8" /></label>
        <label v-if="supportsBinding" class="field">
          <span class="fname">GAAG 合约绑定（V2，可选）</span>
          <input v-model="binding" class="mono" placeholder="gaag.ndvi" /></label>
      </div>
      <p v-if="formError" class="errline">{{ formError }}</p>
      <button class="primary run" :disabled="busy" @click="submit">
        {{ busy ? '执行中…' : 'geo.execute ▶' }}
      </button>
    </template>

    <template v-if="cards.length">
      <h3 class="mt">节点上的 GeoCards</h3>
      <ul class="cards">
        <li v-for="c in cards" :key="c" class="mono dim">{{ c }}</li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.wrap { padding: 12px 14px; }
.mt { margin-top: 16px; }
.skill-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.skill-list li { padding: 7px 9px; border: 1px solid transparent; border-radius: 9px; cursor: pointer;
  display: flex; flex-direction: column; gap: 1px; }
.skill-list li:hover { border-color: var(--line); }
.skill-list li.sel { border-color: var(--cyan); background: rgba(87, 215, 255, .07); }
.skill-list .dim { font-size: 12px; }
.fields { display: flex; flex-direction: column; gap: 8px; }
.field { display: flex; flex-direction: column; gap: 3px; }
.fname { font-size: 12px; color: var(--dim); }
.req { color: var(--amber); font-style: normal; margin-left: 6px; }
.run { width: 100%; margin-top: 10px; }
.errline { color: var(--rose); font-size: 12.5px; margin: 8px 0 0; }
.cards { margin: 0; padding-left: 18px; font-size: 12px; }
</style>
