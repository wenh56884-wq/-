<template>
  <div class="page bento-page">
    <el-card shadow="never" class="filter-bar">
      <el-form inline @submit.prevent>
        <el-form-item label="班级">
          <el-select
            v-model="className"
            filterable
            placeholder="请选择班级"
            style="width: 200px"
            @change="loadReport"
          >
            <el-option v-for="k in classes" :key="k.class_name" :label="k.class_name" :value="k.class_name">
              <span>{{ k.class_name }}</span>
              <span class="option-note">{{ k.headcount }} 人</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="学期">
          <el-input v-model="term" placeholder="如 2025-2026-2" style="width: 160px" />
        </el-form-item>
        <el-form-item label="方向">
          <el-select v-model="intent" placeholder="全部方向" clearable style="width: 140px">
            <el-option v-for="it in INTENTS" :key="it" :label="it" :value="it" />
          </el-select>
        </el-form-item>
        <el-form-item label="档案样本">
          <el-select v-model="limit" style="width: 120px">
            <el-option v-for="n in LIMITS" :key="n" :label="`前 ${n} 人`" :value="n" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="loadReport">查询</el-button>
          <el-button @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <RouteHero
      tone="teacher"
      eyebrow="班级档案 · 十域数据"
      :title="`${report.class_name || '班级'} · 生涯规划全景档案`"
      desc="把成绩、预警、学业预测、岗位、面试、竞赛、测评、选课、招考、图谱十域数据编排进每位学生档案，班级摘要由确定性引擎聚合。"
      :stats="heroStats"
      style="margin-top: 16px"
    />

    <div v-if="report.class_summary" class="intent-bar">
      <span class="intent-bar-label">去向分布</span>
      <span
        v-for="item in intentItems"
        :key="item.key"
        class="intent-chip"
        :style="{ '--intent-color': item.color }"
      >
        {{ item.label }} <b>{{ item.value }}</b>
      </span>
      <span class="intent-bar-total">
        样本 {{ report.student_total }} 人 · 档案 {{ report.filtered_total }} 人
        · 引擎 {{ report.engine_version }} / 画像 {{ report.calc_version }}
      </span>
    </div>

    <el-alert
      v-if="report.note"
      class="note"
      type="info"
      :closable="false"
      show-icon
      :title="report.note"
    />

    <div v-if="report.class_summary" class="highlight-row">
      <el-card shadow="never" class="hl-card">
        <div class="card-title">成绩前列</div>
        <el-table :data="report.class_summary.grade_rank_top" size="small" border>
          <el-table-column label="名次" width="64">
            <template #default="{ row }">{{ row.rank }}</template>
          </el-table-column>
          <el-table-column prop="student_no" label="学号" width="120" />
          <el-table-column prop="name" label="姓名" min-width="90" />
          <el-table-column prop="gpa" label="加权均分" width="90" />
        </el-table>
        <el-empty v-if="!(report.class_summary.grade_rank_top || []).length"
          description="暂无成绩数据" :image-size="56" />
      </el-card>
      <el-card shadow="never" class="hl-card">
        <div class="card-title">全班岗位匹配前列</div>
        <el-table :data="report.class_summary.job_match_top" size="small" border>
          <el-table-column prop="title" label="岗位" min-width="130" />
          <el-table-column prop="company" label="单位" min-width="120" show-overflow-tooltip />
          <el-table-column prop="final_score" label="匹配分" width="80" />
          <el-table-column prop="recommended_by" label="被推荐人数" width="96" />
        </el-table>
        <el-empty v-if="!(report.class_summary.job_match_top || []).length"
          description="暂无岗位匹配数据" :image-size="56" />
      </el-card>
    </div>

    <div class="career-body">
      <el-card shadow="never" class="list-card">
        <div class="card-title">
          学生档案（{{ rows.length }} 人 / 样本 {{ report.student_total }} 人）
        </div>
        <el-skeleton :rows="6" animated v-if="firstLoading" />
        <template v-else>
          <el-table
            v-loading="loading"
            :data="rows"
            border
            stripe
            highlight-current-row
            height="540"
            @current-change="selectStudent"
          >
            <el-table-column prop="student_no" label="学号" width="120" />
            <el-table-column prop="name" label="姓名" min-width="90" />
            <el-table-column prop="grade" label="年级" width="80" />
            <el-table-column label="去向" width="80">
              <template #default="{ row }">
                <el-tag :type="intentType(row.intent)" effect="plain" size="small">
                  {{ row.intent || '未填' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="gpa" label="加权均分" width="96" sortable />
            <el-table-column label="预警" width="90">
              <template #default="{ row }">
                <el-tag :type="levelType(row.warning?.level)" effect="dark" size="small">
                  {{ levelText(row.warning?.level) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="direction" label="瞄准方向" min-width="120" show-overflow-tooltip />
          </el-table>
          <el-empty v-if="!loading && !rows.length" description="该方向下没有学生档案" />
        </template>
      </el-card>

      <el-card shadow="never" class="detail-card">
        <el-empty v-if="!active" description="先在左侧点一名学生，查看其十域生涯档案" />
        <template v-else>
          <div class="detail-head">
            <div>
              <span class="detail-name">{{ active.name || '—' }}</span>
              <span class="detail-no">{{ active.student_no }}</span>
              <el-tag :type="intentType(active.intent)" effect="plain" size="small">
                {{ active.intent || '未填' }}
              </el-tag>
              <el-tag type="info" effect="plain" size="small">{{ active.direction || '—' }}</el-tag>
            </div>
            <div class="detail-side">
              <div class="detail-source">画像版本 {{ report.calc_version }} · 引擎 {{ report.engine_version }}</div>
            </div>
          </div>

          <el-collapse v-model="activePanels" class="domain-collapse">
            <el-collapse-item title="成绩（加权均分 / 课程 / 挂科）" name="grades">
              <el-descriptions :column="4" border size="small" class="desc">
                <el-descriptions-item label="加权均分">{{ num(grades.summary?.weighted_avg) }}</el-descriptions-item>
                <el-descriptions-item label="平均分">{{ num(grades.summary?.avg_score) }}</el-descriptions-item>
                <el-descriptions-item label="课程数">{{ grades.summary?.course_count ?? '-' }}</el-descriptions-item>
                <el-descriptions-item label="挂科门次">{{ grades.summary?.failed_count ?? '-' }}</el-descriptions-item>
                <el-descriptions-item label="总学分">{{ grades.summary?.credits ?? '-' }}</el-descriptions-item>
                <el-descriptions-item label="学期数">{{ grades.summary?.term_count ?? '-' }}</el-descriptions-item>
              </el-descriptions>
              <el-table :data="courseRows" size="small" border class="sub-table">
                <el-table-column prop="term" label="学期" width="130" />
                <el-table-column prop="course_name" label="课程" min-width="140" />
                <el-table-column prop="score" label="成绩" width="80" />
                <el-table-column prop="credit" label="学分" width="70" />
              </el-table>
              <el-empty v-if="!courseRows.length" description="暂无成绩记录" :image-size="48" />
            </el-collapse-item>

            <el-collapse-item title="学业预警（等级 / 风险分 / 归因）" name="warning">
              <el-descriptions :column="3" border size="small" class="desc">
                <el-descriptions-item label="预警等级">
                  <el-tag :type="levelType(active.warning?.level)" effect="dark" size="small">
                    {{ levelText(active.warning?.level) }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="风险分">{{ num(active.warning?.risk_score) }}</el-descriptions-item>
                <el-descriptions-item label="可用指标">{{ active.warning?.coverage ?? '-' }} 项</el-descriptions-item>
                <el-descriptions-item label="缺失项" :span="3">
                  <span v-if="!(active.warning?.missing || []).length" class="muted">无</span>
                  <span v-else class="missing">{{ active.warning.missing.join('、') }}</span>
                </el-descriptions-item>
              </el-descriptions>
              <div class="reason-line">
                <el-tag v-for="(r, i) in active.warning?.reasons || []" :key="i" type="danger" effect="plain">
                  {{ r }}
                </el-tag>
                <span v-if="!(active.warning?.reasons || []).length" class="muted">本学期没有触发项</span>
              </div>
            </el-collapse-item>

            <el-collapse-item title="学业预测（下学期绩点 / 风险趋势）" name="forecast">
              <el-empty v-if="!active.forecast?.available" description="历史学期不足，预测不可用" :image-size="48" />
              <template v-else>
                <el-descriptions :column="3" border size="small" class="desc">
                  <el-descriptions-item label="预测学期">{{ active.forecast.next_term || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="预测绩点">{{ num(active.forecast.gpa_forecast?.predicted) }}</el-descriptions-item>
                  <el-descriptions-item label="预测挂科">{{ active.forecast.fail_forecast?.predicted ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="趋势">{{ active.forecast.gpa_forecast?.trend || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="置信度">{{ active.forecast.gpa_forecast?.confidence || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="定级">{{ active.forecast.level || '-' }}</el-descriptions-item>
                </el-descriptions>
              </template>
            </el-collapse-item>

            <el-collapse-item :title="`岗位推荐（${(active.recommendations?.items || []).length} 个匹配岗位）`" name="recommendations">
              <el-empty v-if="!(active.recommendations?.items || []).length" description="暂无匹配岗位" :image-size="48" />
              <div v-for="job in active.recommendations.items" :key="job.job_id" class="job-card">
                <div class="job-head">
                  <b>{{ job.title || '—' }}</b>
                  <span class="job-score">匹配分 {{ num(job.final_score) }}</span>
                </div>
                <div class="job-meta">
                  {{ job.company || '—' }} · {{ job.city || '—' }} · {{ job.direction || '—' }}
                  <template v-if="job.salary_min"> · {{ job.salary_min }}-{{ job.salary_max }}</template>
                </div>
                <div v-if="(job.hit_items || []).length" class="job-line">
                  <span class="job-label">命中</span>
                  <el-tag v-for="(h, i) in job.hit_items" :key="i" type="success" effect="plain" size="small">{{ h }}</el-tag>
                </div>
                <div v-if="(job.gap_items || []).length" class="job-line">
                  <span class="job-label">差距</span>
                  <el-tag v-for="(g, i) in job.gap_items" :key="i" type="warning" effect="plain" size="small">{{ g }}</el-tag>
                </div>
              </div>
            </el-collapse-item>

            <el-collapse-item title="模拟面试（会话 / 出题大纲）" name="interview">
              <el-empty v-if="!(active.interview?.sessions || []).length && !(active.interview?.outline || []).length"
                description="暂无面试数据" :image-size="48" />
              <template v-if="(active.interview?.sessions || []).length">
                <div class="card-title">历史会话</div>
                <el-table :data="active.interview.sessions" size="small" border class="sub-table">
                  <el-table-column prop="job_title" label="岗位" min-width="110" />
                  <el-table-column prop="status" label="状态" width="90" />
                  <el-table-column prop="cur_round" label="轮次" width="70" />
                  <el-table-column prop="total" label="总分" width="80" />
                  <el-table-column prop="created_at" label="创建时间" min-width="150" />
                </el-table>
              </template>
              <template v-if="(active.interview?.outline || []).length">
                <div class="card-title" style="margin-top: 12px">出题大纲</div>
                <ol class="outline-list">
                  <li v-for="q in active.interview.outline" :key="q.round">
                    <span class="outline-round">第 {{ q.round }} 轮 · {{ q.type }}</span>
                    <span class="outline-q">{{ q.question }}</span>
                    <span class="outline-src">来源 {{ q.source?.kind }}</span>
                  </li>
                </ol>
              </template>
            </el-collapse-item>

            <el-collapse-item :title="`竞赛推荐（${(active.competitions?.items || []).length} 项）`" name="competitions">
              <el-empty v-if="!(active.competitions?.items || []).length" description="暂无推荐赛事" :image-size="48" />
              <el-table :data="active.competitions.items" size="small" border class="sub-table">
                <el-table-column prop="name" label="赛事" min-width="150" show-overflow-tooltip />
                <el-table-column prop="category" label="类别" width="90" />
                <el-table-column prop="org_unit" label="组织单位" min-width="110" show-overflow-tooltip />
                <el-table-column prop="score" label="匹配分" width="80" />
              </el-table>
              <div v-for="item in active.competitions.items" :key="item.competition_id" class="job-line">
                <el-tag size="small" effect="plain">{{ item.match_reason }}</el-tag>
              </div>
            </el-collapse-item>

            <el-collapse-item title="职业测评（总分 / 维度 / 复合能力）" name="assessment">
              <el-empty v-if="!active.assessment?.total_score && !(active.assessment?.dimension_scores || {}).length"
                description="暂无测评数据" :image-size="48" />
              <template v-else>
                <el-descriptions :column="2" border size="small" class="desc">
                  <el-descriptions-item label="总分">{{ num(active.assessment.total_score) }} / {{ active.assessment.total_max ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="测评时间">{{ active.assessment.create_time || '-' }}</el-descriptions-item>
                </el-descriptions>
                <div v-if="(active.assessment.dimension_scores || {}).length" class="card-title">维度得分</div>
                <div class="dim-line">
                  <el-tag v-for="(v, k) in active.assessment.dimension_scores" :key="k" effect="plain" size="small">
                    {{ k }} {{ Number(v).toFixed(2) }}
                  </el-tag>
                </div>
              </template>
            </el-collapse-item>

            <el-collapse-item title="选课建议（技能缺口 → 候选课）" name="elective">
              <el-descriptions :column="2" border size="small" class="desc">
                <el-descriptions-item label="技能覆盖率">{{ pct(active.elective?.coverage) }}</el-descriptions-item>
                <el-descriptions-item label="目标岗位">{{ active.elective?.target?.title || active.elective?.target?.job_title || '-' }}</el-descriptions-item>
                <el-descriptions-item label="要求技能" :span="2">
                  <span v-if="!(active.elective?.required || []).length" class="muted">无</span>
                  <span v-else>{{ active.elective.required.join('、') }}</span>
                </el-descriptions-item>
                <el-descriptions-item label="技能缺口" :span="2">
                  <span v-if="!(active.elective?.skill_gaps || []).length" class="muted">无</span>
                  <span v-else class="missing">{{ active.elective.skill_gaps.join('、') }}</span>
                </el-descriptions-item>
              </el-descriptions>
              <el-table :data="active.elective?.recommendations || []" size="small" border class="sub-table">
                <el-table-column prop="course_name" label="候选课" min-width="140" />
                <el-table-column prop="reason" label="理由" min-width="180" show-overflow-tooltip />
              </el-table>
              <el-empty v-if="!(active.elective?.recommendations || []).length" description="暂无需补课或无可推荐课程" :image-size="48" />
              <div v-if="active.elective?.note" class="muted note-text">{{ active.elective.note }}</div>
            </el-collapse-item>

            <el-collapse-item :title="`招考信息（${(active.exam || []).length} 条）`" name="exam">
              <el-empty v-if="!(active.exam || []).length" description="该去向暂无匹配招考公告" :image-size="48" />
              <el-table :data="active.exam" size="small" border class="sub-table">
                <el-table-column prop="title" label="公告" min-width="180" show-overflow-tooltip />
                <el-table-column prop="org_name" label="招录单位" min-width="120" show-overflow-tooltip />
                <el-table-column prop="region" label="地区" width="90" />
                <el-table-column prop="headcount" label="招录" width="70" />
                <el-table-column prop="signup_end" label="报名截止" min-width="120" />
              </el-table>
            </el-collapse-item>

            <el-collapse-item :title="`知识图谱（专业 ${active.kg?.major || '—'}）`" name="kg">
              <el-empty v-if="!(active.kg?.skills || []).length" description="该专业暂无图谱技能数据" :image-size="48" />
              <el-descriptions :column="2" border size="small" class="desc">
                <el-descriptions-item label="关联技能数">{{ active.kg?.total ?? 0 }} 项</el-descriptions-item>
                <el-descriptions-item label="关联课程数">{{ active.kg?.course_cnt ?? 0 }} 门</el-descriptions-item>
              </el-descriptions>
              <el-table :data="active.kg?.skills || []" size="small" border class="sub-table">
                <el-table-column prop="skill" label="技能" min-width="140" />
                <el-table-column prop="total" label="岗位数" width="90" />
              </el-table>
            </el-collapse-item>
          </el-collapse>
        </template>
      </el-card>
    </div>
  </div>
</template>

<script setup>
// 教师端「生涯规划」：班级维度全域数据全景。
// 数值全部来自后端 engine（铁律 1），前端只做展示，不重算、不生成任何数值。

import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'

import http from '../api/http'
import RouteHero from '../components/brand/RouteHero.vue'

const INTENTS = ['考公', '考研', '考编', '就业']
const LIMITS = [10, 20, 30, 60]
const LEVEL_TEXT = { red: '红色', orange: '橙色', yellow: '黄色', none: '正常', unknown: '数据不足' }
const LEVEL_TYPE = { red: 'danger', orange: 'warning', yellow: 'warning', none: 'success', unknown: 'info' }
const INTENT_TYPE = { 考公: 'danger', 考研: 'warning', 考编: 'success', 就业: 'primary' }
const INTENT_META = [
  { key: '考公', label: '考公', color: '#dc2626' },
  { key: '考研', label: '考研', color: '#d97706' },
  { key: '考编', label: '考编', color: '#16a34a' },
  { key: '就业', label: '就业', color: '#1951c3' },
  { key: '未选', label: '未选', color: '#9aa1ad' }
]

const className = ref(localStorage.getItem('qh_last_class') || '')
const term = ref('2025-2026-2')
const intent = ref('')
const limit = ref(20)
const classes = ref([])
const report = ref({})
const loading = ref(false)
const firstLoading = ref(false)
const activeNo = ref('')
const activePanels = ref(['grades', 'recommendations'])

const rows = computed(() => report.value.students || [])
const active = computed(() =>
  rows.value.find((row) => row.student_no === activeNo.value) || null)
const grades = computed(() => active.value?.grades || {})

const courseRows = computed(() => {
  const out = []
  for (const year of grades.value.years || []) {
    for (const t of year.terms || []) {
      for (const c of t.courses || []) {
        out.push({
          term: t.term || year.year || '',
          course_name: c.course_name || '',
          score: c.score ?? '-',
          credit: c.credit ?? '-'
        })
      }
    }
  }
  return out
})

const intentItems = computed(() => {
  const dist = report.value.class_summary?.intent_distribution || {}
  return INTENT_META.map((item) => ({ ...item, value: Number(dist[item.key] || 0) }))
})

const heroStats = computed(() => {
  const s = report.value.class_summary || {}
  return [
    { label: '班级学生', value: s.student_total ?? 0, tone: 'unknown' },
    { label: '预警人数', value: s.warning_count ?? 0, tone: 'red' },
    { label: '预警率', value: pct(s.warning_rate), suffix: '', tone: 'orange' },
    { label: '平均加权均分', value: num(s.avg_grade) },
    { label: '岗位匹配数', value: (s.job_match_top || []).length, tone: 'good' },
    { label: '班级风险', value: s.risk_level || '—', tone: s.risk_level === '高' ? 'red' : (s.risk_level === '中' ? 'orange' : 'good') }
  ]
})

function levelText(level) {
  return LEVEL_TEXT[level] || level || '-'
}
function levelType(level) {
  return LEVEL_TYPE[level] || 'info'
}
function intentType(intent) {
  return INTENT_TYPE[intent] ?? 'info'
}
function num(v) {
  return v === null || v === undefined ? '-' : v
}
function pct(v) {
  return v === null || v === undefined ? '-' : `${(Number(v) * 100).toFixed(1)}%`
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
  loading.value = true
  try {
    const { data } = await http.get('/teacher/career-search', {
      params: {
        class_name: klass,
        term: term.value,
        intent: intent.value || undefined,
        limit: limit.value
      },
      // 逐生全域编排耗时较长（约 40s+），单独放宽超时，避免被全局 30s 掐断
      timeout: 150000
    })
    report.value = data || {}
    // 选中的学生被方向过滤掉时自动清空右侧
    if (activeNo.value && !rows.value.some((row) => row.student_no === activeNo.value)) {
      activeNo.value = ''
    }
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '生涯档案加载失败')
    report.value = {}
  } finally {
    loading.value = false
    firstLoading.value = false
  }
}

function reset() {
  intent.value = ''
  limit.value = 20
  term.value = '2025-2026-2'
  activeNo.value = ''
  report.value = {}
  loadReport()
}

function selectStudent(row) {
  const no = row?.student_no
  if (!no || no === activeNo.value) return
  activeNo.value = no
}

onMounted(async () => {
  firstLoading.value = true
  await loadDirectory()
  await loadReport()
})

</script>

<style scoped>
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

.intent-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 16px;
  padding: 12px 16px;
  background: var(--qh-surface, #fff);
  border: 1px solid #eef0f5;
  border-radius: 16px;
  font-size: 13px;
}

.intent-bar-label {
  color: var(--qh-text-mute, #5f6672);
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
  color: var(--qh-text-mute, #5f6672);
  font-size: 12px;
}

.note {
  margin-top: 12px;
}

.highlight-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 16px;
}

.hl-card :deep(.el-card__body) {
  padding: 12px 14px;
}

.career-body {
  display: grid;
  grid-template-columns: minmax(360px, 7fr) minmax(420px, 9fr);
  gap: 16px;
  margin-top: 16px;
}

.card-title {
  font-weight: 600;
  margin-bottom: 10px;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
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

.desc {
  margin-bottom: 10px;
}

.muted {
  font-size: 13px;
  color: #5f6672;
}

.missing {
  color: var(--qh-orange);
}

.note-text {
  margin-top: 8px;
  line-height: 1.6;
}

.sub-table {
  margin-top: 8px;
}

.reason-line,
.dim-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 6px 0;
}

.job-card {
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid #eef0f5;
  border-radius: 12px;
  background: #fafbfd;
}

.job-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.job-score {
  color: #1951c3;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.job-meta {
  color: #5f6672;
  font-size: 12.5px;
  margin-top: 4px;
}

.job-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.job-label {
  font-size: 12px;
  color: #5f6672;
}

.outline-list {
  margin: 6px 0 0;
  padding-left: 0;
  list-style: none;
}

.outline-list li {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
  padding: 8px 0;
  border-bottom: 1px dashed #eef0f5;
}

.outline-round {
  font-size: 12px;
  color: #5f6672;
  white-space: nowrap;
}

.outline-q {
  flex: 1 1 240px;
}

.outline-src {
  font-size: 12px;
  color: #9aa1ad;
}

@media (max-width: 1100px) {
  .career-body,
  .highlight-row {
    grid-template-columns: 1fr;
  }
}
</style>
