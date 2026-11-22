<template>
  <div class="rtv">
    <header class="rtv-head">
      <div>
        <div class="rtv-eyebrow">ROUND TABLE · 圆桌评审</div>
        <h3 class="rtv-title">三位面试官独立打分，再合议</h3>
      </div>
      <div class="rtv-meta">
        <span v-if="jobTitleText" class="rtv-job">{{ jobTitleText }}</span>
        <span v-if="review" class="rtv-count">
          {{ review.answered ?? 0 }} 题已答<template v-if="review.skipped"> · {{ review.skipped }} 题跳过</template>
        </span>
      </div>
    </header>

    <!-- 失败可重试：把后端 detail 原样透出，不吞错 -->
    <div v-if="panelError" class="rtv-error" role="alert">
      <div class="error-title">圆桌评审加载失败</div>
      <div class="error-detail">{{ panelError }}</div>
      <el-button size="small" type="primary" plain @click="retry">重试</el-button>
    </div>

    <div v-else-if="panelLoading && !review" class="rtv-skeleton" aria-busy="true">
      <div class="sk-row">
        <div v-for="i in 3" :key="i" class="sk-card"></div>
      </div>
      <div class="sk-line wide"></div>
      <div class="sk-line"></div>
    </div>

    <template v-else-if="review">
      <!-- 1. 三张面试官卡 -->
      <section class="panelists" aria-label="面试官评分">
        <article v-for="(p, i) in panelists" :key="p.id || 'p' + i" class="p-card">
          <div class="p-top">
            <span class="p-avatar" :style="avatarStyle(p)" aria-hidden="true">{{ initial(p) }}</span>
            <div class="p-id">
              <div class="p-name">{{ p.name || '面试官' }}</div>
              <div class="p-title">{{ p.title || '' }}</div>
              <div class="p-tagline">{{ p.tagline || '' }}</div>
            </div>
          </div>

          <div class="p-score-row">
            <div class="p-score">
              <b>{{ fmt(p.score) }}</b>
              <span class="p-delta" :class="deltaClass(p.delta_vs_consensus)">{{ signed(p.delta_vs_consensus) }}</span>
            </div>
            <span class="pill" :class="verdictClass(p.verdict)">{{ p.verdict || '—' }}</span>
          </div>

          <div v-if="p.focus" class="p-focus">最在意：<b>{{ p.focus }}</b></div>
          <p v-if="p.comment" class="p-comment">{{ p.comment }}</p>

          <div class="p-lists">
            <ul v-if="(p.highlights || []).length" class="p-list good">
              <li v-for="(h, hi) in (p.highlights || []).slice(0, 3)" :key="'h' + hi">
                <span class="mark">✓</span><span>{{ h }}</span>
              </li>
            </ul>
            <ul v-if="(p.concerns || []).length" class="p-list warn">
              <li v-for="(c, ci) in (p.concerns || []).slice(0, 3)" :key="'c' + ci">
                <span class="mark">!</span><span>{{ c }}</span>
              </li>
            </ul>
            <div v-if="!((p.highlights || []).length + (p.concerns || []).length)" class="p-list-empty">
              暂无要点记录
            </div>
          </div>

          <div v-if="(p.rounds || []).length" class="p-rounds" :title="'逐轮得分'">
            <span
              v-for="(r, ri) in p.rounds"
              :key="r.round ?? ri"
              class="p-round"
              :class="roundClass(r.score)"
              :title="'第 ' + (r.round ?? ri + 1) + ' 轮 · ' + fmt(r.score)"
            ></span>
          </div>
        </article>
      </section>

      <!-- 2. 合议条 -->
      <section class="sum-card" aria-label="合议结果">
        <div class="sum-head">
          <div class="sum-score">
            <b>{{ noConsensus ? '—' : fmt(consensus.score) }}</b>
            <span>合议分</span>
          </div>
          <div class="sum-side">
            <span class="level-badge" :class="levelClass(consensus?.level)">{{ consensus?.level || '未评级' }}</span>
            <span class="pill small" :class="verdictClass(consensus?.verdict)">{{ consensus?.verdict || '—' }}</span>
          </div>
        </div>

        <template v-if="!noConsensus">
          <div class="ruler" :aria-label="spreadSentence" role="img">
            <div class="ruler-band" :style="bandStyle"></div>
            <span
              v-for="(pt, pi) in consensusPoints"
              :key="pt.id || 'dot' + pi"
              class="ruler-dot"
              :style="{ left: pt.score + '%' }"
              :title="pt.name + ' ' + fmt(pt.score)"
            ></span>
          </div>
          <div class="ruler-scale" aria-hidden="true"><span>0</span><span>50</span><span>100</span></div>
          <p class="sum-plain">{{ spreadSentence }}</p>
          <p v-if="consensus.summary" class="sum-text">{{ consensus.summary }}</p>
          <ol v-if="adviceList.length" class="sum-advice">
            <li v-for="(a, ai) in adviceList" :key="'a' + ai">{{ a }}</li>
          </ol>
        </template>
        <p v-else class="sum-empty">本场无有效作答，无法合议。</p>
      </section>

      <!-- 3. 分歧提示 -->
      <div v-if="divergenceText" class="diverge" role="note">
        <span class="diverge-mark" aria-hidden="true">!</span>
        <div class="diverge-body">
          <b>分歧提示</b>
          <p>{{ divergenceText }}</p>
        </div>
      </div>

      <!-- 4. 追问链 -->
      <section class="chain-card" aria-label="追问链">
        <div class="sec-head">
          <span class="sec-title">追问链</span>
          <span class="sec-sub">{{ hasProbe ? '被追问说明上一答偏浅' : '按轮次串联本场问答' }}</span>
        </div>

        <div v-if="cardLoading && !card" class="chain-note">正在读取追问记录…</div>
        <div v-else-if="cardError" class="chain-note err">
          <span>追问链暂不可用：{{ cardError }}</span>
          <el-button link type="primary" size="small" @click="loadCard">重试</el-button>
        </div>
        <div v-else-if="!hasProbe" class="chain-note">本场无追问</div>
        <ol v-else class="chain">
          <li
            v-for="node in chainNodes"
            :key="node.round"
            class="chain-node"
            :class="{ 'is-probe': node.is_probe }"
          >
            <span class="chain-dot" aria-hidden="true"></span>
            <div class="chain-body">
              <div class="chain-row">
                <span class="chain-round">R{{ node.round }}</span>
                <span class="chain-label">{{ node.label || '问答' }}</span>
                <span v-if="node.is_probe" class="probe-tag">追问</span>
                <span v-if="node.is_probe && node.probe_of" class="chain-of">追自第 {{ node.probe_of }} 题</span>
              </div>
              <p class="chain-q">{{ node.question }}</p>
              <p v-if="node.gap" class="chain-gap">{{ gapText(node.gap) }}</p>
            </div>
            <div class="chain-side">
              <b>{{ fmt(node.score) }}</b>
              <span v-if="node.gap" class="chain-flag" title="有未覆盖的要点">!</span>
            </div>
          </li>
        </ol>
      </section>

      <!-- 5. 复盘卡入口 -->
      <div class="cta-row">
        <el-button type="primary" :loading="capturing" @click="openCard">查看复盘卡</el-button>
        <span class="cta-hint">9:16 竖版卡片，可直接截图分享</span>
      </div>
    </template>

    <div v-else class="rtv-empty">暂无圆桌评审数据</div>

    <!-- 复盘卡弹层 -->
    <el-dialog v-model="cardOpen" width="420px" align-center :show-close="false">
      <div class="rc-shell">
        <div class="rc-tools">
          <span>复盘卡</span>
          <button class="rc-close" type="button" aria-label="关闭" @click="cardOpen = false">×</button>
        </div>
        <div ref="cardWrap" class="rc-print-root">
          <ReportCard v-if="card" :data="card" />
        </div>
        <div class="rc-actions">
          <el-button
            type="primary"
            :loading="capturing"
            title="未安装 html2canvas 时将调用浏览器打印，可在打印窗口另存为 PDF 或图片"
            @click="downloadCard"
          >下载图片</el-button>
          <el-button link @click="cardOpen = false">关闭</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'

import http from '../../api/http'
import ReportCard from './ReportCard.vue'

const props = defineProps({
  sessionId: { type: Number, required: true },
  // 父组件已取好的 panel 响应（含 panel 子对象）或 review 结果本身，有则不重复请求
  panel: { type: Object, default: null }
})

const review = ref(null)
const jobTitle = ref('')
const panelLoading = ref(false)
const panelError = ref('')

const card = ref(null)
const cardLoading = ref(false)
const cardError = ref('')

const cardOpen = ref(false)
const capturing = ref(false)
const cardWrap = ref(null)

const DIM_LABELS = { content: '内容', structure: '结构', depth: '深度', evidence: '证据支撑' }

// 分歧等级的人话解释，避免用户只看数字不懂含义
const SPREAD_PLAIN = {
  高度一致: '不同视角看到的结论几乎相同',
  分歧可控: '不同视角看到的东西基本一致',
  分歧明显: '三方关注点差异较大，建议对照着看',
  严重分歧: '三方结论差距很大，优先看各自最在意的那一项'
}

const AVATAR_GRADIENT = {
  tech: 'linear-gradient(135deg, #1d4ed8 0%, #38bdf8 100%)',
  hr: 'linear-gradient(135deg, #0f766e 0%, #2dd4bf 100%)',
  pressure: 'linear-gradient(135deg, #b91c1c 0%, #fb923c 100%)'
}

const panelists = computed(() => review.value?.panelists || [])
const consensus = computed(() => review.value?.consensus || null)
const noConsensus = computed(() => !consensus.value || consensus.value.score == null)
const adviceList = computed(() => consensus.value?.advice || [])
const divergence = computed(() => review.value?.divergence || null)
const jobTitleText = computed(() => jobTitle.value || card.value?.job_title || '')

const consensusPoints = computed(() =>
  panelists.value
    .map((p, i) => {
      const raw = p?.score
      const score = raw === null || raw === undefined || raw === '' ? NaN : Number(raw)
      return { id: p?.id || 'p' + i, name: p?.name || p?.title || '面试官', score }
    })
    .filter((pt) => Number.isFinite(pt.score))
    .map((pt) => ({ ...pt, score: Math.min(100, Math.max(0, pt.score)) }))
)

const bandStyle = computed(() => {
  const list = consensusPoints.value
  if (list.length < 2) return { left: '0%', width: '0%' }
  const values = list.map((p) => p.score)
  const min = Math.min(...values)
  const max = Math.max(...values)
  return { left: min + '%', width: max - min + '%' }
})

const spreadSentence = computed(() => {
  const c = consensus.value
  if (!c || c.score == null) return ''
  const level = c.level || '分歧未知'
  const plain = SPREAD_PLAIN[level] || '可对照三方意见一起看'
  return `三人分差 ${fmt(c.spread)} 分，属${level}——${plain}`
})

const divergenceText = computed(() => {
  const d = divergence.value
  if (!d) return ''
  const dim = DIM_LABELS[d.dimension] || d.dimension || '关键维度'
  const head = `分歧最大在「${dim}」，差 ${fmt(d.gap)} 分`
  return d.note ? `${head}：${d.note}` : head
})

const chainNodes = computed(() => card.value?.probe_chain || [])
const hasProbe = computed(() => chainNodes.value.some((n) => n && n.is_probe))

function fmt(v) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(1) : '—'
}

function signed(v) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const arrow = n > 0 ? '▲' : n < 0 ? '▼' : '—'
  return `${arrow} ${n > 0 ? '+' : ''}${n.toFixed(1)}`
}

function deltaClass(v) {
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return 'flat'
  return n > 0 ? 'up' : 'down'
}

function verdictClass(verdict) {
  if (verdict === '推荐') return 'good'
  if (verdict === '待定') return 'warn'
  if (verdict === '不通过') return 'bad'
  return 'flat'
}

function levelClass(level) {
  if (level === '高度一致') return 'good'
  if (level === '分歧可控') return 'ok'
  if (level === '分歧明显') return 'warn'
  if (level === '严重分歧') return 'bad'
  return 'flat'
}

function roundClass(score) {
  if (score === null || score === undefined) return 'unknown'
  const n = Number(score)
  if (!Number.isFinite(n)) return 'unknown'
  if (n >= 78) return 'good'
  if (n >= 62) return 'mid'
  return 'low'
}

function avatarStyle(p) {
  return { background: AVATAR_GRADIENT[p?.id] || 'linear-gradient(135deg, #334155 0%, #64748b 100%)' }
}

function initial(p) {
  const name = String(p?.name || p?.title || '?').trim()
  return name.charAt(0) || '?'
}

// 后端 gap 已带「漏掉：」前缀时不再重复拼接
function gapText(gap) {
  const text = String(gap || '').trim()
  if (!text) return ''
  return /^漏掉/.test(text) ? text : `漏掉：${text}`
}

function hydratePanel(data) {
  if (!data) return
  // 兼容父组件传整包响应 {session_id, job_title, panel} 或直接传 review 结果
  const inner = data.panel && typeof data.panel === 'object' ? data.panel : data
  review.value = inner
  jobTitle.value = data.job_title || data.jobTitle || ''
}

async function loadPanel() {
  if (props.panel) {
    hydratePanel(props.panel)
    panelError.value = ''
    return
  }
  panelLoading.value = true
  panelError.value = ''
  try {
    const { data } = await http.get(`/interview/lab/panel/${Number(props.sessionId)}`)
    hydratePanel(data)
  } catch (err) {
    review.value = null
    panelError.value = err?.response?.data?.detail || err?.message || '请求失败'
  } finally {
    panelLoading.value = false
  }
}

async function loadCard() {
  if (!props.sessionId) return
  cardLoading.value = true
  cardError.value = ''
  try {
    const { data } = await http.get(`/interview/lab/report-card/${Number(props.sessionId)}`)
    card.value = data || null
  } catch (err) {
    card.value = null
    cardError.value = err?.response?.data?.detail || err?.message || '请求失败'
  } finally {
    cardLoading.value = false
  }
}

function retry() {
  loadPanel()
  if (!card.value) loadCard()
}

async function openCard() {
  if (!card.value) await loadCard()
  if (!card.value) {
    ElMessage.warning(cardError.value || '复盘卡暂不可用，请稍后重试')
    return
  }
  cardOpen.value = true
}

// html2canvas 未安装时不报错：拿不到就退回浏览器打印。
// 用 Function 包一层动态 import，避免打包器在依赖缺失时把构建搞挂
async function pickHtml2Canvas() {
  if (typeof window !== 'undefined' && typeof window.html2canvas === 'function') return window.html2canvas
  try {
    const dynamicImport = new Function('specifier', 'return import(specifier)')
    const mod = await dynamicImport('html2canvas')
    return mod?.default || mod || null
  } catch {
    return null
  }
}

async function downloadCard() {
  const node = cardWrap.value
  if (!node) return
  capturing.value = true
  try {
    const shooter = await pickHtml2Canvas()
    if (!shooter) {
      ElMessage.info('未安装截图库，已改用浏览器打印：在打印窗口选择「另存为 PDF」即可保存')
      window.print()
      return
    }
    const canvas = await shooter(node, { backgroundColor: '#0d1117', scale: 2, useCORS: true })
    const link = document.createElement('a')
    link.download = `面试复盘卡-${props.sessionId}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()
  } catch {
    ElMessage.warning('截图失败，已改用浏览器打印')
    window.print()
  } finally {
    capturing.value = false
  }
}

watch(
  () => props.sessionId,
  () => {
    review.value = null
    card.value = null
    panelError.value = ''
    cardError.value = ''
    if (!props.sessionId) return
    loadPanel()
    loadCard()
  },
  { immediate: true }
)

// 父组件异步取数后回填，直接复用，不再发第二次请求
watch(
  () => props.panel,
  (val) => {
    if (val) hydratePanel(val)
  }
)
</script>

<style scoped>
.rtv {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border-radius: 18px;
  background: #0d1117;
  color: #e5e7eb;
  font-size: 14px;
}

.rtv-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.rtv-eyebrow {
  color: #60a5fa;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .12em;
}

.rtv-title {
  margin: 6px 0 0;
  font-size: 17px;
  font-weight: 650;
  color: #f3f4f6;
}

.rtv-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: #9ca3af;
  font-size: 12.5px;
}

.rtv-job {
  padding: 3px 9px;
  border: 1px solid rgba(96, 165, 250, .28);
  border-radius: 999px;
  background: rgba(37, 99, 235, .12);
  color: #bfdbfe;
}

.rtv-count { font-variant-numeric: tabular-nums; }

/* ---------- 面试官卡 ---------- */
.panelists {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.p-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  padding: 14px;
  border: 1px solid rgba(148, 163, 184, .16);
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(30, 41, 59, .55) 0%, #111827 100%);
}

.p-top {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.p-avatar {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex: none;
  border-radius: 50%;
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  box-shadow: 0 6px 16px rgba(2, 6, 23, .45);
}

.p-id { min-width: 0; }

.p-name {
  font-size: 14.5px;
  font-weight: 650;
  color: #f3f4f6;
}

.p-title {
  color: #93c5fd;
  font-size: 12.5px;
}

.p-tagline {
  margin-top: 2px;
  color: #9ca3af;
  font-size: 12px;
  line-height: 1.45;
}

.p-score-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.p-score {
  display: flex;
  align-items: baseline;
  gap: 7px;
}

.p-score b {
  font-size: 30px;
  font-weight: 700;
  line-height: 1.05;
  color: #f9fafb;
  font-variant-numeric: tabular-nums;
}

.p-delta {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.p-delta.up { color: #34d399; }
.p-delta.down { color: #f87171; }
.p-delta.flat { color: #9ca3af; }

.pill {
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.pill.small { font-size: 11.5px; padding: 2px 8px; }
.pill.good { border-color: rgba(52, 211, 153, .38); background: rgba(16, 185, 129, .14); color: #6ee7b7; }
.pill.warn { border-color: rgba(251, 191, 36, .38); background: rgba(245, 158, 11, .14); color: #fcd34d; }
.pill.bad { border-color: rgba(248, 113, 113, .38); background: rgba(239, 68, 68, .14); color: #fca5a5; }
.pill.flat { border-color: rgba(148, 163, 184, .3); background: rgba(148, 163, 184, .1); color: #cbd5e1; }

.p-focus {
  padding: 6px 9px;
  border-radius: 9px;
  background: rgba(15, 23, 42, .72);
  color: #9ca3af;
  font-size: 12.5px;
}

.p-focus b { color: #e5e7eb; }

.p-comment {
  margin: 0;
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.7;
}

.p-lists {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: auto;
}

.p-list,
.p-list-empty {
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 12.5px;
  line-height: 1.6;
}

.p-list li {
  display: flex;
  gap: 6px;
  align-items: flex-start;
}

.p-list .mark { flex: none; font-weight: 700; }

.p-list.good { color: #a7f3d0; }
.p-list.good .mark { color: #34d399; }
.p-list.warn { color: #fcd34d; }
.p-list.warn .mark { color: #fb923c; }
.p-list-empty { color: #6b7280; }

.p-rounds {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  padding-top: 8px;
  border-top: 1px dashed rgba(148, 163, 184, .18);
}

.p-round {
  width: 12px;
  height: 12px;
  border-radius: 3px;
}

.p-round.good { background: #34d399; }
.p-round.mid { background: #60a5fa; }
.p-round.low { background: #fb923c; }
.p-round.unknown {
  background: repeating-linear-gradient(45deg, #374151 0 3px, #1f2937 3px 6px);
}

/* ---------- 合议条 ---------- */
.sum-card {
  padding: 16px;
  border: 1px solid rgba(96, 165, 250, .22);
  border-radius: 16px;
  background:
    radial-gradient(320px 140px at 0% 0%, rgba(37, 99, 235, .18), transparent 70%),
    #111827;
}

.sum-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.sum-score {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.sum-score b {
  font-size: 38px;
  line-height: 1;
  color: #f9fafb;
  font-variant-numeric: tabular-nums;
}

.sum-score span { color: #9ca3af; font-size: 12.5px; }

.sum-side {
  display: flex;
  align-items: center;
  gap: 8px;
}

.level-badge {
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 12px;
  font-weight: 600;
}

.level-badge.good { border-color: rgba(52, 211, 153, .38); background: rgba(16, 185, 129, .14); color: #6ee7b7; }
.level-badge.ok { border-color: rgba(96, 165, 250, .38); background: rgba(37, 99, 235, .16); color: #bfdbfe; }
.level-badge.warn { border-color: rgba(251, 191, 36, .38); background: rgba(245, 158, 11, .14); color: #fcd34d; }
.level-badge.bad { border-color: rgba(248, 113, 113, .38); background: rgba(239, 68, 68, .14); color: #fca5a5; }
.level-badge.flat { border-color: rgba(148, 163, 184, .3); background: rgba(148, 163, 184, .1); color: #cbd5e1; }

.ruler {
  position: relative;
  height: 30px;
  margin: 14px 2px 0;
  border: 1px solid rgba(148, 163, 184, .2);
  border-radius: 999px;
  background: linear-gradient(90deg, #1f2937 0%, #0f172a 100%);
}

.ruler-band {
  position: absolute;
  top: 9px;
  bottom: 9px;
  border-radius: 999px;
  background: rgba(96, 165, 250, .2);
  border-left: 1px solid rgba(96, 165, 250, .55);
  border-right: 1px solid rgba(96, 165, 250, .55);
}

.ruler-dot {
  position: absolute;
  top: 50%;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  background: #dbeafe;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, .18);
}

.ruler-scale {
  display: flex;
  justify-content: space-between;
  margin: 4px 2px 0;
  color: #64748b;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}

.sum-plain {
  margin: 10px 0 0;
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.65;
}

.sum-text {
  margin: 8px 0 0;
  color: #9ca3af;
  font-size: 13px;
  line-height: 1.75;
}

.sum-advice {
  margin: 10px 0 0;
  padding-left: 18px;
  color: #e5e7eb;
  font-size: 13px;
  line-height: 1.85;
}

.sum-advice li::marker { color: #60a5fa; }

.sum-empty {
  margin: 12px 0 0;
  padding: 10px 12px;
  border: 1px dashed rgba(148, 163, 184, .28);
  border-radius: 10px;
  color: #9ca3af;
  font-size: 13px;
}

/* ---------- 分歧提示 ---------- */
.diverge {
  display: flex;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid rgba(251, 146, 60, .35);
  border-left: 3px solid #fb923c;
  border-radius: 12px;
  background: rgba(251, 146, 60, .08);
}

.diverge-mark {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  flex: none;
  border-radius: 50%;
  background: rgba(251, 146, 60, .22);
  color: #fdba74;
  font-size: 12px;
  font-weight: 700;
}

.diverge-body { min-width: 0; }
.diverge-body b { color: #fdba74; font-size: 13px; }
.diverge-body p {
  margin: 4px 0 0;
  color: #e5e7eb;
  font-size: 13px;
  line-height: 1.7;
}

/* ---------- 追问链 ---------- */
.chain-card {
  padding: 14px 16px;
  border: 1px solid rgba(148, 163, 184, .16);
  border-radius: 16px;
  background: #111827;
}

.sec-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}

.sec-title { font-size: 14px; font-weight: 650; color: #f3f4f6; }
.sec-sub { color: #6b7280; font-size: 12px; }

.chain-note {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 0;
  color: #9ca3af;
  font-size: 13px;
}

.chain-note.err { color: #fca5a5; flex-wrap: wrap; }

.chain {
  margin: 0;
  padding: 0;
  list-style: none;
}

.chain-node {
  position: relative;
  display: flex;
  gap: 10px;
  padding: 9px 0 9px 20px;
}

.chain-node::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(148, 163, 184, .22);
}

.chain-node:first-child::before { top: 16px; }
.chain-node:last-child::before { bottom: auto; height: 16px; }

.chain-dot {
  position: absolute;
  left: 0;
  top: 14px;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: #0d1117;
  border: 2px solid #60a5fa;
}

.chain-node.is-probe { margin-left: 20px; }
.chain-node.is-probe .chain-dot { border-color: #fbbf24; }
.chain-node.is-probe::after {
  content: '';
  position: absolute;
  left: -15px;
  top: 19px;
  width: 15px;
  height: 1px;
  background: rgba(251, 191, 36, .45);
}

.chain-body { flex: 1; min-width: 0; }

.chain-row {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.chain-round {
  color: #93c5fd;
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.chain-label { color: #e5e7eb; font-size: 13px; font-weight: 600; }

.probe-tag {
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid rgba(251, 191, 36, .45);
  background: rgba(245, 158, 11, .16);
  color: #fcd34d;
  font-size: 11px;
  font-weight: 600;
}

.chain-of { color: #6b7280; font-size: 11.5px; }

.chain-q {
  margin: 4px 0 0;
  color: #cbd5e1;
  font-size: 12.5px;
  line-height: 1.65;
}

.chain-gap {
  margin: 4px 0 0;
  color: #fdba74;
  font-size: 12px;
  line-height: 1.6;
}

.chain-side {
  display: flex;
  align-items: baseline;
  gap: 5px;
  flex: none;
}

.chain-side b {
  color: #f3f4f6;
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.chain-flag {
  color: #fb923c;
  font-size: 11px;
  font-weight: 700;
}

/* ---------- CTA ---------- */
.cta-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.cta-hint { color: #6b7280; font-size: 12px; }

/* ---------- 骨架屏 / 错误 ---------- */
.rtv-skeleton { display: flex; flex-direction: column; gap: 12px; }

.sk-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.sk-card {
  height: 200px;
  border-radius: 16px;
  background: linear-gradient(100deg, #131a26 30%, #1b2433 50%, #131a26 70%);
  background-size: 300% 100%;
  animation: rtv-shimmer 1.4s ease-in-out infinite;
}

.sk-line {
  height: 12px;
  width: 45%;
  border-radius: 6px;
  background: linear-gradient(100deg, #131a26 30%, #1b2433 50%, #131a26 70%);
  background-size: 300% 100%;
  animation: rtv-shimmer 1.4s ease-in-out infinite;
}

.sk-line.wide { width: 70%; height: 18px; }

@keyframes rtv-shimmer {
  from { background-position: 120% 0; }
  to { background-position: -40% 0; }
}

.rtv-error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 16px;
  border: 1px solid rgba(248, 113, 113, .32);
  border-radius: 14px;
  background: rgba(239, 68, 68, .08);
}

.error-title { color: #fca5a5; font-size: 14px; font-weight: 650; }
.error-detail { color: #e5e7eb; font-size: 13px; line-height: 1.6; }

.rtv-empty {
  padding: 24px 0;
  text-align: center;
  color: #6b7280;
  font-size: 13px;
}

/* ---------- 复盘卡弹层（深色） ---------- */
:deep(.el-overlay) { background: rgba(3, 7, 18, .74); }

:deep(.el-dialog) {
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, .18);
  border-radius: 20px;
  background: #0d1117;
  box-shadow: 0 28px 70px rgba(0, 0, 0, .6);
}

:deep(.el-dialog__header) { display: none; }
:deep(.el-dialog__body) { padding: 0; }

.rc-shell {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rc-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #9ca3af;
  font-size: 12.5px;
}

.rc-close {
  width: 26px;
  height: 26px;
  border: 1px solid rgba(148, 163, 184, .24);
  border-radius: 8px;
  background: transparent;
  color: #cbd5e1;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
}

.rc-close:hover { background: rgba(148, 163, 184, .14); }

.rc-print-root { display: flex; justify-content: center; }

.rc-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
}

/* 兜底打印：只留复盘卡，其余隐藏（截图库缺失时用） */
@media print {
  :global(body > *) { visibility: hidden !important; }
  /* 遮罩不能整块 display:none，复盘卡就在它里面 */
  :global(.el-overlay) {
    position: static !important;
    background: transparent !important;
    visibility: visible !important;
  }
  .rc-print-root,
  .rc-print-root * { visibility: visible !important; }
  .rc-print-root {
    position: fixed;
    left: 0;
    top: 0;
    margin: 0;
  }
  .rc-tools,
  .rc-actions { display: none !important; }
  :deep(.el-dialog) {
    padding: 0;
    border: none;
    background: transparent;
    box-shadow: none;
  }
}

@media (max-width: 820px) {
  .panelists,
  .sk-row { grid-template-columns: 1fr; }
  .sk-card { height: 150px; }
  .sum-head { align-items: flex-start; flex-direction: column; gap: 8px; }
}

@media (prefers-reduced-motion: reduce) {
  .sk-card,
  .sk-line { animation: none; }
}
</style>
