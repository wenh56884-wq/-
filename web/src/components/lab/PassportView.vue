<template>
  <div class="lab-passport" v-loading="loading">
    <!-- 头部：场次 + 成长值 + 一致性徽标 -->
    <header class="pp-head">
      <div class="pp-head-main">
        <h2 class="pp-title">能力护照</h2>
        <div class="pp-meta">
          <span class="pp-count">{{ sessionCount }} 场已完成</span>
          <span v-if="growth" class="pp-delta" :class="deltaClass">
            <svg v-if="deltaSign !== 0" class="pp-arrow" viewBox="0 0 12 12" aria-hidden="true">
              <path d="M6 2.2 10 7H2z" />
            </svg>
            <span class="pp-delta-num">{{ deltaText }}</span>
            <span class="pp-delta-label">成长值</span>
          </span>
        </div>
      </div>
      <div v-if="consistencyText" class="pp-badge" :title="CONSISTENCY_TIP">
        一致性 <b>{{ consistencyText }}</b>
      </div>
    </header>

    <el-alert v-if="errorTip" class="pp-alert" type="warning" :closable="false" show-icon
      :title="errorTip" />

    <!-- 空态：不渲染任何图表 -->
    <div v-if="loaded && isEmpty" class="pp-empty">
      <svg class="pp-empty-icon" viewBox="0 0 48 48" aria-hidden="true">
        <rect x="8" y="10" width="32" height="28" rx="4" />
        <path d="M16 22h16M16 29h10" />
      </svg>
      <p class="pp-empty-title">还没有已完成的模拟面试</p>
      <p class="pp-empty-desc">去面试房完成一场，护照会记下你的四维达标情况与成长曲线。</p>
      <el-button type="primary" @click="goInterview">去面试房完成一场</el-button>
    </div>

    <template v-else-if="loaded">
      <div class="pp-grid">
        <!-- 四维雷达 -->
        <section class="pp-card">
          <div class="pp-card-head">
            <h3>四维雷达</h3>
            <span class="pp-card-sub">最新一场 vs 岗位达标线</span>
          </div>
          <div v-if="radar.length" ref="radarRef" class="pp-chart pp-chart-radar"></div>
          <p v-else class="pp-placeholder">暂无维度数据</p>
          <p v-if="unhitLabels.length" class="pp-unhit">
            <span class="pp-unhit-dot"></span>未达标维度：{{ unhitLabels.join('、') }}
          </p>
        </section>

        <!-- 成长折线 -->
        <section class="pp-card">
          <div class="pp-card-head">
            <h3>成长折线</h3>
            <span class="pp-card-sub">每场总分</span>
          </div>
          <div v-if="canTrend" ref="trendRef" class="pp-chart pp-chart-trend"></div>
          <p v-else class="pp-placeholder">至少完成 2 场模拟面试，才能画出一条成长曲线。</p>
        </section>
      </div>

      <!-- 维度明细 -->
      <section v-if="radar.length" class="pp-card">
        <div class="pp-card-head">
          <h3>维度明细</h3>
          <span class="pp-card-sub">蓝条=最新 · 细条=达标线 · 竖线=达标阈值</span>
        </div>
        <div v-for="dim in radar" :key="dim.key" class="dim-row">
          <div class="dim-label">
            <span>{{ dim.label }}</span>
            <span v-if="dim.hit" class="dim-hit">
              <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 6.4 4.8 9 10 3.4" /></svg>
              已达标
            </span>
          </div>
          <div class="dim-bars">
            <div class="dim-bar">
              <div class="dim-fill" :style="{ width: pct(dim.latest) + '%' }"></div>
              <div class="dim-target" :class="{ reached: dim.hit }"
                :style="{ left: pct(dim.target) + '%' }"></div>
            </div>
            <div class="dim-bar dim-bar-sub">
              <div class="dim-target-fill" :style="{ width: pct(dim.target) + '%' }"></div>
            </div>
          </div>
          <div class="dim-values">
            <span class="dim-latest">{{ fmt(dim.latest) }}</span>
            <span class="dim-gap" :class="dim.hit ? 'gap-ok' : 'gap-warn'">
              {{ dim.hit ? '超 ' + fmt(exceedOf(dim)) : '差 ' + fmt(dim.gap) }}
            </span>
          </div>
        </div>
      </section>

      <!-- 徽章墙 -->
      <section v-if="badges.length" class="pp-card">
        <div class="pp-card-head">
          <h3>徽章墙</h3>
          <span class="pp-card-sub">已点亮 {{ earnedCount }} / {{ badges.length }}</span>
        </div>
        <div class="badge-grid">
          <div v-for="badge in badges" :key="badge.id" class="badge-card"
            :class="{ earned: badge.earned }">
            <div class="badge-icon">
              <svg v-if="badge.earned" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M5 12.5 10 17.5 19 7" />
              </svg>
              <svg v-else viewBox="0 0 24 24" aria-hidden="true">
                <rect x="5" y="10.5" width="14" height="9" rx="2" />
                <path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" />
              </svg>
            </div>
            <div class="badge-title">{{ badge.title }}</div>
            <div class="badge-desc">{{ badge.desc }}</div>
            <span class="badge-state">{{ badge.earned ? '已获得' : '未解锁' }}</span>
          </div>
        </div>
      </section>

      <!-- 下一步动作 -->
      <section v-if="nextAction" class="next-card">
        <div class="next-head">
          <span class="next-eyebrow">下一步动作</span>
          <span class="next-gap">差 {{ fmt(nextAction.gap) }}</span>
        </div>
        <div class="next-label">{{ nextAction.label || '继续练习' }}</div>
        <p v-if="nextAction.action" class="next-action">本周动作：{{ nextAction.action }}</p>
        <blockquote v-if="nextAction.drill" class="next-drill">{{ nextAction.drill }}</blockquote>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { MarkPointComponent } from 'echarts/components'
import echarts from '../../utils/echarts'
import api from '../../api/http'

// 折线首末点标注需要 MarkPointComponent；utils/echarts.js 不在本任务改动范围，
// 故按 CampusInsight.vue 的做法在本组件按需补注册（同一 core 实例，只增大本 chunk）。
echarts.use([MarkPointComponent])

const props = defineProps({
  // 外部（容器）在完成新一场面试后自增，用于强制重拉数据
  refreshKey: { type: Number, default: 0 }
})
const emit = defineEmits(['loaded'])

const CONSISTENCY_TIP = '跨场次发挥稳定度：越接近 1，说明每场分数波动越小'
const AXIS_COLOR = '#1f2937'
const TEXT_SUB = '#9ca3af'
const PRIMARY = '#3b82f6'
const TARGET_COLOR = '#f59e0b'

const router = useRouter()
const loading = ref(false)
const loaded = ref(false)
const errorTip = ref('')
const data = ref({})

let radarInstance = null
let trendInstance = null
let resizeObserver = null

const radarRef = ref(null)
const trendRef = ref(null)

const radar = computed(() => (Array.isArray(data.value?.radar) ? data.value.radar : []))
const trend = computed(() => (Array.isArray(data.value?.trend) ? data.value.trend : []))
const badges = computed(() => (Array.isArray(data.value?.badges) ? data.value.badges : []))
const growth = computed(() => data.value?.growth || null)
const nextAction = computed(() => data.value?.next_action || null)
const isEmpty = computed(() => data.value?.empty === true)

const sessionCount = computed(() => {
  const n = Number(data.value?.sessions)
  return Number.isFinite(n) ? n : 0
})

const canTrend = computed(() => trend.value.length >= 2)
const earnedCount = computed(() => badges.value.filter((item) => item?.earned).length)
const unhitLabels = computed(() =>
  radar.value.filter((dim) => dim && dim.hit === false).map((dim) => dim.label).filter(Boolean)
)

const deltaSign = computed(() => {
  const n = num(growth.value?.delta)
  if (n === null || n === 0) return 0
  return n > 0 ? 1 : -1
})
const deltaClass = computed(() => (deltaSign.value > 0 ? 'up' : deltaSign.value < 0 ? 'down' : 'flat'))
const deltaText = computed(() => {
  const n = num(growth.value?.delta)
  if (n === null) return '—'
  if (n === 0) return '持平'
  return `${n > 0 ? '+' : ''}${n.toFixed(1)}`
})
const consistencyText = computed(() => {
  const n = num(growth.value?.consistency)
  return n === null ? '' : n.toFixed(2)
})

function num(value) {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function fmt(value) {
  const n = num(value)
  return n === null ? '—' : n.toFixed(1)
}

function pct(value) {
  const n = num(value)
  if (n === null) return 0
  return Math.max(0, Math.min(100, n))
}

// 达标后「超」多少：latest 高于 target 的部分（缺字段时按 0 兜底）
function exceedOf(dim) {
  const latest = num(dim?.latest)
  const target = num(dim?.target)
  if (latest === null || target === null) return null
  return Math.max(0, latest - target)
}

function dateLabel(value) {
  const text = String(value || '')
  return /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(5) : text
}

function disposeCharts() {
  radarInstance?.dispose()
  trendInstance?.dispose()
  radarInstance = null
  trendInstance = null
}

function ensureInstance(instance, el) {
  if (!instance) return echarts.init(el)
  // 容器 DOM 被 v-if 重建过时旧实例已失效，先销毁再重建，避免绑在脱离文档的节点上
  if (instance.getDom() !== el) {
    instance.dispose()
    return echarts.init(el)
  }
  return instance
}

function renderRadar() {
  if (!radarRef.value || !radar.value.length) return
  radarInstance = ensureInstance(radarInstance, radarRef.value)
  const dims = radar.value
  radarInstance.setOption(
    {
      backgroundColor: 'transparent',
      animationDuration: 700,
      tooltip: {
        trigger: 'item',
        backgroundColor: '#111827',
        borderColor: AXIS_COLOR,
        textStyle: { color: '#e5e7eb', fontSize: 12 }
      },
      legend: {
        bottom: 0,
        itemWidth: 10,
        itemHeight: 10,
        icon: 'roundRect',
        textStyle: { color: TEXT_SUB, fontSize: 12 }
      },
      radar: {
        center: ['50%', '46%'],
        radius: '62%',
        indicator: dims.map((dim) => ({ name: dim?.label || '维度', max: 100 })),
        axisName: { color: TEXT_SUB, fontSize: 12 },
        axisLine: { lineStyle: { color: AXIS_COLOR } },
        splitLine: { lineStyle: { color: AXIS_COLOR } },
        splitArea: {
          areaStyle: { color: ['rgba(17, 24, 39, 0.45)', 'rgba(13, 17, 23, 0.45)'] }
        }
      },
      series: [
        {
          type: 'radar',
          symbol: 'circle',
          symbolSize: 5,
          data: [
            {
              name: '我的最新',
              value: dims.map((dim) => pct(dim?.latest)),
              itemStyle: { color: PRIMARY },
              lineStyle: { width: 2, color: PRIMARY },
              areaStyle: { color: 'rgba(59, 130, 246, 0.24)' }
            },
            {
              name: '岗位达标线',
              value: dims.map((dim) => pct(dim?.target)),
              itemStyle: { color: TARGET_COLOR },
              lineStyle: { width: 2, color: TARGET_COLOR, type: 'dashed' },
              areaStyle: { color: 'transparent' },
              symbolSize: 4
            }
          ]
        }
      ]
    },
    true
  )
  radarInstance.resize()
}

function renderTrend() {
  if (!trendRef.value || !canTrend.value) return
  trendInstance = ensureInstance(trendInstance, trendRef.value)
  const rows = trend.value
  const labels = rows.map((row) => String(row?.date || ''))
  const totals = rows.map((row) => pct(row?.total))
  const marks = []
  const first = rows[0]
  const last = rows[rows.length - 1]
  if (first) {
    marks.push({ name: '起始', coord: [0, totals[0]], value: fmt(first.total) })
  }
  if (last && rows.length > 1) {
    marks.push({ name: '最新', coord: [rows.length - 1, totals[totals.length - 1]], value: fmt(last.total) })
  }

  trendInstance.setOption(
    {
      backgroundColor: 'transparent',
      animationDuration: 700,
      grid: { left: 44, right: 26, top: 46, bottom: 34 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#111827',
        borderColor: AXIS_COLOR,
        textStyle: { color: '#e5e7eb', fontSize: 12 },
        formatter: (params) => {
          const hit = Array.isArray(params) ? params[0] : params
          const row = rows[hit?.dataIndex] || {}
          const head = row.date || labels[hit?.dataIndex] || ''
          const job = row.job_title || '未命名岗位'
          return `${head}<br/>${job}<br/>总分 <b>${fmt(row.total)}</b>`
        }
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: labels,
        axisLine: { lineStyle: { color: AXIS_COLOR } },
        axisTick: { show: false },
        axisLabel: {
          color: TEXT_SUB,
          fontSize: 11,
          formatter: (value) => dateLabel(value)
        }
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: AXIS_COLOR, type: 'dashed' } },
        axisLabel: { color: TEXT_SUB, fontSize: 11 }
      },
      series: [
        {
          type: 'line',
          name: '总分',
          data: totals,
          smooth: true,
          symbol: 'circle',
          symbolSize: 7,
          itemStyle: { color: PRIMARY, borderColor: '#0d1117', borderWidth: 2 },
          lineStyle: { width: 2.5, color: PRIMARY },
          areaStyle: { color: 'rgba(59, 130, 246, 0.16)' },
          markPoint: {
            symbol: 'pin',
            symbolSize: 44,
            itemStyle: { color: PRIMARY },
            label: { color: '#f9fafb', fontSize: 11, fontWeight: 600 },
            data: marks
          }
        }
      ]
    },
    true
  )
  trendInstance.resize()
}

function observeCharts() {
  if (typeof ResizeObserver === 'undefined') return
  resizeObserver?.disconnect()
  resizeObserver = new ResizeObserver(() => {
    radarInstance?.resize()
    trendInstance?.resize()
  })
  if (radarRef.value) resizeObserver.observe(radarRef.value)
  if (trendRef.value) resizeObserver.observe(trendRef.value)
}

async function paint() {
  await nextTick()
  renderRadar()
  renderTrend()
  observeCharts()
}

function onResize() {
  radarInstance?.resize()
  trendInstance?.resize()
}

async function load() {
  loading.value = true
  errorTip.value = ''
  try {
    const { data: res } = await api.get('/interview/lab/passport')
    data.value = res || {}
    loaded.value = true
    emit('loaded', data.value)
    await paint()
  } catch (err) {
    data.value = {}
    loaded.value = false
    errorTip.value = err?.response?.data?.detail || '能力护照加载失败，稍后再试'
  } finally {
    loading.value = false
  }
}

function goInterview() {
  router.push('/student/interview')
}

watch(
  () => props.refreshKey,
  () => {
    load()
  }
)

onMounted(() => {
  window.addEventListener('resize', onResize)
  load()
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  resizeObserver?.disconnect()
  resizeObserver = null
  disposeCharts()
})
</script>

<style scoped>
.lab-passport {
  --pp-bg: #0d1117;
  --pp-card: #111827;
  --pp-line: #1f2937;
  --pp-text: #e5e7eb;
  --pp-sub: #9ca3af;
  --pp-primary: #3b82f6;
  --pp-target: #f59e0b;
  background: var(--pp-bg);
  color: var(--pp-text);
  border-radius: 12px;
  padding: 18px;
  font-variant-numeric: tabular-nums;
}

.lab-passport :deep(.el-loading-mask) {
  background: rgba(13, 17, 23, 0.72);
}

.lab-passport :deep(.el-button--primary) {
  --el-button-bg-color: #2563eb;
  --el-button-border-color: #2563eb;
  --el-button-hover-bg-color: #3b82f6;
  --el-button-hover-border-color: #3b82f6;
  --el-button-active-bg-color: #1d4ed8;
  --el-button-active-border-color: #1d4ed8;
}

.pp-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.pp-title {
  margin: 0;
  font-size: 20px;
  font-weight: 650;
  letter-spacing: 0.4px;
}

.pp-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 8px;
  color: var(--pp-sub);
  font-size: 13px;
}

.pp-count {
  padding: 2px 10px;
  border: 1px solid var(--pp-line);
  border-radius: 999px;
  background: rgba(31, 41, 55, 0.35);
}

.pp-delta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
}

.pp-delta.up {
  color: #22c55e;
}

.pp-delta.down {
  color: #f97316;
}

.pp-delta.flat {
  color: var(--pp-sub);
}

.pp-arrow {
  width: 12px;
  height: 12px;
  fill: currentColor;
}

.pp-delta.down .pp-arrow {
  transform: rotate(180deg);
}

.pp-delta-num {
  font-weight: 700;
  font-size: 15px;
}

.pp-delta-label {
  color: var(--pp-sub);
}

.pp-badge {
  flex: none;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid rgba(59, 130, 246, 0.35);
  background: rgba(59, 130, 246, 0.12);
  color: #bfdbfe;
  font-size: 12px;
  cursor: help;
}

.pp-badge b {
  font-size: 14px;
  color: #dbeafe;
}

.pp-alert {
  margin-top: 14px;
}

.pp-grid {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(320px, 1.15fr);
  gap: 14px;
  margin-top: 16px;
}

.pp-card {
  background: var(--pp-card);
  border: 1px solid var(--pp-line);
  border-radius: 10px;
  padding: 14px 16px 16px;
  margin-top: 14px;
}

.pp-grid .pp-card {
  margin-top: 0;
}

.pp-card-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.pp-card-head h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--pp-text);
}

.pp-card-sub {
  font-size: 12px;
  color: var(--pp-sub);
}

.pp-chart {
  width: 100%;
}

.pp-chart-radar {
  height: 300px;
}

.pp-chart-trend {
  height: 300px;
}

.pp-placeholder {
  margin: 0;
  padding: 42px 8px;
  text-align: center;
  color: var(--pp-sub);
  font-size: 13px;
  border: 1px dashed var(--pp-line);
  border-radius: 8px;
}

.pp-unhit {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 2px 0 0;
  font-size: 12px;
  color: #fbbf24;
}

.pp-unhit-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #fbbf24;
}

/* ---------- 维度明细 ---------- */
.dim-row {
  display: grid;
  grid-template-columns: 136px 1fr 118px;
  align-items: center;
  gap: 14px;
  padding: 11px 0;
}

.dim-row + .dim-row {
  border-top: 1px solid rgba(31, 41, 55, 0.85);
}

.dim-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--pp-text);
  white-space: nowrap;
}

.dim-hit {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: #22c55e;
}

.dim-hit svg {
  width: 11px;
  height: 11px;
  fill: none;
  stroke: #22c55e;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.dim-bars {
  min-width: 0;
}

.dim-bar {
  position: relative;
  height: 10px;
  border-radius: 6px;
  background: #1b2433;
}

.dim-fill {
  height: 100%;
  border-radius: 6px;
  background: linear-gradient(90deg, #2563eb, #60a5fa);
  transition: width 600ms cubic-bezier(0.25, 0.1, 0.25, 1);
}

.dim-target {
  position: absolute;
  top: -3px;
  bottom: -3px;
  width: 2px;
  border-radius: 2px;
  background: var(--pp-target);
  box-shadow: 0 0 6px rgba(245, 158, 11, 0.55);
}

.dim-target.reached {
  background: #22c55e;
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.5);
}

.dim-bar-sub {
  height: 4px;
  margin-top: 7px;
  background: rgba(31, 41, 55, 0.55);
}

.dim-target-fill {
  height: 100%;
  border-radius: 4px;
  background: rgba(245, 158, 11, 0.55);
}

.dim-values {
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  gap: 10px;
  font-size: 12px;
}

.dim-latest {
  font-size: 14px;
  font-weight: 650;
  color: var(--pp-text);
}

.dim-gap {
  min-width: 52px;
  text-align: right;
}

.gap-warn {
  color: #fbbf24;
}

.gap-ok {
  color: #22c55e;
}

/* ---------- 徽章墙 ---------- */
.badge-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-top: 10px;
}

.badge-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid var(--pp-line);
  background: rgba(13, 17, 23, 0.65);
  opacity: 0.45;
  filter: grayscale(1);
  transition: transform 240ms ease, box-shadow 240ms ease, opacity 240ms ease;
}

.badge-card.earned {
  opacity: 1;
  filter: none;
  border-color: rgba(59, 130, 246, 0.55);
  box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.18), 0 0 18px rgba(59, 130, 246, 0.18);
}

.badge-card.earned:hover {
  transform: translateY(-2px);
  box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.35), 0 0 24px rgba(59, 130, 246, 0.28);
}

.badge-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(59, 130, 246, 0.14);
}

.badge-icon svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: #93c5fd;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.badge-card:not(.earned) .badge-icon svg {
  stroke: #6b7280;
}

.badge-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--pp-text);
}

.badge-desc {
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--pp-sub);
}

.badge-state {
  margin-top: auto;
  font-size: 11px;
  color: #6b7280;
}

.badge-card.earned .badge-state {
  color: #60a5fa;
}

/* ---------- 下一步动作 ---------- */
.next-card {
  margin-top: 14px;
  padding: 14px 16px 16px;
  border-radius: 10px;
  border: 1px solid var(--pp-line);
  border-left: 3px solid var(--pp-primary);
  background: linear-gradient(180deg, rgba(59, 130, 246, 0.1), rgba(59, 130, 246, 0.02));
}

.next-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.next-eyebrow {
  font-size: 12px;
  letter-spacing: 1px;
  color: #93c5fd;
  text-transform: uppercase;
}

.next-gap {
  font-size: 12px;
  padding: 2px 9px;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.14);
  color: #fbbf24;
}

.next-label {
  margin-top: 8px;
  font-size: 18px;
  font-weight: 650;
  color: var(--pp-text);
}

.next-action {
  margin: 8px 0 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: #d1d5db;
}

.next-drill {
  margin: 12px 0 0;
  padding: 10px 14px;
  border-left: 2px solid rgba(59, 130, 246, 0.6);
  border-radius: 0 8px 8px 0;
  background: rgba(13, 17, 23, 0.72);
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.7;
}

/* ---------- 空态 ---------- */
.pp-empty {
  margin-top: 18px;
  padding: 44px 20px;
  text-align: center;
  border: 1px dashed var(--pp-line);
  border-radius: 12px;
  background: rgba(17, 24, 39, 0.6);
}

.pp-empty-icon {
  width: 52px;
  height: 52px;
  fill: none;
  stroke: #4b5563;
  stroke-width: 2;
  stroke-linecap: round;
}

.pp-empty-title {
  margin: 14px 0 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--pp-text);
}

.pp-empty-desc {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--pp-sub);
}

@media (max-width: 900px) {
  .pp-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .badge-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dim-row {
    grid-template-columns: 82px 1fr 96px;
  }
}
</style>
