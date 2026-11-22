<template>
  <div class="page bento-page">
    <el-skeleton v-if="firstLoading" :rows="10" animated />
    <div v-else ref="pageRoot" class="bento-grid">
      <el-alert
        v-if="data.note"
        class="bento-span-4 qh-reveal"
        :style="{ '--qh-index': 0 }"
        type="info"
        :closable="false"
        show-icon
        :title="data.note"
      />
      <el-alert
        v-if="errorTip"
        class="bento-span-4 qh-reveal"
        :style="{ '--qh-index': 0 }"
        type="error"
        :closable="false"
        show-icon
        :title="errorTip"
      />

      <RouteHero
        class="bento-span-4 qh-reveal qh-hero"
        :style="{ '--qh-index': 0 }"
        tone="student"
        eyebrow="校园洞察 · 本校本租户"
        title="校园行为洞察"
        desc="数据来自图书馆到馆借阅、一卡通消费、课堂考勤、证书/竞赛/项目活动与岗位浏览收藏；全部数值由确定性引擎计算，本页只做展示。"
        :stats="heroStats"
      >
        <template #actions>
          <el-button type="primary" :loading="loading" @click="load">刷新</el-button>
        </template>
      </RouteHero>

      <section class="bento-card bento-span-4 ai-card qh-reveal" :style="{ '--qh-index': 1 }" v-loading="aiLoading">
        <div class="card-head">
          <h3 class="bento-title">AI 解读</h3>
          <div class="ai-head-right">
            <el-tag v-if="ai" class="ai-source-tag" size="small" :type="ai.source === 'llm' ? 'success' : 'info'" effect="plain">
              {{ ai.source === 'llm' ? `大模型 · ${ai.provider || 'llm'}` : '模板兜底（模型不可用或数值驳回）' }}
            </el-tag>
            <el-button size="small" :loading="aiLoading" @click="loadAi">重新解读</el-button>
          </div>
        </div>
        <div class="ai-body" aria-live="polite">
          <Transition name="ai-fade" mode="out-in">
            <p v-if="aiError" key="error" class="ai-error">{{ aiError }}</p>
            <p v-else-if="ai" :key="ai.text" class="ai-text">{{ ai.text }}</p>
            <p v-else key="placeholder" class="ai-text ai-placeholder" :class="{ 'qh-breathe': aiLoading }">大模型正在阅读你的校园行为事实…</p>
          </Transition>
        </div>
        <p class="rule-note">
          解读由大模型基于引擎事实生成，数值经 critic 逐条回查；驳回超限自动降级确定性模板，数值始终来自引擎。
        </p>
      </section>

      <section class="bento-card bento-span-2 qh-reveal" :style="{ '--qh-index': 2 }" v-loading="loading">
        <div class="card-head">
          <h3 class="bento-title">学习投入画像</h3>
          <el-tag size="small" :type="styleType(studyStyle.label)" effect="dark">
            {{ studyStyle.label || '暂无数据' }}
          </el-tag>
        </div>
        <div class="style-label">{{ studyStyle.label || '暂无数据' }}</div>
        <el-progress
          :percentage="scorePct"
          :stroke-width="14"
          :color="scoreColor"
          :format="() => (studyStyle.score === null || studyStyle.score === undefined ? '—' : `${scorePct}%`)"
        />
        <p class="rule-note">
          投入分 = 到馆 40% + 出勤 30% + 消费规律 30%，数值由确定性引擎计算，非大模型生成。
        </p>
      </section>

      <section class="bento-card bento-span-2 qh-reveal" :style="{ '--qh-index': 3 }" v-loading="loading">
        <div class="card-head">
          <h3 class="bento-title">个人事实卡</h3>
          <span class="bento-eyebrow">来自档案 extra</span>
        </div>
        <el-descriptions v-if="extra" :column="2" border size="small">
          <el-descriptions-item label="四级成绩">{{ extra.cet4 ?? '未考' }}</el-descriptions-item>
          <el-descriptions-item label="六级成绩">{{ extra.cet6 ?? '未考' }}</el-descriptions-item>
          <el-descriptions-item label="政治面貌">{{ extra.politics || '—' }}</el-descriptions-item>
          <el-descriptions-item label="意向城市">{{ extra.target_city || '—' }}</el-descriptions-item>
          <el-descriptions-item label="每周学时">
            {{ extra.weekly_hours === null || extra.weekly_hours === undefined ? '—' : `${extra.weekly_hours} 小时` }}
          </el-descriptions-item>
          <el-descriptions-item label="班级 / 学期">{{ data.class_name || '—' }} / {{ data.term || '—' }}</el-descriptions-item>
        </el-descriptions>
        <el-empty v-else description="暂无档案事实数据" :image-size="60" />
      </section>

      <section class="bento-card bento-span-2 qh-reveal" :style="{ '--qh-index': 4 }" v-loading="loading">
        <div class="card-head">
          <h3 class="bento-title">图书馆到馆 / 借阅</h3>
          <el-tag size="small" :type="trendType(library.trend)">
            趋势 {{ trendText(library.trend) }}
          </el-tag>
        </div>
        <div v-if="libraryTerms.length" ref="libRef" class="chart-box"></div>
        <el-empty v-else description="暂无到馆借阅记录" :image-size="60" />
        <div class="stat-line">
          <el-tag size="small" effect="plain">累计到馆 {{ num(library.total_visits) }} 次</el-tag>
          <el-tag size="small" effect="plain">累计借阅 {{ num(library.total_borrows) }} 本</el-tag>
        </div>
      </section>

      <section class="bento-card bento-span-2 qh-reveal" :style="{ '--qh-index': 5 }" v-loading="loading">
        <div class="card-head">
          <h3 class="bento-title">一卡通消费</h3>
          <span class="bento-eyebrow">日均金额 × 活跃天数</span>
        </div>
        <div v-if="consumptionTerms.length" ref="conRef" class="chart-box"></div>
        <el-empty v-else description="暂无消费记录" :image-size="60" />
        <div class="regularity-line">
          <span class="regularity-label">消费规律性</span>
          <el-progress
            class="regularity-bar"
            :percentage="regularityPct"
            :stroke-width="10"
            :format="() => (consumption.regularity === null || consumption.regularity === undefined ? '—' : `${regularityPct}%`)"
          />
        </div>
      </section>

      <section class="bento-card bento-span-2 qh-reveal" :style="{ '--qh-index': 6 }" v-loading="loading">
        <div class="card-head">
          <h3 class="bento-title">活动参与（按学期）</h3>
          <el-tag size="small" effect="plain">共 {{ num(activities.total) }} 项</el-tag>
        </div>
        <div v-if="activityTerms.length" ref="actBarRef" class="chart-box"></div>
        <el-empty v-else description="暂无活动记录" :image-size="60" />
      </section>

      <section class="bento-card bento-span-2 qh-reveal" :style="{ '--qh-index': 7 }" v-loading="loading">
        <div class="card-head">
          <h3 class="bento-title">活动构成与近期清单</h3>
          <span class="bento-eyebrow">证书 / 竞赛 / 项目</span>
        </div>
        <div v-if="activityTypeItems.length" ref="actPieRef" class="chart-box chart-box-sm"></div>
        <el-empty v-else description="暂无活动数据" :image-size="60" />
        <ul v-if="recentActivities.length" class="recent-list">
          <li v-for="(item, i) in recentActivities" :key="i" :style="{ '--qh-index': Math.min(i, 11) }">
            <span class="recent-name">{{ item.name || '—' }}</span>
            <el-tag size="small" :type="actTagType(item.type)" effect="plain">{{ actText(item.type) }}</el-tag>
            <span class="recent-meta">{{ item.level || '—' }} · {{ item.date || '—' }}</span>
          </li>
        </ul>
      </section>

      <section class="bento-card bento-span-2 qh-reveal" :style="{ '--qh-index': 8 }" v-loading="loading">
        <div class="card-head">
          <h3 class="bento-title">课堂出勤率</h3>
          <span class="bento-eyebrow">最新 {{ pct(attendance.latest_rate) }} · 平均 {{ pct(attendance.avg_rate) }}</span>
        </div>
        <div v-if="attendanceTerms.length" ref="attRef" class="chart-box"></div>
        <el-empty v-else description="暂无考勤记录" :image-size="60" />
      </section>

      <section class="bento-card bento-span-2 qh-reveal" :style="{ '--qh-index': 9 }" v-loading="loading">
        <div class="card-head">
          <h3 class="bento-title">岗位兴趣</h3>
          <span class="bento-eyebrow">
            浏览 {{ num(jobInterest.views_total) }} · 收藏 {{ num(jobInterest.favorites_total) }}
          </span>
        </div>
        <template v-if="topCities.length || topIndustries.length">
          <div v-if="topCities.length" ref="cityRef" class="chart-box chart-box-sm"></div>
          <div v-if="topIndustries.length" ref="indRef" class="chart-box chart-box-sm"></div>
        </template>
        <el-empty v-else description="暂无岗位浏览记录" :image-size="60" />
      </section>

      <section class="bento-card bento-span-4 qh-reveal" :style="{ '--qh-index': 10 }" v-loading="loading">
        <div class="card-head">
          <h3 class="bento-title">每周状态快照</h3>
          <span class="bento-eyebrow">引擎按周落盘的整体状态</span>
        </div>
        <el-timeline v-if="snapshots.length" class="snapshot-line">
          <el-timeline-item
            v-for="(snap, i) in snapshots"
            :key="i"
            :color="overallColor(snap.overall)"
            :timestamp="`${snap.year} 年第 ${snap.week} 周`"
          >
            <el-tag size="small" :type="overallType(snap.overall)" effect="plain">
              {{ overallText(snap.overall) }}
            </el-tag>
            <span class="snapshot-summary">{{ snap.summary || '—' }}</span>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无周快照" :image-size="60" />
        <div class="engine-line">
          引擎 {{ data.engine_version || '—' }} · 画像 {{ data.calc_version || '—' }} · 工具 {{ data.tools_version || '—' }}
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
// 学生端「校园行为洞察」：图书馆/消费/活动/考勤/岗位兴趣五域展示。
// 数值全部来自后端确定性引擎（铁律 1），前端只做展示与百分比格式化，不重算。
// 身份由 JWT 登录态注入（铁律 2），本页不传任何 student_id。

import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { PieChart } from 'echarts/charts'
// timeline-item 没有独立入口，vite.config 的按需 resolver 解析不到；
// 该配置不在本任务允许改动范围内，故这里显式引入（含样式）。
import { ElTimeline, ElTimelineItem } from 'element-plus/es/components/timeline/index.mjs'
import 'element-plus/es/components/timeline/style/css'
import 'element-plus/es/components/timeline-item/style/css'

import http from '../api/http'
import RouteHero from '../components/brand/RouteHero.vue'
import echarts from '../utils/echarts'
import { useReveal } from '../composables/useReveal'

// 入场编排：只给卡片加 opacity/transform 渐显；chart-box 高度固定，reveal 不影响 ECharts 初始化尺寸
const pageRoot = ref(null)
const { refresh } = useReveal(pageRoot)

function queueReveal() {
  nextTick(refresh)
}

// 饼图未在全局 utils/echarts.js 注册；该文件不在本任务允许改动范围内，
// 故在本页按需补注册（echarts.use 作用于同一 core 实例，只增加本 chunk 体积）。
echarts.use([PieChart])

const ACT_META = {
  cert: { label: '证书', color: '#1951c3', tag: 'primary' },
  contest: { label: '竞赛', color: '#f5a623', tag: 'warning' },
  project: { label: '项目', color: '#4cb971', tag: 'success' }
}

const loading = ref(false)
const firstLoading = ref(true)
const errorTip = ref('')
const data = ref({})
const ai = ref(null)
const aiLoading = ref(false)
const aiError = ref('')

const library = computed(() => data.value.library || {})
const consumption = computed(() => data.value.consumption || {})
const activities = computed(() => data.value.activities || {})
const attendance = computed(() => data.value.attendance || {})
const jobInterest = computed(() => data.value.job_interest || {})
const extra = computed(() => data.value.extra || null)
const snapshots = computed(() => data.value.snapshots || [])
const studyStyle = computed(() => data.value.study_style || {})

const libraryTerms = computed(() => library.value.terms || [])
const consumptionTerms = computed(() => consumption.value.terms || [])
const activityTerms = computed(() => activities.value.by_term || [])
const attendanceTerms = computed(() => attendance.value.terms || [])
const recentActivities = computed(() => activities.value.recent || [])
const topCities = computed(() => jobInterest.value.top_cities || [])
const topIndustries = computed(() => jobInterest.value.top_industries || [])
const activityTypeItems = computed(() =>
  Object.entries(activities.value.by_type || {})
    .filter(([, v]) => Number(v) > 0)
    .map(([k, v]) => ({ key: k, name: actText(k), value: Number(v) }))
)

const scorePct = computed(() => {
  const v = studyStyle.value.score
  return v === null || v === undefined ? 0 : Math.round(Number(v) * 100)
})
const regularityPct = computed(() => {
  const v = consumption.value.regularity
  return v === null || v === undefined ? 0 : Math.round(Number(v) * 100)
})
const scoreColor = computed(() => {
  const label = studyStyle.value.label
  if (label === '高投入型') return '#4cb971'
  if (label === '待激活') return '#f5a623'
  return '#1951c3'
})

const heroStats = computed(() => [
  { label: '学习投入分', value: num(studyStyle.value.score), tone: 'good' },
  { label: '到馆总次数', value: num(library.value.total_visits), suffix: '次' },
  { label: '最新出勤率', value: pct(attendance.value.latest_rate) },
  { label: '活动总数', value: num(activities.value.total), suffix: '项' }
])

function num(v) {
  return v === null || v === undefined ? '—' : v
}
function pct(v) {
  return v === null || v === undefined ? '—' : `${(Number(v) * 100).toFixed(1)}%`
}
function trendType(t) {
  if (t === 'up') return 'success'
  if (t === 'down') return 'danger'
  return 'info'
}
function trendText(t) {
  return { up: '上升', down: '下降', flat: '平稳' }[t] || '—'
}
function styleType(label) {
  return { 高投入型: 'success', 稳健型: 'primary', 待激活: 'warning' }[label] || 'info'
}
function actText(type) {
  return ACT_META[type]?.label || type || '—'
}
function actTagType(type) {
  return ACT_META[type]?.tag || 'info'
}
function overallColor(o) {
  return { green: '#4cb971', yellow: '#f0c808', red: '#e5484d' }[o] || '#9aa1ad'
}
function overallType(o) {
  return { green: 'success', yellow: 'warning', red: 'danger' }[o] || 'info'
}
function overallText(o) {
  return { green: '正常', yellow: '关注', red: '预警' }[o] || o || '—'
}

// ---------- 图表：init / resize / dispose 与 TeacherDashboard 同模式 ----------
const libRef = ref(null)
const conRef = ref(null)
const actBarRef = ref(null)
const actPieRef = ref(null)
const attRef = ref(null)
const cityRef = ref(null)
const indRef = ref(null)
const charts = {}

function chartOf(key, el) {
  if (!el) return null
  charts[key] = charts[key] || echarts.init(el)
  return charts[key]
}

const AXIS_LABEL = { color: '#4e5969' }
const SPLIT_LINE = { lineStyle: { color: '#e4e7ee' } }

function renderLibrary() {
  const chart = chartOf('lib', libRef.value)
  if (!chart) return
  const terms = libraryTerms.value
  chart.setOption({
    animationDuration: 800,
    animationEasing: 'cubicOut',
    grid: { left: 44, right: 44, top: 36, bottom: 28 },
    tooltip: { trigger: 'axis' },
    legend: { data: ['到馆次数', '借阅本数'], textStyle: AXIS_LABEL },
    xAxis: { type: 'category', data: terms.map((t) => t.term), axisLabel: AXIS_LABEL },
    yAxis: [
      { type: 'value', name: '到馆', minInterval: 1, splitLine: SPLIT_LINE },
      { type: 'value', name: '借阅', minInterval: 1, splitLine: { show: false } }
    ],
    series: [
      {
        name: '到馆次数', type: 'bar', barMaxWidth: 28,
        data: terms.map((t) => t.visits ?? 0),
        itemStyle: { color: '#1951c3', borderRadius: [4, 4, 0, 0] }
      },
      {
        name: '借阅本数', type: 'line', yAxisIndex: 1, smooth: true,
        data: terms.map((t) => t.borrows ?? 0),
        itemStyle: { color: '#f5a623' }, lineStyle: { color: '#f5a623' }
      }
    ]
  }, true)
}

function renderConsumption() {
  const chart = chartOf('con', conRef.value)
  if (!chart) return
  const terms = consumptionTerms.value
  chart.setOption({
    animationDuration: 800,
    animationEasing: 'cubicOut',
    grid: { left: 44, right: 44, top: 36, bottom: 28 },
    tooltip: { trigger: 'axis' },
    legend: { data: ['日均金额(元)', '活跃天数'], textStyle: AXIS_LABEL },
    xAxis: { type: 'category', data: terms.map((t) => t.term), axisLabel: AXIS_LABEL },
    yAxis: [
      { type: 'value', name: '元', splitLine: SPLIT_LINE },
      { type: 'value', name: '天', minInterval: 1, splitLine: { show: false } }
    ],
    series: [
      {
        name: '日均金额(元)', type: 'line', smooth: true,
        data: terms.map((t) => t.daily_avg ?? 0),
        itemStyle: { color: '#1951c3' }, lineStyle: { color: '#1951c3' },
        areaStyle: { opacity: 0.08 }
      },
      {
        name: '活跃天数', type: 'bar', yAxisIndex: 1, barMaxWidth: 28,
        data: terms.map((t) => t.active_days ?? 0),
        itemStyle: { color: '#4cb971', borderRadius: [4, 4, 0, 0] }
      }
    ]
  }, true)
}

function renderActivityBar() {
  const chart = chartOf('actBar', actBarRef.value)
  if (!chart) return
  const terms = activityTerms.value
  chart.setOption({
    animationDuration: 800,
    animationEasing: 'cubicOut',
    grid: { left: 40, right: 16, top: 36, bottom: 28 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['证书', '竞赛', '项目'], textStyle: AXIS_LABEL },
    xAxis: { type: 'category', data: terms.map((t) => t.term), axisLabel: AXIS_LABEL },
    yAxis: { type: 'value', minInterval: 1, splitLine: SPLIT_LINE },
    series: ['cert', 'contest', 'project'].map((key) => ({
      name: ACT_META[key].label,
      type: 'bar',
      stack: 'activity',
      barMaxWidth: 32,
      data: terms.map((t) => t[key] ?? 0),
      itemStyle: { color: ACT_META[key].color }
    }))
  }, true)
}

function renderActivityPie() {
  const chart = chartOf('actPie', actPieRef.value)
  if (!chart) return
  chart.setOption({
    animationDuration: 800,
    animationEasing: 'cubicOut',
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: AXIS_LABEL },
    series: [{
      type: 'pie',
      radius: ['42%', '66%'],
      center: ['50%', '44%'],
      label: { formatter: '{b}: {c}' },
      data: activityTypeItems.value.map((item) => ({
        name: item.name,
        value: item.value,
        itemStyle: { color: ACT_META[item.key]?.color || '#9aa1ad' }
      }))
    }]
  }, true)
}

function renderAttendance() {
  const chart = chartOf('att', attRef.value)
  if (!chart) return
  const terms = attendanceTerms.value
  chart.setOption({
    animationDuration: 800,
    animationEasing: 'cubicOut',
    grid: { left: 48, right: 16, top: 28, bottom: 28 },
    tooltip: { trigger: 'axis', valueFormatter: (v) => `${v}%` },
    xAxis: { type: 'category', data: terms.map((t) => t.term), axisLabel: AXIS_LABEL },
    yAxis: {
      type: 'value', min: 0, max: 100,
      axisLabel: { ...AXIS_LABEL, formatter: '{value}%' },
      splitLine: SPLIT_LINE
    },
    series: [{
      name: '出勤率', type: 'line', smooth: true,
      data: terms.map((t) => (t.rate === null || t.rate === undefined ? null : Number((Number(t.rate) * 100).toFixed(1)))),
      itemStyle: { color: '#4cb971' }, lineStyle: { color: '#4cb971' },
      areaStyle: { opacity: 0.1 }
    }]
  }, true)
}

function renderHBar(key, el, rows, nameKey, color) {
  const chart = chartOf(key, el)
  if (!chart) return
  const list = rows.slice().reverse() // ECharts Y 轴自下而上，反转后与接口顺序一致
  chart.setOption({
    animationDuration: 800,
    animationEasing: 'cubicOut',
    grid: { left: 72, right: 30, top: 12, bottom: 24 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', minInterval: 1, splitLine: SPLIT_LINE },
    yAxis: { type: 'category', data: list.map((r) => r[nameKey]), axisLabel: AXIS_LABEL },
    series: [{
      type: 'bar', barMaxWidth: 18,
      data: list.map((r) => r.cnt ?? 0),
      label: { show: true, position: 'right' },
      itemStyle: { color, borderRadius: [0, 4, 4, 0] }
    }]
  }, true)
}

function renderAll() {
  renderLibrary()
  renderConsumption()
  renderActivityBar()
  renderActivityPie()
  renderAttendance()
  renderHBar('city', cityRef.value, topCities.value, 'city', '#1951c3')
  renderHBar('ind', indRef.value, topIndustries.value, 'industry', '#0f9d8a')
}

function onResize() {
  Object.values(charts).forEach((chart) => chart?.resize())
}

async function load() {
  loading.value = true
  errorTip.value = ''
  try {
    // 引擎逐域聚合可能偏慢，单独放宽超时，避免被全局 30s 掐断
    const { data: res } = await http.get('/student/campus-insight', { timeout: 60000 })
    data.value = res || {}
  } catch (err) {
    data.value = {}
    errorTip.value = err?.response?.data?.detail || '校园洞察数据加载失败'
  } finally {
    loading.value = false
    firstLoading.value = false
  }
  await nextTick()
  renderAll()
  queueReveal()
  if (!errorTip.value) loadAi()
}

async function loadAi() {
  aiLoading.value = true
  aiError.value = ''
  try {
    // 大模型解读耗时可达分钟级，单独放宽超时
    const { data: res } = await http.post(
      '/student/campus-insight/interpret',
      { term: data.value.term || undefined },
      { timeout: 150000 }
    )
    ai.value = res || null
  } catch (err) {
    ai.value = null
    aiError.value = err?.response?.data?.detail || 'AI 解读暂不可用，可点击「重新解读」重试'
  } finally {
    aiLoading.value = false
  }
}

onMounted(async () => {
  await load()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  Object.values(charts).forEach((chart) => chart?.dispose())
  Object.keys(charts).forEach((key) => delete charts[key])
})
</script>

<style scoped>
.ai-head-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ai-text {
  white-space: pre-wrap;
  line-height: 1.9;
  margin: 4px 0 8px;
}

.ai-placeholder {
  /* 占位文案在移动端只有 0.35 透明度时几乎看不见，抬到正文次级灰度 */
  color: #5b667a;
}

.ai-error {
  color: var(--el-color-danger);
  margin: 4px 0 8px;
}

.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.chart-box {
  width: 100%;
  height: 280px;
}

.chart-box-sm {
  height: 220px;
}

.style-label {
  font-size: 34px;
  font-weight: 700;
  line-height: 1.2;
  margin-bottom: 14px;
  color: var(--bento-text, #16181d);
}

.rule-note {
  margin: 14px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--bento-mute, #6b7280);
}

.stat-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.regularity-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}

.regularity-label {
  flex: 0 0 auto;
  font-size: 12.5px;
  color: var(--bento-sub, #5f6672);
}

.regularity-bar {
  flex: 1 1 auto;
}

.recent-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
}

.recent-list li {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 7px 0;
  border-bottom: 1px dashed #eef0f5;
  font-size: 13px;
}

.recent-name {
  flex: 1 1 160px;
  min-width: 0;
  color: var(--bento-text, #16181d);
}

.recent-meta {
  font-size: 12px;
  color: var(--bento-mute, #6b7280);
}

.snapshot-line {
  margin-top: 6px;
  padding-left: 4px;
}

.snapshot-summary {
  margin-left: 8px;
  font-size: 13px;
  color: var(--bento-sub, #5f6672);
}

.engine-line {
  margin-top: 10px;
  font-size: 12px;
  color: var(--bento-mute, #6b7280);
}

/* ---------- 入场动效（仅 transform/opacity/filter，不改布局尺寸） ---------- */
/* AI 解读正文：到达时 fade + translateY 渐显（Vue Transition） */
.ai-fade-enter-active,
.ai-fade-leave-active {
  transition: opacity 320ms ease, transform 320ms ease;
}

.ai-fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.ai-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

/* 「大模型 · spark」标签入场微光：一次性，不循环 */
.ai-source-tag {
  animation: tag-glow 1100ms ease-out backwards;
}

@keyframes tag-glow {
  0% { opacity: 0; transform: translateY(-4px); filter: brightness(1.5); }
  45% { opacity: 1; filter: brightness(1.35); }
  100% { opacity: 1; transform: none; filter: brightness(1); }
}






/* 近期活动清单：逐行浮入，delay 由 --qh-index 封顶前 12 行 */
.recent-list li {
  animation: row-in 420ms var(--bento-ease, ease) backwards;
  animation-delay: calc(var(--qh-index, 0) * 55ms);
}

@keyframes row-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}

@media (prefers-reduced-motion: reduce) {
  .ai-fade-enter-active,
  .ai-fade-leave-active {
    transition: none;
  }

  .ai-source-tag,
  .recent-list li {
    animation: none;
  }
}
</style>