<template>
  <details class="agent-trace" :class="{ 'is-degraded': degraded }">
    <summary class="agent-trace__summary">
      <span class="trace-status-dot" :class="dotClass" />
      <span class="agent-trace__title">执行与回查</span>
      <span class="trace-status-pill" :class="dotClass">{{ statusLabel }}</span>
      <span class="agent-trace__count">
        {{ claims.length ? `已核对 ${claims.length} 个数值` : '本轮无数值' }}
      </span>
      <svg class="agent-trace__chevron" viewBox="0 0 12 8" aria-hidden="true">
        <path d="M1 1.5 6 6.5l5-5" fill="none" stroke="currentColor" stroke-width="1.4"
          stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </summary>

    <div class="agent-trace__body">
      <AgentPipeline
        :status="pipelineStatus"
        :attempts="attempts"
        compact
      />

      <div class="trace-meta">
        <span><i>工具</i><b>{{ toolName || '—' }}</b></span>
        <span><i>生成</i><b>{{ draftModeText }}</b></span>
        <span><i>规划</i><b>{{ plannerText }}</b></span>
        <span><i>回查</i><b>{{ criticVersion || 'critic' }}</b></span>
      </div>

      <div v-if="claims.length" class="trace-claims">
        <span class="trace-claims-label">本轮核对</span>
        <span
          v-for="(claim, index) in claims.slice(0, 12)"
          :key="`${claim.raw}-${index}`"
          class="trace-claim"
        >{{ claim.raw }}{{ unitLabel(claim.unit) }}</span>
        <span v-if="claims.length > 12" class="trace-claim is-more">+{{ claims.length - 12 }}</span>
      </div>

      <div v-if="problems.length" class="trace-problems">
        <p v-for="(problem, index) in problems" :key="index">{{ problem }}</p>
      </div>

      <details v-if="steps.length" class="trace-steps">
        <summary>自主大脑执行步骤 · {{ steps.length }} 步</summary>
        <div v-for="step in steps" :key="step.index" class="trace-step">
          <div class="trace-step-head">
            <span class="trace-step-index">{{ step.index }}</span>
            <span class="trace-step-tool">{{ step.tool }}</span>
            <span class="trace-step-ok" :class="{ bad: !step.ok }">
              {{ step.ok ? '成功' : '失败' }}
            </span>
            <span v-if="step.elapsed_ms" class="trace-step-cost">{{ step.elapsed_ms }} ms</span>
            <span class="trace-step-purpose">{{ step.purpose }}</span>
          </div>
          <div v-if="step.observation" class="trace-step-obs">{{ step.observation }}</div>
        </div>
      </details>

      <div class="trace-foot">
        <span>trace {{ traceId || '—' }}</span>
        <span v-if="engineVersion">引擎 {{ engineVersion }}</span>
        <span v-if="calcVersion">画像 {{ calcVersion }}</span>
        <span v-if="graphVersion">编排 {{ graphVersion }}</span>
      </div>
    </div>
  </details>
</template>

<script setup>
// AgentTracePanel：每条回答的「执行与回查」卡。
// 把 plan → tool → draft → critic → output 和 Critic 抽出的数值原样展示出来，
// 让「大模型只表达、数字由引擎算、回查通过才输出」变成用户可见的产品能力。

import { computed } from 'vue'
import AgentPipeline from './AgentPipeline.vue'

const props = defineProps({
  trace: { type: Object, default: () => ({}) }
})

const verdict = computed(() => props.trace.verdict || {})
const claims = computed(() => verdict.value.claims || [])
const attempts = computed(() => Number(props.trace.attempts || 1))
const degraded = computed(() => Boolean(props.trace.degraded))
const steps = computed(() => props.trace.steps || [])
const toolName = computed(() => props.trace.tool || props.trace.tool_name || '')
const traceId = computed(() => props.trace.trace_id || '')
const engineVersion = computed(() => props.trace.engine_version || '')
const calcVersion = computed(() => props.trace.calc_version || '')
const graphVersion = computed(() => props.trace.graph_version || '')
const criticVersion = computed(() => props.trace.critic_version || '')

const passed = computed(() => Boolean(verdict.value.passed))
const pipelineStatus = computed(() => {
  if (degraded.value) return 'degraded'
  if (passed.value) return 'passed'
  if (Object.keys(verdict.value).length) return 'retry'
  return 'idle'
})
const dotClass = computed(() => {
  if (degraded.value) return 'is-bad'
  if (passed.value) return 'is-ok'
  return 'is-warn'
})
const statusLabel = computed(() => {
  if (degraded.value) return '降级输出'
  if (passed.value) return attempts.value > 1 ? `重写 ${attempts.value - 1} 次后通过` : '回查通过'
  return '回查未完成'
})
const draftModeText = computed(() => ({
  draft: '模型表达',
  template: '模板直引',
  positions: '职位明细',
  rag: '引用表达',
  workflow: '工作流',
  chitchat: '纯对话',
  brain: '大脑汇总',
  injected: '注入结果'
}[props.trace.draft_mode] || props.trace.draft_mode || '—'))
const plannerText = computed(() => ({
  brain: '自主大脑',
  auto: '模型选工具',
  graph: '规则路由'
}[props.trace.planner] || props.trace.planner || '规则路由'))

const problems = computed(() => [
  ...(verdict.value.mismatches || []),
  ...(verdict.value.fuzzy || [])
])

function unitLabel(unit) {
  return {
    person: '人',
    percent: '%',
    score: '分',
    course: '门',
    count: '',
    rank: '名',
    term: '学期',
    version: '版',
    rowref: '条'
  }[unit] ?? ''
}
</script>

<style scoped>
.agent-trace {
  margin-top: 10px;
  border: 1px solid #e6ebf1;
  border-radius: 12px;
  background: #fbfcfe;
  overflow: hidden;
}

.agent-trace.is-degraded {
  border-color: #f3cbc8;
  background: #fffafa;
}

.agent-trace__summary {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 11px;
  cursor: pointer;
  list-style: none;
  user-select: none;
}

.agent-trace__summary::-webkit-details-marker {
  display: none;
}

.trace-status-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 50%;
  background: #c9a227;
}

.trace-status-dot.is-ok { background: #0f9d8a; }
.trace-status-dot.is-warn { background: #d99a00; }
.trace-status-dot.is-bad { background: #d83b32; }

.agent-trace__title {
  flex: 0 0 auto;
  color: #35435f;
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}

.trace-status-pill {
  padding: 2px 7px;
  border-radius: 999px;
  background: #fff7e6;
  color: #9a5b00;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}

.trace-status-pill.is-ok { background: #e8f8f4; color: #0b7d70; }
.trace-status-pill.is-warn { background: #fff7e6; color: #9a5b00; }
.trace-status-pill.is-bad { background: #fff0ef; color: #b42318; }

.agent-trace__count {
  margin-left: auto;
  color: #8a94a6;
  font-size: 10.5px;
  white-space: nowrap;
}

.agent-trace__chevron {
  width: 11px;
  height: 8px;
  flex: 0 0 11px;
  color: #9aa4b2;
  transition: transform 180ms ease;
}

.agent-trace[open] .agent-trace__chevron {
  transform: rotate(180deg);
}

.agent-trace__body {
  padding: 0 11px 10px;
  border-top: 1px solid #eef2f6;
}

.trace-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  padding: 8px 0 0;
  font-size: 10.5px;
}

.trace-meta span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.trace-meta i {
  color: #8a94a6;
  font-style: normal;
}

.trace-meta b {
  color: #35435f;
  font-weight: 600;
  font-family: var(--cf-font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-claims {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 9px;
}

.trace-claims-label {
  color: #8a94a6;
  font-size: 10.5px;
  margin-right: 2px;
}

.trace-claim {
  padding: 2px 6px;
  border: 1px solid #dbe6ee;
  border-radius: 6px;
  background: #fff;
  color: #31506f;
  font-family: var(--cf-font-mono);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}

.trace-claim.is-more {
  color: #8a94a6;
  border-style: dashed;
}

.trace-problems {
  margin-top: 9px;
  padding: 7px 9px;
  border-radius: 8px;
  background: #fff0ef;
  color: #b42318;
  font-size: 10.5px;
  line-height: 1.6;
}

.trace-problems p {
  margin: 0;
}

.trace-steps {
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px dashed #e6ebf1;
}

.trace-steps > summary {
  color: #52617b;
  font-size: 10.5px;
  font-weight: 600;
  cursor: pointer;
}

.trace-step {
  margin-top: 7px;
}

.trace-step-head {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
  color: #52617b;
  font-size: 10.5px;
}

.trace-step-index {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #eef3f8;
  color: #52617b;
  font-family: var(--cf-font-mono);
  font-size: 9px;
}

.trace-step-tool {
  color: #315db1;
  font-family: var(--cf-font-mono);
}

.trace-step-ok { color: #0b7d70; }
.trace-step-ok.bad { color: #b42318; }

/* 每步耗时：并发执行后这几个数字是「真的并行了」最直观的证据 */
.trace-step-cost {
  color: #7b8794;
  font-variant-numeric: tabular-nums;
  font-size: 10px;
}

.trace-step-purpose {
  color: #7b8794;
  min-width: 0;
}

.trace-step-obs {
  margin: 3px 0 0 22px;
  color: #7b8794;
  font-size: 10px;
  line-height: 1.55;
}

.trace-foot {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 9px;
  padding-top: 7px;
  border-top: 1px dashed #e6ebf1;
  color: #9aa4b2;
  font-family: var(--cf-font-mono);
  font-size: 9.5px;
}
</style>
