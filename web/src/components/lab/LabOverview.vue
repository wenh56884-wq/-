<!-- 实验室总览：六个工具的前置结论页。
     进来先看「我在哪、有没有变好、下一步做哪三件事」，再决定点哪个工具，
     而不是先面对一排看不懂的 Tab。 -->
<template>
  <div class="ov">
    <!-- 载入骨架 -->
    <div v-if="loading" class="ov-skeleton" aria-busy="true">
      <div class="sk-card"></div>
      <div class="sk-card"></div>
      <div class="sk-card"></div>
    </div>

    <template v-else>
      <!-- ① 三个数：现在在哪 -->
      <section class="ov-stats">
        <article class="stat stat-hero">
          <div class="stat-top">
            <span class="stat-label">岗位就绪度</span>
            <span v-if="target" class="stat-tag" :class="levelClass">{{ target.level_label }}</span>
          </div>
          <div class="stat-num">
            <b>{{ target?.readiness == null ? '—' : target.readiness.toFixed(1) }}</b>
            <span>/ 100</span>
          </div>
          <p class="stat-foot">
            <template v-if="target">
              目标：{{ target.job_title }}<template v-if="target.company"> · {{ target.company }}</template>
            </template>
            <template v-else>还没有带技能标签的岗位可评估</template>
          </p>
          <!-- 这一行是这个板块最值钱的东西：考得好、简历没写的技能，改一行简历就能补 -->
          <div v-if="target?.hidden?.length" class="hidden-row">
            <span class="hidden-label">考得好但简历没写</span>
            <span v-for="h in target.hidden" :key="h.skill" class="hidden-chip">
              {{ h.skill }}<b>{{ h.score == null ? '' : Math.round(h.score) }}</b>
            </span>
          </div>
          <button v-if="target" class="stat-link" type="button" @click="$emit('go', 'ready')">
            看这项技能差在哪 →
          </button>
        </article>

        <article class="stat">
          <div class="stat-top">
            <span class="stat-label">最近一场</span>
            <span v-if="latest?.grade" class="stat-tag grade">{{ latest.grade }}</span>
          </div>
          <div class="stat-num">
            <b>{{ latest?.total == null ? '—' : latest.total.toFixed(1) }}</b>
            <span v-if="delta != null" class="delta" :class="{ up: delta > 0, down: delta < 0 }"
                  title="与上一场相比">
              {{ delta > 0 ? '+' : '' }}{{ delta }}
            </span>
          </div>
          <!-- 岗位名与「日期 · 题数」分两行：挤成一行时「题」字会孤零零掉到第二行 -->
          <p v-if="latest" class="stat-foot foot-2">
            <span>{{ latest.job_title || '通用面试' }}</span>
            <span class="foot-sub">{{ latest.date }} · {{ latest.rounds }} 题</span>
          </p>
          <p v-else class="stat-foot">还没有已完成的面试</p>
          <button class="stat-link" type="button" @click="$emit('go', latest ? 'panel' : 'practice')">
            {{ latest ? '看三位面试官怎么吵 →' : '去答一场 →' }}
          </button>
        </article>

        <article class="stat">
          <div class="stat-top">
            <span class="stat-label">同辈分位</span>
            <span v-if="peer" class="stat-tag" :class="{ muted: peer.basis !== 'observed' }">
              {{ peer.basis === 'observed' ? '实测' : '样本不足' }}
            </span>
          </div>
          <div class="stat-num">
            <b :class="{ 'is-text': !peerNumeric }">{{ peerText }}</b>
          </div>
          <p class="stat-foot">{{ peerFoot }}</p>
        </article>
      </section>

      <!-- ② 走势：在不在变好 -->
      <section class="ov-trend">
        <header class="sec-head">
          <h4>近 {{ trend.length || 0 }} 场成绩</h4>
          <p v-if="latest?.weakest" class="sec-sub">
            最弱一环：{{ latest.weakest.label }} {{ latest.weakest.value }} 分
          </p>
        </header>

        <div v-if="points.length >= 2" class="spark">
          <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id="ovFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#3b82f6" stop-opacity=".38" />
                <stop offset="100%" stop-color="#3b82f6" stop-opacity="0" />
              </linearGradient>
            </defs>
            <line v-for="g in gridLines" :key="'g' + g" :x1="0" :x2="W" :y1="g" :y2="g"
                  stroke="rgba(148,163,184,.16)" stroke-width="1" />
            <polygon :points="areaPoints" fill="url(#ovFill)" />
            <polyline :points="linePoints" fill="none" stroke="#60a5fa" stroke-width="2"
                      stroke-linejoin="round" stroke-linecap="round" />
            <circle v-for="(p, i) in points" :key="'c' + i" :cx="p.x" :cy="p.y" r="3.4"
                    fill="#0d1117" stroke="#93c5fd" stroke-width="2" />
          </svg>
          <!-- 刻度按每个点的实际横坐标定位，而不是 space-between 均分：
               均分时标签和折线点对不上，读起来像在看两张图 -->
          <div class="spark-axis">
            <span v-for="(p, i) in points" :key="'a' + i"
                  :style="{ left: (p.x / W) * 100 + '%' }">{{ p.total.toFixed(0) }}</span>
          </div>
        </div>
        <div v-else class="trend-empty">
          再答完一场就有对比曲线了 —— 现在只有 {{ trend.length }} 场记录。
        </div>
      </section>

      <!-- ③ 下一步：按优先级排好的三件事 -->
      <section class="ov-steps">
        <header class="sec-head">
          <h4>接下来做这三件事</h4>
          <p class="sec-sub">顺序是按「哪一项最拖后腿」排的，不是随机推荐</p>
        </header>
        <div class="steps">
          <button v-for="(s, i) in steps" :key="s.key" class="step" type="button"
                  @click="$emit('go', s.tab)">
            <span class="step-idx">{{ i + 1 }}</span>
            <span class="step-body">
              <span class="step-title">{{ s.title }}</span>
              <span class="step-why">{{ s.why }}</span>
            </span>
            <span class="step-cta">{{ s.cta }}<i>→</i></span>
          </button>
        </div>
      </section>

      <!-- ④ 工具入口 -->
      <section class="ov-tools">
        <header class="sec-head">
          <h4>六个工具</h4>
          <p class="sec-sub">都要一场已完成面试才出结论</p>
        </header>
        <div class="tools">
          <button v-for="t in tools" :key="t.key" class="tool" :class="{ locked: t.state === 'locked' }"
                  type="button" :title="t.note || ''" @click="$emit('go', t.key)">
            <span class="tool-label">{{ t.label }}</span>
            <span class="tool-note">{{ t.state === 'locked' ? t.note : '可用' }}</span>
          </button>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import http from '../../api/http'

defineEmits(['go'])

const W = 560
const H = 120

const loading = ref(true)
const data = ref(null)

const target = computed(() => data.value?.target || null)
const latest = computed(() => data.value?.latest || null)
const trend = computed(() => data.value?.trend || [])
const delta = computed(() => data.value?.delta ?? null)
const peer = computed(() => data.value?.peer || null)
const steps = computed(() => data.value?.next_steps || [])
const tools = computed(() => data.value?.tools || [])

const levelClass = computed(() => {
  const lv = target.value?.level
  if (lv === 'high') return 'ok'
  if (lv === 'mid') return ''
  return 'warn'
})

const peerNumeric = computed(
  () => peer.value?.basis === 'observed' && peer.value?.percentile != null
)

const peerText = computed(() => {
  if (!peer.value) return '—'
  if (peer.value.basis !== 'observed' || peer.value.percentile == null) return '样本不足'
  return `前 ${Math.max(1, Math.round(100 - peer.value.percentile))}%`
})

const peerFoot = computed(() => {
  const p = peer.value
  if (!p) return '还没有可用于比较的样本'
  if (p.basis === 'observed') {
    return `同专业同年级 ${p.cohort || '—'} 人，实测 ${p.sample_n} 份`
  }
  return `同专业同年级只有 ${p.sample_n || 0} 份实测成绩，不足 5 份不下结论`
})

// 折线：取值域固定 0~100，避免「40 分和 45 分看起来差一倍」
const points = computed(() => {
  const rows = trend.value.filter((t) => t.total != null)
  if (!rows.length) return []
  const pad = 10
  const inner = H - pad * 2
  return rows.map((t, i) => ({
    ...t,
    x: rows.length === 1 ? W / 2 : pad + (i * (W - pad * 2)) / (rows.length - 1),
    y: pad + inner - (Math.min(100, Math.max(0, t.total)) / 100) * inner
  }))
})

const linePoints = computed(() => points.value.map((p) => `${p.x},${p.y}`).join(' '))
const areaPoints = computed(() => {
  if (!points.value.length) return ''
  const first = points.value[0]
  const last = points.value[points.value.length - 1]
  return `${first.x},${H} ${linePoints.value} ${last.x},${H}`
})
const gridLines = computed(() => [H * 0.25, H * 0.5, H * 0.75])

async function load() {
  loading.value = true
  try {
    const { data: res } = await http.get('/interview/lab/summary')
    data.value = res
  } catch (e) {
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.ov {
  --ov-bg: #0d1117;
  --ov-card: #111827;
  --ov-line: rgba(148, 163, 184, 0.16);
  --ov-text: #e5e7eb;
  --ov-sub: #9ca3af;
  --ov-faint: #6b7280;
  color: var(--ov-text);
  font-variant-numeric: tabular-nums;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* ---------- ① 三个数 ---------- */
.ov-stats {
  display: grid;
  grid-template-columns: 1.25fr 1fr 1fr;
  gap: 14px;
}

.stat {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px 18px 14px;
  border: 1px solid var(--ov-line);
  border-radius: 14px;
  background: linear-gradient(168deg, #131a26 0%, #0f1520 100%);
  overflow: hidden;
}

.stat-hero::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: linear-gradient(180deg, #60a5fa, #2563eb);
}

.stat-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stat-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ov-sub);
}

.stat-tag {
  margin-left: auto;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(96, 165, 250, 0.32);
  background: rgba(37, 99, 235, 0.16);
  color: #bfdbfe;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.stat-tag.ok {
  border-color: rgba(52, 211, 153, 0.34);
  background: rgba(16, 185, 129, 0.14);
  color: #6ee7b7;
}

.stat-tag.warn {
  border-color: rgba(251, 191, 36, 0.36);
  background: rgba(245, 158, 11, 0.14);
  color: #fcd34d;
}

.stat-tag.muted {
  border-color: var(--ov-line);
  background: rgba(148, 163, 184, 0.1);
  color: var(--ov-sub);
}

.stat-tag.grade {
  border-color: rgba(96, 165, 250, 0.3);
  background: rgba(37, 99, 235, 0.18);
  color: #dbeafe;
  font-size: 12px;
}

.stat-num {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.stat-num b {
  font-size: 40px;
  font-weight: 750;
  line-height: 1.02;
  letter-spacing: -0.03em;
  color: #fff;
}

.stat-num span {
  font-size: 12px;
  color: var(--ov-faint);
}

.stat-num b.is-text {
  font-size: 22px;
  font-weight: 650;
  letter-spacing: 0;
  color: #cbd5e1;
}

/* 被埋没的资产：考得好、简历没写 */
.hidden-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: -2px;
}

.hidden-label {
  font-size: 11px;
  color: #6ee7b7;
}

.hidden-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  padding: 2px 7px;
  border: 1px solid rgba(52, 211, 153, 0.3);
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.12);
  color: #a7f3d0;
  font-size: 11.5px;
}

.hidden-chip b {
  color: #6ee7b7;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.stat-num .delta {
  margin-left: 2px;
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
}

.delta.up {
  background: rgba(16, 185, 129, 0.16);
  color: #6ee7b7;
}

.delta.down {
  background: rgba(239, 68, 68, 0.16);
  color: #fca5a5;
}

.stat-foot {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ov-sub);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.foot-2 {
  display: flex;
  flex-direction: column;
  gap: 2px;
  -webkit-line-clamp: unset;
}

.foot-sub {
  font-size: 11.5px;
  color: #6b7280;
}

.stat-link {
  align-self: flex-start;
  margin-top: auto;
  padding: 0;
  border: 0;
  background: none;
  color: #93c5fd;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.stat-link:hover {
  color: #bfdbfe;
  text-decoration: underline;
}

/* ---------- 区块标题 ---------- */
.sec-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.sec-head h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
  color: #f3f4f6;
}

.sec-sub {
  margin: 0;
  font-size: 12px;
  color: var(--ov-faint);
}

/* ---------- ② 走势 ---------- */
.ov-trend {
  padding: 16px 18px 12px;
  border: 1px solid var(--ov-line);
  border-radius: 14px;
  background: var(--ov-card);
}

.spark svg {
  display: block;
  width: 100%;
  height: 120px;
}

.spark-axis {
  position: relative;
  height: 16px;
  margin-top: 6px;
  font-size: 11px;
  color: var(--ov-faint);
}

.spark-axis span {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.trend-empty {
  padding: 26px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--ov-faint);
}

/* ---------- ③ 下一步 ---------- */
.ov-steps {
  padding: 16px 18px;
  border: 1px solid var(--ov-line);
  border-radius: 14px;
  background: var(--ov-card);
}

.steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.step {
  /* 竖排：序号绝对定位在左上，正文占满宽度，CTA 落在卡片左下。
     原来是「序号 + 正文 + 右下 CTA」的横排，窄屏上正文被挤成一条 8 字宽的窄柱。 */
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 14px 14px 46px;
  text-align: left;
  border: 1px solid var(--ov-line);
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.6);
  font-family: inherit;
  cursor: pointer;
  transition: border-color 180ms ease, transform 180ms ease, background-color 180ms ease;
}

.step:hover {
  border-color: rgba(96, 165, 250, 0.42);
  background: rgba(23, 37, 63, 0.8);
  transform: translateY(-2px);
}

.step-idx {
  position: absolute;
  left: 14px;
  top: 14px;
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 7px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

.step-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.step-title {
  font-size: 13px;
  font-weight: 650;
  line-height: 1.45;
  color: #f3f4f6;
}

.step-why {
  font-size: 12px;
  line-height: 1.55;
  color: var(--ov-sub);
}

.step-cta {
  align-self: flex-start;
  font-size: 12px;
  font-weight: 600;
  color: #93c5fd;
  white-space: nowrap;
}

.step-cta i {
  font-style: normal;
  margin-left: 3px;
}

/* ---------- ④ 工具 ---------- */
.ov-tools {
  padding: 16px 18px;
  border: 1px solid var(--ov-line);
  border-radius: 14px;
  background: var(--ov-card);
}

.tools {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}

.tool {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 11px 12px;
  border: 1px solid var(--ov-line);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.5);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease;
}

.tool:hover {
  border-color: rgba(96, 165, 250, 0.4);
  background: rgba(23, 37, 63, 0.75);
}

.tool-label {
  font-size: 13px;
  font-weight: 650;
  color: #e5e7eb;
}

.tool-note {
  font-size: 11px;
  color: var(--ov-faint);
}

.tool.locked {
  opacity: 0.55;
}

/* ---------- 骨架 ---------- */
.ov-skeleton {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.sk-card {
  height: 132px;
  border-radius: 14px;
  background: linear-gradient(100deg, #111827 30%, #16202f 50%, #111827 70%);
  background-size: 200% 100%;
  animation: ov-sk 1.4s ease-in-out infinite;
}

@keyframes ov-sk {
  0% { background-position: 120% 0; }
  100% { background-position: -20% 0; }
}

/* ---------- 响应式 ---------- */
@media (max-width: 1180px) {
  .tools {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .ov-stats {
    grid-template-columns: 1fr 1fr;
  }

  .stat-hero {
    grid-column: 1 / -1;
  }

  .steps {
    grid-template-columns: 1fr;
  }

}

@media (max-width: 560px) {
  .ov-stats {
    grid-template-columns: 1fr;
  }

  .tools {
    grid-template-columns: 1fr 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sk-card {
    animation: none;
  }

  .step:hover {
    transform: none;
  }
}
</style>
