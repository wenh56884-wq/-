// web/src/composables/useNotifications.js
// 职责：站内通知与浏览器推送状态；身份沿用 JWT，不接受外部 student_id。
// 说明：只读取既有 /student/notices 与新增 /notifications/push/* 接口。

import { computed, ref } from 'vue'
import http from '../api/http'


export function useNotifications() {
  const notices = ref([])
  const unreadCount = ref(0)
  const lastReadAt = ref('')
  const loading = ref(false)
  const loadError = ref('')

  const pushConfig = ref({ enabled: false, public_key: '', contact_configured: false })
  const pushState = ref('checking')
  const pushMessage = ref('')
  const pushBusy = ref(false)
  const pushSupported = typeof window !== 'undefined'
    && 'Notification' in window
    && 'serviceWorker' in navigator
    && 'PushManager' in window

  const hasUnread = computed(() => unreadCount.value > 0)
  const pushEnabled = computed(() => pushState.value === 'enabled')

  async function loadNotices() {
    loading.value = true
    loadError.value = ''
    try {
      const { data } = await http.get('/student/notices', { params: { limit: 20 } })
      notices.value = Array.isArray(data?.items) ? data.items : []
      unreadCount.value = Number(data?.unread_cnt || 0)
      lastReadAt.value = String(data?.last_read_at || '')
    } catch (error) {
      notices.value = []
      unreadCount.value = 0
      loadError.value = error?.response?.data?.detail || '通知加载失败，请稍后重试'
    } finally {
      loading.value = false
    }
  }

  async function markAllRead() {
    if (!hasUnread.value) return
    try {
      await http.post('/student/notices/read')
      unreadCount.value = 0
      await loadNotices()
    } catch (error) {
      loadError.value = error?.response?.data?.detail || '标记已读失败，请稍后重试'
    }
  }

  function _base64ToUint8Array(value) {
    const padding = '='.repeat((4 - (value.length % 4)) % 4)
    const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/')
    const raw = window.atob(base64)
    return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)))
  }

  async function _serviceWorkerRegistration() {
    if (!pushSupported) return null
    try {
      return await navigator.serviceWorker.register('/sw.js')
    } catch {
      return null
    }
  }

  async function loadPushConfig() {
    try {
      const { data } = await http.get('/notifications/push/config')
      pushConfig.value = {
        enabled: Boolean(data?.enabled),
        public_key: String(data?.public_key || ''),
        contact_configured: Boolean(data?.contact_configured),
      }
    } catch {
      pushConfig.value = { enabled: false, public_key: '', contact_configured: false }
    }
    await refreshPushState()
  }

  async function refreshPushState() {
    if (!pushSupported) {
      pushState.value = 'unsupported'
      pushMessage.value = '当前浏览器不支持 Web Push'
      return
    }
    if (!pushConfig.value.enabled) {
      pushState.value = 'unconfigured'
      pushMessage.value = '服务端尚未配置浏览器推送'
      return
    }
    if (Notification.permission === 'denied') {
      pushState.value = 'denied'
      pushMessage.value = '浏览器已拒绝通知权限，可在站点设置中重新开启'
      return
    }
    const registration = await _serviceWorkerRegistration()
    if (!registration) {
      pushState.value = 'unsupported'
      pushMessage.value = 'Service Worker 注册失败'
      return
    }
    const subscription = await registration.pushManager.getSubscription()
    if (!subscription) {
      pushState.value = 'idle'
      pushMessage.value = '开启后可在浏览器收到新通知'
      return
    }
    let confirmed = false
    try {
      const { data } = await http.get('/notifications/push/status', {
        params: { endpoint: subscription.endpoint },
      })
      confirmed = Boolean(data?.enabled)
    } catch {
      confirmed = false
    }
    pushState.value = confirmed ? 'enabled' : 'idle'
    pushMessage.value = confirmed ? '已在本设备开启浏览器推送' : '本设备订阅尚未同步到服务端'
  }

  async function enablePush() {
    if (!pushSupported || !pushConfig.value.enabled) {
      await refreshPushState()
      return
    }
    pushBusy.value = true
    pushMessage.value = ''
    try {
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        pushState.value = 'denied'
        pushMessage.value = '未获得浏览器通知权限'
        return
      }
      const registration = await _serviceWorkerRegistration()
      if (!registration) {
        pushState.value = 'unsupported'
        pushMessage.value = 'Service Worker 注册失败'
        return
      }
      let subscription = await registration.pushManager.getSubscription()
      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: _base64ToUint8Array(pushConfig.value.public_key),
        })
      }
      const payload = subscription.toJSON()
      await http.put('/notifications/push/subscription', {
        endpoint: payload.endpoint,
        keys: payload.keys || {},
        user_agent: navigator.userAgent.slice(0, 300),
      })
      pushState.value = 'enabled'
      pushMessage.value = '已在本设备开启浏览器推送'
    } catch (error) {
      pushState.value = pushState.value === 'enabled' ? 'enabled' : 'idle'
      pushMessage.value = error?.response?.data?.detail || '开启失败，请稍后重试'
    } finally {
      pushBusy.value = false
    }
  }

  async function disablePush() {
    if (!pushSupported) return
    pushBusy.value = true
    try {
      const registration = await _serviceWorkerRegistration()
      const subscription = await registration?.pushManager.getSubscription()
      if (!subscription) {
        pushState.value = 'idle'
        pushMessage.value = '已关闭浏览器推送'
        return
      }
      const endpoint = subscription.endpoint
      try {
        await http.request({
          method: 'DELETE',
          url: '/notifications/push/subscription',
          data: { endpoint },
        })
      } catch (error) {
        pushMessage.value = error?.response?.data?.detail || '服务端退订失败，请重试'
        return
      }
      await subscription.unsubscribe()
      pushState.value = 'idle'
      pushMessage.value = '已关闭浏览器推送'
    } finally {
      pushBusy.value = false
    }
  }

  return {
    notices,
    unreadCount,
    lastReadAt,
    loading,
    loadError,
    hasUnread,
    loadNotices,
    markAllRead,
    pushConfig,
    pushState,
    pushMessage,
    pushBusy,
    pushSupported,
    pushEnabled,
    loadPushConfig,
    refreshPushState,
    enablePush,
    disablePush,
  }
}
