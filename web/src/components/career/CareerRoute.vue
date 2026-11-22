<template>
  <section class="career-route" aria-label="四年生涯航线">
    <header v-if="direction || grade" class="route-head">
      <span class="route-eyebrow">CAREER ROUTE</span>
      <div class="route-meta">
        <span v-if="direction">方向 · <b>{{ direction }}</b></span>
        <span v-if="grade">当前 · <b>{{ grade }}</b></span>
      </div>
    </header>

    <div v-if="!routeSteps.length" class="route-empty">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 17c2.8 0 3.6-3 6-3s3.2 3 6 3 4-2.5 4-2.5" />
        <circle cx="4" cy="17" r="1.4" />
        <circle cx="20" cy="14.5" r="1.4" />
      </svg>
      <p>暂无可用规划数据</p>
      <small>规划引擎返回后会自动画出生涯航线</small>
    </div>

    <template v-else>
      <ol class="route-track">
        <li
          v-for="(item, index) in routeSteps"
          :key="`${item.stage}-${index}`"
          class="route-item"
          :class="[`is-${item.status}`, { 'is-active': index === activeIndex }]"
        >
          <button
            type="button"
            class="route-node"
            :aria-pressed="index === activeIndex"
            :aria-label="`${item.stage}：${item.goal || '查看阶段详情'}`"
            @click="activeIndex = index"
          >
            <span class="route-dot" aria-hidden="true">
              <svg v-if="item.status === 'past'" viewBox="0 0 24 24">
                <path d="M5.5 12.5l4.2 4.2 8.8-8.8" />
              </svg>
              <i v-else />
            </span>
            <span class="route-labels">
              <span class="route-year">{{ item.year }}</span>
              <span v-if="item.theme" class="route-theme">{{ item.theme }}</span>
            </span>
          </button>
        </li>
      </ol>

      <div class="route-detail" aria-live="polite">
        <div class="detail-top">
          <span class="detail-stage">{{ activeItem.stage }}</span>
          <span class="detail-status" :class="`is-${activeItem.status}`">
            {{ STATUS_TEXT[activeItem.status] }}
          </span>
        </div>
        <p v-if="activeItem.goal" class="detail-goal">{{ activeItem.goal }}</p>
        <ul v-if="activeItem.actions.length" class="detail-actions">
          <li v-for="(action, index) in activeItem.actions" :key="index">{{ action }}</li>
        </ul>
        <p v-if="!activeItem.goal && !activeItem.actions.length" class="detail-empty">
          该阶段暂无目标与行动数据
        </p>
      </div>
    </template>
  </section>
</template>

<script setup>
// CareerRoute：学生端「四年生涯航线」时间轴。
// 只展示引擎返回的 steps / all_steps 文本（阶段、目标、行动），不生成任何数值或计划文案；
// 当前阶段由 grade 对应的 stage 推导，只影响节点状态标记，不改变规划内容。

import { computed, ref, watch } from 'vue'

const props = defineProps({
  allSteps: { type: Array, default: () => [] },
  steps: { type: Array, default: () => [] },
  stage: { type: String, default: 'unknown' },
  grade: { type: String, default: '' },
  direction: { type: String, default: '' }
})

const YEAR_ORDER = ['大一', '大二', '大三', '大四', '毕业后']
const STAGE_YEAR = {
  freshman: '大一',
  sophomore: '大二',
  junior: '大三',
  senior: '大四',
  graduated: '毕业后'
}
const GRADE_YEAR = { 大一: '大一', 大二: '大二', 大三: '大三', 大四: '大四', 已毕业: '毕业后' }
const STATUS_TEXT = { past: '已走过', current: '当前阶段', future: '未来阶段', plain: '规划节点' }

// stage 缺失的旧后端回退到 grade 文本；两者都来自引擎，不在前端推断年级
const currentYear = computed(() => STAGE_YEAR[props.stage] || GRADE_YEAR[props.grade] || '')

// 优先完整四年主线；旧后端没有 all_steps 时回退剩余阶段。
// 已毕业等场景下 steps 可能出现主线之外的「毕业后」节点，按阶段名去重后追加，内容仍全部来自引擎。
const sourceSteps = computed(() => {
  const full = (props.allSteps || []).filter(Boolean)
  const remaining = (props.steps || []).filter(Boolean)
  if (!full.length) return remaining
  const seen = new Set(full.map((step) => String(step['阶段'] || '')))
  const extra = remaining.filter((step) => !seen.has(String(step['阶段'] || '')))
  return extra.length ? [...full, ...extra] : full
})

function statusOf(label) {
  const text = String(label || '')
  const year = YEAR_ORDER.find((item) => text.startsWith(item)) || ''
  if (!currentYear.value) return text.includes('当前') ? 'current' : 'plain'
  if (!year) return text.includes('当前') ? 'current' : 'plain'
  const itemIndex = YEAR_ORDER.indexOf(year)
  const currentIndex = YEAR_ORDER.indexOf(currentYear.value)
  if (itemIndex === currentIndex) return 'current'
  return itemIndex < currentIndex ? 'past' : 'future'
}

const routeSteps = computed(() =>
  sourceSteps.value.map((step) => {
    const stageText = String(step['阶段'] || '')
    const [year, ...themeParts] = stageText.split(' · ')
    return {
      stage: stageText || '—',
      year: year || stageText || '—',
      theme: themeParts.join(' · '),
      goal: String(step['目标'] || ''),
      actions: Array.isArray(step['行动']) ? step['行动'].map(String) : [],
      status: statusOf(stageText)
    }
  })
)

const activeIndex = ref(0)
const activeItem = computed(() => routeSteps.value[activeIndex.value] || routeSteps.value[0])

function defaultActiveIndex() {
  if (!routeSteps.value.length) return 0
  const current = routeSteps.value.findIndex((item) => item.status === 'current')
  if (current >= 0) return current
  const future = routeSteps.value.findIndex((item) => item.status === 'future')
  return future >= 0 ? future : routeSteps.value.length - 1
}

watch(
  routeSteps,
  () => {
    activeIndex.value = defaultActiveIndex()
  },
  { immediate: true }
)
</script>

<style scoped>
.career-route {
  --route-accent: var(--bento-accent, #1951c3);
  --route-accent-soft: var(--bento-accent-soft, #e9efff);
  --route-line: var(--bento-border, #e4e7ee);

  margin-top: 12px;
}

.route-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.route-eyebrow {
  color: var(--bento-mute, #6b7280);
  font-family: var(--cf-font-mono, ui-monospace, monospace);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
}

.route-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  color: var(--bento-mute, #6b7280);
  font-size: 12.5px;
}

.route-meta b {
  color: var(--bento-sub, #5f6672);
  font-weight: 650;
}

/* 桌面：四个阶段等分横排，连接线从上一节点圆心画到当前节点圆心 */
.route-track {
  display: flex;
  align-items: stretch;
  margin: 0;
  padding: 0;
  list-style: none;
}

.route-item {
  position: relative;
  flex: 1 1 0;
  min-width: 0;
}

.route-item + .route-item::before {
  position: absolute;
  top: 17px;
  left: -50%;
  z-index: 0;
  width: 100%;
  height: 2px;
  background: var(--route-line);
  content: '';
  transition: background-color 200ms var(--bento-ease, ease);
}

.route-item.is-past::before,
.route-item.is-current::before {
  background: var(--route-accent);
}

.route-node {
  position: relative;
  z-index: 1;
  display: flex;
  width: 100%;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 5px 6px 4px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  font-family: inherit;
  text-align: center;
  cursor: pointer;
  transition: background-color 180ms var(--bento-ease, ease);
}

.route-node:hover {
  background: rgba(25, 81, 195, 0.05);
}

.route-node:focus-visible {
  outline: 2px solid var(--route-accent);
  outline-offset: 2px;
}

.route-dot {
  position: relative;
  z-index: 1;
  display: grid;
  width: 26px;
  height: 26px;
  box-sizing: border-box;
  place-items: center;
  margin-bottom: 4px;
  border: 2px solid var(--bento-border-strong, #cfd4de);
  border-radius: 50%;
  background: #fff;
  color: #fff;
  transition:
    border-color 180ms ease,
    background-color 180ms ease,
    box-shadow 180ms ease,
    transform 180ms ease;
}

.route-dot svg {
  width: 13px;
  height: 13px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.route-dot i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--bento-border-strong, #cfd4de);
}

.route-node:hover .route-dot {
  border-color: var(--route-accent);
  transform: translateY(-1px);
}

.route-item.is-past .route-dot,
.route-item.is-current .route-dot {
  border-color: var(--route-accent);
  background: var(--route-accent);
}

.route-item.is-current .route-dot {
  box-shadow: 0 0 0 5px var(--route-accent-soft);
}

.route-item.is-current .route-dot i {
  background: #fff;
}

.route-item.is-future .route-dot {
  border-style: dashed;
}

.route-item.is-active:not(.is-current) .route-dot {
  box-shadow: 0 0 0 4px var(--route-accent-soft);
}

.route-labels {
  display: flex;
  width: 100%;
  min-width: 0;
  flex-direction: column;
  align-items: center;
  gap: 1px;
}

.route-year {
  color: var(--bento-sub, #5f6672);
  font-family: var(--cf-font-mono, ui-monospace, monospace);
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.route-item.is-current .route-year,
.route-item.is-active .route-year {
  color: var(--route-accent);
}

.route-theme {
  overflow: hidden;
  max-width: 100%;
  color: var(--bento-mute, #6b7280);
  font-size: 12px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.route-detail {
  margin-top: 14px;
  padding: 12px 14px 13px;
  border: 1px solid var(--bento-border, #e4e7ee);
  border-radius: 12px;
  background: linear-gradient(160deg, #ffffff 0%, #f8faff 100%);
}

.detail-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px 10px;
  flex-wrap: wrap;
}

.detail-stage {
  color: var(--bento-text, #16181d);
  font-size: 14px;
  font-weight: 650;
}

.detail-status {
  flex: 0 0 auto;
  padding: 2px 9px;
  border: 1px solid var(--bento-border, #e4e7ee);
  border-radius: 999px;
  background: #fff;
  color: var(--bento-mute, #6b7280);
  font-size: 11.5px;
}

.detail-status.is-current {
  border-color: #baccf0;
  background: var(--route-accent-soft);
  color: var(--route-accent);
}

.detail-status.is-past {
  border-color: #b7e6db;
  background: #eefaf6;
  color: #0b7a6b;
}

.detail-goal {
  margin: 7px 0 0;
  color: var(--bento-sub, #5f6672);
  font-size: 13.5px;
  line-height: 1.65;
}

.detail-actions {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 9px 0 0;
  padding: 0;
  list-style: none;
}

.detail-actions li {
  position: relative;
  padding-left: 15px;
  color: var(--bento-text, #16181d);
  font-size: 13.5px;
  line-height: 1.6;
}

.detail-actions li::before {
  position: absolute;
  top: 9px;
  left: 2px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--route-accent);
  content: '';
}

.detail-empty {
  margin: 8px 0 0;
  color: var(--bento-mute, #6b7280);
  font-size: 13px;
}

.route-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 22px 14px;
  border: 1px dashed var(--bento-border-strong, #cfd4de);
  border-radius: 12px;
  background: #fbfcff;
  text-align: center;
}

.route-empty svg {
  width: 30px;
  height: 30px;
  fill: none;
  stroke: var(--bento-border-strong, #cfd4de);
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.route-empty p {
  margin: 2px 0 0;
  color: var(--bento-sub, #5f6672);
  font-size: 13.5px;
  font-weight: 600;
}

.route-empty small {
  color: var(--bento-mute, #6b7280);
  font-size: 12px;
}

/* 移动端：纵向时间轴，圆点靠左，连接线上下贯通 */
@media (max-width: 640px) {
  .route-track {
    flex-direction: column;
  }

  .route-item {
    flex: none;
    width: 100%;
  }

  .route-item + .route-item::before {
    display: none;
  }

  .route-node {
    flex-direction: row;
    align-items: flex-start;
    gap: 10px;
    padding: 6px 4px;
    text-align: left;
  }

  .route-dot {
    flex: 0 0 26px;
    margin-bottom: 0;
  }

  .route-labels {
    align-items: flex-start;
    padding-top: 3px;
  }

  .route-theme {
    white-space: normal;
  }

  .route-node::before,
  .route-node::after {
    position: absolute;
    left: 16px;
    z-index: 0;
    width: 2px;
    background: var(--route-line);
    content: '';
  }

  .route-node::before {
    top: 0;
    height: 19px;
  }

  .route-item:first-child .route-node::before {
    display: none;
  }

  .route-item.is-past .route-node::before,
  .route-item.is-current .route-node::before,
  .route-item.is-past .route-node::after {
    background: var(--route-accent);
  }

  .route-node::after {
    top: 19px;
    bottom: 0;
  }

  .route-item:last-child .route-node::after {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .route-item + .route-item::before,
  .route-node,
  .route-dot {
    transition: none;
  }

  .route-node:hover .route-dot {
    transform: none;
  }
}
</style>
