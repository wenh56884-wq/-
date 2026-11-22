<template>
  <div class="pb">
    <header class="pb-head">
      <div>
        <div class="pb-eyebrow">PEER BENCHMARK · 同辈分位</div>
        <h3 class="pb-title">你在同届里的位置</h3>
      </div>
      <div v-if="data" class="pb-meta">
        <span v-if="sampleN != null">实测样本 {{ sampleN }} 场</span>
        <span v-if="cohort != null">同届母体 {{ cohort }} 人</span>
      </div>
    </header>

    <div v-if="loading && !data" class="pb-skeleton" aria-busy="true">
      <div class="sk-bubble"></div>
      <div class="sk-axis"></div>
      <div class="sk-line" v-for="i in 4" :key="i"></div>
    </div>

    <div v-else-if="error" class="pb-error" role="alert">
      <div class="pb-error-title">同辈分位加载失败</div>
      <p class="pb-error-detail">{{ error }}</p>
      <el-button size="small" type="primary" plain @click="load">重试</el-button>
    </div>

    <div v-else-if="!data" class="pb-empty">暂无同辈分位数据</div>

    <template v-else>
      <!-- 口径提示：course_proxy 必须显式说清是代理基准 -->
      <div v-if="data.basis === 'course_proxy'" class="pb-proxy" role="note">
        <span class="pb-proxy-tag">诚实口径</span>
        <span class="pb-proxy-text">{{ noteText }}</span>
      </div>

      <div v-if="data.basis === 'none'" class="pb-none">
        <b>暂无同辈可比样本</b>
        <span>本专业同年级还没有足够的面试实测样本，也没有可用的课程代理基准。先把自己的分数练上去，样本会随届次积累。</span>
      </div>

      <template v-else>
        <section class="pb-card">
          <div class="pb-card-head">
            <h3>总分分位</h3>
            <span class="pb-card-sub">{{ basisText }}</span>
          </div>

          <div class="pb-ruler">
            <div v-if="totalPct != null" class="pb-bubble" :style="bubbleStyle">{{ bubbleText }}</div>
            <div v-else class="pb-bubble flat" style="left: 50%; transform: translateX(-50%)">
              本场总分为空，暂无法定位
            </div>

            <div class="pb-axis">
              <div class="pb-marker" v-if="totalPct != null" :style="{ left: totalPct + '%' }"></div>
            </div>

            <div class="pb-ticks">
              <span v-for="t in ticks" :key="t" :style="{ left: t + '%' }">{{ t }}</span>
            </div>

            <div class="pb-bands">
              <span v-for="b in bands" :key="b.key" class="pb-band" :class="'band-' + b.key">{{ b.label }}</span>
            </div>
          </div>

          <p v-if="noteText" class="pb-note">口径：{{ noteText }}</p>
        </section>

        <section class="pb-card">
          <div class="pb-card-head">
            <h3>维度分位</h3>
            <span class="pb-card-sub">
              实线=本专业实测 · 虚线=课程成绩代理
            </span>
          </div>

          <div v-if="dims.length" class="pb-dims">
            <div
              v-for="d in dims"
              :key="d.key || d.label"
              class="pb-dim"
              :class="{ proxy: d.basis === 'course_proxy' }"
            >
              <span class="pb-dim-label">{{ d.label || d.key }}</span>
              <div class="pb-dim-track">
                <i v-if="pctOf(d.percentile) != null" :style="{ width: pctOf(d.percentile) + '%' }"></i>
              </div>
              <span class="pb-dim-p">{{ pText(d.percentile) }}</span>
            </div>
          </div>
          <p v-else class="pb-placeholder">暂无维度分位数据</p>
        </section>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

import http from '../../api/http'

const props = defineProps({
  sessionId: { type: Number, required: true }
})

const BANDS = [
  { key: 'low', label: '后25%' },
  { key: 'midlow', label: '中下' },
  { key: 'midhigh', label: '中上' },
  { key: 'high', label: '前25%' }
]

const TICKS = [0, 25, 50, 75, 100]

const BASIS_TEXT = {
  observed: '基于本专业同年级实测样本',
  course_proxy: '样本不足，改用课程成绩代理基准',
  none: '暂无同辈可比样本'
}

const data = ref(null)
const loading = ref(false)
const error = ref('')

const bands = BANDS
const ticks = TICKS

const total = computed(() => data.value?.total || null)
const dims = computed(() => (Array.isArray(data.value?.dims) ? data.value.dims : []))
const cohort = computed(() => numOf(data.value?.cohort))
const sampleN = computed(() => numOf(data.value?.sample_n))
const noteText = computed(() => {
  const note = data.value?.note
  if (typeof note === 'string' && note.trim()) return note
  return BASIS_TEXT[data.value?.basis] || ''
})
const basisText = computed(() => BASIS_TEXT[data.value?.basis] || '')

const totalPct = computed(() => pctOf(total.value?.percentile))

const bubbleText = computed(() => {
  const parts = [`你 ${fmt(total.value?.score)} 分`]
  if (total.value?.label) parts.push(total.value.label)
  const rank = numOf(total.value?.rank)
  if (rank != null && cohort.value != null) {
    parts.push(`${Math.round(cohort.value)} 人中第 ${Math.round(rank)}`)
  }
  return parts.join(' · ')
})

const bubbleStyle = computed(() => {
  const p = totalPct.value
  if (p == null) return {}
  const shift = p < 20 ? -6 : p > 80 ? -94 : -50
  return { left: p + '%', transform: `translateX(${shift}%)` }
})

function numOf(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function pctOf(v) {
  const n = numOf(v)
  if (n == null) return null
  return Math.min(100, Math.max(0, n))
}

function fmt(v) {
  const n = numOf(v)
  return n == null ? '—' : n.toFixed(1)
}

function pText(v) {
  const n = numOf(v)
  return n == null ? '—' : `P${Math.round(n)}`
}

async function load() {
  if (!props.sessionId) return
  loading.value = true
  error.value = ''
  try {
    const { data: res } = await http.get(`/interview/lab/peer/${Number(props.sessionId)}`)
    data.value = res || null
  } catch (err) {
    data.value = null
    error.value = err?.response?.data?.detail || err?.message || '请求失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.sessionId,
  () => {
    data.value = null
    load()
  },
  { immediate: true }
)
</script>

<style scoped>
.pb {
  --pb-bg: #0d1117;
  --pb-card: #111827;
  --pb-line: rgba(148, 163, 184, 0.18);
  --pb-text: #e5e7eb;
  --pb-sub: #9ca3af;
  --pb-primary: #3b82f6;
  background: var(--pb-bg);
  color: var(--pb-text);
  border-radius: 14px;
  padding: 18px;
  font-variant-numeric: tabular-nums;
}

.pb :deep(.el-button--primary) {
  --el-button-bg-color: #2563eb;
  --el-button-border-color: #2563eb;
  --el-button-hover-bg-color: #3b82f6;
  --el-button-hover-border-color: #3b82f6;
}

.pb-eyebrow {
  color: #60a5fa;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.pb-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.pb-title {
  margin: 6px 0 0;
  font-size: 17px;
  font-weight: 650;
  color: #f3f4f6;
}

.pb-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--pb-sub);
  font-size: 12px;
}

.pb-meta span {
  padding: 3px 9px;
  border: 1px solid var(--pb-line);
  border-radius: 999px;
  background: rgba(31, 41, 55, 0.35);
}

/* ---------------- 口径提示 ---------------- */
.pb-proxy {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid rgba(251, 191, 36, 0.4);
  border-radius: 12px;
  background: rgba(245, 158, 11, 0.1);
}

.pb-proxy-tag {
  flex: none;
  padding: 1px 8px;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.22);
  color: #fcd34d;
  font-size: 11px;
  font-weight: 700;
}

.pb-proxy-text {
  color: #fde68a;
  font-size: 12.5px;
  line-height: 1.65;
}

/* ---------------- 空态 ---------------- */
.pb-none {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 14px;
  padding: 20px 16px;
  border: 1px dashed rgba(148, 163, 184, 0.28);
  border-radius: 14px;
  background: rgba(17, 24, 39, 0.6);
}

.pb-none b { color: #e5e7eb; font-size: 14px; }
.pb-none span { color: #6b7280; font-size: 12.5px; line-height: 1.7; }

/* ---------------- 卡片 ---------------- */
.pb-card {
  margin-top: 12px;
  padding: 16px;
  border: 1px solid var(--pb-line);
  border-radius: 16px;
  background: var(--pb-card);
}

.pb-card-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.pb-card-head h3 {
  margin: 0;
  color: #f3f4f6;
  font-size: 14px;
  font-weight: 650;
}

.pb-card-sub { color: #6b7280; font-size: 11.5px; }

/* ---------------- 刻度尺 ---------------- */
.pb-ruler {
  position: relative;
  margin-top: 40px;
  padding: 0 4px;
}

.pb-bubble {
  position: absolute;
  top: -34px;
  max-width: 320px;
  padding: 5px 11px;
  border: 1px solid rgba(96, 165, 250, 0.45);
  border-radius: 9px;
  background: #14213b;
  color: #dbeafe;
  font-size: 12px;
  line-height: 1.5;
  white-space: nowrap;
  box-shadow: 0 8px 20px rgba(2, 6, 23, 0.45);
}

.pb-bubble.flat {
  color: #9ca3af;
  border-color: rgba(148, 163, 184, 0.3);
  background: rgba(17, 24, 39, 0.9);
}

.pb-axis {
  position: relative;
  height: 20px;
  border-radius: 999px;
  background: linear-gradient(
    90deg,
    rgba(239, 68, 68, 0.42) 0%,
    rgba(239, 68, 68, 0.42) 25%,
    rgba(245, 158, 11, 0.36) 25%,
    rgba(245, 158, 11, 0.36) 50%,
    rgba(56, 189, 248, 0.34) 50%,
    rgba(56, 189, 248, 0.34) 75%,
    rgba(34, 197, 94, 0.38) 75%,
    rgba(34, 197, 94, 0.38) 100%
  );
  border: 1px solid var(--pb-line);
}

.pb-marker {
  position: absolute;
  top: -6px;
  bottom: -6px;
  width: 2px;
  transform: translateX(-50%);
  background: #f8fafc;
  box-shadow: 0 0 8px rgba(248, 250, 252, 0.55);
}

.pb-marker::before {
  content: '';
  position: absolute;
  left: 50%;
  top: -8px;
  transform: translateX(-50%);
  border-left: 6px solid transparent;
  border-right: 6px solid transparent;
  border-top: 9px solid #f8fafc;
}

.pb-ticks {
  position: relative;
  height: 15px;
  margin-top: 5px;
}

.pb-ticks span {
  position: absolute;
  transform: translateX(-50%);
  color: #64748b;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}

.pb-ticks span:first-child { transform: translateX(0); }
.pb-ticks span:last-child { transform: translateX(-100%); }

.pb-bands {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  margin-top: 8px;
}

.pb-band {
  padding: 2px 0;
  border-radius: 6px;
  text-align: center;
  font-size: 10.5px;
  color: #cbd5e1;
  background: rgba(148, 163, 184, 0.1);
}

.pb-band.band-low { background: rgba(239, 68, 68, 0.16); color: #fca5a5; }
.pb-band.band-midlow { background: rgba(245, 158, 11, 0.14); color: #fcd34d; }
.pb-band.band-midhigh { background: rgba(56, 189, 248, 0.14); color: #bae6fd; }
.pb-band.band-high { background: rgba(34, 197, 94, 0.16); color: #86efac; }

.pb-note {
  margin: 10px 0 0;
  padding-top: 8px;
  border-top: 1px dashed rgba(148, 163, 184, 0.2);
  color: #6b7280;
  font-size: 11.5px;
  line-height: 1.65;
}

/* ---------------- 维度分位 ---------------- */
.pb-dims {
  display: flex;
  flex-direction: column;
  gap: 9px;
  margin-top: 12px;
}

.pb-dim {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
}

.pb-dim-label {
  flex: none;
  width: 62px;
  color: #9ca3af;
}

.pb-dim-track {
  flex: 1;
  height: 12px;
  border-radius: 6px;
  background: #0b1220;
  border: 1px solid transparent;
  overflow: hidden;
}

.pb-dim-track i {
  display: block;
  height: 100%;
  border-radius: 6px;
  background: linear-gradient(90deg, #1d4ed8, #60a5fa);
  transition: width 0.5s;
}

.pb-dim.proxy .pb-dim-track {
  border: 1px dashed rgba(251, 191, 36, 0.55);
  background: transparent;
}

.pb-dim.proxy .pb-dim-track i {
  background: repeating-linear-gradient(135deg, #3b82f6 0 6px, #1d4ed8 6px 12px);
}

.pb-dim-p {
  flex: none;
  width: 42px;
  text-align: right;
  color: #cbd5e1;
  font-size: 12px;
  font-weight: 600;
}

.pb-placeholder { margin: 12px 0 0; color: #6b7280; font-size: 12.5px; }

/* ---------------- 骨架 / 错误 ---------------- */
.pb-skeleton { display: flex; flex-direction: column; gap: 10px; margin-top: 16px; }

.sk-bubble,
.sk-axis,
.sk-line {
  background: linear-gradient(100deg, #131a26 30%, #1b2433 50%, #131a26 70%);
  background-size: 300% 100%;
  animation: pb-shimmer 1.4s ease-in-out infinite;
}

.sk-bubble { width: 240px; height: 26px; border-radius: 8px; }
.sk-axis { height: 20px; border-radius: 999px; }
.sk-line { height: 12px; border-radius: 6px; }

@keyframes pb-shimmer {
  from { background-position: 120% 0; }
  to { background-position: -40% 0; }
}

.pb-error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  margin-top: 14px;
  padding: 16px;
  border: 1px solid rgba(248, 113, 113, 0.32);
  border-radius: 14px;
  background: rgba(239, 68, 68, 0.08);
}

.pb-error-title { color: #fca5a5; font-size: 14px; font-weight: 650; }
.pb-error-detail { margin: 0; color: #e5e7eb; font-size: 13px; line-height: 1.6; }

.pb-empty {
  margin-top: 16px;
  padding: 24px 0;
  text-align: center;
  color: #6b7280;
  font-size: 13px;
}

@media (max-width: 640px) {
  .pb-bubble { white-space: normal; max-width: 210px; }
  .pb-dim-label { width: 52px; }
  .pb-meta { font-size: 11.5px; }
}

@media (prefers-reduced-motion: reduce) {
  .sk-bubble,
  .sk-axis,
  .sk-line { animation: none; }
  .pb-dim-track i { transition: none; }
}
</style>
