<template>
  <div class="page bento-page">
    <div class="bento-grid">
    <section class="bento-card bento-span-4 filter-bar">
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
            style="width: 200px"
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
            style="width: 200px"
            @change="onClassChange"
          >
            <el-option v-for="k in filteredClasses" :key="k.class_name" :label="k.class_name" :value="k.class_name">
              <span>{{ k.class_name }}</span>
              <span class="option-note">{{ k.headcount }} 人 · {{ majorLabel(k) }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="学期">
          <el-input v-model="term" placeholder="如 2025-2026-2" style="width: 160px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="loadAll">查询</el-button>
          <el-button @click="reset">重置</el-button>
          <el-button @click="openThresholds">预警阈值</el-button>
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
    </section>

    <article class="bento-card stat-card stat-red">
      <div class="stat-top">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M12 3l9 16H3L12 3z" /><path d="M12 9v4M12 16h.01" /></svg>
        </span>
        <span class="stat-label">红色预警</span>
      </div>
      <div class="bento-stat"><count-number :value="dist.red" /></div>
    </article>

    <article class="bento-card stat-card stat-orange">
      <div class="stat-top">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></svg>
        </span>
        <span class="stat-label">橙色预警</span>
      </div>
      <div class="bento-stat"><count-number :value="dist.orange" /></div>
    </article>

    <article class="bento-card stat-card stat-yellow">
      <div class="stat-top">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M12 4a6 6 0 0 0-6 6v4l-2 3h16l-2-3v-4a6 6 0 0 0-6-6z" /><path d="M10 19a2 2 0 0 0 4 0" /></svg>
        </span>
        <span class="stat-label">黄色预警</span>
      </div>
      <div class="bento-stat"><count-number :value="dist.yellow" /></div>
    </article>

    <article class="bento-card stat-card stat-normal">
      <div class="stat-top">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3" /><path d="M3 20a6 6 0 0 1 12 0M16 5a3 3 0 0 1 0 6M18 20a5 5 0 0 0-3-4.5" /></svg>
        </span>
        <span class="stat-label">班级人数 / 均分</span>
      </div>
      <div class="bento-stat">
        <count-number :value="overview.headcount" />
        <span class="stat-sep">/</span>
        <count-number :value="overview.avg_gpa" :decimals="1" />
      </div>
    </article>

    <section class="bento-card bento-span-2 bento-row-2 hero-card" v-loading="loading">
      <div class="hero-head">
        <div>
          <p class="bento-eyebrow">班级概貌</p>
          <h2 class="hero-class-name">{{ overview.class_name || '请选择班级' }}</h2>
          <p class="bento-sub">{{ currentCollege || '—' }} · {{ currentMajors }}</p>
        </div>
        <el-tag size="small" effect="plain">{{ overview.term || term || '—' }}</el-tag>
      </div>

      <div class="hero-metrics">
        <div>
          <span>在册人数</span>
          <b><count-number :value="overview.headcount" /></b>
        </div>
        <div>
          <span>班级均分</span>
          <b><count-number :value="overview.avg_gpa" :decimals="1" /></b>
        </div>
        <div>
          <span>挂科率</span>
          <b>{{ fmtRate(overview.fail_rate) }}</b>
        </div>
        <div>
          <span>挂科人数</span>
          <b><count-number :value="overview.fail_students" /></b>
        </div>
      </div>

      <div class="hero-split">
        <div class="split-bar" aria-hidden="true">
          <span class="seg seg-red" :style="{ flex: dist.red || 0 }" />
          <span class="seg seg-orange" :style="{ flex: dist.orange || 0 }" />
          <span class="seg seg-yellow" :style="{ flex: dist.yellow || 0 }" />
          <span class="seg seg-none" :style="{ flex: dist.none || 0 }" />
        </div>
        <div class="split-legend">
          <span><i class="dot dot-red" />红 {{ dist.red || 0 }}</span>
          <span><i class="dot dot-orange" />橙 {{ dist.orange || 0 }}</span>
          <span><i class="dot dot-yellow" />黄 {{ dist.yellow || 0 }}</span>
          <span><i class="dot dot-none" />正常 {{ dist.none || 0 }}</span>
        </div>
      </div>

      <div class="hero-info">
        <div><span>学院</span><b>{{ currentCollege || '-' }}</b></div>
        <div><span>专业</span><b>{{ currentMajors || '-' }}</b></div>
      </div>

      <div class="hero-links">
        <router-link to="/teacher/students" class="hero-link">学生档案</router-link>
        <router-link to="/teacher/jobs" class="hero-link">岗位库</router-link>
        <router-link to="/teacher/exams" class="hero-link">招考信息</router-link>
        <router-link to="/teacher/kg" class="hero-link">知识图谱</router-link>
      </div>

      <div class="hero-foot">
        {{ overview.term || term || '-' }} · 引擎 {{ warnings.engine_version || overview.engine_version || '-' }}
        · 画像 {{ warnings.calc_version || overview.calc_version || '-' }} · 数据于 {{ clock.ago(lastLoadAt) }}
      </div>
    </section>

    <section class="bento-card bento-span-2 chart-card" v-loading="loading">
      <div class="card-head">
        <h3 class="bento-title">预警等级分布</h3>
        <span class="bento-eyebrow">按当前班级</span>
      </div>
      <div ref="barRef" class="chart-box"></div>
    </section>

    <section class="bento-card bento-span-2 risk-card">
      <div class="card-head">
        <h3 class="bento-title">高风险 Top5</h3>
        <span class="bento-eyebrow">点击行看画像</span>
      </div>
      <el-empty v-if="!overview.top_risk_students?.length" description="暂无数据" />
      <ul v-else class="risk-list">
        <li v-for="s in overview.top_risk_students" :key="s.student_no">
          <el-tag :type="levelType(s.level)" size="small">{{ s.student_no }}</el-tag>
          <span class="risk-name">{{ s.name || '—' }}</span>
          <span class="risk-score">{{ s.risk_score }}</span>
        </li>
      </ul>
    </section>

    <section class="bento-card bento-span-4 intent-card" v-loading="loading">
      <div class="intent-head">
        <span class="card-title" style="margin: 0">职业目标分布</span>
        <el-tag size="small" effect="plain">
          已填写 {{ overview.career_intent?.filled ?? 0 }} / {{ overview.career_intent?.total ?? 0 }} 人
        </el-tag>
      </div>
      <el-empty v-if="!(overview.career_intent?.total)" description="暂无学生数据" />
      <div v-else class="intent-grid">
        <div
          v-for="item in intentItems"
          :key="item.key"
          class="intent-item"
          :style="{ '--intent-color': item.color }"
        >
          <div class="intent-label">{{ item.label }}</div>
          <div class="intent-value"><count-number :value="item.value" /></div>
          <div class="intent-rate">{{ item.rate }}</div>
        </div>
      </div>
    </section>

    <section class="bento-card bento-span-4 table-card">
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
        <el-table-column label="归因摘要" min-width="280">
          <template #default="{ row }">
            <span v-if="row.reasons?.length" class="table-reason">
              {{ row.reasons[0] }}<template v-if="row.reasons.length > 1"> 等 {{ row.reasons.length }} 项</template>
            </span>
            <span v-else class="table-reason muted">无触发项</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openProfile(row)">画像</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !(warnings.items || []).length" description="该班级暂无预警数据" />
    </section>
    </div>

    <el-dialog v-model="thresholdDialog" title="班级预警阈值" width="760px">
      <div class="threshold-head">
        <span>班级：<b>{{ className || '-' }}</b></span>
        <span class="muted">留空 = 回退租户默认 / 引擎默认</span>
      </div>
      <el-table v-loading="thresholdLoading" :data="thresholdRows" border size="small">
        <el-table-column prop="label" label="指标" width="110" />
        <el-table-column label="权重" width="115">
          <template #default="{ row }">
            <el-input-number
              v-if="row.metric !== 'level' && row.metric !== 'gpa_drop_slope'"
              v-model="row.weight" :min="0" :max="10" :step="0.1" size="small"
              controls-position="right" :value-on-clear="null"
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="黄色阈值" width="125">
          <template #default="{ row }">
            <el-input-number
              v-model="row.yellow_value" :min="0" :step="1" size="small"
              controls-position="right" :value-on-clear="null"
            />
          </template>
        </el-table-column>
        <el-table-column label="橙色阈值" width="125">
          <template #default="{ row }">
            <el-input-number
              v-if="row.metric !== 'gpa_drop_slope'"
              v-model="row.orange_value" :min="0" :step="1" size="small"
              controls-position="right" :value-on-clear="null"
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="红色阈值" width="125">
          <template #default="{ row }">
            <el-input-number
              v-if="row.metric !== 'gpa_drop_slope'"
              v-model="row.red_value" :min="0" :step="1" size="small"
              controls-position="right" :value-on-clear="null"
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ thresholdSourceText(row.source) }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div class="threshold-tip">{{ thresholdTip }}</div>
      <template #footer>
        <el-button @click="thresholdDialog = false">取消</el-button>
        <el-button type="primary" :loading="thresholdSaving" @click="saveThresholds">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="drawer" :title="`${profile.name || ''}（${profile.student_no || ''}）画像`" size="45%">
      <div v-loading="profileLoading">
        <el-empty v-if="!profile.student_no && !profileLoading" description="未加载到画像" />
        <template v-else>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="学院">{{ profile.college || '-' }}</el-descriptions-item>
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
const className = ref(localStorage.getItem('qh_last_class') || '')
const term = ref('2025-2026-2')
const colleges = ref([])
const classes = ref([])
const majors = ref([])
const college = ref('')
const major = ref('')
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

const INTENT_META = [
  { key: '考公', label: '考公', color: '#dc2626' },
  { key: '考研', label: '考研', color: '#d97706' },
  { key: '考编', label: '考编', color: '#16a34a' },
  { key: '就业', label: '就业', color: '#2563eb' },
  { key: '未填写', label: '未填写', color: '#a1a1aa' }
]

// 职业目标人数全部来自 /teacher/class-overview，前端只做展示，不做任何推断
const intentItems = computed(() => {
  const info = overview.value?.career_intent || {}
  const distMap = info.distribution || {}
  const total = Number(info.total || 0)
  return INTENT_META.map((item) => {
    const value = Number(distMap[item.key] || 0)
    return {
      ...item,
      value,
      rate: total ? `${((value / total) * 100).toFixed(1)}%` : '-'
    }
  })
})

const thresholdDialog = ref(false)
const thresholdLoading = ref(false)
const thresholdSaving = ref(false)
const thresholdRows = ref([])
const thresholdTip = ref('')

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

// 学院/专业取自己那份班级目录（同源数据），不依赖任何前端推断
const currentClassMeta = computed(() =>
  classes.value.find((item) => item.class_name === className.value) || null
)
const currentCollege = computed(() => currentClassMeta.value?.college || '')
const currentMajors = computed(() => (currentClassMeta.value?.majors || []).join('、') || '-')

// 班级目录来自后端（本租户可见范围），前端不做任何推断
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

async function loadClass(reportError = true) {
  const klass = String(className.value || '').trim()
  if (!klass) {
    ElMessage.warning('请先选择班级')
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
  college.value = ''
  major.value = ''
  className.value = classes.value[0]?.class_name || ''
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

function thresholdSourceText(source) {
  const map = { class: '班级覆盖', tenant: '租户默认', default: '引擎默认' }
  return map[source] || source || '-'
}

async function openThresholds() {
  const klass = String(className.value || '').trim()
  if (!klass) {
    ElMessage.warning('请先选择班级')
    return
  }
  thresholdDialog.value = true
  thresholdLoading.value = true
  thresholdTip.value = ''
  try {
    const { data } = await http.get('/teacher/warning-thresholds', {
      params: { class_name: klass }
    })
    thresholdRows.value = (data?.thresholds || []).map((row) => ({ ...row }))
  } catch (err) {
    thresholdTip.value = err?.response?.data?.detail || '阈值加载失败'
  } finally {
    thresholdLoading.value = false
  }
}

async function saveThresholds() {
  const klass = String(className.value || '').trim()
  if (!klass) return
  thresholdSaving.value = true
  thresholdTip.value = ''
  try {
    const payload = {
      thresholds: thresholdRows.value.map((row) => ({
        metric: row.metric,
        weight: row.weight,
        yellow_value: row.yellow_value,
        orange_value: row.orange_value,
        red_value: row.red_value
      }))
    }
    await http.put('/teacher/warning-thresholds', payload, {
      params: { class_name: klass }
    })
    ElMessage.success('阈值已保存，预警结果已按新口径重算')
    thresholdDialog.value = false
    await loadClass()
  } catch (err) {
    thresholdTip.value = err?.response?.data?.detail || '阈值保存失败'
  } finally {
    thresholdSaving.value = false
  }
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

onMounted(async () => {
  await loadDirectory()
  await loadAll()
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
  padding: 16px 18px;
}

.filter-bar :deep(.el-form-item) {
  margin-bottom: 10px;
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

.option-note {
  float: right;
  margin-left: 12px;
  font-size: 12px;
  color: #a9aeb8;
}

.err {
  color: var(--qh-red);
  margin-left: 12px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 128px;
}

.stat-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stat-card .bento-icon {
  width: 38px;
  height: 38px;
  flex-basis: 38px;
}

.stat-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--qh-text-mute);
}

.stat-red .bento-icon { color: var(--qh-red); background: #fef2f2; }
.stat-orange .bento-icon { color: var(--qh-orange); background: #fffbeb; }
.stat-yellow .bento-icon { color: var(--qh-yellow); background: #fefce8; }
.stat-normal .bento-icon { color: #52525b; background: #f4f4f5; }

.stat-red:hover .bento-icon { color: var(--qh-red); background: #fee2e2; }
.stat-orange:hover .bento-icon { color: var(--qh-orange); background: #fef3c7; }
.stat-yellow:hover .bento-icon { color: var(--qh-yellow); background: #fef9c3; }
.stat-normal:hover .bento-icon { color: #18181b; background: #e4e4e7; }

.stat-value {
  font-size: 24px;
  font-weight: 600;
  color: var(--qh-text);
  line-height: 1.3;
  font-variant-numeric: tabular-nums;
}

@media (min-width: 1024px) {
  .stat-value {
    font-size: 30px;
  }
}

.stat-value.small {
  font-size: 20px;
  color: var(--qh-text);
}

.stat-sep {
  margin: 0 6px;
  font-size: 18px;
  font-weight: 500;
  color: var(--bento-mute);
}

.hero-card {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 100%;
}

.hero-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.hero-class-name {
  margin: 0;
  font-size: clamp(26px, 2.6vw, 36px);
  font-weight: 700;
  line-height: 1.15;
  color: var(--bento-text);
}

.hero-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 16px 0;
  border-top: 1px solid var(--bento-border);
  border-bottom: 1px solid var(--bento-border);
}

.hero-metrics div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.hero-metrics span {
  font-size: 12px;
  color: var(--bento-mute);
}

.hero-metrics b {
  font-size: 24px;
  font-weight: 680;
  color: var(--bento-text);
  font-variant-numeric: tabular-nums;
}

.hero-split {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.split-bar {
  display: flex;
  height: 10px;
  gap: 2px;
  overflow: hidden;
  border-radius: 999px;
  background: #f4f4f5;
}

.seg {
  display: block;
  height: 100%;
  min-width: 0;
}

.seg-red { background: #e5484d; }
.seg-orange { background: #f5a623; }
.seg-yellow { background: #f0c808; }
.seg-none { background: #4cb971; }

.split-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--bento-sub);
}

.split-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 999px;
}

.dot-red { background: #e5484d; }
.dot-orange { background: #f5a623; }
.dot-yellow { background: #f0c808; }
.dot-none { background: #4cb971; }

.hero-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hero-info div {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.hero-info span {
  flex: 0 0 40px;
  font-size: 12px;
  color: var(--bento-mute);
}

.hero-info b {
  font-size: 13px;
  font-weight: 500;
  line-height: 1.5;
  color: var(--bento-text);
}

.hero-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hero-link {
  padding: 6px 12px;
  border-radius: 999px;
  background: #f4f4f5;
  color: var(--bento-sub);
  font-size: 12px;
  text-decoration: none;
  transition:
    background-color 200ms var(--bento-ease),
    color 200ms var(--bento-ease),
    transform 200ms var(--bento-ease);
}

.hero-link:hover {
  background: #18181b;
  color: #fff;
  transform: translateY(-1px);
}

.hero-foot {
  margin-top: auto;
  font-size: 12px;
  line-height: 1.6;
  color: var(--bento-mute);
}

.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.chart-card {
  display: flex;
  flex-direction: column;
}

.risk-card {
  display: flex;
  flex-direction: column;
}

.threshold-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--qh-text-sub);
}

.threshold-tip {
  min-height: 18px;
  margin-top: 8px;
  color: var(--qh-red);
  font-size: 12px;
}

.intent-card {
  margin-top: 0;
}

.intent-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.intent-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 16px;
}

.intent-item {
  border: 1px solid var(--qh-border);
  border-radius: 16px;
  background: #fafafa;
  padding: 14px 16px;
  transition: transform 220ms var(--bento-ease), box-shadow 220ms var(--bento-ease);
}

.intent-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.06);
}

.intent-label {
  font-size: 13px;
  color: var(--qh-text-sub);
}

.intent-value {
  font-size: 26px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--intent-color);
  font-variant-numeric: tabular-nums;
}

.intent-rate {
  font-size: 12px;
  color: var(--qh-text-mute);
}

@media (max-width: 900px) {
  .intent-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.chart-box {
  height: 300px;
  width: 100%;
}

.radar-box {
  margin-top: 8px;
}

.table-card {
  margin-top: 0;
}

.expand-box {
  padding: 4px 12px;
  font-size: 13px;
  color: #4e5969;
  line-height: 1.9;
}

.table-reason {
  font-size: 13px;
  color: var(--bento-sub);
}

.table-reason.muted {
  color: var(--bento-mute);
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
  gap: 12px;
  padding: 8px 0;
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
