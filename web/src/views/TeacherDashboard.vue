<template>
  <div class="page">
    <el-card shadow="never" class="filter-bar">
      <el-form inline @submit.prevent>
        <el-form-item label="班级">
          <el-autocomplete
            v-model="className"
            :fetch-suggestions="suggestClass"
            placeholder="如 AI2201"
            style="width: 200px"
            @keyup.enter="loadAll"
          />
        </el-form-item>
        <el-form-item label="学期">
          <el-input v-model="term" placeholder="如 2025-2026-2" style="width: 160px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="loadAll">查询</el-button>
          <el-button @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
      <div class="engine-line">
        <span>引擎版本：{{ warnings.engine_version || overview.engine_version || '-' }}</span>
        <span>画像版本：{{ warnings.calc_version || overview.calc_version || '-' }}</span>
        <span>数据于 {{ clock.ago(lastLoadAt) }}</span>
        <span v-if="errorTip" class="err">{{ errorTip }}</span>
        <el-switch v-model="autoRefresh" size="small" active-text="自动刷新" class="auto-switch" />
        <router-link to="/teacher/students" class="to-files">看学生个人档案 →</router-link>
      </div>
    </el-card>

    <el-row :gutter="12" class="stat-row">
      <el-col :span="6">
        <el-card shadow="never" class="stat-card stat-red">
          <div class="stat-label">红色预警</div>
          <div class="stat-value"><count-number :value="dist.red" /></div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card stat-orange">
          <div class="stat-label">橙色预警</div>
          <div class="stat-value"><count-number :value="dist.orange" /></div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card stat-yellow">
          <div class="stat-label">黄色预警</div>
          <div class="stat-value"><count-number :value="dist.yellow" /></div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card stat-normal">
          <div class="stat-label">班级人数 / 均分</div>
          <div class="stat-value small">
            <count-number :value="overview.headcount" /> /
            <count-number :value="overview.avg_gpa" :decimals="1" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12">
      <el-col :span="10">
        <el-card shadow="never" v-loading="loading">
          <div class="card-title">预警等级分布</div>
          <div ref="barRef" class="chart-box"></div>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card shadow="never" v-loading="loading">
          <div class="card-title">班级概貌</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="班级">{{ overview.class_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="学期">{{ overview.term || '-' }}</el-descriptions-item>
            <el-descriptions-item label="挂科人数">{{ overview.fail_students ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="挂科率">{{ fmtRate(overview.fail_rate) }}</el-descriptions-item>
          </el-descriptions>
          <div class="card-title" style="margin-top: 12px">高风险 Top5</div>
          <el-empty v-if="!overview.top_risk_students?.length" description="暂无数据" />
          <ul v-else class="risk-list">
            <li v-for="s in overview.top_risk_students" :key="s.student_no">
              <el-tag :type="levelType(s.level)" size="small">{{ s.student_no }}</el-tag>
              <span class="risk-name">{{ s.name || '—' }}</span>
              <span class="risk-score">{{ s.risk_score }}</span>
            </li>
          </ul>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="table-card">
      <div class="card-title">预警名单（点击行看四维画像）</div>
      <el-table
        v-loading="loading"
        :data="warnings.items || []"
        border
        stripe
        height="420"
        @row-click="openProfile"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-box">
              <div><b>归因：</b>
                <span v-if="!row.reasons?.length">无触发项</span>
                <span v-for="(r, i) in row.reasons" :key="i" class="reason">{{ r }}</span>
              </div>
              <div><b>可用指标：</b>{{ row.coverage }} 项<span v-if="row.missing?.length">（缺失：{{ row.missing.join('、') }}）</span></div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="student_no" label="学号" width="130" />
        <el-table-column prop="name" label="姓名" width="100" />
        <el-table-column label="等级" width="110">
          <template #default="{ row }">
            <el-tag :type="levelType(row.level)" effect="dark">{{ levelText(row.level) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="risk_score" label="风险分" width="100" sortable />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openProfile(row)">画像</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !(warnings.items || []).length" description="该班级暂无预警数据" />
    </el-card>

    <el-drawer v-model="drawer" :title="`${profile.name || ''}（${profile.student_no || ''}）画像`" size="45%">
      <div v-loading="profileLoading">
        <el-empty v-if="!profile.student_no && !profileLoading" description="未加载到画像" />
        <template v-else>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="专业">{{ profile.major || '-' }}</el-descriptions-item>
            <el-descriptions-item label="班级">{{ profile.class_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="数据源">{{ profile.source || '-' }}</el-descriptions-item>
            <el-descriptions-item label="画像版本">{{ profile.calc_version || '-' }}</el-descriptions-item>
          </el-descriptions>
          <div class="tag-line">
            <el-tag v-for="t in profile.tags || []" :key="t" class="tag-item">{{ t }}</el-tag>
          </div>
          <div ref="radarRef" class="chart-box radar-box"></div>
          <div class="card-title">职业差距（目标方向：{{ gap.target_direction || '—' }}）</div>
          <el-empty v-if="!gapLoading && !(gap.gaps || []).length" description="暂无职业差距数据" />
          <template v-else>
            <div ref="gapRef" class="chart-box"></div>
            <div class="gap-note">口径：需求侧关键词出现率 − 班级具备率；≥30% 红档、≥10% 橙档</div>
          </template>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'

import http from '../api/http'
import CountNumber from '../components/CountNumber.vue'
import { useClock } from '../composables/useSystemStatus'

const LEVEL_TEXT = { red: '红色', orange: '橙色', yellow: '黄色', none: '正常', unknown: '数据不足' }
const LEVEL_TYPE = { red: 'danger', orange: 'warning', yellow: 'warning', none: 'success', unknown: 'info' }
const COLORS = ['#e5484d', '#f5a623', '#f0c808', '#4cb971', '#86909c']

const HISTORY_KEY = 'qh_class_history'
const className = ref(localStorage.getItem('qh_last_class') || 'AI2201')
const term = ref('2025-2026-2')
const loading = ref(false)
const errorTip = ref('')
const autoRefresh = ref(false)
const lastLoadAt = ref(null)
let timer = null
const clock = useClock()
const overview = ref({})
const warnings = ref({})
const barRef = ref(null)
const radarRef = ref(null)
let barChart = null
let radarChart = null

const dist = computed(() => warnings.value.distribution || {})

const drawer = ref(false)
const profileLoading = ref(false)
const profile = ref({})
const gapLoading = ref(false)
const gap = ref({})
const gapRef = ref(null)
let gapChart = null

function levelText(level) {
  return LEVEL_TEXT[level] || level || '-'
}

function levelType(level) {
  return LEVEL_TYPE[level] || 'info'
}

function fmtRate(v) {
  return v === null || v === undefined ? '-' : `${(Number(v) * 100).toFixed(1)}%`
}

function suggestClass(query, cb) {
  const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  const keyword = String(query || '').trim()
  const hits = history.filter((name) => !keyword || name.includes(keyword))
  cb(hits.map((name) => ({ value: name })))
}

function rememberClass(name) {
  const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  const next = [name, ...history.filter((item) => item !== name)].slice(0, 10)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
  localStorage.setItem('qh_last_class', name)
}

async function loadClass(reportError = true) {
  const klass = String(className.value || '').trim()
  if (!klass) {
    ElMessage.warning('请先填写班级名')
    return
  }
  rememberClass(klass)
  errorTip.value = ''
  try {
    const [ovRes, wnRes] = await Promise.all([
      http.get('/teacher/class-overview', { params: { class_name: klass, term: term.value } }),
      http.get('/teacher/warnings', { params: { class_name: klass, term: term.value } })
    ])
    overview.value = ovRes.data || {}
    warnings.value = wnRes.data || {}
    lastLoadAt.value = new Date()
    await nextTick()
    renderBar()
  } catch (err) {
    overview.value = {}
    warnings.value = {}
    if (reportError) {
      errorTip.value = err?.response?.data?.detail || '加载失败'
    }
    renderBar()
  }
}

async function loadAll() {
  loading.value = true
  try {
    await loadClass()
  } finally {
    loading.value = false
  }
}

function reset() {
  className.value = ''
  term.value = '2025-2026-2'
  overview.value = {}
  warnings.value = {}
  errorTip.value = ''
  renderBar()
}

watch(autoRefresh, (on) => {
  if (timer) clearInterval(timer)
  timer = on ? setInterval(loadClass, 30000) : null
})

function renderBar() {
  if (!barRef.value) return
  barChart = barChart || echarts.init(barRef.value)
  const labels = ['红色', '橙色', '黄色', '正常', '数据不足']
  const keys = ['red', 'orange', 'yellow', 'none', 'unknown']
  barChart.setOption(
    {
      grid: { left: 48, right: 16, top: 24, bottom: 32 },
      xAxis: { type: 'category', data: labels, axisLabel: { color: '#4e5969' } },
      yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#e5e6eb' } } },
      tooltip: { trigger: 'axis' },
      series: [
        {
          type: 'bar',
          barWidth: 36,
          label: { show: true, position: 'top' },
          data: keys.map((key, index) => ({
            value: dist.value[key] ?? 0,
            itemStyle: { color: COLORS[index], borderRadius: [4, 4, 0, 0] }
          }))
        }
      ]
    },
    true
  )
}

async function openProfile(row) {
  drawer.value = true
  profileLoading.value = true
  profile.value = { student_no: row?.student_no, name: row?.name }
  renderRadar({})
  loadGap()
  try {
    const { data } = await http.get(`/teacher/student/${encodeURIComponent(row.student_no)}`, {
      params: { term: term.value }
    })
    profile.value = data || {}
    await nextTick()
    renderRadar(profile.value)
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '画像加载失败')
  } finally {
    profileLoading.value = false
  }
}

function renderRadar(data) {
  if (!radarRef.value) return
  radarChart = radarChart || echarts.init(radarRef.value)
  const dims = data?.dimensions || {}
  const names = { study: '学业', behavior: '行为', interest: '兴趣', ability: '能力' }
  const keys = Object.keys(names)
  radarChart.setOption(
    {
      tooltip: { trigger: 'item' },
      radar: {
        indicator: keys.map((key) => ({ name: names[key], max: 1 })),
        radius: '66%',
        axisName: { color: '#4e5969' }
      },
      series: [
        {
          type: 'radar',
          areaStyle: { opacity: 0.25 },
          lineStyle: { color: '#e5484d' },
          itemStyle: { color: '#e5484d' },
          data: [
            {
              name: '四维画像',
              value: keys.map((key) => (dims[key] === null || dims[key] === undefined ? 0 : Number(dims[key])))
            }
          ]
        }
      ]
    },
    true
  )
}

async function loadGap() {
  const klass = String(className.value || '').trim()
  if (!klass) return
  gapLoading.value = true
  try {
    const { data } = await http.get('/teacher/career-gap', {
      params: { class_name: klass, term: term.value }
    })
    gap.value = data || {}
    await nextTick()
    renderGap(gap.value)
  } catch (err) {
    gap.value = {}
    ElMessage.error(err?.response?.data?.detail || '职业差距加载失败')
  } finally {
    gapLoading.value = false
  }
}

function renderGap(data) {
  if (!gapRef.value) return
  gapChart = gapChart || echarts.init(gapRef.value)
  const rows = (data?.gaps || []).slice().reverse() // ECharts Y 轴自下而上，反转后顺序与接口一致
  gapChart.setOption(
    {
      grid: { left: 80, right: 24, top: 28, bottom: 28 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { data: ['班级具备率', '岗位需求率'], textStyle: { color: '#4e5969' } },
      xAxis: { type: 'value', max: 1, splitLine: { lineStyle: { color: '#e5e6eb' } } },
      yAxis: {
        type: 'category',
        data: rows.map((row) => row.dimension),
        axisLabel: { color: '#4e5969' }
      },
      series: [
        {
          name: '班级具备率',
          type: 'bar',
          data: rows.map((row) => row.class_rate ?? 0),
          itemStyle: { color: '#4cb971', borderRadius: [0, 4, 4, 0] }
        },
        {
          name: '岗位需求率',
          type: 'bar',
          data: rows.map((row) => row.demand_rate ?? 0),
          itemStyle: {
            color: (params) => {
              const level = rows[params.dataIndex]?.level
              return level === 'red' ? '#e5484d' : level === 'orange' ? '#f5a623' : '#86909c'
            },
            borderRadius: [0, 4, 4, 0]
          }
        }
      ]
    },
    true
  )
}

function onResize() {
  barChart?.resize()
  radarChart?.resize()
  gapChart?.resize()
}

watch(
  () => drawer.value,
  async (opened) => {
    if (opened) {
      await nextTick()
      radarChart?.resize()
    }
  }
)

onMounted(() => {
  loadAll()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('resize', onResize)
  barChart?.dispose()
  radarChart?.dispose()
  gapChart?.dispose()
  barChart = null
  radarChart = null
  gapChart = null
})
</script>

<style scoped>
.filter-bar {
  margin-bottom: 12px;
}

.engine-line {
  font-size: 12px;
  color: #86909c;
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.auto-switch {
  margin-left: auto;
}

.to-files {
  color: var(--qh-red);
  text-decoration: none;
  font-size: 12px;
}

.err {
  color: var(--qh-red);
  margin-left: 12px;
}

.stat-row {
  margin-bottom: 12px;
}

.stat-card {
  border-left-width: 4px;
  border-left-style: solid;
}

.stat-red {
  border-left-color: var(--qh-red);
}

.stat-orange {
  border-left-color: var(--qh-orange);
}

.stat-yellow {
  border-left-color: var(--qh-yellow);
}

.stat-normal {
  border-left-color: #c9cdd4;
}

.stat-label {
  font-size: 13px;
  color: #86909c;
}

.stat-value {
  font-size: 30px;
  font-weight: 600;
  color: var(--qh-red);
  line-height: 1.4;
}

.stat-value.small {
  font-size: 22px;
  color: #1f2329;
}

.chart-box {
  height: 300px;
  width: 100%;
}

.radar-box {
  margin-top: 8px;
}

.table-card {
  margin-top: 12px;
}

.expand-box {
  padding: 4px 12px;
  font-size: 13px;
  color: #4e5969;
  line-height: 1.9;
}

.reason {
  margin-left: 8px;
  background: #f2f3f5;
  border-radius: 4px;
  padding: 2px 6px;
}

.risk-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.risk-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
}

.risk-name {
  color: #4e5969;
}

.risk-score {
  margin-left: auto;
  font-weight: 600;
  color: var(--qh-red);
}

.gap-note {
  font-size: 12px;
  color: #86909c;
  margin-top: 6px;
}

.tag-line {
  margin: 12px 0 4px;
}

.tag-item {
  margin-right: 6px;
}
</style>
