<template>
  <div class="shell" :class="{ 'shell-mobile': isMobile }">
    <!-- 移动端抽屉遮罩：点击即收起，禁止在手机上常驻展开侧栏 -->
    <div v-if="isMobile && drawer" class="scrim" @click="drawer = false" />

    <aside
      class="sidebar"
      :class="{ 'is-open': drawer, 'is-collapsed': collapsed && !isMobile }"
    >
      <!-- 1) 品牌区 -->
      <div class="sidebar-brand">
        <span class="brand-mark">启</span>
        <div v-if="!collapsedOnly" class="brand-text">
          <div class="brand-title">启航 · 生涯与岗位匹配</div>
          <div class="brand-sub">确定性引擎算数</div>
        </div>
      </div>

      <!-- 2) 主导航（内容溢出可滚动） -->
      <nav class="sidebar-nav" aria-label="主导航">
        <p v-if="!collapsedOnly" class="nav-group">工作区</p>
        <router-link
          v-for="item in menus"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ 'is-active': isActive(item.path) }"
          :title="collapsedOnly ? item.label : ''"
          @click="drawer = false"
        >
          <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path :d="ICONS[item.icon]" />
          </svg>
          <span v-if="!collapsedOnly" class="nav-text">
            <span class="nav-label">{{ item.label }}</span>
            <span class="nav-hint">{{ item.hint }}</span>
          </span>
        </router-link>
      </nav>

      <!-- 3) 次要操作 + 4) 用户信息 -->
      <div class="sidebar-foot">
        <button class="side-btn" type="button" @click="toggleCollapse">
          <span class="side-btn-icon">{{ collapsedOnly ? '»' : '«' }}</span>
          <span v-if="!collapsedOnly" class="side-btn-text">收起侧边栏</span>
        </button>
        <div class="user-card">
          <span class="user-avatar">{{ role === 'teacher' ? '教' : '学' }}</span>
          <div v-if="!collapsedOnly" class="user-meta">
            <div class="user-name">{{ identityText }}</div>
            <div class="user-role">{{ role === 'teacher' ? '教师账号' : '学生账号' }}</div>
          </div>
          <button v-if="!collapsedOnly" class="logout-btn" type="button" @click="logout">退出</button>
        </div>
      </div>
    </aside>

    <div class="content" :style="{ marginLeft: contentMargin }">
      <header class="topbar">
        <button
          v-if="isMobile"
          class="icon-btn"
          type="button"
          aria-label="打开导航"
          @click="drawer = true"
        >
          <span class="hamburger" />
        </button>
        <div class="topbar-title">
          <h1 class="page-title">{{ currentLabel }}</h1>
          <p class="page-sub">{{ currentHint }}</p>
        </div>

        <div class="pulse">
          <span class="pulse-item">
            <i class="dot" :class="dotClass(health.db)"></i>MySQL <b>{{ health.db }}</b>
          </span>
          <span class="pulse-item">
            <i class="dot" :class="dotClass(health.duckdb)"></i>DuckDB <b>{{ health.duckdb }}</b>
          </span>
          <span class="pulse-item">
            <i class="dot" :class="health.llm === 'configured' ? 'dot-ok' : 'dot-warn'"></i>
            LLM <b>{{ health.llm }}</b>
          </span>
          <span class="pulse-tag" :class="statusTag">{{ statusText }}</span>
          <span class="pulse-time">健康检测 {{ ago(health.lastCheckAt) }}</span>
          <button class="ghost-btn" type="button" :disabled="health.checking" @click="refresh">
            {{ health.checking ? '检测中' : '立即刷新' }}
          </button>
        </div>

        <div class="who">
          <span class="who-clock">{{ timeText }}</span>
        </div>
      </header>

      <main class="page-main">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>

    <!-- 悬浮助手：右下角「摸鱼」形象按钮 → 右侧抽屉，不占侧栏导航位 -->
    <button
      class="assistant-fab"
      type="button"
      aria-label="打开智能助手"
      title="不想摸鱼了？来问我"
      :class="{ 'is-open': chatOpen }"
      @click="chatOpen = true"
    >
      <img class="fab-img" :src="moyuImg" alt="智能助手" />
      <span class="fab-badge">AI</span>
    </button>

    <ChatDrawer v-model="chatOpen" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { clearSession, currentRole } from '../api/http'
import ChatDrawer from '../components/ChatDrawer.vue'
import { useClock, useSystemStatus } from '../composables/useSystemStatus'
import moyuImg from '../assets/deepseek-mo-yu.webp'

// 24×24 stroke 图标（无外部图标库依赖）
const ICONS = {
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  users: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
  chat: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
  self: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8',
  // 招考：卷轴/公告形态（纸 + 折角 + 两行正文）
  doc: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h4',
  // 岗位：公文包（把手 + 箱体）
  briefcase: 'M20 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2zM16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2M2 12h20'
}

// 侧栏宽度：规范上限 280px，统一 256px；折叠态 64px
const SIDEBAR_W = 256
const SIDEBAR_COLLAPSED_W = 64
const MOBILE_QUERY = '(max-width: 1023px)'

const { health, refresh } = useSystemStatus()
const { timeText, ago } = useClock()
const router = useRouter()
const route = useRoute()
const role = currentRole()

// 智能助手改为右下角悬浮入口（抽屉），不再占用侧栏导航位
const MENUS = {
  teacher: [
    { path: '/teacher', label: '班级总览', hint: '全班预警与概貌', icon: 'grid' },
    { path: '/teacher/students', label: '学生档案', hint: '全班 → 个人详情', icon: 'users' },
    { path: '/teacher/jobs', label: '岗位库', hint: '企业岗位周更', icon: 'briefcase' },
    { path: '/teacher/exams', label: '招考信息', hint: '考公 / 考编 / 考研', icon: 'doc' }
  ],
  student: [
    { path: '/student', label: '我的画像', hint: '预警 + 岗位推荐', icon: 'self' },
    { path: '/student/jobs', label: '岗位库', hint: '企业岗位搜索', icon: 'briefcase' },
    { path: '/student/exams', label: '招考信息', hint: '考公 / 考编 / 考研', icon: 'doc' }
  ]
}

const menus = computed(() => MENUS[role] || MENUS.student)
const collapsed = ref(false)
const drawer = ref(false)
const chatOpen = ref(false)
const isMobile = ref(false)
let media = null

const collapsedOnly = computed(() => collapsed.value && !isMobile.value)

const contentMargin = computed(() => {
  if (isMobile.value) return '0px'
  return `${collapsed.value ? SIDEBAR_COLLAPSED_W : SIDEBAR_W}px`
})

// 取「最长匹配」而非「第一个匹配」：否则 /teacher/exams 会被 /teacher 抢先命中，
// 顶栏标题就永远停在「班级总览」。
const currentItem = computed(() => {
  const hits = menus.value.filter(
    (item) => route.path === item.path || route.path.startsWith(`${item.path}/`)
  )
  if (!hits.length) return menus.value[0]
  return hits.reduce((best, cur) => (cur.path.length > best.path.length ? cur : best))
})
const currentLabel = computed(() => currentItem.value?.label || '')
const currentHint = computed(() => currentItem.value?.hint || '')

function isActive(path) {
  return route.path === path || route.path.startsWith(`${path}/`)
}

function toggleCollapse() {
  if (isMobile.value) {
    drawer.value = !drawer.value
    return
  }
  collapsed.value = !collapsed.value
  localStorage.setItem('qh_sidebar_collapsed', collapsed.value ? '1' : '0')
}

function syncViewport(event) {
  isMobile.value = event.matches
  if (!event.matches) {
    drawer.value = false
  }
}

const identityText = computed(() => {
  if (role === 'teacher') {
    const tenant = localStorage.getItem('qh_tenant_id')
    return tenant ? `教师 · 租户 ${tenant}` : '教师'
  }
  return localStorage.getItem('qh_student_no') || '学生'
})

const statusText = computed(() => {
  const map = { ok: '服务正常', degraded: '部分降级', down: '服务不可达', checking: '检测中' }
  return map[health.status] || health.status
})

const statusTag = computed(() => {
  const map = { ok: 'tag-ok', degraded: 'tag-warn', down: 'tag-bad', checking: 'tag-idle' }
  return map[health.status] || 'tag-idle'
})

function dotClass(state) {
  if (state === 'ok') return 'dot-ok'
  if (state === 'down') return 'dot-bad'
  return 'dot-warn'
}

function logout() {
  clearSession()
  router.push('/login')
}

onMounted(() => {
  media = window.matchMedia(MOBILE_QUERY)
  isMobile.value = media.matches
  media.addEventListener('change', syncViewport)
  // 折叠偏好持久化（但移动端永远不展开常驻）
  collapsed.value = localStorage.getItem('qh_sidebar_collapsed') === '1'
})

onBeforeUnmount(() => {
  media?.removeEventListener('change', syncViewport)
})
</script>

<style scoped>
.shell {
  min-height: 100vh;
  background: #fafafa;
}

/* ---------- 侧边栏：fixed 定位，宽 256px（≤280px 上限） ---------- */
.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  width: 256px;
  z-index: 40;
  display: flex;
  flex-direction: column;
  background: #fafafa;
  border-right: 1px solid #e4e4e7;
  transform: translateX(0);
  transition: width 150ms ease, transform 150ms ease;
}

.sidebar.is-collapsed {
  width: 64px;
}

.sidebar-brand {
  height: 56px;
  flex: 0 0 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  border-bottom: 1px solid #e4e4e7;
  overflow: hidden;
}

.brand-mark {
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.brand-title {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: #18181b;
  white-space: nowrap;
}

.brand-sub {
  font-size: 11px;
  color: #a1a1aa;
  white-space: nowrap;
}

/* 主导航区：内容溢出时自身滚动，不挤压底部信息 */
.sidebar-nav {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 12px 8px;
  scrollbar-width: thin;
}

.nav-group {
  margin: 0 0 6px;
  padding: 0 8px;
  font-size: 11px;
  color: #a1a1aa;
  letter-spacing: 0.04em;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  margin: 2px 0;
  border-radius: 8px;
  color: #52525b;
  text-decoration: none;
  /* 仅颜色/背景过渡，150ms，无位移波纹 */
  transition: background-color 150ms ease, color 150ms ease;
  position: relative;
}

.nav-item:hover {
  background: #f4f4f5;
  color: #18181b;
}

/* Magnetic Icon Shift：hover 时图标轻移 2px */
.nav-item:hover .nav-icon {
  transform: translateX(2px);
}

.nav-icon {
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  transition: transform 150ms ease;
}

/* 稳定激活锚点：左侧 2px 强调线 + 浅底 + 字重提升，不做浮动动画 */
.nav-item.is-active {
  background: #eff6ff;
  color: #1d4ed8;
  font-weight: 500;
}

.nav-item.is-active::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 6px;
  bottom: 6px;
  width: 2px;
  border-radius: 8px;
  background: #2563eb;
}

.nav-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.nav-label {
  font-size: 13px;
  line-height: 1.3;
  white-space: nowrap;
}

.nav-hint {
  font-size: 11px;
  color: #a1a1aa;
  white-space: nowrap;
}

.sidebar-foot {
  flex: 0 0 auto;
  border-top: 1px solid #e4e4e7;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.side-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #52525b;
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.side-btn:hover {
  background: #f4f4f5;
  color: #18181b;
}

.side-btn-icon {
  width: 18px;
  text-align: center;
  font-size: 13px;
}

.user-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: #ffffff;
  border: 1px solid #e4e4e7;
  border-radius: 8px;
}

.user-avatar {
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: 8px;
  background: #f4f4f5;
  color: #52525b;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.user-meta {
  min-width: 0;
  flex: 1 1 auto;
}

.user-name {
  font-size: 12px;
  color: #18181b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-role {
  font-size: 11px;
  color: #a1a1aa;
}

.logout-btn {
  flex: 0 0 auto;
  border: 0;
  border-radius: 8px;
  padding: 4px 10px;
  background: #f4f4f5;
  color: #52525b;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.logout-btn:hover {
  background: #fee2e2;
  color: #b91c1c;
}

/* ---------- 主内容区：左边距对齐侧栏宽度，自身滚动上下文 ---------- */
.content {
  min-height: 100vh;
  transition: margin-left 150ms ease;
  min-width: 0;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 24px;
  background: #ffffff;
  border-bottom: 1px solid #e4e4e7;
}

.topbar-title {
  min-width: 0;
  flex: 0 0 auto;
}

.page-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: #18181b;
}

.page-sub {
  margin: 0;
  font-size: 11px;
  color: #a1a1aa;
}

.icon-btn {
  width: 32px;
  height: 32px;
  border: 1px solid #e4e4e7;
  border-radius: 8px;
  background: #ffffff;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 150ms ease;
}

.icon-btn:hover {
  background: #f4f4f5;
}

.hamburger,
.hamburger::before,
.hamburger::after {
  display: block;
  width: 16px;
  height: 1.5px;
  background: #52525b;
  content: '';
  position: relative;
}

.hamburger::before {
  position: absolute;
  top: -5px;
}

.hamburger::after {
  position: absolute;
  top: 5px;
}

.pulse {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
  font-size: 12px;
  color: #52525b;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.pulse-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.pulse-item b {
  color: #18181b;
  font-weight: 500;
}

.pulse-time {
  color: #a1a1aa;
}

.pulse-tag {
  padding: 1px 8px;
  border-radius: 8px;
  font-size: 11px;
  border: 1px solid #e4e4e7;
  background: #fafafa;
  color: #52525b;
}

.tag-ok {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
}

.tag-warn {
  background: #fffbeb;
  border-color: #fde68a;
  color: #b45309;
}

.tag-bad {
  background: #fef2f2;
  border-color: #fecaca;
  color: #b91c1c;
}

.ghost-btn {
  border: 1px solid #e4e4e7;
  border-radius: 8px;
  background: #ffffff;
  color: #52525b;
  font-size: 12px;
  font-family: inherit;
  padding: 4px 10px;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.ghost-btn:hover:not(:disabled) {
  background: #f4f4f5;
  color: #18181b;
}

.ghost-btn:disabled {
  opacity: 0.6;
  cursor: default;
}

.who-clock {
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: #52525b;
}

.page-main {
  padding: 0;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 8px;
  display: inline-block;
  background: #d4d4d8;
}

.dot-ok {
  background: #16a34a;
}

.dot-warn {
  background: #d97706;
}

.dot-bad {
  background: #dc2626;
}

/* ---------- 移动端：抽屉 + 汉堡 + 遮罩，主区占满宽度 ---------- */
.scrim {
  position: fixed;
  inset: 0;
  z-index: 35;
  background: rgba(24, 24, 27, 0.45);
}

/* ---------- 悬浮 AI 助手入口（右下角小人） ---------- */
.assistant-fab {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 45;
  width: 64px;
  height: 64px;
  padding: 0;
  border: 0;
  border-radius: 16px;
  background: transparent;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: visible;
  transition: transform 150ms ease, box-shadow 150ms ease;
}

.assistant-fab:hover {
  transform: translateY(-3px) scale(1.04);
}

.fab-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  filter: drop-shadow(0 4px 10px rgba(24, 24, 27, 0.16));
}

.assistant-fab.is-open {
  opacity: 0;
  pointer-events: none;
}

.fab-badge {
  position: absolute;
  top: -2px;
  right: -4px;
  padding: 1px 6px;
  border-radius: 8px;
  background: #2563eb;
  color: #ffffff;
  font-size: 10px;
  font-weight: 500;
  border: 1px solid #ffffff;
}

/* 抽屉本体：抹掉默认内边距，交给 ChatDrawer 自己排布 */
.chat-drawer :deep(.el-drawer__body) {
  padding: 0;
}

@media (max-width: 1023px) {
  .sidebar {
    transform: translateX(-100%);
    box-shadow: 0 8px 24px rgba(24, 24, 27, 0.08);
  }

  .sidebar.is-open {
    transform: translateX(0);
  }

  .sidebar.is-collapsed {
    width: 256px;
  }

  .topbar {
    padding: 0 16px;
    gap: 12px;
  }

  .topbar-title {
    flex: 1 1 auto;
  }

  .pulse {
    display: none;
  }

  .assistant-fab {
    right: 12px;
    bottom: 12px;
    width: 56px;
    height: 56px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sidebar,
  .content,
  .nav-item,
  .nav-icon,
  .side-btn,
  .ghost-btn,
  .logout-btn,
  .icon-btn,
  .assistant-fab {
    transition: none;
  }
}
</style>
