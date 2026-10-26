<template>
  <div class="page">
    <el-card shadow="never" class="filter-bar">
      <el-form inline @submit.prevent>
        <el-form-item label="班级">
          <el-autocomplete
            v-model="className"
            :fetch-suggestions="suggestClass"
            placeholder="如 AI2201"
            style="width: 180px"
            @keyup.enter="loadClass"
          />
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
          <el-empty v-if="!activeNo" description="先在左侧点一名学生，查看他/她的个人档案" />
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
              <el-descriptions-item label="专业">{{ detail.major || '-' }}</el-descriptions-item>
              <el-descriptions-item label="班级">{{ detail.class_name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="学期">{{ detail.term || '-' }}</el-descriptions-item>
              <el-descriptions-item label="可用指标">{{ activeRow?.coverage ?? '-' }} 项</el-descriptions-item>
              <el-descriptions-item label="缺失项">
                <span v-if="!activeRow?.missing?.length">无</span>
                <span v-else class="missing">{{ activeRow.missing.join('、') }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="班内对比">
                班均 {{ overview.avg_gpa ?? '-' }} · 本人 {{ stored.gpa ?? '-' }}
              </el-descriptions-item>
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

const className = ref(localStorage.getItem('qh_last_class') || 'AI2201')
const term = ref('2025-2026-2')
const level = ref('')
const rows = ref([])
const classmates = ref(0)
const overview = ref({})
const warnings = ref({})
const gap = ref({})
const listLoading = ref(false)
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

function suggestClass(query, cb) {
  const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  const keyword = String(query || '').trim()
  cb(history.filter((name) => !keyword || name.includes(keyword)).map((value) => ({ value })))
}

function rememberClass(name) {
  const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  const next = [name, ...history.filter((item) => item !== name)].slice(0, 10)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
  localStorage.setItem('qh_last_class', name)
}

async function loadClass() {
  const klass = String(className.value || '').trim()
  if (!klass) {
    ElMessage.warning('请先填写班级名')
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
  level.value = ''
  term.value = '2025-2026-2'
  rows.value = []
  detail.value = {}
  activeNo.value = ''
  overview.value = {}
  warnings.value = {}
  gap.value = {}
  classmates.value = 0
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

onMounted(() => {
  firstLoading.value = true
  loadClass()
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
