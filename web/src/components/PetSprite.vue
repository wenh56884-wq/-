<template>
  <div
    ref="rootEl"
    class="pet-root"
    :class="{ 'is-dimmed': dimmed }"
    role="img"
    :aria-label="ariaLabel"
    @click="onClick"
  >
    <span v-if="badge" class="pet-badge" @click.stop="emit('badge-click')">{{ badge }}</span>

    <div class="pet-stage">
      <img
        class="pet-img"
        :class="`is-${mode}`"
        :style="imgStyle"
        :src="currentSrc"
        alt=""
        draggable="false"
        @load="onImgLoad"
      />
      <span class="pet-shadow" aria-hidden="true" />
    </div>

    <!-- 气泡挂在宠物身上 -->
    <slot />
  </div>
</template>

<script setup>
// PetSprite：2D 电子宠物立绘，固定驻留在视口左下角、不移动。
// 立绘来自蓝色大肥鱼档案馆 https://fisharchive.cc/（CC BY-NC-SA 4.0）：
// 待机（侧视）/说话（正视）两姿态靠换图做出回应感。
// 范围约定：组件内不做走路/拖动/漫游；姿态切换只由 speak 定时器驱动。

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  // 立绘高度（px）；宽度按图片比例自动算
  size: { type: Number, default: 200 },
  // 姿态 → 图片地址：{ idle, talk }
  poses: { type: Object, default: () => ({}) },
  // 距视口左下角的留白
  edge: { type: Number, default: 20 },
  // idle / happy / thinking / sleepy：只影响呼吸幅度（纯表现层）
  mood: { type: String, default: 'idle' },
  // 右上角角标（例如 "AI"）；点角标触发 badge-click，不触发 click
  badge: { type: String, default: '' },
  // 助手抽屉打开时淡出，避免挡住正在读的对话
  dimmed: { type: Boolean, default: false }
})

const emit = defineEmits(['click', 'badge-click'])

const rootEl = ref(null)
const width = ref(props.size * 0.6)
const mode = ref('idle') // idle | talk
let talkUntil = 0
let tickTimer = null

const currentSrc = computed(() => props.poses[mode.value] || props.poses.idle || '')

// 呼吸幅度由心情驱动，写成 CSS 变量在类里用
const breatheVar = computed(() => {
  const map = { idle: 2, happy: 4, thinking: 1.5, sleepy: 1 }
  return `${map[props.mood] ?? 2}px`
})

const imgStyle = computed(() => ({ height: `${props.size}px`, '--breathe': breatheVar.value }))

const ariaLabel = computed(() => '小航，电子宠物，固定在左下角，点击会回应')

function onImgLoad(event) {
  const img = event?.target
  if (!img?.naturalWidth) return
  width.value = Math.max(48, props.size * (img.naturalWidth / img.naturalHeight))
}

// 说一句话：切到说话姿态，按字数估个时长；到点自动回待机
function speak(text = '') {
  const ms = Math.min(4200, 900 + String(text).length * 130)
  talkUntil = Date.now() + ms
  mode.value = 'talk'
}

// 点击蹦一下：瞬时 WAAPI 动画，纯表现层，不产生任何数据
function bounce() {
  rootEl.value?.animate?.(
    [
      { transform: 'translateY(0)' },
      { transform: 'translateY(-10px)' },
      { transform: 'translateY(0)' }
    ],
    { duration: 360, easing: 'ease-out' }
  )
}

function onClick() {
  bounce()
  // 点击时没有具体文本，用最短时长占位，说回话姿态由父组件 speak 控制
  speak('')
  emit('click')
}

function tick() {
  if (mode.value === 'talk' && Date.now() > talkUntil) mode.value = 'idle'
}

onMounted(() => {
  tickTimer = setInterval(tick, 400)
})

onBeforeUnmount(() => {
  if (tickTimer) clearInterval(tickTimer)
  tickTimer = null
})

defineExpose({ speak, bounce })
</script>

<style scoped>
.pet-root {
  position: fixed;
  left: v-bind('props.edge + "px"');
  bottom: v-bind('props.edge + "px"');
  z-index: 45;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  will-change: transform;
  transition: opacity 220ms ease;
}

.pet-root.is-dimmed {
  opacity: 0;
  pointer-events: none;
}

/* 窄屏：宠物上移到控制条上方避免被 320px 宽控制条遮挡；横向仍在最左、纵向仍是最低一档 */
@media (max-width: 760px) {
  .pet-root {
    bottom: 104px;
  }
}

.pet-stage {
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.pet-img {
  display: block;
  width: auto;
  max-width: none;
  filter: drop-shadow(0 6px 12px rgba(20, 40, 90, 0.18));
  animation: pet-breathe 3.6s ease-in-out infinite;
}

/* 待机/心情：呼吸起伏幅度由心情驱动 */
@keyframes pet-breathe {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(calc(var(--breathe, 2px) * -1)); }
}

/* 说话：小幅度上下点动，代替骨骼动画 */
.pet-img.is-talk {
  animation: pet-talk 0.9s ease-in-out infinite;
}

@keyframes pet-talk {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}

/* 地面投影：让贴图看起来是"站"在页面底部而不是浮着 */
.pet-shadow {
  position: absolute;
  bottom: -4px;
  left: 50%;
  width: 62%;
  height: 10px;
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(24, 40, 80, 0.24), rgba(24, 40, 80, 0));
  transform: translateX(-50%);
  pointer-events: none;
}

.pet-badge {
  position: absolute;
  top: 0;
  right: 0;
  padding: 1px 7px;
  border-radius: 8px;
  background: #4d6bfe;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.3px;
  border: 1px solid #fff;
  box-shadow: 0 2px 8px rgba(77, 107, 254, 0.35);
  pointer-events: auto;
  cursor: pointer;
  z-index: 2;
}

@media (prefers-reduced-motion: reduce) {
  .pet-img,
  .pet-img.is-talk {
    animation: none;
  }
}
</style>
