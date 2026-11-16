// web/src/composables/useReveal.js
// 职责：IntersectionObserver 驱动的滚动入场——给 .qh-reveal 目标在进入视口时加 .is-revealed。
// reduced-motion / 无 IntersectionObserver 时直接全部可见；refresh() 支持动态子节点重扫。
import { onBeforeUnmount, onMounted, unref } from 'vue'

const SELECTOR = '.qh-reveal:not(.is-revealed)'

/** 创建入场观察器：observe(el) 注册单个元素，refresh() 重扫根节点（缺省 document）下的 .qh-reveal。 */
export function useReveal(rootRef) {
  let observer = null

  function motionOff() {
    return (
      typeof window === 'undefined' ||
      typeof IntersectionObserver === 'undefined' ||
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    )
  }

  function ensureObserver() {
    if (observer) return observer
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          entry.target.classList.add('is-revealed')
          observer.unobserve(entry.target)
        }
      },
      { threshold: 0.12 }
    )
    return observer
  }

  /** 注册一个元素；降级环境下立即加 .is-revealed。 */
  function observe(el) {
    if (!el || el.classList.contains('is-revealed')) return
    if (motionOff()) {
      el.classList.add('is-revealed')
      return
    }
    ensureObserver().observe(el)
  }

  /** 重扫根节点下所有未 reveal 的 .qh-reveal（动态列表渲染后调用）。 */
  function refresh() {
    const root = unref(rootRef) || document
    root.querySelectorAll(SELECTOR).forEach(observe)
  }

  onMounted(refresh)
  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = null
  })

  return { observe, refresh }
}