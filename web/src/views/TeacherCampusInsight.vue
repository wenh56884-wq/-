<template>
  <div ref="pageRoot" class="page bento-page">
    <el-card shadow="never" class="filter-bar qh-reveal" :style="{ '--qh-index': 0 }">
      <el-form inline @submit.prevent>
        <el-form-item label="班级">
          <el-select
            v-model="className"
            filterable
            placeholder="请选择班级"
            style="width: 200px"
            @change="onClassChange"
          >
            <el-option v-for="k in classes" :key="k.class_name" :label="k.class_name" :value="k.class_name">
              <span>{{ k.class_name }}</span>
              <span class="option-note">{{ k.headcount }} 人</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="学期">
          <el-input v-model="term" placeholder="留空 = 全部学期" clearable style="width: 160px" />
        </el-form-item>
        <el-form-item label="样本人数">
          <el-input-number v-model="limit" :min="1" :max="60" :step="1" style="width: 130px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="loadReport">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <RouteHero
      class="qh-reveal qh-hero"
      :style="{ '--qh-index': 1 }"
      tone="teacher"
      eyebrow="校园洞察 · 本校本租户"
      :title="`${report.class_name || className || '班级'} · 校园行为洞察`"
      desc="图书馆、一卡通、考勤、活动与岗位浏览五域行为数据按班聚合；投入分与低投入名单由确定性引擎计算，本页只做展示。"
      :stats="heroStats"
      style="margin-top: 16px"
    />

    <el-alert
      v-if="report.note"
      class="note"
      type="info"
      :closable="false"
      show-icon
      :title="report.note"
    />

    <el-card shadow="never" class="ai-card qh-reveal" :style="{ '--qh-index': 2 }" v-loading="aiLoading">
      <div class="card-title">
        AI 班级解读
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
          <p v-else key="placeholder" class="ai-text ai-placeholder" :class="{ 'qh-breathe': aiLoading }">大模型正在阅读班级行为事实…</p>
        </Transition>
      </div>
      <p class="ai-note">
        解读由大模型基于引擎事实生成，数值经 critic 逐条回查；驳回超限自动降级确定性模板，数值始终来自引擎。
      </p>
    </el-card>

    <div class="chart-row">
      <el-card shadow="never" class="chart-card qh-reveal" :style="{ '--qh-index': 3 }" v-loading="loading">
        <div class="card-title">学习投入类型分布</div>
        <div v-if="styleDistItems.length" ref="stylePieRef" class="chart-box"></div>
        <el-empty v-else description="暂无投入画像数据" :image-size="60" />
      </el-card>
      <el-card shadow="never" class="chart-card qh-reveal" :style="{ '--qh-index': 4 }" v-loading="loading">
        <div class="card-title">岗位浏览热门城市</div>
        <div v-if="topCities.length" ref="cityRef" class="chart-box"></div>
        <el-empty v-else description="暂无岗位浏览数据" :image-size="60" />
      </el-card>
      <el-card shadow="never" class="chart-card qh-reveal" :style="{ '--qh-index': 5 }" v-loading="loading">
        <div class="card-title">班级活动构成</div>
        <div v-if="activityCountItems.length" ref="actRef" class="chart-box"></div>
        <el-empty v-else description="暂无活动数据" :image-size="60" />
      </el-card>
    </div>

    <el-card shadow="never" class="low-card qh-reveal" :style="{ '--qh-index': 6 }" v-loading="loading">
      <div class="card-title">
        低投入警示名单
        <el-tag v-if="lowEngagement.length" size="small" type="danger" effect="plain">
          {{ lowEngagement.length }} 人
        </el-tag>
      </div>
      <el-table v-if="lowEngagement.length" :data="lowEngagement" size="small" border max-height="260">
        <el-table-column prop="student_no" label="学号" width="140" />
        <el-table-column prop="name" label="姓名" width="110" />
        <el-table-column label="触发原因" min-width="300">
          <template #default="{ row }">
            <el-tag
              v-for="(r, i) in row.reasons || []"
              :key="i"
              type="danger"
              effect="plain"
              size="small"
              class="reason-tag"
            >{{ r }}</el-tag>
            <span v-if="!(row.reasons || []).length" class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="全员投入达标" :image-size="60" />
    </el-card>

    <div class="campus-body">
      <el-card shadow="never" class="list-card qh-reveal" :style="{ '--qh-index': 7 }">
        <div class="card-title">
          学生行为明细（{{ rows.length }} 人 / 班级 {{ report.student_total ?? summary.student_total ?? '—' }} 人）
        </div>
        <el-skeleton :rows="6" animated v-if="firstLoading" />
        <template v-else>
          <el-table
            v-loading="loading"
            :data="rows"
            border
            stripe
            highlight-current-row
            height="560"
            @current-change="selectStudent"
          >
            <el-table-column prop="student_no" label="学号" width="120" />
            <el-table-column prop="name" label="姓名" width="90" />
            <el-table-column label="投入类型" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="styleType(row.study_style?.label)" effect="plain">
                  {{ row.study_style?.label || '暂无数据' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="投入分" prop="study_style.score" width="86" sortable>
              <template #default="{ row }">{{ num(row.study_style?.score) }}</template>
            </el-table-column>
            <el-table-column label="最新出勤率" width="106">
              <template #default="{ row }">{{ pct(row.attendance?.latest_rate) }}</template>
            </el-table-column>
            <el-table-column label="最新到馆" width="92">
              <template #default="{ row }">{{ num(row.library?.latest?.visits) }}</template>
            </el-table-column>
            <el-table-column label="消费规律性" width="106">
              <template #default="{ row }">{{ pct(row.consumption?.regularity) }}</template>
            </el-table-column>
            <el-table-column label="活动总数" width="92">
              <template #default="{ row }">{{ num(row.activities?.total) }}</template>
            </el-table-column>
            <el-table-column label="岗位浏览" width="92">
              <template #default="{ row }">{{ num(row.job_interest?.views_total) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!loading && !rows.length" description="暂无学生行为数据" :image-size="60" />
        </template>
      </el-card>

      <el-card shadow="never" class="detail-card qh-reveal" :style="{ '--qh-index': 8 }">
        <el-empty v-if="!active" description="先在左侧点一名学生，查看其行为明细（数据已随班级报告返回，不再发请求）" />
        <template v-else>
          <div class="detail-head">
            <div>
              <span class="detail-name">{{ active.name || '—' }}</span>
              <span class="detail-no">{{ active.student_no }}</span>
              <el-tag size="small" :type="styleType(active.study_style?.label)" effect="dark">
                {{ active.study_style?.label || '暂无数据' }}
              </el-tag>
            </div>
            <div class="detail-source">
              投入分 {{ num(active.study_style?.score) }} · 引擎 {{ report.engine_version || '—' }}
            </div>
          </div>

          <el-collapse v-model="activePanels" class="domain-collapse">
            <el-collapse-item title="图书馆（按学期到馆 / 借阅）" name="library">
              <div class="tag-line">
                <el-tag size="small" effect="plain">累计到馆 {{ num(active.library?.total_visits) }} 次</el-tag>
                <el-tag size="small" effect="plain">累计借阅 {{ num(active.library?.total_borrows) }} 本</el-tag>
                <el-tag size="small" :type="trendType(active.library?.trend)">
                  趋势 {{ trendText(active.library?.trend) }}
                </el-tag>
              </div>
              <el-table :data="active.library?.terms || []" size="small" border class="sub-table">
                <el-table-column prop="term" label="学期" width="140" />
                <el-table-column prop="visits" label="到馆次数" width="100" />
                <el-table-column prop="borrows" label="借阅本数" width="100" />
              </el-table>
              <el-empty v-if="!(active.library?.terms || []).length" description="暂无到馆借阅记录" :image-size="48" />
            </el-collapse-item>

            <el-collapse-item title="课堂考勤（按学期出勤率）" name="attendance">
              <div class="tag-line">
                <el-tag size="small" effect="plain">最新出勤率 {{ pct(active.attendance?.latest_rate) }}</el-tag>
                <el-tag size="small" effect="plain">平均出勤率 {{ pct(active.attendance?.avg_rate) }}</el-tag>
              </div>
              <el-table :data="active.attendance?.terms || []" size="small" border class="sub-table">
                <el-table-column prop="term" label="学期" width="140" />
                <el-table-column prop="expected" label="应到" width="80" />
                <el-table-column prop="absent" label="缺勤" width="80" />
                <el-table-column label="出勤率" width="100">
                  <template #default="{ row }">{{ pct(row.rate) }}</template>
                </el-table-column>
              </el-table>
              <el-empty v-if="!(active.attendance?.terms || []).length" description="暂无考勤记录" :image-size="48" />
            </el-collapse-item>

            <el-collapse-item title="岗位兴趣（浏览 / 收藏 / 热门城市）" name="job">
              <div class="tag-line">
                <el-tag size="small" effect="plain">浏览 {{ num(active.job_interest?.views_total) }}</el-tag>
                <el-tag size="small" effect="plain">收藏 {{ num(active.job_interest?.favorites_total) }}</el-tag>
              </div>
              <div class="card-title sub-title">热门城市</div>
              <div class="tag-line">
                <el-tag
                  v-for="c in active.job_interest?.top_cities || []"
                  :key="c.city"
                  size="small"
                  effect="plain"
                >{{ c.city }} {{ c.cnt }}</el-tag>
                <span v-if="!(active.job_interest?.top_cities || []).length" class="muted">暂无数据</span>
              </div>
              <div class="card-title sub-title">热门行业</div>
              <div class="tag-line">
                <el-tag
                  v-for="it in active.job_interest?.top_industries || []"
                  :key="it.industry"
                  size="small"
                  effect="plain"
                >{{ it.industry }} {{ it.cnt }}</el-tag>
                <span v-if="!(active.job_interest?.top_industries || []).length" class="muted">暂无数据</span>
              </div>
            </el-collapse-item>

            <el-collapse-item :title="`活动参与（共 ${active.activities?.total ?? 0} 项）`" name="activities">
              <el-table :data="active.activities?.recent || []" size="small" border class="sub-table">
                <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
                <el-table-column label="类型" width="80">
                  <template #default="{ row }">
                    <el-tag size="small" :type="actTagType(row.type)" effect="plain">{{ actText(row.type) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="level" label="级别" width="100" />
                <el-table-column prop="date" label="日期" width="110" />
              </el-table>
              <el-empty v-if="!(active.activities?.recent || []).length" description="暂无活动记录" :image-size="48" />
            </el-collapse-item>

            <el-collapse-item title="个人事实（四六级 / 政治面貌 / 意向）" name="extra">
              <el-descriptions v-if="active.extra" :column="2" border size="small">
                <el-descriptions-item label="四级成绩">{{ active.extra.cet4 ?? '未考' }}</el-descriptions-item>
                <el-descriptions-item label="六级成绩">{{ active.extra.cet6 ?? '未考' }}</el-descriptions-item>
                <el-descriptions-item label="政治面貌">{{ active.extra.politics || '—' }}</el-descriptions-item>
                <el-descriptions-item label="意向城市">{{ active.extra.target_city || '—' }}</el-descriptions-item>
                <el-descriptions-item label="每周学时">
                  {{ active.extra.weekly_hours === null || active.extra.weekly_hours === undefined ? '—' : `${active.extra.weekly_hours} 小时` }}
                </el-descriptions-item>
                <el-descriptions-item label="消费规律性">{{ pct(active.consumption?.regularity) }}</el-descriptions-item>
              </el-descriptions>
              <el-empty v-else description="暂无档案事实数据" :image-size="48" />
            </el-collapse-item>

            <el-collapse-item :title="`每周状态快照（${(active.snapshots || []).length} 条）`" name="snapshots">
              <el-timeline v-if="(active.snapshots || []).length" class="snapshot-line">
                <el-timeline-item
                  v-for="(snap, i) in active.snapshots"
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
              <el-empty v-else description="暂无周快照" :image-size="48" />
            </el-collapse-item>
          </el-collapse>
        </template>
      </el-card>
    </div>

    <div class="engine-line">
      引擎 {{ report.engine_version || '—' }} · 画像 {{ report.calc_version || '—' }} · 工具 {{ report.tools_version || '—' }}
      · 租户 {{ report.tenant_id ?? '—' }} · 学期 {{ report.term || '全部' }}
    </div>
  </div>
</template>

<script setup>
// 教师端「校园行为洞察」：班级五域行为聚合 + 逐生明细。
// 数值全部来自后端确定性引擎（铁律 1/3），前端只做展示；租户隔离在数据层完成。
// 学生详情直接取自班级报告 students 数组，选中行不再发请求。

import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
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
const STYLE_COLORS = { 高投入型: '#4cb971', 稳健型: '#1951c3', 待激活: '#f5a623', 暂无数据: '#9aa1ad' }

const className = ref(localStorage.getItem('qh_last_class') || '')
const term = ref('')
const limit = ref(30)
const classes = ref([])
const report = ref({})
const loading = ref(false)
const firstLoading = ref(false)
const activeNo = ref('')
const activePanels = ref(['library', 'attendance'])
const ai = ref(null)
const aiLoading = ref(false)
const aiError = ref('')

const rows = computed(() => report.value.students || [])
const summary = computed(() => report.value.class_summary || {})
const lowEngagement = computed(() => summary.value.low_engagement || [])
const topCities = computed(() => summary.value.top_cities || [])
const active = computed(() =>
  rows.value.find((row) => row.student_no === activeNo.value) || null)

const styleDistItems = computed(() =>
  Object.entries(summary.value.study_style_distribution || {})
    .filter(([, v]) => Number(v) > 0)
    .map(([k, v]) => ({ name: k, value: Number(v) }))
)
const activityCountItems = computed(() =>
  Object.entries(summary.value.activity_counts || {})
    .map(([k, v]) => ({ key: k, name: actText(k), value: Number(v || 0) }))
)

const heroStats = computed(() => {
  const s = summary.value
  return [
    { label: '样本人数', value: report.value.student_total ?? s.student_total ?? '—', suffix: '人', tone: 'unknown' },
    { label: '平均出勤率', value: pct(s.avg_attendance_rate) },
    { label: '活动覆盖率', value: pct(s.activity_coverage_rate), tone: 'good' },
    { label: '平均到馆', value: num(s.avg_library_visits), suffix: '次' }
  ]
})

function num(v) {
  return v === null || v === undefined ? '—' : v
}
function pct(v) {
  return v === null || v === undefined ? '—' : `${(Number(v) * 100).toFixed(1)}%`
}
function styleType(label) {
  return { 高投入型: 'success', 稳健型: 'primary', 待激活: 'warning' }[label] || 'info'
}
function trendType(t) {
  if (t === 'up') return 'success'
  if (t === 'down') return 'danger'
  return 'info'
}
function trendText(t) {
  return { up: '上升', down: '下降', flat: '平稳' }[t] || '—'
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
const stylePieRef = ref(null)
const cityRef = ref(null)
const actRef = ref(null)
const charts = {}

function chartOf(key, el) {
  if (!el) return null
  charts[key] = charts[key] || echarts.init(el)
  return charts[key]
}

const AXIS_LABEL = { color: '#4e5969' }
const SPLIT_LINE = { lineStyle: { color: '#e4e7ee' } }

function renderStylePie() {
  const chart = chartOf('style', stylePieRef.value)
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
      data: styleDistItems.value.map((item) => ({
        ...item,
        itemStyle: { color: STYLE_COLORS[item.name] || '#9aa1ad' }
      }))
    }]
  }, true)
}

function renderCityBar() {
  const chart = chartOf('city', cityRef.value)
  if (!chart) return
  const list = topCities.value.slice().reverse() // Y 轴自下而上，反转后与接口顺序一致
  chart.setOption({
    animationDuration: 800,
    animationEasing: 'cubicOut',
    grid: { left: 72, right: 36, top: 16, bottom: 26 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', minInterval: 1, splitLine: SPLIT_LINE },
    yAxis: { type: 'category', data: list.map((r) => r.city), axisLabel: AXIS_LABEL },
    series: [{
      type: 'bar', barMaxWidth: 18,
      data: list.map((r) => r.cnt ?? 0),
      label: { show: true, position: 'right' },
      itemStyle: { color: '#1951c3', borderRadius: [0, 4, 4, 0] }
    }]
  }, true)
}

function renderActivityBar() {
  const chart = chartOf('act', actRef.value)
  if (!chart) return
  chart.setOption({
    animationDuration: 800,
    animationEasing: 'cubicOut',
    grid: { left: 44, right: 16, top: 28, bottom: 28 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: {
      type: 'category',
      data: activityCountItems.value.map((item) => item.name),
      axisLabel: AXIS_LABEL
    },
    yAxis: { type: 'value', minInterval: 1, splitLine: SPLIT_LINE },
    series: [{
      type: 'bar', barMaxWidth: 40,
      label: { show: true, position: 'top' },
      data: activityCountItems.value.map((item) => ({
        value: item.value,
        itemStyle: { color: ACT_META[item.key]?.color || '#9aa1ad', borderRadius: [4, 4, 0, 0] }
      }))
    }]
  }, true)
}

function renderAll() {
  renderStylePie()
  renderCityBar()
  renderActivityBar()
}

function onResize() {
  Object.values(charts).forEach((chart) => chart?.resize())
}

async function loadDirectory() {
  try {
    const { data } = await http.get('/teacher/classes')
    classes.value = data?.classes || []
    if (!className.value) {
      className.value = classes.value[0]?.class_name || ''
    }
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '班级目录加载失败')
  }
}

async function loadReport() {
  const klass = String(className.value || '').trim()
  if (!klass) {
    ElMessage.warning('请先选择班级')
    return
  }
  localStorage.setItem('qh_last_class', klass)
  loading.value = true
  ai.value = null
  aiError.value = ''
  try {
    const { data } = await http.get('/teacher/campus-insight', {
      params: {
        class_name: klass,
        term: term.value || undefined,
        limit: limit.value
      },
      // 逐生五域编排耗时较长，单独放宽超时，避免被全局 30s 掐断
      timeout: 150000
    })
    report.value = data || {}
    if (activeNo.value && !rows.value.some((row) => row.student_no === activeNo.value)) {
      activeNo.value = ''
    }
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '校园洞察加载失败')
    report.value = {}
    activeNo.value = ''
  } finally {
    loading.value = false
    firstLoading.value = false
  }
  await nextTick()
  renderAll()
  queueReveal()
  if (rows.value.length) loadAi()
}

async function loadAi() {
  const klass = String(className.value || '').trim()
  if (!klass) return
  aiLoading.value = true
  aiError.value = ''
  try {
    // 大模型解读耗时可达分钟级，单独放宽超时
    const { data } = await http.post(
      '/teacher/campus-insight/interpret',
      { class_name: klass, term: term.value || undefined, limit: limit.value },
      { timeout: 150000 }
    )
    ai.value = data || null
  } catch (err) {
    ai.value = null
    aiError.value = err?.response?.data?.detail || 'AI 解读暂不可用，可点击「重新解读」重试'
  } finally {
    aiLoading.value = false
  }
}

function onClassChange() {
  loadReport()
}

function selectStudent(row) {
  const no = row?.student_no
  if (!no || no === activeNo.value) return
  activeNo.value = no
}

onMounted(async () => {
  queueReveal()
  firstLoading.value = true
  await loadDirectory()
  await loadReport()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  Object.values(charts).forEach((chart) => chart?.dispose())
  Object.keys(charts).forEach((key) => delete charts[key])
})
</script>

<style scoped>
.ai-card {
  margin-top: 16px;
}

.ai-head-right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: 12px;
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

.ai-note {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin: 0;
}

.filter-bar {
  margin-bottom: 0;
  padding: 16px 18px;
}

.filter-bar :deep(.el-form-item) {
  margin-bottom: 10px;
}

.option-note {
  float: right;
  margin-left: 12px;
  font-size: 12px;
  color: #6b7280;
}

.note {
  margin-top: 12px;
}

.chart-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.chart-card :deep(.el-card__body) {
  padding: 14px 16px;
}

.chart-box {
  width: 100%;
  height: 260px;
}

.low-card {
  margin-top: 16px;
}

.reason-tag {
  margin: 2px 6px 2px 0;
}

.campus-body {
  display: grid;
  grid-template-columns: minmax(420px, 9fr) minmax(380px, 7fr);
  gap: 16px;
  margin-top: 16px;
}

.card-title {
  font-weight: 600;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.sub-title {
  margin-top: 10px;
  font-size: 13px;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.detail-name {
  font-size: 18px;
  font-weight: 600;
  margin-right: 8px;
}

.detail-no {
  color: #5f6672;
  margin-right: 10px;
}

.detail-source {
  font-size: 12px;
  color: #5f6672;
}

.tag-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 6px 0;
}

.sub-table {
  margin-top: 8px;
}

.muted {
  font-size: 13px;
  color: #5f6672;
}

.snapshot-line {
  margin-top: 6px;
  padding-left: 4px;
}

.snapshot-summary {
  margin-left: 8px;
  font-size: 13px;
  color: #5f6672;
}

.engine-line {
  margin-top: 14px;
  font-size: 12px;
  color: #5f6672;
}

@media (max-width: 1100px) {
  .chart-row,
  .campus-body {
    grid-template-columns: 1fr;
  }
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






/* 低投入名单：前 12 行逐行浮入，其余行直接可见；学生明细表交互保持原样 */
.low-card :deep(.el-table__body tr:nth-child(-n+12)) {
  animation: row-in 360ms var(--bento-ease, ease) backwards;
}

.low-card :deep(.el-table__body tr:nth-child(2)) { animation-delay: 45ms; }
.low-card :deep(.el-table__body tr:nth-child(3)) { animation-delay: 90ms; }
.low-card :deep(.el-table__body tr:nth-child(4)) { animation-delay: 135ms; }
.low-card :deep(.el-table__body tr:nth-child(5)) { animation-delay: 180ms; }
.low-card :deep(.el-table__body tr:nth-child(6)) { animation-delay: 225ms; }
.low-card :deep(.el-table__body tr:nth-child(7)) { animation-delay: 270ms; }
.low-card :deep(.el-table__body tr:nth-child(8)) { animation-delay: 315ms; }
.low-card :deep(.el-table__body tr:nth-child(9)) { animation-delay: 360ms; }
.low-card :deep(.el-table__body tr:nth-child(10)) { animation-delay: 405ms; }
.low-card :deep(.el-table__body tr:nth-child(11)) { animation-delay: 450ms; }
.low-card :deep(.el-table__body tr:nth-child(12)) { animation-delay: 495ms; }

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
  .low-card :deep(.el-table__body tr:nth-child(-n+12)) {
    animation: none;
  }
}
</style>