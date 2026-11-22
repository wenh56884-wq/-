<!-- 板块内的二级导航：浅色分段控件 + 当前分段的一句话说明。
     全站所有「聚合板块」（学业 / 机会库 / 生涯规划 / 学生 / 模拟面试）共用这一个组件，
     避免每个板块各写一套 tab 样式导致观感漂移。 -->
<template>
  <div class="hubbar" :class="{ 'is-flat': flat }">
    <div class="hubbar-inner">
      <div class="seg" role="tablist" :aria-label="ariaLabel">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="seg-btn"
          :class="{ on: modelValue === t.key }"
          type="button"
          role="tab"
          :aria-selected="modelValue === t.key"
          @click="pick(t.key)"
        >
          <span class="seg-label">{{ t.label }}</span>
        </button>
      </div>
      <p v-if="activeHint" class="seg-hint">{{ activeHint }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  tabs: { type: Array, required: true },
  modelValue: { type: String, required: true },
  ariaLabel: { type: String, default: '板块切换' },
  // flat：不吸顶，用于已经在卡片内部嵌一级导航的场景
  flat: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'change'])

const activeHint = computed(
  () => props.tabs.find((t) => t.key === props.modelValue)?.hint || ''
)

function pick(key) {
  if (key === props.modelValue) return
  emit('update:modelValue', key)
  emit('change', key)
}
</script>

<style scoped>
/* 顶栏 64px（桌面）/ 60px（窄屏）之下吸顶，翻页时二级导航一直可见 */
.hubbar {
  position: sticky;
  top: 64px;
  z-index: 22;
  padding: 10px 0;
  background: rgba(247, 248, 250, 0.9);
  backdrop-filter: saturate(180%) blur(14px);
  -webkit-backdrop-filter: saturate(180%) blur(14px);
  border-bottom: 1px solid rgba(228, 231, 238, 0.9);
}

.hubbar.is-flat {
  position: static;
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  border-bottom: 0;
  padding: 0;
}

.hubbar-inner {
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 38px;
  padding: 0 24px;
}

.seg {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  background: #ffffff;
  border: 1px solid var(--cf-line);
  border-radius: 11px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
  overflow-x: auto;
  scrollbar-width: none;
}

.seg::-webkit-scrollbar {
  display: none;
}

.seg-btn {
  position: relative;
  flex: 0 0 auto;
  padding: 7px 15px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--cf-mid);
  font-family: inherit;
  font-size: 13.5px;
  font-weight: 550;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 160ms ease, color 160ms ease, box-shadow 160ms ease;
}

.seg-btn:hover {
  color: var(--cf-ink);
  background: #f2f4f8;
}

.seg-btn.on {
  color: #fff;
  background: linear-gradient(135deg, #2563eb, #1951c3);
  box-shadow: 0 4px 12px rgba(25, 81, 195, 0.28);
}

.seg-hint {
  margin: 0;
  min-width: 0;
  font-size: 12px;
  color: var(--cf-faint);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 1023px) {
  .hubbar {
    top: 60px;
    padding: 8px 0;
  }

  .hubbar-inner {
    padding: 0 16px;
    gap: 10px;
  }

  .seg-btn {
    padding: 7px 13px;
    min-height: 36px;
  }

  .seg-hint {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .seg-btn {
    transition: none;
  }
}
</style>
