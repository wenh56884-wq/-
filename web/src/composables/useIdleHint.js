// 冷场提示：学生超过时限没动作，AI 宠物（小航）冒一句结构化提示。
// 使用方：InterviewRoom（1v1 面试，按题型给抓手）、GroupRoom（群面，按局面给推进建议）。
//
// 设计约束（为什么这么写）：
// - 确定性模板文案、不发 LLM 请求——提示必须在 1 秒内出现，不能比学生还慢；
//   文案按题型/局面分组，由调用方的 pick(count) 决定说哪句（count 是已说过的条数，
//   同一道题内不重复）。
// - 尊重宠物专注模式：focusMode 时 usePet 的 petSay 返回 false，这里不重试不计数。
// - 学生一有动作（打字/发言）就 poke 重新计时；一道题/一场最多 maxHints 条，
//   防止提示刷屏比面试官还吵。
// - pick 返回 null（此刻不适合说话，如 AI 正在发言、正在提交）时本次跳过、
//   不自动续期，等下一次 poke 再重新计时。

import { onBeforeUnmount } from 'vue'
import { petSay } from './usePet'

export function useIdleHint({ timeoutMs = 45000, maxHints = 2, pick } = {}) {
  let timer = null
  let count = 0

  function arm() {
    disarm()
    timer = setTimeout(fire, timeoutMs)
  }

  function disarm() {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  function fire() {
    timer = null
    if (count >= maxHints) return
    const text = typeof pick === 'function' ? pick(count) : null
    if (!text) return
    if (petSay(text)) count += 1
  }

  // 学生有动作：重新计时（只有还有提示额度时才续）
  function poke() {
    if (timer || count >= maxHints) return
    arm()
  }

  // 进入新一轮（新题目/新场次）：清零计数并重新开始计时
  function restart() {
    count = 0
    arm()
  }

  function stop() {
    disarm()
  }

  onBeforeUnmount(stop)

  return { arm, poke, restart, stop }
}
