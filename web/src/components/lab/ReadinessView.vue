<template>
  <div class="rd">
    <!-- 顶部：岗位搜索 -->
    <header class="rd-head">
      <div>
        <div class="rd-eyebrow">READINESS · 岗位就绪度</div>
        <h3 class="rd-title">你的成绩单里有、简历里没有的，到底是哪几项</h3>
      </div>
    </header>

    <div class="rd-search">
      <input
        v-model="jobQuery"
        class="rd-search-input"
        type="text"
        placeholder="搜索岗位名，如：数据分析师 / 前端开发"
        @input="onQueryInput"
      />
      <span class="rd-search-hint">{{ searching ? '搜索中…' : `${jobs.length} 个岗位` }}</span>
    </div>

    <!-- 岗位候选列表 -->
    <div v-if="jobs.length && !result" class="rd-jobs">
      <button
        v-for="j in jobs"
        :key="j.job_id"
        class="rd-job"
        type="button"
        :disabled="assessing"
        @click="selectJob(j)"
      >
        <div class="rd-job-main">
          <span class="rd-job-title">{{ j.title || '未命名岗位' }}</span>
          <span class="rd-job-meta">
            {{ j.company || '未知企业' }}<template v-if="j.city"> · {{ j.city }}</template>
          </span>
        </div>
        <div class="rd-job-skills">
          <span v-for="s in topSkills(j)" :key="s" class="rd-job-skill">{{ s }}</span>
        </div>
      </button>
    </div>

    <!-- 骨架屏：顶部 3 条灰条 + 环占位 -->
    <div v-if="assessing" class="rd-skeleton" aria-busy="true">
      <div class="sk-ring-big"></div>
      <div class="sk-line wide"></div>
      <div class="sk-line"></div>
      <div class="sk-line"></div>
    </div>

    <!-- 请求失败：可重试 -->
    <div v-else-if="error" class="rd-error" role="alert">
      <div class="rd-error-title">评估请求失败</div>
      <p class="rd-error-detail">{{ error }}</p>
      <el-button size="small" type="primary" plain @click="retryAssess">重试</el-button>
    </div>

    <!-- 引导态：未选岗位 -->
    <div v-else-if="!result" class="rd-guide">
      选一个你打算投的岗位，我告诉你差哪几项、哪几项其实你有但没写。
    </div>

    <!-- 结果 -->
    <template v-else>
      <!-- 就绪度环 + level + narrative + 五态计数 -->
      <section class="rd-summary">
        <div class="rd-ring-wrap">
          <svg viewBox="0 0 120 120" class="rd-ring" aria-hidden="true">
            <circle cx="60" cy="60" r="52" class="rd-ring-bg" />
            <circle
              cx="60"
              cy="60"
              r="52"
              class="rd-ring-fg"
              :style="{ strokeDasharray: ringDash, stroke: ringColor }"
            />
          </svg>
          <div class="rd-ring-center">
            <b>{{ readinessText }}</b>
            <span v-if="readinessNum != null">分</span>
          </div>
        </div>
        <div class="rd-summary-main">
          <div class="rd-level" :style="levelStyle">{{ result.level_label || '暂无结论' }}</div>
          <p v-if="readinessNum == null" class="rd-no-skill">该岗位没有技能标签，无法评估</p>
          <p v-if="result.narrative" class="rd-narrative">{{ result.narrative }}</p>
          <div v-if="countsList.length" class="rd-counts">
            <div
              v-for="c in countsList"
              :key="c.key"
              class="rd-count"
              :style="countStyle(c)"
            >
              <span class="rd-count-name">{{ c.label }}</span>
              <span class="rd-count-num">{{ c.num }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 被埋没的资产（整页最重要） -->
      <section v-if="hiddenAssets.length" class="rd-hidden">
        <div class="rd-sec-head">
          <span class="rd-hidden-title">
            <span class="rd-hidden-mark">！</span>
            被埋没的资产 · 你的成绩单里有、简历里没有
          </span>
          <span class="rd-sec-sub">{{ hiddenAssets.length }} 条，按分数排序</span>
        </div>
        <div v-for="(a, i) in hiddenAssets" :key="'h' + i" class="rd-hidden-card">
          <div class="rd-hidden-top">
            <span class="rd-hidden-skill">{{ a.skill || '未知技能' }}</span>
            <span class="rd-hidden-course">{{ a.course || '' }}</span>
            <span class="rd-hidden-score">{{ fmt(a.score) }}</span>
            <span v-if="pctText(a.percentile)" class="rd-hidden-pct">{{ pctText(a.percentile) }}</span>
          </div>
          <p v-if="a.why" class="rd-hidden-why">{{ a.why }}</p>
          <div v-if="a.suggestion" class="rd-hidden-sug">
            <code class="rd-hidden-cmd">{{ a.suggestion }}</code>
            <button class="rd-copy-btn" type="button" @click="copyText(a.suggestion, i)">
              {{ copiedIndex === i ? '已复制' : '复制' }}
            </button>
          </div>
        </div>
      </section>

      <!-- 技能清单 -->
      <section v-if="items.length" class="rd-items-wrap">
        <div class="rd-sec-head">
          <span class="rd-sec-title">技能清单</span>
          <span class="rd-sec-sub">{{ filteredItems.length }} / {{ items.length }} 项</span>
        </div>
        <div class="rd-chips">
          <button
            v-for="f in FILTERS"
            :key="f.key"
            type="button"
            class="rd-chip"
            :class="{ active: filter === f.key }"
            @click="filter = f.key"
          >
            {{ f.label }}
          </button>
        </div>
        <div class="rd-items">
          <div v-for="(it, i) in filteredItems" :key="'i' + i" class="rd-item">
            <span class="rd-pill" :style="pillStyle(it.status)">{{ statusLabel(it) }}</span>
            <div class="rd-item-main">
              <span class="rd-item-skill">{{ it.skill || '未知技能' }}</span>
              <span v-if="it.course || it.score != null" class="rd-item-sub">
                <template v-if="it.course">{{ it.course }}</template>
                <template v-if="it.score != null"> · {{ fmt(it.score) }} 分</template>
              </span>
            </div>
            <div class="rd-item-right">
              <span v-if="it.evidence" class="rd-item-ev">{{ it.evidence }}</span>
              <span class="rd-resume-tag" :class="it.in_resume ? 'yes' : 'no'">
                {{ it.in_resume ? '简历已写' : '简历未写' }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <!-- 补课路径 -->
      <section v-if="gaps.length" class="rd-gaps-wrap">
        <div class="rd-sec-head">
          <span class="rd-sec-title">补课路径</span>
          <span class="rd-sec-sub">{{ gaps.length }} 项缺口</span>
        </div>
        <div v-for="(g, i) in gaps" :key="'g' + i" class="rd-gap">
          <span class="rd-gap-skill">{{ g.skill || '未知技能' }}</span>
          <span class="rd-gap-fix">{{ g.fix || '' }}</span>
          <template v-if="g.how === 'course'">
            <span v-for="(c, ci) in gapCourses(g)" :key="'gc' + ci" class="rd-gap-tag">{{ c }}</span>
          </template>
          <span v-else-if="g.how === 'self'" class="rd-gap-tag self">自学</span>
        </div>
      </section>

      <!-- 面试追问预览 -->
      <section v-if="hooks.length" class="rd-hooks-wrap">
        <div class="rd-sec-head">
          <span class="rd-sec-title">面试官大概率会这样问</span>
        </div>
        <blockquote v-for="(h, i) in hooks" :key="'k' + i" class="rd-hook">{{ h }}</blockquote>
      </section>

      <!-- 行动建议 -->
      <section v-if="advice.length" class="rd-advice-wrap">
        <div class="rd-sec-head">
          <span class="rd-sec-title">行动建议</span>
          <span class="rd-sec-sub">按紧急程度排序</span>
        </div>
        <ol class="rd-advice">
          <li v-for="(a, i) in advice" :key="'a' + i">
            <span class="rd-when">{{ a.when || '本周' }}</span>
            <div class="rd-advice-body">
              <p class="rd-what">{{ a.what || '' }}</p>
              <p v-if="a.why" class="rd-why">{{ a.why }}</p>
            </div>
          </li>
        </ol>
      </section>

      <!-- 其他岗位按缺口数分两组：这是「除当前岗位外，还有哪些岗位离你更近」，
           不是当前所选岗位的属性。每组最多 5 条，由后端分好组。 -->
      <section class="rd-buckets-wrap">
        <div class="rd-sec-head">
          <span class="rd-sec-title">还差几项就能投</span>
          <span class="rd-sec-sub">与你已修课程相关的其他岗位，按缺口数分组</span>
        </div>
        <div class="rd-buckets">
          <div class="rd-bucket is-near">
            <div class="rd-bucket-head">
              <span class="rd-bucket-title">差 1–2 项即可投</span>
              <span v-if="gapNearCount" class="rd-bucket-count">{{ gapNearCount }}</span>
            </div>
            <ul v-if="gapNear.length" class="rd-bucket-list">
              <li v-for="(g, i) in gapNear" :key="'n' + i" class="rd-bucket-item">
                <span class="rd-bucket-job">{{ g.job }}</span>
                <span class="rd-bucket-gaps">
                  <span v-for="(s, si) in g.gaps" :key="'ng' + si" class="rd-bucket-gap">{{ s }}</span>
                </span>
                <span v-if="g.hint" class="rd-bucket-hint">{{ g.hint }}</span>
              </li>
            </ul>
            <p v-else class="rd-bucket-empty">暂无该维度数据</p>
          </div>

          <div class="rd-bucket is-far">
            <div class="rd-bucket-head">
              <span class="rd-bucket-title">差 3 项以上</span>
              <span v-if="gapFarCount" class="rd-bucket-count">{{ gapFarCount }}</span>
            </div>
            <ul v-if="gapFar.length" class="rd-bucket-list">
              <li v-for="(g, i) in gapFar" :key="'f' + i" class="rd-bucket-item">
                <span class="rd-bucket-job">{{ g.job }}</span>
                <span class="rd-bucket-gaps">
                  <span v-for="(s, si) in g.gaps" :key="'fg' + si" class="rd-bucket-gap">{{ s }}</span>
                  <span v-if="g.moreGaps > 0" class="rd-bucket-gap is-more">另 {{ g.moreGaps }} 项</span>
                </span>
                <span v-if="g.hint" class="rd-bucket-hint">{{ g.hint }}</span>
              </li>
            </ul>
            <p v-else class="rd-bucket-empty">暂无该维度数据</p>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref } from 'vue'

import http from '../../api/http'

// 状态五色与筛选 chip，顺序固定 proven → hidden → claimed → weak → gap
const STATUS_META = {
  proven: { color: '#34d399', label: '有背书', full: '有成绩单背书' },
  hidden: { color: '#f59e0b', label: '被埋没', full: '被埋没的资产' },
  claimed: { color: '#a78bfa', label: '只有自述', full: '只有自述' },
  weak: { color: '#fb923c', label: '没学牢', full: '学过没学牢' },
  gap: { color: '#6b7280', label: '空白', full: '完全空白' }
}
const STATUS_ORDER = ['proven', 'hidden', 'claimed', 'weak', 'gap']

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'proven', label: '有背书' },
  { key: 'hidden', label: '被埋没' },
  { key: 'claimed', label: '只有自述' },
  { key: 'weak', label: '没学牢' },
  { key: 'gap', label: '空白' }
]

const LEVEL_COLOR = {
  high: '#34d399',
  mid: '#3b82f6',
  low: '#fb923c',
  critical: '#f87171'
}

const jobs = ref([])
const jobQuery = ref('')
const searching = ref(false)
const searchTimer = ref(null)

const result = ref(null)
const assessing = ref(false)
const error = ref('')
const lastJobId = ref(null)

const filter = ref('all')
const copiedIndex = ref(-1)
let copyTimer = null

// ---- 工具函数 ----
function numOf(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function fmt(v) {
  const n = numOf(v)
  return n == null ? '—' : n.toFixed(1)
}

// 分位文案必须与后端 engine/readiness._top_txt 同口径：
// 满分直接算 100-p 会变成「专业前 0%」，垫底会变成「专业前 90%」，都会误导。
function pctText(p) {
  const v = numOf(p)
  if (v == null) return ''
  if (v >= 95) return '专业前列'
  const n = Math.max(1, Math.round(100 - v))
  return v < 50 ? `专业后 ${n}%` : `专业前 ${n}%`
}

function topSkills(j) {
  const list = Array.isArray(j?.skills) ? j.skills : []
  return list.slice(0, 3).filter(Boolean)
}

function hexToRgba(hex, alpha) {
  const h = String(hex || '').replace('#', '')
  if (h.length !== 6) return `rgba(148, 163, 184, ${alpha})`
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// ---- 岗位搜索（debounce 400ms）----
function onQueryInput() {
  if (searchTimer.value) clearTimeout(searchTimer.value)
  searchTimer.value = setTimeout(() => searchJobs(), 400)
}

async function searchJobs() {
  searching.value = true
  try {
    const { data: res } = await http.get('/interview/lab/readiness/jobs', {
      params: { q: jobQuery.value || undefined, limit: 20 }
    })
    jobs.value = Array.isArray(res?.items) ? res.items : []
  } catch {
    // 搜索失败不打断主流程，保留旧列表
    jobs.value = []
  } finally {
    searching.value = false
  }
}

// ---- 评估 ----
async function selectJob(j) {
  const id = numOf(j?.job_id)
  if (id == null) return
  lastJobId.value = id
  await assess(id)
}

async function assess(jobId) {
  assessing.value = true
  error.value = ''
  try {
    const { data: res } = await http.post('/interview/lab/readiness', { job_id: jobId })
    result.value = res || null
    filter.value = 'all'
  } catch (err) {
    result.value = null
    error.value = err?.response?.data?.detail || err?.message || '请求失败'
  } finally {
    assessing.value = false
  }
}

function retryAssess() {
  if (lastJobId.value != null) assess(lastJobId.value)
}

// ---- 派生数据 ----
const readinessNum = computed(() => numOf(result.value?.readiness))
const readinessText = computed(() => (readinessNum.value == null ? '—' : String(readinessNum.value)))
const ringColor = computed(() => LEVEL_COLOR[result.value?.level] || '#3b82f6')
const ringDash = computed(() => {
  // r=52，周长 2πr ≈ 326.7
  const pct = Math.min(100, Math.max(0, readinessNum.value ?? 0))
  return `${(pct / 100) * 326.7} 326.7`
})
const levelStyle = computed(() => ({
  color: ringColor.value,
  borderColor: hexToRgba(ringColor.value, 0.45),
  background: hexToRgba(ringColor.value, 0.12)
}))

// counts 缺键按 0 处理，顺序固定
const countsList = computed(() => {
  const c = result.value?.counts || {}
  return STATUS_ORDER.map((key) => ({
    key,
    label: STATUS_META[key].label,
    num: numOf(c[key]) ?? 0,
    color: STATUS_META[key].color
  }))
})

function countStyle(c) {
  return {
    color: c.color,
    borderColor: hexToRgba(c.color, 0.4),
    background: hexToRgba(c.color, 0.1)
  }
}

const hiddenAssets = computed(() => (Array.isArray(result.value?.hidden_assets) ? result.value.hidden_assets : []))

const items = computed(() => {
  const list = Array.isArray(result.value?.items) ? result.value.items : []
  return [...list].sort(
    (a, b) => STATUS_ORDER.indexOf(a?.status) - STATUS_ORDER.indexOf(b?.status)
  )
})

const filteredItems = computed(() =>
  filter.value === 'all' ? items.value : items.value.filter((it) => it?.status === filter.value)
)

function statusLabel(it) {
  return it?.status_label || STATUS_META[it?.status]?.full || it?.status || '未知'
}

function pillStyle(status) {
  const color = STATUS_META[status]?.color || '#6b7280'
  return {
    color,
    borderColor: hexToRgba(color, 0.4),
    background: hexToRgba(color, 0.12)
  }
}

const gaps = computed(() => (Array.isArray(result.value?.gaps) ? result.value.gaps : []))

function gapCourses(g) {
  const list = Array.isArray(g?.courses) ? g.courses : []
  return list.filter(Boolean)
}

const hooks = computed(() => (Array.isArray(result.value?.interview_hooks) ? result.value.interview_hooks.filter(Boolean) : []))
const advice = computed(() => (Array.isArray(result.value?.advice) ? result.value.advice : []))

// ---- 其他岗位按缺口数分组：后端 gap_bucket = {near: [...], far: [...]}，各最多 5 条 ----
// near = 差 1-2 项即可投，far = 差 3 项以上。字段缺失、不是对象或两组都为空时整节不出现，
// 组内为空则显示「暂无该维度数据」。缺口标签最多展示 3 个，其余汇成「另 N 项」（N 是真实差值，不是占位）。
const BUCKET_MAX_TAGS = 3
function cleanBucket(list) {
  if (!Array.isArray(list)) return []
  return list
    .filter((g) => g && String(g.job || '').trim() && Array.isArray(g.gaps) && g.gaps.length)
    .map((g) => {
      const gapList = g.gaps.map((s) => String(s || '').trim()).filter(Boolean)
      return {
        job: String(g.job).trim(),
        gaps: gapList.slice(0, BUCKET_MAX_TAGS),
        moreGaps: Math.max(0, gapList.length - BUCKET_MAX_TAGS),
        hint: String(g.hint || '').trim(),
      }
    })
}
const gapNear = computed(() => cleanBucket(result.value?.gap_bucket?.near))
const gapFar = computed(() => cleanBucket(result.value?.gap_bucket?.far))
// 两组条目数：为 0 时返回空串，标题旁不显示「0 个岗位」这种占位数字
const gapNearCount = computed(() => (gapNear.value.length ? `${gapNear.value.length} 个岗位` : ''))
const gapFarCount = computed(() => (gapFar.value.length ? `${gapFar.value.length} 个岗位` : ''))

// ---- 复制：clipboard API 优先，execCommand 兜底 ----
async function copyText(text, idx) {
  let ok = false
  try {
    await navigator.clipboard.writeText(text)
    ok = true
  } catch {
    // 非安全上下文或权限被拒，降级到 execCommand
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      ok = document.execCommand('copy')
      document.body.removeChild(ta)
    } catch {
      ok = false
    }
  }
  if (!ok) return
  copiedIndex.value = idx
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    copiedIndex.value = -1
  }, 1600)
}

// 初始加载默认 20 个岗位；清理定时器
searchJobs()

onUnmounted(() => {
  if (searchTimer.value) clearTimeout(searchTimer.value)
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<style scoped>
.rd {
  --rd-bg: #0d1117;
  --rd-card: #111827;
  --rd-line: rgba(148, 163, 184, 0.18);
  --rd-text: #e5e7eb;
  --rd-sub: #9ca3af;
  --rd-primary: #3b82f6;
  background: var(--rd-bg);
  color: var(--rd-text);
  border-radius: 14px;
  padding: 18px;
  font-variant-numeric: tabular-nums;
}

.rd :deep(.el-button--primary) {
  --el-button-bg-color: #2563eb;
  --el-button-border-color: #2563eb;
  --el-button-hover-bg-color: #3b82f6;
  --el-button-hover-border-color: #3b82f6;
}

.rd-eyebrow {
  color: #60a5fa;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.rd-title {
  margin: 6px 0 0;
  font-size: 17px;
  font-weight: 650;
  color: #f3f4f6;
}

/* ---------------- 岗位搜索 ---------------- */
.rd-search {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}

.rd-search-input {
  flex: 1;
  min-width: 0;
  padding: 9px 13px;
  border: 1px solid var(--rd-line);
  border-radius: 10px;
  background: var(--rd-card);
  color: var(--rd-text);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
}

.rd-search-input:focus { border-color: rgba(96, 165, 250, 0.6); }
.rd-search-input::placeholder { color: #4b5563; }

.rd-search-hint {
  flex: none;
  color: #6b7280;
  font-size: 11.5px;
  white-space: nowrap;
}

.rd-jobs {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.rd-job {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--rd-line);
  border-radius: 12px;
  background: var(--rd-card);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s, transform 0.15s;
}

.rd-job:hover:not(:disabled) {
  border-color: rgba(96, 165, 250, 0.55);
  transform: translateY(-1px);
}

.rd-job:disabled { opacity: 0.55; cursor: wait; }

.rd-job-main {
  /* 标题与公司固定上下两行：横排时有的卡片一行放得下、有的放不下，
     同一排卡片高度一样但文字基线不齐，看着像排版坏了。 */
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.rd-job-title { color: #f3f4f6; font-size: 14px; font-weight: 650; }
.rd-job-meta { color: #6b7280; font-size: 11.5px; }

.rd-job-skills { display: flex; gap: 6px; flex-wrap: wrap; }

.rd-job-skill {
  padding: 1px 8px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.7);
  color: #cbd5e1;
  font-size: 11px;
}

/* ---------------- 骨架 / 错误 / 引导 ---------------- */
.rd-skeleton {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 16px;
}

.sk-ring-big,
.sk-line {
  background: linear-gradient(100deg, #131a26 30%, #1b2433 50%, #131a26 70%);
  background-size: 300% 100%;
  animation: rd-shimmer 1.4s ease-in-out infinite;
}

.sk-ring-big { width: 130px; height: 130px; border-radius: 50%; }
.sk-line { height: 14px; border-radius: 7px; width: 52%; }
.sk-line.wide { width: 74%; height: 18px; }

@keyframes rd-shimmer {
  from { background-position: 120% 0; }
  to { background-position: -40% 0; }
}

.rd-error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  margin-top: 16px;
  padding: 16px;
  border: 1px solid rgba(248, 113, 113, 0.32);
  border-radius: 14px;
  background: rgba(239, 68, 68, 0.08);
}

.rd-error-title { color: #fca5a5; font-size: 14px; font-weight: 650; }
.rd-error-detail { margin: 0; color: #e5e7eb; font-size: 13px; line-height: 1.6; }

.rd-guide {
  margin-top: 18px;
  padding: 26px 18px;
  border: 1px dashed rgba(148, 163, 184, 0.28);
  border-radius: 14px;
  background: rgba(17, 24, 39, 0.6);
  color: var(--rd-sub);
  font-size: 13.5px;
  line-height: 1.7;
  text-align: center;
}

/* ---------------- 就绪度环 ---------------- */
.rd-summary {
  display: flex;
  align-items: flex-start;
  gap: 20px;
  margin-top: 16px;
  padding: 16px;
  border: 1px solid var(--rd-line);
  border-radius: 16px;
  background: var(--rd-card);
  flex-wrap: wrap;
}

.rd-ring-wrap {
  position: relative;
  flex: none;
  width: 130px;
  height: 130px;
}

.rd-ring { width: 100%; height: 100%; transform: rotate(-90deg); }
.rd-ring-bg { fill: none; stroke: #1f2937; stroke-width: 10; }
.rd-ring-fg {
  fill: none;
  stroke-width: 10;
  stroke-linecap: round;
  transition: stroke-dasharray 0.6s;
}

.rd-ring-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.rd-ring-center b {
  color: #f9fafb;
  font-size: 34px;
  font-weight: 700;
  line-height: 1.05;
}

.rd-ring-center span { color: #6b7280; font-size: 11px; }

.rd-summary-main { flex: 1; min-width: 220px; }

.rd-level {
  display: inline-block;
  padding: 5px 16px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 19px;
  font-weight: 700;
}

.rd-no-skill { margin: 10px 0 0; color: #fca5a5; font-size: 13px; }

.rd-narrative {
  margin: 10px 0 0;
  color: var(--rd-sub);
  font-size: 13px;
  line-height: 1.75;
}

.rd-counts {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.rd-count {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 66px;
  padding: 7px 10px;
  border: 1px solid transparent;
  border-radius: 10px;
}

.rd-count-name { font-size: 10.5px; opacity: 0.85; }
.rd-count-num { font-size: 17px; font-weight: 700; }

/* ---------------- 区块通用 ---------------- */
.rd-sec-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 18px 0 10px;
  flex-wrap: wrap;
}

.rd-sec-title { color: #f3f4f6; font-size: 14px; font-weight: 650; }
.rd-sec-sub { color: #6b7280; font-size: 11.5px; }

/* ---------------- 被埋没的资产 ---------------- */
.rd-hidden-title {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #fcd34d;
  font-size: 14px;
  font-weight: 650;
}

.rd-hidden-mark {
  display: inline-grid;
  place-items: center;
  width: 17px;
  height: 17px;
  border-radius: 50%;
  background: #f59e0b;
  color: #111827;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
}

.rd-hidden-card {
  margin-bottom: 10px;
  padding: 13px 15px;
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-left: 3px solid #f59e0b;
  border-radius: 12px;
  background: rgba(245, 158, 11, 0.06);
}

.rd-hidden-top {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.rd-hidden-skill { color: #fde68a; font-size: 14px; font-weight: 650; }
.rd-hidden-course { color: var(--rd-sub); font-size: 12.5px; }

.rd-hidden-score {
  color: #fbbf24;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.1;
  margin-left: auto;
}

.rd-hidden-pct { color: #d97706; font-size: 11.5px; }

.rd-hidden-why {
  margin: 7px 0 0;
  color: #e5e7eb;
  font-size: 12.5px;
  line-height: 1.65;
}

.rd-hidden-sug {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 9px;
}

.rd-hidden-cmd {
  flex: 1;
  min-width: 0;
  padding: 7px 10px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(245, 158, 11, 0.22);
  color: #fef3c7;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 12px;
  line-height: 1.6;
  word-break: break-all;
}

.rd-copy-btn {
  flex: none;
  padding: 5px 12px;
  border: 1px solid rgba(245, 158, 11, 0.45);
  border-radius: 8px;
  background: rgba(245, 158, 11, 0.14);
  color: #fcd34d;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.rd-copy-btn:hover { background: rgba(245, 158, 11, 0.26); }

/* ---------------- 技能清单 ---------------- */
.rd-chips {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.rd-chip {
  padding: 4px 13px;
  border: 1px solid var(--rd-line);
  border-radius: 999px;
  background: rgba(17, 24, 39, 0.6);
  color: var(--rd-sub);
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s;
}

.rd-chip:hover { color: #e5e7eb; }

.rd-chip.active {
  border-color: rgba(96, 165, 250, 0.55);
  background: rgba(37, 99, 235, 0.14);
  color: #bfdbfe;
}

.rd-items {
  border: 1px solid var(--rd-line);
  border-radius: 14px;
  background: var(--rd-card);
  overflow: hidden;
}

.rd-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
}

.rd-item + .rd-item { border-top: 1px solid rgba(148, 163, 184, 0.1); }

.rd-pill {
  flex: none;
  min-width: 70px;
  padding: 2px 9px;
  border: 1px solid transparent;
  border-radius: 999px;
  text-align: center;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.rd-item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rd-item-skill { color: #f3f4f6; font-size: 13.5px; font-weight: 600; }
.rd-item-sub { color: #6b7280; font-size: 11.5px; }

.rd-item-right {
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  max-width: 46%;
}

.rd-item-ev {
  color: #6b7280;
  font-size: 11px;
  line-height: 1.5;
  text-align: right;
}

.rd-resume-tag {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 600;
  white-space: nowrap;
}

.rd-resume-tag.yes {
  border: 1px solid rgba(52, 211, 153, 0.4);
  background: rgba(16, 185, 129, 0.12);
  color: #6ee7b7;
}

.rd-resume-tag.no {
  border: 1px solid rgba(148, 163, 184, 0.3);
  background: rgba(148, 163, 184, 0.1);
  color: #9ca3af;
}

/* ---------------- 补课路径 ---------------- */
.rd-gap {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
  padding: 10px 14px;
  margin-bottom: 8px;
  border: 1px solid var(--rd-line);
  border-radius: 12px;
  background: var(--rd-card);
}

.rd-gap-skill { color: #f3f4f6; font-size: 13px; font-weight: 650; }
.rd-gap-fix { color: var(--rd-sub); font-size: 12.5px; line-height: 1.6; flex: 1; min-width: 160px; }

.rd-gap-tag {
  flex: none;
  padding: 1px 9px;
  border: 1px solid rgba(96, 165, 250, 0.4);
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.12);
  color: #bfdbfe;
  font-size: 11px;
}

.rd-gap-tag.self {
  border-color: rgba(148, 163, 184, 0.3);
  background: rgba(148, 163, 184, 0.1);
  color: #9ca3af;
}

/* ---------------- 面试追问预览 ---------------- */
.rd-hook {
  margin: 0 0 9px;
  padding: 10px 14px;
  border-left: 3px solid var(--rd-primary);
  border-radius: 0 10px 10px 0;
  background: rgba(59, 130, 246, 0.08);
  color: #dbeafe;
  font-size: 13px;
  line-height: 1.75;
}

/* ---------------- 行动建议 ---------------- */
.rd-advice {
  margin: 0;
  padding: 0;
  list-style: none;
}

.rd-advice li {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 9px 0 9px 16px;
}

.rd-advice li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(148, 163, 184, 0.22);
}

.rd-advice li::after {
  content: '';
  position: absolute;
  left: -4px;
  top: 16px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid #60a5fa;
  background: var(--rd-bg);
}

.rd-advice li:first-child::before { top: 16px; }
.rd-advice li:last-child::before { bottom: auto; height: 16px; }

.rd-when {
  flex: none;
  height: 22px;
  padding: 0 10px;
  border: 1px solid rgba(96, 165, 250, 0.35);
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.14);
  color: #bfdbfe;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 20px;
  white-space: nowrap;
}

.rd-advice-body { min-width: 0; }

/* ---------------- 其他岗位按缺口数分组：左 near（主色强调）右 far ---------------- */
.rd-buckets-wrap { margin-top: 18px; }
.rd-buckets {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}
.rd-bucket {
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid var(--rd-line);
  border-radius: 12px;
  background: var(--rd-card);
}
/* near 组：主色描边 + 左上角淡靛蓝提亮，是整节的视觉重心 */
.rd-bucket.is-near {
  border-color: rgba(59, 130, 246, 0.5);
  background:
    radial-gradient(260px 120px at 0% 0%, rgba(37, 99, 235, 0.2), transparent 70%),
    var(--rd-card);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.08);
}
.rd-bucket-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.rd-bucket-title { font-size: 13.5px; font-weight: 650; color: #f3f4f6; }
.rd-bucket.is-near .rd-bucket-title { color: #93c5fd; }
.rd-bucket-count { font-size: 11.5px; color: #6b7280; white-space: nowrap; }
.rd-bucket-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; }
.rd-bucket-item {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
  padding: 9px 11px;
  border-radius: 9px;
  background: rgba(15, 23, 42, 0.6);
}
.rd-bucket.is-near .rd-bucket-item { background: rgba(37, 99, 235, 0.12); }
.rd-bucket-job { font-size: 13px; font-weight: 600; color: #e5e7eb; }
.rd-bucket.is-near .rd-bucket-job { color: #fff; }
.rd-bucket-gaps { display: inline-flex; flex-wrap: wrap; gap: 4px; }
.rd-bucket-gap {
  padding: 1px 8px;
  border: 1px solid rgba(148, 163, 184, 0.32);
  border-radius: 999px;
  color: #cbd5e1;
  font-size: 11px;
  line-height: 1.7;
}
.rd-bucket.is-near .rd-bucket-gap { border-color: rgba(96, 165, 250, 0.5); color: #bfdbfe; }
.rd-bucket-gap.is-more { border-style: dashed; color: #6b7280; }
/* hint 由后端拼好（「补上 X、Y 就能投「岗位」」），与岗位名重复，弱化成一行说明 */
.rd-bucket-hint { flex-basis: 100%; font-size: 12px; line-height: 1.6; color: #9ca3af; }
.rd-bucket.is-near .rd-bucket-hint { color: #bfdbfe; }
.rd-bucket-empty { margin: 0; padding: 6px 2px; font-size: 12.5px; color: #6b7280; }

.rd-what {
  margin: 0;
  color: #e5e7eb;
  font-size: 13px;
  line-height: 1.65;
}

.rd-why {
  margin: 3px 0 0;
  color: #6b7280;
  font-size: 12px;
  line-height: 1.6;
}

/* ---------------- 响应式 ---------------- */
@media (max-width: 640px) {
  .rd-summary { flex-direction: column; align-items: center; }
  .rd-summary-main { width: 100%; }
  .rd-buckets { grid-template-columns: minmax(0, 1fr); }
  .rd-item { flex-wrap: wrap; }
  .rd-item-right { max-width: 100%; align-items: flex-start; }
  .rd-item-ev { text-align: left; }
  .rd-hidden-score { margin-left: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .sk-ring-big,
  .sk-line { animation: none; }
  .rd-ring-fg { transition: none; }
}
</style>
