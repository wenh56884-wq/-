<template>
  <div class="gr">
    <!-- ==================== 开始页 ==================== -->
    <section v-if="phase === 'start'" class="gr-start">
      <header class="gr-start-head">
        <div class="gr-eyebrow">GROUP INTERVIEW · 无领导小组讨论</div>
        <h2 class="gr-h1">群面房间</h2>
        <p class="gr-lead">
          你 + 3 位 AI 候选人，12 分钟抢一个结论。没有标准答案，只有谁推动了讨论、谁只是附和。
        </p>
      </header>

      <div class="gr-start-grid">
        <div class="gr-panel">
          <label class="gr-field-label" for="gr-job">目标岗位</label>
          <el-select
            id="gr-job"
            v-model="jobId"
            class="gr-select"
            filterable
            clearable
            remote
            :remote-method="searchJobs"
            :loading="jobsLoading"
            placeholder="搜索或选择岗位（全行业，支持输入关键词）"
          >
            <el-option v-for="j in jobs" :key="j.id" :value="j.id" :label="jobLabel(j)" />
          </el-select>
          <p v-if="jobsError" class="gr-hint warn">
            岗位列表加载失败，将按「{{ defaultJobTitle }}」开局
          </p>
          <p v-else class="gr-hint">
            默认按行业各取一个代表岗位（共 {{ jobTotal }} 个行业）；输入关键词可搜全部岗位。
          </p>

          <button class="gr-start-btn" type="button" :disabled="starting" @click="startGroup">
            {{ starting ? '正在生成议题…' : '进入会议室' }}
          </button>
        </div>

        <aside class="gr-rules">
          <div class="gr-rules-title">本场规则</div>
          <ul class="gr-rule-list">
            <li><b>12 分钟</b><span>倒计时归零后建议直接做总结</span></li>
            <li><b>4 人</b><span>你与 3 位 AI 候选人同场，没有主持人</span></li>
            <li><b>要形成一致结论</b><span>评分看的是推动与收敛，不是谁话多</span></li>
            <li v-if="ttsReady || sttSupported"><b>语音模式</b><span>{{ voiceRuleHint }}</span></li>
            <li><b>冷场救援</b><span>1 分钟没人接话，小航会在旁边递一句推进建议</span></li>
          </ul>
        </aside>
      </div>

      <div class="gr-roster">
        <div v-for="c in roster" :key="c.id" class="gr-roster-card" :class="{ me: c.me }">
          <span class="gr-roster-avatar" :style="rosterStyle(c)">{{ c.initial }}</span>
          <div>
            <b>{{ c.name }}</b>
            <span>{{ c.role }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- ==================== 进行中 ==================== -->
    <section v-else-if="phase === 'live'" class="gr-live">
      <header class="gr-topic">
        <div class="gr-topic-main">
          <div class="gr-eyebrow">GROUP · 议题</div>
          <h2 class="gr-topic-title">{{ topic.title || '群面议题' }}</h2>
          <p v-if="topic.brief" class="gr-topic-brief">{{ topic.brief }}</p>
          <div v-if="keywords.length" class="gr-chips">
            <span v-for="k in keywords" :key="k" class="gr-chip">#{{ k }}</span>
          </div>
        </div>
        <div class="gr-timer" :class="{ over: timeUp }">
          <b>{{ clock }}</b>
          <span>{{ timeUp ? '时间到，建议做总结' : '剩余时间' }}</span>
        </div>
      </header>

      <div ref="streamRef" class="gr-stream" aria-live="polite">
        <div v-for="t in turns" :key="t.key" class="gr-msg" :class="t.speaker === 'student' ? 'me' : 'ai'">
          <span class="gr-avatar" :style="avatarStyle(t)">{{ initialOf(t) }}</span>
          <div class="gr-bubble-wrap">
            <div class="gr-msg-meta">
              <b>{{ t.name }}</b>
              <span v-if="roleOf(t)" class="gr-msg-role">{{ roleOf(t) }}</span>
              <span v-if="atText(t.at)" class="gr-msg-at">{{ atText(t.at) }}</span>
              <span v-if="speakingKey === t.key" class="gr-msg-role gr-speaking-tag">播报中</span>
            </div>
            <div class="gr-bubble" :class="{ speaking: speakingKey === t.key }">{{ t.text }}</div>
          </div>
        </div>

        <div v-if="typingName" class="gr-msg ai">
          <span class="gr-avatar" :style="typingStyle">{{ typingName.charAt(0) }}</span>
          <div class="gr-bubble-wrap">
            <div class="gr-msg-meta"><b>{{ typingName }}</b><span class="gr-msg-role">正在发言</span></div>
            <div class="gr-bubble gr-typing"><i></i><i></i><i></i></div>
          </div>
        </div>

        <div v-if="!turns.length && !typingName" class="gr-stream-empty">
          会议刚开始。你可以先破冰，也可以点「听他们说一轮」看看别人怎么开口。
        </div>
      </div>

      <footer class="gr-composer">
        <el-input
          v-model="draft"
          class="gr-input"
          type="textarea"
          :rows="3"
          maxlength="500"
          resize="none"
          :placeholder="listening ? '聆听中…识别的文字会出现在这里' : '抢话发言：先给判断，再给理由，最后收一句结论（Ctrl + Enter 发送）'"
          @keydown.enter.ctrl.prevent="speak"
        />
        <div v-if="listening" class="gr-mic-hint live">
          <i class="gr-mic-dot"></i>聆听中…说完点「发言」发出，或再点「停止聆听」结束
        </div>
        <p v-else-if="!sttSupported" class="gr-mic-hint dim">{{ sttHint }}，文字发言不受影响。</p>
        <div class="gr-composer-actions">
          <el-button type="primary" :loading="sending" :disabled="busy || !draft.trim()" @click="speak">
            发言
          </el-button>
          <el-button
            v-if="sttSupported"
            :type="listening ? 'warning' : 'default'"
            :disabled="sending || finishing"
            @click="toggleListen"
          >
            {{ listening ? '停止聆听' : '语音发言' }}
          </el-button>
          <el-button v-if="ttsReady" :disabled="sending || finishing" @click="toggleTts">
            播报{{ ttsOn ? '开' : '关' }}
          </el-button>
          <el-button :loading="aiRunning" :disabled="busy" @click="listenRound">
            听他们说一轮
          </el-button>
          <el-button :disabled="busy" @click="finish">结束并评估</el-button>
          <span class="gr-turn-count">已发生 {{ turns.length }} 条发言</span>
        </div>
      </footer>
    </section>

    <!-- ==================== 评估报告 ==================== -->
    <section v-else class="gr-report">
      <header class="gr-report-head">
        <div class="gr-report-id">
          <div class="gr-eyebrow">GROUP REPORT · 群面评估</div>
          <h2 class="gr-h1">你在这一局里的位置</h2>
        </div>
        <button class="gr-again" type="button" @click="restart">再练一场</button>
      </header>

      <div class="gr-role" :style="roleStyle">
        <div class="gr-role-badge">
          <span class="gr-role-dot" :style="{ background: roleInfo.color }"></span>
          <b>{{ roleInfo.label }}</b>
        </div>
        <p v-if="roleInfo.reason" class="gr-role-reason">{{ roleInfo.reason }}</p>
        <p v-else class="gr-role-reason">本场角色由发言占比、新观点与收敛动作机械判定。</p>
      </div>

      <div class="gr-score-grid">
        <div v-for="s in scoreCards" :key="s.key" class="gr-score-card">
          <div class="gr-ring">
            <svg viewBox="0 0 72 72" aria-hidden="true">
              <circle cx="36" cy="36" r="30" class="gr-ring-bg" />
              <circle
                cx="36"
                cy="36"
                r="30"
                class="gr-ring-fg"
                :style="{ strokeDasharray: `${(s.value || 0) / 100 * 188.5} 188.5`, stroke: scoreTone(s.value) }"
              />
            </svg>
            <div class="gr-ring-text">
              <b>{{ s.value == null ? '—' : Math.round(s.value) }}</b>
            </div>
          </div>
          <span class="gr-score-label">{{ s.label }}</span>
        </div>
      </div>
      <p class="gr-score-note">「表达」为贡献 / 协作 / 结构 / 表达四项加权后的综合分。</p>

      <section class="gr-metrics">
        <div class="gr-sec-head">
          <span class="gr-sec-title">发言占比</span>
          <span class="gr-sec-sub">你 vs 其他三位候选人</span>
        </div>
        <div class="gr-ratio" role="img" :aria-label="`你占 ${talkPct}% 的发言字数`">
          <div class="gr-ratio-me" :style="{ width: talkPct + '%' }">
            <span v-if="talkPct >= 12">你 {{ talkPct }}%</span>
          </div>
          <div class="gr-ratio-other" :style="{ width: otherPct + '%' }">
            <span v-if="otherPct >= 12">其他人 {{ otherPct }}%</span>
          </div>
        </div>
        <div class="gr-metric-chips">
          <div v-for="m in metricFacts" :key="m.label" class="gr-metric-chip">
            <span>{{ m.label }}</span>
            <b>{{ m.value }}</b>
          </div>
        </div>
      </section>

      <div class="gr-lists">
        <section class="gr-list-card">
          <div class="gr-sec-head"><span class="gr-sec-title">做对的</span><span class="gr-sec-sub">highlights</span></div>
          <ul v-if="highlights.length" class="gr-list good">
            <li v-for="(h, i) in highlights" :key="'h' + i"><span class="mark">✓</span><span>{{ h }}</span></li>
          </ul>
          <p v-else class="gr-list-empty">本场没有记录到明显亮点。</p>
        </section>

        <section class="gr-list-card">
          <div class="gr-sec-head"><span class="gr-sec-title">该改的</span><span class="gr-sec-sub">improvements</span></div>
          <ul v-if="improvements.length" class="gr-list warn">
            <li v-for="(m, i) in improvements" :key="'m' + i"><span class="mark">!</span><span>{{ m }}</span></li>
          </ul>
          <p v-else class="gr-list-empty">没有明显扣分动作。</p>
        </section>
      </div>

      <section class="gr-drill">
        <div class="gr-drill-tag">下一场只练这一个动作</div>
        <p class="gr-drill-text">{{ evalResult?.next_drill || '下一次讨论，前 3 句内先给出一个可被讨论的框架，再补理由。' }}</p>
      </section>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'

import http from '../../api/http'
import { useVoice, SPOKEN_SPEAKERS } from '../../composables/useVoice'
import { useIdleHint } from '../../composables/useIdleHint'

// 候选人底色与契约 CANDIDATES 保持一致；后端返回的 name 优先
const CANDIDATES = [
  { id: 'ice', name: '林一', role: '破冰者', color: '#38bdf8' },
  { id: 'data', name: '赵敏', role: '数据派', color: '#34d399' },
  { id: 'spark', name: '王锐', role: '搅局者', color: '#fb923c' }
]

const DEFAULT_JOB_TITLE = '数据分析岗'

// 角色四色：推动者 / 贡献者 / 跟随者 / 沉默者
const ROLE_META = {
  leader: { label: '推动者', color: '#3b82f6' },
  contributor: { label: '贡献者', color: '#10b981' },
  follower: { label: '跟随者', color: '#f59e0b' },
  silent: { label: '沉默者', color: '#6b7280' }
}

const SPEAKER_META = {
  host: { name: '主持人', role: '议题', color: '#64748b' },
  moderator: { name: '主持人', role: '议题', color: '#64748b' },
  system: { name: '主持人', role: '议题', color: '#64748b' }
}

const phase = ref('start')
const jobs = ref([])
const jobsLoading = ref(false)
const jobsError = ref('')
const jobId = ref(null)
const defaultJobTitle = DEFAULT_JOB_TITLE

const starting = ref(false)
const topic = ref({})
const state = ref(null)
const openingTurn = ref(null)

const draft = ref('')
const sending = ref(false)
const aiRunning = ref(false)
const finishing = ref(false)
const typingName = ref('')
const streamRef = ref(null)

const evalResult = ref(null)
const secondsLeft = ref(0)

// ---------------- 语音（浏览器原生，能力不可用时自动隐藏入口） ----------------
const voice = useVoice()
const { ttsReady, ttsOn, speakingKey, listening, sttSupported, sttHint } = voice

const voiceRuleHint = computed(() => {
  if (ttsReady && sttSupported) return 'AI 候选人开口发言，你也可以用麦克风说'
  if (ttsReady) return 'AI 候选人开口发言（浏览器语音合成）'
  return '可用麦克风发言（Chrome / Edge + HTTPS）'
})

// 已朗读去重：AI 候选人的同一句话只读一次（开场白并入 state.turns 时 key 会变，靠文本兜底）
const spokenKeys = new Set()
const spokenTexts = new Set()

function speakFreshTurns(list) {
  if (phase.value !== 'live') return
  const fresh = list.filter((t) => {
    if (spokenKeys.has(t.key)) return false
    spokenKeys.add(t.key)
    return true
  })
  if (!ttsOn.value) return
  if (listening.value) return // 麦克风开着时不朗读，否则 AI 的声音会被当成你的发言
  // 只读三位 AI 候选人；主持人/议题（"面试官的语音"）按用户要求不读
  const batch = fresh
    .filter((t) => SPOKEN_SPEAKERS.includes(t.speaker) && !spokenTexts.has(t.text))
  for (const t of batch) spokenTexts.add(t.text)
  if (batch.length) voice.speakTurns(batch.map((t) => ({ key: t.key, text: t.text, speakerId: t.speaker })))
}

function toggleTts() {
  ttsOn.value = !ttsOn.value
  if (!ttsOn.value) voice.stopSpeak()
}

function onVoiceText(finalText, interimText) {
  draft.value = (finalText + interimText).trim()
}

function onVoiceError(code) {
  voice.stopListen()
  draft.value = draft.value.trim()
  ElMessage.warning(
    code === 'not-allowed'
      ? '麦克风权限被拒绝，请在浏览器地址栏允许麦克风后重试'
      : '语音识别暂时不可用，可以改用文字发言'
  )
}

function toggleListen() {
  if (listening.value) {
    const text = voice.stopListen()
    if (text) draft.value = text
    else ElMessage.warning('这次没有识别到内容，可以改用文字发言')
    return
  }
  voice.stopSpeak() // 先停播报，避免朗读声被麦克风收进去
  const ok = voice.startListen({ onText: onVoiceText, onError: onVoiceError })
  if (ok) draft.value = ''
}

// ---- 冷场提示：60 秒没接话，AI 宠物（小航）按局面递一句推进建议 ----
// 确定性文案、不发模型请求；每场最多 2 条；打字/发言/听一轮都会重新计时。
const idleHint = useIdleHint({
  timeoutMs: 60000,
  maxHints: 2,
  pick: (n) => {
    if (phase.value !== 'live' || busy.value) return null
    const spoke = Array.isArray(state.value?.turns)
      && state.value.turns.some((t) => t?.speaker === 'student')
    if (!spoke) {
      const openers = [
        '会议室安静了。可以抢个框架开场：「我先说个思路——把这个问题拆成成本、风险、落地三块」，先开口的人往往定调。',
        '还没人接话的话，把议题复述成一句你的判断，再问大家同不同意，两句话就能破冰。'
      ]
      return openers[n % openers.length]
    }
    if (timeUp.value) {
      return '时间到了。主动收尾：共识一句、分歧一句、下一步一句——考官看的就是谁敢收。'
    }
    const advances = [
      '试试收敛：把分歧点摆上桌，问一句「我们能不能先在这两点上达成一致？」',
      '给一个折中方案：吸收数据派的事实，回应搅局者的风险，落成可执行的一步。',
      '主动点名推进：「王锐刚才提的风险，我们在方案里怎么规避？」——被你点到的人会接话。'
    ]
    return advances[n % advances.length]
  }
})

watch(phase, (p) => {
  if (p === 'live') idleHint.restart()
  else idleHint.stop()
})

watch(draft, (text) => {
  if (String(text).trim()) idleHint.poke()
})

let tickTimer = null
let gapTimer = null
let disposed = false

const busy = computed(() => sending.value || aiRunning.value || finishing.value)
const keywords = computed(() => (Array.isArray(topic.value?.keywords) ? topic.value.keywords.filter(Boolean) : []))

const roster = computed(() => [
  ...CANDIDATES.map((c) => ({ id: c.id, name: c.name, role: c.role, initial: c.name.charAt(0), color: c.color })),
  { id: 'student', name: '你', role: '候选人', initial: '你', color: '#3b82f6', me: true }
])

const turns = computed(() => {
  const list = Array.isArray(state.value?.turns) ? state.value.turns : []
  const mapped = list
    .map((t, i) => {
      const text = typeof t?.text === 'string' ? t.text.trim() : ''
      const speaker = t?.speaker || ''
      return {
        key: `turn-${t?.idx ?? i}-${i}`,
        speaker,
        name: t?.name || speakerName(speaker),
        text,
        at: t?.at
      }
    })
    .filter((t) => t.text)
  if (!mapped.length && openingTurn.value) return [openingTurn.value]
  return mapped
})

const timeUp = computed(() => secondsLeft.value <= 0)
const clock = computed(() => {
  const s = Math.max(0, secondsLeft.value)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})

const roleInfo = computed(() => {
  const role = evalResult.value?.role || {}
  const meta = ROLE_META[role.id] || { label: '未评定', color: '#6b7280' }
  return { label: role.label || meta.label, color: meta.color, reason: role.reason || '' }
})

const roleStyle = computed(() => ({
  borderColor: hexToRgba(roleInfo.value.color, 0.4),
  background: hexToRgba(roleInfo.value.color, 0.09)
}))

const scoreCards = computed(() => {
  const s = evalResult.value?.scores || {}
  return [
    { key: 'contribution', label: '贡献', value: numOf(s.contribution) },
    { key: 'collaboration', label: '协作', value: numOf(s.collaboration) },
    { key: 'structure', label: '结构', value: numOf(s.structure) },
    { key: 'overall', label: '表达', value: numOf(s.overall) }
  ]
})

const metrics = computed(() => evalResult.value?.metrics || {})
const talkPct = computed(() => {
  const ratio = numOf(metrics.value.talk_ratio)
  if (ratio == null) return 0
  return Math.round(Math.min(1, Math.max(0, ratio)) * 100)
})
const otherPct = computed(() => 100 - talkPct.value)

const metricFacts = computed(() => {
  const m = metrics.value
  const list = []
  const chars = numOf(m.chars)
  if (chars != null) list.push({ label: '发言字数', value: `${Math.round(chars)} 字` })
  const points = numOf(m.new_points)
  if (points != null) list.push({ label: '新观点', value: `${points} 个` })
  const converge = numOf(m.converge_marks)
  if (converge != null) list.push({ label: '收敛动作', value: `${converge} 次` })
  const first = numOf(m.first_speak_position)
  if (first != null) list.push({ label: '首次发言', value: `进度 ${Math.round(Math.min(1, Math.max(0, first)) * 100)}%` })
  const asked = numOf(m.question_asked)
  if (asked != null) list.push({ label: '主动提问', value: `${asked} 次` })
  return list
})

const highlights = computed(() => (Array.isArray(evalResult.value?.highlights) ? evalResult.value.highlights : []))
const improvements = computed(() => (Array.isArray(evalResult.value?.improvements) ? evalResult.value.improvements : []))

const typingStyle = computed(() => {
  const c = CANDIDATES.find((item) => item.name === typingName.value)
  return { background: c?.color || '#475569' }
})

function numOf(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function hexToRgba(hex, alpha) {
  const h = String(hex || '').replace('#', '')
  if (h.length !== 6) return `rgba(148, 163, 184, ${alpha})`
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function scoreTone(v) {
  if (v == null) return '#334155'
  if (v >= 75) return '#10b981'
  if (v >= 60) return '#f59e0b'
  return '#ef4444'
}

function jobLabel(j) {
  if (!j) return ''
  return [j.title, j.company, j.city].filter(Boolean).join(' · ')
}

function speakerMeta(speaker) {
  if (!speaker) return SPEAKER_META.host
  if (speaker === 'student') return { name: '你', role: '候选人', color: '#3b82f6' }
  const c = CANDIDATES.find((item) => item.id === speaker)
  if (c) return { name: c.name, role: c.role, color: c.color }
  return SPEAKER_META[speaker] || { name: '候选人', role: '', color: '#64748b' }
}

function speakerName(speaker) {
  return speakerMeta(speaker).name
}

function initialOf(t) {
  const name = String(t?.name || speakerMeta(t?.speaker).name || '?').trim()
  return name.charAt(0) || '?'
}

function avatarStyle(t) {
  if (t?.speaker === 'student') {
    return { background: 'linear-gradient(135deg, #1d4ed8 0%, #3b82f6 100%)' }
  }
  return { background: speakerMeta(t?.speaker).color }
}

function rosterStyle(c) {
  return c.me ? { background: 'linear-gradient(135deg, #1d4ed8 0%, #3b82f6 100%)' } : { background: c.color }
}

function roleOf(t) {
  if (!t) return ''
  if (t.speaker === 'student') return '你'
  return speakerMeta(t.speaker).role || ''
}

function atText(at) {
  const n = numOf(at)
  if (n == null || n < 0) return ''
  const total = Math.floor(n)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

function normalizeOpening(opening) {
  if (!opening) return null
  if (typeof opening === 'string') {
    return { key: 'opening', speaker: 'host', name: '主持人', text: opening, at: null }
  }
  const text = typeof opening.text === 'string' ? opening.text : ''
  if (!text.trim()) return null
  return {
    key: 'opening',
    speaker: opening.speaker || 'host',
    name: opening.name || speakerName(opening.speaker || 'host'),
    text,
    at: opening.at
  }
}

function startTimer() {
  stopTimer()
  const minutes = numOf(topic.value?.minutes)
  secondsLeft.value = Math.round((minutes && minutes > 0 ? minutes : 12) * 60)
  tickTimer = setInterval(() => {
    if (secondsLeft.value > 0) secondsLeft.value -= 1
    if (secondsLeft.value <= 0) stopTimer()
  }, 1000)
}

function stopTimer() {
  if (tickTimer) {
    clearInterval(tickTimer)
    tickTimer = null
  }
}

function waitGap(ms) {
  return new Promise((resolve) => {
    gapTimer = setTimeout(() => {
      gapTimer = null
      resolve()
    }, ms)
  })
}

async function scrollBottom() {
  await nextTick()
  const el = streamRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function applyEvaluation(evaluation) {
  if (evaluation && evaluation.role) {
    evalResult.value = evaluation
    phase.value = 'report'
    stopTimer()
  }
}

function errText(err) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  return err?.message || '请求失败'
}

// 初始用「行业分层」样本：岗位表头部是成片的 IT 岗，按编号取前 20 条会
// 让人以为岗位库只有计算机岗。diverse=1 让 82 个行业各出一个代表。
// 输入关键词时走远程搜索，覆盖全库。
const jobTotal = ref(0)
let jobSeq = 0

async function searchJobs(keyword) {
  const kw = String(keyword || '').trim()
  const seq = ++jobSeq
  jobsLoading.value = true
  try {
    if (!kw) {
      await loadJobs()
      return
    }
    const { data } = await http.get('/interview/jobs',
      { params: { limit: 30, keyword: kw } })
    if (seq !== jobSeq) return          // 已有更新的搜索，丢弃旧结果
    jobTotal.value = data?.total || 0
    jobs.value = (Array.isArray(data?.items) ? data.items : []).filter((j) => j && j.id != null)
  } catch (err) {
    if (seq === jobSeq) {
      jobs.value = []
      jobsError.value = errText(err)
    }
  } finally {
    if (seq === jobSeq) jobsLoading.value = false
  }
}

async function loadJobs() {
  jobsLoading.value = true
  jobsError.value = ''
  try {
    const { data } = await http.get('/interview/jobs', { params: { diverse: 1, limit: 60 } })
    const items = Array.isArray(data?.items) ? data.items : []
    jobs.value = items.filter((j) => j && j.id != null)
    jobTotal.value = data?.total || jobs.value.length
    if (jobs.value.length && jobId.value == null) jobId.value = jobs.value[0].id
  } catch (err) {
    jobs.value = []
    jobsError.value = errText(err)
  } finally {
    jobsLoading.value = false
  }
}

async function startGroup() {
  if (starting.value) return
  starting.value = true
  try {
    const job = jobs.value.find((j) => j.id === jobId.value)
    const { data } = await http.post('/interview/lab/group/start', {
      job_id: jobId.value ?? null,
      job_title: job?.title || DEFAULT_JOB_TITLE
    })
    topic.value = data?.topic || {}
    state.value = data?.state || null
    openingTurn.value = normalizeOpening(data?.opening)
    evalResult.value = null
    draft.value = ''
    spokenKeys.clear()
    spokenTexts.clear()
    phase.value = 'live'
    startTimer()
    // 开场议题不朗读：主持人/议题播报按用户要求去掉，只有 AI 候选人开口
    await scrollBottom()
  } catch (err) {
    ElMessage.error(errText(err))
  } finally {
    starting.value = false
  }
}

async function speak() {
  const text = draft.value.trim()
  if (!text || busy.value) return
  if (listening.value) voice.stopListen() // 发言时结束聆听，识别文本已在输入框里
  sending.value = true
  try {
    // 失败时不写回 state：只有成功响应才替换，避免把会话状态弄坏
    const { data } = await http.post('/interview/lab/group/turn', { state: state.value, text })
    if (data?.state) state.value = data.state
    draft.value = ''
    applyEvaluation(data?.evaluation)
    idleHint.poke() // 发了言就算有动作：重新计冷场时间
    await scrollBottom()
  } catch (err) {
    ElMessage.error(errText(err))
  } finally {
    sending.value = false
  }
}

async function listenRound() {
  if (busy.value) return
  if (listening.value) voice.stopListen()
  aiRunning.value = true
  try {
    for (let i = 0; i < CANDIDATES.length; i += 1) {
      if (disposed) return
      typingName.value = CANDIDATES[i].name
      await scrollBottom()
      const { data } = await http.post('/interview/lab/group/turn', { state: state.value, text: '' })
      if (disposed) return
      if (data?.state) state.value = data.state
      applyEvaluation(data?.evaluation)
      idleHint.poke() // AI 每说完一句重新计时：学生听完后的沉默才起算
      await scrollBottom()
      if (phase.value !== 'live') return
      if (i < CANDIDATES.length - 1) await waitGap(400)
    }
  } catch (err) {
    ElMessage.error(errText(err))
  } finally {
    typingName.value = ''
    aiRunning.value = false
  }
}

async function finish() {
  if (busy.value) return
  if (listening.value) voice.stopListen()
  voice.stopSpeak()
  finishing.value = true
  try {
    const { data } = await http.post('/interview/lab/group/finish', { state: state.value })
    evalResult.value = data || {}
    phase.value = 'report'
    stopTimer()
  } catch (err) {
    ElMessage.error(errText(err))
  } finally {
    finishing.value = false
  }
}

function restart() {
  stopTimer()
  voice.teardown()
  spokenKeys.clear()
  spokenTexts.clear()
  phase.value = 'start'
  topic.value = {}
  state.value = null
  openingTurn.value = null
  evalResult.value = null
  draft.value = ''
  typingName.value = ''
  secondsLeft.value = 0
}

watch(
  () => turns.value.length,
  () => {
    scrollBottom()
    speakFreshTurns(turns.value)
  }
)

onMounted(loadJobs)

onUnmounted(() => {
  disposed = true
  stopTimer()
  voice.teardown()
  if (gapTimer) {
    clearTimeout(gapTimer)
    gapTimer = null
  }
})
</script>

<style scoped>
.gr {
  --gr-bg: #0d1117;
  --gr-card: #111827;
  --gr-line: rgba(148, 163, 184, 0.18);
  --gr-text: #e5e7eb;
  --gr-sub: #9ca3af;
  --gr-primary: #3b82f6;
  background: var(--gr-bg);
  color: var(--gr-text);
  border-radius: 14px;
  padding: 18px;
  font-variant-numeric: tabular-nums;
}

.gr :deep(.el-textarea__inner) {
  background: #0b1220;
  color: var(--gr-text);
  border-color: var(--gr-line);
  box-shadow: none;
  font-size: 14px;
  line-height: 1.7;
}

.gr :deep(.el-textarea__inner::placeholder) {
  color: #6b7280;
}

.gr :deep(.el-input__wrapper) {
  background: #0b1220;
  box-shadow: 0 0 0 1px var(--gr-line) inset;
}

.gr :deep(.el-input__inner) {
  color: var(--gr-text);
}

.gr :deep(.el-button--primary) {
  --el-button-bg-color: #2563eb;
  --el-button-border-color: #2563eb;
  --el-button-hover-bg-color: #3b82f6;
  --el-button-hover-border-color: #3b82f6;
  --el-button-active-bg-color: #1d4ed8;
  --el-button-active-border-color: #1d4ed8;
}

.gr-eyebrow {
  color: #60a5fa;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.gr-h1 {
  margin: 6px 0 0;
  font-size: 22px;
  font-weight: 650;
  color: #f3f4f6;
}

/* ---------------- 开始页 ---------------- */
.gr-lead {
  margin: 8px 0 0;
  max-width: 620px;
  color: var(--gr-sub);
  font-size: 13.5px;
  line-height: 1.75;
}

.gr-start-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  gap: 12px;
  margin-top: 18px;
}

.gr-panel {
  padding: 16px;
  border: 1px solid var(--gr-line);
  border-radius: 16px;
  background: var(--gr-card);
}

.gr-field-label {
  display: block;
  margin-bottom: 8px;
  color: var(--gr-text);
  font-size: 13px;
  font-weight: 600;
}

.gr-select { width: 100%; }

.gr-hint {
  margin: 8px 0 0;
  color: #6b7280;
  font-size: 12.5px;
  line-height: 1.6;
}

.gr-hint.warn { color: #fcd34d; }

.gr-start-btn {
  width: 100%;
  margin-top: 16px;
  padding: 13px 20px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(120deg, #1d4ed8 0%, #3b82f6 100%);
  color: #fff;
  font-size: 15px;
  font-weight: 650;
  letter-spacing: 0.02em;
  cursor: pointer;
  transition: filter 0.2s, transform 0.12s;
}

.gr-start-btn:hover:not(:disabled) { filter: brightness(1.08); }
.gr-start-btn:active:not(:disabled) { transform: translateY(1px); }
.gr-start-btn:disabled { cursor: not-allowed; opacity: 0.62; }

.gr-rules {
  padding: 16px;
  border: 1px solid rgba(96, 165, 250, 0.22);
  border-radius: 16px;
  background: radial-gradient(320px 160px at 100% 0%, rgba(37, 99, 235, 0.18), transparent 70%), var(--gr-card);
}

.gr-rules-title {
  color: #bfdbfe;
  font-size: 13px;
  font-weight: 650;
}

.gr-rule-list {
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.gr-rule-list li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-left: 12px;
  border-left: 2px solid rgba(96, 165, 250, 0.4);
}

.gr-rule-list b { color: #f3f4f6; font-size: 14px; }
.gr-rule-list span { color: var(--gr-sub); font-size: 12.5px; line-height: 1.55; }

.gr-roster {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.gr-roster-card {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 12px;
  border: 1px solid var(--gr-line);
  border-radius: 12px;
  background: rgba(17, 24, 39, 0.72);
  min-width: 0;
}

.gr-roster-card.me { border-color: rgba(59, 130, 246, 0.5); }

.gr-roster-avatar {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex: none;
  border-radius: 50%;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
}

.gr-roster-card > div { display: flex; flex-direction: column; min-width: 0; }
.gr-roster-card b { color: #f3f4f6; font-size: 13px; }
.gr-roster-card span { color: #6b7280; font-size: 11.5px; }

/* ---------------- 进行中 ---------------- */
.gr-topic {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 16px;
  border: 1px solid var(--gr-line);
  border-radius: 16px;
  background: radial-gradient(360px 180px at 0% 0%, rgba(37, 99, 235, 0.16), transparent 72%), var(--gr-card);
}

.gr-topic-main { min-width: 0; flex: 1; }

.gr-topic-title {
  margin: 6px 0 0;
  font-size: 18px;
  font-weight: 650;
  line-height: 1.5;
  color: #f9fafb;
}

.gr-topic-brief {
  margin: 6px 0 0;
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.75;
}

.gr-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.gr-chip {
  padding: 2px 9px;
  border: 1px solid rgba(96, 165, 250, 0.3);
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.12);
  color: #bfdbfe;
  font-size: 11.5px;
}

.gr-timer {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  flex: none;
  padding: 10px 14px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 12px;
  background: #0b1220;
}

.gr-timer b {
  color: #f9fafb;
  font-size: 26px;
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.gr-timer span { color: #6b7280; font-size: 11.5px; white-space: nowrap; }

.gr-timer.over { border-color: rgba(248, 113, 113, 0.45); background: rgba(239, 68, 68, 0.1); }
.gr-timer.over b { color: #fca5a5; }
.gr-timer.over span { color: #fca5a5; }

.gr-stream {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 420px;
  margin-top: 12px;
  padding: 14px;
  overflow-y: auto;
  border: 1px solid var(--gr-line);
  border-radius: 16px;
  background: #0a0f18;
  scroll-behavior: smooth;
}

.gr-stream-empty {
  padding: 22px 0;
  text-align: center;
  color: #6b7280;
  font-size: 13px;
}

.gr-msg {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  max-width: 88%;
}

.gr-msg.me {
  flex-direction: row-reverse;
  align-self: flex-end;
}

.gr-avatar {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex: none;
  border-radius: 50%;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  box-shadow: 0 4px 12px rgba(2, 6, 23, 0.45);
}

.gr-bubble-wrap { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.gr-msg.me .gr-bubble-wrap { align-items: flex-end; }

.gr-msg-meta {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 11.5px;
  color: #6b7280;
}

.gr-msg-meta b { color: #cbd5e1; font-size: 12px; font-weight: 600; }
.gr-msg-role {
  padding: 0 6px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.14);
  color: #94a3b8;
  font-size: 10.5px;
}
.gr-msg-at { font-variant-numeric: tabular-nums; }

.gr-bubble {
  padding: 9px 13px;
  border: 1px solid var(--gr-line);
  border-radius: 4px 14px 14px 14px;
  background: #131c2b;
  color: #e5e7eb;
  font-size: 13.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.gr-msg.me .gr-bubble {
  border-color: rgba(59, 130, 246, 0.45);
  border-radius: 14px 4px 14px 14px;
  background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%);
  color: #f8fbff;
}

.gr-typing {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 14px;
}

.gr-typing i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #64748b;
  animation: gr-blink 1.2s infinite ease-in-out;
}

.gr-typing i:nth-child(2) { animation-delay: 0.16s; }
.gr-typing i:nth-child(3) { animation-delay: 0.32s; }

@keyframes gr-blink {
  0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-3px); }
}

.gr-composer {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--gr-line);
  border-radius: 16px;
  background: var(--gr-card);
}

.gr-composer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.gr-turn-count { margin-left: auto; color: #6b7280; font-size: 12px; }

/* 语音提示与播报态 */
.gr-mic-hint {
  margin: 8px 2px 0;
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  line-height: 1.5;
}

.gr-mic-hint.live { color: #fbbf24; }
.gr-mic-hint.dim { color: #6b7280; }

.gr-mic-dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  background: #f59e0b;
  animation: gr-mic-pulse 1.1s infinite ease-in-out;
}

@keyframes gr-mic-pulse {
  0%, 100% { opacity: 0.35; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.15); }
}

.gr-bubble.speaking {
  border-color: rgba(96, 165, 250, 0.6);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.22);
}

.gr-speaking-tag {
  color: #93c5fd;
  background: rgba(37, 99, 235, 0.18);
}

/* ---------------- 报告 ---------------- */
.gr-report-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.gr-report-id { min-width: 0; }

.gr-again {
  padding: 9px 18px;
  border: 1px solid rgba(96, 165, 250, 0.4);
  border-radius: 10px;
  background: rgba(37, 99, 235, 0.16);
  color: #bfdbfe;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.gr-again:hover { background: rgba(37, 99, 235, 0.26); }

.gr-role {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 16px;
  padding: 14px 16px;
  border: 1px solid var(--gr-line);
  border-radius: 14px;
}

.gr-role-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 16px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.6);
}

.gr-role-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 0 4px rgba(148, 163, 184, 0.14);
}

.gr-role-badge b { font-size: 17px; font-weight: 700; color: #f9fafb; }
.gr-role-badge { color: #9ca3af; }
.gr-role-reason {
  flex: 1;
  min-width: 220px;
  margin: 0;
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.7;
}

.gr-score-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.gr-score-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 14px 8px;
  border: 1px solid var(--gr-line);
  border-radius: 14px;
  background: var(--gr-card);
}

.gr-ring { position: relative; width: 72px; height: 72px; }
.gr-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.gr-ring-bg { fill: none; stroke: #1f2937; stroke-width: 7; }
.gr-ring-fg { fill: none; stroke-width: 7; stroke-linecap: round; transition: stroke-dasharray 0.6s; }

.gr-ring-text {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
}

.gr-ring-text b { color: #f9fafb; font-size: 22px; font-weight: 700; }
.gr-score-label { color: #9ca3af; font-size: 12.5px; }

.gr-score-note {
  margin: 8px 0 0;
  color: #6b7280;
  font-size: 11.5px;
}

.gr-metrics {
  margin-top: 16px;
  padding: 14px 16px;
  border: 1px solid var(--gr-line);
  border-radius: 14px;
  background: var(--gr-card);
}

.gr-sec-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
}

.gr-sec-title { color: #f3f4f6; font-size: 14px; font-weight: 650; }
.gr-sec-sub { color: #6b7280; font-size: 11.5px; }

.gr-ratio {
  display: flex;
  height: 26px;
  overflow: hidden;
  border: 1px solid var(--gr-line);
  border-radius: 8px;
  background: #0b1220;
}

.gr-ratio-me {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  background: linear-gradient(90deg, #1d4ed8, #3b82f6);
  color: #f8fbff;
  font-size: 11.5px;
  font-weight: 600;
  transition: width 0.5s;
}

.gr-ratio-other {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  background: repeating-linear-gradient(135deg, #1f2937 0 8px, #243044 8px 16px);
  color: #cbd5e1;
  font-size: 11.5px;
  transition: width 0.5s;
}

.gr-metric-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.gr-metric-chip {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid var(--gr-line);
  border-radius: 9px;
  background: rgba(15, 23, 42, 0.55);
}

.gr-metric-chip span { color: #6b7280; font-size: 11.5px; }
.gr-metric-chip b { color: #e5e7eb; font-size: 13px; }

.gr-lists {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.gr-list-card {
  padding: 14px 16px;
  border: 1px solid var(--gr-line);
  border-radius: 14px;
  background: var(--gr-card);
}

.gr-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 13px;
  line-height: 1.65;
}

.gr-list li { display: flex; align-items: flex-start; gap: 7px; }
.gr-list .mark { flex: none; font-weight: 700; }
.gr-list.good { color: #a7f3d0; }
.gr-list.good .mark { color: #34d399; }
.gr-list.warn { color: #fcd34d; }
.gr-list.warn .mark { color: #fb923c; }
.gr-list-empty { margin: 0; color: #6b7280; font-size: 12.5px; }

.gr-drill {
  margin-top: 12px;
  padding: 16px;
  border: 1px solid rgba(96, 165, 250, 0.35);
  border-left: 3px solid #3b82f6;
  border-radius: 14px;
  background: radial-gradient(340px 160px at 0% 0%, rgba(37, 99, 235, 0.2), transparent 70%), #111827;
}

.gr-drill-tag { color: #93c5fd; font-size: 11.5px; font-weight: 700; letter-spacing: 0.04em; }
.gr-drill-text { margin: 6px 0 0; color: #f3f4f6; font-size: 15px; line-height: 1.7; }

@media (max-width: 860px) {
  .gr-start-grid { grid-template-columns: 1fr; }
  .gr-roster { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .gr-score-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .gr-lists { grid-template-columns: 1fr; }
  .gr-msg { max-width: 96%; }
}

@media (max-width: 560px) {
  .gr-topic { flex-direction: column; }
  .gr-timer { align-items: flex-start; }
  .gr-composer-actions :deep(.el-button) { flex: 1; }
  .gr-turn-count { margin-left: 0; width: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  .gr-typing i { animation: none; opacity: 0.6; }
  .gr-mic-dot { animation: none; opacity: 0.8; }
  .gr-stream { scroll-behavior: auto; }
  .gr-ratio-me,
  .gr-ratio-other,
  .gr-ring-fg { transition: none; }
}
</style>
