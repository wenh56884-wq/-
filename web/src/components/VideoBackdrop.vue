<template>
  <div class="video-backdrop" aria-hidden="true">
    <video
      ref="vidA"
      class="vb-video is-active"
      autoplay
      muted
      loop
      playsinline
      preload="auto"
      disablepictureinpicture
      :poster="poster"
      :style="{ objectPosition }"
    >
      <source :src="src" type="video/mp4" />
    </video>
    <video
      ref="vidB"
      class="vb-video"
      muted
      loop
      playsinline
      preload="auto"
      disablepictureinpicture
      :poster="poster"
      :style="{ objectPosition }"
    >
      <source :src="src" type="video/mp4" />
    </video>
    <div class="vb-scrim" :style="{ background: `rgba(0, 0, 0, ${scrim})` }" />
  </div>
</template>

<script setup>
/* 暗色视频背景：两路 video 交替，在循环点交叉淡出。
   片段首尾帧不衔接，单路 loop 每轮会横跳一次，故用双路覆盖接缝。 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

/* 资源已本地化到 web/public/media/，Vite 会原样复制到 dist/，
   生产环境由 FastAPI 的 StaticFiles 挂载在站点根路径提供 —— 内外网都能播。 */
const DEFAULT_SRC = '/media/globe.mp4'
const DEFAULT_POSTER = '/media/globe-poster.webp'

defineProps({
  src: { type: String, default: DEFAULT_SRC },
  poster: { type: String, default: DEFAULT_POSTER },
  /* 压暗遮罩强度：保证叠在上面的白字达到对比度要求 */
  scrim: { type: Number, default: 0.46 },
  /* 视频取景位置：整页用 51% 8%，矮横幅需要往上抬才看得到地球弧线 */
  objectPosition: { type: String, default: '51% 8%' }
})

const FADE = 0.9

const vidA = ref(null)
const vidB = ref(null)

let intervalId = null
let swapTimer = null
let cur = null
let nxt = null
let swapping = false

function play(video) {
  if (!video) return
  const p = video.play()
  if (p && typeof p.catch === 'function') p.catch(() => {})
}

function tick() {
  if (swapping || !cur) return
  if (!cur.duration || Number.isNaN(cur.duration)) return
  if (cur.duration - cur.currentTime > FADE) return

  swapping = true
  const out = cur

  try {
    nxt.currentTime = 0
  } catch {
    /* 元数据未就绪时忽略 */
  }
  play(nxt)
  nxt.classList.add('is-active')
  out.classList.remove('is-active')

  cur = nxt
  nxt = out

  swapTimer = window.setTimeout(() => {
    try {
      out.pause()
      out.currentTime = 0
    } catch {
      /* 同上 */
    }
    swapping = false
  }, FADE * 1000 + 100)
}

function stop() {
  if (intervalId) {
    window.clearInterval(intervalId)
    intervalId = null
  }
  if (swapTimer) {
    window.clearTimeout(swapTimer)
    swapTimer = null
  }
  ;[vidA.value, vidB.value].forEach((v) => {
    if (!v) return
    v.removeEventListener('timeupdate', tick)
    try {
      v.pause()
    } catch {
      /* 忽略 */
    }
  })
}

onMounted(() => {
  const A = vidA.value
  const B = vidB.value
  if (!A || !B) return

  const reduce =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  if (reduce) {
    /* 静帧首帧：暂停并回到 0，不做任何播放与淡出 */
    A.removeAttribute('autoplay')
    try {
      A.pause()
      B.pause()
      A.currentTime = 0
    } catch {
      /* 忽略 */
    }
    return
  }

  cur = A
  nxt = B
  play(A)

  A.addEventListener('timeupdate', tick)
  B.addEventListener('timeupdate', tick)
  /* 部分内核（Edge 节能模式）把 timeupdate 节流到不足以覆盖 0.9s 淡出窗口，
     用 150ms 轮询兜底；tick 幂等，已切换时一次判断即返回。 */
  intervalId = window.setInterval(tick, 150)
})

onBeforeUnmount(stop)
</script>

<style scoped>
.video-backdrop {
  position: absolute;
  inset: 0;
  overflow: hidden;
  background: #000;
  pointer-events: none;
}

.vb-video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  background: #000;
  opacity: 0;
  transition: opacity 0.9s linear;
}

.vb-video.is-active {
  opacity: 1;
}

.vb-scrim {
  position: absolute;
  inset: 0;
}

@media (prefers-reduced-motion: reduce) {
  .vb-video {
    transition: none;
  }
}
</style>
