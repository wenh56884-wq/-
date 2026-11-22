<template>
  <Teleport to="body">
    <Transition name="xh-fade" appear>
      <div v-if="open" class="xh-root" role="dialog" aria-modal="true" aria-labelledby="xh-title">
        <!-- 目标挖洞：巨大 box-shadow 充当全屏遮罩，洞处透出真实页面 -->
        <div v-if="hole" class="xh-hole" :style="holeStyle" aria-hidden="true">
          <span class="xh-hole__ring" />
          <span class="xh-hole__no">{{ currentStep + 1 }}</span>
        </div>
        <!-- 无目标步骤：全屏淡蒙层 -->
        <div v-else class="xh-veil" aria-hidden="true" />

        <!-- 小助手气泡 -->
        <section class="xh-bubble" :style="bubbleStyle" aria-live="polite">
          <span v-if="hole" class="xh-arrow" :style="arrowStyle" aria-hidden="true" />

          <header class="xh-head">
            <span class="xh-mascot" aria-hidden="true">
              <svg viewBox="0 0 64 64">
                <line x1="32" y1="9" x2="32" y2="17" stroke="#1951c3" stroke-width="3" stroke-linecap="round" />
                <circle class="xh-mascot__antenna" cx="32" cy="6.5" r="4" fill="#1951c3" />
                <rect x="9" y="17" width="46" height="42" rx="16" fill="#16181d" />
                <rect x="15" y="27" width="34" height="22" rx="11" fill="#ffffff" />
                <circle class="xh-mascot__eye" cx="26" cy="38" r="2.8" fill="#16181d" />
                <circle class="xh-mascot__eye" cx="38" cy="38" r="2.8" fill="#16181d" />
                <path d="M28.5 43.5q3.5 2.8 7 0" stroke="#1951c3" stroke-width="2" fill="none" stroke-linecap="round" />
              </svg>
            </span>
            <div class="xh-who">
              <b class="xh-who__name">启小航</b>
              <span class="xh-who__role">{{ grade }}新生引导员</span>
            </div>
            <span class="xh-progress">{{ currentStep + 1 }}<i>/</i>{{ steps.length }}</span>
            <button type="button" class="xh-close" aria-label="跳过新生引导" @click="skip">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
            </button>
          </header>

          <div class="xh-body">
            <p class="xh-eyebrow">{{ activeStep.eyebrow }}</p>
            <h2 id="xh-title" class="xh-title">{{ activeStep.title }}</h2>
            <p class="xh-text">{{ activeStep.text }}</p>
            <p v-if="activeStep.tip" class="xh-tip">{{ activeStep.tip }}</p>
          </div>

          <footer class="xh-foot">
            <button type="button" class="xh-skip" @click="skip">跳过引导</button>
            <div class="xh-foot__right">
              <div class="xh-dots" aria-hidden="true">
                <span v-for="(s, i) in steps" :key="i"
                  :class="{ 'is-on': i === currentStep, 'is-done': i < currentStep }" />
              </div>
              <button v-if="currentStep > 0" type="button" class="xh-btn xh-btn--ghost" @click="previous">
                上一步
              </button>
              <button ref="primaryButton" type="button" class="xh-btn xh-btn--primary" @click="next">
                {{ primaryLabel }}
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
              </button>
            </div>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  grade: { type: String, default: '大一' }
})

const emit = defineEmits(['complete', 'skip'])

// ------------------------------------------------------------------
// 步骤脚本：target 指向页面上的真实元素，由小助手逐一介绍并挖洞高亮。
// 最后一步无目标（收尾致辞），主按钮变成「去选方向」直接带用户去操作。
// ------------------------------------------------------------------
const steps = [
  {
    target: '.assistant-fab',
    eyebrow: `第 1 步 · 认识我`,
    title: '欢迎来到启航生涯规划',
    text: '我是你的小助手启小航，接下来跟着我的步伐来认识它吧～右下角这个小家伙就是我，以后有任何问题，点它就能找到我。'
  },
  {
    target: '.page-hero',
    eyebrow: '第 2 步 · 看结论',
    title: '首页已经替你算好了这学期',
    text: '这张卡是你的本学期结论：预警等级、风险分、已匹配岗位。所有数字都由引擎实算，每一个都查得到出处。',
    tip: '想深挖就点「问 AI」，我会引用你的真实数据来回答。'
  },
  {
    // 高亮「方向按钮组」而不是整张卡：整卡太高，气泡只能压在卡片上
    target: '.onboard-pick, .guide-card',
    eyebrow: '第 3 步 · 定方向',
    title: '大一最关键的一步：选方向',
    text: '考公、考研、考编还是就业？在这里选定后，四年规划、课程重点和推荐岗位都会跟着你的方向走。',
    tip: '选错了也不怕，随时可以回来改。'
  },
  {
    target: '.quick-card',
    eyebrow: '第 4 步 · 记入口',
    title: '常用功能都在快捷入口',
    text: '成绩单、模拟面试、岗位库、招考信息，从这里一跳就到，不用到处翻菜单。'
  },
  {
    target: null,
    eyebrow: '准备出发',
    title: '认识完了，该你上场啦',
    text: '跟着我转了一圈，接下来从「选方向」开始你的启航之旅吧。遇到问题，随时来右下角找我～',
    cta: '去选方向'
  }
]

const currentStep = ref(0)
const primaryButton = ref(null)
// 挖洞矩形 { top,left,width,height }；null 表示无目标步骤
const hole = ref(null)
const bubbleEl = ref(null)
const bubbleHeight = ref(0)
let rafId = 0
let ro = null

const activeStep = computed(() => steps[currentStep.value])
const isLastStep = computed(() => currentStep.value === steps.length - 1)
const primaryLabel = computed(() =>
  activeStep.value.cta || (isLastStep.value ? '完成' : '下一步'))

// ---------------- 定位 ----------------
const PAD = 10          // 洞比目标外扩
const GAP = 14          // 气泡与洞的间距
const EDGE = 16         // 视口安全边距

const holeStyle = computed(() => {
  if (!hole.value) return {}
  const h = hole.value
  return {
    top: `${h.top - PAD}px`,
    left: `${h.left - PAD}px`,
    width: `${h.width + PAD * 2}px`,
    height: `${h.height + PAD * 2}px`
  }
})

const bubbleWidth = 348

// 纯计算，不写任何 ref：computed 里改 placement 会让它反复自我失效，
// 表现为气泡位置落在「按 260px 算」的旧值上，最后一两行被切掉。
const bubbleLayout = computed(() => {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const bw = Math.min(bubbleWidth, vw - EDGE * 2)
  const bh = bubbleHeight.value || 260

  // 移动端 / 无目标：底部停靠（不遮页面正中）
  if (!hole.value || vw < 720) {
    return {
      placement: 'dock',
      style: {
        width: `${bw}px`,
        left: `${Math.max(EDGE, (vw - bw) / 2)}px`,
        top: 'auto',
        bottom: `${EDGE}px`
      }
    }
  }

  const h = hole.value
  const holeTop = h.top - PAD
  const holeBottom = h.top + h.height + PAD
  const spaceBelow = vh - EDGE - holeBottom - GAP
  const spaceAbove = holeTop - GAP - EDGE
  const preferBelow = spaceBelow >= spaceAbove

  let top
  let placement
  if (preferBelow && spaceBelow >= bh) {
    top = holeBottom + GAP
    placement = 'below'
  } else if (!preferBelow && spaceAbove >= bh) {
    top = holeTop - GAP - bh
    placement = 'above'
  } else {
    // 上下都塞不下完整气泡：优先贴视口底/顶停靠，前提是不能压住高亮目标
    const dockBottom = vh - EDGE - bh
    const dockTop = EDGE
    if (dockBottom >= holeBottom + GAP) {
      top = dockBottom
      placement = 'dock'
    } else if (dockTop + bh <= holeTop - GAP) {
      top = dockTop
      placement = 'dock'
    } else if (spaceBelow >= spaceAbove) {
      top = Math.min(holeBottom + GAP, dockBottom)
      placement = 'below'
    } else {
      top = Math.max(dockTop, holeTop - GAP - bh)
      placement = 'above'
    }
  }

  // 竖向兜底：任何情况下都不许出视口
  top = Math.max(EDGE, Math.min(top, vh - EDGE - bh))

  let left = h.left + h.width / 2 - bw / 2
  left = Math.max(EDGE, Math.min(left, vw - bw - EDGE))
  return { placement, style: { width: `${bw}px`, left: `${left}px`, top: `${top}px`, bottom: 'auto' } }
})

const bubbleStyle = computed(() => bubbleLayout.value.style)
const placement = computed(() => bubbleLayout.value.placement)

const arrowStyle = computed(() => {
  const h = hole.value
  if (!h || placement.value === 'dock') return { display: 'none' }
  const bs = bubbleStyle.value
  const bubbleLeft = parseFloat(bs.left)
  const targetCenter = h.left + h.width / 2
  const x = Math.max(22, Math.min(targetCenter - bubbleLeft,
    (parseFloat(bs.width) || bubbleWidth) - 22))
  return placement.value === 'below'
    ? { top: '-9px', left: `${x}px`, '--xh-arrow-rotate': '0deg' }
    : { bottom: '-9px', top: 'auto', left: `${x}px`, '--xh-arrow-rotate': '180deg' }
})

// ---------------- 跟踪 ----------------
function measure() {
  bubbleHeight.value = bubbleEl.value?.offsetHeight || 260
}

// 气泡高度会随文案换行变化；高度一变就重算 top，避免贴着视口底缘被切
function observeBubble() {
  if (typeof ResizeObserver === 'undefined') return
  ro?.disconnect()
  if (!bubbleEl.value) return
  ro = new ResizeObserver(() => measure())
  ro.observe(bubbleEl.value)
}

// 目标选择器按顺序尝试：querySelector('.a, .b') 返回的是**文档顺序**里先匹配的那个，
// 会把 .guide-card 这种祖先卡抢先选中，所以这里逐个试。
function pickEl(target) {
  for (const sel of String(target).split(',').map((s) => s.trim()).filter(Boolean)) {
    const el = document.querySelector(sel)
    if (el) {
      const r = el.getBoundingClientRect()
      if (r.width >= 4 && r.height >= 4) return el
    }
  }
  return null
}

// 目标比视口还高时，挖洞只框住顶部一段：否则气泡上下都没地方放，只能压住目标
function spotRect(el) {
  const vh = window.innerHeight
  const r = el.getBoundingClientRect()
  const maxH = Math.round(vh * 0.42)
  const height = Math.min(r.height, maxH)
  const top = Math.max(EDGE, Math.min(r.top, vh - height - EDGE))
  return { top, left: r.left, width: r.width, height }
}

function track() {
  rafId = 0
  const step = steps[currentStep.value]
  const vw = window.innerWidth
  if (!step?.target || vw < 720) { hole.value = null; measure(); return }
  const el = pickEl(step.target)
  if (!el) { hole.value = null; measure(); return }
  hole.value = spotRect(el)
  measure()
}

function scheduleTrack() {
  if (!rafId) rafId = requestAnimationFrame(track)
}

function bringTargetIntoView() {
  const step = steps[currentStep.value]
  if (!step?.target) return
  const el = pickEl(step.target)
  if (!el) return
  // 固定定位元素（右下角助手球）不随滚动移动，别为它滚页面
  if (getComputedStyle(el).position === 'fixed') return
  const r = el.getBoundingClientRect()
  const vh = window.innerHeight
  // 目标默认滚到视口上 14% 处：下方留足空间给气泡，避免「上下都塞不下」只能压住目标
  const wantTop = Math.round(vh * 0.14)
  const needScroll = r.top < 72 || r.top > wantTop + 60 || r.bottom > vh - 120
  if (!needScroll) return
  const y = window.scrollY + r.top - wantTop
  window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' })
}

function onKeydown(event) {
  if (!props.open) return
  if (event.key === 'Escape') { event.preventDefault(); skip() }
  else if (event.key === 'ArrowRight') { event.preventDefault(); next() }
  else if (event.key === 'ArrowLeft') { event.preventDefault(); previous() }
  else if (event.key === 'Enter' && document.activeElement === primaryButton.value) {
    /* 按钮自身行为，不重复触发 */
  } else if (event.key === 'Enter') { event.preventDefault(); next() }
}

// ---------------- 步骤流转 ----------------
function next() {
  if (isLastStep.value) { emit('complete'); return }
  currentStep.value += 1
}

function previous() {
  if (currentStep.value > 0) currentStep.value -= 1
}

function skip() { emit('skip') }

watch(
  () => props.open,
  async (open) => {
    if (open) {
      currentStep.value = 0
      window.addEventListener('keydown', onKeydown)
      window.addEventListener('scroll', scheduleTrack, { passive: true, capture: true })
      window.addEventListener('resize', scheduleTrack)
      await nextTick()
      observeBubble()
      // 等页面数据与布局稳定后再定位首步
      setTimeout(() => { bringTargetIntoView(); scheduleTrack() }, 380)
      setTimeout(scheduleTrack, 700)
      primaryButton.value?.focus()
    } else {
      window.removeEventListener('keydown', onKeydown)
      window.removeEventListener('scroll', scheduleTrack, { capture: true })
      window.removeEventListener('resize', scheduleTrack)
      hole.value = null
    }
  },
  { immediate: true }
)

watch(currentStep, async () => {
  hole.value = null
  await nextTick()
  observeBubble()
  setTimeout(() => { bringTargetIntoView(); scheduleTrack() }, 360)
  setTimeout(scheduleTrack, 700)
  primaryButton.value?.focus()
})

onBeforeUnmount(() => {
  if (rafId) cancelAnimationFrame(rafId)
  ro?.disconnect()
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('scroll', scheduleTrack, { capture: true })
  window.removeEventListener('resize', scheduleTrack)
})
</script>

<style scoped>
.xh-root {
  position: fixed;
  inset: 0;
  z-index: 3000;
  pointer-events: none;
}

/* ---------- 挖洞与蒙层 ---------- */
.xh-hole {
  position: fixed;
  border-radius: 20px;
  box-shadow: 0 0 0 200vmax rgba(9, 34, 36, 0.62);
  transition: top 240ms cubic-bezier(0.22, 1, 0.36, 1),
    left 240ms cubic-bezier(0.22, 1, 0.36, 1),
    width 240ms cubic-bezier(0.22, 1, 0.36, 1),
    height 240ms cubic-bezier(0.22, 1, 0.36, 1);
}

.xh-hole__ring {
  position: absolute;
  inset: -4px;
  border: 2px solid rgba(255, 122, 89, 0.9);
  border-radius: 24px;
  animation: xh-ring 1.8s ease-out infinite;
}

@keyframes xh-ring {
  0% { opacity: 0.9; transform: scale(1); }
  70% { opacity: 0; transform: scale(1.045); }
  100% { opacity: 0; transform: scale(1.045); }
}

.xh-hole__no {
  position: absolute;
  top: -13px;
  left: -13px;
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border-radius: 50%;
  background: #1951c3;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  box-shadow: 0 3px 10px rgba(25, 81, 195, 0.4);
}

.xh-veil {
  position: fixed;
  inset: 0;
  background: rgba(9, 34, 36, 0.5);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}

/* ---------- 气泡 ---------- */
.xh-bubble {
  position: fixed;
  pointer-events: auto;
  border: 1px solid #e4e7ee;
  border-radius: 20px;
  background:
    radial-gradient(circle at 92% 0%, rgba(25, 81, 195, 0.07), transparent 42%),
    #ffffff;
  box-shadow: 0 24px 70px rgba(9, 34, 36, 0.34), 0 2px 8px rgba(9, 34, 36, 0.1);
  animation: xh-pop 260ms cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes xh-pop {
  from { opacity: 0; transform: translateY(10px) scale(0.97); }
  to { opacity: 1; transform: none; }
}

.xh-arrow {
  position: absolute;
  width: 18px;
  height: 18px;
  border: 1px solid #e4e7ee;
  border-radius: 4px;
  background: #ffffff;
  transform: rotate(var(--xh-arrow-rotate, 0deg)) rotate(45deg);
  clip-path: polygon(100% 0, 100% 100%, 0 100%);
}

.xh-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px 0;
}

.xh-mascot {
  display: grid;
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  place-items: center;
  border-radius: 15px;
  background: linear-gradient(150deg, #e9efff, #e9f7f4);
  animation: xh-bob 3.2s ease-in-out infinite;
}

.xh-mascot svg {
  width: 38px;
  height: 38px;
}

.xh-mascot__eye {
  transform-origin: center;
  animation: xh-blink 4.6s infinite;
}

@keyframes xh-blink {
  0%, 93%, 100% { transform: scaleY(1); }
  95.5% { transform: scaleY(0.12); }
}

@keyframes xh-bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}

.xh-who {
  display: grid;
  gap: 1px;
  min-width: 0;
}

.xh-who__name {
  color: #16181d;
  font-size: 15px;
  font-weight: 750;
  line-height: 1.2;
}

.xh-who__role {
  color: #6b7280;
  font-size: 11.5px;
}

.xh-progress {
  margin-left: auto;
  color: #6b7280;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.xh-progress i {
  margin: 0 3px;
  font-style: normal;
  opacity: 0.6;
}

.xh-close {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: #f2f2f4;
  color: #5f6672;
  cursor: pointer;
  transition: background 160ms ease, color 160ms ease;
}

.xh-close:hover { background: #e8eaf2; color: #16181d; }

.xh-close svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-width: 2;
}

.xh-body { padding: 10px 18px 0; }

.xh-eyebrow {
  margin: 0 0 6px;
  color: #1951c3;
  font-size: 11.5px;
  font-weight: 750;
  letter-spacing: 0.1em;
}

.xh-title {
  margin: 0;
  color: #16181d;
  font-size: 20px;
  font-weight: 750;
  letter-spacing: -0.02em;
  line-height: 1.3;
}

.xh-text {
  margin: 8px 0 0;
  color: #5f6672;
  font-size: 13.5px;
  line-height: 1.72;
}

.xh-tip {
  display: flex;
  gap: 7px;
  margin: 12px 0 0;
  padding: 9px 12px;
  border-radius: 11px;
  background: #f7f8fa;
  color: #5f6672;
  font-size: 12.5px;
  line-height: 1.55;
}

.xh-tip::before {
  content: '💡';
  flex: 0 0 auto;
}

.xh-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px 16px;
}

.xh-skip {
  padding: 4px 2px;
  border: 0;
  background: transparent;
  color: #6b7280;
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
}

.xh-skip:hover { color: #16181d; }

.xh-foot__right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.xh-dots {
  display: flex;
  gap: 5px;
}

.xh-dots span {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #e4e7ee;
  transition: background 200ms ease, width 200ms ease;
}

.xh-dots span.is-done { background: #b9b9ea; }
.xh-dots span.is-on { width: 18px; background: #1951c3; }

.xh-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 38px;
  padding: 0 16px;
  border: 0;
  border-radius: 11px;
  font: inherit;
  font-size: 13.5px;
  font-weight: 650;
  cursor: pointer;
  transition: background 160ms ease, transform 160ms ease, box-shadow 160ms ease;
}

.xh-btn--ghost { background: #f2f2f4; color: #35353a; }
.xh-btn--ghost:hover { background: #e8e8eb; }

.xh-btn--primary {
  background-image: linear-gradient(135deg, #2d61dd 0%, #1951c3 52%, #14419c 100%);
  color: #fff;
  box-shadow:
    0 8px 20px rgba(79, 70, 229, 0.28),
    inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.xh-btn--primary:hover {
  background-image: linear-gradient(135deg, #3b6ee5 0%, #1f5ad0 52%, #14419c 100%);
  transform: translateY(-1px);
  box-shadow:
    0 12px 26px rgba(79, 70, 229, 0.34),
    inset 0 1px 0 rgba(255, 255, 255, 0.26);
}

.xh-btn--primary svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2;
}

.xh-skip:focus-visible,
.xh-btn:focus-visible,
.xh-close:focus-visible {
  outline: 3px solid rgba(25, 81, 195, 0.3);
  outline-offset: 2px;
}

/* ---------- 过渡 ---------- */
.xh-fade-enter-active,
.xh-fade-leave-active { transition: opacity 200ms ease; }

.xh-fade-enter-active .xh-bubble,
.xh-fade-leave-active .xh-bubble { transition: transform 240ms cubic-bezier(0.22, 1, 0.36, 1); }

.xh-fade-enter-from,
.xh-fade-leave-to { opacity: 0; }

.xh-fade-enter-from .xh-bubble { transform: translateY(14px) scale(0.97); }

@media (prefers-reduced-motion: reduce) {
  .xh-hole,
  .xh-bubble,
  .xh-fade-enter-active,
  .xh-fade-leave-active,
  .xh-fade-enter-active .xh-bubble,
  .xh-fade-leave-active .xh-bubble,
  .xh-mascot,
  .xh-mascot__eye,
  .xh-hole__ring { transition: none !important; animation: none !important; }
}
</style>
