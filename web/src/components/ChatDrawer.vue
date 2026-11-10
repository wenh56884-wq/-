<template>
  <!-- AI 助手抽屉：从右侧滑出，移动端占满宽度 -->
  <el-drawer
    v-model="visible"
    :size="drawerSize"
    direction="rtl"
    :with-header="false"
    :modal="true"
    class="chat-drawer"
    @opened="scrollBottom"
  >
    <div class="chat-shell">
      <header class="chat-head">
        <div class="chat-title">
          <img class="chat-logo-img" :src="moyuImg" alt="AI" />
          <div class="chat-title-text">
            <div class="chat-name">启航智能助手</div>
            <div class="chat-sub">LangGraph 多智能体 · 数值经 Critic 回查</div>
          </div>
        </div>
        <button class="icon-btn" type="button" aria-label="AI 记忆" title="AI 记忆"
          @click="toggleMemories">
          <svg viewBox="0 0 24 24" class="ico">
            <path d="M9 4a3 3 0 0 0-3 3v1a3 3 0 0 0 0 6v1a3 3 0 0 0 3 3h1V4H9zM15 4a3 3 0 0 1 3 3v1a3 3 0 0 1 0 6v1a3 3 0 0 1-3 3h-1V4h1z" />
          </svg>
        </button>
        <button class="icon-btn" type="button" aria-label="新对话" title="新对话"
          :disabled="!messages.length" @click="newSession">
          <svg viewBox="0 0 24 24" class="ico"><path d="M12 5v14M5 12h14" /></svg>
        </button>
        <button class="icon-btn" type="button" aria-label="关闭助手" @click="close">
          <svg viewBox="0 0 24 24" class="ico"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </header>

      <div class="chat-alert">
        数值只能来自确定性引擎；回查不过会降级为不含数值的安全话术。
      </div>

      <div ref="listRef" class="chat-body">
        <div v-if="!messages.length" class="chat-empty">
          <div class="chat-empty-title">有什么想问的？</div>
          <div class="chat-empty-sub">直接点下面的示例问题，或在下方输入</div>
          <button
            v-for="q in examples"
            :key="q"
            class="example-btn"
            type="button"
            :disabled="sending"
            @click="send(q)"
          >{{ q }}</button>
        </div>

        <div v-for="msg in messages" :key="msg.id" class="msg-row" :class="msg.role">
          <div class="avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
          <div class="bubble">
            <div v-if="msg.streaming && !msg.text" class="typing">
              <span class="typing-dot"></span>
              <span class="typing-dot"></span>
              <span class="typing-dot"></span>
              <span class="typing-text">{{ msg.status || '意图识别 → 工具取数 → 生成 → Critic 回查…' }}</span>
            </div>
            <div v-else class="bubble-text">{{ msg.text }}<span v-if="msg.streaming" class="stream-caret"></span></div>
            <div v-if="msg.streaming && msg.text" class="stream-status">
              {{ msg.status || '生成中 · 核验通过后生效' }}
            </div>
            <div v-if="msg.citations && msg.citations.length" class="cite-list">
              <div class="cite-title">引用（点开可核对原文）</div>
              <div v-for="c in msg.citations" :key="c.no" class="cite-item">
                <span class="cite-no">[{{ c.no }}]</span>
                <a v-if="c.url" :href="c.url" target="_blank" rel="noopener">{{ c.title }}</a>
                <span v-else class="cite-doc">{{ c.title }}</span>
                <span v-if="c.page" class="cite-pos">第 {{ c.page }} 页</span>
                <span v-else-if="c.chunk_no" class="cite-pos">第 {{ c.chunk_no }} 段</span>
              </div>
            </div>
            <details v-if="msg.role === 'assistant' && !msg.streaming
                           && msg.steps && msg.steps.length" class="trace-box">
              <summary>执行轨迹 · {{ msg.steps.length }} 步</summary>
              <div v-for="step in msg.steps" :key="step.index" class="trace-step">
                <div class="trace-head">
                  <span class="trace-index">{{ step.index }}</span>
                  <span class="trace-tool">{{ step.tool }}</span>
                  <span class="trace-ok" :class="{ bad: !step.ok }">
                    {{ step.ok ? '成功' : '失败' }}
                  </span>
                  <span class="trace-purpose">{{ step.purpose }}</span>
                </div>
                <div v-if="traceArgs(step)" class="trace-args">参数：{{ traceArgs(step) }}</div>
                <div v-if="step.observation" class="trace-obs">{{ step.observation }}</div>
              </div>
            </details>
            <div v-if="msg.role === 'assistant' && !msg.streaming" class="bubble-foot">
              <span v-if="msg.tool" class="chip">{{ msg.tool }}</span>
              <span class="chip">trace {{ msg.trace_id }}</span>
              <span class="chip">{{ msg.term }}</span>
              <span class="chip">{{ msg.cost }} ms</span>
              <span class="chip" :class="msg.degraded ? 'chip-warn' : 'chip-ok'">
                {{ msg.degraded ? '降级话术（未通过回查）' : '数值已回查' }}
              </span>
              <span class="vote-group">
                <button class="vote-btn" type="button" :class="{ active: msg.feedback === 'up' }"
                  :disabled="!!msg.feedback" @click="vote(msg, 'up')">👍</button>
                <button class="vote-btn" type="button" :class="{ active: msg.feedback === 'down' }"
                  :disabled="!!msg.feedback" @click="vote(msg, 'down')">👎</button>
              </span>
            </div>
            <div v-if="msg.role === 'assistant' && !msg.streaming && !msg.error
                        && msg.followups && msg.followups.length" class="followups">
              <button v-for="q in msg.followups" :key="q" class="followup-btn"
                type="button" :disabled="sending" @click="send(q)">{{ q }}</button>
            </div>
            <div v-if="msg.error" class="bubble-err">{{ msg.error }}</div>
          </div>
        </div>
      </div>

      <div class="chat-foot">
        <div v-if="messages.length" class="quick-row">
          <button
            v-for="q in examples.slice(0, 2)"
            :key="q"
            class="example-btn small"
            type="button"
            :disabled="sending"
            @click="send(q)"
          >{{ q }}</button>
          <button class="clear-btn" type="button" :disabled="!messages.length" @click="clearChat">
            清空会话
          </button>
        </div>

        <div class="input-row">
          <textarea
            v-model="query"
            class="chat-input"
            rows="2"
            maxlength="300"
            placeholder="输入问题（Ctrl + Enter 发送）"
            @keydown.ctrl.enter.prevent="send()"
          />
          <button class="send-btn" type="button" :disabled="sending || !query.trim()" @click="send()">
            {{ sending ? '思考中' : '发送' }}
          </button>
        </div>
      </div>

      <!-- 长期记忆面板：盖在对话上，只读本人记忆，可删除 -->
      <div v-if="memoryOpen" class="memory-overlay">
        <div class="memory-head">
          <div>
            <div class="memory-title">AI 记住了什么</div>
            <div class="memory-sub">只显示你自己的长期记忆；删除后不再参与召回</div>
          </div>
          <button class="clear-btn" type="button" :disabled="memoryLoading" @click="loadMemories">
            刷新
          </button>
        </div>
        <div v-if="memoryLoading" class="memory-empty">正在读取记忆…</div>
        <div v-else-if="memoryError" class="memory-empty">{{ memoryError }}</div>
        <div v-else-if="!memories.length" class="memory-empty">
          还没有长期记忆。聊几轮后，助手会记住你的方向、偏好和约束。
        </div>
        <div v-else class="memory-list">
          <div v-for="m in memories" :key="m.id" class="memory-item">
            <div class="memory-item-head">
              <span class="memory-kind">{{ memoryKindText(m.kind) }}</span>
              <span class="memory-importance">重要度 {{ m.importance }}</span>
              <button class="memory-del" type="button" @click="removeMemory(m)">删除</button>
            </div>
            <div class="memory-content">{{ m.content }}</div>
            <div v-if="m.created_at" class="memory-time">{{ m.created_at }}</div>
          </div>
        </div>
        <button class="memory-back" type="button" @click="memoryOpen = false">返回对话</button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import http from '../api/http'
import { clearSession, currentRole } from '../api/http'
import router from '../router'
import moyuImg from '../assets/deepseek-mo-yu.webp'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 父级带着具体问题打开抽屉（页面 AI 问题条 / 空状态点击）：打开即自动发问
  seedQuestion: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue'])

const EXAMPLES = {
  teacher: [
    '有哪些班级可以看？',
    'RJ2201 班有哪些红色预警学生？',
    '给我班级的整体学业情况',
    '班级学生的岗位兴趣和需求差距在哪？',
    '公司制度里报销的住宿标准是多少？',
    '帮我跑一遍班级周报'
  ],
  student: [
    '我这学期的学业预警情况怎么样？',
    '有哪些岗位适合我？为什么？',
    '我和目标岗位之间差哪些能力？',
    '报销的住宿标准是多少？',
    '跑一遍求职体检'
  ]
}

const role = currentRole()
const examples = computed(() => EXAMPLES[role] || EXAMPLES.student)

const visible = ref(props.modelValue)
watch(
  () => props.modelValue,
  (opened) => {
    visible.value = opened
  }
)
watch(visible, (opened) => {
  emit('update:modelValue', opened)
})

// 种子问题：抽屉打开时若带了具体问题，等动画稳定后自动发出（只发一次）。
// 两个来源：① 父级 seedQuestion（问题条 / 空状态点击）；② 窗口事件 qh:ask-ai（页面内「问 AI」按钮）。
const pendingSeed = ref('')

watch(
  [visible, () => props.seedQuestion, pendingSeed],
  ([opened, seed, pending]) => {
    if (!opened || sending.value) return
    const q = String(pending || seed || '').trim()
    if (!q) return
    nextTick(() => {
      setTimeout(() => {
        if (!sending.value && visible.value) {
          pendingSeed.value = ''
          emit('seed-consumed')
          send(q)
        }
      }, 250)
    })
  }
)

// 页面内「问 AI」按钮走这条通道：抽屉常驻在 ShellLayout（不在本次改动范围），
// 用窗口事件开抽屉并带上问题，不动 ShellLayout / 路由 / 接口。
const ASK_EVENT = 'qh:ask-ai'
function onAskEvent(event) {
  pendingSeed.value = String(event?.detail?.question || '').trim()
  visible.value = true
}
onMounted(() => window.addEventListener(ASK_EVENT, onAskEvent))
onBeforeUnmount(() => window.removeEventListener(ASK_EVENT, onAskEvent))

// 抽屉宽度：桌面 420px（不挤主内容），窄屏占满
const drawerSize = computed(() => (window.innerWidth < 768 ? '100%' : '420px'))

const term = ref('2025-2026-2')
const query = ref('')
const sending = ref(false)
const messages = ref([])
const sessionId = ref(null)   // 后端会话：关掉抽屉再打开还能接着聊
const listRef = ref(null)
const memoryOpen = ref(false)
const memories = ref([])
const memoryLoading = ref(false)
const memoryError = ref('')
let seq = 0

function close() {
  memoryOpen.value = false
  visible.value = false
}

function newSession() {
  memoryOpen.value = false
  sessionId.value = null
  messages.value = []
}

function push(roleName, text, extra = {}) {
  seq += 1
  messages.value.push({ id: seq, role: roleName, text, ...extra })
  scrollBottom()
}

// 执行轨迹里的参数展示（模板里不直接调 JSON，避免表达式沙箱限制）
function traceArgs(step) {
  const args = step?.args
  if (!args || typeof args !== 'object' || !Object.keys(args).length) return ''
  try {
    return JSON.stringify(args)
  } catch {
    return ''
  }
}

async function scrollBottom() {
  await nextTick()
  if (listRef.value) {
    listRef.value.scrollTop = listRef.value.scrollHeight
  }
}

// 逐块到达时不必每块都等 nextTick：合并到下一帧再滚，避免抖动
let scrollQueued = false
function scheduleScroll() {
  if (scrollQueued) return
  scrollQueued = true
  requestAnimationFrame(() => {
    scrollQueued = false
    scrollBottom()
  })
}

function apiError(message, status) {
  const err = new Error(message)
  err.status = status
  return err
}

function streamUrl() {
  return `${import.meta.env.DEV ? '/api' : '/'}chat/stream`
}

// 解析 SSE：按空行切帧，逐帧回调 onEvent(eventName, payload)
async function streamChat(payload, onEvent) {
  const token = localStorage.getItem('qh_token')
  const resp = await fetch(streamUrl(), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify(payload)
  })
  if (resp.status === 401) {
    clearSession()
    router.push('/login')
    throw apiError('登录已失效，请重新登录', 401)
  }
  if (!resp.ok || !resp.body) {
    let detail = ''
    try {
      detail = (await resp.json())?.detail || ''
    } catch {
      detail = ''
    }
    throw apiError(typeof detail === 'string' && detail ? detail : `请求失败（${resp.status}）`,
      resp.status)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  const drain = () => {
    let cut
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      let name = 'message'
      const dataLines = []
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) name = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (!dataLines.length) continue
      try {
        onEvent(name, JSON.parse(dataLines.join('\n')))
      } catch {
        // 单帧损坏不影响后续帧
      }
    }
  }
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    drain()
  }
  buffer += decoder.decode()
  drain()
}

// 旧后端没有 /chat/stream 时退回一次性请求，保证演示不中断
async function sendOneShot(pending, content, history, started) {
  try {
    const { data } = await http.post('/chat', {
      query: content,
      term: term.value || null,
      session_id: sessionId.value,
      history
    })
    if (data?.session_id) sessionId.value = data.session_id
    Object.assign(pending, {
      text: data?.answer || '（本次没有返回内容）',
      trace_id: data?.trace_id || '-',
      term: data?.term || term.value,
      degraded: Boolean(data?.degraded),
      tool: data?.tool || '',
      citations: data?.citations || [],
      followups: Array.isArray(data?.suggested_followups) ? data.suggested_followups : [],
      steps: Array.isArray(data?.steps) ? data.steps : [],
      cost: Math.round(performance.now() - started),
      streaming: false,
      status: ''
    })
  } catch (err) {
    const detail = err?.response?.data?.detail || err?.message || '请求失败'
    pending.streaming = false
    pending.status = ''
    pending.error = typeof detail === 'string' ? detail : '请求失败'
  } finally {
    scheduleScroll()
  }
}

async function send(text) {
  const content = String(text ?? query.value).trim()
  if (!content || sending.value) return
  // 带上最近几轮，后端用于理解「为什么」「那他呢」这类追问
  const history = messages.value.slice(-8).map(({ role, text: body }) => ({
    role: role === 'user' ? 'user' : 'assistant',
    text: body
  }))
  push('user', content)
  query.value = ''
  sending.value = true
  const started = performance.now()

  // 助手气泡先占位，随后由流式事件持续填充
  const pending = reactive({
    id: ++seq,
    role: 'assistant',
    text: '',
    streaming: true,
    status: '正在理解问题…',
    trace_id: '-',
    term: term.value,
    degraded: false,
    tool: '',
    citations: [],
    followups: [],
    steps: [],
    feedback: '',
    cost: 0
  })
  messages.value.push(pending)
  scrollBottom()

  let gotDone = false
  try {
    await streamChat({
      query: content,
      term: term.value || null,
      session_id: sessionId.value,
      history
    }, (name, data) => {
      if (name === 'status') {
        pending.status = data?.text || pending.status
        if (data?.tool) pending.tool = data.tool
      } else if (name === 'replace') {
        pending.text = data?.text || ''
      } else if (name === 'delta') {
        pending.text += data?.text || ''
      } else if (name === 'done') {
        gotDone = true
        if (data?.session_id) sessionId.value = data.session_id
        // 最终文本以已过 Critic 的 done.answer 为准
        if (data?.answer) pending.text = data.answer
        pending.trace_id = data?.trace_id || '-'
        pending.term = data?.term || term.value
        pending.degraded = Boolean(data?.degraded)
        pending.tool = data?.tool || pending.tool
        pending.citations = data?.citations || []
        pending.followups = Array.isArray(data?.suggested_followups)
          ? data.suggested_followups : []
        pending.steps = Array.isArray(data?.steps) ? data.steps : []
        pending.cost = Math.round(performance.now() - started)
        pending.status = ''
        pending.streaming = false
      } else if (name === 'error') {
        const message = data?.message || '请求失败'
        pending.error = pending.text ? `生成中断，以上内容未核验：${message}` : message
      }
      scheduleScroll()
    })
    if (!gotDone) {
      pending.streaming = false
      pending.status = ''
      if (!pending.error) {
        pending.error = pending.text
          ? '连接中断：以上是不完整的生成内容，未经过 Critic 核验。'
          : '连接已断开，回答可能不完整。'
      }
    }
  } catch (err) {
    if (!pending.text && (err?.status === 404 || err?.status === 405)) {
      await sendOneShot(pending, content, history, started)
    } else if (err?.status !== 401) {
      pending.streaming = false
      pending.status = ''
      pending.error = err?.message || '请求失败'
      if (pending.text) {
        pending.error = `流式连接中断，以上内容未核验：${pending.error}`
      }
    }
  } finally {
    pending.streaming = false
    sending.value = false
    scrollBottom()
  }
}

// 长期记忆：只读本人记忆（后端按 JWT 身份隔离），删除是软删除
function memoryKindText(kind) {
  const labels = { fact: '事实', preference: '偏好', goal: '目标', constraint: '约束' }
  return labels[kind] || kind || '记忆'
}

async function loadMemories() {
  memoryLoading.value = true
  memoryError.value = ''
  try {
    const { data } = await http.get('/chat/memories')
    const rows = Array.isArray(data?.items) ? data.items : []
    memories.value = rows.map((row) => ({
      id: row['编号'] ?? row.id,
      kind: row['记忆类型'] ?? row.kind ?? 'fact',
      content: row['内容'] ?? row.content ?? '',
      importance: row['重要度'] ?? row.importance ?? 3,
      created_at: row['创建时间'] ?? row.created_at ?? ''
    }))
  } catch (err) {
    memoryError.value = err?.response?.data?.detail || '记忆加载失败，稍后再试'
    memories.value = []
  } finally {
    memoryLoading.value = false
  }
}

async function toggleMemories() {
  memoryOpen.value = !memoryOpen.value
  if (memoryOpen.value) await loadMemories()
}

async function removeMemory(item) {
  if (!item?.id) return
  if (!window.confirm('删除后这条记忆不会再参与召回，确定删除？')) return
  try {
    await http.delete(`/chat/memories/${item.id}`)
    memories.value = memories.value.filter((row) => row.id !== item.id)
  } catch (err) {
    memoryError.value = err?.response?.data?.detail || '删除失败，稍后再试'
  }
}

function clearChat() {
  newSession()
}

// 对话反馈：点赞/点踩落审计，供质量指标统计（失败静默，不打扰对话）
async function vote(msg, rating) {
  if (msg.feedback || !msg.trace_id || msg.trace_id === '-') return
  try {
    await http.post('/chat/feedback', { trace_id: msg.trace_id, rating })
    msg.feedback = rating
  } catch {
    /* 反馈失败不打扰用户 */
  }
}
</script>

<style scoped>
.chat-shell {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f7f8fd;
}

.chat-head {
  flex: 0 0 auto;
  height: 60px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  /* 白毛玻璃：半透明白底 + 背景模糊，消息从头部下方穿过时仍有层次 */
  background: rgba(255, 255, 255, 0.72);
  -webkit-backdrop-filter: blur(18px) saturate(180%);
  backdrop-filter: blur(18px) saturate(180%);
  border-bottom: 1px solid rgba(236, 238, 247, 0.9);
}

.chat-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.chat-logo-img {
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  object-fit: contain;
}

.chat-name {
  font-size: 14px;
  font-weight: 650;
  letter-spacing: -0.01em;
  color: #16181d;
}

.chat-sub {
  font-size: 11px;
  color: #9aa1ad;
}

.icon-btn {
  width: 30px;
  height: 30px;
  margin-left: auto;
  border: 1px solid #e4e7ee;
  border-radius: 10px;
  background: #ffffff;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 150ms ease;
}

.icon-btn:hover {
  background: #f1efff;
}

.ico {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: #5f6672;
  stroke-width: 1.8;
  stroke-linecap: round;
}

.chat-alert {
  flex: 0 0 auto;
  margin: 12px 16px 0;
  padding: 8px 10px;
  font-size: 12px;
  color: #5b5bd6;
  background: #ececfb;
  border: 1px solid #dcdcf9;
  border-radius: 10px;
}

.chat-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 12px 16px;
  scrollbar-width: thin;
}

.chat-empty {
  padding: 24px 0;
}

.chat-empty-title {
  font-size: 14px;
  font-weight: 650;
  color: #16181d;
}

.chat-empty-sub {
  margin-top: 4px;
  font-size: 12px;
  color: #9aa1ad;
}

.example-btn {
  display: block;
  width: 100%;
  margin-top: 8px;
  padding: 9px 11px;
  text-align: left;
  border: 1px solid #e4e7ee;
  border-radius: 10px;
  background: #ffffff;
  color: #5f6672;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.example-btn:hover:not(:disabled) {
  background: #f1efff;
  color: #0058b0;
}

.example-btn:disabled {
  opacity: 0.6;
  cursor: default;
}

.example-btn.small {
  width: auto;
  margin-top: 0;
}

.msg-row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.msg-row.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: 8px;
  background: #5b5bd6;
  color: #fff;
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.msg-row.user .avatar {
  background: #5b5bd6;
  color: #ffffff;
}

.bubble {
  max-width: 80%;
  background: #ffffff;
  border: 1px solid #e4e7ee;
  border-radius: 12px;
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.75;
}

.msg-row.user .bubble {
  /* 用户气泡：Apple 蓝实底，与 AI 白底气泡拉开视觉层级 */
  background: #5b5bd6;
  border-color: transparent;
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(91, 91, 214, 0.2);
}

.bubble-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.stream-caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: -0.15em;
  background: #5b5bd6;
  animation: caret-blink 1s steps(2, start) infinite;
}

.stream-status {
  margin-top: 6px;
  font-size: 11px;
  color: #9aa1ad;
}

.bubble-foot {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.cite-list {
  margin-top: 10px;
  padding: 8px 10px;
  border-left: 2px solid #bfdbfe;
  background: #f8fafc;
  border-radius: 6px;
}
.cite-title { font-size: 11px; color: #64748b; margin-bottom: 4px; }
.cite-item { font-size: 12px; color: #334155; line-height: 1.7; }
.cite-no { color: #5b5bd6; margin-right: 4px; }
.cite-doc { font-weight: 600; }
.cite-pos { color: #64748b; margin-left: 6px; }
.cite-item a { color: #5b5bd6; text-decoration: none; }
.cite-item a:hover { text-decoration: underline; }

/* 自主大脑执行轨迹 */
.trace-box {
  margin-top: 10px;
  padding: 8px 10px;
  border-left: 2px solid #d8b4fe;
  background: #faf5ff;
  border-radius: 6px;
  font-size: 12px;
  color: #3f3f46;
}
.trace-box summary {
  cursor: pointer;
  color: #7e22ce;
  font-weight: 600;
  user-select: none;
}
.trace-step {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed #e9d5ff;
}
.trace-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.trace-index {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #f3e8ff;
  color: #7e22ce;
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.trace-tool {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 600;
  color: #5f6672;
}
.trace-ok { color: #15803d; font-size: 11px; }
.trace-ok.bad { color: #b91c1c; }
.trace-purpose { color: #64748b; }
.trace-args {
  margin-top: 3px;
  color: #0058b0;
  word-break: break-all;
}
.trace-obs {
  margin-top: 3px;
  max-height: 90px;
  overflow: auto;
  color: #71717a;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.chip {
  padding: 1px 6px;
  border: 1px solid #e4e7ee;
  border-radius: 8px;
  background: #ffffff;
  color: #5f6672;
  font-size: 11px;
}

.chip-ok {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
}

.chip-warn {
  background: #fffbeb;
  border-color: #fde68a;
  color: #b45309;
}

.vote-group { margin-left: auto; display: inline-flex; gap: 4px; }

.vote-btn {
  border: 1px solid #e4e7ee;
  border-radius: 8px;
  background: #ffffff;
  font-size: 12px;
  line-height: 1;
  padding: 2px 6px;
  cursor: pointer;
  color: #71717a;
}
.vote-btn:hover:not(:disabled) { border-color: #9aa1ad; }
.vote-btn.active { background: #ececfb; border-color: #93c5fd; color: #4a4ac0; }
.vote-btn:disabled { opacity: 0.55; cursor: default; }

.followups {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.followup-btn {
  border: 1px solid #dcdcf9;
  border-radius: 14px;
  background: #f8fafc;
  color: #4a4ac0;
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
}
.followup-btn:hover:not(:disabled) { background: #ececfb; }
.followup-btn:disabled { opacity: 0.5; cursor: default; }

.bubble-err {
  margin-top: 6px;
  color: #dc2626;
  font-size: 12px;
}

.typing {
  display: flex;
  align-items: center;
  gap: 6px;
}

.typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 8px;
  background: #d4d4d8;
  animation: typing-bounce 1s ease-in-out infinite;
}

.typing-dot:nth-child(2) {
  animation-delay: 0.15s;
}

.typing-dot:nth-child(3) {
  animation-delay: 0.3s;
}

.typing-text {
  margin-left: 6px;
  font-size: 12px;
  color: #9aa1ad;
}

.chat-foot {
  flex: 0 0 auto;
  border-top: 1px solid #e4e7ee;
  background: #ffffff;
  padding: 10px 16px 14px;
}

.quick-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  overflow-x: auto;
}

.clear-btn {
  margin-left: auto;
  border: 1px solid #e4e7ee;
  border-radius: 8px;
  background: #ffffff;
  color: #5f6672;
  font-size: 12px;
  font-family: inherit;
  padding: 6px 10px;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.clear-btn:hover:not(:disabled) {
  background: #fef2f2;
  color: #b91c1c;
}

.input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.chat-input {
  flex: 1 1 auto;
  min-height: 52px;
  max-height: 120px;
  resize: none;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: #eef0f5;
  color: #16181d;
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: box-shadow 150ms ease;
}

.chat-input:focus {
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.25);
}

.send-btn {
  flex: 0 0 auto;
  height: 36px;
  padding: 0 14px;
  border: 0;
  border-radius: 8px;
  background: #5b5bd6;
  color: #ffffff;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 150ms ease, opacity 150ms ease;
}

.send-btn:hover:not(:disabled) {
  background: #4a4ac0;
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

@keyframes caret-blink {
  50% {
    opacity: 0;
  }
}

@keyframes typing-bounce {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.5;
  }
  40% {
    transform: translateY(-3px);
    opacity: 1;
  }
}

/* 长期记忆面板：盖住对话区，保持抽屉内操作，不新开页面 */
.memory-overlay {
  position: absolute;
  inset: 60px 0 0 0;   /* 保留顶部 60px 头部：关闭 / 新对话 / 记忆按钮仍可点 */
  z-index: 20;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 16px;
  background: #f7f8fd;
  overflow-y: auto;
}
.memory-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.memory-title {
  font-size: 16px;
  font-weight: 650;
  color: #16181d;
}
.memory-sub {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: #9aa1ad;
}
.memory-empty {
  padding: 32px 12px;
  text-align: center;
  font-size: 13px;
  color: #9aa1ad;
}
.memory-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.memory-item {
  padding: 12px;
  border: 1px solid #e4e7ee;
  border-radius: 12px;
  background: #fff;
}
.memory-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.memory-kind {
  padding: 1px 8px;
  border-radius: 999px;
  background: #ececfb;
  color: #5b5bd6;
  font-size: 11px;
  font-weight: 600;
}
.memory-importance {
  font-size: 11px;
  color: #9aa1ad;
}
.memory-del {
  margin-left: auto;
  border: 0;
  background: transparent;
  color: #dc2626;
  font-size: 12px;
  cursor: pointer;
}
.memory-content {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: #16181d;
  white-space: pre-wrap;
}
.memory-time {
  margin-top: 6px;
  font-size: 11px;
  color: #9aa1ad;
}
.memory-back {
  flex: 0 0 auto;
  height: 38px;
  margin-top: auto;
  border: 1px solid #e4e7ee;
  border-radius: 10px;
  background: #fff;
  color: #5b5bd6;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

@media (prefers-reduced-motion: reduce) {
  .typing-dot,
  .stream-caret {
    animation: none;
  }

  .example-btn,
  .icon-btn,
  .clear-btn,
  .send-btn,
  .chat-input {
    transition: none;
  }
}
</style>
