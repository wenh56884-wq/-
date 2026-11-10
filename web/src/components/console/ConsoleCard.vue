<template>
  <article class="console-card" :class="{ 'is-dense': dense }">
    <header v-if="title || eyebrow || index || $slots.actions" class="console-card__header">
      <div class="console-card__heading">
        <span v-if="index" class="console-card__index">{{ index }}</span>
        <div>
          <p v-if="eyebrow" class="console-card__eyebrow">{{ eyebrow }}</p>
          <h2 v-if="title" class="console-card__title">{{ title }}</h2>
        </div>
      </div>
      <div v-if="$slots.actions" class="console-card__actions">
        <slot name="actions" />
      </div>
    </header>

    <div class="console-card__body">
      <slot />
    </div>

    <footer v-if="$slots.footer" class="console-card__footer">
      <slot name="footer" />
    </footer>
  </article>
</template>

<script setup>
// 职责：提供 Medusa 式浅青工程仪表盘卡片，只处理视觉与插槽。
// 输入：标题、编号、说明密度与页面提供的内容。
// 输出：无业务逻辑的语义化 article，页面负责真实数据与交互。
defineProps({
  title: {
    type: String,
    default: ''
  },
  eyebrow: {
    type: String,
    default: ''
  },
  index: {
    type: String,
    default: ''
  },
  dense: {
    type: Boolean,
    default: false
  }
})
</script>

<style scoped>
.console-card {
  --cc-bg: rgba(255, 255, 255, 0.78);
  --cc-border: var(--cf-line, #e4e7ee);
  --cc-ink: var(--cf-ink, #16181d);
  --cc-mid: var(--cf-mid, #5f6672);
  --cc-faint: var(--cf-faint, #9aa1ad);
  --cc-coral: var(--cf-coral, #5b5bd6);
  position: relative;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--cc-border);
  border-radius: var(--cf-radius, 8px);
  background: var(--cc-bg);
  box-shadow: var(--cf-shadow, 0 6px 30px rgba(16, 24, 40, 0.08));
  color: var(--cc-ink);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.console-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.95) 18%,
    rgba(255, 255, 255, 0.95) 82%,
    transparent
  );
  pointer-events: none;
}

.console-card__header {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px 12px;
  border-bottom: 1px solid color-mix(in srgb, var(--cc-border) 68%, transparent);
}

.console-card__heading {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 10px;
}

.console-card__index {
  display: inline-grid;
  min-width: 25px;
  height: 22px;
  place-items: center;
  padding: 0 5px;
  border: 1px solid rgba(91, 91, 214, 0.34);
  border-radius: 3px;
  color: var(--cc-coral);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.console-card__eyebrow,
.console-card__title {
  margin: 0;
}

.console-card__eyebrow {
  margin-bottom: 3px;
  color: var(--cc-faint);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.console-card__title {
  overflow: hidden;
  color: var(--cc-ink);
  font-size: 14px;
  font-weight: 650;
  letter-spacing: 0.01em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.console-card__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.console-card__body {
  padding: 16px 18px;
}

.console-card__footer {
  padding: 10px 18px 12px;
  border-top: 1px solid rgba(228, 231, 238, 0.72);
  color: var(--cc-mid);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.08em;
}

.console-card.is-dense .console-card__header {
  padding: 12px 14px 10px;
}

.console-card.is-dense .console-card__body {
  padding: 12px 14px;
}

.console-card.is-dense .console-card__footer {
  padding: 8px 14px 10px;
}

@media (max-width: 640px) {
  .console-card__header {
    padding: 14px 14px 11px;
  }

  .console-card__body {
    padding: 14px;
  }
}
</style>
