<template>
  <div class="page bento-page">
    <el-alert class="trust-bar" type="success" :closable="false" show-icon
      title="评分与差距由确定性引擎计算；点评中的「引文」逐字校验，模型不可编造" />

    <el-tabs v-model="tab" class="iv-tabs">
      <!-- ============ 简历 ============ -->
      <el-tab-pane label="我的简历" name="resume">
        <div class="bento-grid">
        <el-card shadow="never" class="block-card bento-span-2 bento-row-2">
          <template #header><span class="card-title">录入简历</span></template>
          <el-radio-group v-model="entryMode">
            <el-radio-button value="paste">粘贴文本</el-radio-button>
            <el-radio-button value="upload">上传 docx / txt</el-radio-button>
            <el-radio-button value="form">问卷自填</el-radio-button>
          </el-radio-group>

          <template v-if="entryMode === 'paste'">
            <el-input v-model="pasteText" type="textarea" :rows="10" class="mt8"
              placeholder="粘贴简历全文（含 教育经历 / 技能证书 / 实践经历 各小节效果最佳）" />
            <el-button type="primary" class="mt8" :loading="parsing" :disabled="!pasteText.trim()"
              @click="parseText">解析</el-button>
          </template>

          <template v-else-if="entryMode === 'upload'">
            <input type="file" accept=".docx,.txt" class="mt8" @change="onFile" />
            <div class="muted mt8">其他格式（pdf 等）请复制内容后用「粘贴文本」</div>
          </template>

          <template v-else>
            <el-form label-width="90px" class="mt8">
              <el-form-item label="自我评价"><el-input v-model="form.self" /></el-form-item>
              <el-form-item label="意向方向"><el-input v-model="form.intent" placeholder="如 数据分析" /></el-form-item>
              <el-form-item label="教育经历">
                <el-input v-model="form.edu" placeholder="学校｜专业｜2023.09-2027.06" />
              </el-form-item>
              <el-form-item label="技能/证书">
                <el-input v-model="form.skills" placeholder="Python、MySQL、CET-6 568（顿号分隔）" />
              </el-form-item>
              <el-form-item label="实践经历">
                <el-input v-model="form.exp" type="textarea" :rows="3"
                  placeholder="项目名｜负责后端开发，完成12个接口，服务500名学生" />
              </el-form-item>
            </el-form>
            <el-button type="primary" @click="saveForm">保存简历</el-button>
          </template>
        </el-card>

        <el-card v-if="parsed" shadow="never" class="block-card bento-span-2">
          <template #header>
            <div class="head-row"><span class="card-title">解析结果（确认后保存）</span>
              <el-button type="primary" size="small" :loading="saving" @click="saveParsed">保存为当前简历</el-button>
            </div>
          </template>
          <div class="kv"><span class="k">教育</span>{{ parsed.educations.map(e => e.school + '｜' + (e.major || '')).join('；') || '（无）' }}</div>
          <div class="kv"><span class="k">技能</span>{{ parsed.skills.join('、') || '（无）' }}</div>
          <div class="kv"><span class="k">证书</span>{{ parsed.certs.map(c => c.name).join('、') || '（无）' }}</div>
          <div class="kv"><span class="k">经历</span>
            <div v-for="(e, i) in parsed.experiences" :key="i" class="exp-item">{{ e.name }}</div>
            <span v-if="!parsed.experiences.length">（无）</span>
          </div>
        </el-card>

        <el-card v-if="resume" shadow="never" class="block-card bento-span-2">
          <template #header>
            <div class="head-row"><span class="card-title">当前简历（v{{ resume['版本号'] }}，{{ resume['来源'] === 'upload' ? '上传' : '自填' }}）</span>
              <el-button size="small" :loading="diagLoading" @click="runDiagnosis">简历诊断</el-button>
            </div>
          </template>
          <div class="kv"><span class="k">教育</span>{{ (resume.educations || []).map(e => e.school + '｜' + (e.major || '')).join('；') || '（无）' }}</div>
          <div class="kv"><span class="k">技能</span>{{ (resume.skills || []).join('、') || '（无）' }}</div>
          <div class="kv"><span class="k">证书</span>{{ (resume.certs || []).map(c => c.name + (c.level ? ' ' + c.level : '')).join('、') || '（无）' }}</div>
          <div class="kv"><span class="k">经历</span>
            <div v-for="(e, i) in resume.experiences || []" :key="i" class="exp-item">{{ e.name }}</div>
            <span v-if="!(resume.experiences || []).length">（无）</span>
          </div>
        </el-card>

        <el-card v-if="diagnosis" shadow="never" class="block-card bento-span-2">
          <template #header><span class="card-title">简历诊断（{{ diagnosis.issues.length }} 个问题）</span></template>
          <div v-for="(iss, i) in diagnosis.issues" :key="i" class="diag-item">
            <el-tag size="small" type="warning">{{ issueLabel(iss.kind) }}</el-tag>
            <b>{{ iss.where }}</b>：{{ iss.problem }}
            <div class="rewrite">{{ iss.rewrite }}</div>
          </div>
          <div v-if="!diagnosis.issues.length" class="muted">未发现明显问题</div>
        </el-card>

        <el-card shadow="never" class="block-card bento-span-2">
          <template #header><span class="card-title">怎么练</span></template>
          <ol class="howto">
            <li><b>录入简历</b>：粘贴 / 上传 / 问卷任选，解析后确认保存。</li>
            <li><b>选择岗位</b>：到「面试演练」选目标岗位开局。</li>
            <li><b>深度模拟面试</b>：逐题作答、逐题点评（引文逐字校验），答浅了会被追问。</li>
            <li><b>看评估报告</b>：维度分 + 核心问题 + 三步改进计划，照着练下一场就涨分。</li>
          </ol>
        </el-card>
        </div>
      </el-tab-pane>

      <!-- ============ 面试 ============ -->
      <el-tab-pane label="面试演练" name="interview">
        <div class="bento-grid">
        <el-card v-if="!session && !report" shadow="never" class="block-card bento-span-2">
          <template #header>
            <div class="head-row">
              <span class="card-title">选择目标岗位开局</span>
              <el-tag size="small" type="info" effect="plain">
                全国岗位池 {{ jobTotal || '…' }} 条
              </el-tag>
            </div>
          </template>
          <div class="job-filters">
            <el-input v-model="jobKeyword" placeholder="搜索岗位 / 技能 / 企业" clearable
              class="job-kw" @keyup.enter="loadJobs" @clear="loadJobs" />
            <el-select v-model="jobIndustry" placeholder="行业" clearable filterable
              class="job-filter" @change="loadJobs">
              <el-option v-for="i in facets.industries" :key="i.name" :value="i.name"
                :label="`${i.name} (${i.count})`" />
            </el-select>
            <el-select v-model="jobCity" placeholder="城市" clearable filterable
              class="job-filter" @change="loadJobs">
              <el-option v-for="c in facets.cities" :key="c.name" :value="c.name"
                :label="`${c.name} (${c.count})`" />
            </el-select>
            <el-button :loading="jobLoading" @click="loadJobs">搜索</el-button>
          </div>
          <el-select v-model="jobId" filterable placeholder="选择岗位（可先按条件过滤）"
            class="job-select" :loading="jobLoading">
            <el-option v-for="j in jobs" :key="j.id" :value="j.id"
              :label="`${j.title} · ${j.company || ''} · ${j.city || ''}`" />
          </el-select>
          <el-button type="primary" class="ml8" :loading="starting" :disabled="!jobId || !resume"
            @click="startInterview">开始模拟面试</el-button>
          <div v-if="!resume" class="muted mt8">还没有简历：请先在「我的简历」页录入</div>
          <div class="muted mt8">
            默认 6 轮：动机 → 专业 → 项目 → 情景 → 抗压 → 反问（按简历证据自动裁剪）；
            答得浅或漏考点时，面试官会追加 1–2 道追问
          </div>
        </el-card>

        <el-card v-if="session && !report" shadow="never" class="block-card bento-span-2 bento-row-2">
          <template #header>
            <div class="head-row">
              <span class="card-title">
                第 {{ session.round }} / {{ session.total }} 题 · {{ session.label }}
                <el-tag v-if="session.isProbe" size="small" type="warning" effect="dark"
                  class="probe-tag">追问</el-tag>
              </span>
              <el-tag size="small">{{ jobTitle }}</el-tag>
            </div>
          </template>
          <el-progress :percentage="Math.round(((session.round - 1) / session.total) * 100)"
            :stroke-width="6" :show-text="false" class="iv-progress" />
          <div class="question">{{ session.question }}</div>
          <div v-if="session.source" class="q-source">
            <template v-if="session.source.kind === 'bank'">
              <el-tag size="small" type="success" effect="plain">题库命中</el-tag>
              <span class="src-txt">
                本题出自
                <a :href="session.source.url" target="_blank" rel="noopener">{{ session.source.name }}</a>
                · {{ session.source.family_label || session.source.family }}
                <template v-if="session.source.matched_by && session.source.matched_by.length">
                  · 命中 {{ session.source.matched_by.join('、') }}
                </template>
              </span>
            </template>
            <template v-else>
              <el-tag size="small" type="info" effect="plain">模板出题</el-tag>
              <span class="src-txt">该行业暂无题库覆盖，按简历证据套用通用问法</span>
            </template>
          </div>
          <el-input v-model="answerText" type="textarea" :rows="5"
            placeholder="建议用 STAR 结构回答：背景 → 目标 → 行动 → 结果（带数字）" />
          <div class="mt8 head-row">
            <el-button type="primary" :loading="answering" @click="submitAnswer(true)">提交回答</el-button>
            <el-button :loading="answering" @click="submitAnswer(false)">跳过本题</el-button>
          </div>
        </el-card>

        <el-card v-if="lastComment && !report" shadow="never" class="block-card bento-span-2">
          <template #header>
            <div class="head-row"><span class="card-title">上一题点评</span>
              <el-tag size="small" :type="lastComment.version === 'comment-fallback-v1' ? 'info' : 'success'">
                {{ lastComment.version === 'comment-fallback-v1' ? '模板点评' : 'AI 点评·引文已校验' }}
              </el-tag>
              <el-tag v-if="lastComment.score != null" size="small" type="warning">{{ lastComment.score }} 分</el-tag>
            </div>
          </template>
          <div class="comment">{{ lastComment.text }}</div>
        </el-card>

        <el-card v-if="report" shadow="never" class="block-card bento-span-4 report-card">
          <template #header>
            <div class="head-row"><span class="card-title">面试评估报告</span>
              <el-tag size="small" type="info" effect="plain">引擎 {{ evaluation.engine_version || 'interview-v2' }} · 全部为确定性实算</el-tag>
              <el-button size="small" @click="resetInterview">再来一场</el-button>
            </div>
          </template>

          <!-- 顶部：总分 + 概况 + 维度分 -->
          <div class="report-hero">
            <div class="score-ring" :class="scoreClass">
              <svg viewBox="0 0 120 120">
                <circle cx="60" cy="60" r="52" class="ring-bg" />
                <circle cx="60" cy="60" r="52" class="ring-fg"
                  :stroke-dasharray="`${(evaluation.total || 0) / 100 * 326.7} 326.7`" />
              </svg>
              <div class="ring-text">
                <b>{{ evaluation.total ?? '—' }}</b><span>总分</span>
              </div>
            </div>
            <div class="hero-facts">
              <div class="fact-row">
                <span class="fact">已答 <b>{{ evaluation.answered }}</b> 题</span>
                <span class="fact warn" v-if="evaluation.skipped">跳过 <b>{{ evaluation.skipped }}</b> 题</span>
                <span class="fact" v-if="evaluation.probes">追问 <b>{{ evaluation.probes }}</b> 道</span>
                <span class="fact" v-if="jobTitle">{{ jobTitle }}</span>
              </div>
              <div class="dim-bars">
                <div v-for="d in evaluation.dimensions" :key="d.type" class="dim-row">
                  <span class="dim-label">{{ d.label }}</span>
                  <div class="dim-track">
                    <div class="dim-fill" :class="dimClass(d.avg)"
                      :style="{ width: (d.avg || 0) + '%' }"></div>
                  </div>
                  <span class="dim-val">{{ d.avg ?? '未答' }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 核心问题 -->
          <div v-if="evaluation.core_problems && evaluation.core_problems.length" class="report-sec">
            <div class="sec-title">核心问题 <span class="muted">（按严重度排序，全部由评分明细机械归因）</span></div>
            <div v-for="(p, i) in evaluation.core_problems" :key="i" class="problem-item">
              <el-tag size="small" :type="p.severity === 'high' ? 'danger' : p.severity === 'medium' ? 'warning' : 'info'"
                effect="dark">{{ p.severity === 'high' ? '高' : p.severity === 'medium' ? '中' : '低' }}</el-tag>
              <span class="problem-dim">{{ p.dimension }}</span>
              <span class="problem-txt">{{ p.problem }}</span>
              <div class="problem-action">→ {{ p.action }}</div>
            </div>
          </div>

          <!-- 改进计划 -->
          <div v-if="evaluation.improvement_plan && evaluation.improvement_plan.length" class="report-sec">
            <div class="sec-title">改进计划</div>
            <div class="plan-row">
              <div v-for="(s, i) in evaluation.improvement_plan" :key="i" class="plan-card">
                <div class="plan-when">{{ s.when }}</div>
                <div class="plan-focus">{{ s.focus }}</div>
                <div class="plan-action">{{ s.action }}</div>
              </div>
            </div>
          </div>

          <!-- 逐题复盘 -->
          <div class="report-sec">
            <div class="sec-title">逐题复盘 <span class="muted">（点评引文已逐字校验；追问以 ⚡ 标记）</span></div>
            <div v-for="q in evaluation.per_question" :key="q.round" class="qreview"
              :class="{ probe: q.is_probe, skipped: !q.answered }">
              <div class="qreview-head">
                <span class="qreview-round">第 {{ q.round }} 题 <template v-if="q.is_probe">⚡追问</template></span>
                <el-tag size="small" effect="plain">{{ q.label }}</el-tag>
                <el-tag size="small" :type="scoreTagType(q.score)">
                  {{ q.score != null ? q.score + ' 分' : '未作答' }}
                </el-tag>
              </div>
              <div class="qreview-question">{{ q.question }}</div>
              <div v-if="q.comment" class="qreview-comment">{{ q.comment }}</div>
              <div v-if="q.keyword_missed && q.keyword_missed.length" class="qreview-tags">
                <span class="tag-muted">漏掉考点：</span>
                <el-tag v-for="k in q.keyword_missed" :key="k" size="small" type="warning" effect="plain">{{ k }}</el-tag>
              </div>
              <div v-if="q.keyword_hits && q.keyword_hits.length" class="qreview-tags">
                <span class="tag-muted">命中：</span>
                <el-tag v-for="k in q.keyword_hits" :key="k" size="small" type="success" effect="plain">{{ k }}</el-tag>
              </div>
            </div>
          </div>

          <!-- 强项与原文 -->
          <el-collapse class="mt8">
            <el-collapse-item title="报告原文（可复制）" name="raw">
              <pre class="report">{{ report.report }}</pre>
            </el-collapse-item>
          </el-collapse>

          <div v-if="reportSources.length" class="mt8">
            <div class="muted">本场题目出处（每道题都能回到来源页面核对）</div>
            <el-table :data="reportSources" size="small" class="mt8">
              <el-table-column prop="round" label="轮次" width="70" />
              <el-table-column label="题型" width="120">
                <template #default="{ row }">
                  {{ row.label }}
                  <el-tag v-if="row.is_probe" size="small" type="warning" effect="plain">追问</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="来源" width="140" />
              <el-table-column prop="question" label="题目" min-width="240" show-overflow-tooltip />
              <el-table-column label="链接" width="90">
                <template #default="{ row }">
                  <a v-if="row.url" :href="row.url" target="_blank" rel="noopener">查看</a>
                  <span v-else class="muted">模板</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>

        <el-card shadow="never" class="block-card bento-span-4">
          <template #header><span class="card-title">历史场次</span></template>
          <el-table :data="history" size="small" @row-click="openHistory">
            <el-table-column prop="编号" label="场次" width="80" />
            <el-table-column prop="岗位名称" label="岗位" min-width="180" show-overflow-tooltip />
            <el-table-column prop="状态" label="状态" width="90" />
            <el-table-column prop="总分" label="总分" width="80" />
            <el-table-column prop="当前轮次" label="进度" width="80">
              <template #default="{ row }">{{ row['当前轮次'] }}/{{ row['最大轮次'] }}</template>
            </el-table-column>
            <el-table-column prop="创建时间" label="时间" width="170" />
          </el-table>
        </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api/http'

const tab = ref('resume')
const entryMode = ref('paste')
const pasteText = ref('')
const parsed = ref(null)
const saving = ref(false)
const parsing = ref(false)
const resume = ref(null)
const diagnosis = ref(null)
const diagLoading = ref(false)
const form = ref({ self: '', intent: '', edu: '', skills: '', exp: '' })

const jobs = ref([])
const jobId = ref(null)
const jobPool = ref('national')
const jobTotal = ref(0)
const jobKeyword = ref('')
const jobCity = ref('')
const jobIndustry = ref('')
const jobLoading = ref(false)
const facets = ref({ industries: [], cities: [] })
const session = ref(null)
const jobTitle = ref('')
const answerText = ref('')
const answering = ref(false)
const starting = ref(false)
const lastComment = ref(null)
const report = ref(null)
const evaluation = ref({})
const history = ref([])

// 报告配色：分数段语义色（复用评分口径：<60 待提升 / 60-75 合格 / >=75 强项）
const scoreClass = computed(() => {
  const t = evaluation.value.total
  return t == null ? '' : t >= 75 ? 'good' : t >= 60 ? 'mid' : 'low'
})
const dimClass = (v) => (v == null ? '' : v >= 75 ? 'good' : v >= 60 ? 'mid' : 'low')
const scoreTagType = (s) => (s == null ? 'info' : s >= 75 ? 'success' : s >= 60 ? 'warning' : 'danger')

const ISSUE_LABELS = {
  quantify: '缺量化', verb: '动词开头', length: '过长', missing: '缺失',
  alignment: '岗位对齐'
}
const issueLabel = (k) => ISSUE_LABELS[k] || k

const TYPE_LABELS = {
  motivation: '动机匹配', major: '专业基础', project: '项目深挖',
  scenario: '情景模拟', stress: '抗压应对', counter: '反问环节'
}
const labelOf = (t) => TYPE_LABELS[t] || t

// 报告页的题目出处表：题库题给链接，模板题明确标注，不含糊
const reportSources = computed(() => (report.value && report.value.sources) || [])

async function loadResume() {
  const { data } = await http.get('/interview/resume/me')
  resume.value = data.resume
}

async function parseText() {
  parsing.value = true
  try {
    const { data } = await http.post('/interview/resume/parse', { text: pasteText.value })
    parsed.value = data.parsed
  } finally {
    parsing.value = false
  }
}

async function onFile(ev) {
  const file = ev.target.files[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  parsing.value = true
  try {
    const { data } = await http.post('/interview/resume/upload', fd,
      { headers: { 'Content-Type': 'multipart/form-data' } })
    parsed.value = data.parsed
    ElMessage.success('解析成功，请确认后保存')
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    parsing.value = false
  }
}

async function saveParsed() {
  saving.value = true
  try {
    const p = parsed.value
    const skills = (p.skills || []).map((s) => ({ type: 'skill', name: s }))
    const certs = (p.certs || []).map((c) => ({ type: 'cert', name: c.name, level: c.level }))
    const exps = (p.experiences || []).map((e) => ({
      type: e.type || 'project', name: e.name, desc: e.desc || e.name, dates: e.dates
    }))
    const edus = (p.educations || []).map((e) => ({
      school: e.school, major: e.major, dates: e.dates
    }))
    await http.post('/interview/resume', {
      self_eval: p.self, educations: edus, skills: [...skills, ...certs], experiences: exps,
      raw_text: pasteText.value || null
    })
    ElMessage.success('简历已保存')
    parsed.value = null
    await loadResume()
  } finally {
    saving.value = false
  }
}

async function saveForm() {
  saving.value = true
  try {
    const f = form.value
    const exp = f.exp ? f.exp.split('\n').filter(Boolean).map((line) => ({
      type: /实习/.test(line) ? 'intern' : /竞赛|比赛/.test(line) ? 'contest' : 'project',
      name: line.split('｜')[0], desc: line
    })) : []
    const skills = f.skills.split('、').map((s) => s.trim()).filter(Boolean)
      .map((s) => (/CET|证|等级/.test(s) ? { type: 'cert', name: s } : { type: 'skill', name: s }))
    const edu = f.edu ? f.edu.split('｜') : []
    await http.post('/interview/resume', {
      self_eval: f.self || null, intent: f.intent || null,
      educations: edu.length ? [{ school: edu[0], major: edu[1] || null, dates: edu[2] || null }] : [],
      skills, experiences: exp
    })
    ElMessage.success('简历已保存')
    await loadResume()
  } finally {
    saving.value = false
  }
}

async function runDiagnosis() {
  diagLoading.value = true
  try {
    const q = jobId.value ? `?job_id=${jobId.value}` : ''
    const { data } = await http.get(`/interview/resume/diagnosis${q}`)
    diagnosis.value = data
  } finally {
    diagLoading.value = false
  }
}

async function loadJobs() {
  jobLoading.value = true
  try {
    const { data } = await http.get('/interview/jobs', {
      params: { pool: jobPool.value, limit: 50, keyword: jobKeyword.value,
        city: jobCity.value, industry: jobIndustry.value }
    })
    jobs.value = data.items
    jobTotal.value = data.total
  } finally {
    jobLoading.value = false
  }
}

async function loadFacets() {
  const { data } = await http.get('/interview/jobs/facets')
  facets.value = data
  jobTotal.value = jobTotal.value || data.total
}

async function loadHistory() {
  const { data } = await http.get('/interview/history/me')
  history.value = data.items
}

async function startInterview() {
  starting.value = true
  try {
    const { data } = await http.post('/interview/start', {
      job_id: jobId.value, job_pool: jobPool.value
    })
    const job = jobs.value.find((j) => j.id === jobId.value)
    jobTitle.value = job ? job.title : ''
    session.value = { round: data.round, total: data.total_rounds, question: data.question,
      type: data.question_type, label: data.question_label, id: data.session_id,
      source: data.source || null, isProbe: false }
    report.value = null
    evaluation.value = {}
    lastComment.value = null
    answerText.value = ''
    diagnosis.value = null
  } finally {
    starting.value = false
  }
}

async function submitAnswer(real) {
  answering.value = true
  try {
    const { data } = await http.post(`/interview/${session.value.id}/answer`,
      { text: real ? answerText.value : null })
    if (data.finished) {
      report.value = data
      evaluation.value = data.evaluation || {}
      session.value = null
      await loadHistory()
      return
    }
    lastComment.value = { text: data.comment, score: data.score, version: data.comment_version }
    session.value = { ...session.value, round: data.next.round, question: data.next.question,
      type: data.next.question_type, source: data.next.source || null,
      total: data.total_rounds || session.value.total,
      isProbe: !!data.next.is_probe, probeOf: data.next.probe_of || null }
    if (data.probed) ElMessage.info('这道题答得比较浅，面试官追加了一道追问')
    answerText.value = ''
  } finally {
    answering.value = false
  }
}

async function openHistory(row) {
  if (row['状态'] !== 'finished') {
    ElMessage.info('该场次未完成（可重新开局练习）')
    return
  }
  const { data } = await http.get(`/interview/${row['编号']}`)
  // 结构化评估与收卷同一引擎重算，结果与当时一致
  let eva = {}
  try {
    const { data: ed } = await http.get(`/interview/${row['编号']}/evaluation`)
    eva = ed.evaluation || {}
  } catch {
    eva = {}
  }
  report.value = { total: data.session['总分'], report: data.session['报告'] || '(报告为空)', gaps: [],
    sources: (data.outline || []).map((o) => ({
      round: o.round, type: o.type, label: labelOf(o.type),
      question: o.question, kind: (o.source || {}).kind || 'template',
      name: (o.source || {}).name || '模板出题', url: (o.source || {}).url, bank_id: (o.source || {}).id,
      is_probe: !!o.probe_of,
    })) }
  evaluation.value = eva
  jobTitle.value = data.session['岗位名称'] || ''
  session.value = null
  lastComment.value = null
}

function resetInterview() {
  report.value = null
  evaluation.value = {}
  session.value = null
  lastComment.value = null
  jobId.value = null
  jobTitle.value = ''
}

onMounted(async () => {
  await Promise.all([loadResume(), loadJobs(), loadFacets(), loadHistory()])
})
</script>

<style scoped>
.page { display: block; }
.trust-bar { border-radius: 16px; margin-bottom: 20px; }
.card-title { font-weight: 600; }
.mt8 { margin-top: 8px; }
.ml8 { margin-left: 8px; }
.muted { color: var(--el-text-color-secondary); font-size: 13.5px; }
.kv { display: flex; gap: 8px; margin: 6px 0; font-size: 14px; align-items: baseline; }
.kv .k { color: var(--el-text-color-secondary); flex: none; width: 34px; }
.exp-item { margin: 2px 0; }
.head-row { display: flex; align-items: center; gap: 8px; }
.question { font-size: 15px; font-weight: 600; margin-bottom: 10px; line-height: 1.6; }
.q-source { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin: -2px 0 12px; font-size: 13.5px; color: #6b7280; }
.q-source .src-txt a { color: #2563eb; text-decoration: none; }
.q-source .src-txt a:hover { text-decoration: underline; }
.comment { line-height: 1.7; font-size: 14px; }
.report { white-space: pre-wrap; font-family: inherit; font-size: 14px; line-height: 1.8; margin: 0; }
.diag-item { margin: 10px 0; font-size: 14px; line-height: 1.6; }
.rewrite { color: var(--el-color-success); margin-top: 4px; }
.howto { margin: 0; padding-left: 18px; font-size: 14px; line-height: 1.8; color: var(--el-text-color-regular); }
.howto b { color: var(--el-text-color-primary); }
.job-select { width: 360px; }
.job-filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.job-kw { width: 260px; }
.job-filter { width: 160px; }
.probe-tag { margin-left: 8px; vertical-align: 1px; }
.iv-progress { margin-bottom: 12px; }
.iv-tabs :deep(.el-tabs__header) { margin-bottom: 20px; }

/* ===== 面试评估报告 ===== */
.report-hero { display: flex; gap: 28px; align-items: center; flex-wrap: wrap; }
.score-ring { position: relative; width: 128px; height: 128px; flex: none; }
.score-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.ring-bg { fill: none; stroke: #e5e7eb; stroke-width: 10; }
.ring-fg { fill: none; stroke-width: 10; stroke-linecap: round; transition: stroke-dasharray .6s; }
.score-ring.good .ring-fg { stroke: #10b981; }
.score-ring.mid .ring-fg { stroke: #f59e0b; }
.score-ring.low .ring-fg { stroke: #ef4444; }
.ring-text { position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; }
.ring-text b { font-size: 30px; line-height: 1.1; }
.ring-text span { font-size: 13.5px; color: #6b7280; }
.hero-facts { flex: 1; min-width: 260px; display: flex; flex-direction: column; gap: 12px; }
.fact-row { display: flex; gap: 14px; flex-wrap: wrap; font-size: 14px; color: #374151; }
.fact b { color: #111827; }
.fact.warn { color: #b45309; }
.dim-bars { display: flex; flex-direction: column; gap: 6px; }
.dim-row { display: flex; align-items: center; gap: 10px; font-size: 13.5px; }
.dim-label { flex: none; width: 64px; color: #6b7280; }
.dim-track { flex: 1; height: 8px; border-radius: 4px; background: #f1f5f9; overflow: hidden; }
.dim-fill { height: 100%; border-radius: 4px; }
.dim-fill.good { background: #10b981; }
.dim-fill.mid { background: #f59e0b; }
.dim-fill.low { background: #ef4444; }
.dim-val { flex: none; width: 44px; text-align: right; color: #374151; }

.report-sec { margin-top: 22px; }
.sec-title { font-weight: 600; font-size: 14px; margin-bottom: 10px; }
.problem-item { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
  padding: 8px 0; border-bottom: 1px dashed #f1f5f9; font-size: 14px; }
.problem-dim { font-weight: 600; }
.problem-txt { color: #374151; }
.problem-action { width: 100%; color: #059669; font-size: 13.5px; padding-left: 42px; }

.plan-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.plan-card { border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px 14px;
  background: #f8fafc; }
.plan-when { font-size: 13.5px; color: #2563eb; font-weight: 600; }
.plan-focus { font-weight: 600; margin: 4px 0; }
.plan-action { font-size: 13.5px; color: #4b5563; line-height: 1.6; }

.qreview { border: 1px solid #eef2f7; border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; }
.qreview.probe { border-color: #fde68a; background: #fffbeb; }
.qreview.skipped { opacity: 0.72; }
.qreview-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.qreview-round { font-weight: 600; font-size: 14px; }
.qreview-question { margin: 8px 0; font-size: 14px; color: #111827; font-weight: 500; }
.qreview-comment { font-size: 14px; line-height: 1.8; color: #374151;
  border-left: 3px solid #93c5fd; padding-left: 10px; margin: 6px 0; }
.qreview-tags { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
.tag-muted { font-size: 13.5px; color: #6b7280; }
</style>
