<template>
  <section class="route-hero" :class="`route-hero--${tone}`">
    <div class="route-hero__ambient" aria-hidden="true" />
    <BrandRoute
      variant="strip"
      :tone="tone === 'student' ? 'teal' : 'gold'"
      class="route-hero__line"
      style="inset: auto 0 0 0; height: 46px"
    />

    <div class="route-hero__content">
      <div class="route-hero__copy">
        <p v-if="eyebrow" class="route-hero__eyebrow">{{ eyebrow }}</p>
        <h2 class="route-hero__title">{{ title }}</h2>
        <p v-if="desc" class="route-hero__desc">{{ desc }}</p>
        <div v-if="$slots.actions" class="route-hero__actions">
          <slot name="actions" />
        </div>
      </div>

      <div v-if="stats.length" class="route-hero__stats">
        <div
          v-for="(stat, index) in stats"
          :key="stat.label"
          class="route-stat"
          :class="stat.tone ? `route-stat--${stat.tone}` : ''"
          :style="{ '--qh-index': index }"
        >
          <span class="route-stat__label">{{ stat.label }}</span>
          <b class="route-stat__value">
            {{ stat.value }}<small v-if="stat.suffix">{{ stat.suffix }}</small>
          </b>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
// RouteHero：教师/学生首页的「航线页头」。
// 登录页用完整叙事场景；进入工作台后只保留一条安静的品牌航线 + 结论 + 指标，
// 不再重复整块视频 hero，把首屏让给业务结论。

import BrandRoute from './BrandRoute.vue'

defineProps({
  tone: { type: String, default: 'teacher' },
  eyebrow: { type: String, default: '' },
  title: { type: String, default: '' },
  desc: { type: String, default: '' },
  // [{ label, value, suffix?, tone?: 'red'|'orange'|'yellow'|'good'|'unknown' }]
  stats: { type: Array, default: () => [] }
})
</script>

<style scoped>
.route-hero {
  position: relative;
  overflow: hidden;
  min-height: 160px;
  padding: 26px 30px 30px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  color: #f4fffd;
  box-shadow: 0 18px 44px rgba(8, 24, 28, 0.16);
}

.route-hero--teacher {
  --hero-glow-a: rgba(43, 123, 120, 0.22);
  --hero-glow-b: rgba(111, 201, 193, 0.12);
  background:
    radial-gradient(520px 240px at 86% 0%, rgba(43, 123, 120, 0.3), transparent 66%),
    linear-gradient(118deg, #071a20 0%, #0b2830 58%, #0a1e27 100%);
}

.route-hero--student {
  --hero-glow-a: rgba(216, 180, 90, 0.16);
  --hero-glow-b: rgba(241, 213, 143, 0.1);
  background:
    radial-gradient(520px 240px at 88% 6%, rgba(216, 180, 90, 0.2), transparent 66%),
    linear-gradient(118deg, #071a20 0%, #0b2a30 58%, #0a1e27 100%);
}

/* 极淡品牌色氛围光斑：只动 transform/opacity，缓慢漂移不抢内容 */
.route-hero__ambient {
  position: absolute;
  inset: -18%;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(38% 46% at 22% 28%, var(--hero-glow-a), transparent 70%),
    radial-gradient(30% 40% at 76% 72%, var(--hero-glow-b), transparent 72%);
  animation: hero-ambient-drift 28s ease-in-out infinite alternate;
  will-change: transform;
}

@keyframes hero-ambient-drift {
  from {
    transform: translate3d(-2%, -1.5%, 0) scale(1);
  }
  to {
    transform: translate3d(2%, 2%, 0) scale(1.06);
  }
}

.route-hero__line {
  opacity: 0.72;
}

.route-hero__content {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
  width: 100%;
}

.route-hero__copy {
  flex: 1 1 420px;
  min-width: 0;
}

.route-hero__eyebrow {
  position: relative;
  overflow: hidden;
  display: inline-flex;
  align-items: center;
  margin: 0 0 10px;
  padding: 4px 10px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(236, 248, 244, 0.8);
  font-family: var(--cf-font-mono);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.04em;
  animation: hero-rise 0.6s cubic-bezier(0.22, 0.61, 0.36, 1) 0.05s both;
}

/* eyebrow 一次性扫光：低亮度，不霓虹 */
.route-hero__eyebrow::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(105deg, transparent 32%, rgba(255, 255, 255, 0.24) 50%, transparent 68%);
  transform: translateX(-130%);
  animation: hero-shimmer 1.1s ease 0.55s forwards;
  pointer-events: none;
}

.route-hero__title {
  margin: 0;
  max-width: 62ch;
  color: #f6fffd;
  font-size: clamp(17px, 1.5vw, 22px);
  font-weight: 650;
  line-height: 1.5;
  letter-spacing: -0.01em;
  text-wrap: balance;
  /* 允许在空格/标点处换行，但不把「预警」这类中文词拆成两行 */
  word-break: keep-all;
  overflow-wrap: anywhere;
  animation: hero-title-in 0.7s cubic-bezier(0.22, 0.61, 0.36, 1) 0.16s both;
}

.route-hero__desc {
  margin: 8px 0 0;
  max-width: 68ch;
  color: rgba(226, 244, 242, 0.64);
  font-size: 13px;
  line-height: 1.7;
  animation: hero-rise 0.65s ease 0.34s both;
}

.route-hero__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 15px;
  animation: hero-rise 0.65s ease 0.62s both;
}

/* 暗底上的按钮：主按钮白底深字，次按钮玻璃底白字 */
.route-hero__actions :deep(.el-button) {
  border-radius: 10px;
  border-color: rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.1);
  color: #f4fffd;
}

.route-hero__actions :deep(.el-button:hover) {
  border-color: rgba(255, 255, 255, 0.32);
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
}

.route-hero__actions :deep(.el-button--primary:not(.is-plain):not(.is-text):not(.is-link)) {
  --el-button-bg-color: #f4fffd;
  --el-button-border-color: #f4fffd;
  --el-button-hover-bg-color: #ffffff;
  --el-button-hover-border-color: #ffffff;
  --el-button-active-bg-color: #e4f5f1;
  --el-button-active-border-color: #e4f5f1;
  border-color: #f4fffd;
  background-color: #f4fffd;
  background-image: none;
  color: #0b2830;
  box-shadow: 0 8px 20px rgba(3, 12, 16, 0.24);
}

.route-hero__actions :deep(.el-button--primary:not(.is-plain):not(.is-text):not(.is-link):hover) {
  border-color: #fff;
  background-color: #fff;
  background-image: none;
  color: #0b2830;
  transform: translateY(-1px);
}

.route-hero__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  flex: 0 0 auto;
  min-width: 0;
}

.route-stat {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 108px;
  padding: 10px 14px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.07);
  /* 逐个 stagger 浮入；数值本身原样渲染，不做数字滚动 */
  animation: hero-rise 0.6s cubic-bezier(0.22, 0.61, 0.36, 1)
    calc(0.46s + var(--qh-index, 0) * 0.09s) both;
  transition: transform 220ms var(--qh-ease);
}

.route-stat::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.05);
  opacity: 0;
  transition: opacity 220ms var(--qh-ease);
  pointer-events: none;
}

.route-stat:hover {
  transform: translateY(-2px);
}

.route-stat:hover::after {
  opacity: 1;
}

.route-stat__label {
  color: rgba(236, 248, 244, 0.62);
  font-size: 11.5px;
  white-space: nowrap;
}

.route-stat__value {
  color: #f6fffd;
  font-size: 22px;
  font-weight: 650;
  line-height: 1.25;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.route-stat__value small {
  margin-left: 2px;
  color: rgba(236, 248, 244, 0.62);
  font-size: 11px;
  font-weight: 500;
}

.route-stat--red .route-stat__value { color: #ff7b72; }
.route-stat--orange .route-stat__value { color: #ffa94d; }
.route-stat--yellow .route-stat__value { color: #f5d33f; }
.route-stat--good .route-stat__value { color: #7ce3c4; }
.route-stat--unknown .route-stat__value { color: rgba(246, 255, 253, 0.7); }

/* ---------- 入场编排 keyframes（只动 transform/opacity/clip-path） ---------- */
@keyframes hero-rise {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes hero-title-in {
  from {
    opacity: 0;
    transform: translateY(10px);
    clip-path: inset(0 0 100% 0);
  }
  to {
    opacity: 1;
    transform: translateY(0);
    clip-path: inset(0 0 0 0);
  }
}

@keyframes hero-shimmer {
  to {
    transform: translateX(130%);
  }
}

@media (pointer: coarse) {
  /* 触屏设备不做持续漂移，省电且避免滚动掉帧 */
  .route-hero__ambient {
    animation: none;
  }

  .route-stat:hover {
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .route-hero__ambient,
  .route-hero__eyebrow,
  .route-hero__eyebrow::after,
  .route-hero__title,
  .route-hero__desc,
  .route-hero__actions,
  .route-stat {
    animation: none;
  }

  .route-hero__eyebrow::after {
    display: none;
  }

  .route-stat,
  .route-stat::after {
    transition: none;
  }

  .route-stat:hover {
    transform: none;
  }
}

@media (max-width: 700px) {
  .route-hero {
    min-height: 0;
    padding: 20px 20px 30px;
  }

  .route-hero__content {
    align-items: stretch;
    gap: 18px;
  }

  .route-hero__copy {
    flex-basis: 100%;
  }

  .route-hero__title {
    font-size: 17px;
  }

  .route-hero__desc {
    font-size: 12.5px;
  }

  .route-hero__stats {
    width: 100%;
    gap: 8px;
  }

  .route-stat {
    min-width: 0;
    padding: 9px 10px;
  }

  .route-stat__label {
    font-size: 11px;
    white-space: normal;
  }

  .route-stat__value {
    font-size: 19px;
  }
}
</style>
