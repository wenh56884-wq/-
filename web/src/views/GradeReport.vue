<template>
  <div class="page bento-page">
    <div class="bento-grid">
      <!-- 教师：班级/学生选择 -->
      <section v-if="isTeacher" class="bento-card bento-span-4 filter-card">
        <el-form inline @submit.prevent>
          <el-form-item label="班级">
            <el-select v-model="className" filterable style="width: 200px" @change="loadStudents">
              <el-option v-for="k in classes" :key="k.class_name" :label="k.class_name" :value="k.class_name" />
            </el-select>
          </el-form-item>
          <el-form-item label="学生">
            <el-select v-model="studentNo" filterable style="width: 260px" @change="loadGrades">
              <el-option v-for="s in students" :key="s.student_no"
                :label="`${s.student_no} ${s.name || ''}`" :value="s.student_no" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="loading" :disabled="!studentNo" @click="loadGrades">
              查询成绩
            </el-button>
          </el-form-item>
        </el-form>
        <div v-if="err" class="err">{{ err }}</div>
      </section>

      <!-- 学生信息 + 汇总 -->
      <section v-if="report" class="bento-card bento-span-4 summary-card">
        <div class="summary-head">
          <div>
            <p class="bento-eyebrow">成绩单</p>
            <h2 class="summary-name">
              {{ student.name || '—' }}<small>{{ student.student_no }}</small>
            </h2>
            <p class="bento-sub">
              {{ student.major || '专业未填' }} · {{ student.class_name || '班级未填' }}
              · {{ student.grade || '年级未知' }}
            </p>
          </div>
          <div class="summary-stats">
            <div><span>课程</span><b>{{ summary.course_count ?? 0 }}</b></div>
            <div><span>学分</span><b>{{ summary.credits ?? 0 }}</b></div>
            <div><span>加权均分</span><b>{{ summary.weighted_avg ?? '—' }}</b></div>
            <div><span>挂科</span><b :class="{ fail: summary.failed_count }">{{ summary.failed_count ?? 0 }}</b></div>
            <div><span>学期</span><b>{{ summary.term_count ?? 0 }}</b></div>
            <div><span>记录</span><b>{{ summary.record_count ?? 0 }}</b></div>
          </div>
        </div>
      </section>

      <!-- 趋势 + 口径 -->
      <section v-if="report" class="bento-card bento-span-2 chart-card">
        <div class="card-head">
          <h3 class="bento-title">学期均分趋势</h3>
          <span class="bento-eyebrow">平均分 / 加权均分</span>
        </div>
        <div ref="chartRef" class="chart-box"></div>
      </section>

      <section v-if="report" class="bento-card bento-span-2 note-card">
        <div class="card-head">
          <h3 class="bento-title">成绩口径</h3>
          <span class="bento-eyebrow">引擎 {{ report.engine_version }}</span>
        </div>
        <ul class="note-list">
          <li v-for="n in report.notes || []" :key="n">{{ n }}</li>
        </ul>
        <div class="note-meta">
          共 {{ summary.year_count || 0 }} 个学年 · {{ summary.term_count || 0 }} 个学期 ·
          {{ summary.record_count || 0 }} 条原始记录
        </div>
      </section>

      <!-- 学年 tabs：每学期一张全量成绩表 -->
      <section v-if="report" class="bento-card bento-span-4 years-card">
        <el-tabs v-model="activeYear">
          <el-tab-pane v-for="year in report.years" :key="year.year"
            :label="`${year.year} 学年`" :name="year.year">
            <div class="year-summary">
              <span>平均分 <b>{{ year.avg_score ?? '—' }}</b></span>
              <span>加权均分 <b>{{ year.weighted_avg ?? '—' }}</b></span>
              <span>学分 <b>{{ year.credits }}</b></span>
              <span>课程 <b>{{ year.course_count }}</b></span>
              <span :class="{ 'is-fail': year.failed_count }">挂科 <b>{{ year.failed_count }}</b></span>
            </div>

            <div v-for="term in year.terms" :key="term.term" class="term-block">
              <div class="term-head">
                <h4>{{ term.term_label }}</h4>
                <span>
                  平均 {{ term.avg_score ?? '—' }} · 加权 {{ term.weighted_avg ?? '—' }}
                  · 学分 {{ term.credits }} · {{ term.record_count }} 条记录
                </span>
              </div>
              <el-table :data="term.records" size="small" border stripe>
                <el-table-column prop="course_code" label="课程代码" width="110" />
                <el-table-column prop="course_name" label="课程" min-width="180" show-overflow-tooltip />
                <el-table-column prop="credit" label="学分" width="80" />
                <el-table-column label="成绩" width="90">
                  <template #default="{ row }">
                    <b :class="{ fail: row.score !== null && row.score < 60 }">{{ row.score ?? '—' }}</b>
                  </template>
                </el-table-column>
                <el-table-column prop="attempt" label="第几次" width="80" />
                <el-table-column label="重修" width="80">
                  <template #default="{ row }">
                    <el-tag v-if="row.retake" size="small" type="warning">重修</el-tag>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="90">
                  <template #default="{ row }">
                    <el-tag v-if="row.score !== null" size="small" :type="row.score >= 60 ? 'success' : 'danger'">
                      {{ row.score >= 60 ? '及格' : '挂科' }}
                    </el-tag>
                    <span v-else class="muted">缺考</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-tab-pane>
        </el-tabs>
      </section>

      <el-empty v-if="!report && !loading" class="bento-span-4" description="暂无成绩数据" />
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'

import http, { currentRole } from '../api/http'

const role = currentRole()
const isTeacher = role === 'teacher'
const route = useRoute()

const classes = ref([])
const students = ref([])
const className = ref('')
const studentNo = ref('')
const report = ref(null)
const loading = ref(false)
const err = ref('')
const activeYear = ref('')
const chartRef = ref(null)
let chart = null

const summary = computed(() => report.value?.summary || {})
const student = computed(() => report.value?.student || {})
const termSeries = computed(() => (report.value?.years || []).flatMap(
  (year) => (year.terms || []).map((term) => ({
    term: term.term,
    avg: term.avg_score,
    weighted: term.weighted_avg
  }))
))

async function loadClasses() {
  try {
    const { data } = await http.get('/teacher/classes')
    classes.value = data?.classes || []
    const wanted = String(route.query.student_no || '')
    if (wanted) {
      // 从「学生档案」跳进来时，先定位该生班级，避免下拉框落在别的班
      try {
        const { data: prof } = await http.get(`/teacher/student/${encodeURIComponent(wanted)}`, {
          params: { term: '2025-2026-2' }
        })
        if (prof?.class_name) className.value = prof.class_name
      } catch {
        /* 越权/不存在由下面的 loadGrades 统一提示 */
      }
    }
    if (!className.value && classes.value.length) className.value = classes.value[0].class_name
    await loadStudents()
  } catch (e) {
    err.value = e?.response?.data?.detail || '班级目录加载失败'
  }
}

async function loadStudents() {
  if (!className.value) return
  try {
    const { data } = await http.get('/teacher/warnings', {
      params: { class_name: className.value, term: '2025-2026-2' }
    })
    students.value = data?.items || []
    const wanted = String(route.query.student_no || '')
    if (wanted && students.value.some((s) => s.student_no === wanted)) {
      studentNo.value = wanted
    } else if (!students.value.some((s) => s.student_no === studentNo.value)) {
      studentNo.value = students.value[0]?.student_no || ''
    }
    if (studentNo.value) await loadGrades()
  } catch (e) {
    err.value = e?.response?.data?.detail || '学生名单加载失败'
  }
}

async function loadGrades() {
  if (isTeacher && !studentNo.value) return
  loading.value = true
  err.value = ''
  try {
    const { data } = isTeacher
      ? await http.get(`/grades/student/${encodeURIComponent(studentNo.value)}`)
      : await http.get('/grades/me')
    report.value = data
  } catch (e) {
    report.value = null
    err.value = e?.response?.data?.detail || '成绩加载失败'
    ElMessage.error(err.value)
  } finally {
    loading.value = false
  }
}

function renderChart() {
  if (!chartRef.value) return
  chart = chart || echarts.init(chartRef.value)
  const rows = termSeries.value
  chart.setOption({
    grid: { left: 12, right: 16, top: 36, bottom: 8, containLabel: true },
    tooltip: { trigger: 'axis' },
    legend: { data: ['平均分', '加权均分'], right: 0, top: 0, textStyle: { fontSize: 11 } },
    xAxis: {
      type: 'category',
      data: rows.map((r) => r.term),
      axisLabel: { fontSize: 10, rotate: 30, align: 'right', margin: 10, hideOverlap: true }
    },
    yAxis: {
      type: 'value', min: 0, max: 100,
      splitLine: { lineStyle: { color: '#f4f4f5' } }
    },
    series: [
      {
        name: '平均分', type: 'line', smooth: true,
        data: rows.map((r) => r.avg),
        lineStyle: { color: '#ea580c', width: 2 },
        itemStyle: { color: '#ea580c' },
        areaStyle: { opacity: 0.08 }
      },
      {
        name: '加权均分', type: 'line', smooth: true,
        data: rows.map((r) => r.weighted),
        lineStyle: { color: '#2563eb', width: 2 },
        itemStyle: { color: '#2563eb' }
      }
    ]
  }, true)
  chart.resize()
}

function onResize() {
  chart?.resize()
}

watch(report, async (value) => {
  activeYear.value = value?.years?.[0]?.year || ''
  await nextTick()
  renderChart()
})

onMounted(async () => {
  window.addEventListener('resize', onResize)
  if (isTeacher) await loadClasses()
  else await loadGrades()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.filter-card {
  padding: 16px 18px;
}

.filter-card :deep(.el-form-item) {
  margin-bottom: 10px;
}

.err {
  color: var(--qh-red);
  font-size: 12px;
}

.summary-card {
  padding: 24px 28px;
}

.summary-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
}

.summary-name {
  margin: 0;
  font-size: clamp(24px, 2.4vw, 34px);
  font-weight: 700;
  line-height: 1.2;
  color: var(--bento-text);
}

.summary-name small {
  margin-left: 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--bento-mute);
}

.summary-stats {
  display: grid;
  grid-template-columns: repeat(6, minmax(70px, 1fr));
  gap: 12px;
  min-width: min(560px, 100%);
}

.summary-stats div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: 14px;
  background: #fafafa;
}

.summary-stats span {
  font-size: 12px;
  color: var(--bento-mute);
}

.summary-stats b {
  font-size: 22px;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
  color: var(--bento-text);
}

.summary-stats b.fail {
  color: var(--qh-red);
}

.chart-card {
  display: flex;
  flex-direction: column;
}

.chart-box {
  height: 320px;
  width: 100%;
}

.note-list {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.85;
  color: var(--bento-sub);
}

.note-meta {
  margin-top: 12px;
  font-size: 12px;
  color: var(--bento-mute);
}

.years-card {
  padding: 18px 22px 22px;
}

.years-card :deep(.el-tabs__header) {
  margin-bottom: 18px;
}

.year-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  padding: 10px 14px;
  margin-bottom: 16px;
  border-radius: 14px;
  background: #fafafa;
  font-size: 13px;
  color: var(--bento-sub);
}

.year-summary b {
  color: var(--bento-text);
  font-variant-numeric: tabular-nums;
}

.year-summary .is-fail b {
  color: var(--qh-red);
}

.term-block + .term-block {
  margin-top: 22px;
}

.term-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.term-head h4 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  color: var(--bento-text);
}

.term-head span {
  font-size: 12px;
  color: var(--bento-mute);
}

.fail {
  color: var(--qh-red);
}

.muted {
  color: var(--bento-mute);
}

@media (max-width: 900px) {
  .summary-stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    min-width: 100%;
  }
}

@media (max-width: 700px) {
  .summary-card {
    padding: 18px;
  }

  .summary-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .chart-box {
    height: 260px;
  }
}
</style>
