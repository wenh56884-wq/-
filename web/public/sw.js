// web/public/sw.js
// 职责：只处理启航 Web Push 的展示与点击路由；不缓存业务数据，不改写页面请求。

self.addEventListener('push', (event) => {
  if (!event.data) return
  let payload
  try {
    payload = event.data.json()
  } catch {
    return
  }
  const title = String(payload.title || '启航新通知').slice(0, 120)
  const body = String(payload.body || '你有一条新的站内通知').slice(0, 200)
  const tag = String(payload.tag || 'qihang-notice')
  const url = String(payload.url || '/student?notices=open')
  event.waitUntil(self.registration.showNotification(title, {
    body,
    tag,
    icon: '/favicon.svg',
    badge: '/favicon.svg',
    data: { url },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = String(event.notification.data?.url || '/student?notices=open')
  // 只允许落到本站同源路径，避免把推送正文里的任意 URL 注入导航。
  const url = new URL(target, self.location.origin)
  if (url.origin !== self.location.origin) return
  event.waitUntil((async () => {
    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    const existing = clients.find((client) => new URL(client.url).origin === self.location.origin)
    if (existing) {
      await existing.focus()
      existing.postMessage({ type: 'qh:open-notices' })
      return
    }
    await self.clients.openWindow(url.pathname + url.search)
  })())
})
