<script setup>
/** LLM 会话面板（面板类插件）：多配置档 + 工具集=GeoMCP + 执行类人在环。
 *  · 端点/密钥/模型按**配置档**管理（可多档、可切换、可测连），存 localStorage。
 *  · 不内置任何模型；端点不可用时面板明说。
 *  · 发送区固定在底部、常驻可见，Enter 发送 / Shift+Enter 换行。 */
import { computed, nextTick, ref } from 'vue'
import { GeoMCPError } from '../lib/geomcp.js'
import { buildTools, needsConfirm, pendingCalls, runTool } from '../lib/agent.js'
import { activeProfile, loadProfiles, saveProfiles, setActive, testProfile } from '../lib/llm.js'

const props = defineProps({ caps: Object, clientFactory: Function, activeUrl: String })

const profiles = ref(loadProfiles())
const current = ref(activeProfile())
const messages = ref([])
const draft = ref('')
const busy = ref(false)
const error = ref('')
const showSettings = ref(false)
const tests = ref({})          // profileId -> {ok, message}
const scroller = ref(null)
const MAX_ROUNDS = 4

const tools = computed(() => buildTools(props.caps))

function pickProfile(id) {
  setActive(id)
  current.value = activeProfile()
  messages.value = []          // 换模型=换会话上下文，避免半截对话串味
  error.value = ''
}
function updateProfile(p) {
  const list = profiles.value.map((x) => (x.id === p.id ? { ...x } : x))
  profiles.value = list
  saveProfiles(list)
  current.value = activeProfile()
}
function addProfile() {
  const id = `p${Date.now().toString(36)}`
  profiles.value = [...profiles.value, { id, name: '新配置', baseUrl: '', key: '', model: '' }]
  saveProfiles(profiles.value)
}
function removeProfile(id) {
  if (profiles.value.length <= 1) return
  profiles.value = profiles.value.filter((p) => p.id !== id)
  saveProfiles(profiles.value)
  if (current.value.id === id) pickProfile(profiles.value[0].id)
}
async function runTest(p) {
  tests.value = { ...tests.value, [p.id]: { ok: null, message: '测试中…' } }
  const r = await testProfile(p)
  tests.value = { ...tests.value, [p.id]: r }
}

function toApi() {
  return messages.value
    .filter((m) => ['user', 'assistant', 'tool'].includes(m.role))
    .map((m) => (m.role === 'assistant'
      ? { role: 'assistant', content: m.content || null, tool_calls: m.tool_calls || undefined }
      : { role: m.role, content: m.content, tool_call_id: m.tool_call_id }))
}

async function scrollDown() {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

function askUser(callMsg) {
  return new Promise((resolve) => { callMsg.resolve = resolve })
}
function decide(callMsg, ok) {
  callMsg.status = ok ? 'approved' : 'denied'
  callMsg.resolve?.(ok)
}

async function loop(round) {
  if (round > MAX_ROUNDS) {
    messages.value.push({ role: 'assistant', content: `（已达 ${MAX_ROUNDS} 轮工具上限，停止循环）` })
    await scrollDown()
    return
  }
  const p = current.value
  const res = await fetch(`${String(p.baseUrl || '').replace(/\/$/, '')}/chat/completions`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(p.key ? { authorization: `Bearer ${p.key}` } : {})
    },
    body: JSON.stringify({ model: p.model, messages: toApi(), tools: tools.value })
  })
  if (!res.ok) throw new Error(`LLM 端点 HTTP ${res.status}：${(await res.text()).slice(0, 200)}`)
  const m = (await res.json()).choices?.[0]?.message
  if (!m) throw new Error('LLM 响应缺少 choices[0].message')
  messages.value.push({ role: 'assistant', content: m.content || '', tool_calls: m.tool_calls })
  await scrollDown()
  const calls = pendingCalls(m)
  if (!calls.length) return
  for (const c of calls) {
    const callMsg = { role: 'call', call: c, status: needsConfirm(c.name) ? 'pending' : 'auto' }
    messages.value.push(callMsg)
    await scrollDown()
    if (callMsg.status === 'pending') {
      const ok = await askUser(callMsg)
      if (!ok) {
        messages.value.push({ role: 'tool', tool_call_id: c.id, content: '用户拒绝执行该调用' })
        continue
      }
      callMsg.status = 'approved'
    }
    try {
      const client = props.clientFactory(props.activeUrl)
      const out = await runTool(client, c.name, c.args)
      callMsg.result = out
      messages.value.push({ role: 'tool', tool_call_id: c.id,
        content: JSON.stringify(out).slice(0, 4000) })
    } catch (e) {
      callMsg.result = { error: e.message }
      messages.value.push({ role: 'tool', tool_call_id: c.id,
        content: `错误${e instanceof GeoMCPError ? ` ${e.code}` : ''}：${e.message}` })
    }
    await scrollDown()
  }
  await loop(round + 1)
}

async function send() {
  const text = draft.value.trim()
  if (!text || busy.value) return
  if (!props.activeUrl) { error.value = '先连接一个节点'; return }
  if (!current.value.baseUrl) { error.value = '先配置 LLM 端点（右上 ⚙）'; showSettings.value = true; return }
  draft.value = ''
  error.value = ''
  busy.value = true
  messages.value.push({ role: 'user', content: text })
  await scrollDown()
  try {
    await loop(0)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
    await scrollDown()
  }
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
}
</script>

<template>
  <aside class="chat panel">
    <div class="head">
      <h3>会话 <span class="dim">（工具 = GeoMCP · 执行需确认）</span></h3>
      <select class="switcher mono" :value="current.id" @change="pickProfile($event.target.value)"
              :title="`${current.baseUrl} · ${current.model}`">
        <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.name }}｜{{ p.model || '未设模型' }}</option>
      </select>
      <button title="模型配置" @click="showSettings = true">⚙ 配置</button>
    </div>

    <div v-if="showSettings" class="settings">
      <div v-for="p in profiles" :key="p.id" class="profile">
        <div class="prow">
          <input type="radio" :checked="p.id === current.id" @change="pickProfile(p.id)" title="设为当前" />
          <input v-model="p.name" placeholder="配置名" class="pname" @change="updateProfile(p)" />
          <button :disabled="profiles.length <= 1" title="删除该配置" @click="removeProfile(p.id)">删除</button>
        </div>
        <label>端点 <input v-model="p.baseUrl" class="mono" placeholder="http://host:port/v1"
                           @change="updateProfile(p)" /></label>
        <label>密钥 <input v-model="p.key" type="password" class="mono" placeholder="可选（只存本机）"
                           @change="updateProfile(p)" /></label>
        <label>模型 <input v-model="p.model" class="mono" placeholder="model id"
                           @change="updateProfile(p)" /></label>
        <div class="prow">
          <button @click="runTest(p)">测连</button>
          <span v-if="tests[p.id]" class="tag" :class="tests[p.id].ok === true ? 'ok' : tests[p.id].ok === false ? 'err' : ''">
            {{ tests[p.id].message }}
          </span>
        </div>
      </div>
      <div class="prow">
        <button @click="addProfile">＋ 新增配置</button>
        <button class="primary" @click="showSettings = false">收起</button>
      </div>
      <p class="dim note">存 localStorage；不内置模型。执行类工具一律先展示参数、人工确认后才发出。</p>
    </div>

    <div ref="scroller" class="msgs">
      <p v-if="!messages.length" class="dim hint">
        问节点点什么，例如：<em>这个节点有哪些技能？跑一个样例并把结果画到地图上。</em><br />
        只读工具（列能力/看合约）自动执行；执行与规划会先让你确认。
      </p>
      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
        <template v-if="m.role === 'call'">
          <div class="callcard">
            <div class="crow">
              <strong class="mono">{{ m.call.name }}</strong>
              <em class="tag" :class="m.status === 'denied' ? 'err' : m.status === 'pending' ? '' : 'ok'">
                {{ m.status === 'pending' ? '待确认' : m.status === 'approved' ? '已确认'
                  : m.status === 'denied' ? '已拒绝' : '只读·自动' }}
              </em>
            </div>
            <pre>{{ JSON.stringify(m.call.args, null, 1) }}</pre>
            <div v-if="m.status === 'pending'" class="btns">
              <button class="primary" @click="decide(m, true)">确认执行</button>
              <button @click="decide(m, false)">拒绝</button>
            </div>
          </div>
        </template>
        <pre v-else-if="m.role === 'tool'" class="toolout">{{ m.content }}</pre>
        <p v-else>{{ m.content }}</p>
      </div>
      <p v-if="busy" class="dim thinking">思考中…</p>
    </div>

    <p v-if="error" class="errline">{{ error }}</p>
    <div class="composer">
      <textarea v-model="draft" rows="2"
                placeholder="在这儿输入消息 —— Enter 发送，Shift+Enter 换行"
                @keydown="onKeydown" />
      <div class="sendcol">
        <button class="primary send" :disabled="busy || !draft.trim()" @click="send">
          {{ busy ? '…' : '发送' }}
        </button>
        <small class="dim mono" :title="current.baseUrl">{{ current.model || '未设模型' }}</small>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.chat { display: flex; flex-direction: column; width: 420px; max-width: 94vw; height: 100%;
  position: fixed; right: 12px; top: 70px; bottom: 12px; z-index: 40; }
.head { display: flex; align-items: center; gap: 8px; padding: 9px 12px;
  border-bottom: 1px solid var(--line); }
.head h3 { margin: 0; font-size: 13px; color: var(--cyan); }
.switcher { margin-left: auto; max-width: 170px; }
.settings { border-bottom: 1px solid var(--line); padding: 10px 12px; max-height: 46vh; overflow: auto; }
.profile { border: 1px solid var(--line); border-radius: 9px; padding: 8px 9px; margin-bottom: 8px;
  display: flex; flex-direction: column; gap: 5px; }
.prow { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.pname { flex: 1; }
.settings label { display: flex; gap: 6px; align-items: center; font-size: 12px; color: var(--dim); }
.settings label input { flex: 1; }
.msgs { flex: 1; overflow: auto; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
.hint { font-size: 12.5px; line-height: 1.7; }
.hint em { color: var(--cyan); font-style: normal; }
.msg.user { display: flex; justify-content: flex-end; }
.msg.user p { background: rgba(87, 215, 255, .12); border: 1px solid rgba(87, 215, 255, .32);
  border-radius: 11px; padding: 7px 11px; margin: 0; max-width: 86%; white-space: pre-wrap; }
.msg.assistant p { margin: 0; white-space: pre-wrap; }
.callcard { border: 1px solid var(--amber); border-radius: 10px; padding: 7px 9px;
  background: rgba(255, 198, 92, .06); display: flex; flex-direction: column; gap: 5px; }
.crow { display: flex; align-items: center; gap: 8px; }
.callcard pre, .toolout { margin: 0; font-size: 11.5px; white-space: pre-wrap; word-break: break-all;
  max-height: 180px; overflow: auto; }
.toolout { border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; color: var(--dim); }
.btns { display: flex; gap: 8px; }
.composer { display: flex; gap: 8px; padding: 9px 12px; border-top: 1px solid var(--line);
  background: #0A1420; align-items: stretch; }
.composer textarea { flex: 1; resize: vertical; min-height: 40px; }
.sendcol { display: flex; flex-direction: column; gap: 4px; align-items: center; }
.send { min-width: 74px; }
.errline { color: var(--rose); font-size: 12px; margin: 4px 12px; }
.note { font-size: 11.5px; margin: 4px 0 0; }
.thinking { font-size: 12px; }
</style>
