<template>
  <el-drawer v-model="open" :size="drawerSize" direction="rtl" :with-header="false">
    <div class="notice-shell">
      <header class="notice-head">
        <div class="notice-head-text">
          <div class="notice-title">通知中心</div>
          <div class="notice-sub">竞赛通知 · 考证节点 · 浏览器推送</div>
        </div>
        <button class="close-btn" type="button" aria-label="关闭通知中心" @click="open = false">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </header>

      <div class="notice-body">
        <section class="push-card" aria-labelledby="push-title">
          <div class="push-head">
            <div>
              <h3 id="push-title">浏览器推送</h3>
              <p>{{ pushMessage || '检查当前设备状态…' }}</p>
            </div>
            <span class="push-state" :data-state="pushState">{{ pushStateText }}</span>
          </div>
          <div class="push-actions">
            <el-button v-if="pushState === 'enabled'" :loading="pushBusy" @click="disablePush">关闭推送</el-button>
            <el-button v-else type="primary" :loading="pushBusy"
              :disabled="!canEnablePush" @click="enablePush">开启推送</el-button>
            <el-button link :loading="pushBusy" @click="refreshPushState">刷新状态</el-button>
          </div>
          <p class="push-note">只有本人未读通知会推送；关闭后本设备不再收到系统通知，站内消息仍保留。</p>
        </section>

        <div class="notice-toolbar">
          <div>
            <h3>站内通知</h3>
            <span role="status" aria-atomic="true">{{ unreadCount }} 条未读通知</span>
          </div>
          <div class="notice-actions">
            <el-button size="small" :loading="loading" @click="loadNotices">刷新</el-button>
            <el-button size="small" :disabled="!hasUnread || loading" @click="markAllRead">全部已读</el-button>
          </div>
        </div>

        <el-alert v-if="loadError" class="notice-error" type="error" :closable="false" show-icon
          :title="loadError" />
        <el-empty v-else-if="!loading && !notices.length" description="当前没有未读通知" />

        <div v-else v-loading="loading" class="notice-list">
          <article v-for="item in notices" :key="noticeKey(item)" class="notice-row">
            <div class="notice-row-head">
              <span class="notice-kind" :data-kind="noticeKind(item)">{{ noticeKindText(item) }}</span>
              <span class="notice-unread" aria-hidden="true" />
              <time v-if="item.published_at">{{ item.published_at }}</time>
            </div>
            <h4 class="notice-row-title">{{ item.title }}</h4>
            <p v-if="item.content" class="notice-row-content">{{ item.content }}</p>
            <a v-if="safeNoticeUrl(item.url)" :href="safeNoticeUrl(item.url)" target="_blank"
              rel="noopener noreferrer" class="notice-link">查看原文 <span aria-hidden="true">↗</span></a>
            <span v-else class="notice-source">来源：{{ item.source || '站内通知' }}</span>
          </article>
        </div>
        <div class="notice-foot">已读水位：{{ lastReadAt || '未读' }} · 数值与通知内容来自确定性引擎</div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
// NotificationCenter：学生站内通知与 Web Push 授权的单一入口。
// 不生成通知、不改写水位、不接收任意 student_id；仅展示接口返回内容。

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useNotifications } from '../../composables/useNotifications'

const open = ref(false)
const drawerSize = computed(() => (window.innerWidth < 768 ? '100%' : '460px'))
const {
  notices, unreadCount, lastReadAt, loading, loadError, hasUnread,
  loadNotices, markAllRead, pushState, pushMessage, pushBusy,
  loadPushConfig, refreshPushState, enablePush, disablePush,
} = useNotifications()

const pushStateText = computed(() => ({
  checking: '检查中',
  unsupported: '浏览器不支持',
  unconfigured: '服务端未配置',
  denied: '权限被拒绝',
  idle: '未开启',
  enabled: '已开启',
}[pushState.value] || '未开启'))

const canEnablePush = computed(() =>
  ['idle', 'denied'].includes(pushState.value) && !pushBusy.value)

function noticeKind(item) {
  if (item?.kind === 'cert' || item?.source === 'cert') return 'cert'
  if (item?.kind === 'exam' || item?.source === 'exam') return 'exam'
  return 'competition'
}

function noticeKindText(item) {
  return {
    competition: '竞赛通知',
    cert: '考证节点',
    exam: '招考机会',
  }[noticeKind(item)]
}

function noticeKey(item) {
  return `${noticeKind(item)}:${item?.id ?? item?.title ?? ''}`
}

function safeNoticeUrl(raw) {
  if (!raw) return ''
  try {
    const parsed = new URL(String(raw), window.location.origin)
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : ''
  } catch {
    return ''
  }
}

function handleOpen() {
  open.value = true
  loadNotices()
  loadPushConfig()
}

function handlePushMessage(event) {
  if (event?.data?.type === 'qh:open-notices') handleOpen()
}

watch(open, (visible) => {
  if (!visible) return
  loadNotices()
})

onMounted(() => {
  window.addEventListener('qh:open-notices', handleOpen)
  navigator.serviceWorker?.addEventListener?.('message', handlePushMessage)
  if (new URLSearchParams(window.location.search).get('notices') === 'open') handleOpen()
})

onBeforeUnmount(() => {
  window.removeEventListener('qh:open-notices', handleOpen)
  navigator.serviceWorker?.removeEventListener?.('message', handlePushMessage)
})
</script>

<style scoped>
.notice-shell {
  display: flex;
  height: 100%;
  flex-direction: column;
  background: #f5f6f8;
}

.notice-head {
  display: flex;
  height: 64px;
  flex: 0 0 auto;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  border-bottom: 1px solid #e4e7ee;
  background: #fff;
}

.notice-head-text { min-width: 0; }
.notice-title { color: #16181d; font-size: 16px; font-weight: 650; }
.notice-sub { color: #5f6672; font-size: 13px; }

.close-btn {
  display: grid;
  width: 36px;
  height: 36px;
  margin-left: auto;
  place-items: center;
  border: 1px solid #e4e7ee;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
}

.close-btn svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: #5f6672;
  stroke-width: 1.8;
  stroke-linecap: round;
}

.notice-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 16px;
}

.push-card {
  padding: 16px;
  border: 1px solid #e4e7ee;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 1px 2px rgb(16 24 40 / 4%);
}

.push-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.push-head h3,
.notice-toolbar h3 {
  margin: 0;
  color: #16181d;
  font-size: 15px;
  font-weight: 650;
}

.push-head p {
  margin: 4px 0 0;
  color: #5f6672;
  font-size: 13px;
  line-height: 1.55;
}

.push-state {
  flex: 0 0 auto;
  padding: 3px 9px;
  border: 1px solid #d8dde8;
  border-radius: 999px;
  color: #5f6672;
  font-size: 12px;
}

.push-state[data-state='enabled'] {
  border-color: #b9e7dd;
  background: #eefaf6;
  color: #0b7a6b;
}

.push-state[data-state='denied'],
.push-state[data-state='unsupported'] {
  border-color: #f5c5c1;
  background: #fff0ef;
  color: #b42318;
}

.push-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.push-note {
  margin: 10px 0 0;
  color: #6b7280;
  font-size: 12.5px;
  line-height: 1.55;
}

.notice-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 20px 0 12px;
}

.notice-toolbar span {
  color: #5f6672;
  font-size: 13px;
}

.notice-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.notice-error { margin-bottom: 12px; }

.notice-list {
  display: flex;
  min-height: 80px;
  flex-direction: column;
  gap: 10px;
}

.notice-row {
  padding: 13px 14px;
  border: 1px solid #e4e7ee;
  border-radius: 10px;
  background: #fff;
}

.notice-row-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.notice-kind {
  padding: 2px 8px;
  border-radius: 999px;
  background: #e9efff;
  color: #1951c3;
  font-size: 12px;
  font-weight: 600;
}

.notice-kind[data-kind='cert'] { background: #fff7e6; color: #9a5b00; }
.notice-kind[data-kind='exam'] { background: #eefaf6; color: #0b7a6b; }

.notice-unread {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #1951c3;
}

.notice-row-head time {
  margin-left: auto;
  color: #6b7280;
  font-size: 12px;
}

.notice-row-title {
  margin: 8px 0 0;
  color: #16181d;
  font-size: 14.5px;
  font-weight: 650;
  line-height: 1.55;
}

.notice-row-content {
  margin: 5px 0 0;
  color: #5f6672;
  font-size: 13.5px;
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.notice-link,
.notice-source {
  display: inline-block;
  margin-top: 8px;
  color: #1951c3;
  font-size: 13px;
  text-decoration: none;
}

.notice-source { color: #6b7280; }
.notice-link:hover { text-decoration: underline; }

.notice-foot {
  margin-top: 16px;
  color: #6b7280;
  font-size: 12.5px;
}

@media (max-width: 560px) {
  .notice-body { padding: 12px; }
  .notice-head { padding: 0 12px; }
  .push-head { flex-direction: column; }
  .notice-toolbar { align-items: flex-start; flex-direction: column; }
  .push-actions :deep(.el-button),
  .notice-actions :deep(.el-button) { min-height: 44px; }
}
</style>
