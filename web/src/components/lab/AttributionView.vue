<template>
  <div class="att">
    <div v-if="loading && !data" class="att-skeleton" aria-busy="true">
      <div class="sk-head">
        <div class="sk-block"></div>
        <div class="sk-ring"></div>
      </div>
      <div class="sk-line wide"></div>
      <div class="sk-row" v-for="i in 3" :key="i"></div>
    </div>

    <div v-else-if="error" class="att-error" role="alert">
      <div class="att-error-title">失分溯源加载失败</div>
      <p class="att-error-detail">{{ error }}</p>
      <el-button size="small" type="primary" plain @click="load">重试</el-button>
    </div>

    <div v-else-if="!data" class="att-empty">暂无失分溯源数据</div>

    <template v-else>
      <header class="att-head">
        <div class="att-head-main">
          <div class="att-eyebrow">ATTRIBUTION · 失分溯源</div>
          <span class="att-type" :style="typeStyle">{{ typeLabel }}</span>
          <p class="att-head-sub">把「漏掉的考点」反查到课程与成绩，分开「不会说」和「没学扎实」。</p>
        </div>
        <div v-if="sharePct != null && sharePct > 0" class="att-share">
          <div class="att-share-ring">
            <svg viewBox="0 0 72 72" aria-hidden="true">
              <circle cx="36" cy="36" r="30" class="att-share-bg" />
              <circle
                cx="36"
                cy="36"
                r="30"
                class="att-share-fg"
                :style="{ strokeDasharray: `${(sharePct / 100) * 188.5} 188.5`, stroke: tone.color }"
              />
            </svg>
            <b>{{ sharePct }}%</b>
          </div>
          <span class="att-share-label">失分落在薄弱课程上</span>
        </div>
        <!-- 0% 画成空环会被读成「差」，改成明确的好消息 -->
        <div v-else-if="sharePct === 0" class="att-share att-share-zero">
          <span class="att-zero-badge">无薄弱课程失分</span>
          <span class="att-share-label">失分不在成绩差的课上</span>
        </div>
        <!-- 0% 画成空环会被读成「差」，改成明确的好消息 -->
        <div v-else-if="sharePct === 0" class="att-share att-share-zero">
          <span class="att-zero-badge">无薄弱课程失分</span>
          <span class="att-share-label">失分不在成绩差的课上</span>
        </div>
      </header>

      <blockquote v-if="data.narrative" class="att-quote">{{ data.narrative }}</blockquote>

      <section class="att-courses">
        <div class="att-sec-head">
          <span class="att-sec-title">课程归因</span>
          <span class="att-sec-sub" v-if="items.length">{{ items.length }} 个考点匹配到课程</span>
        </div>

        <div v-if="!items.length" class="att-empty-inline">
          <b>本场未发现可归因的失分点</b>
          <span>要么这场几乎没漏考点，要么漏掉的考点没有对应课程记录。</span>
        </div>

        <div v-for="(it, i) in items" :key="itemKey(it, i)" class="att-course">
          <div class="att-course-main">
            <div class="att-course-top">
              <span class="att-course-name">{{ it.course || it.concept || '未命名课程' }}</span>
              <span class="att-verdict" :class="verdictClass(it.verdict)">{{ it.verdict || '未评级' }}</span>
            </div>
            <p v-if="it.concept && it.concept !== it.course" class="att-concept">
              漏掉考点：{{ it.concept }}
            </p>

            <div v-if="pctOf(it.percentile) != null" class="att-mini">
              <div class="att-mini-track">
                <div class="att-mini-fill" :style="{ width: pctOf(it.percentile) + '%' }"></div>
              </div>
              <div class="att-mini-scale">
                <span>0</span><span>50</span><span>100</span>
              </div>
              <span class="att-mini-label">课程分位 {{ fmt(it.percentile) }}</span>
            </div>

            <div class="att-course-foot">
              <span v-for="r in roundsOf(it)" :key="'r' + r" class="att-round">第 {{ r }} 轮</span>
              <span v-if="numOf(it.credit) != null" class="att-credit">{{ fmt(it.credit) }} 学分</span>
            </div>

            <p v-if="it.evidence" class="att-evidence">{{ it.evidence }}</p>
          </div>

          <div class="att-score">
            <b>{{ fmt(it.score) }}</b>
            <span>成绩</span>
          </div>
        </div>
      </section>

      <el-collapse v-if="unmatched.length" v-model="openUnmatched" class="att-collapse">
        <el-collapse-item :title="`未匹配到课程的考点（${unmatched.length}）`" name="unmatched">
          <div class="att-unmatched">
            <span v-for="(u, i) in unmatched" :key="'u' + i" class="att-unmatched-chip">{{ u }}</span>
          </div>
          <p class="att-unmatched-note">这些考点没有对应课程记录，不做硬凑归因。</p>
        </el-collapse-item>
      </el-collapse>

      <section v-if="actions.length" class="att-actions-wrap">
        <div class="att-sec-head">
          <span class="att-sec-title">把失分补回来</span>
          <span class="att-sec-sub">按薄弱程度排序</span>
        </div>
        <ol class="att-actions">
          <li v-for="(a, i) in actions" :key="'a' + i">
            <span class="att-when">{{ a.when || '本周' }}</span>
            <div class="att-action-body">
              <p class="att-what">{{ a.what || '' }}</p>
              <p v-if="a.why" class="att-why">{{ a.why }}</p>
            </div>
          </li>
        </ol>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

import http from '../../api/http'

const props = defineProps({
  sessionId: { type: Number, required: true }
})

const TYPE_META = {
  foundation: { label: '基础薄弱型', color: '#f97316' },
  expression: { label: '表达组织型', color: '#3b82f6' },
  mixed: { label: '混合型', color: '#a855f7' },
  unknown: { label: '证据不足', color: '#6b7280' }
}

const data = ref(null)
const loading = ref(false)
const error = ref('')
const openUnmatched = ref([])

const tone = computed(() => TYPE_META[data.value?.type] || TYPE_META.unknown)
const typeLabel = computed(() => data.value?.type_label || tone.value.label)
const items = computed(() => (Array.isArray(data.value?.items) ? data.value.items : []))
const unmatched = computed(() => (Array.isArray(data.value?.unmatched) ? data.value.unmatched.filter(Boolean) : []))
const actions = computed(() => (Array.isArray(data.value?.actions) ? data.value.actions : []))

const sharePct = computed(() => {
  const v = numOf(data.value?.missed_share_weak)
  if (v == null) return null
  return Math.round(Math.min(1, Math.max(0, v)) * 100)
})

const typeStyle = computed(() => ({
  color: tone.value.color,
  borderColor: hexToRgba(tone.value.color, 0.45),
  background: hexToRgba(tone.value.color, 0.12)
}))

function numOf(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function fmt(v) {
  const n = numOf(v)
  return n == null ? '—' : n.toFixed(1)
}

function pctOf(v) {
  const n = numOf(v)
  if (n == null) return null
  return Math.min(100, Math.max(0, n))
}

function hexToRgba(hex, alpha) {
  const h = String(hex || '').replace('#', '')
  if (h.length !== 6) return `rgba(148, 163, 184, ${alpha})`
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function roundsOf(it) {
  const list = Array.isArray(it?.rounds) ? it.rounds : []
  return list.filter((r) => r !== null && r !== undefined && r !== '')
}

function itemKey(it, i) {
  if (it?.course_id != null) return `c-${it.course_id}-${i}`
  return `c-${it?.course || it?.concept || 'x'}-${i}`
}

function verdictClass(verdict) {
  const text = String(verdict || '')
  if (text.includes('薄弱')) return 'weak'
  if (text.includes('一般')) return 'fair'
  if (text.includes('良好')) return 'good'
  return 'flat'
}

async function load() {
  if (!props.sessionId) return
  loading.value = true
  error.value = ''
  try {
    const { data: res } = await http.get(`/interview/lab/attribution/${Number(props.sessionId)}`)
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
    openUnmatched.value = []
    load()
  },
  { immediate: true }
)
</script>

<style scoped>
.att {
  --att-bg: #0d1117;
  --att-card: #111827;
  --att-line: rgba(148, 163, 184, 0.18);
  --att-text: #e5e7eb;
  --att-sub: #9ca3af;
  --att-primary: #3b82f6;
  background: var(--att-bg);
  color: var(--att-text);
  border-radius: 14px;
  padding: 18px;
  font-variant-numeric: tabular-nums;
}

.att :deep(.el-button--primary) {
  --el-button-bg-color: #2563eb;
  --el-button-border-color: #2563eb;
  --el-button-hover-bg-color: #3b82f6;
  --el-button-hover-border-color: #3b82f6;
}

.att-eyebrow {
  color: #60a5fa;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

/* ---------------- 头部 ---------------- */
.att-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.att-head-main { min-width: 0; flex: 1; }

.att-type {
  display: inline-block;
  margin-top: 8px;
  padding: 5px 16px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.att-head-sub {
  margin: 8px 0 0;
  max-width: 560px;
  color: var(--att-sub);
  font-size: 12.5px;
  line-height: 1.7;
}

.att-share {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  flex: none;
  min-width: 108px;
}

.att-share-ring {
  position: relative;
  width: 74px;
  height: 74px;
}

.att-share-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.att-share-bg { fill: none; stroke: #1f2937; stroke-width: 7; }
.att-share-fg { fill: none; stroke-width: 7; stroke-linecap: round; transition: stroke-dasharray 0.6s; }

.att-share-ring b {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #f3f4f6;
  font-size: 18px;
  font-weight: 700;
}

.att-share-zero { flex-direction: column; align-items: flex-end; gap: 6px; }
.att-zero-badge {
  padding: 5px 12px; font-size: 12px; color: #34d399;
  border: 1px solid rgba(52, 211, 153, .45); border-radius: 999px;
  background: rgba(52, 211, 153, .12);
}
.att-share-zero { flex-direction: column; align-items: flex-end; gap: 6px; }
.att-zero-badge {
  padding: 5px 12px; font-size: 12px; color: #34d399;
  border: 1px solid rgba(52, 211, 153, .45); border-radius: 999px;
  background: rgba(52, 211, 153, .12);
}
.att-share-label {
  color: #6b7280;
  font-size: 11px;
  text-align: center;
  line-height: 1.5;
}

/* ---------------- 结论 ---------------- */
.att-quote {
  margin: 14px 0 0;
  padding: 10px 14px;
  border-left: 3px solid var(--att-primary);
  border-radius: 0 10px 10px 0;
  background: rgba(59, 130, 246, 0.08);
  color: #dbeafe;
  font-size: 13.5px;
  line-height: 1.8;
}

/* ---------------- 课程卡 ---------------- */
.att-courses { margin-top: 16px; }

.att-sec-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
}

.att-sec-title { color: #f3f4f6; font-size: 14px; font-weight: 650; }
.att-sec-sub { color: #6b7280; font-size: 11.5px; }

.att-empty-inline {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px;
  border: 1px dashed rgba(148, 163, 184, 0.28);
  border-radius: 12px;
  background: rgba(17, 24, 39, 0.6);
}

.att-empty-inline b { color: #e5e7eb; font-size: 13.5px; }
.att-empty-inline span { color: #6b7280; font-size: 12.5px; line-height: 1.6; }

.att-course {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 13px 15px;
  margin-bottom: 10px;
  border: 1px solid var(--att-line);
  border-radius: 14px;
  background: var(--att-card);
}

.att-course-main { flex: 1; min-width: 0; }

.att-course-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.att-course-name {
  color: #f3f4f6;
  font-size: 14.5px;
  font-weight: 650;
}

.att-verdict {
  padding: 1px 8px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.att-verdict.weak {
  border-color: rgba(251, 146, 60, 0.45);
  background: rgba(249, 115, 22, 0.14);
  color: #fdba74;
}

.att-verdict.fair {
  border-color: rgba(96, 165, 250, 0.4);
  background: rgba(37, 99, 235, 0.14);
  color: #bfdbfe;
}

.att-verdict.good {
  border-color: rgba(52, 211, 153, 0.4);
  background: rgba(16, 185, 129, 0.14);
  color: #6ee7b7;
}

.att-verdict.flat {
  border-color: rgba(148, 163, 184, 0.3);
  background: rgba(148, 163, 184, 0.1);
  color: #cbd5e1;
}

.att-concept {
  margin: 5px 0 0;
  color: #9ca3af;
  font-size: 12.5px;
  line-height: 1.6;
}

.att-mini { margin-top: 9px; max-width: 320px; }

.att-mini-track {
  height: 7px;
  border-radius: 4px;
  background: #0b1220;
  border: 1px solid var(--att-line);
  overflow: hidden;
}

.att-mini-fill {
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, #1d4ed8, #60a5fa);
  transition: width 0.5s;
}

.att-mini-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 2px;
  color: #4b5563;
  font-size: 9.5px;
}

.att-mini-label {
  display: block;
  margin-top: 2px;
  color: #93c5fd;
  font-size: 11px;
}

.att-course-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 9px;
}

.att-round {
  padding: 1px 8px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.7);
  color: #cbd5e1;
  font-size: 11px;
}

.att-credit { color: #6b7280; font-size: 11px; }

.att-evidence {
  margin: 8px 0 0;
  color: #9ca3af;
  font-size: 12px;
  line-height: 1.6;
}

.att-score {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  flex: none;
  min-width: 64px;
}

.att-score b {
  color: #f9fafb;
  font-size: 26px;
  font-weight: 700;
  line-height: 1.1;
}

.att-score span { color: #6b7280; font-size: 10.5px; }

/* ---------------- 未匹配折叠 ---------------- */
.att-collapse {
  margin-top: 4px;
  border-top: 1px solid var(--att-line);
  border-bottom: 1px solid var(--att-line);
  --el-collapse-header-bg-color: transparent;
  --el-collapse-content-bg-color: transparent;
  --el-collapse-border-color: transparent;
  --el-collapse-header-text-color: #cbd5e1;
  --el-collapse-content-text-color: #9ca3af;
}

.att-collapse :deep(.el-collapse-item__header) {
  background: transparent;
  border-bottom: none;
  color: #cbd5e1;
  font-size: 13px;
}

.att-collapse :deep(.el-collapse-item__wrap) {
  background: transparent;
  border-bottom: none;
}

.att-collapse :deep(.el-collapse-item__content) { padding-bottom: 12px; }

.att-unmatched { display: flex; flex-wrap: wrap; gap: 7px; }

.att-unmatched-chip {
  padding: 2px 10px;
  border: 1px dashed rgba(148, 163, 184, 0.35);
  border-radius: 999px;
  color: #cbd5e1;
  font-size: 11.5px;
}

.att-unmatched-note {
  margin: 9px 0 0;
  color: #6b7280;
  font-size: 11.5px;
}

/* ---------------- 行动时间轴 ---------------- */
.att-actions-wrap { margin-top: 16px; }

.att-actions {
  margin: 0;
  padding: 0;
  list-style: none;
}

.att-actions li {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 9px 0 9px 16px;
}

.att-actions li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(148, 163, 184, 0.22);
}

.att-actions li::after {
  content: '';
  position: absolute;
  left: -4px;
  top: 16px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid #60a5fa;
  background: var(--att-bg);
}

.att-actions li:first-child::before { top: 16px; }
.att-actions li:last-child::before { bottom: auto; height: 16px; }

.att-when {
  flex: none;
  height: 22px;
  padding: 0 10px;
  border: 1px solid rgba(96, 165, 250, 0.35);
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.14);
  color: #bfdbfe;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 20px;
  white-space: nowrap;
}

.att-action-body { min-width: 0; }

.att-what {
  margin: 0;
  color: #e5e7eb;
  font-size: 13px;
  line-height: 1.65;
}

.att-why {
  margin: 3px 0 0;
  color: #6b7280;
  font-size: 12px;
  line-height: 1.6;
}

/* ---------------- 骨架 / 错误 / 空态 ---------------- */
.att-skeleton { display: flex; flex-direction: column; gap: 12px; }

.sk-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.sk-block,
.sk-line,
.sk-row,
.sk-ring {
  background: linear-gradient(100deg, #131a26 30%, #1b2433 50%, #131a26 70%);
  background-size: 300% 100%;
  animation: att-shimmer 1.4s ease-in-out infinite;
}

.sk-block { width: 180px; height: 34px; border-radius: 999px; }
.sk-ring { width: 74px; height: 74px; border-radius: 50%; }
.sk-line { height: 13px; border-radius: 6px; width: 46%; }
.sk-line.wide { width: 72%; height: 16px; }
.sk-row { height: 84px; border-radius: 14px; }

@keyframes att-shimmer {
  from { background-position: 120% 0; }
  to { background-position: -40% 0; }
}

.att-error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 16px;
  border: 1px solid rgba(248, 113, 113, 0.32);
  border-radius: 14px;
  background: rgba(239, 68, 68, 0.08);
}

.att-error-title { color: #fca5a5; font-size: 14px; font-weight: 650; }
.att-error-detail { margin: 0; color: #e5e7eb; font-size: 13px; line-height: 1.6; }

.att-empty {
  padding: 26px 0;
  text-align: center;
  color: #6b7280;
  font-size: 13px;
}

@media (max-width: 640px) {
  .att-course { flex-direction: column; }
  .att-score { flex-direction: row; align-items: baseline; gap: 6px; }
  .att-share { align-items: flex-start; }
}

@media (prefers-reduced-motion: reduce) {
  .sk-block,
  .sk-line,
  .sk-row,
  .sk-ring { animation: none; }
  .att-mini-fill,
  .att-share-fg { transition: none; }
}
</style>
