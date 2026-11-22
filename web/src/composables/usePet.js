// web/src/composables/usePet.js
// 职责：AI 宠物前端状态编排——心情、专注模式、对话、主动说话轮询。
// 铁律落地：数值（心情/专注/下下次说话时间）来自后端 engine.pet；前端只做展示与触发。
// 单例：宠物是全局唯一陪伴，state 为模块级单例，多组件共享。

import { reactive, onMounted, onBeforeUnmount } from 'vue'
import http from '../api/http'

// 模块级单例状态
const state = reactive({
  mood: 'idle',            // 驱动宠物立绘动画：idle/happy/thinking/sleepy
  focusMode: false,        // 专注模式：开启后宠物不再主动说话
  name: '小航',
  greeting: '嗨，我是小航，今天想聊点什么呀？',
  personality: { name: '小航', species: '启航小助手', tone: '活泼、鼓励、像学长一样陪伴', greeting: '嗨，我是小航，今天想聊点什么呀？', encourage: ['加油哦，我相信你！', '慢慢来，每一步都算数。', '你做得很好，继续保持。'] },
  memories: [],           // 宠物记住的长期事实
  bubbleText: '',          // 当前气泡要说的话
  sending: false,
  available: false         // 登录后才可用
})

let proactiveTimer = null
let mountedCount = 0
// 首次挂载时只初始化一次；登录页不初始化（宠物未渲染、后端全 401），
// 登录后宠物挂载再补初始化。
let started = false
// 主动说话门控：用户至少交互过一次才允许；连续 10 分钟没交互则静默。
// 页面刚打开时绝不冒话——陪伴要等用户先打招呼。
let lastInteractAt = 0
const IDLE_SILENCE_MS = 10 * 60 * 1000

function markInteract() {
  lastInteractAt = Date.now()
}

// 业务关键时刻让宠物说一句话（面试冷场提示等）。模块级导出：不需要组件生命周期，
// 在 setup 里随时可调。专注模式下闭嘴（返回 false，调用方可据此决定是否再安排）。
export function petSay(text) {
  if (!text || state.focusMode || !state.available) return false
  state.bubbleText = text
  return true
}

async function loadPersonality() {
  try {
    const { data } = await http.get('/pet/personality')
    state.personality = data
    state.name = data.name
    state.greeting = data.greeting
  } catch (e) {
    // 未登录或失败：保留默认值，不打扰
  }
}

async function setPersonality(payload) {
  try {
    const { data } = await http.put('/pet/personality', payload)
    state.personality = data
    state.name = data.name
    state.greeting = data.greeting
  } catch (e) {
    // 静默失败，保留旧值
  }
}

async function loadMemories() {
  try {
    const { data } = await http.get('/pet/memories')
    state.memories = data.items || []
  } catch (e) {
    // 静默失败，保留旧值
  }
}

// 删除一条长期记忆：成功后本地同步移除，不整表重拉
async function deleteMemory(id) {
  try {
    await http.delete(`/pet/memories/${id}`)
    state.memories = state.memories.filter((m) => m.id !== id)
    return true
  } catch (e) {
    return false
  }
}

// 编辑一条长期记忆的文本：成功后本地同步更新
async function updateMemory(id, content) {
  const text = String(content || '').trim()
  if (!text) return false
  try {
    await http.put(`/pet/memories/${id}`, { content: text })
    const target = state.memories.find((m) => m.id === id)
    if (target) target.content = text
    return true
  } catch (e) {
    return false
  }
}

async function loadState() {
  try {
    const { data } = await http.get('/pet/state')
    state.mood = data.mood
    state.focusMode = data.focus_mode
    state.name = data.name
    state.available = true
  } catch (e) {
    state.available = false
  }
}

async function chat(text) {
  if (!text || !text.trim() || state.sending) return
  markInteract()
  state.sending = true
  // 宠物对话走 LLM，偶尔会慢到 20s+；先给一句“在想”，再设 18s 上限，
  // 避免输入框一直禁用、用户以为界面卡死。
  state.bubbleText = '让我想想…'
  try {
    const { data } = await http.post('/pet/chat', { text }, { timeout: 18000 })
    state.bubbleText = data.reply || '我在听，再说一遍？'
    state.mood = data.mood
    state.available = true
  } catch (e) {
    state.bubbleText = '我这边有点慢，稍后再问我一次？'
  } finally {
    state.sending = false
  }
}

async function setFocus(on) {
  try {
    const { data } = await http.post('/pet/focus', { on })
    state.focusMode = data.focus_mode
  } catch (e) {
    // 静默失败，保留旧值
  }
}

async function proactiveTick() {
  if (state.focusMode) return
  if (!lastInteractAt) return // 从未交互过：不打扰
  if (Date.now() - lastInteractAt > IDLE_SILENCE_MS) return // 闲置太久：静默
  try {
    const { data } = await http.post('/pet/proactive')
    if (data.spoke) {
      state.bubbleText = data.text
      state.mood = data.mood
    }
  } catch (e) {
    // 静默
  }
}

function startProactive(intervalMs = 60000) {
  stopProactive()
  proactiveTimer = setInterval(proactiveTick, intervalMs)
}

function stopProactive() {
  if (proactiveTimer) {
    clearInterval(proactiveTimer)
    proactiveTimer = null
  }
}

// 登录成功后重拉宠物状态：App 层的 PetConsole 不随路由重挂，
// 若只在 mounted 时拉一次，登录页的 401 会把 available 永久卡在 false
function onSession() {
  loadPersonality()
  loadState()
  loadMemories()
}

export function usePet() {
  onMounted(() => {
    mountedCount += 1
    // 已初始化或登录页：不重复拉取（登录页宠物未渲染，后端接口全部 401）
    if (started) return
    if (window.location.pathname === '/login') return
    started = true
    // 全局只启动一次轮询与拉取
    loadPersonality()
    loadState()
    loadMemories()
    startProactive(60000)
    window.addEventListener('qh:session', onSession)
  })
  onBeforeUnmount(() => {
    mountedCount -= 1
    if (mountedCount <= 0) {
      mountedCount = 0
      started = false
      stopProactive()
      window.removeEventListener('qh:session', onSession)
    }
  })

  // 气泡消失后清空，以便下次相同文本能再次触发
  function clearBubble() {
    state.bubbleText = ''
  }

  // 点宠物：说问候或随机鼓励（陪伴感，不弹助手抽屉）
  async function onPetClick() {
    markInteract()
    if (state.sending) return
    const pool = [state.greeting, ...(state.personality?.encourage || [])].filter(Boolean)
    if (!pool.length) return
    state.bubbleText = pool[Math.floor(Math.random() * pool.length)]
  }

  return {
    state,
    chat,
    setFocus,
    setPersonality,
    loadMemories,
    loadState,
    deleteMemory,
    updateMemory,
    proactiveTick,
    startProactive,
    stopProactive,
    clearBubble,
    onPetClick,
    markInteract
  }
}
