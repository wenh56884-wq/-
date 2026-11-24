<template>
  <div class="rc">
    <span class="rc-aura" aria-hidden="true"></span>

    <header class="rc-top">
      <span class="rc-brand">启航 · 模拟面试复盘</span>
      <span class="rc-date">{{ dateText }}</span>
      <button class="rc-print" type="button" @click="printPage">打印本页</button>
    </header>

    <div class="rc-job" :title="jobTitle">{{ jobTitle }}</div>

    <section class="rc-printable" aria-label="可打印复盘摘要">
      <p class="rc-summary">{{ summaryText }}</p>
      <div class="rc-groups">
        <div v-for="g in printableGroups" :key="g.key" class="rc-group">
          <div class="sec-h">{{ g.title }}</div>
          <p v-for="(t, i) in g.items" :key="g.key + i" class="line">
            <span class="idx">{{ i + 1 }}</span><span>{{ t }}</span>
          </p>
          <p v-if="!g.items.length" class="line muted">暂无该维度数据</p>
        </div>
      </div>
    </section>

    <div class="rc-score-row">
      <div class="rc-total">
        <b>{{ totalText }}</b>
        <span>总分</span>
      </div>
      <div class="rc-grade" :class="gradeClass">{{ gradeText }}</div>
    </div>

    <div v-if="dimBars.length" class="rc-dims">
      <div v-for="d in dimBars" :key="d.key" class="dim">
        <span class="dim-label">{{ d.label }}</span>
        <span class="dim-track"><i :style="{ width: barWidth(d.value), background: barColor(d.value) }"></i></span>
        <span class="dim-val">{{ d.value == null ? '—' : d.value.toFixed(1) }}</span>
      </div>
    </div>

    <div v-if="panelists.length" class="rc-panel">
      <div v-for="(p, i) in panelists" :key="p.id || 'p' + i" class="rc-panelist">
        <span class="dot" :style="avatarStyle(p)" aria-hidden="true">{{ initial(p) }}</span>
        <span class="dot-name">{{ p.title || p.name || '面试官' }}</span>
        <b>{{ scoreText(p.score) }}</b>
      </div>
    </div>

    <section class="rc-sec">
      <div class="sec-h">三个最该改的点</div>
      <p v-for="(t, i) in problems" :key="'pb' + i" class="line">
        <span class="idx">{{ i + 1 }}</span><span>{{ t }}</span>
      </p>
      <p v-if="!problems.length" class="line muted">本场没有记录到明显问题</p>
    </section>

    <section class="rc-sec">
      <div class="sec-h">下一步</div>
      <p v-for="(t, i) in actions" :key="'na' + i" class="line">
        <span class="arrow">→</span><span>{{ t }}</span>
      </p>
      <p v-if="!actions.length" class="line muted">按本场复盘继续练下一场</p>
    </section>

    <footer class="rc-foot">确定性引擎评分 · 仅供参考，不构成录用承诺</footer>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Object, required: true }
})

const DIM_DEFS = [
  { key: 'content', label: '内容' },
  { key: 'structure', label: '结构' },
  { key: 'depth', label: '深度' },
  { key: 'evidence', label: '证据' }
]

const AVATAR_GRADIENT = {
  tech: 'linear-gradient(135deg, #1d4ed8 0%, #38bdf8 100%)',
  hr: 'linear-gradient(135deg, #0f766e 0%, #2dd4bf 100%)',
  pressure: 'linear-gradient(135deg, #b91c1c 0%, #fb923c 100%)'
}

const jobTitle = computed(() => props.data?.job_title || '模拟面试')
const dateText = computed(() => props.data?.date || '')

const totalNum = computed(() => {
  const raw = props.data?.total
  if (raw === null || raw === undefined || raw === '') return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
})

const totalText = computed(() => (totalNum.value == null ? '—' : totalNum.value.toFixed(1)))

// 后端会给 grade；缺字段时按契约阈值兜底，保证卡片不缺角
const gradeText = computed(() => {
  if (props.data?.grade) return String(props.data.grade)
  const t = totalNum.value
  if (t == null) return '—'
  if (t >= 85) return 'A'
  if (t >= 75) return 'B+'
  if (t >= 65) return 'B'
  if (t >= 55) return 'C+'
  return 'C'
})

const gradeClass = computed(() => {
  const g = gradeText.value
  if (g === 'A') return 'ga'
  if (g === 'B+' || g === 'B') return 'gb'
  return 'gc'
})

const panelists = computed(() => props.data?.panel?.panelists || [])

// 四维进度条替代雷达：读数优先取 passport_dot，其次 panel.radar，都缺就显示占位
function readDims(src) {
  if (!src) return null
  if (Array.isArray(src)) {
    const map = {}
    src.forEach((item) => {
      if (!item || typeof item !== 'object') return
      const key = item.key || item.dim || item.id
      const val = item.latest ?? item.value ?? item.score ?? item.avg
      if (key && val != null) map[key] = Number(val)
    })
    return Object.keys(map).length ? map : null
  }
  if (typeof src !== 'object') return null
  if (Array.isArray(src.radar)) return readDims(src.radar)
  const map = {}
  DIM_DEFS.forEach(({ key }) => {
    const raw = src[key]
    if (raw == null) return
    if (typeof raw === 'object') {
      const val = raw.latest ?? raw.value ?? raw.score ?? raw.avg
      if (val != null) map[key] = Number(val)
    } else {
      map[key] = Number(raw)
    }
  })
  return Object.keys(map).length ? map : null
}

const dimBars = computed(() => {
  const map = readDims(props.data?.passport_dot) || readDims(props.data?.panel) || {}
  return DIM_DEFS.map((d) => {
    const v = map[d.key]
    return { ...d, value: Number.isFinite(v) ? v : null }
  })
})

function textOf(item) {
  if (item == null) return ''
  if (typeof item !== 'object') return String(item)
  const tag = item.dimension || item.dim_label || item.label || ''
  const body = item.problem || item.text || item.title || item.action || item.focus || item.detail || item.desc || ''
  if (tag && body && tag !== body) return `${tag}：${body}`
  return tag || body || ''
}

const problems = computed(() =>
  (props.data?.top_problems || []).slice(0, 3).map(textOf).filter(Boolean)
)

const actions = computed(() =>
  (props.data?.next_actions || []).slice(0, 2).map(textOf).filter(Boolean)
)

// ---------- 可打印摘要：优先用后端 printable；缺失/空数组时回退旧字段，不造数字 ----------
function textList(value, max = 3) {
  if (!Array.isArray(value)) return []
  return value.map(textOf).filter(Boolean).slice(0, max)
}

const printable = computed(() => props.data?.printable || null)

const summaryText = computed(() => {
  const text = printable.value?.summary
  if (typeof text === 'string' && text.trim()) return text.trim()
  if (totalNum.value != null) {
    return `本场模拟面试总分 ${totalText.value} 分，评级 ${gradeText.value}。`
  }
  if (props.data?.grade) return `本场模拟面试评级 ${gradeText.value}。`
  return '暂无该维度数据'
})

const printableGroups = computed(() => {
  const p = printable.value
  const strengths = textList(p?.strengths)
  const weaknesses = textList(p?.weaknesses)
  const steps = textList(p?.actions)
  const dimFallback = [...dimBars.value]
    .filter((d) => d.value != null)
    .sort((a, b) => b.value - a.value)
    .slice(0, 3)
    .map((d) => `${d.label}维度 ${d.value.toFixed(1)} 分`)
  return [
    { key: 'strengths', title: '三项最强', items: strengths.length ? strengths : dimFallback },
    { key: 'weaknesses', title: '三项最弱',
      items: weaknesses.length ? weaknesses : textList(props.data?.top_problems) },
    { key: 'actions', title: '三步行动',
      items: steps.length ? steps : textList(props.data?.next_actions) }
  ]
})

function printPage() {
  if (typeof window !== 'undefined') window.print()
}

function barWidth(v) {
  if (v == null) return '0%'
  return `${Math.min(100, Math.max(0, v))}%`
}

function barColor(v) {
  if (v == null) return '#374151'
  if (v >= 75) return '#34d399'
  if (v >= 60) return '#60a5fa'
  return '#fbbf24'
}

function avatarStyle(p) {
  return { background: AVATAR_GRADIENT[p?.id] || 'linear-gradient(135deg, #334155 0%, #64748b 100%)' }
}

function scoreText(v) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(1) : '—'
}

function initial(p) {
  const name = String(p?.name || p?.title || '?').trim()
  return name.charAt(0) || '?'
}
</script>

<style scoped>
/* 固定 9:16，内部不再响应式：截图与打印的尺寸始终一致 */
.rc {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 360px;
  min-height: 640px;
  height: auto;
  padding: 22px 22px 18px;
  overflow: hidden;
  border-radius: 20px;
  background:
    radial-gradient(300px 220px at 88% -8%, rgba(37, 99, 235, .38), transparent 70%),
    radial-gradient(260px 200px at 0% 108%, rgba(13, 148, 136, .22), transparent 72%),
    linear-gradient(168deg, #111827 0%, #0d1117 58%, #0a0f18 100%);
  color: #e5e7eb;
  box-sizing: border-box;
}

.rc-aura {
  position: absolute;
  right: -70px;
  top: -90px;
  width: 210px;
  height: 210px;
  border: 1px solid rgba(148, 197, 253, .16);
  border-radius: 50%;
  box-shadow: 0 0 0 24px rgba(148, 197, 253, .04), 0 0 0 48px rgba(148, 197, 253, .025);
  pointer-events: none;
}

.rc > *:not(.rc-aura) { position: relative; z-index: 1; }

.rc-top {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.rc-print {
  flex: none;
  padding: 3px 8px;
  border: 1px solid rgba(147, 197, 253, .5);
  border-radius: 7px;
  background: rgba(37, 99, 235, .18);
  color: #bfdbfe;
  font: inherit;
  font-size: 10.5px;
  cursor: pointer;
}

.rc-print:hover { border-color: #93c5fd; color: #eff6ff; }

.rc-printable {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, .16);
  border-radius: 12px;
  background: rgba(15, 23, 42, .5);
}

.rc-summary {
  margin: 0;
  color: #93c5fd;
  font-size: 14px;
  font-weight: 650;
  line-height: 1.5;
}

.rc-groups { display: flex; flex-direction: column; gap: 9px; }

.rc-group { display: flex; flex-direction: column; gap: 4px; }

.rc-brand {
  color: #bfdbfe;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: .06em;
}

.rc-date {
  color: #6b7280;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.rc-job {
  overflow: hidden;
  color: #f3f4f6;
  font-size: 16px;
  font-weight: 650;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rc-score-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 4px;
}

.rc-total {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.rc-total b {
  color: #ffffff;
  font-size: 54px;
  font-weight: 750;
  line-height: 1;
  letter-spacing: -.02em;
  font-variant-numeric: tabular-nums;
}

.rc-total span { color: #9ca3af; font-size: 11.5px; }

.rc-grade {
  display: grid;
  place-items: center;
  min-width: 46px;
  height: 46px;
  padding: 0 10px;
  border-radius: 14px;
  font-size: 22px;
  font-weight: 750;
  letter-spacing: .02em;
}

.rc-grade.ga { border: 1px solid rgba(52, 211, 153, .45); background: rgba(16, 185, 129, .16); color: #6ee7b7; }
.rc-grade.gb { border: 1px solid rgba(96, 165, 250, .45); background: rgba(37, 99, 235, .18); color: #bfdbfe; }
.rc-grade.gc { border: 1px solid rgba(251, 191, 36, .42); background: rgba(245, 158, 11, .16); color: #fcd34d; }

.rc-dims {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 11px 12px;
  border: 1px solid rgba(148, 163, 184, .14);
  border-radius: 12px;
  background: rgba(15, 23, 42, .58);
}

.dim {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.dim-label { flex: none; width: 28px; color: #9ca3af; }

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
  flex: none;
  width: 34px;
  color: #e5e7eb;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.rc-panel {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rc-panelist {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  padding: 4px 8px 4px 4px;
  border: 1px solid rgba(148, 163, 184, .14);
  border-radius: 999px;
  background: rgba(15, 23, 42, .5);
}

.dot {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  flex: none;
  border-radius: 50%;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
}

.dot-name {
  overflow: hidden;
  color: #cbd5e1;
  font-size: 10.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rc-panelist b {
  color: #f3f4f6;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.rc-sec {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 10px;
  border-top: 1px dashed rgba(148, 163, 184, .16);
}

.sec-h {
  color: #93c5fd;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .04em;
}

.line {
  display: flex;
  gap: 7px;
  margin: 0;
  color: #d1d5db;
  font-size: 11.5px;
  line-height: 1.55;
}

.line.muted { color: #6b7280; }

.idx {
  display: grid;
  place-items: center;
  width: 14px;
  height: 14px;
  flex: none;
  margin-top: 2px;
  border-radius: 5px;
  background: rgba(37, 99, 235, .28);
  color: #bfdbfe;
  font-size: 9.5px;
  font-weight: 700;
}

.arrow { flex: none; color: #34d399; font-weight: 700; }

.rc-foot {
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid rgba(148, 163, 184, .12);
  color: #4b5563;
  font-size: 9.5px;
  line-height: 1.5;
}

/* ---------------- 打印：白底黑字，只保留卡内容 ---------------- */
/* 屏上是深色数据卡；打印时浏览器默认不打印背景，若强制印背景则耗墨且发灰，
   所以直接把配色整个翻成白底黑字，装饰层全部隐藏。 */
@media print {
  .rc {
    width: auto;
    max-width: 100%;
    height: auto;
    overflow: visible;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    background: #ffffff;
    color: #111827;
    box-shadow: none;
  }
  /* 光晕装饰与打印按钮不上纸 */
  .rc-aura, .rc-print { display: none; }
  .rc-brand { color: #374151; }
  .rc-job { color: #111827; }
  .rc-total b { color: #000000; }
  .rc-total span { color: #4b5563; }
  .rc-grade { color: #111827; background: #ffffff; }
  .rc-grade.ga, .rc-grade.gb, .rc-grade.gc { border-color: #9ca3af; background: #ffffff; color: #111827; }
  .rc-dims { border-color: #d1d5db; background: #ffffff; }
  .dim-label { color: #4b5563; }
  .dim-track { background: #e5e7eb; }
  .dim-track i { background: #374151 !important; }
  .dim-val { color: #111827; }
  .rc-panelist { border-color: #d1d5db; background: #ffffff; }
  .rc-panelist b { color: #111827; }
  .dot { color: #ffffff; }
  .dot-name { color: #374151; }
  .rc-sec { border-top-color: #d1d5db; }
  .sec-h { color: #111827; }
  .line { color: #111827; }
  .line.muted { color: #6b7280; }
  .idx { background: #e5e7eb; color: #374151; }
  .arrow { color: #111827; }
  .rc-foot { color: #6b7280; }
  /* 打印时高度自适应，固定 640px 会把后面的内容裁掉 */
  .rc { height: auto; min-height: 0; }

  :global(html), :global(body) { background: #fff !important; color: #000 !important; }
  /* 侧边导航、工位切换、弹层工具条与下载/关闭按钮都不进纸面 */
  :global(.sidebar), :global(.nav-drawer), :global(.topbar), :global(.page-head),
  :global(.lab-tabs), :global(.picker), :global(.pet-root), :global(.ai-launcher),
  :global(.rc-tools), :global(.rc-actions) { display: none !important; }
  :global(.shell), :global(.shell-main), :global(.page-main), :global(.lab), :global(.pane),
  :global(.el-overlay), :global(.el-dialog), :global(.el-dialog__body),
  :global(.rc-shell), :global(.rc-print-root) {
    width: 100% !important;
    max-width: none !important;
    height: auto !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: visible !important;
    border: 0 !important;
    box-shadow: none !important;
    background: #fff !important;
  }
  .rc, .rc * { box-shadow: none !important; background-image: none !important; }
  .rc, .rc * { font-size: 11pt !important; }
  .rc-summary { color: #000 !important; font-size: 14pt !important; }
  .rc-printable { border: 1px solid #9ca3af !important; background: #fff !important; }
  .sec-h, .rc-summary, .line, .line.muted, .idx { color: #000 !important; }
  .rc-top, .rc-job, .rc-printable, .rc-score-row, .rc-dims,
  .rc-panel, .rc-sec, .rc-group, .rc-foot {
    break-inside: avoid;
    page-break-inside: avoid;
  }
}
</style>
