<template>
  <!-- 气泡挂在 PetSprite 的 slot 里：绝对定位天然跟着宠物 -->
  <Transition name="bubble-pop">
    <div v-if="show" class="pet-bubble" role="status" aria-live="polite">
      <span class="pet-bubble-text">{{ displayText }}</span>
    </div>
  </Transition>
</template>

<script setup>
// PetBubble：宠物头顶的对话气泡。收到 text 时打字机显示，停留后自动消失。
// 不发网络请求；只负责"把一句话演出来"。

import { ref, watch, onBeforeUnmount } from 'vue'

const props = defineProps({
  // 要说的话；变化即触发一次显示
  text: { type: String, default: '' },
  // 显示时长（毫秒），从打字完成算起
  duration: { type: Number, default: 4500 },
  // 打字机每字间隔（毫秒）
  typeSpeed: { type: Number, default: 28 },
  // 最大宽度（像素），超出换行
  maxWidth: { type: Number, default: 240 }
})
const emit = defineEmits(['hidden'])

const show = ref(false)
const displayText = ref('')
let timers = []

function clearTimers() {
  timers.forEach((t) => { clearInterval(t); clearTimeout(t) })
  timers = []
}

watch(
  () => props.text,
  (t) => {
    clearTimers()
    if (!t) {
      show.value = false
      displayText.value = ''
      return
    }
    show.value = true
    displayText.value = ''
    let i = 0
    const full = t
    const typer = setInterval(() => {
      i += 1
      displayText.value = full.slice(0, i)
      if (i >= full.length) clearInterval(typer)
    }, props.typeSpeed)
    timers.push(typer)
    const hide = setTimeout(() => {
      show.value = false
      emit('hidden')
    }, props.duration + full.length * props.typeSpeed)
    timers.push(hide)
  }
)

onBeforeUnmount(clearTimers)
</script>

<style scoped>
.pet-bubble {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  white-space: normal;
  max-width: v-bind('`${props.maxWidth}px`');
  padding: 9px 15px;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(10px) saturate(1.3);
  -webkit-backdrop-filter: blur(10px) saturate(1.3);
  border: 1px solid #eceef6;
  border-radius: 16px;
  /* drop-shadow 作用于含尾巴的整层轮廓，气泡和尾巴的影子自然连贯 */
  filter: drop-shadow(0 4px 10px rgba(40, 50, 90, 0.12))
    drop-shadow(0 14px 30px rgba(40, 50, 90, 0.08));
  font-size: 13px;
  color: #2a2d45;
  pointer-events: none;
  transform-origin: 50% 100%;
}

.pet-bubble::after {
  content: '';
  position: absolute;
  bottom: -6px;
  left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-top-color: rgba(255, 255, 255, 0.96);
  border-bottom: 0;
}

.pet-bubble-text {
  line-height: 1.5;
}

.bubble-pop-enter-active {
  /* 弹性入场：轻微过冲再回稳，像气泡"啵"地冒出来 */
  transition: opacity 0.22s ease, transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.bubble-pop-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.bubble-pop-enter-from,
.bubble-pop-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(8px) scale(0.86);
}

/* 平板/手机宠物只剩 64px：气泡改为左对齐，避免以宠物为中心时溢出视口左缘 */
@media (max-width: 1023px) {
  .pet-bubble {
    left: 4px;
    max-width: min(220px, calc(100vw - 32px));
    transform: none;
  }

  .bubble-pop-enter-from,
  .bubble-pop-leave-to {
    transform: translateY(8px) scale(0.86);
  }
}
</style>
