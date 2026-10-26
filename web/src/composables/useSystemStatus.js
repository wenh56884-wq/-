// useSystemStatus：轮询 /health 作为「动态信息」的数据脉搏（30 秒一次，多页面共享同一个轮询）
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'

import http from '../api/http'

const CHECK_INTERVAL = 30000

const state = reactive({
  status: 'checking', // ok / degraded / down / checking
  db: '-',
  duckdb: '-',
  llm: '-',
  error: '',
  lastCheckAt: null,
  checking: false
})

let timer = null
let refCount = 0

async function checkHealth() {
  state.checking = true
  try {
    const { data } = await http.get('/health')
    state.status = String(data?.status || 'unknown')
    state.db = String(data?.db || '-')
    state.duckdb = String(data?.duckdb || '-')
    state.llm = String(data?.llm || '-')
    state.error = ''
    state.lastCheckAt = new Date()
  } catch (err) {
    state.status = 'down'
    state.error = err?.message || '服务不可达'
    state.lastCheckAt = new Date()
  } finally {
    state.checking = false
  }
}

export function useSystemStatus() {
  refCount += 1
  if (!timer) {
    checkHealth()
    timer = setInterval(checkHealth, CHECK_INTERVAL)
  }
  onUnmounted(() => {
    refCount -= 1
    if (refCount <= 0 && timer) {
      clearInterval(timer)
      timer = null
    }
  })
  return { health: state, refresh: checkHealth }
}

function pad(n) {
  return String(n).padStart(2, '0')
}

// useClock：每秒走一次的实时时钟（页面级动态信息）
export function useClock() {
  const now = ref(new Date())
  let ticker = null
  onMounted(() => {
    ticker = setInterval(() => {
      now.value = new Date()
    }, 1000)
  })
  onUnmounted(() => {
    if (ticker) clearInterval(ticker)
  })
  const timeText = computed(() => {
    const d = now.value
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  })
  // ago 依赖 now 每秒刷新：传延时基点即可得到「刚刚 / N 秒前 / N 分钟前」的动态文案
  function ago(date) {
    if (!date) return '未刷新'
    const seconds = Math.max(0, Math.round((now.value - date) / 1000))
    if (seconds < 5) return '刚刚'
    if (seconds < 60) return `${seconds} 秒前`
    return `${Math.floor(seconds / 60)} 分钟前`
  }
  return { now, timeText, ago }
}
