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

      <!-- 同题型趋势：最近最多 3 场。后端给的是「场次 × 题型」平铺列表，
           同一场含多个题型时在一场内取均值，一个场次只落一个点。 -->
      <section class="att-trend">
        <div class="att-sec-head">
          <span class="att-sec-title">同题型得分趋势</span>
          <span v-if="trendPoints.length" class="att-sec-sub">最近 {{ trendPoints.length }} 场 · 含本场</span>
        </div>
        <div v-if="trendPoints.length" class="att-trend-body">
          <div
            ref="trendRef"
            class="att-trend-chart"
            role="img"
            :aria-label="trendAria"
          ></div>
          <ol class="att-trend-list" aria-label="各场次得分读数">
            <li v-for="p in trendPoints" :key="p.sid">
              <span class="att-trend-date">{{ p.asOf || '时间未记录' }}</span>
              <b class="att-trend-score">{{ p.score }}</b>
            </li>
          </ol>
          <p v-if="trendAveraged" class="att-trend-note">同一场含多个同题型考点，取平均分</p>
        </div>
        <div v-else class="att-empty-inline att-empty-slim">
          <span>暂无该维度数据</span>
        </div>
      </section>

      <!-- 相关课程提示：失分维度 → 对应课程 → 本人在该课的分位 -->
      <section class="att-hints">
        <div class="att-sec-head">
          <span class="att-sec-title">相关课程</span>
          <span v-if="courseHints.length" class="att-sec-sub">{{ courseHints.length }} 个失分维度对应到课程</span>
        </div>
        <div v-if="courseHints.length" class="att-hint-row">
          <span v-for="(h, i) in courseHints" :key="'h' + i" class="att-hint">
            <span class="att-hint-dim">{{ h.dimension }}</span>
            <span class="att-hint-sep" aria-hidden="true">·</span>
            <span class="att-hint-course">{{ h.course }}</span>
            <span v-if="h.percentile != null" class="att-hint-pct">本人该课分位 {{ h.percentile }}</span>
            <span v-else class="att-hint-pct is-missing">本人分位未记录</span>
          </span>
        </div>
        <div v-else class="att-empty-inline att-empty-slim">
          <span>暂无该维度数据</span>
        </div>
      </section>

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
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import http from '../../api/http'
import echarts from '../../utils/echarts'

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

// ---- 同题型趋势：后端 trend = [{sid, as_of, type, score}]（场次 × 题型，平铺） ----
// 按场次聚成一个点：同一场多个题型的分数取平均。score 不是有限数字的条目直接丢弃，
// 缺失或全空时 trendPoints 为空，界面显示「暂无该维度数据」，不画 0。
const trendRef = ref(null)
let trendChart = null
const trendPoints = computed(() => {
  const raw = data.value?.trend
  if (!Array.isArray(raw)) return []
  const bySid = new Map()
  for (const row of raw) {
    const sid = row?.sid
    const score = numOf(row?.score)
    if (sid === null || sid === undefined || sid === '' || score == null) continue
    const key = String(sid)
    if (!bySid.has(key)) {
      bySid.set(key, { sid: key, asOf: dayOf(row.as_of), scores: [] })
    }
    bySid.get(key).scores.push(score)
  }
  // 时间升序（旧 → 新）；时间相同或缺失时按场次编号升序，保证同输入同顺序
  return [...bySid.values()]
    .map((p) => ({ sid: p.sid, asOf: p.asOf, score: Math.round((sum(p.scores) / p.scores.length) * 10) / 10 }))
    .sort((a, b) => String(a.asOf || '').localeCompare(String(b.asOf || '')) || a.sid.localeCompare(b.sid))
})
// 是否发生过「同一场多个题型取均值」——发生过才显示说明，没发生不啰嗦
const trendAveraged = computed(() => {
  const raw = data.value?.trend
  if (!Array.isArray(raw)) return false
  const countBySid = new Map()
  for (const row of raw) {
    const key = String(row?.sid)
    countBySid.set(key, (countBySid.get(key) || 0) + 1)
  }
  return [...countBySid.values()].some((n) => n > 1)
})
const trendAria = computed(() => {
  if (!trendPoints.value.length) return '同题型得分趋势：暂无数据'
  const parts = trendPoints.value.map((p) => `${p.asOf || '时间未记录'} 得 ${p.score} 分`)
  return `同题型得分趋势折线图，最近 ${trendPoints.value.length} 场，由早到晚：${parts.join('，')}`
})

// ---- 相关课程：后端 course_hint = [{dimension, course, percentile}] ----
// percentile 缺失时保留 null，标签上如实写「未记录」，不补 0
const courseHints = computed(() => {
  const raw = data.value?.course_hint
  if (!Array.isArray(raw)) return []
  return raw
    .filter((h) => h && String(h.dimension || '').trim() && String(h.course || '').trim())
    .map((h) => ({
      dimension: String(h.dimension).trim(),
      course: String(h.course).trim(),
      percentile: numOf(h.percentile),
    }))
})

function dayOf(value) {
  // 后端给的是 'YYYY-MM-DD HH:MM:SS' 或 'YYYY-MM-DD'，只取日期部分；非法值返回空串
  const text = String(value || '')
  return /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(0, 10) : ''
}

function sum(list) {
  return list.reduce((acc, n) => acc + n, 0)
}

function renderTrend() {
  const points = trendPoints.value
  if (!points.length || !trendRef.value) return
  const chart = ensureTrendChart()
  if (!chart) return
  chart.setOption({
    animation: false,
    grid: { left: 8, right: 16, top: 14, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#111827',
      borderColor: 'rgba(148, 163, 184, 0.35)',
      textStyle: { color: '#e5e7eb', fontSize: 12 },
      formatter: (params) => {
        const p = params?.[0]
        const hit = points[p?.dataIndex]
        return hit ? `${hit.asOf || '时间未记录'}<br/>同题型得分：${hit.score}` : ''
      }
    },
    xAxis: {
      type: 'category',
      data: points.map((p) => p.asOf || '—'),
      axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.3)' } },
      axisTick: { show: false },
      axisLabel: { color: '#9ca3af', fontSize: 10.5, interval: 0 }
    },
    yAxis: {
      type: 'value',
      // 纵轴固定 0~100：分数的量程是确定的，不随数据伸缩，避免 2 个相近分数看起来像陡崖
      min: 0, max: 100,
      splitNumber: 2,
      axisLabel: { color: '#6b7280', fontSize: 10.5 },
      splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.14)' } }
    },
    series: [{
      type: 'line',
      data: points.map((p) => p.score),
      symbol: 'circle', symbolSize: 7,
      lineStyle: { color: '#3b82f6', width: 2 },
      itemStyle: { color: '#3b82f6', borderColor: '#0d1117', borderWidth: 2 },
      label: { show: true, color: '#e5e7eb', fontSize: 11, position: 'top' }
    }]
  }, true)
}

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

// 趋势图：数据变化后等 DOM 更新（容器是 v-if 控制的）再初始化 / 重绘
watch(trendPoints, async () => {
  await nextTick()
  renderTrend()
})

// 图表是 v-if 控制的：数据清空时容器已被移除，旧实例要销毁，否则下次会挂到失效的节点上
watch(() => trendPoints.value.length, (len) => {
  if (len === 0 && trendChart) disposeTrendChart()
})

function resizeTrend() {
  trendChart?.resize()
}

window.addEventListener('resize', resizeTrend)

// 本组件可能挂在 v-show 隐藏的工位里（宽度为 0）。用 ResizeObserver 盯住容器：
// 图表在 0 宽度下初始化后，等工位切出来、容器有了尺寸，再自动重绘一次。
let trendObserver = null

function ensureTrendChart() {
  if (!trendRef.value) return null
  if (!trendChart) {
    trendChart = echarts.init(trendRef.value)
    if (typeof ResizeObserver !== 'undefined') {
      trendObserver = new ResizeObserver(() => trendChart?.resize())
      trendObserver.observe(trendRef.value)
    }
  }
  return trendChart
}

function disposeTrendChart() {
  trendObserver?.disconnect()
  trendObserver = null
  trendChart?.dispose()
  trendChart = null
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeTrend)
  disposeTrendChart()
})
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

/* ---------------- 同题型趋势 ---------------- */
.att-trend, .att-hints { margin-top: 16px; }
.att-trend-body { position: relative; }
.att-trend-chart { width: 100%; height: 132px; }
.att-trend-list {
  display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 6px 0 0; padding: 0; list-style: none;
}
.att-trend-list li { display: inline-flex; align-items: baseline; gap: 6px; font-size: 11.5px; }
.att-trend-date { color: #6b7280; font-variant-numeric: tabular-nums; }
.att-trend-score { color: #e5e7eb; font-weight: 650; }
.att-trend-note { margin: 6px 0 0; color: #6b7280; font-size: 11.5px; }
/* 空态比「课程归因」的更矮：这里只是一行说明，不需要 16px 内边距的大块 */
.att-empty-slim { padding: 10px 14px; }
.att-empty-slim span { color: #9ca3af; }

/* ---------------- 相关课程 ---------------- */
.att-hint-row { display: flex; flex-wrap: wrap; gap: 8px; }
.att-hint {
  display: inline-flex; align-items: baseline; flex-wrap: wrap; gap: 5px;
  padding: 5px 12px; border: 1px solid rgba(59, 130, 246, 0.28); border-radius: 999px;
  background: rgba(37, 99, 235, 0.1); font-size: 12px; line-height: 1.6;
}
.att-hint-dim { color: #f3f4f6; font-weight: 600; }
.att-hint-sep { color: #6b7280; }
.att-hint-course { color: #bfdbfe; }
.att-hint-pct { color: #93c5fd; font-variant-numeric: tabular-nums; }
.att-hint-pct.is-missing { color: #6b7280; }

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
