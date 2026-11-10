// 智能助手抽屉的全局开关：宠物点击、侧栏问法、抽屉本身都从这里拿同一份状态，
// 避免"宠物点开了、抽屉却没反应"这类两份状态的问题。
import { ref } from 'vue'

const open = ref(false)
const seed = ref('')

export function useAssistant() {
  // q 为空 = 只开抽屉，由用户自己提问
  function ask(q) {
    seed.value = String(q || '').trim()
    open.value = true
  }

  function close() {
    open.value = false
    seed.value = ''
  }

  return { open, seed, ask, close }
}
