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
            <el-select v-model="studentNo" filterable clearable placeholder="选择学生后查看个人成绩" style="width: 260px" @change="onStudentChange">
              <el-option v-for="s in studentOptions" :key="s.student_no"
                :label="`${s.student_no} ${s.name || ''}`" :value="s.student_no" />
            </el-select>
          </el-form-item>
          <el-form-item label="学期">
            <el-select v-model="rankTerm" style="width: 160px" @change="loadRank">
              <el-option v-for="t in terms" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="loading" :disabled="!studentNo" @click="loadGrades">
              查询成绩
            </el-button>
          </el-form-item>
          <el-form-item label="导出">
            <el-dropdown trigger="click" :disabled="!className" @command="exportClassGrades">
              <el-button :loading="exportingClass" :disabled="!className"
                title="导出全班成绩：Excel 含「成绩明细」与「个人汇总」两个表">
                全班成绩 <span class="caret">▾</span>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="xlsx">Excel（.xlsx，明细+汇总）</el-dropdown-item>
                  <el-dropdown-item command="csv" divided>CSV（.csv，仅明细）</el-dropdown-item>
                  <el-dropdown-item command="json">JSON（.json，含汇总结构）</el-dropdown-item>
                  <el-dropdown-item command="pick" divided>自选字段…（只要我要的那几列）</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </el-form-item>
        </el-form>
        <div v-if="err" class="err">{{ err }}</div>
      </section>

      <!-- 教师：全班总体平均成绩 -->
      <section v-if="isTeacher && rank" class="bento-card bento-span-2 rank-card">
        <div class="card-head">
          <h3 class="bento-title">全班总体平均成绩</h3>
          <span class="bento-eyebrow">{{ rank.term }} · {{ rank.class_name }}</span>
        </div>
        <div class="class-stats">
          <div>
            <span>加权均分</span>
            <b>{{ curClass?.weighted_avg ?? '—' }}</b>
          </div>
          <div>
            <span>平均分</span>
            <b>{{ curClass?.avg_score ?? '—' }}</b>
          </div>
          <div>
            <span>在册 / 有成绩</span>
            <b>{{ curClass?.student_cnt ?? 0 }} / {{ curClass?.graded_cnt ?? 0 }}</b>
          </div>
          <div>
            <span>最高 / 最低</span>
            <b>{{ curClass?.max_weighted_avg ?? '—' }} / {{ curClass?.min_weighted_avg ?? '—' }}</b>
          </div>
        </div>
        <p class="rank-note">
          班级均分 = 该班各学生个人加权均分的算术平均（学生等权），口径与成绩单一致
        </p>
      </section>

      <!-- 教师：同专业之间的班级排名 -->
      <section v-if="isTeacher && rank" class="bento-card bento-span-2 rank-card">
        <div class="card-head">
          <h3 class="bento-title">同专业班级排名</h3>
          <span class="bento-eyebrow">按「专业 + 班级」聚合</span>
        </div>
        <el-table :data="majorClassRank" size="small" border stripe max-height="300">
          <el-table-column prop="major" label="专业" min-width="120" show-overflow-tooltip />
          <el-table-column prop="class_name" label="班级" width="86" />
          <el-table-column label="名次" width="76">
            <template #default="{ row }">
              <b :class="{ 'is-top': row.rank === 1 }">{{ row.rank }} / {{ row.rank_total }}</b>
            </template>
          </el-table-column>
          <el-table-column prop="student_cnt" label="人数" width="66" />
          <el-table-column label="加权均分" width="88">
            <template #default="{ row }"><b>{{ row.weighted_avg ?? '—' }}</b></template>
          </el-table-column>
        </el-table>
        <p class="rank-note">
          一个班里可能有多个专业，各专业分别计名次；任教范围内共
          {{ comparedClassCnt }} 个班参与比较{{ singleClassHint ? '，该专业范围内仅 1 个班，无法横向比较，如需跨班比较请联系管理员扩充任教班级' : '' }}
        </p>
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
          <div class="export-inline">
            <el-dropdown trigger="click" @command="exportCurrentGrades">
              <el-button size="small" type="primary" plain :loading="exportingOne"
                title="导出当前这份成绩单（与学生端看到的内容完全一致）">
                下载成绩单 <span class="caret">▾</span>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="xlsx">Excel（.xlsx）</el-dropdown-item>
                  <el-dropdown-item command="csv" divided>CSV（.csv）</el-dropdown-item>
                  <el-dropdown-item command="json">JSON（.json）</el-dropdown-item>
                  <el-dropdown-item command="pick" divided>自选字段…（只要我要的那几列）</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
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

      <!-- 教师：班级每个人的平均成绩与排名 -->
      <section v-if="isTeacher && rank" class="bento-card bento-span-4 rank-card">
        <div class="card-head">
          <h3 class="bento-title">班级个人平均成绩与排名</h3>
          <span class="bento-eyebrow">
            点一行看该生成绩单 · 引擎 {{ rank.engine_version }} · 范围
            {{ rank.scope === 'assigned' ? '任教班级' : '本租户' }}
          </span>
        </div>
        <el-table :data="rankStudents" size="small" border stripe max-height="420"
          highlight-current-row @row-click="pickStudent">
          <el-table-column prop="student_no" label="学号" width="130" />
          <el-table-column prop="name" label="姓名" width="86" />
          <el-table-column prop="major" label="专业" min-width="130" show-overflow-tooltip />
          <el-table-column label="加权均分" width="92">
            <template #default="{ row }"><b>{{ row.weighted_avg ?? '—' }}</b></template>
          </el-table-column>
          <el-table-column prop="avg_score" label="平均分" width="84" />
          <el-table-column label="班内名次" width="96">
            <template #default="{ row }">
              <span :class="{ 'is-top': row.class_rank === 1 }">
                {{ row.class_rank ?? '—' }} / {{ row.class_rank_total }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="同专业名次" width="104">
            <template #default="{ row }">
              <span :class="{ 'is-top': row.major_rank === 1 }">
                {{ row.major_rank ?? '—' }} / {{ row.major_rank_total }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="credits" label="学分" width="76" />
          <el-table-column label="挂科" width="72">
            <template #default="{ row }">
              <span :class="{ fail: row.failed_count }">{{ row.failed_count ?? 0 }}</span>
            </template>
          </el-table-column>
        </el-table>
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

      <el-empty
        v-if="isTeacher && !report && !loading && !err"
        class="bento-span-4"
        description="请选择学生查看个人成绩；班级均分与排名已在上方展示"
      />
      <el-empty v-else-if="!isTeacher && !report && !loading" class="bento-span-4" description="暂无成绩数据" />
    </div>

    <!-- 自选字段导出：字段目录由后端给，勾几列就导几列 -->
    <ExportDialog
      v-model="pickOpen"
      :url="pickUrl"
      :dataset="pickDataset"
      :params="pickParams"
      :fallback-name="pickFallback"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import echarts from '../utils/echarts'

import http, { currentRole } from '../api/http'
import ExportDialog from '../components/export/ExportDialog.vue'
import { downloadFile } from '../utils/download'
// 同上：dropdown 三个组件共用一个入口，自动导入会找错路径
import {
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu
} from 'element-plus/es/components/dropdown/index.mjs'
import 'element-plus/es/components/dropdown/style/css'
import 'element-plus/es/components/dropdown-menu/style/css'
import 'element-plus/es/components/dropdown-item/style/css'

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
// 教师端新增：班级成绩分析（全班均分 / 班级排名 / 个人排名）
const rank = ref(null)
const terms = ref([])
const rankTerm = ref('')
let chart = null

const summary = computed(() => report.value?.summary || {})
const student = computed(() => report.value?.student || {})
const curClass = computed(
  () => (rank.value?.classes || []).find((c) => c.class_name === className.value) || null
)
const rankStudents = computed(() => rank.value?.students || [])
// 同专业班级排名里只保留本班涉及的专业，免得把无关专业也铺出来
const majorClassRank = computed(() => {
  const majors = new Set((rankStudents.value || []).map((s) => s.major))
  return (rank.value?.class_rank_in_major || []).filter((r) => majors.has(r.major))
})
// 参与比较的班级数：教师只带一个班时排名没有横向意义，界面要直说，不能让用户猜
const comparedClassCnt = computed(
  () => new Set((rank.value?.class_rank_in_major || []).map((r) => r.class_name)).size
)
const singleClassHint = computed(
  () => majorClassRank.value.length > 0
    && majorClassRank.value.every((r) => (r.rank_total || 0) < 2)
)
// 排名字段给出的是全班名单，比预警名单全，优先用它填学生下拉
const studentOptions = computed(() =>
  rankStudents.value.length ? rankStudents.value : students.value
)
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
      await loadGrades()
    } else {
      // 教师成绩页默认只呈现班级汇总；个人信息必须由教师主动选择。
      studentNo.value = ''
      report.value = null
    }
    await loadRank()
  } catch (e) {
    err.value = e?.response?.data?.detail || '学生名单加载失败'
  }
}

async function loadRank() {
  if (!isTeacher || !className.value) return
  try {
    const { data } = await http.get('/grades/class-rank', {
      params: { class_name: className.value, term: rankTerm.value || undefined }
    })
    rank.value = data
    if (!terms.value.length && data?.available_terms?.length) terms.value = data.available_terms
    if (!rankTerm.value && data?.term) rankTerm.value = data.term
  } catch (e) {
    rank.value = null
    ElMessage.error(e?.response?.data?.detail || '班级成绩分析加载失败')
  }
}

// 点排名表里的一行就看这个学生的成绩单：不必先在下拉里找到他
function pickStudent(row) {
  if (!row?.student_no) return
  studentNo.value = row.student_no
  loadGrades()
}

function onStudentChange() {
  if (!studentNo.value) {
    report.value = null
    return
  }
  loadGrades()
}

// ---------------------------------------------------------------- 导出
// 两个入口分开：全班成绩走教师专属接口，个人成绩单按角色走不同接口
// （学生只能用 /export/my-grades，学号由 JWT 决定，接口层不接受入参指定他人）
const exportingOne = ref(false)
const exportingClass = ref(false)

// 自选字段导出：url / dataset 按角色与当前选择决定，弹窗只负责勾列
const pickOpen = ref(false)
const pickUrl = ref('/export/grades')
const pickDataset = ref('grades')
const pickParams = ref({})
const pickFallback = ref('导出')

function openPicker(url, dataset, params, fallback) {
  pickUrl.value = url
  pickDataset.value = dataset
  pickParams.value = params
  pickFallback.value = fallback
  pickOpen.value = true
}

async function exportCurrentGrades(fmt) {
  const teacher = isTeacher
  if (teacher && !studentNo.value) {
    ElMessage.warning('请先选择学生')
    return
  }
  if (fmt === 'pick') {
    openPicker(
      teacher ? `/export/student-grades/${encodeURIComponent(studentNo.value)}` : '/export/my-grades',
      teacher ? 'student-grades' : 'my-grades',
      { term: '' },
      teacher ? `成绩单-${studentNo.value}` : '我的成绩单'
    )
    return
  }
  exportingOne.value = true
  try {
    const name = teacher
      ? await downloadFile(
          `/export/student-grades/${encodeURIComponent(studentNo.value)}`,
          { term: '', fmt },
          `成绩单-${studentNo.value}.${fmt}`
        )
      : await downloadFile('/export/my-grades', { term: '', fmt }, `我的成绩单.${fmt}`)
    ElMessage.success(`已下载：${name}`)
  } catch {
    // 具体原因由 http 拦截器提示
  } finally {
    exportingOne.value = false
  }
}

async function exportClassGrades(fmt) {
  if (!className.value) {
    ElMessage.warning('请先选择班级')
    return
  }
  if (fmt === 'pick') {
    openPicker('/export/grades', 'grades', { class_name: className.value, term: '' },
      `班级成绩-${className.value}`)
    return
  }
  exportingClass.value = true
  try {
    const name = await downloadFile(
      '/export/grades',
      { class_name: className.value, term: '', fmt },
      `班级成绩-${className.value}.${fmt}`
    )
    ElMessage.success(`已下载：${name}`)
  } catch {
    // 具体原因由 http 拦截器提示
  } finally {
    exportingClass.value = false
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
      splitLine: { lineStyle: { color: '#eef0f5' } }
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
        lineStyle: { color: '#1951c3', width: 2 },
        itemStyle: { color: '#1951c3' }
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

// 学生板块把「学生档案 → 全班成绩」放在同一页，GradeReport 只挂载一次：
// 教师点了某个学生的「看成绩」只是改了 query，必须跟着 query 重新定位班级与人，
// 否则页面停在第一次进入时的那个班，白点一次。
watch(
  () => route.query.student_no,
  async (now, before) => {
    if (!isTeacher || String(now || '') === String(before || '')) return
    if (!now) return
    await loadClasses()
  }
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.caret {
  font-size: 10px;
  opacity: 0.6;
  margin-left: 2px;
}
/* 成绩单头部的下载按钮：靠右贴住汇总统计 */
.export-inline {
  margin-left: auto;
  align-self: flex-start;
}

.filter-card {
  padding: 16px 18px;
}

.filter-card :deep(.el-form-item) {
  margin-bottom: 10px;
}

.err {
  color: var(--qh-red);
  font-size: 13.5px;
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
  font-size: 14px;
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
  background: #f7f8fa;
}

.summary-stats span {
  font-size: 13.5px;
  color: var(--bento-mute);
}

.summary-stats b {
  font-size: 22px;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
  color: var(--bento-text);
  white-space: nowrap;
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
  font-size: 14px;
  line-height: 1.85;
  color: var(--bento-sub);
}

.note-meta {
  margin-top: 12px;
  font-size: 13.5px;
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
  background: #f7f8fa;
  font-size: 14px;
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
  font-size: 13.5px;
  color: var(--bento-mute);
}

.rank-card {
  display: flex;
  flex-direction: column;
  padding: 18px 20px 20px;
}

.rank-card .card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.class-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.class-stats div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: 14px;
  background: #f7f8fa;
}

.class-stats span {
  font-size: 13.5px;
  color: var(--bento-mute);
}

.class-stats b {
  font-size: 20px;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
  color: var(--bento-text);
  /* 「100 / 48.18」这类长值不许折成两行，否则四块指标高度不齐 */
  white-space: nowrap;
}

.rank-note {
  margin: 10px 0 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--bento-mute);
}

.is-top {
  color: #ea580c;
  font-weight: 650;
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

  .class-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .class-stats b {
    font-size: 18px;
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
