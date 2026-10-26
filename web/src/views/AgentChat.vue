<template>
  <div class="page chat-page">
    <el-alert class="trust-bar" type="info" :closable="false" show-icon
      title="智能助手：数值只能来自确定性引擎，回答经 Critic 逐条回查；回查不过会降级为不含数值的安全话术" />

    <el-card shadow="never" class="chat-card">
      <template #header>
        <div class="chat-head">
          <span class="card-title" style="margin: 0">多智能体问答（LangGraph）</span>
          <el-input v-model="term" size="small" placeholder="学期" style="width: 150px" />
          <span class="chat-meta">共 {{ messages.length }} 条 · 角色 {{ roleText }}</span>
          <el-button size="small" :disabled="!messages.length" @click="clearChat">清空会话</el-button>
        </div>
      </template>

      <div ref="listRef" class="chat-body">
        <el-empty v-if="!messages.length" description="在下方输入问题，或直接点下面的示例问题试试" />
        <div v-for="msg in messages" :key="msg.id" class="msg-row" :class="msg.role">
          <div class="avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
          <div class="bubble">
            <div class="bubble-text">{{ msg.text }}</div>
            <div v-if="msg.role === 'assistant'" class="bubble-foot">
              <el-tag size="small" effect="plain">trace {{ msg.trace_id }}</el-tag>
              <el-tag size="small" effect="plain">{{ msg.term }}</el-tag>
              <el-tag size="small" effect="plain">{{ msg.cost }} ms</el-tag>
              <el-tag v-if="msg.degraded" size="small" type="warning" effect="dark">
                降级话术（未通过 Critic 回查，不含数值）
              </el-tag>
              <el-tag v-else size="small" type="success" effect="plain">数值已回查</el-tag>
            </div>
            <div v-if="msg.error" class="bubble-err">{{ msg.error }}</div>
          </div>
        </div>

        <div v-if="sending" class="msg-row assistant">
          <div class="avatar">AI</div>
          <div class="bubble typing">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-text">意图识别 → 工具取数 → 生成 → Critic 回查…</span>
          </div>
        </div>
      </div>

      <div class="quick-row">
        <span class="quick-label">示例：</span>
        <el-button
          v-for="q in examples"
          :key="q"
          size="small"
          round
          :disabled="sending"
          @click="send(q)"
        >{{ q }}</el-button>
      </div>

      <div class="input-row">
        <el-input
          v-model="query"
          type="textarea"
          :rows="3"
          maxlength="300"
          show-word-limit
          resize="none"
          placeholder="输入你的问题（Ctrl + Enter 发送）"
          @keydown.ctrl.enter.prevent="send()"
        />
        <el-button type="primary" :loading="sending" :disabled="!query.trim()" @click="send()">
          发送
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'

import http from '../api/http'
import { currentRole } from '../api/http'

const EXAMPLES = {
  teacher: [
    'AI2201 班有哪些红色预警学生？',
    '给我 AI2201 班的整体学业情况',
    '班级学生的岗位兴趣和岗位需求差距在哪？'
  ],
  student: [
    '我这学期的学业预警情况怎么样？',
    '有哪些岗位适合我？为什么？',
    '我和目标岗位之间差哪些能力？'
  ]
}

const role = currentRole()
const roleText = computed(() => (role === 'teacher' ? '教师' : '学生'))
const examples = computed(() => EXAMPLES[role] || EXAMPLES.student)

const term = ref('2025-2026-2')
const query = ref('')
const sending = ref(false)
const messages = ref([])
const listRef = ref(null)
let seq = 0

function push(roleName, text, extra = {}) {
  seq += 1
  messages.value.push({ id: seq, role: roleName, text, ...extra })
  scrollBottom()
}

async function scrollBottom() {
  await nextTick()
  if (listRef.value) {
    listRef.value.scrollTop = listRef.value.scrollHeight
  }
}

async function send(text) {
  const content = String(text ?? query.value).trim()
  if (!content || sending.value) return
  if (text) {
    query.value = content
  }
  push('user', content)
  query.value = ''
  sending.value = true
  const started = performance.now()
  try {
    const { data } = await http.post('/chat', { query: content, term: term.value || null })
    push('assistant', data?.answer || '（本次没有返回内容）', {
      trace_id: data?.trace_id || '-',
      term: data?.term || term.value,
      degraded: Boolean(data?.degraded),
      cost: Math.round(performance.now() - started)
    })
  } catch (err) {
    const status = err?.response?.status
    const detail = err?.response?.data?.detail || err?.message || '请求失败'
    // 401/403 已由拦截器统一跳登录，这里不再重复提示
    if (status !== 401 && status !== 403) {
      push('assistant', '这次没能拿到回答。', {
        trace_id: '-',
        term: term.value,
        degraded: false,
        cost: Math.round(performance.now() - started),
        error: typeof detail === 'string' ? detail : '请求失败'
      })
    }
  } finally {
    sending.value = false
  }
}

function clearChat() {
  messages.value = []
}
</script>

<style scoped>
.trust-bar {
  margin-bottom: 12px;
}

.chat-head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.chat-meta {
  margin-left: auto;
  font-size: 12px;
  color: #86909c;
}

.chat-body {
  height: 420px;
  overflow-y: auto;
  border: 1px solid #e5e6eb;
  border-radius: 6px;
  padding: 12px;
  background: #fafbfc;
}

.msg-row {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
  animation: msg-in 0.25s ease-out;
}

.msg-row.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  border-radius: 50%;
  background: var(--qh-red);
  color: #fff;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.msg-row.user .avatar {
  background: #4e5969;
}

.bubble {
  max-width: 76%;
  background: #fff;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  line-height: 1.8;
}

.msg-row.user .bubble {
  background: #f2f3f5;
}

.bubble-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble-foot {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.bubble-err {
  margin-top: 6px;
  color: var(--qh-red);
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
  border-radius: 50%;
  background: #c9cdd4;
  animation: typing-bounce 1s infinite;
}

.typing-dot:nth-child(2) {
  animation-delay: 0.15s;
}

.typing-dot:nth-child(3) {
  animation-delay: 0.3s;
}

.typing-text {
  margin-left: 8px;
  font-size: 12px;
  color: #86909c;
}

.quick-row {
  margin: 12px 0 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.quick-label {
  font-size: 12px;
  color: #86909c;
}

.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

@keyframes msg-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
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
    transform: translateY(-4px);
    opacity: 1;
  }
}
</style>
