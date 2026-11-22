<template>
  <div class="cv">
    <!-- ========== 阶段 1：领题 ========== -->
    <template v-if="phase === 'intro'">
      <div class="cv-eyebrow">CALIBRATION · 评分校准</div>

      <div v-if="caseLoading && !caseData" class="cv-skel" aria-busy="true">
        <div class="sk-block"></div>
        <div class="sk-line w80"></div>
        <div class="sk-line w60"></div>
        <div class="sk-line"></div>
      </div>

      <div v-else-if="caseError" class="cv-error" role="alert">
        <div class="err-title">题目加载失败</div>
        <p class="err-detail">{{ caseError }}</p>
        <el-button size="small" type="primary" plain @click="loadCases">重试</el-button>
      </div>

      <section v-else-if="!items.length" class="empty-card">
        <p class="empty-title">暂无可用题目</p>
        <p class="empty-hint">先去完成一场模拟面试，系统会把你的题目变成评审素材。</p>
        <router-link class="empty-link" to="/student/interview">去做一场模拟面试 →</router-link>
      </section>

      <section v-else class="intro-card">
        <h2 class="intro-title">这次，你是面试官</h2>
        <p class="intro-text">
          下面有 {{ total }} 道题，每题给你三份匿名作答。你要做的只有一件事：排个高下——谁答得最好，谁最差。
        </p>
        <p class="intro-text">
          排完立刻揭晓引擎算出的标准分。你的排序和标准差多远，就说明你有多容易被「听起来很像样」的答案带走。
        </p>
        <div class="intro-meta">
          <template v-if="jobTitleText">本场：{{ jobTitleText }} · </template>{{ total }} 道题
        </div>
        <el-button type="primary" size="large" class="intro-btn" @click="start">开始评审</el-button>
      </section>
    </template>

    <!-- ========== 阶段 2：逐题排序 ========== -->
    <template v-else-if="phase === 'rank'">
      <div class="cv-eyebrow">CALIBRATION · 逐题评审</div>

      <div class="prog-row">
        <span class="prog">第 {{ idx + 1 }}/{{ total }} 题</span>
        <span class="prog-job">{{ jobTitleText }}</span>
      </div>
      <div class="prog-bar" role="progressbar" :aria-valuenow="idx + 1" aria-valuemin="1" :aria-valuemax="total">
        <i :style="{ width: progWidth }"></i>
      </div>

      <p class="q-text">{{ current?.question || '题目内容缺失' }}</p>

      <div v-if="currentSkipped" class="skip-note">
        <span>本题已跳过，不会计入提交。</span>
        <el-button link type="primary" size="small" @click="undoSkip">撤销跳过</el-button>
      </div>

      <div class="ans-list" :class="{ muted: currentSkipped }">
        <article v-for="(c, ci) in currentCandidates" :key="c?.id || 'c' + ci" class="ans-card">
          <div class="ans-head">
            <!-- 只给序号，不露任何 persona 信息，避免提前剧透 -->
            <span class="ans-tag">作答 {{ letterOf(ci) }}</span>
          </div>
          <p class="ans-body">{{ c?.answer || '（这条作答没有内容）' }}</p>
          <div class="rank-row">
            <span class="rank-label">名次</span>
            <button
              v-for="n in 3"
              :key="n"
              type="button"
              class="rank-btn"
              :class="{ on: rankOf(c) === n }"
              :disabled="currentSkipped"
              :aria-pressed="rankOf(c) === n"
              :aria-label="'把作答 ' + letterOf(ci) + ' 排在第 ' + n + ' 名'"
              @click="setRank(c, n)"
            >{{ n }}</button>
          </div>
        </article>
      </div>

      <p v-if="!currentSkipped && !currentDone" class="order-hint">三张卡都选好名次，才能进入下一题</p>
      <p v-if="orderText" class="order-line">{{ orderText }}</p>

      <div v-if="judgeError" class="cv-error" role="alert">
        <div class="err-title">揭晓失败</div>
        <p class="err-detail">{{ judgeError }}</p>
        <el-button size="small" type="primary" plain :disabled="submitting" @click="submit">重试</el-button>
      </div>

      <div class="rank-foot">
        <el-button link :disabled="currentSkipped || submitting" @click="skipCurrent">跳过这题</el-button>
        <el-button
          type="primary"
          :disabled="!canGo || submitting"
          :loading="submitting"
          @click="next"
        >{{ submitting ? '正在比对…' : isLast ? '揭晓结果' : '下一题' }}</el-button>
      </div>
    </template>

    <!-- ========== 阶段 3：揭晓 ========== -->
    <template v-else>
      <div class="cv-eyebrow">CALIBRATION · 校准结果</div>

      <section class="hero">
        <div class="hero-cap">你的判断准度</div>
        <div v-if="hasAccuracy" class="hero-row">
          <b class="hero-num">{{ accText }}</b>
          <span class="hero-badge" :class="levelClass">{{ levelLabel }}</span>
        </div>
        <p v-else class="hero-none">没有有效排序，本次无法校准</p>
        <p v-if="hasAccuracy && plainText" class="hero-plain">{{ plainText }}</p>
      </section>

      <!-- 逐题揭晓：按标准名次升序重排，第 1 名在最上 -->
      <section v-for="(sec, si) in resultSections" :key="sec.key" class="res-item">
        <div class="ri-head">
          <span class="ri-round">第 {{ sec.round ?? si + 1 }} 题</span>
        </div>
        <p class="ri-q">{{ sec.question }}</p>
        <div v-if="sec.verdict" class="verdict-note">{{ sec.verdict }}</div>

        <article v-for="c in sec.candidates" :key="c.id" class="ri-card">
          <div class="ri-top">
            <span class="rank-no">{{ c.standardRank ?? '—' }}</span>
            <span class="persona-pill" :style="c.pill">{{ c.label }}</span>
            <b class="std-score">{{ fmt(c.standard) }}</b>
          </div>

          <div class="ri-sub">
            <span class="my-rank">你的排名：{{ c.myRank ?? '未排' }}</span>
            <span v-if="c.delta" class="delta" :class="c.delta.cls">{{ c.delta.text }}</span>
          </div>

          <div class="dims">
            <div v-for="d in c.dims" :key="d.key" class="dim">
              <span class="dim-label">{{ d.label }}</span>
              <span class="dim-track"><i :style="{ width: d.pct + '%', background: d.color }"></i></span>
              <span class="dim-val">{{ d.text }}</span>
            </div>
          </div>

          <el-collapse class="ans-collapse">
            <el-collapse-item title="展开原答案" :name="c.id">
              <p class="ans-text">{{ c.answer }}</p>
            </el-collapse-item>
          </el-collapse>
        </article>
      </section>

      <!-- 偏误诊断 -->
      <div class="sec-label">偏误诊断</div>
      <div v-if="!hasAccuracy" class="bias-none muted">
        <span>没有有效排序，本次没有可诊断的偏误。</span>
      </div>
      <template v-else>
        <div v-if="!biasList.length" class="bias-none">
          <span class="bias-none-mark" aria-hidden="true">✓</span>
          <span>没有明显偏误——你没有被表面功夫带偏。</span>
        </div>
        <section v-for="(b, bi) in biasList" :key="b.key || 'b' + bi" class="bias-card">
          <span class="bias-pill" :style="biasStyle(b.key)">{{ b.label || '评判偏误' }}</span>
          <p class="bias-detail">{{ b.detail }}</p>
          <blockquote v-if="b.tip" class="bias-tip">{{ b.tip }}</blockquote>
        </section>
      </template>

      <!-- 结论与动作 -->
      <div class="sec-label">结论与动作</div>
      <ol v-if="insights.length" class="insights">
        <li v-for="(t, ti) in insights" :key="'in' + ti">{{ t }}</li>
      </ol>

      <section v-if="nextDrill" class="drill">
        <div class="drill-title">现在就能练的一件事</div>
        <p>{{ nextDrill }}</p>
      </section>

      <div class="res-foot">
        <el-button type="primary" plain :loading="caseLoading" @click="restart">再来一次</el-button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import http from '../../api/http'

const PERSONA_LABELS = { talker: '话术型', doer: '实干型', vague: '空转型' }
const PERSONA_COLORS = { talker: '#fb923c', doer: '#34d399', vague: '#6b7280' }

const BIAS_COLORS = {
  talker_bias: '#fb923c',
  doer_bias: '#a78bfa',
  harsh: '#f87171',
  lenient: '#38bdf8'
}

const LEVEL_LABELS = { sharp: '判断很准', fair: '大体靠得住', blunt: '还需要练眼力' }

const LEVEL_PLAIN = {
  sharp: '你排的和引擎算的基本一致，说明你已经能看穿包装',
  fair: '方向对了，但有一两处被表面功夫带偏',
  blunt: '你的排序和评分标准差得比较远，这恰恰是你自己答题时容易踩的坑'
}

const DIM_DEFS = [
  { key: 'keyword_score', label: '要点命中', max: 30, color: '#60a5fa' },
  { key: 'struct_score', label: '结构', max: 25, color: '#a78bfa' },
  { key: 'depth_score', label: '深度', max: 25, color: '#34d399' },
  { key: 'evidence_score', label: '证据', max: 20, color: '#fbbf24' }
]

// 三阶段状态机：intro（领题）→ rank（逐题排序）→ result（揭晓）
const phase = ref('intro')

const caseData = ref(null)
const caseLoading = ref(false)
const caseError = ref('')

const idx = ref(0)
const rankMap = ref([])
const skipped = ref([])

const submitting = ref(false)
const judgeError = ref('')
const result = ref(null)

const items = computed(() => caseData.value?.items || [])
const total = computed(() => items.value.length)
const jobTitleText = computed(() => caseData.value?.job_title || '')
const current = computed(() => items.value[idx.value] || null)
const currentMap = computed(() => rankMap.value[idx.value] || {})
const currentSkipped = computed(() => !!skipped.value[idx.value])
const isLast = computed(() => idx.value >= total.value - 1)
const progWidth = computed(() => (total.value ? ((idx.value + 1) / total.value) * 100 + '%' : '0%'))

// 每道题按题号轮换一次显示顺序，避免「第 1 张卡就是标准第一」这种位置暗示
const currentCandidates = computed(() => {
  const list = current.value?.candidates || []
  if (list.length < 2) return list
  const shift = idx.value % list.length
  return list.slice(shift).concat(list.slice(0, shift))
})

const needCount = computed(() => Math.min(3, currentCandidates.value.length))
const currentDone = computed(() => {
  if (!needCount.value) return false
  const picked = Object.keys(currentMap.value).filter((k) => currentMap.value[k]).length
  return picked >= needCount.value
})
const canGo = computed(() => currentSkipped.value || currentDone.value)

const orderText = computed(() => {
  const list = currentCandidates.value
  if (!list.length) return ''
  const parts = []
  for (let n = 1; n <= needCount.value; n += 1) {
    const pos = list.findIndex((c) => currentMap.value[c?.id] === n)
    if (pos >= 0) parts.push(`作答 ${letterOf(pos)}`)
  }
  // 排不满就不显示，避免只排了两位也自称「你的排序」
  return parts.length === needCount.value && parts.length ? `你的排序：${parts.join(' > ')}` : ''
})

const accText = computed(() => {
  const n = Number(result.value?.accuracy)
  return Number.isFinite(n) ? n.toFixed(1) : '—'
})

const hasAccuracy = computed(() => {
  const raw = result.value?.accuracy
  if (raw === null || raw === undefined || raw === '') return false
  return Number.isFinite(Number(raw))
})

const resultLevel = computed(() => result.value?.level || '')
const levelClass = computed(() => {
  const lv = resultLevel.value
  return lv === 'sharp' || lv === 'blunt' ? `lv-${lv}` : 'lv-fair'
})
const levelLabel = computed(() => result.value?.level_label || LEVEL_LABELS[resultLevel.value] || '已校准')
const plainText = computed(() => LEVEL_PLAIN[resultLevel.value] || '')

const insights = computed(() => (result.value?.insights || []).filter(Boolean))
const nextDrill = computed(() => result.value?.next_drill || '')
const biasList = computed(() => (result.value?.biases || []).filter((b) => b && (b.label || b.detail)))

const resultSections = computed(() =>
  (result.value?.items || []).map((it, i) => {
    const list = [...(it?.candidates || [])].sort((a, b) => rankNum(a?.standard_rank) - rankNum(b?.standard_rank))
    return {
      key: `sec-${i}`,
      round: it?.round ?? i + 1,
      question: it?.question || '（题干缺失）',
      verdict: it?.verdict || '',
      candidates: list.map((c, ci) => {
        const color = PERSONA_COLORS[c?.id] || '#6b7280'
        return {
          id: c?.id || `c-${i}-${ci}`,
          label: c?.label || PERSONA_LABELS[c?.id] || '候选人',
          answer: c?.answer || '',
          standard: c?.standard,
          standardRank: c?.standard_rank ?? null,
          myRank: c?.my_rank ?? null,
          delta: deltaOf(c?.my_rank, c?.standard_rank),
          pill: { color, borderColor: `${color}59`, background: `${color}1f` },
          // dims 缺字段按 0 处理，保证四条迷你条始终完整
          dims: DIM_DEFS.map((d) => {
            const v = toNum(c?.dims?.[d.key]) ?? 0
            const pct = Math.min(100, Math.max(0, (v / d.max) * 100))
            return { ...d, pct, text: v.toFixed(1) }
          })
        }
      })
    }
  })
)

function letterOf(i) {
  return String.fromCharCode(65 + i)
}

function rankOf(c) {
  if (!c?.id) return 0
  return Number(currentMap.value[c.id]) || 0
}

function rankNum(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n : 99
}

function toNum(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function fmt(v) {
  const n = toNum(v)
  return n == null ? '—' : n.toFixed(1)
}

function deltaOf(myRank, standardRank) {
  if (myRank === null || myRank === undefined || standardRank === null || standardRank === undefined) return null
  const my = Number(myRank)
  const std = Number(standardRank)
  if (!Number.isFinite(my) || !Number.isFinite(std)) return null
  const diff = my - std
  if (diff === 0) return { cls: 'ok', text: '排对了' }
  if (diff > 0) return { cls: 'low', text: `你排低了 ${diff} 档` }
  return { cls: 'high', text: `你排高了 ${-diff} 档` }
}

function biasStyle(key) {
  const color = BIAS_COLORS[key] || '#60a5fa'
  return { color, borderColor: `${color}59`, background: `${color}1f` }
}

function pickDetail(err) {
  return err?.response?.data?.detail || err?.message || '请求失败'
}

// 同题内名次互斥：先清掉占用该名次的另一张卡，再落位；再点同一个数字即取消
function setRank(c, rank) {
  const cid = c?.id
  if (!cid) return
  const q = idx.value
  const map = { ...(rankMap.value[q] || {}) }
  Object.keys(map).forEach((k) => {
    if (k !== cid && map[k] === rank) delete map[k]
  })
  if (map[cid] === rank) delete map[cid]
  else map[cid] = rank
  rankMap.value[q] = map
}

function skipCurrent() {
  if (currentSkipped.value) return
  const q = idx.value
  skipped.value[q] = true
  rankMap.value[q] = {}
  if (!isLast.value) idx.value = q + 1
}

function undoSkip() {
  skipped.value[idx.value] = false
}

function resetRun() {
  idx.value = 0
  rankMap.value = items.value.map(() => ({}))
  skipped.value = items.value.map(() => false)
  result.value = null
  judgeError.value = ''
  submitting.value = false
}

function start() {
  if (!items.value.length) return
  resetRun()
  phase.value = 'rank'
}

function buildRanks() {
  const out = []
  items.value.forEach((item, i) => {
    if (skipped.value[i]) return
    const map = rankMap.value[i] || {}
    ;(item?.candidates || []).forEach((c) => {
      const r = map[c?.id]
      if (r) out.push({ round: item?.round ?? i + 1, id: c.id, rank: Number(r) })
    })
  })
  return out
}

async function submit() {
  if (submitting.value) return
  submitting.value = true
  judgeError.value = ''
  try {
    const { data } = await http.post('/interview/lab/calibration/judge', {
      session_id: caseData.value?.session_id ?? null,
      ranks: buildRanks()
    })
    result.value = data || null
    phase.value = 'result'
  } catch (err) {
    judgeError.value = pickDetail(err)
  } finally {
    submitting.value = false
  }
}

function next() {
  if (!canGo.value || submitting.value) return
  if (isLast.value) {
    submit()
    return
  }
  idx.value += 1
}

async function loadCases() {
  caseLoading.value = true
  caseError.value = ''
  try {
    const { data } = await http.get('/interview/lab/calibration/cases')
    caseData.value = data || null
  } catch (err) {
    caseData.value = null
    caseError.value = pickDetail(err)
  } finally {
    caseLoading.value = false
  }
}

async function restart() {
  phase.value = 'intro'
  caseData.value = null
  resetRun()
  await loadCases()
}

onMounted(loadCases)
</script>

<style scoped>
.cv {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 16px;
  border-radius: 18px;
  background: #0d1117;
  color: #e5e7eb;
  font-size: 14px;
}

.cv-eyebrow {
  color: #60a5fa;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .12em;
}

/* ---------- 阶段 1 ---------- */
.intro-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 20px 18px;
  border: 1px solid #1f2937;
  border-radius: 16px;
  background:
    radial-gradient(340px 170px at 100% 0%, rgba(59, 130, 246, .16), transparent 70%),
    #111827;
}

.intro-title {
  margin: 0;
  color: #f3f4f6;
  font-size: 21px;
  font-weight: 700;
  line-height: 1.35;
}

.intro-text {
  margin: 0;
  color: #cbd5e1;
  font-size: 13.5px;
  line-height: 1.8;
}

.intro-meta {
  margin-top: 2px;
  color: #9ca3af;
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
}

.intro-btn {
  align-self: flex-start;
  margin-top: 6px;
}

.empty-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 26px 18px;
  border: 1px dashed rgba(148, 163, 184, .28);
  border-radius: 16px;
  background: #111827;
}

.empty-title {
  margin: 0;
  color: #f3f4f6;
  font-size: 15px;
  font-weight: 650;
}

.empty-hint {
  margin: 0;
  color: #9ca3af;
  font-size: 13px;
  line-height: 1.7;
}

.empty-link {
  align-self: flex-start;
  margin-top: 4px;
  color: #60a5fa;
  font-size: 13px;
  text-decoration: none;
}

.empty-link:hover { color: #93c5fd; text-decoration: underline; }

/* ---------- 阶段 2 ---------- */
.prog-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.prog {
  color: #bfdbfe;
  font-size: 13px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.prog-job {
  overflow: hidden;
  color: #6b7280;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prog-bar {
  height: 4px;
  border-radius: 999px;
  background: #1f2937;
  overflow: hidden;
}

.prog-bar i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #1d4ed8 0%, #60a5fa 100%);
  transition: width .25s ease;
}

.q-text {
  margin: 4px 0 0;
  color: #f3f4f6;
  font-size: 16.5px;
  font-weight: 600;
  line-height: 1.7;
}

.skip-note {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 8px 12px;
  border: 1px solid #1f2937;
  border-radius: 10px;
  background: rgba(148, 163, 184, .08);
  color: #9ca3af;
  font-size: 12.5px;
}

.ans-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ans-list.muted { opacity: .55; }

.ans-card {
  display: flex;
  flex-direction: column;
  padding: 14px;
  border: 1px solid #1f2937;
  border-radius: 14px;
  background: #111827;
}

.ans-head { display: flex; align-items: center; }

.ans-tag {
  padding: 2px 9px;
  border: 1px solid rgba(96, 165, 250, .28);
  border-radius: 999px;
  background: rgba(37, 99, 235, .16);
  color: #93c5fd;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: .04em;
}

/* 这一屏最该好读的内容：更亮的字、更大的字号 */
.ans-body {
  margin: 10px 0 12px;
  color: #e2e8f0;
  font-size: 15px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.rank-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px dashed rgba(148, 163, 184, .16);
}

.rank-label {
  color: #6b7280;
  font-size: 12px;
}

.rank-btn {
  width: 36px;
  height: 32px;
  border: 1px solid #1f2937;
  border-radius: 9px;
  background: #0f172a;
  color: #cbd5e1;
  font-family: inherit;
  font-size: 13.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  transition: all .15s ease;
}

.rank-btn:hover:not(:disabled) {
  border-color: rgba(96, 165, 250, .55);
  color: #dbeafe;
}

.rank-btn.on {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, .24);
  color: #dbeafe;
  box-shadow: inset 0 0 0 1px rgba(59, 130, 246, .45);
}

.rank-btn:disabled { cursor: not-allowed; }

.order-hint {
  margin: 0;
  color: #4b5563;
  font-size: 11.5px;
}

.order-line {
  margin: 0;
  color: #9ca3af;
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
}

.rank-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 2px;
}

/* ---------- 阶段 3 ---------- */
.hero {
  padding: 22px 16px;
  border: 1px solid rgba(96, 165, 250, .22);
  border-radius: 16px;
  background:
    radial-gradient(320px 160px at 50% -20%, rgba(37, 99, 235, .22), transparent 72%),
    #111827;
  text-align: center;
}

.hero-cap {
  color: #93c5fd;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: .1em;
}

.hero-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 6px;
}

.hero-num {
  color: #ffffff;
  font-size: 48px;
  font-weight: 750;
  line-height: 1;
  letter-spacing: -.02em;
  font-variant-numeric: tabular-nums;
}

.hero-badge {
  padding: 4px 11px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 650;
  white-space: nowrap;
}

.lv-fair { border-color: rgba(96, 165, 250, .42); background: rgba(37, 99, 235, .18); color: #bfdbfe; }

.hero-plain {
  margin: 10px 0 0;
  color: #cbd5e1;
  font-size: 13.5px;
  line-height: 1.75;
}

.hero-none {
  margin: 10px 0 0;
  color: #9ca3af;
  font-size: 15px;
  line-height: 1.7;
}

.res-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border: 1px solid #1f2937;
  border-radius: 16px;
  background: #111827;
}

.ri-head { display: flex; align-items: center; gap: 8px; }

.ri-round {
  color: #93c5fd;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .04em;
  font-variant-numeric: tabular-nums;
}

.ri-q {
  margin: 0;
  color: #e5e7eb;
  font-size: 14px;
  line-height: 1.7;
}

.verdict-note {
  padding: 9px 12px;
  border-left: 3px solid #fb923c;
  border-radius: 0 8px 8px 0;
  background: rgba(251, 146, 60, .08);
  color: #fdba74;
  font-size: 12.8px;
  line-height: 1.7;
}

.ri-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid #1f2937;
  border-radius: 12px;
  background: #0f172a;
}

.ri-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.rank-no {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  flex: none;
  border-radius: 7px;
  background: rgba(59, 130, 246, .2);
  color: #bfdbfe;
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.persona-pill {
  padding: 2px 9px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 650;
  white-space: nowrap;
}

.std-score {
  margin-left: auto;
  color: #f9fafb;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.ri-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.my-rank {
  color: #9ca3af;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.delta {
  padding: 1px 8px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.delta.ok { border-color: rgba(52, 211, 153, .4); background: rgba(16, 185, 129, .12); color: #6ee7b7; }
.delta.low { border-color: rgba(251, 146, 60, .4); background: rgba(251, 146, 60, .12); color: #fdba74; }
.delta.high { border-color: rgba(167, 139, 250, .4); background: rgba(167, 139, 250, .12); color: #c4b5fd; }

.dims {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dim {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
}

.dim-label {
  width: 56px;
  flex: none;
  color: #9ca3af;
}

.dim-track {
  flex: 1;
  height: 5px;
  border-radius: 4px;
  background: rgba(148, 163, 184, .16);
  overflow: hidden;
}

.dim-track i {
  display: block;
  height: 100%;
  border-radius: 4px;
}

.dim-val {
  width: 34px;
  flex: none;
  color: #cbd5e1;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.ans-collapse {
  border-top: 1px dashed rgba(148, 163, 184, .14);
  padding-top: 2px;
}

.ans-text {
  margin: 0;
  color: #e2e8f0;
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

/* el-collapse 默认是浅色，这里压成暗色 */
:deep(.el-collapse) {
  border: none;
  background: transparent;
}

:deep(.el-collapse-item__header) {
  height: 30px;
  border-bottom: none;
  background: transparent;
  color: #93c5fd;
  font-size: 12.5px;
  line-height: 30px;
}

:deep(.el-collapse-item__header:hover) { color: #bfdbfe; }

:deep(.el-collapse-item__arrow) { color: #60a5fa; }

:deep(.el-collapse-item__wrap) {
  border-bottom: none;
  background: transparent;
}

:deep(.el-collapse-item__content) {
  padding-bottom: 0;
  color: #cbd5e1;
  font-size: 13px;
}

/* ---------- 偏误诊断 ---------- */
.sec-label {
  margin-top: 2px;
  color: #93c5fd;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .08em;
}

.bias-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 16px;
  border: 1px solid #1f2937;
  border-radius: 14px;
  background: #111827;
}

.bias-pill {
  align-self: flex-start;
  padding: 3px 10px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 650;
}

.bias-detail {
  margin: 0;
  color: #e5e7eb;
  font-size: 13px;
  line-height: 1.75;
}

.bias-tip {
  margin: 0;
  padding: 8px 12px;
  border-left: 3px solid #3b82f6;
  border-radius: 0 8px 8px 0;
  background: rgba(59, 130, 246, .08);
  color: #bfdbfe;
  font-size: 12.5px;
  line-height: 1.7;
}

.bias-none {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid rgba(52, 211, 153, .32);
  border-radius: 12px;
  background: rgba(16, 185, 129, .1);
  color: #a7f3d0;
  font-size: 13px;
  line-height: 1.7;
}

.bias-none-mark {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  flex: none;
  border-radius: 50%;
  background: rgba(16, 185, 129, .22);
  color: #6ee7b7;
  font-size: 11px;
  font-weight: 700;
}

.bias-none.muted {
  border-color: #1f2937;
  background: rgba(148, 163, 184, .08);
  color: #9ca3af;
}

/* ---------- 结论与动作 ---------- */
.insights {
  margin: 0;
  padding-left: 18px;
  color: #e5e7eb;
  font-size: 13px;
  line-height: 1.85;
}

.insights li::marker { color: #60a5fa; }

.drill {
  padding: 14px 16px;
  border: 1px solid rgba(59, 130, 246, .3);
  border-left: 3px solid #3b82f6;
  border-radius: 12px;
  background: rgba(59, 130, 246, .08);
}

.drill-title {
  color: #bfdbfe;
  font-size: 12.5px;
  font-weight: 700;
  letter-spacing: .04em;
}

.drill p {
  margin: 6px 0 0;
  color: #e5e7eb;
  font-size: 13.5px;
  line-height: 1.75;
}

.res-foot {
  display: flex;
  justify-content: center;
  padding-top: 2px;
}

/* ---------- 骨架屏 / 错误 ---------- */
.cv-skel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px;
  border: 1px solid #1f2937;
  border-radius: 16px;
  background: #111827;
}

.sk-block,
.sk-line {
  border-radius: 8px;
  background: linear-gradient(100deg, #131a26 30%, #1b2433 50%, #131a26 70%);
  background-size: 300% 100%;
  animation: cv-shimmer 1.4s ease-in-out infinite;
}

.sk-block { height: 110px; }
.sk-line { height: 12px; }
.sk-line.w80 { width: 80%; }
.sk-line.w60 { width: 60%; }

@keyframes cv-shimmer {
  from { background-position: 120% 0; }
  to { background-position: -40% 0; }
}

.cv-error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 16px;
  border: 1px solid rgba(248, 113, 113, .32);
  border-radius: 14px;
  background: rgba(239, 68, 68, .08);
}

.err-title {
  color: #fca5a5;
  font-size: 14px;
  font-weight: 650;
}

.err-detail {
  margin: 0;
  color: #e5e7eb;
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
}

@media (max-width: 560px) {
  .hero-num { font-size: 40px; }
  .q-text { font-size: 16px; }
}

@media (prefers-reduced-motion: reduce) {
  .sk-block,
  .sk-line { animation: none; }
  .prog-bar i { transition: none; }
}
</style>
