<template>
  <div
    class="agent-pipeline"
    :class="[`is-${status}`, { 'is-compact': compact }]"
    :aria-label="`智能体执行链路：${statusText}`"
  >
    <div
      v-for="(stage, index) in stages"
      :key="stage.key"
      class="pipe-stage"
      :class="stageClass(index)"
    >
      <span class="pipe-node">{{ index + 1 }}</span>
      <span class="pipe-label">{{ stage.label }}</span>
      <span v-if="index < stages.length - 1" class="pipe-connector" aria-hidden="true" />
    </div>
    <span v-if="attempts > 1" class="pipe-retry">第 {{ attempts }} 稿</span>
  </div>
</template>

<script setup>
// AgentPipeline：把「意图识别 → 工具取数 → 文本生成 → Critic 回查 → 输出」
// 画成一条可读的链路。既用于每条回答的回查卡，也用于教师端质量页。

import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: 'passed' }, // passed | retry | degraded | idle
  attempts: { type: Number, default: 1 },
  compact: { type: Boolean, default: false }
})

const stages = [
  { key: 'plan', label: '意图识别' },
  { key: 'tool', label: '工具取数' },
  { key: 'draft', label: '文本生成' },
  { key: 'critic', label: 'Critic 回查' },
  { key: 'output', label: '输出' }
]

const statusText = computed(() => ({
  passed: '全部通过',
  retry: '回查驳回后重写',
  degraded: '超限降级',
  idle: '等待执行'
}[props.status] || props.status))

function stageClass(index) {
  const isCritic = index === 3
  const isOutput = index === 4
  if (props.status === 'degraded' && (isCritic || isOutput)) return 'is-bad'
  if (props.status === 'retry' && isCritic) return 'is-warn'
  if (props.status === 'passed' && (isCritic || isOutput)) return 'is-ok'
  if (props.status === 'idle') return 'is-idle'
  return ''
}
</script>

<style scoped>
.agent-pipeline {
  display: flex;
  align-items: center;
  gap: 0;
  width: 100%;
  min-width: 0;
  padding: 10px 4px 4px;
}

.pipe-stage {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  flex: 1 1 0;
  min-width: 0;
}

.pipe-node {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border: 1px solid #d9e2ea;
  border-radius: 50%;
  background: #fff;
  color: #7b8794;
  font-family: var(--cf-font-mono);
  font-size: 10px;
  font-weight: 600;
  position: relative;
  z-index: 1;
}

.pipe-label {
  color: #667085;
  font-size: 11px;
  line-height: 1.3;
  text-align: center;
  white-space: nowrap;
}

.pipe-connector {
  position: absolute;
  top: 11px;
  left: calc(50% + 14px);
  right: calc(-50% + 14px);
  height: 1px;
  background: #d9e1ea;
  z-index: 0;
}

.pipe-stage.is-ok .pipe-node {
  border-color: #0f9d8a;
  background: #e8f8f4;
  color: #0b7d70;
}

.pipe-stage.is-warn .pipe-node {
  border-color: #d99a00;
  background: #fff7e6;
  color: #9a5b00;
}

.pipe-stage.is-bad .pipe-node {
  border-color: #d83b32;
  background: #fff0ef;
  color: #b42318;
}

.pipe-stage.is-ok .pipe-label { color: #0b7d70; }
.pipe-stage.is-warn .pipe-label { color: #9a5b00; }
.pipe-stage.is-bad .pipe-label { color: #b42318; }

.pipe-stage.is-idle .pipe-node {
  border-color: #cfd6df;
  background: #f7f9fb;
  color: #8a94a6;
}

.pipe-retry {
  flex: 0 0 auto;
  margin-left: 4px;
  padding: 3px 8px;
  border-radius: 999px;
  background: #fff7e6;
  color: #9a5b00;
  font-size: 10px;
  white-space: nowrap;
}

.agent-pipeline.is-degraded .pipe-connector {
  background: linear-gradient(90deg, #e4e9ef, #f5c5c1);
}

/* 紧凑版：聊天卡内不占太多高度 */
.agent-pipeline.is-compact {
  padding: 6px 0 0;
}

.agent-pipeline.is-compact .pipe-node {
  width: 18px;
  height: 18px;
  font-size: 9px;
}

.agent-pipeline.is-compact .pipe-label {
  font-size: 10px;
}

.agent-pipeline.is-compact .pipe-connector {
  top: 9px;
}

@media (max-width: 520px) {
  .pipe-label {
    font-size: 10px;
    white-space: normal;
  }

  .agent-pipeline.is-compact .pipe-label {
    font-size: 9px;
  }
}
</style>
