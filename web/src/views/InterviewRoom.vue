<template>
  <div class="page">
    <el-alert class="trust-bar" type="success" :closable="false" show-icon
      title="评分与差距由确定性引擎计算；点评中的「引文」逐字校验，模型不可编造" />

    <el-tabs v-model="tab" class="iv-tabs">
      <!-- ============ 简历 ============ -->
      <el-tab-pane label="我的简历" name="resume">
        <el-card shadow="never" class="block-card">
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

        <el-card v-if="parsed" shadow="never" class="block-card">
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

        <el-card v-if="resume" shadow="never" class="block-card">
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

        <el-card v-if="diagnosis" shadow="never" class="block-card">
          <template #header><span class="card-title">简历诊断（{{ diagnosis.issues.length }} 个问题）</span></template>
          <div v-for="(iss, i) in diagnosis.issues" :key="i" class="diag-item">
            <el-tag size="small" type="warning">{{ issueLabel(iss.kind) }}</el-tag>
            <b>{{ iss.where }}</b>：{{ iss.problem }}
            <div class="rewrite">{{ iss.rewrite }}</div>
          </div>
          <div v-if="!diagnosis.issues.length" class="muted">未发现明显问题</div>
        </el-card>
      </el-tab-pane>

      <!-- ============ 面试 ============ -->
      <el-tab-pane label="面试演练" name="interview">
        <el-card v-if="!session && !report" shadow="never" class="block-card">
          <template #header><span class="card-title">选择目标岗位开局</span></template>
          <el-select v-model="jobId" filterable placeholder="搜索或选择岗位" class="job-select">
            <el-option v-for="j in jobs" :key="j.id" :value="j.id"
              :label="`${j.title} · ${j.company || ''}`" />
          </el-select>
          <el-button type="primary" class="ml8" :loading="starting" :disabled="!jobId || !resume"
            @click="startInterview">开始模拟面试</el-button>
          <div v-if="!resume" class="muted mt8">还没有简历：请先在「我的简历」页录入</div>
          <div class="muted mt8">默认 6 轮：动机 → 专业 → 项目 → 情景 → 抗压 → 反问（按简历证据自动裁剪）</div>
        </el-card>

        <el-card v-if="session && !report" shadow="never" class="block-card">
          <template #header>
            <div class="head-row">
              <span class="card-title">第 {{ session.round }} / {{ session.total }} 题 · {{ session.label }}</span>
              <el-tag size="small">{{ jobTitle }}</el-tag>
            </div>
          </template>
          <div class="question">{{ session.question }}</div>
          <el-input v-model="answerText" type="textarea" :rows="5"
            placeholder="建议用 STAR 结构回答：背景 → 目标 → 行动 → 结果（带数字）" />
          <div class="mt8 head-row">
            <el-button type="primary" :loading="answering" @click="submitAnswer(true)">提交回答</el-button>
            <el-button :loading="answering" @click="submitAnswer(false)">跳过本题</el-button>
          </div>
        </el-card>

        <el-card v-if="lastComment && !report" shadow="never" class="block-card">
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

        <el-card v-if="report" shadow="never" class="block-card">
          <template #header>
            <div class="head-row"><span class="card-title">面试报告</span>
              <el-tag type="danger" effect="dark">总分 {{ report.total }}</el-tag>
              <el-button size="small" @click="resetInterview">再来一场</el-button>
            </div>
          </template>
          <pre class="report">{{ report.report }}</pre>
        </el-card>

        <el-card shadow="never" class="block-card">
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
const session = ref(null)
const jobTitle = ref('')
const answerText = ref('')
const answering = ref(false)
const starting = ref(false)
const lastComment = ref(null)
const report = ref(null)
const history = ref([])

const ISSUE_LABELS = {
  quantify: '缺量化', verb: '动词开头', length: '过长', missing: '缺失',
  alignment: '岗位对齐'
}
const issueLabel = (k) => ISSUE_LABELS[k] || k

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
  const { data } = await http.get('/interview/jobs?limit=50')
  jobs.value = data.items
}

async function loadHistory() {
  const { data } = await http.get('/interview/history/me')
  history.value = data.items
}

async function startInterview() {
  starting.value = true
  try {
    const { data } = await http.post('/interview/start', { job_id: jobId.value })
    const job = jobs.value.find((j) => j.id === jobId.value)
    jobTitle.value = job ? job.title : ''
    session.value = { round: data.round, total: data.total_rounds, question: data.question,
      type: data.question_type, label: data.question_label, id: data.session_id }
    report.value = null
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
      session.value = null
      await loadHistory()
      return
    }
    lastComment.value = { text: data.comment, score: data.score, version: data.comment_version }
    session.value = { ...session.value, round: data.next.round, question: data.next.question,
      type: data.next.question_type }
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
  report.value = { total: data.session['总分'], report: data.session['报告'] || '(报告为空)', gaps: [] }
  session.value = null
  lastComment.value = null
}

function resetInterview() {
  report.value = null
  session.value = null
  lastComment.value = null
  jobId.value = null
}

onMounted(async () => {
  await Promise.all([loadResume(), loadJobs(), loadHistory()])
})
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.trust-bar { border-radius: 8px; }
.block-card { border-radius: 10px; }
.card-title { font-weight: 600; }
.mt8 { margin-top: 8px; }
.ml8 { margin-left: 8px; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.kv { display: flex; gap: 8px; margin: 6px 0; font-size: 13px; align-items: baseline; }
.kv .k { color: var(--el-text-color-secondary); flex: none; width: 34px; }
.exp-item { margin: 2px 0; }
.head-row { display: flex; align-items: center; gap: 8px; }
.question { font-size: 15px; font-weight: 600; margin-bottom: 10px; line-height: 1.6; }
.comment { line-height: 1.7; font-size: 13px; }
.report { white-space: pre-wrap; font-family: inherit; font-size: 13px; line-height: 1.8; margin: 0; }
.diag-item { margin: 10px 0; font-size: 13px; line-height: 1.6; }
.rewrite { color: var(--el-color-success); margin-top: 4px; }
.job-select { width: 360px; }
.iv-tabs :deep(.el-tabs__header) { margin-bottom: 12px; }
</style>
