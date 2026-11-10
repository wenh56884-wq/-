<template>
  <div class="page bento-page asst-page" :class="{ 'is-chat': mode === 'chat' }">
    <!-- 顶部模式切换：对话（AI 多智能体） / 联网搜索（直接检索外部网页） -->
    <div class="asst-mode-tabs">
      <button class="mode-tab" type="button" :class="{ 'is-on': mode === 'chat' }"
        @click="switchMode('chat')">
        <svg viewBox="0 0 24 24" class="mode-ico" aria-hidden="true">
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
        </svg>
        对话
      </button>
      <button class="mode-tab" type="button" :class="{ 'is-on': mode === 'search' }"
        @click="switchMode('search')">
        <svg viewBox="0 0 24 24" class="mode-ico" aria-hidden="true">
          <path d="M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35M11 3a8 8 0 0 1 0 16M3 11h16M11 3c2.5 2 2.5 14 0 16M11 3c-2.5 2-2.5 14 0 16" />
        </svg>
        联网搜索
      </button>
    </div>
    <template v-if="mode === 'chat'">
    <div class="asst-shell">
      <!-- ---------- 左栏：会话列表 ---------- -->
      <aside class="asst-sessions">
        <div class="sess-head">
          <span class="sess-head-title">会话</span>
          <button class="sess-new" type="button" :disabled="sending" @click="newSession">
            <svg viewBox="0 0 24 24" class="mini-ico"><path d="M12 5v14M5 12h14" /></svg>
            新对话
          </button>
        </div>

        <div v-loading="sessionsLoading" class="sess-list">
          <button v-for="s in sessions" :key="s.id" type="button" class="sess-item"
            :class="{ 'is-active': s.id === sessionId }" @click="openSession(s.id)">
            <span class="sess-title">{{ s.title || '未命名会话' }}</span>
            <span class="sess-meta">{{ s.updated_at || s.created_at || '' }}</span>
          </button>
          <div v-if="!sessionsLoading && !sessions.length" class="sess-empty">
            还没有历史会话，先问一句试试
          </div>
        </div>
      </aside>

      <!-- ---------- 中栏：对话 ---------- -->
      <section class="asst-main">
        <header class="asst-head">
          <div class="asst-id">
            <img class="asst-logo" :src="moyuImg" alt="AI" />
            <div class="asst-id-text">
              <div class="asst-name">启航智能助手</div>
              <div class="asst-sub">LangGraph 多智能体 · 数值经 Critic 回查</div>
            </div>
          </div>
          <button class="ghost-btn" type="button" @click="searchOpen = !searchOpen">
            {{ searchOpen ? '收起来源' : '查看来源' }}
          </button>
        </header>

        <div ref="listRef" class="asst-body">
          <div v-if="!messages.length" class="asst-empty">
            <div class="empty-title">有什么想问的？</div>
            <div class="empty-sub">数值只能来自确定性引擎；需要外部事实时开启「智能搜索」</div>
            <div class="empty-qs">
              <button v-for="q in examples" :key="q" type="button" class="empty-q"
                :disabled="sending" @click="send(q)">{{ q }}</button>
            </div>
          </div>

          <div v-for="msg in messages" :key="msg.id" class="msg" :class="msg.role">
            <div class="avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
            <div class="bubble">
              <div v-if="msg.streaming && !msg.text" class="typing">
                <span class="dot"></span><span class="dot"></span><span class="dot"></span>
                <span class="typing-text">{{ msg.status || '意图识别 → 工具取数 → 生成 → Critic 回查…' }}</span>
              </div>
              <div v-else class="bubble-text">{{ msg.text }}<span v-if="msg.streaming" class="caret"></span></div>

              <div v-if="msg.streaming && msg.text" class="stream-status">
                {{ msg.status || '生成中 · 核验通过后生效' }}
              </div>

              <div v-if="msg.error" class="bubble-error">{{ msg.error }}</div>

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
                  <span class="trace-index">{{ step.index }}</span>
                  <span class="trace-tool">{{ step.tool }}</span>
                  <span class="trace-ok" :class="{ bad: !step.ok }">{{ step.ok ? '成功' : '失败' }}</span>
                  <span class="trace-purpose">{{ step.purpose }}</span>
                </div>
              </details>

              <div v-if="msg.role === 'assistant' && !msg.streaming" class="bubble-foot">
                <span v-if="msg.tool" class="chip">{{ msg.tool }}</span>
                <span v-if="msg.trace_id && msg.trace_id !== '-'" class="chip">
                  trace {{ msg.trace_id }}
                </span>
                <span v-if="msg.cost" class="chip">{{ msg.cost }} ms</span>
                <span v-if="msg.text" class="chip"
                  :class="msg.degraded ? 'chip-warn' : 'chip-ok'">
                  {{ msg.degraded ? '降级话术（未通过回查）' : '数值已回查' }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <footer class="asst-compose">
          <div class="compose-box">
            <textarea v-model="query" class="compose-input" rows="1"
              placeholder="给启航智能助手发送消息，Enter 发送 / Shift+Enter 换行"
              @keydown.enter.exact.prevent="send()" />

            <div class="compose-foot">
              <div class="toggles">
                <button type="button" class="toggle" :class="{ 'is-on': deepThinking }"
                  :title="deepThinkingHint" @click="toggleDeep">
                  <span class="toggle-dot" />深度思考
                </button>
                <button type="button" class="toggle" :class="{ 'is-on': webSearch }"
                  title="开启后，提问会同时检索外部网页，右侧展示来源摘要" @click="toggleWeb">
                  <span class="toggle-dot" />智能搜索
                </button>
              </div>
              <button class="send-btn" type="button"
                :disabled="sending || !query.trim()" @click="send()">
                {{ sending ? '生成中' : '发送' }}
              </button>
            </div>
          </div>
          <div class="compose-note">{{ composeNote }}</div>
        </footer>
      </section>

      <!-- ---------- 右栏：优先展示本次回答的引用，编号与正文 [n] 一致 ---------- -->
      <aside v-if="searchOpen" class="asst-search">
        <div class="search-head">
          <span class="search-title">{{ currentCitations.length ? '引用来源' : '搜索结果' }}</span>
          <button class="icon-btn" type="button" aria-label="收起" @click="searchOpen = false">
            <svg viewBox="0 0 24 24" class="mini-ico"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>

        <div v-loading="searchLoading" class="search-body">
          <div v-if="searchError" class="search-hint is-warn">{{ searchError }}</div>

          <template v-else-if="currentCitations.length">
            <div class="search-meta">
              本次回答引用 · {{ currentCitations.length }} 条 · 与正文 [n] 编号一致
            </div>
            <button v-for="c in currentCitations" :key="c.no" type="button" class="search-item"
              @click="c.url && openUrl(c.url)">
              <div class="search-item-title">{{ c.title }}</div>
              <!-- 知识库片段没有外链，别渲染成可点却打不开的按钮 -->
              <div v-if="c.url" class="search-item-host">{{ hostOf(c.url) }}</div>
              <div v-else class="search-item-host">知识库片段 · 无外链</div>
              <div v-if="c.snippet" class="search-item-snippet">{{ c.snippet }}</div>
              <span class="search-item-no">[{{ c.no }}]</span>
            </button>
          </template>

          <template v-else-if="searchResults.length">
            <div class="search-meta">
              {{ searchAnswer.engine_version || 'web-v1' }}
              <template v-if="searchAnswer.provider"> · {{ searchAnswer.provider }}</template>
              · {{ searchResults.length }} 条
            </div>
            <div class="search-hint is-warn">
              本次回答未带引用，以下为独立检索结果，与回答引用并非同一批
            </div>
            <button v-for="(r, i) in searchResults" :key="r.url + i" type="button" class="search-item"
              @click="openUrl(r.url)">
              <div class="search-item-title">{{ r.title || r.url }}</div>
              <div class="search-item-host">{{ hostOf(r.url) }}</div>
              <div v-if="r.snippet" class="search-item-snippet">{{ r.snippet }}</div>
              <span class="search-item-no">[{{ i + 1 }}]</span>
            </button>
          </template>

          <div v-else class="search-hint">
            开启「智能搜索」后提问，这里会显示外部网页来源与摘要。
          </div>
        </div>
      </aside>
    </div>
    </template>
    <template v-else>
      <WebSearch embedded />
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'

import http, { clearSession, currentRole } from '../api/http'
import router from '../router'
import moyuImg from '../assets/deepseek-mo-yu.webp'
import WebSearch from './WebSearch.vue'

const EXAMPLES = {
  teacher: [
    '有哪些班级可以看？',
    'RJ2201 班有哪些红色预警学生？',
    '给我班级的整体学业情况',
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

// 两种模式：对话（AI 多智能体）/ 联网搜索（直接检索外部网页）
const mode = ref('chat')

const term = ref('2025-2026-2')
const query = ref('')
const sending = ref(false)
const messages = ref([])
const sessionId = ref(null)
const listRef = ref(null)
let seq = 0

// 会话列表
const sessions = ref([])
const sessionsLoading = ref(false)

// 两个模式开关
const deepThinking = ref(false)
const webSearch = ref(false)

// 右侧搜索来源
const searchOpen = ref(false)
const searchLoading = ref(false)
const searchError = ref('')
const searchAnswer = ref({})
const searchResults = computed(() => searchAnswer.value?.results || [])

// 右栏优先展示「当前回答」的引用：编号与正文里的 [n] 同源，不会各编各的号。
// 只有本次回答没带引用时才退回独立检索结果，并明确标注两者并非同一批。
const currentCitations = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const m = messages.value[i]
    if (m.role === 'assistant' && (m.citations || []).length) return m.citations
  }
  return []
})

const deepThinkingHint = computed(() =>
  '深度思考：后端 ChatIn 目前没有该参数，开启只会带上标记；' +
  '要真正生效需后端接入 brain 多步规划'
)

const composeNote = computed(() => {
  const bits = []
  if (webSearch.value) bits.push('智能搜索已开：提问会同时检索外部网页，来源在右侧')
  if (deepThinking.value) bits.push('深度思考已开（等待后端支持 brain 多步规划）')
  return bits.length ? bits.join(' · ') : '数值类回答一律经 Critic 回查，不通过会降级为不含数字的安全话术'
})

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch (err) {
    return ''
  }
}

function openUrl(url) {
  if (url) window.open(url, 'target_blank', 'noopener')
}

function toggleWeb() {
  webSearch.value = !webSearch.value
  if (webSearch.value) searchOpen.value = true
}

function toggleDeep() {
  deepThinking.value = !deepThinking.value
}

function switchMode(target) {
  mode.value = target
  // 切到搜索模式时收起右栏来源，避免两套面板叠在一起
  if (target === 'search') searchOpen.value = false
}

async function scrollBottom() {
  await nextTick()
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
}

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
    } catch (err) {
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
      } catch (err) {
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

// 旧后端没有 /chat/stream 时退回一次性请求
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
      degraded: Boolean(data?.degraded),
      tool: data?.tool || '',
      citations: data?.citations || [],
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

// 联网搜索：与聊天并行发起，结果单独进右栏，不阻塞回答
async function runWebSearch(text) {
  searchLoading.value = true
  searchError.value = ''
  try {
    const { data } = await http.get('/web/search', { params: { q: text, top_k: 8 } })
    if (data?.configured === false) {
      searchAnswer.value = {}
      searchError.value = data.error || '当前未配置联网搜索密钥，没有联网能力'
    } else if (data?.error) {
      searchAnswer.value = {}
      searchError.value = data.error
    } else {
      searchAnswer.value = data || {}
      searchOpen.value = true
    }
  } catch (err) {
    searchAnswer.value = {}
    const status = err?.response?.status
    searchError.value = status === 404
      ? '搜索接口尚未就绪（后端未实现 /web/search）'
      : '联网搜索失败'
  } finally {
    searchLoading.value = false
  }
}

async function send(text) {
  const content = String(text ?? query.value).trim()
  if (!content || sending.value) return

  const history = messages.value.slice(-8).map(({ role: r, text: body }) => ({
    role: r === 'user' ? 'user' : 'assistant',
    text: body
  }))

  push('user', content)
  query.value = ''
  sending.value = true
  const started = performance.now()

  // 联网搜索与聊天并行，右栏结果不阻塞回答
  if (webSearch.value) runWebSearch(content)

  const pending = reactive({
    id: ++seq,
    role: 'assistant',
    text: '',
    streaming: true,
    status: '正在理解问题…',
    trace_id: '-',
    degraded: false,
    tool: '',
    citations: [],
    steps: [],
    cost: 0,
    error: ''
  })
  messages.value.push(pending)
  scrollBottom()

  let gotDone = false
  try {
    await streamChat({
      query: content,
      term: term.value || null,
      session_id: sessionId.value,
      history,
      // 后端 ChatIn 暂无该字段（Pydantic 会忽略未知字段）；接入后即生效
      deep_thinking: Boolean(deepThinking.value)
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
        if (data?.answer) pending.text = data.answer
        pending.trace_id = data?.trace_id || '-'
        pending.degraded = Boolean(data?.degraded)
        pending.tool = data?.tool || pending.tool
        pending.citations = data?.citations || []
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
      if (pending.text) pending.error = `流式连接中断，以上内容未核验：${pending.error}`
    }
  } finally {
    pending.streaming = false
    sending.value = false
    scrollBottom()
    loadSessions()
  }
}

function push(roleName, text, extra = {}) {
  seq += 1
  messages.value.push({ id: seq, role: roleName, text, ...extra })
  scrollBottom()
}

function newSession() {
  sessionId.value = null
  messages.value = []
  searchAnswer.value = {}
  searchError.value = ''
}

function toBubble(m) {
  seq += 1
  return {
    id: seq,
    role: m.role === 'user' ? 'user' : 'assistant',
    text: m.text || '',
    streaming: false,
    status: '',
    trace_id: m.trace_id || '-',
    degraded: Boolean(m.degraded),
    tool: m.tool || '',
    citations: m.citations || [],
    steps: [],
    cost: 0,
    error: ''
  }
}

async function openSession(sid) {
  if (sending.value) return
  try {
    const { data } = await http.get(`/chat/sessions/${sid}`)
    sessionId.value = sid
    messages.value = (data?.messages || []).map(toBubble)
    scrollBottom()
  } catch (err) {
    messages.value = []
  }
}

async function loadSessions() {
  sessionsLoading.value = true
  try {
    const { data } = await http.get('/chat/sessions', { params: { limit: 30 } })
    sessions.value = Array.isArray(data?.items) ? data.items : []
  } catch (err) {
    sessions.value = []
  } finally {
    sessionsLoading.value = false
  }
}

onMounted(loadSessions)
</script>

<style scoped>
/* 三栏铺满：100vh - 顶栏(64) - AI 问法条(~44) - 页面上下内边距(48) ≈ 156，留 4px 余量 */
.asst-page {
  min-height: 540px;
}

/* 对话模式：铺满视口（顶栏 + AI 问法条 + 模式条 + 上下内边距） */
.asst-page.is-chat {
  height: calc(100vh - 200px);
  min-height: 540px;
}

/* ---------- 顶部模式切换条 ---------- */
.asst-mode-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.mode-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border: 1px solid var(--bento-border-strong);
  border-radius: 999px;
  background: #ffffff;
  font-size: 14px;
  color: var(--bento-sub);
  cursor: pointer;
  transition:
    border-color 180ms var(--bento-ease),
    background-color 180ms var(--bento-ease),
    color 180ms var(--bento-ease);
}

.mode-tab:hover {
  border-color: var(--bento-accent);
}

.mode-tab.is-on {
  border-color: var(--bento-accent);
  background: var(--bento-accent-soft);
  color: var(--bento-accent);
}

.mode-ico {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.asst-shell {
  /* 窄屏时右栏转 absolute，必须有这个定位上下文，否则会相对 body 飘走 */
  position: relative;
  display: flex;
  height: 100%;
  gap: 14px;
}

/* ---------- 左栏 ---------- */
.asst-sessions {
  display: flex;
  flex-direction: column;
  flex: 0 0 220px;
  min-width: 0;
  border: 1px solid var(--bento-border);
  border-radius: var(--bento-radius);
  background: var(--bento-surface);
  box-shadow: var(--bento-shadow);
  overflow: hidden;
}

.sess-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 14px 14px 10px;
  border-bottom: 1px solid var(--bento-border);
}

.sess-head-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--bento-text);
}

.sess-new {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border: 1px solid var(--bento-border-strong);
  border-radius: 999px;
  background: #ffffff;
  font-size: 13.5px;
  color: var(--bento-sub);
  cursor: pointer;
  transition:
    border-color 180ms var(--bento-ease),
    color 180ms var(--bento-ease),
    background-color 180ms var(--bento-ease);
}

.sess-new:hover:not(:disabled) {
  border-color: var(--bento-accent);
  background: var(--bento-accent-soft);
  color: var(--bento-accent);
}

.sess-new:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.sess-list {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 8px;
}

.sess-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: var(--bento-radius-sm);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background-color 180ms var(--bento-ease);
}

.sess-item:hover {
  background: #f7f8fd;
}

.sess-item.is-active {
  border-color: #dcdcf9;
  background: var(--bento-accent-soft);
}

.sess-title {
  font-size: 14px;
  line-height: 1.5;
  color: var(--bento-text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.sess-item.is-active .sess-title {
  color: var(--bento-accent);
  font-weight: 600;
}

.sess-meta {
  font-size: 13px;
  color: var(--bento-mute);
}

.sess-empty {
  padding: 22px 12px;
  font-size: 14px;
  line-height: 1.8;
  color: var(--bento-mute);
  text-align: center;
}

/* ---------- 中栏 ---------- */
.asst-main {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-width: 0;
  border: 1px solid var(--bento-border);
  border-radius: var(--bento-radius);
  background: var(--bento-surface);
  box-shadow: var(--bento-shadow);
  overflow: hidden;
}

.asst-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--bento-border);
}

.asst-id {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.asst-logo {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  border-radius: 9px;
  object-fit: cover;
  background: var(--bento-accent-soft);
}

.asst-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--bento-text);
}

.asst-sub {
  font-size: 13px;
  color: var(--bento-mute);
}

.ghost-btn {
  padding: 5px 12px;
  border: 1px solid var(--bento-border-strong);
  border-radius: 999px;
  background: #ffffff;
  font-size: 13.5px;
  color: var(--bento-sub);
  cursor: pointer;
}

.ghost-btn:hover {
  border-color: var(--bento-accent);
  color: var(--bento-accent);
}

.asst-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 18px;
}

.asst-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 10px;
  text-align: center;
}

.empty-title {
  font-size: 18px;
  font-weight: 650;
  color: var(--bento-text);
}

.empty-sub {
  font-size: 14px;
  color: var(--bento-mute);
}

.empty-qs {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 10px;
  max-width: 620px;
}

.empty-q {
  padding: 7px 14px;
  border: 1px solid var(--bento-border);
  border-radius: 999px;
  background: #ffffff;
  font-size: 14px;
  color: var(--bento-sub);
  cursor: pointer;
  transition:
    border-color 180ms var(--bento-ease),
    background-color 180ms var(--bento-ease),
    color 180ms var(--bento-ease);
}

.empty-q:hover:not(:disabled) {
  border-color: var(--bento-accent);
  background: var(--bento-accent-soft);
  color: var(--bento-accent);
}

/* 消息 */
.msg {
  display: flex;
  gap: 10px;
  margin-bottom: 18px;
}

.msg.user {
  flex-direction: row-reverse;
}

.avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: 9px;
  background: var(--bento-accent-soft);
  font-size: 13px;
  font-weight: 600;
  color: var(--bento-accent);
}

.msg.user .avatar {
  /* Apple 蓝实底，替代原来的蓝紫渐变 */
  background: #5b5bd6;
  color: #ffffff;
}

.bubble {
  max-width: min(78%, 720px);
  padding: 11px 14px;
  border-radius: 14px;
  background: #f7f8fa;
  font-size: 14px;
  line-height: 1.85;
  color: var(--bento-text);
  word-break: break-word;
}

.msg.user .bubble {
  background: #5b5bd6;
  color: #ffffff;
}

.bubble-text {
  white-space: pre-wrap;
}

.caret {
  display: inline-block;
  width: 6px;
  height: 14px;
  margin-left: 2px;
  background: var(--bento-accent);
  vertical-align: -2px;
  animation: blink 1s steps(2, start) infinite;
}

@keyframes blink {
  to {
    visibility: hidden;
  }
}

.typing {
  display: flex;
  align-items: center;
  gap: 5px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #5b5bd6;
  animation: bounce 1.2s infinite;
}

.dot:nth-child(2) {
  animation-delay: 0.15s;
}

.dot:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes bounce {
  0%, 60%, 100% {
    transform: translateY(0);
  }
  30% {
    transform: translateY(-4px);
  }
}

.typing-text {
  margin-left: 4px;
  font-size: 13.5px;
  color: var(--bento-mute);
}

.stream-status {
  margin-top: 6px;
  font-size: 13px;
  color: var(--bento-mute);
}

.bubble-error {
  margin-top: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  background: #fff2f0;
  font-size: 13.5px;
  color: #cf1322;
}

.cite-list {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--bento-border-strong);
}

.cite-title {
  margin-bottom: 5px;
  font-size: 13px;
  color: var(--bento-mute);
}

.cite-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 14px;
  line-height: 1.8;
}

.cite-no {
  color: var(--bento-accent);
  font-weight: 600;
}

.cite-item a {
  color: var(--bento-accent);
  text-decoration: none;
  word-break: break-all;
}

.cite-item a:hover {
  text-decoration: underline;
}

.cite-pos {
  font-size: 12.5px;
  color: var(--bento-mute);
}

.trace-box {
  margin-top: 8px;
  font-size: 13.5px;
  color: var(--bento-sub);
}

.trace-box summary {
  cursor: pointer;
  color: var(--bento-mute);
}

.trace-step {
  display: flex;
  align-items: baseline;
  gap: 7px;
  margin-top: 6px;
  padding-left: 4px;
}

.trace-index {
  width: 16px;
  flex: 0 0 16px;
  color: var(--bento-mute);
}

.trace-tool {
  font-weight: 600;
  color: var(--bento-text);
}

.trace-ok {
  color: #0f9d58;
}

.trace-ok.bad {
  color: #cf1322;
}

.trace-purpose {
  color: var(--bento-mute);
}

.bubble-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 9px;
}

.chip {
  padding: 2px 8px;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid var(--bento-border);
  font-size: 12.5px;
  color: var(--bento-mute);
}

.chip-ok {
  border-color: #cfe9d6;
  color: #0f9d58;
}

.chip-warn {
  border-color: #ffd8bf;
  color: #d46b08;
}

/* 输入区 */
.asst-compose {
  padding: 12px 18px 14px;
  border-top: 1px solid var(--bento-border);
}

.compose-box {
  border: 1px solid var(--bento-border-strong);
  border-radius: 14px;
  background: #ffffff;
  transition: border-color 180ms var(--bento-ease);
}

.compose-box:focus-within {
  border-color: var(--bento-accent);
}

.compose-input {
  display: block;
  width: 100%;
  min-height: 52px;
  max-height: 140px;
  padding: 12px 14px 6px;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.7;
  color: var(--bento-text);
}

.compose-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 10px 10px;
}

.toggles {
  display: flex;
  gap: 8px;
}

.toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid var(--bento-border-strong);
  border-radius: 999px;
  background: #ffffff;
  font-size: 13.5px;
  color: var(--bento-sub);
  cursor: pointer;
  transition:
    border-color 180ms var(--bento-ease),
    background-color 180ms var(--bento-ease),
    color 180ms var(--bento-ease);
}

.toggle-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #d9dbe6;
  transition: background-color 180ms var(--bento-ease);
}

.toggle.is-on {
  border-color: var(--bento-accent);
  background: var(--bento-accent-soft);
  color: var(--bento-accent);
}

.toggle.is-on .toggle-dot {
  background: var(--bento-accent);
}

.send-btn {
  padding: 7px 18px;
  border: none;
  border-radius: 999px;
  background: #5b5bd6;
  font-size: 14px;
  font-weight: 600;
  color: #ffffff;
  cursor: pointer;
  transition: opacity 300ms var(--bento-ease), background-color 300ms var(--bento-ease);
}

.send-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.compose-note {
  margin-top: 7px;
  font-size: 13px;
  color: var(--bento-mute);
}

/* ---------- 右栏 ---------- */
.asst-search {
  display: flex;
  flex-direction: column;
  flex: 0 0 310px;
  min-width: 0;
  border: 1px solid var(--bento-border);
  border-radius: var(--bento-radius);
  background: var(--bento-surface);
  box-shadow: var(--bento-shadow);
  overflow: hidden;
}

.search-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--bento-border);
}

.search-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--bento-text);
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
}

.icon-btn:hover {
  background: #eef0f5;
}

.mini-ico {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: var(--bento-sub);
  stroke-width: 2;
  stroke-linecap: round;
}

.search-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 10px;
}

.search-meta {
  padding: 2px 4px 8px;
  font-size: 13px;
  color: var(--bento-mute);
}

.search-item {
  position: relative;
  display: block;
  width: 100%;
  margin-bottom: 8px;
  padding: 10px 12px;
  border: 1px solid var(--bento-border);
  border-radius: var(--bento-radius-sm);
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 180ms var(--bento-ease),
    background-color 180ms var(--bento-ease);
}

.search-item:hover {
  border-color: #dcdcf9;
  background: #fbfbff;
}

.search-item-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.6;
  color: var(--bento-text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  /* 右上角角标是 [n]，比纯数字宽，留出避让空间 */
  padding-right: 28px;
}

.search-item-host {
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--bento-accent);
}

.search-item-snippet {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--bento-mute);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.search-item-no {
  position: absolute;
  top: 8px;
  right: 10px;
  /* 编号改成 [n] 后变宽，字号也顺势抬一档 */
  font-size: 12px;
  color: var(--bento-mute);
  font-variant-numeric: tabular-nums;
}

.search-hint {
  padding: 18px 12px;
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--bento-mute);
  text-align: center;
}

.search-hint.is-warn {
  color: #d46b08;
}

/* ---------- 响应式：窄屏先收右栏，再收左栏 ---------- */
@media (max-width: 1279px) {
  .asst-search {
    position: absolute;
    right: 24px;
    width: 310px;
    max-height: calc(100% - 40px);
    z-index: 5;
  }
}

@media (max-width: 1023px) {
  .asst-sessions {
    display: none;
  }

  .asst-page.is-chat {
    height: calc(100vh - 120px);
  }
}

@media (max-width: 767px) {
  .bubble {
    max-width: 88%;
  }

  .asst-search {
    position: static;
    width: auto;
  }
}
</style>
