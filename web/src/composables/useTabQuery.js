// 聚合板块的二级 Tab 与地址栏 ?tab= 双向同步。
// 目的：刷新、分享、从别处跳进来都能落回同一个分段；把这段逻辑收成一处，
// 避免四个聚合页各写一遍（写岔了就会出现「刷新回到第一个 Tab」这种低级问题）。
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export function useTabQuery(tabs, { param = 'tab' } = {}) {
  const route = useRoute()
  const router = useRouter()
  const keys = tabs.map((t) => t.key)
  const fallback = keys[0]

  const pick = (raw) => (keys.includes(String(raw)) ? String(raw) : fallback)
  const tab = ref(pick(route.query[param]))

  watch(
    () => route.query[param],
    (raw) => {
      tab.value = pick(raw)
    }
  )

  function go(key, extra = {}) {
    if (!keys.includes(key)) return
    tab.value = key
    const query = { ...route.query, ...extra }
    // 首个 Tab 不写进地址栏，URL 保持干净
    if (key === fallback) delete query[param]
    else query[param] = key
    router.replace({ query })
  }

  return { tab, go }
}
