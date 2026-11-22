<template>
  <div class="page bento-page">
    <div class="bento-grid">
      <el-alert class="trust-bar bento-span-4" type="success" :closable="false" show-icon
        title="分数由确定性引擎 assessment-v1 计算，不调用大模型" />

      <!-- ---------- 阶段一：介绍 ---------- -->
      <template v-if="stage === 'intro'">
        <el-card shadow="never" class="bento-span-4 intro-card" v-loading="loading">
          <template #header>
            <span class="card-title">职业测评 · 软技能五维画像</span>
          </template>

          <p class="intro-desc">
            共 122 道量表题，覆盖性格特质、职业兴趣、能力评估、职业价值观与 IT 专项能力五类维度。
            作答后由确定性引擎算出五个复合能力得分，用于岗位匹配的软技能侧画像。
          </p>

          <div class="dim-grid">
            <div v-for="item in ABILITY_LABELS" :key="item.key" class="dim-cell">
              <span class="dim-dot" aria-hidden="true" />
              <span class="dim-name">{{ item.label }}</span>
            </div>
          </div>

          <div class="intro-actions">
            <el-button type="primary" size="large" :loading="loading" @click="start">
              开始测评
            </el-button>
            <span class="intro-tip">约 5–8 分钟，可随时返回</span>
          </div>
        </el-card>

        <!-- 有历史结果时给出入口：不重新答题也能看到上一次画像 -->
        <el-card v-if="latest" shadow="never" class="bento-span-4 history-card">
          <template #header>
            <span class="card-title">上次测评结果</span>
          </template>
          <div class="history-main">
            <div class="history-score">
              <b>{{ fmt(latest.total_score) }}</b>
              <span>/ {{ fmt(latest.total_max) }}</span>
            </div>
            <div class="history-meta">
              <div>测评时间：{{ latest.create_time || '-' }}</div>
              <div>引擎版本：assessment-v1</div>
            </div>
            <el-button @click="viewHistory(latest)">查看上次结果</el-button>
          </div>
        </el-card>
      </template>

      <!-- ---------- 阶段二：答题 ---------- -->
      <template v-else-if="stage === 'quiz'">
        <el-card shadow="never" class="bento-span-4 quiz-card">
          <template #header>
            <div class="quiz-head">
              <span class="card-title">职业测评</span>
              <span class="quiz-count">第 {{ currentIndex + 1 }} / {{ total }} 题</span>
            </div>
          </template>

          <el-progress class="quiz-progress" :percentage="progressPct" :stroke-width="8"
            :show-text="false" />

          <template v-if="current">
            <div class="quiz-tags">
              <el-tag size="small" effect="plain">{{ current.category || '未分类' }}</el-tag>
              <el-tag v-if="current.dimension" size="small" type="info" effect="plain">
                {{ current.dimension }}
              </el-tag>
            </div>

            <div class="quiz-stem">{{ current.content }}</div>

            <div class="opt-list">
              <button v-for="opt in currentOptions" :key="opt.key" type="button" class="opt-item"
                :class="{ 'is-picked': picked === opt.key }" @click="pick(opt.key)">
                <span class="opt-key">{{ opt.key }}</span>
                <span class="opt-text">{{ opt.text }}</span>
              </button>
            </div>

            <div class="quiz-actions">
              <el-button :disabled="currentIndex === 0" @click="prev">上一题</el-button>
              <span class="quiz-answered">已答 {{ answeredCount }} / {{ total }}</span>
              <el-button type="primary" :loading="submitting" @click="next">
                {{ isLast ? '提交测评' : '下一题' }}
              </el-button>
            </div>
          </template>

          <el-empty v-else description="暂无题目" :image-size="60" />
        </el-card>
      </template>

      <!-- ---------- 阶段三：结果 ---------- -->
      <template v-else>
        <el-card shadow="never" class="bento-span-4 result-card">
          <template #header>
            <div class="result-head">
              <span class="card-title">复合能力画像</span>
              <span v-if="result?.total_score !== undefined" class="result-total">
                总分 {{ fmt(result.total_score) }} / {{ fmt(result.total_max) }}
                <template v-if="result.answered">（{{ result.answered }} 题）</template>
              </span>
            </div>
          </template>

          <div v-if="abilityList.length" class="ring-row">
            <div v-for="item in abilityList" :key="item.key" class="ring-cell">
              <el-progress type="dashboard" :percentage="item.value" :width="118" :stroke-width="9"
                :color="abilityColor(item.value)">
                <template #default="{ percentage }">
                  <span class="ring-value">{{ percentage }}</span>
                  <span class="ring-label">{{ item.label }}</span>
                </template>
              </el-progress>
            </div>
          </div>
          <el-empty v-else description="暂无能力数据" :image-size="60" />
        </el-card>

        <el-card v-if="dimTabs.length" shadow="never" class="bento-span-4 dim-card">
          <template #header>
            <span class="card-title">细粒度维度（按量表分类）</span>
          </template>
          <el-tabs class="dim-tabs">
            <el-tab-pane v-for="tab in dimTabs" :key="tab.group" :label="tab.group">
              <div class="dim-list">
                <div v-for="dim in tab.items" :key="dim.name" class="dim-row">
                  <span class="dim-row-name">{{ dim.name }}</span>
                  <el-progress class="dim-bar" :percentage="clampPct(dim.value)" :stroke-width="10"
                    :color="abilityColor(dim.value)" />
                  <span class="dim-row-value">{{ fmt(dim.value) }}</span>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-card>

        <div class="result-actions bento-span-4">
          <el-button type="primary" @click="restart">重新测评</el-button>
          <span class="result-engine">
            引擎 {{ result?.engine_version || 'assessment-v1' }}
          </span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import http from '../api/http'

// 复合能力 label 映射（与后端 engine/assessment.py 的 ABILITY_KEYS 对齐）
const ABILITY_LABELS = [
  { key: 'professional_skills', label: '专业技能' },
  { key: 'learning_ability', label: '学习能力' },
  { key: 'innovation_ability', label: '创新能力' },
  { key: 'stress_resistance', label: '抗压能力' },
  { key: 'communication_ability', label: '沟通能力' }
]

// 细粒度维度分组（结果页分 Tab 用）
const DIM_GROUPS = {
  性格特质: ['外向性', '尽责性', '开放性', '情绪稳定性', '宜人性'],
  职业兴趣: ['现实型', '研究型', '艺术型', '社会型', '企业型', '常规型'],
  能力评估: ['逻辑思维', '沟通表达', '团队协作', '学习能力', '创新能力', '抗压能力', '执行力', '问题解决'],
  职业价值观: ['成就导向', '自主性', '社会贡献', '工作环境', '发展空间', '薪酬安全', '人际关系', '智力激发', '声望'],
  IT专项能力: ['技术热情', '项目经验', '问题解决', '技术视野', '协作工具']
}

const stage = ref('intro') // intro / quiz / result
const loading = ref(false)
const submitting = ref(false)
const questions = ref([])
const currentIndex = ref(0)
const answers = ref({}) // { [题目 id]: 'A' }，提交时即转成接口要的 dict
const result = ref(null)
const history = ref([])

const total = computed(() => questions.value.length)
const current = computed(() => questions.value[currentIndex.value] || null)
const picked = computed(() => (current.value ? answers.value[current.value.id] || '' : ''))
const isLast = computed(() => currentIndex.value === total.value - 1)
const answeredCount = computed(() => Object.keys(answers.value).length)
const progressPct = computed(() =>
  total.value ? Math.round(((currentIndex.value + 1) / total.value) * 100) : 0
)

// 选项：对象按字母序渲染成卡片，保证 A~E 顺序稳定
const currentOptions = computed(() => {
  const options = current.value?.options || {}
  return Object.entries(options)
    .sort((a, b) => String(a[0]).localeCompare(String(b[0])))
    .map(([key, text]) => ({ key, text }))
})

// 结果页：五个复合能力，只显示接口真正返回的（缺的不补 0 冒充）
const abilityList = computed(() => {
  const abilities = result.value?.abilities || {}
  return ABILITY_LABELS.filter(
    (item) => abilities[item.key] !== undefined && abilities[item.key] !== null
  ).map((item) => ({ ...item, value: Number(abilities[item.key]) || 0 }))
})

// 结果页：分 Tab 的细粒度维度，接口没给的维度整组跳过
const dimTabs = computed(() => {
  const scores = result.value?.dimension_scores || {}
  return Object.entries(DIM_GROUPS)
    .map(([group, dims]) => ({
      group,
      items: dims
        .filter((dim) => scores[dim] !== undefined && scores[dim] !== null)
        .map((dim) => ({ name: dim, value: Number(scores[dim]) || 0 }))
    }))
    .filter((tab) => tab.items.length)
})

const latest = computed(() => history.value[0] || null)
const firstUnanswered = computed(() =>
  questions.value.findIndex((q) => !answers.value[q.id])
)

function fmt(value) {
  if (value === null || value === undefined) return '-'
  const num = Number(value)
  if (Number.isNaN(num)) return '-'
  return Number.isInteger(num) ? String(num) : num.toFixed(1)
}

function clampPct(value) {
  const num = Number(value) || 0
  return Math.max(0, Math.min(100, num))
}

function abilityColor(value) {
  const num = Number(value) || 0
  if (num >= 80) return '#16a34a'
  if (num >= 60) return '#1951c3'
  if (num >= 40) return '#f59e0b'
  return '#ef4444'
}

function pick(key) {
  if (!current.value) return
  answers.value = { ...answers.value, [current.value.id]: key }
}

function prev() {
  if (currentIndex.value > 0) currentIndex.value -= 1
}

function next() {
  if (!picked.value) {
    ElMessage.warning('请先选择一个选项')
    return
  }
  if (isLast.value) {
    submit()
    return
  }
  currentIndex.value += 1
}

async function start() {
  loading.value = true
  try {
    const { data: res } = await http.get('/assessment/questions')
    const list = res?.questions || []
    if (!list.length) {
      ElMessage.error('加载题目失败')
      return
    }
    questions.value = list
    answers.value = {}
    currentIndex.value = 0
    stage.value = 'quiz'
  } catch (err) {
    ElMessage.error('加载题目失败')
  } finally {
    loading.value = false
  }
}

async function submit() {
  // 末题才提交，但仍可能有中间漏答：跳到第一个未答的题
  const missIndex = firstUnanswered.value
  if (missIndex >= 0) {
    currentIndex.value = missIndex
    ElMessage.warning(`第 ${missIndex + 1} 题还未作答，已跳转过去`)
    return
  }
  submitting.value = true
  try {
    const payload = {}
    Object.entries(answers.value).forEach(([qid, option]) => {
      payload[String(qid)] = option
    })
    const { data: res } = await http.post('/assessment/submit', { answers: payload })
    result.value = res || null
    stage.value = 'result'
  } finally {
    submitting.value = false
  }
}

function restart() {
  result.value = null
  answers.value = {}
  currentIndex.value = 0
  stage.value = 'intro'
  loadHistory()
}

async function loadHistory() {
  try {
    const { data: res } = await http.get('/assessment/results')
    history.value = res?.results || []
  } catch (err) {
    history.value = []
  }
}

// 历史结果：后端已返回与提交同口径的 dimension_scores，直接用即可
function viewHistory(item) {
  result.value = { ...item }
  stage.value = 'result'
}

onMounted(loadHistory)
</script>

<style scoped>
.trust-bar {
  border-radius: var(--bento-radius);
}

/* ---------- 阶段一：介绍 ---------- */
.intro-desc {
  margin: 0 0 18px;
  font-size: 14px;
  line-height: 1.8;
  color: var(--bento-sub);
}

.dim-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.dim-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid var(--bento-border);
  border-radius: 999px;
  background: var(--bento-accent-soft);
  color: var(--bento-accent);
  font-size: 14px;
  font-weight: 500;
}

.dim-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--bento-accent);
}

.intro-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 22px;
}

.intro-tip {
  font-size: 13.5px;
  color: var(--bento-mute);
}

.history-main {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.history-score {
  display: flex;
  align-items: baseline;
  gap: 6px;
  color: var(--bento-mute);
  font-size: 14px;
}

.history-score b {
  font-size: 26px;
  font-weight: 650;
  color: var(--bento-text);
  font-variant-numeric: tabular-nums;
}

.history-meta {
  flex: 1 1 220px;
  font-size: 14px;
  line-height: 1.9;
  color: var(--bento-mute);
}

/* ---------- 阶段二：答题 ---------- */
.quiz-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.quiz-count {
  font-size: 14px;
  color: var(--bento-mute);
}

.quiz-progress {
  margin-bottom: 18px;
}

.quiz-tags {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}

.quiz-stem {
  margin-bottom: 20px;
  font-size: 17px;
  font-weight: 600;
  line-height: 1.7;
  color: var(--bento-text);
}

.opt-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.opt-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 13px 16px;
  border: 1px solid var(--bento-border);
  border-radius: var(--bento-radius-sm);
  background: #ffffff;
  font-size: 14px;
  color: var(--bento-sub);
  text-align: left;
  cursor: pointer;
  transition:
    transform 180ms var(--bento-ease),
    border-color 180ms var(--bento-ease),
    background-color 180ms var(--bento-ease),
    color 180ms var(--bento-ease);
}

.opt-item:hover {
  transform: translateY(-1px);
  border-color: #baccf0;
  background: #fbfbff;
}

.opt-item.is-picked {
  border-color: var(--bento-accent);
  background: var(--bento-accent-soft);
  color: var(--bento-accent);
}

.opt-key {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: 8px;
  background: #eef0f5;
  font-size: 14px;
  font-weight: 600;
  color: var(--bento-sub);
  transition:
    background-color 180ms var(--bento-ease),
    color 180ms var(--bento-ease);
}

.opt-item.is-picked .opt-key {
  background: var(--bento-accent);
  color: #ffffff;
}

.opt-text {
  min-width: 0;
}

.quiz-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 22px;
}

.quiz-answered {
  font-size: 14px;
  color: var(--bento-mute);
}

/* ---------- 阶段三：结果 ---------- */
.result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.result-total {
  font-size: 14px;
  color: var(--bento-mute);
}

.ring-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-around;
  gap: 18px;
}

.ring-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.ring-value {
  display: block;
  font-size: 22px;
  font-weight: 650;
  line-height: 1.2;
  color: var(--bento-text);
  font-variant-numeric: tabular-nums;
}

.ring-label {
  display: block;
  margin-top: 2px;
  font-size: 14px;
  color: var(--bento-mute);
}

.dim-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-top: 4px;
}

.dim-row {
  display: grid;
  grid-template-columns: 110px 1fr 56px;
  align-items: center;
  gap: 12px;
}

.dim-row-name {
  font-size: 14px;
  color: var(--bento-sub);
}

.dim-row-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--bento-text);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.result-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.result-engine {
  font-size: 13.5px;
  color: var(--bento-mute);
}

@media (max-width: 720px) {
  .dim-row {
    grid-template-columns: 90px 1fr 48px;
  }

  .quiz-actions {
    flex-wrap: wrap;
  }
}
</style>
