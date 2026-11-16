<template>
  <div class="login-scene" aria-hidden="true">
    <svg
      class="login-scene__svg"
      viewBox="0 0 900 900"
      preserveAspectRatio="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient :id="`${uid}-sky`" x1="0" y1="0" x2="0.35" y2="1">
          <stop offset="0" stop-color="#06171D" />
          <stop offset="0.52" stop-color="#0A2B34" />
          <stop offset="1" stop-color="#06161C" />
        </linearGradient>
        <radialGradient :id="`${uid}-dawn`" cx="0.68" cy="0.16" r="0.62">
          <stop offset="0" stop-color="#2B7B78" stop-opacity=".55" />
          <stop offset="0.48" stop-color="#14434C" stop-opacity=".28" />
          <stop offset="1" stop-color="#06171D" stop-opacity="0" />
        </radialGradient>
        <linearGradient :id="`${uid}-river`" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#79D8D0" stop-opacity=".75" />
          <stop offset="0.55" stop-color="#2C8B96" stop-opacity=".48" />
          <stop offset="1" stop-color="#1D4E89" stop-opacity=".22" />
        </linearGradient>
        <radialGradient :id="`${uid}-confluence`" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stop-color="#9CEAE2" stop-opacity=".3" />
          <stop offset="1" stop-color="#9CEAE2" stop-opacity="0" />
        </radialGradient>
        <radialGradient :id="`${uid}-fog`" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stop-color="#BFEFE9" stop-opacity=".26" />
          <stop offset="1" stop-color="#BFEFE9" stop-opacity="0" />
        </radialGradient>
        <linearGradient :id="`${uid}-shade`" x1="0" y1="0" x2="0.2" y2="1">
          <stop offset="0" stop-color="#041014" stop-opacity="0" />
          <stop offset="0.55" stop-color="#041014" stop-opacity=".12" />
          <stop offset="1" stop-color="#041014" stop-opacity=".88" />
        </linearGradient>
        <filter :id="`${uid}-blur`" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="16" />
        </filter>
        <filter :id="`${uid}-soft`" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="30" />
        </filter>
      </defs>

      <rect width="900" height="900" :fill="`url(#${uid}-sky)`" />
      <rect width="900" height="900" :fill="`url(#${uid}-dawn)`" />

      <!-- 远山：低对比，先把空间推远 -->
      <path
        d="M0 470 C 90 438 150 468 230 448 C 320 424 380 460 470 438 C 580 410 680 448 790 424 C 840 412 872 418 900 410 L900 900 L0 900 Z"
        fill="#14343E"
        opacity=".5"
      />
      <path
        d="M0 555 C 110 516 190 556 300 532 C 410 508 500 552 610 522 C 720 492 810 532 900 512 L900 900 L0 900 Z"
        fill="#0E2A33"
        opacity=".9"
      />

      <!-- 两江：在画面中左汇合，对应「学生画像 × 岗位市场」 -->
      <g :filter="`url(#${uid}-blur)`">
        <path
          d="M 175 -30 C 200 220 290 350 385 510 C 455 625 485 760 505 940"
          fill="none"
          :stroke="`url(#${uid}-river)`"
          stroke-width="86"
          opacity=".34"
        />
        <path
          d="M 840 -30 C 730 210 600 350 500 500 C 440 600 410 760 390 940"
          fill="none"
          :stroke="`url(#${uid}-river)`"
          stroke-width="62"
          opacity=".24"
        />
      </g>
      <ellipse
        cx="440"
        cy="548"
        rx="220"
        ry="110"
        :fill="`url(#${uid}-confluence)`"
        :filter="`url(#${uid}-soft)`"
      />
      <path
        d="M 200 -20 C 225 220 310 360 400 520 C 465 630 490 760 510 920"
        fill="none"
        stroke="#8CE7DF"
        stroke-width="1.8"
        opacity=".28"
      />

      <!-- 近山：把画面底部压暗，给标题留出稳定对比 -->
      <path
        d="M0 672 C 120 632 230 674 350 646 C 470 618 570 666 700 638 C 790 618 850 636 900 628 L900 900 L0 900 Z"
        fill="#081A20"
      />
      <path
        d="M0 790 C 140 760 260 800 420 772 C 580 744 720 790 900 764 L900 900 L0 900 Z"
        fill="#051318"
      />

      <!-- 等高线：只做极淡的结构，不做满屏网格 -->
      <g fill="none" stroke="#D8B45A" stroke-opacity=".09" stroke-width="1">
        <path d="M-20 520 C 100 484 180 520 290 496 C 400 472 500 512 620 484 C 730 458 820 492 920 470" />
        <path d="M-20 566 C 110 530 200 566 310 542 C 420 518 520 558 640 530 C 750 504 830 538 920 516" />
        <path d="M-20 620 C 120 584 220 620 330 596 C 440 572 540 612 660 584 C 770 558 850 592 920 570" />
        <path d="M-20 704 C 130 668 240 704 360 678 C 480 652 580 694 700 666 C 800 642 870 668 920 652" />
      </g>
      <g fill="none" stroke="#6FC9C1" stroke-opacity=".07" stroke-width="1">
        <path d="M-20 480 C 110 446 200 482 320 458 C 440 434 550 474 670 446 C 780 420 850 452 920 432" />
        <path d="M-20 756 C 140 720 250 758 380 730 C 510 702 620 744 750 716 C 830 698 880 712 920 704" />
      </g>

      <!-- 江雾 -->
      <ellipse
        cx="300"
        cy="520"
        rx="430"
        ry="140"
        :fill="`url(#${uid}-fog)`"
        :filter="`url(#${uid}-soft)`"
      />
      <ellipse
        cx="670"
        cy="430"
        rx="360"
        ry="120"
        :fill="`url(#${uid}-fog)`"
        opacity=".7"
        :filter="`url(#${uid}-soft)`"
      />

      <rect width="900" height="900" :fill="`url(#${uid}-shade)`" />
    </svg>

    <!-- 环境氛围：两层 mesh gradient 缓慢漂移 + 少量浮动光点（桌面 18 / 触屏 8） -->
    <div class="login-scene__aurora" />
    <div class="login-scene__aurora login-scene__aurora--b" />
    <span
      v-for="p in particles"
      :key="p.id"
      class="login-scene__particle"
      :style="p.style"
    />

    <BrandRoute variant="hero" class="login-scene__route" />
  </div>
</template>

<script setup>
// LoginScene：登录页的「两江启航」叙事场景。
// 纯 SVG 生成山脊、两江、江雾与等高线，叠加 CSS 氛围光与光点粒子；
// 不依赖视频/大图，首屏更轻。BrandRoute 叠加在同一条视觉轴上：画像 → 匹配 → 启航。

import BrandRoute from './BrandRoute.vue'

const uid = `login-scene-${Math.random().toString(36).slice(2, 8)}`

// 光点粒子：纯 CSS transform/opacity 动画，无定时器；触屏设备减量到 8 个
const isCoarse =
  typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches
const particleCount = isCoarse ? 8 : 18
const particles = Array.from({ length: particleCount }, (_, i) => {
  const size = 2 + Math.random() * 2.4
  return {
    id: i,
    style: {
      left: `${4 + Math.random() * 92}%`,
      top: `${6 + Math.random() * 62}%`,
      width: `${size}px`,
      height: `${size}px`,
      color: i % 3 === 0 ? 'rgba(241, 213, 143, 0.8)' : 'rgba(191, 239, 233, 0.8)',
      '--dx': `${(Math.random() - 0.5) * 36}px`,
      '--o': `${0.22 + Math.random() * 0.3}`,
      '--dur': `${9 + Math.random() * 9}s`,
      '--delay': `${-Math.random() * 18}s`
    }
  }
})
</script>

<style scoped>
.login-scene {
  position: absolute;
  inset: 0;
  overflow: hidden;
  background: #06171d;
}

.login-scene__svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
  /* 电影感开场：场景从暗处轻微推近落定 */
  animation: scene-settle 1.7s cubic-bezier(0.22, 0.61, 0.36, 1) both;
}

@keyframes scene-settle {
  from {
    opacity: 0;
    transform: scale(1.045);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

/* 两层 mesh gradient 氛围光：低饱和品牌色，只动 transform */
.login-scene__aurora {
  position: absolute;
  inset: -12%;
  pointer-events: none;
  background:
    radial-gradient(42% 34% at 24% 22%, rgba(43, 123, 120, 0.2), transparent 70%),
    radial-gradient(36% 30% at 74% 12%, rgba(216, 180, 90, 0.1), transparent 70%);
  animation: aurora-drift-a 52s ease-in-out infinite alternate;
  will-change: transform;
}

.login-scene__aurora--b {
  background:
    radial-gradient(40% 32% at 68% 62%, rgba(111, 201, 193, 0.12), transparent 70%),
    radial-gradient(30% 26% at 12% 78%, rgba(29, 78, 137, 0.14), transparent 72%);
  animation: aurora-drift-b 64s ease-in-out infinite alternate;
}

@keyframes aurora-drift-a {
  from {
    transform: translate3d(-2.5%, -1.5%, 0) scale(1);
  }
  to {
    transform: translate3d(2.5%, 2%, 0) scale(1.06);
  }
}

@keyframes aurora-drift-b {
  from {
    transform: translate3d(2%, 1.5%, 0) scale(1.04);
  }
  to {
    transform: translate3d(-2%, -2%, 0) scale(1);
  }
}

/* 浮动光点：transform 漂移 + opacity 呼吸，负延迟错开相位 */
.login-scene__particle {
  position: absolute;
  border-radius: 999px;
  background: currentColor;
  opacity: 0;
  pointer-events: none;
  animation: scene-particle var(--dur, 12s) linear var(--delay, 0s) infinite;
  will-change: transform, opacity;
}

@keyframes scene-particle {
  0% {
    opacity: 0;
    transform: translate3d(0, 0, 0);
  }
  14% {
    opacity: var(--o, 0.3);
  }
  86% {
    opacity: var(--o, 0.3);
  }
  100% {
    opacity: 0;
    transform: translate3d(var(--dx, 12px), -56px, 0);
  }
}

.login-scene__route {
  z-index: 1;
}

/* 右侧与底部压暗，保证登录卡和标题的对比 */
.login-scene::after {
  content: '';
  position: absolute;
  inset: 0;
  background:
    linear-gradient(90deg, transparent 58%, rgba(4, 16, 20, 0.42) 100%),
    radial-gradient(120% 90% at 20% 100%, rgba(4, 16, 20, 0.72), transparent 62%);
  pointer-events: none;
}

@media (pointer: coarse) {
  /* 触屏不做持续漂移的氛围层；光点已减量，保留轻量漂浮 */
  .login-scene__aurora,
  .login-scene__aurora--b {
    animation: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .login-scene__svg,
  .login-scene__aurora,
  .login-scene__aurora--b,
  .login-scene__particle {
    animation: none;
  }

  .login-scene__particle {
    opacity: 0.2;
  }
}

</style>
