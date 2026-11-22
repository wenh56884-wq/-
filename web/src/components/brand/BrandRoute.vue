<template>
  <div
    class="brand-route"
    :class="[`brand-route--${variant}`, `brand-route--${tone}`]"
    aria-hidden="true"
  >
    <svg :viewBox="viewBox" preserveAspectRatio="none" class="brand-route__svg">
      <defs>
        <linearGradient :id="gradientId" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stop-color="#6FC9C1" stop-opacity=".7" />
          <stop offset=".52" stop-color="#D8B45A" />
          <stop offset="1" stop-color="#F1D58F" />
        </linearGradient>
        <filter :id="glowId" x="-35%" y="-35%" width="170%" height="170%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <path
        :d="solidPath"
        class="brand-route__line"
        :stroke="`url(#${gradientId})`"
        :filter="`url(#${glowId})`"
        pathLength="1"
        vector-effect="non-scaling-stroke"
      />
      <path
        :d="dashPath"
        class="brand-route__dash"
        :stroke="`url(#${gradientId})`"
        pathLength="1"
        vector-effect="non-scaling-stroke"
      />

      <g class="brand-route__nodes">
        <circle
          v-for="(node, index) in nodes"
          :key="node.id"
          :cx="node.x"
          :cy="node.y"
          r="4.2"
          :style="{ animationDelay: `${1.15 + index * 0.22}s, ${2.6 + index * 0.35}s` }"
        />
      </g>
    </svg>

    <span
      v-for="(node, index) in nodes"
      v-show="showLabels"
      :key="`label-${node.id}`"
      class="brand-route__label"
      :style="{
        left: percent(node.x, width),
        top: percent(node.y, height),
        animationDelay: `${1.3 + index * 0.22}s`
      }"
    >
      {{ node.label }}
    </span>
  </div>
</template>

<script setup>
// BrandRoute：启航品牌母题「一条启航线」。
// 一条线从山脊等高线出发，在两江交汇处下沉，再抬升为行情曲线，最后变成虚线航线。
// hero 用于登录页叙事场景；strip 用于教师/学生首页的页头航线条。

import { computed } from 'vue'

const props = defineProps({
  variant: { type: String, default: 'hero' },
  tone: { type: String, default: 'gold' }
})

const uid = `qh-route-${Math.random().toString(36).slice(2, 8)}`
const gradientId = computed(() => `${uid}-stroke`)
const glowId = computed(() => `${uid}-glow`)

const HERO_SOLID = 'M 24 560 C 118 522 172 592 250 598 C 342 606 398 474 500 450 C 590 428 632 364 700 336'
const HERO_DASH = 'M 700 336 C 748 320 778 310 812 298'
const STRIP_SOLID = 'M -8 154 C 88 146 152 158 232 150 C 332 140 402 132 500 130 C 562 128 604 126 648 124'
const STRIP_DASH = 'M 648 124 C 672 123 688 122 708 121'

const isHero = computed(() => props.variant === 'hero')
const width = computed(() => (isHero.value ? 900 : 640))
const height = computed(() => (isHero.value ? 900 : 160))
const viewBox = computed(() => `0 0 ${width.value} ${height.value}`)
const solidPath = computed(() => (isHero.value ? HERO_SOLID : STRIP_SOLID))
const dashPath = computed(() => (isHero.value ? HERO_DASH : STRIP_DASH))
const showLabels = computed(() => isHero.value)
const nodes = computed(() =>
  isHero.value
    ? [
        { id: 'profile', x: 250, y: 598, label: '' },
        { id: 'match', x: 500, y: 450, label: '匹配' },
        { id: 'sail', x: 700, y: 336, label: '启航' }
      ]
    : [
        { id: 'start', x: 232, y: 150, label: '' },
        { id: 'mid', x: 500, y: 130, label: '' },
        { id: 'end', x: 648, y: 124, label: '' }
      ]
)

function percent(value, total) {
  return `${(value / total) * 100}%`
}
</script>

<style scoped>
.brand-route {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.brand-route__svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.brand-route__line {
  fill: none;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  animation: route-draw 1.9s cubic-bezier(0.22, 0.61, 0.36, 1) 0.35s forwards;
}

.brand-route__dash {
  fill: none;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-dasharray: 6 9;
  opacity: 0;
  animation:
    route-fade 0.9s ease 1.55s forwards,
    route-breathe 4.6s ease-in-out 2.8s infinite;
}

.brand-route__nodes circle {
  fill: #f3e2b4;
  stroke: #0b1f26;
  stroke-width: 1.4;
  transform-box: fill-box;
  transform-origin: center;
  opacity: 0;
  animation:
    route-node 0.55s cubic-bezier(0.22, 0.61, 0.36, 1) forwards,
    route-node-breathe 3.8s ease-in-out infinite;
}

.brand-route__label {
  position: absolute;
  transform: translate(-50%, -180%);
  color: rgba(236, 248, 244, 0.78);
  font-family: var(--cf-font-mono);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.14em;
  white-space: nowrap;
  opacity: 0;
  animation: route-label 0.6s ease forwards;
}



.brand-route--strip .brand-route__nodes circle {
  animation: none;
  opacity: 0.65;
  transform: scale(0.76);
}

@keyframes route-draw {
  to {
    stroke-dashoffset: 0;
  }
}

@keyframes route-fade {
  to {
    opacity: 0.9;
  }
}

@keyframes route-node {
  from {
    opacity: 0;
    transform: scale(0.4);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes route-label {
  from {
    opacity: 0;
    transform: translate(-50%, -150%);
  }
  to {
    opacity: 1;
    transform: translate(-50%, -180%);
  }
}

/* 入场后的轻微呼吸：只动 opacity/transform，幅度克制 */
@keyframes route-breathe {
  0%,
  100% {
    opacity: 0.9;
  }
  50% {
    opacity: 0.55;
  }
}

@keyframes route-node-breathe {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.72;
    transform: scale(1.12);
  }
}

@keyframes route-strip-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@media (max-width: 900px) {
  .brand-route__label {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .brand-route,
  .brand-route--strip,
  .brand-route__line,
  .brand-route__dash,
  .brand-route__nodes circle,
  .brand-route__label {
    animation: none;
    opacity: 1;
  }

  .brand-route__line {
    stroke-dashoffset: 0;
  }

  .brand-route--strip .brand-route__line,
  .brand-route--strip .brand-route__dash,
  .brand-route--strip .brand-route__nodes circle {
    opacity: 0.5;
  }
}
</style>
