<template>
  <span class="count-number">{{ display }}</span>
</template>

<script setup>
// CountNumber：数字从上一次的值缓动到新值（纯 CSS/JS 动画，不影响数值本身来自接口）
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  value: { type: [Number, String], default: '-' },
  decimals: { type: Number, default: 0 },
  duration: { type: Number, default: 700 }
})

const current = ref(0)
let raf = null

const target = computed(() => {
  const num = Number(props.value)
  return props.value === null || props.value === undefined || props.value === '' || Number.isNaN(num) ? null : num
})

const display = computed(() => {
  if (target.value === null) return '-'
  return current.value.toFixed(props.decimals)
})

function easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3)
}

function animate(from, to) {
  if (raf) cancelAnimationFrame(raf)
  if (to === null) {
    current.value = 0
    return
  }
  const start = performance.now()
  const step = (now) => {
    const progress = Math.min(1, (now - start) / Math.max(1, props.duration))
    current.value = from + (to - from) * easeOutCubic(progress)
    if (progress < 1) {
      raf = requestAnimationFrame(step)
    } else {
      raf = null
    }
  }
  raf = requestAnimationFrame(step)
}

watch(target, (to, from) => animate(from || 0, to))

onMounted(() => animate(0, target.value))

onBeforeUnmount(() => {
  if (raf) cancelAnimationFrame(raf)
})
</script>

<style scoped>
.count-number {
  display: inline-block;
  font-variant-numeric: tabular-nums;
}
</style>
