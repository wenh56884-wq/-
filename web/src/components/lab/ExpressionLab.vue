<template>
  <div class="lab-expression">
    <section class="ex-card">
      <div class="ex-head">
        <div class="ex-head-copy">
          <h2>表达力实验室</h2>
          <p>说一段或写一段，量出语速、口头语与句子结构。</p>
        </div>
        <el-radio-group v-model="mode" size="small" class="ex-mode">
          <el-radio-button value="text">文本模式</el-radio-button>
          <el-radio-button value="mic">麦克风</el-radio-button>
        </el-radio-group>
      </div>

      <!-- 麦克风舞台 -->
      <div v-if="mode === 'mic'" class="mic-stage">
        <button type="button" class="mic-btn" :class="{ recording }" :disabled="!micReady"
          :aria-label="recording ? '结束录音并分析' : '开始录音'" @click="toggleRecording">
          <svg v-if="!recording" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="9" y="3" width="6" height="11" rx="3" />
            <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3" />
          </svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true">
            <rect x="7.5" y="7.5" width="9" height="9" rx="2" />
          </svg>
        </button>

        <div class="mic-stats">
          <div class="stat">
            <span class="stat-num">{{ liveChars }}</span>
            <span class="stat-label">已说字数</span>
          </div>
          <div class="stat">
            <span class="stat-num">{{ clock }}</span>
            <span class="stat-label">计时</span>
          </div>
          <div class="stat">
            <span class="stat-num">{{ liveSpeed }}</span>
            <span class="stat-label">字/分（近 5 秒）</span>
          </div>
        </div>

        <p v-if="recording" class="mic-tip">正在听你说，说完点一下大按钮结束并自动分析</p>
        <p v-else-if="micReady" class="mic-tip">点击麦克风开始；识别结果会回填到下方文本框</p>
        <p v-if="recording && micLiveText" class="mic-live">{{ micLiveText }}</p>
      </div>

      <div v-if="mode === 'mic' && !micReady" class="warn-bar">
        <span class="warn-icon" aria-hidden="true">!</span>
        <div class="warn-copy">
          <span>当前为 HTTP 环境，麦克风需要 HTTPS 访问；可先用文本模式，或让管理员开启 HTTPS</span>
          <span v-if="warnExtra" class="warn-extra">{{ warnExtra }}</span>
        </div>
      </div>

      <div class="ex-field">
        <label class="ex-label" for="expr-text">{{ mode === 'mic' ? '识别文本（可再编辑）' : '要说的话' }}</label>
        <el-input id="expr-text" v-model="text" type="textarea" :rows="8" :maxlength="4000"
          show-word-limit resize="vertical"
          placeholder="把你要说的话打出来，或粘贴语音转写稿" />
      </div>

      <div class="ex-actions">
        <div class="ex-duration">
          <span class="ex-label">时长（秒）</span>
          <el-input-number v-model="durationSec" :min="1" :max="3600" :step="5" :controls="false"
            class="ex-number" placeholder="可空" aria-label="说话时长（秒）" />
          <span class="ex-hint">不填也能分析，只是语速不参与评分</span>
        </div>
        <el-button type="primary" :loading="loading" :disabled="!canSubmit" @click="onAnalyzeClick">
          开始分析
        </el-button>
      </div>

      <el-alert v-if="errorTip" class="ex-alert" type="warning" :closable="false" show-icon
        :title="errorTip" />
    </section>

    <!-- 结果区 -->
    <section v-if="result" class="ex-card ex-result">
      <div class="ex-result-head">
        <div class="ring-wrap">
          <svg class="ring" viewBox="0 0 120 120" aria-hidden="true">
            <circle class="ring-track" cx="60" cy="60" r="52" />
            <circle class="ring-fill" cx="60" cy="60" r="52" :stroke="scoreColor"
              :stroke-dasharray="RING_C" :stroke-dashoffset="ringOffset" />
          </svg>
          <div class="ring-center">
            <span class="ring-score" :style="{ color: scoreColor }">{{ scoreValue === null ? '—' : scoreValue }}</span>
            <span class="ring-unit">表达分</span>
          </div>
          <p v-if="isLowConfidence" class="ring-note">未提供时长，语速未参与评分</p>
        </div>

        <div class="metrics">
          <div v-for="metric in metrics" :key="metric.key || metric.label" class="metric">
            <div class="metric-top">
              <span class="metric-label">{{ metric.label || '指标' }}</span>
              <span class="metric-value">{{ metric.value ?? '—' }}</span>
              <span v-if="metric.key === 'speed' && speedBand" class="band-tag" :class="bandClass">
                {{ speedBand }}
              </span>
            </div>
            <div class="metric-track" :title="metric.hint || ''">
              <div class="metric-fill"
                :style="{ width: metricWidth(metric.score) + '%', background: metricColor(metric.score) }"></div>
            </div>
          </div>
          <p v-if="!metrics.length" class="metric-empty">这次没有返回指标明细</p>
        </div>
      </div>

      <div class="filler-block">
        <div class="filler-head">
          <span class="block-title">口头语</span>
          <span class="filler-total">{{ fillerTotal }} 次</span>
        </div>
        <div v-if="fillerChips.length" class="filler-chips">
          <span v-for="chip in fillerChips" :key="chip.word" class="filler-chip">
            {{ chip.word }}<b>{{ chip.count }}</b>
          </span>
        </div>
        <p v-else class="filler-none">没有口头语，很好</p>
      </div>

      <div v-if="tips.length" class="tips-block">
        <div class="block-title">下一步怎么改</div>
        <ol class="tips-list">
          <li v-for="(tip, index) in tips" :key="index">
            <span class="tip-arrow" aria-hidden="true">→</span>
            <span>{{ tip }}</span>
          </li>
        </ol>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import api from '../../api/http'

const SpeechCtor = typeof window === 'undefined'
  ? null
  : (window.SpeechRecognition || window.webkitSpeechRecognition)

const isSecure = typeof window === 'undefined' ? true : window.isSecureContext !== false
const micApiReady = Boolean(SpeechCtor)
// 契约：HTTP 环境或不支持识别 API 时，麦克风不可用，引导先用文本模式
const micReady = micApiReady && isSecure

const RING_R = 52
const RING_C = Number((2 * Math.PI * RING_R).toFixed(2))

const mode = ref('text')
const text = ref('')
const durationSec = ref(null)
const loading = ref(false)
const result = ref(null)
const errorTip = ref('')

const recording = ref(false)
const elapsed = ref(0)
const liveChars = ref(0)
const liveSpeed = ref(0)
const micLiveText = ref('')

let recognition = null
let tickTimer = null
let startedAt = 0
let finalText = ''
let stopping = false
let applyingTranscript = false
let segStartMap = new Map()
let lastSegEnd = 0
const segments = []
const samples = []

const canSubmit = computed(() => text.value.trim().length > 0)

const warnExtra = computed(() =>
  micApiReady ? '' : '另外，当前浏览器没有提供语音识别接口，建议改用 Chrome / Edge。'
)

const clock = computed(() => {
  const total = Math.max(0, Math.floor(elapsed.value))
  const mm = String(Math.floor(total / 60)).padStart(2, '0')
  const ss = String(total % 60).padStart(2, '0')
  return `${mm}:${ss}`
})

const scoreValue = computed(() => {
  const raw = result.value?.score
  if (raw === null || raw === undefined) return null
  const n = Number(raw)
  return Number.isFinite(n) ? Math.max(0, Math.min(100, Math.round(n))) : null
})

const scoreColor = computed(() => (scoreValue.value === null ? '#6b7280' : toneColor(scoreValue.value)))

const ringOffset = computed(() => {
  const score = scoreValue.value === null ? 0 : scoreValue.value
  return RING_C * (1 - score / 100)
})

const metrics = computed(() => (Array.isArray(result.value?.metrics) ? result.value.metrics : []))
const tips = computed(() => (Array.isArray(result.value?.tips) ? result.value.tips : []))
const isLowConfidence = computed(() => result.value?.confidence === 'low')

const fillerChips = computed(() => {
  const fillers = result.value?.fillers || {}
  return Object.entries(fillers)
    .map(([word, count]) => ({ word, count: Number(count) || 0 }))
    .sort((a, b) => b.count - a.count)
})

const fillerTotal = computed(() => {
  const raw = result.value?.filler_total
  if (raw !== null && raw !== undefined && Number.isFinite(Number(raw))) return Number(raw)
  return fillerChips.value.reduce((sum, chip) => sum + chip.count, 0)
})

const speedBand = computed(() => {
  const band = result.value?.speed_band
  return band === '偏快' || band === '偏慢' ? band : ''
})

const bandClass = computed(() => (speedBand.value === '偏快' ? 'band-fast' : 'band-slow'))

function toneColor(score) {
  if (score >= 80) return '#22c55e'
  if (score >= 60) return '#3b82f6'
  if (score >= 45) return '#f59e0b'
  return '#ef4444'
}

function metricWidth(score) {
  if (score === null || score === undefined) return 0
  const n = Number(score)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(100, n))
}

function metricColor(score) {
  if (score === null || score === undefined) return '#4b5563'
  const n = Number(score)
  return Number.isFinite(n) ? toneColor(n) : '#4b5563'
}

function secondsNow() {
  return startedAt ? (Date.now() - startedAt) / 1000 : 0
}

function round1(value) {
  return Math.round(Number(value) * 10) / 10
}

function startTick() {
  stopTick()
  tickTimer = setInterval(() => {
    elapsed.value = secondsNow()
    refreshSpeed(liveChars.value, elapsed.value)
  }, 400)
}

function stopTick() {
  if (tickTimer) clearInterval(tickTimer)
  tickTimer = null
}

function pushSample(chars, sec) {
  samples.push({ sec, chars })
  if (samples.length > 40) samples.shift()
}

// 滚动窗口 5 秒：用窗口内首个样本做基线，样本不足时退回整段平均
function refreshSpeed(chars, sec) {
  if (sec < 0.6) {
    liveSpeed.value = 0
    return
  }
  const inWindow = samples.filter((item) => item.sec >= sec - 5)
  if (inWindow.length >= 2) {
    const base = inWindow[0]
    const span = Math.max(0.8, sec - base.sec)
    liveSpeed.value = Math.max(0, Math.round(((chars - base.chars) / span) * 60))
    return
  }
  liveSpeed.value = Math.max(0, Math.round((chars / sec) * 60))
}

function handleResult(event) {
  const now = secondsNow()
  let interim = ''
  for (let i = event.resultIndex; i < event.results.length; i += 1) {
    const item = event.results[i]
    const piece = String(item[0]?.transcript || '').trim()
    if (!piece) continue
    if (item.isFinal) {
      const start = segStartMap.has(i) ? segStartMap.get(i) : lastSegEnd
      const end = Math.max(now, start + 0.2)
      finalText += piece
      segments.push({ text: piece, start: round1(start), end: round1(end) })
      lastSegEnd = end
      segStartMap.delete(i)
    } else {
      if (!segStartMap.has(i)) segStartMap.set(i, now)
      interim += piece
    }
  }
  micLiveText.value = `${finalText}${interim}`
  liveChars.value = micLiveText.value.length
  pushSample(liveChars.value, now)
  refreshSpeed(liveChars.value, now)
}

function handleError(event) {
  const code = event?.error
  if (code === 'not-allowed' || code === 'service-not-allowed') {
    ElMessage.warning('麦克风权限被拒绝，请在地址栏的权限设置里允许后重试')
  } else if (code === 'no-speech') {
    ElMessage.warning('没有听到声音，靠近一点再说一次试试')
  } else if (code === 'audio-capture') {
    ElMessage.warning('没有找到可用的麦克风设备')
  } else if (code === 'network') {
    ElMessage.warning('语音识别服务网络异常，可先用文本模式')
  }
  // 出错时不再自动提交，避免把空文本送去分析
  stopping = false
}

function handleEnd() {
  recording.value = false
  stopTick()
  elapsed.value = secondsNow()
  recognition = null

  const captured = finalText.trim()
  const seconds = Math.max(1, Math.round(elapsed.value))
  const shouldAnalyze = stopping
  stopping = false
  micLiveText.value = captured
  liveChars.value = captured.length

  if (!captured) {
    if (shouldAnalyze) ElMessage.warning('这次没有识别到内容，可以改用文本模式')
    return
  }

  applyingTranscript = true
  text.value = captured
  applyingTranscript = false
  durationSec.value = seconds
  if (shouldAnalyze) analyze({ duration: seconds })
}

function startRecording() {
  if (!micReady || recording.value) return
  try {
    recognition = new SpeechCtor()
  } catch {
    ElMessage.error('当前浏览器无法创建语音识别实例，请改用文本模式')
    return
  }
  recognition.lang = 'zh-CN'
  recognition.continuous = true
  recognition.interimResults = true
  recognition.onresult = handleResult
  recognition.onerror = handleError
  recognition.onend = handleEnd

  finalText = ''
  micLiveText.value = ''
  liveChars.value = 0
  liveSpeed.value = 0
  elapsed.value = 0
  segments.length = 0
  samples.length = 0
  segStartMap = new Map()
  lastSegEnd = 0
  stopping = false
  startedAt = Date.now()

  try {
    recognition.start()
  } catch {
    recognition = null
    ElMessage.error('麦克风启动失败，请检查浏览器权限后重试')
    return
  }
  recording.value = true
  startTick()
}

function stopRecording(autoSubmit = true) {
  if (!recording.value || !recognition) return
  stopping = autoSubmit
  try {
    recognition.stop()
  } catch {
    stopping = false
    handleEnd()
  }
}

function toggleRecording() {
  if (recording.value) stopRecording()
  else startRecording()
}

async function analyze(extra = {}) {
  const content = text.value.trim()
  if (!content) {
    ElMessage.warning('先把要说的话填进文本框')
    return
  }
  const rawSeconds = extra?.duration ?? durationSec.value
  const seconds = Number(rawSeconds)
  loading.value = true
  errorTip.value = ''
  try {
    const payload = { text: content }
    if (Number.isFinite(seconds) && seconds > 0) {
      payload.duration_sec = round1(seconds)
    }
    if (segments.length) {
      payload.segments = segments.map((item) => ({ text: item.text, start: item.start, end: item.end }))
    }
    const { data } = await api.post('/interview/lab/expression', payload)
    result.value = data || null
  } catch (err) {
    result.value = null
    errorTip.value = err?.response?.data?.detail || '分析失败，稍后再试'
  } finally {
    loading.value = false
  }
}

function onAnalyzeClick() {
  analyze()
}

// 手动改过文本后，旧的录音片段时间轴就失效了，不再随请求提交
watch(
  text,
  () => {
    if (applyingTranscript) return
    if (segments.length) segments.length = 0
  },
  { flush: 'sync' }
)

// 切走麦克风分栏时收尾，避免面板隐藏后还在后台录音
watch(mode, (next) => {
  if (next !== 'mic' && recording.value) stopRecording(false)
})

onUnmounted(() => {
  stopTick()
  if (recognition) {
    const current = recognition
    recognition = null
    current.onresult = null
    current.onerror = null
    current.onend = null
    try {
      current.abort()
    } catch {
      /* 已经结束的实例 abort 会抛错，忽略即可 */
    }
  }
  recording.value = false
})
</script>

<style scoped>
.lab-expression {
  --ex-bg: #0d1117;
  --ex-card: #111827;
  --ex-line: #1f2937;
  --ex-text: #e5e7eb;
  --ex-sub: #9ca3af;
  --ex-primary: #3b82f6;
  background: var(--ex-bg);
  color: var(--ex-text);
  border-radius: 12px;
  padding: 18px;
  font-variant-numeric: tabular-nums;
}

.ex-card {
  background: var(--ex-card);
  border: 1px solid var(--ex-line);
  border-radius: 10px;
  padding: 16px;
}

.lab-expression :deep(.el-button--primary) {
  --el-button-bg-color: #2563eb;
  --el-button-border-color: #2563eb;
  --el-button-hover-bg-color: #3b82f6;
  --el-button-hover-border-color: #3b82f6;
  --el-button-active-bg-color: #1d4ed8;
  --el-button-active-border-color: #1d4ed8;
}

.ex-result {
  margin-top: 14px;
}

.ex-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.ex-head-copy h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
}

.ex-head-copy p {
  margin: 6px 0 0;
  font-size: 12.5px;
  color: var(--ex-sub);
}

.ex-mode :deep(.el-radio-button__inner) {
  background: #0d1117;
  border-color: var(--ex-line);
  color: var(--ex-sub);
}

.ex-mode :deep(.el-radio-button.is-active .el-radio-button__original-radio:not(:disabled) + .el-radio-button__inner) {
  background: rgba(59, 130, 246, 0.9);
  border-color: var(--ex-primary);
  color: #f9fafb;
  box-shadow: none;
}

/* ---------- 麦克风 ---------- */
.mic-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 18px 12px 10px;
  border: 1px solid var(--ex-line);
  border-radius: 10px;
  background: radial-gradient(circle at 50% 0%, rgba(59, 130, 246, 0.12), rgba(13, 17, 23, 0.6) 65%);
}

.mic-btn {
  width: 84px;
  height: 84px;
  border-radius: 50%;
  border: 1px solid rgba(59, 130, 246, 0.55);
  background: rgba(59, 130, 246, 0.16);
  color: #bfdbfe;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform 200ms ease, box-shadow 240ms ease, background 240ms ease;
}

.mic-btn svg {
  width: 34px;
  height: 34px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
}

.mic-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 0 22px rgba(59, 130, 246, 0.35);
}

.mic-btn:disabled {
  cursor: not-allowed;
  opacity: 0.4;
  border-color: var(--ex-line);
  background: rgba(31, 41, 55, 0.4);
  color: #6b7280;
}

.mic-btn.recording {
  background: rgba(239, 68, 68, 0.18);
  border-color: rgba(239, 68, 68, 0.6);
  color: #fca5a5;
  animation: mic-breath 1.8s ease-in-out infinite;
}

@keyframes mic-breath {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.35);
    transform: scale(1);
  }
  50% {
    box-shadow: 0 0 0 14px rgba(239, 68, 68, 0);
    transform: scale(1.04);
  }
}

.mic-stats {
  display: flex;
  gap: 26px;
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.stat-num {
  font-size: 20px;
  font-weight: 650;
  color: var(--ex-text);
}

.stat-label {
  font-size: 11.5px;
  color: var(--ex-sub);
}

.mic-tip {
  margin: 0;
  font-size: 12.5px;
  color: var(--ex-sub);
}

.mic-live {
  margin: 0;
  max-width: 100%;
  max-height: 96px;
  overflow-y: auto;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(13, 17, 23, 0.75);
  border: 1px solid var(--ex-line);
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.7;
}

.warn-bar {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid rgba(245, 158, 11, 0.38);
  background: rgba(245, 158, 11, 0.12);
  color: #fbbf24;
  font-size: 12.5px;
  line-height: 1.6;
}

.warn-icon {
  flex: none;
  width: 16px;
  height: 16px;
  margin-top: 1px;
  border-radius: 50%;
  border: 1px solid #fbbf24;
  text-align: center;
  font-size: 11px;
  line-height: 14px;
}

.warn-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.warn-extra {
  color: #d1a63a;
}

/* ---------- 输入 ---------- */
.ex-field {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ex-label {
  font-size: 12.5px;
  color: var(--ex-sub);
}

.lab-expression :deep(.el-textarea__inner) {
  background: #0d1117;
  color: var(--ex-text);
  border: 1px solid var(--ex-line);
  box-shadow: none;
  font-size: 13.5px;
  line-height: 1.8;
}

.lab-expression :deep(.el-textarea__inner:focus) {
  border-color: rgba(59, 130, 246, 0.6);
}

.lab-expression :deep(.el-textarea .el-input__count) {
  background: transparent;
  color: #6b7280;
}

.ex-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.ex-duration {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ex-number {
  width: 96px;
}

.ex-number :deep(.el-input__wrapper) {
  background: #0d1117;
  box-shadow: 0 0 0 1px var(--ex-line) inset;
}

.ex-number :deep(.el-input__inner) {
  color: var(--ex-text);
  text-align: left;
}

.ex-hint {
  font-size: 12px;
  color: #6b7280;
}

.ex-alert {
  margin-top: 12px;
}

/* ---------- 结果 ---------- */
.ex-result-head {
  display: grid;
  grid-template-columns: 178px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.ring-wrap {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.ring {
  width: 132px;
  height: 132px;
  transform: rotate(-90deg);
}

.ring-track {
  fill: none;
  stroke: #1f2937;
  stroke-width: 10;
}

.ring-fill {
  fill: none;
  stroke-width: 10;
  stroke-linecap: round;
  transition: stroke-dashoffset 700ms cubic-bezier(0.25, 0.1, 0.25, 1), stroke 300ms ease;
}

.ring-center {
  position: absolute;
  top: 0;
  left: 50%;
  width: 132px;
  height: 132px;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  pointer-events: none;
}

.ring-score {
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
}

.ring-unit {
  font-size: 11.5px;
  color: var(--ex-sub);
}

.ring-note {
  margin: 0;
  text-align: center;
  font-size: 11.5px;
  line-height: 1.5;
  color: #6b7280;
}

.metrics {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.metric-top {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 4px;
}

.metric-label {
  font-size: 12.5px;
  color: var(--ex-sub);
}

.metric-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--ex-text);
}

.band-tag {
  padding: 0 6px;
  border-radius: 4px;
  font-size: 11px;
  line-height: 17px;
}

.band-fast {
  color: #fdba74;
  background: rgba(249, 115, 22, 0.16);
  border: 1px solid rgba(249, 115, 22, 0.4);
}

.band-slow {
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.16);
  border: 1px solid rgba(245, 158, 11, 0.4);
}

.metric-track {
  height: 7px;
  border-radius: 5px;
  background: #1b2433;
  overflow: hidden;
}

.metric-fill {
  height: 100%;
  border-radius: 5px;
  transition: width 600ms cubic-bezier(0.25, 0.1, 0.25, 1);
}

.metric-empty {
  margin: 0;
  font-size: 12.5px;
  color: var(--ex-sub);
}

.filler-block {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--ex-line);
}

.filler-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.block-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ex-text);
}

.filler-total {
  font-size: 12px;
  color: var(--ex-sub);
}

.filler-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.filler-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border-radius: 999px;
  border: 1px solid rgba(245, 158, 11, 0.35);
  background: rgba(245, 158, 11, 0.12);
  color: #fcd34d;
  font-size: 12px;
}

.filler-chip b {
  color: #fbbf24;
  font-size: 12.5px;
}

.filler-none {
  margin: 8px 0 0;
  font-size: 12.5px;
  color: #34d399;
}

.tips-block {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--ex-line);
}

.tips-list {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tips-list li {
  display: flex;
  gap: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: #d1d5db;
}

.tip-arrow {
  flex: none;
  color: var(--ex-primary);
}

@media (max-width: 720px) {
  .ex-result-head {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
