<template>
  <div class="console-stat" :class="`is-${tone}`">
    <div class="console-stat__label">
      <span>{{ label }}</span>
      <small v-if="code">{{ code }}</small>
    </div>
    <div class="console-stat__value">
      <b>{{ value }}</b>
      <span v-if="unit">{{ unit }}</span>
    </div>
    <p v-if="detail" class="console-stat__detail">{{ detail }}</p>
  </div>
</template>

<script setup>
// 职责：展示页面传入的单个确定性指标，不计算、不格式化业务数值。
// 输入：标签、值、单位、语气和补充说明。
// 输出：技术仪表样式指标块；调用方负责使用引擎返回值。
defineProps({
  label: {
    type: String,
    required: true
  },
  value: {
    type: [String, Number],
    default: '—'
  },
  unit: {
    type: String,
    default: ''
  },
  code: {
    type: String,
    default: ''
  },
  detail: {
    type: String,
    default: ''
  },
  tone: {
    type: String,
    default: 'neutral'
  }
})
</script>

<style scoped>
.console-stat {
  --cs-accent: var(--cf-mid, #5f6672);
  --cs-soft: rgba(93, 130, 132, 0.08);
  position: relative;
  min-width: 0;
  padding: 13px 14px;
  overflow: hidden;
  border: 1px solid var(--cf-line, #e4e7ee);
  border-radius: var(--cf-radius, 8px);
  background: rgba(255, 255, 255, 0.68);
}

.console-stat::after {
  content: '';
  position: absolute;
  top: 10px;
  right: 10px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--cs-accent);
  box-shadow: 0 0 0 4px var(--cs-soft);
}

.console-stat.is-active {
  --cs-accent: var(--cf-teal, #0f9d8a);
  --cs-soft: rgba(15, 157, 138, 0.1);
}

.console-stat.is-warning {
  --cs-accent: var(--cf-warning, #c98900);
  --cs-soft: rgba(201, 137, 0, 0.1);
}

.console-stat.is-danger {
  --cs-accent: var(--cf-danger, #d83b32);
  --cs-soft: rgba(216, 59, 50, 0.1);
}

.console-stat__label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-right: 14px;
  color: var(--cf-mid, #5f6672);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.console-stat__label small {
  color: var(--cf-faint, #9aa1ad);
  font-size: 8px;
}

.console-stat__value {
  display: flex;
  align-items: baseline;
  gap: 5px;
  margin-top: 8px;
  color: var(--cf-ink, #16181d);
}

.console-stat__value b {
  overflow: hidden;
  font-family: Inter, system-ui, sans-serif;
  font-size: clamp(22px, 2.6vw, 34px);
  font-weight: 700;
  letter-spacing: -0.035em;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.console-stat__value span {
  color: var(--cf-mid, #5f6672);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
}

.console-stat__detail {
  margin: 8px 0 0;
  color: var(--cf-mid, #5f6672);
  font-size: 11px;
  line-height: 1.5;
}
</style>
