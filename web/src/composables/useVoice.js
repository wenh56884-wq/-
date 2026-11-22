// 群面语音能力（浏览器原生 Web Speech API，零后端依赖、零成本）
// - AI 候选人发言朗读：speechSynthesis，三位候选人各配不同音色（按系统可用音色择优）
// - 学生语音输入：SpeechRecognition（zh-CN）实时转文字填入发言框
// 降级约定（与 ExpressionLab 同款思路）：
//   · 朗读不受 HTTP 限制，http 站点也能响
//   · 语音输入要求"支持识别 API + 安全上下文（HTTPS 或 localhost）"，不满足时
//     sttSupported=false，调用方隐藏麦克风入口并给出文字模式提示
//   · 两种能力互不依赖，单独不可用不影响另一侧
// 明确不读的：主持人/议题播报（用户不要"面试官的语音"），只有 ice/data/spark 三位候选人开口。

import { ref } from 'vue'

const TTS = typeof window === 'undefined' ? null : window.speechSynthesis
const SpeechCtor = typeof window === 'undefined'
  ? null
  : (window.SpeechRecognition || window.webkitSpeechRecognition)
const isSecure = typeof window === 'undefined' ? true : window.isSecureContext !== false

// 朗读范围白名单：只有这三位候选人会被朗读，其余（host/moderator/system 等）一律静默
export const SPOKEN_SPEAKERS = ['ice', 'data', 'spark']

// 微调档位：音色本身已经区分三人，这里只做轻微的语速/音高差异
export const VOICE_PROFILES = {
  ice: { pitch: 1.0, rate: 1.05 },
  data: { pitch: 1.05, rate: 1.0 },
  spark: { pitch: 0.92, rate: 1.08 }
}

// ---------- 音色池：按质量打分，优先 Natural/Neural 在线音色（Edge）> Google 网络 > 桌面 SAPI ----------
// 每位候选人按性别/气质给定偏好序列，命中即用；都不可用时退回分数最高的中文音色
const SPEAKER_VOICE_PREFS = {
  ice: ['xiaoyi', 'xiaoxiao', 'yaoyao', 'tingting', 'huihui', 'yunxi'],
  data: ['xiaoxiao', 'xiaoyi', 'yaoyao', 'tingting', 'huihui', 'yunxi'],
  spark: ['yunxi', 'yunyang', 'yunjian', 'kangkang', 'yunxia']
}

const QUALITY_HINTS = ['natural', 'neural', 'online', 'google']

function scoreVoice(v) {
  const name = String(v?.name || '').toLowerCase()
  let s = 0
  for (const hint of QUALITY_HINTS) {
    if (name.includes(hint)) s += 6
  }
  if (/^zh[-_]cn/i.test(v?.lang || '')) s += 2
  else if (/^zh/i.test(v?.lang || '')) s += 1
  return s
}

let voicePool = []

function refreshVoicePool() {
  if (!TTS) return
  let voices = []
  try {
    voices = TTS.getVoices() || []
  } catch {
    return
  }
  voicePool = voices
    .filter((v) => /^zh/i.test(v.lang || ''))
    .sort((a, b) => scoreVoice(b) - scoreVoice(a))
}

// 按候选人偏好挑音色：先在偏好序列里找池子里已有的，找不到退回池首
function voiceFor(speakerId) {
  if (!voicePool.length) return null
  const prefs = SPEAKER_VOICE_PREFS[speakerId] || []
  for (const key of prefs) {
    const hit = voicePool.find((v) => String(v.name || '').toLowerCase().includes(key))
    if (hit) return hit
  }
  return voicePool[0]
}

// Chrome/Edge 的 voices 列表是异步加载的，先刷一次再挂监听；朗读前也会再刷
if (TTS) {
  refreshVoicePool()
  try {
    TTS.addEventListener?.('voiceschanged', refreshVoicePool)
  } catch {
    /* 老浏览器没有 addEventListener 就不监听，speak 前再刷一次 */
  }
}

export function useVoice() {
  const ttsReady = Boolean(TTS)
  const ttsOn = ref(ttsReady)
  const speakingKey = ref('')
  const listening = ref(false)
  const sttSupported = Boolean(SpeechCtor) && isSecure
  const sttHint = sttSupported
    ? ''
    : (!SpeechCtor
      ? '当前浏览器没有语音识别接口，建议改用 Chrome / Edge'
      : '语音输入需要 HTTPS 环境（当前站点请用文字发言）')

  // ---------------- 朗读：带队列，按到达顺序读完 ----------------
  const queue = []
  let speaking = false

  function _drain() {
    if (!TTS || speaking || !queue.length) return
    const item = queue.shift()
    speaking = true
    speakingKey.value = item.key
    const u = new SpeechSynthesisUtterance(String(item.text).slice(0, 300))
    const profile = VOICE_PROFILES[item.speakerId] || { pitch: 1.0, rate: 1.0 }
    u.pitch = profile.pitch
    u.rate = profile.rate
    u.lang = 'zh-CN'
    refreshVoicePool() // 每次朗读前再刷一次：voices 异步加载，晚到的音色也能被用上
    const v = voiceFor(item.speakerId)
    if (v) u.voice = v
    let done = false
    // 兜底：无声卡 / headless 环境里 utterance 可能永远不会触发 onend，按字数估时强制收尾
    const estMs = Math.min(30000, 4000 + String(item.text).length * 90)
    const finish = () => {
      if (done) return
      done = true
      clearTimeout(guard)
      speaking = false
      speakingKey.value = ''
      if (item.onDone) item.onDone()
      _drain()
    }
    const guard = setTimeout(finish, estMs)
    u.onend = finish
    u.onerror = finish
    try {
      TTS.speak(u)
    } catch {
      finish()
    }
  }

  // 一批新发言：清掉未读旧条目再排队，保持会议室实时感。
  // 白名单过滤：主持人/议题等一律不读（用户明确不要"面试官的语音"）
  function speakTurns(items) {
    if (!TTS || !ttsOn.value || !Array.isArray(items) || !items.length) return
    queue.length = 0
    speaking = false
    speakingKey.value = ''
    try {
      TTS.cancel()
    } catch {
      /* 还没开始朗读时 cancel 可能抛错，忽略 */
    }
    for (const t of items) {
      if (!t || !t.text) continue
      if (!SPOKEN_SPEAKERS.includes(t.speakerId)) continue
      queue.push({ key: t.key || '', text: t.text, speakerId: t.speakerId })
    }
    _drain()
  }

  function stopSpeak() {
    queue.length = 0
    speaking = false
    speakingKey.value = ''
    try {
      if (TTS) TTS.cancel()
    } catch {
      /* 同上 */
    }
  }

  // ---------------- 语音输入：continuous + interim，onend 自动续录 ----------------
  let rec = null
  let recFinal = ''
  let recInterim = ''
  let manualStop = false

  function startListen({ onText, onError } = {}) {
    if (!sttSupported || rec) return false
    let instance
    try {
      instance = new SpeechCtor()
    } catch {
      return false
    }
    rec = instance
    recFinal = ''
    recInterim = ''
    manualStop = false
    instance.lang = 'zh-CN'
    instance.continuous = true
    instance.interimResults = true
    instance.onresult = (event) => {
      recInterim = ''
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const r = event.results[i]
        if (r.isFinal) recFinal += r[0].transcript
        else recInterim += r[0].transcript
      }
      if (onText) onText(recFinal, recInterim)
    }
    instance.onerror = (e) => {
      const code = e?.error || ''
      if (onError && code !== 'aborted' && code !== 'no-speech') onError(code)
    }
    // Chrome 单段识别约 60 秒会自动 onend；用户没有手动停止就续录，保持"一直开着"
    instance.onend = () => {
      if (rec !== instance || manualStop || !listening.value) return
      try {
        instance.start()
      } catch {
        /* 已经在跑时 start 会抛错，忽略 */
      }
    }
    try {
      instance.start()
    } catch {
      rec = null
      return false
    }
    listening.value = true
    return true
  }

  // 停止并返回本次识别到的完整文本
  function stopListen() {
    listening.value = false
    if (!rec) return ''
    manualStop = true
    const current = rec
    rec = null
    current.onresult = null
    current.onerror = null
    current.onend = null
    try {
      current.stop()
    } catch {
      /* 已经结束的实例 stop 会抛错，忽略 */
    }
    const text = (recFinal + recInterim).trim()
    recFinal = ''
    recInterim = ''
    return text
  }

  function teardown() {
    stopSpeak()
    listening.value = false
    manualStop = true
    if (rec) {
      const current = rec
      rec = null
      current.onresult = null
      current.onerror = null
      current.onend = null
      try {
        current.abort()
      } catch {
        /* 已结束的实例 abort 会抛错，忽略 */
      }
    }
  }

  return {
    ttsReady,
    ttsOn,
    speakingKey,
    listening,
    sttSupported,
    sttHint,
    speakTurns,
    stopSpeak,
    startListen,
    stopListen,
    teardown
  }
}
