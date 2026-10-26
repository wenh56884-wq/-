<template>
  <div class="page">
    <el-card shadow="never" class="filter-bar">
      <el-form inline @submit.prevent>
        <el-form-item label="学院">
          <el-select
            v-model="college"
            clearable
            filterable
            placeholder="全部学院"
            style="width: 180px"
            @change="onCollegeChange"
          >
            <el-option v-for="c in colleges" :key="c.college" :label="c.college" :value="c.college">
              <span>{{ c.college }}</span>
              <span class="option-note">{{ c.class_cnt }} 班 / {{ c.student_cnt }} 人</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="专业">
          <el-select
            v-model="major"
            clearable
            filterable
            :placeholder="college ? '全部专业' : '请先选学院'"
            :disabled="!college"
            style="width: 180px"
            @change="onMajorChange"
          >
            <el-option v-for="m in majorOptions" :key="m.college + '/' + m.major" :label="m.major" :value="m.major">
              <span>{{ m.major }}</span>
              <span class="option-note">{{ m.class_cnt }} 班 / {{ m.student_cnt }} 人</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="班级">
          <el-select
            v-model="className"
            filterable
            :placeholder="classes.length ? '请选择班级' : '加载中…'"
            style="width: 180px"
            @change="onClassChange"
          >
            <el-option v-for="k in filteredClasses" :key="k.class_name" :label="k.class_name" :value="k.class_name">
              <span>{{ k.class_name }}</span>
              <span class="option-note">{{ k.headcount }} 人 · {{ majorLabel(k) }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="学号直达">
          <el-input v-model="studentNo" placeholder="如 AI2022001" style="width: 160px"
            @keyup.enter="searchStudent" />
          <el-button type="primary" plain :loading="studentSearchLoading" @click="searchStudent">
            查个人
          </el-button>
        </el-form-item>
        <el-form-item label="学期">
          <el-input v-model="term" placeholder="如 2025-2026-2" style="width: 150px" />
        </el-form-item>
        <el-form-item label="等级">
          <el-select v-model="level" placeholder="全部" clearable style="width: 130px">
            <el-option v-for="lv in LEVELS" :key="lv.value" :label="lv.label" :value="lv.value" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="listLoading" @click="loadClass">查询</el-button>
          <el-button @click="clearFilter">重置</el-button>
        </el-form-item>
        <el-form-item label="自动刷新">
          <el-switch v-model="autoRefresh" />
        </el-form-item>
        <el-form-item>
          <span class="refresh-tip">{{ clock.ago(lastLoadAt) }}</span>
          <el-button size="small" text :loading="listLoading" @click="loadClass">刷新</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div v-if="overview.career_intent?.total" class="intent-bar">
      <span class="intent-bar-label">职业目标</span>
      <span
        v-for="item in intentItems"
        :key="item.key"
        class="intent-chip"
        :style="{ '--intent-color': item.color }"
      >
        {{ item.label }} <b>{{ item.value }}</b>
      </span>
      <span class="intent-bar-total">
        已填写 {{ overview.career_intent.filled }} / {{ overview.career_intent.total }} 人
      </span>
    </div>

    <el-row :gutter="12">
      <el-col :span="9">
        <el-card shadow="never">
          <div class="card-title">学生名单（{{ rows.length }} 人 / 全班 {{ classmates }} 人）</div>
          <el-skeleton :rows="6" animated v-if="firstLoading" />
          <template v-else>
            <el-table
              v-loading="listLoading"
              :data="rows"
              border
              stripe
              highlight-current-row
              height="560"
              @current-change="selectStudent"
            >
              <el-table-column label="等级" width="96">
                <template #default="{ row }">
                  <el-tag :type="levelType(row.level)" effect="dark" size="small">
                    {{ levelText(row.level) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="student_no" label="学号" width="120" />
              <el-table-column prop="name" label="姓名" width="90" />
              <el-table-column prop="risk_score" label="风险分" width="90" sortable />
            </el-table>
            <el-empty v-if="!listLoading && !rows.length" description="该筛选条件下没有学生" />
          </template>
        </el-card>
      </el-col>

      <el-col :span="15">
        <el-card shadow="never">
          <el-empty v-if="!activeNo" description="先在左侧点一名学生，或在顶部输入学号直接查询" />
          <el-skeleton :rows="10" animated v-else-if="detailLoading" />
          <template v-else-if="detail.student_no">
            <div class="detail-head">
              <div>
                <span class="detail-name">{{ detail.name || '—' }}</span>
                <span class="detail-no">{{ detail.student_no }}</span>
                <el-tag :type="levelType(activeRow?.level)" effect="dark" size="small">
                  {{ levelText(activeRow?.level) }}
                </el-tag>
                <el-tag type="danger" effect="plain" size="small">
                  风险分 <count-number :value="activeRow?.risk_score" />
                </el-tag>
              </div>
              <div class="detail-source">
                数据源 {{ detail.source || '-' }} · 画像版本 {{ detail.calc_version || '-' }}
              </div>
            </div>

            <el-descriptions :column="3" border size="small" class="detail-desc">
              <el-descriptions-item label="学院">{{ detail.college || '-' }}</el-descriptions-item>
              <el-descriptions-item label="专业">{{ detail.major || '-' }}</el-descriptions-item>
              <el-descriptions-item label="班级">{{ detail.class_name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="年级">{{ detail.grade || '-' }}</el-descriptions-item>
              <el-descriptions-item label="学期">{{ detail.term || '-' }}</el-descriptions-item>
              <el-descriptions-item label="可用指标">{{ activeRow?.coverage ?? '-' }} 项</el-descriptions-item>
              <el-descriptions-item label="缺失项">
                <span v-if="!activeRow?.missing?.length">无</span>
                <span v-else class="missing">{{ activeRow.missing.join('、') }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="班内对比">
                班均 {{ overview.avg_gpa ?? '-' }} · 本人 {{ stored.gpa ?? '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="数据源">{{ detail.source || '-' }}</el-descriptions-item>
              <el-descriptions-item label="画像版本">{{ detail.calc_version || '-' }}</el-descriptions-item>
            </el-descriptions>

            <div class="card-title" style="margin-top: 12px">预警归因</div>
            <div class="reason-line">
              <el-tag v-for="(r, i) in activeRow?.reasons || []" :key="i" type="danger" effect="plain">
                {{ r }}
              </el-tag>
              <span v-if="!(activeRow?.reasons || []).length" class="muted">本学期没有触发项</span>
            </div>

            <div class="tag-line">
              <el-tag v-for="t in detail.tags || []" :key="t" class="tag-item">{{ t }}</el-tag>
              <span v-if="!(detail.tags || []).length" class="muted">暂无画像标签</span>
            </div>

            <el-row :gutter="8">
              <el-col :span="12">
                <div class="card-title">四维画像</div>
                <div ref="radarRef" class="chart-box"></div>
              </el-col>
              <el-col :span="12">
                <div class="card-title">成绩趋势（各学期均分）</div>
                <div ref="trendRef" class="chart-box"></div>
              </el-col>
            </el-row>

            <div class="card-title" style="margin-top: 12px">画像指标明细</div>
            <el-descriptions :column="4" border size="small">
              <el-descriptions-item label="本学期均分">{{ stored.gpa ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="成绩变化">{{ stored.gpa_trend ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="挂科门次">{{ stored.fail_count ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="出勤率">{{ rate(stored.attendance_rate) }}</el-descriptions-item>
              <el-descriptions-item label="班级排名百分位">{{ pct(stored.class_rank_pct) }}</el-descriptions-item>
              <el-descriptions-item label="专业排名百分位">{{ pct(stored.major_rank_pct) }}</el-descriptions-item>
              <el-descriptions-item label="图书馆到馆">{{ stored.library_visit_cnt ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="借阅活跃度">{{ stored.library_activity ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="证书数">{{ stored.cert_count ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="竞赛数">{{ stored.contest_count ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="项目数">{{ stored.project_cnt ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="选课偏好">{{ stored.course_pref ?? '-' }}</el-descriptions-item>
            </el-descriptions>

            <el-alert class="note" type="info" :closable="false" show-icon
              :title="`班级整体瞄准的就业方向：${gap.target_direction || '—'}（班级样本 ${gap.sample_cnt ?? '-'} 条浏览），个人匹配度请参考上面的画像与预警`" />
          </template>
        </el-card>
      </el-col>
    </el-row>
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
const LEVELS = [
  { value: 'red', label: '红色预警' },
  { value: 'orange', label: '橙色预警' },
  { value: 'yellow', label: '黄色预警' },
  { value: 'none', label: '正常' },
  { value: 'unknown', label: '数据不足' }
]
const HISTORY_KEY = 'qh_class_history'

const className = ref(localStorage.getItem('qh_last_class') || '')
const studentNo = ref('')
const term = ref('2025-2026-2')
const colleges = ref([])
const classes = ref([])
const majors = ref([])
const college = ref('')
const major = ref('')
const level = ref('')
const rows = ref([])
const classmates = ref(0)
const overview = ref({})
const warnings = ref({})
const gap = ref({})
const listLoading = ref(false)
const studentSearchLoading = ref(false)
const firstLoading = ref(false)
const detailLoading = ref(false)
const detail = ref({})
const activeNo = ref('')
const lastLoadAt = ref(null)
const autoRefresh = ref(false)
const radarRef = ref(null)
const trendRef = ref(null)
let radarChart = null
let trendChart = null
let timer = null
const clock = useClock()

const activeRow = computed(() => rows.value.find((row) => row.student_no === activeNo.value) || null)
const stored = computed(() => detail.value.stored || {})

const INTENT_META = [
  { key: '考公', label: '考公', color: '#dc2626' },
  { key: '考研', label: '考研', color: '#d97706' },
  { key: '考编', label: '考编', color: '#16a34a' },
  { key: '就业', label: '就业', color: '#2563eb' },
  { key: '未填写', label: '未填写', color: '#a1a1aa' }
]

const intentItems = computed(() => {
  const dist = overview.value?.career_intent?.distribution || {}
  return INTENT_META.map((item) => ({ ...item, value: Number(dist[item.key] || 0) }))
})

function levelText(level) {
  return LEVEL_TEXT[level] || level || '-'
}

function levelType(level) {
  return LEVEL_TYPE[level] || 'info'
}

function rate(v) {
  return v === null || v === undefined ? '-' : `${(Number(v) * 100).toFixed(1)}%`
}

function pct(v) {
  return v === null || v === undefined ? '-' : `${(Number(v) * 100).toFixed(1)}%`
}

function rememberClass(name) {
  if (!name) return
  const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  const next = [name, ...history.filter((item) => item !== name)].slice(0, 10)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
  localStorage.setItem('qh_last_class', name)
}

// 三级级联：学院 → 专业 → 班级
const majorOptions = computed(() =>
  college.value ? majors.value.filter((item) => item.college === college.value) : []
)

const filteredClasses = computed(() => {
  let list = classes.value
  if (college.value) list = list.filter((item) => item.college === college.value)
  // 一个班可能挂多个专业，只要包含所选专业就算命中
  if (major.value) list = list.filter((item) => (item.majors || []).includes(major.value))
  return list
})

async function loadDirectory() {
  try {
    const { data } = await http.get('/teacher/classes')
    classes.value = data?.classes || []
    colleges.value = data?.colleges || []
    majors.value = data?.majors || []
    if (!className.value) {
      const remembered = localStorage.getItem('qh_last_class')
      const hit = classes.value.find((item) => item.class_name === remembered)
      className.value = hit ? hit.class_name : (classes.value[0]?.class_name || '')
      if (hit) {
        college.value = hit.college
        major.value = (hit.majors || [])[0] || ''
      }
    }
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '班级目录加载失败')
  }
}

// 班级选项里的专业标注：单专业直接显示，多专业显示数量
function majorLabel(item) {
  const list = item?.majors || []
  if (!list.length) return '专业未填'
  return list.length === 1 ? list[0] : `${list.length} 个专业`
}

// 换学院：专业清空，班级落到该学院第一个班
function onCollegeChange(value) {
  major.value = ''
  const list = value ? filteredClasses.value : classes.value
  if (!list.some((item) => item.class_name === className.value)) {
    className.value = list[0]?.class_name || ''
    rememberClass(className.value)
    loadClass()
  }
}

// 换专业：班级落到该专业第一个班
function onMajorChange() {
  const list = filteredClasses.value
  if (!list.some((item) => item.class_name === className.value)) {
    className.value = list[0]?.class_name || ''
    rememberClass(className.value)
    loadClass()
  }
}

async function loadClass() {
  const klass = String(className.value || '').trim()
  if (!klass) {
    ElMessage.warning('请先选择班级')
    return
  }
  rememberClass(klass)
  listLoading.value = true
  try {
    const [wnRes, ovRes, gapRes] = await Promise.all([
      http.get('/teacher/warnings', {
        params: { class_name: klass, term: term.value, level: level.value || undefined }
      }),
      http.get('/teacher/class-overview', { params: { class_name: klass, term: term.value } }),
      http.get('/teacher/career-gap', { params: { class_name: klass, term: term.value } }).catch(() => ({ data: {} }))
    ])
    warnings.value = wnRes.data || {}
    rows.value = wnRes.data?.items || []
    overview.value = ovRes.data || {}
    classmates.value = Number(ovRes.data?.headcount || 0)
    gap.value = gapRes.data || {}
    lastLoadAt.value = new Date()
    // 选中的学生被筛掉时自动清空右侧
    if (activeNo.value && !rows.value.some((row) => row.student_no === activeNo.value)) {
      activeNo.value = ''
      detail.value = {}
    } else if (activeNo.value) {
      loadDetail(activeNo.value)
    }
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '名单加载失败')
  } finally {
    listLoading.value = false
    firstLoading.value = false
  }
}

function clearFilter() {
  college.value = ''
  major.value = ''
  className.value = classes.value[0]?.class_name || ''
  level.value = ''
  term.value = '2025-2026-2'
  rows.value = []
  studentNo.value = ''
  detail.value = {}
  activeNo.value = ''
  overview.value = {}
  warnings.value = {}
  gap.value = {}
  classmates.value = 0
}

function onClassChange() {
  // 直接选班级时把上级两项补齐，保证三级筛选状态与当前班级一致
  const meta = classes.value.find((item) => item.class_name === className.value)
  if (meta) {
    if (!college.value) college.value = meta.college || ''
    if (!major.value) major.value = (meta.majors || [])[0] || ''
  }
  rememberClass(className.value)
  loadClass()
}

async function loadDetail(studentNo) {
  detailLoading.value = true
  try {
    const { data } = await http.get(`/teacher/student/${encodeURIComponent(studentNo)}`, {
      params: { term: term.value }
    })
    detail.value = data || {}
    await nextTick()
    renderRadar(detail.value)
    renderTrend(detail.value)
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '个人档案加载失败')
    detail.value = {}
  } finally {
    detailLoading.value = false
  }
}

async function searchStudent() {
  const no = String(studentNo.value || '').trim()
  if (!no) {
    ElMessage.warning('请输入学号')
    return
  }
  studentSearchLoading.value = true
  try {
    const { data } = await http.get(`/teacher/student/${encodeURIComponent(no)}`, {
      params: { term: term.value }
    })
    const klass = String(data?.class_name || '').trim()
    if (klass) {
      className.value = klass
      const hit = classes.value.find((item) => item.class_name === klass)
      if (hit) college.value = hit.college
    }
    if (data?.term) term.value = data.term
    level.value = ''
    activeNo.value = ''
    detail.value = {}
    await loadClass()
    activeNo.value = String(data?.student_no || no)
    detail.value = data || {}
    await nextTick()
    renderRadar(detail.value)
    renderTrend(detail.value)
    ElMessage.success(`已定位 ${detail.value.name || no}`)
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || `未找到学号 ${no}`)
    detail.value = {}
    activeNo.value = ''
  } finally {
    studentSearchLoading.value = false
  }
}

function selectStudent(row) {
  const no = row?.student_no
  if (!no || no === activeNo.value) return
  activeNo.value = no
  loadDetail(no)
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
      radar: { indicator: keys.map((key) => ({ name: names[key], max: 1 })), radius: '64%' },
      series: [
        {
          type: 'radar',
          areaStyle: { opacity: 0.25 },
          lineStyle: { color: '#e5484d' },
          itemStyle: { color: '#e5484d' },
          animationDuration: 700,
          data: [{ name: '四维画像', value: keys.map((key) => Number(dims[key] ?? 0)) }]
        }
      ]
    },
    true
  )
}

function renderTrend(data) {
  if (!trendRef.value) return
  trendChart = trendChart || echarts.init(trendRef.value)
  const series = data?.gpa_trend_series || []
  trendChart.setOption(
    {
      grid: { left: 44, right: 16, top: 24, bottom: 28 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: series.map((row) => row.term), boundaryGap: false },
      yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: '#e5e6eb' } } },
      series: [
        {
          type: 'line',
          smooth: true,
          symbolSize: 7,
          areaStyle: { opacity: 0.15 },
          itemStyle: { color: '#e5484d' },
          data: series.map((row) => row.gpa),
          animationDuration: 700
        }
      ]
    },
    true
  )
}

function onResize() {
  radarChart?.resize()
  trendChart?.resize()
}

watch(autoRefresh, (on) => {
  if (timer) clearInterval(timer)
  timer = on ? setInterval(loadClass, 30000) : null
})

onMounted(async () => {
  firstLoading.value = true
  await loadDirectory()
  await loadClass()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('resize', onResize)
  radarChart?.dispose()
  trendChart?.dispose()
  radarChart = null
  trendChart = null
})
</script>

<style scoped>
.filter-bar {
  margin-bottom: 12px;
}

.intent-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--qh-surface, #fff);
  border: 1px solid var(--qh-border, #e5e6eb);
  border-radius: var(--qh-radius-lg, 8px);
  font-size: 13px;
}

.intent-bar-label {
  color: var(--qh-text-mute, #86909c);
  margin-right: 2px;
}

.intent-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--intent-color) 10%, transparent);
  color: var(--intent-color);
}

.intent-chip b {
  font-variant-numeric: tabular-nums;
}

.intent-bar-total {
  margin-left: auto;
  color: var(--qh-text-mute, #86909c);
  font-size: 12px;
}

.option-note {
  float: right;
  margin-left: 12px;
  font-size: 12px;
  color: #a9aeb8;
}

.refresh-tip {
  font-size: 12px;
  color: #86909c;
  margin-right: 4px;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.detail-name {
  font-size: 18px;
  font-weight: 600;
  margin-right: 8px;
}

.detail-no {
  color: #86909c;
  margin-right: 10px;
}

.detail-source {
  font-size: 12px;
  color: #86909c;
}

.detail-desc {
  margin-bottom: 4px;
}

.reason-line,
.tag-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.muted {
  font-size: 13px;
  color: #86909c;
}

.missing {
  color: var(--qh-orange);
}

.chart-box {
  height: 240px;
  width: 100%;
}

.note {
  margin-top: 12px;
}
</style>
