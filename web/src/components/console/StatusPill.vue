<template>
  <span class="status-pill" :class="`is-${tone}`">
    <i aria-hidden="true" />
    <span>{{ label }}</span>
  </span>
</template>

<script setup>
// 职责：统一展示运行、告警、危险和中性状态。
// 输入：状态文案与语义语气；颜色不是唯一识别方式。
// 输出：带文字和状态点的轻量 pill，不推断业务状态。
defineProps({
  label: {
    type: String,
    required: true
  },
  tone: {
    type: String,
    default: 'neutral'
  }
})
</script>

<style scoped>
.status-pill {
  --sp-color: var(--cf-mid, #5f6672);
  --sp-bg: rgba(93, 130, 132, 0.08);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 3px 8px;
  border: 1px solid color-mix(in srgb, var(--sp-color) 24%, transparent);
  border-radius: 999px;
  background: var(--sp-bg);
  color: var(--sp-color);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.09em;
  line-height: 1;
  text-transform: uppercase;
  white-space: nowrap;
}

.status-pill i {
  width: 5px;
  height: 5px;
  flex: 0 0 5px;
  border-radius: 50%;
  background: currentColor;
}

.status-pill.is-active {
  --sp-color: var(--cf-teal, #0f9d8a);
  --sp-bg: var(--cf-teal-soft, #ddf6f1);
}

.status-pill.is-warning {
  --sp-color: var(--cf-warning, #c98900);
  --sp-bg: rgba(201, 137, 0, 0.09);
}

.status-pill.is-danger {
  --sp-color: var(--cf-danger, #d83b32);
  --sp-bg: rgba(216, 59, 50, 0.09);
}

.status-pill.is-idle {
  --sp-color: var(--cf-faint, #9aa1ad);
  --sp-bg: rgba(157, 188, 188, 0.1);
}
</style>
