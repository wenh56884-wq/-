<template>
  <div class="shell">
    <!-- ============ 顶栏导航（参考讯飞星辰 MaaS：冷白 + 紫蓝、顶栏 + 全宽内容） ============ -->
    <header class="topnav" :class="{ 'is-scrolled': scrolled }">
      <div class="topnav-inner">
        <router-link class="brand" to="/" aria-label="启航首页">
          <span class="brand-mark">启</span>
          <span class="brand-text">
            <span class="brand-title">启航</span>
            <span class="brand-sub">生涯与岗位匹配</span>
          </span>
        </router-link>

        <!-- 桌面端：横向导航 pill；1024px 以下收起，改由汉堡打开抽屉 -->
        <nav v-if="!isMobile" class="nav" aria-label="主导航">
          <router-link
            v-for="item in menus"
            :key="item.path"
            :to="item.path"
            class="nav-pill"
            :class="{ 'is-active': isActive(item.path) }"
            :title="item.hint"
          >
            <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path :d="ICONS[item.icon]" />
            </svg>
            <span class="nav-label">{{ item.label }}</span>
          </router-link>
        </nav>

        <div class="nav-right">
          <!-- 运维细节收进状态点：正常时只显示一个绿点，出问题才展开看详情 -->
          <el-popover placement="bottom-end" :width="250" trigger="click">
            <template #reference>
              <button class="status-btn" type="button" :title="statusText">
                <i class="dot" :class="overallDot"></i>
                <span class="status-text">{{ statusText }}</span>
              </button>
            </template>
            <div class="health-pop">
              <div class="hp-row"><span>MySQL</span><i class="dot" :class="dotClass(health.db)"></i><b>{{ health.db }}</b></div>
              <div class="hp-row"><span>DuckDB</span><i class="dot" :class="dotClass(health.duckdb)"></i><b>{{ health.duckdb }}</b></div>
              <div class="hp-row"><span>大模型</span><i class="dot" :class="health.llm === 'configured' ? 'dot-ok' : 'dot-warn'"></i><b>{{ health.llm === 'configured' ? '已配置' : health.llm }}</b></div>
              <div class="hp-row"><span>上次检测</span><b>{{ ago(health.lastCheckAt) }}</b></div>
              <button class="ghost-btn hp-refresh" type="button" :disabled="health.checking" @click="refresh">
                {{ health.checking ? '检测中' : '重新检测' }}
              </button>
            </div>
          </el-popover>

          <span class="clock">{{ timeText }}</span>

          <!-- 用户区：头像 + 身份，点开才出现账号信息与退出 -->
          <el-popover placement="bottom-end" :width="222" trigger="click">
            <template #reference>
              <button class="user-btn" type="button" :title="identityText">
                <span class="user-avatar">{{ role === 'teacher' ? '教' : '学' }}</span>
                <span class="user-name">{{ identityText }}</span>
              </button>
            </template>
            <div class="user-pop">
              <p class="user-pop-name">{{ identityText }}</p>
              <p class="user-pop-role">{{ role === 'teacher' ? '教师账号' : '学生账号' }}</p>
              <button class="logout-btn" type="button" @click="logout">退出登录</button>
            </div>
          </el-popover>

          <button
            v-if="isMobile"
            class="icon-btn"
            type="button"
            aria-label="打开导航"
            @click="drawer = true"
          >
            <span class="hamburger" />
          </button>
        </div>
      </div>
    </header>

    <!-- 本页 AI 助手条：每个板块都有专属问法，点击即让智能体带着问题作答 -->
    <div v-if="aiChips.length" class="ai-strip">
      <div class="ai-strip-inner">
        <span class="ai-strip-label">
          <span class="ai-strip-dot">AI</span>本页可以直接问
        </span>
        <button
          v-for="c in aiChips"
          :key="c.q"
          class="ai-chip"
          type="button"
          :title="'让 AI 回答：' + c.q"
          @click="askAI(c.q)"
        >
          {{ c.q }}
        </button>
        <button class="ai-more" type="button" @click="askAI()">更多问题…</button>
      </div>
    </div>

    <main class="page-main">
      <div class="page-head">
        <h1 class="page-title">{{ currentLabel }}</h1>
        <p class="page-sub">{{ currentHint }}</p>
      </div>
      <router-view v-slot="{ Component }">
        <transition name="page-fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>

    <!-- 移动端导航抽屉：不保留常驻侧栏 -->
    <template v-if="isMobile">
      <div v-if="drawer" class="scrim" @click="drawer = false" />
      <aside class="nav-drawer" :class="{ 'is-open': drawer }" aria-label="主导航">
        <div class="drawer-brand">
          <span class="brand-mark">启</span>
          <div class="brand-text">
            <span class="brand-title">启航</span>
            <span class="brand-sub">生涯与岗位匹配</span>
          </div>
        </div>
        <nav class="drawer-nav">
          <router-link
            v-for="item in menus"
            :key="item.path"
            :to="item.path"
            class="drawer-item"
            :class="{ 'is-active': isActive(item.path) }"
            @click="drawer = false"
          >
            <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path :d="ICONS[item.icon]" />
            </svg>
            <span class="drawer-text">
              <span class="drawer-label">{{ item.label }}</span>
              <span class="drawer-hint">{{ item.hint }}</span>
            </span>
          </router-link>
        </nav>
        <div class="drawer-foot">
          <div class="user-card">
            <span class="user-avatar">{{ role === 'teacher' ? '教' : '学' }}</span>
            <div class="user-meta">
              <div class="user-name">{{ identityText }}</div>
              <div class="user-role">{{ role === 'teacher' ? '教师账号' : '学生账号' }}</div>
            </div>
            <button class="logout-btn" type="button" @click="logout">退出</button>
          </div>
        </div>
      </aside>
    </template>

    <!-- 悬浮助手：右下角「摸鱼」形象按钮 → 右侧抽屉 -->
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

    <ChatDrawer
      v-model="chatOpen"
      :seed-question="chatSeed"
      @seed-consumed="chatSeed = ''"
    />
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
  briefcase: 'M20 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2zM16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2M2 12h20',
  // 面试：麦克风（话筒头 + 支架）
  mic: 'M12 2a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v4M8 22h8',
  // 图谱：三节点连线
  graph: 'M5 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM19 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM12 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM7 17l3.5-2M17 9.5l-3.5 8M17.5 8 8 17',
  // 预测：折线上扬 + 箭头
  trend: 'M3 17l6-6 4 4 7-7M17 8h4M17 8v4',
  // 报考分析：靶心 + 箭，对应「按指标评估能打到哪」
  target: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z'
}

const MOBILE_QUERY = '(max-width: 1023px)'

const { health, refresh } = useSystemStatus()
const { timeText, ago } = useClock()
const router = useRouter()
const route = useRoute()
const role = currentRole()

// 智能助手是右下角悬浮入口（抽屉），不占导航位
const MENUS = {
  teacher: [
    { path: '/teacher', label: '班级总览', hint: '全班预警与概貌', icon: 'grid' },
    { path: '/teacher/students', label: '学生档案', hint: '全班 → 个人详情', icon: 'users' },
    { path: '/teacher/grades', label: '成绩单', hint: '按学年看全部成绩', icon: 'doc' },
    { path: '/teacher/jobs', label: '岗位库', hint: '企业岗位周更', icon: 'briefcase' },
    { path: '/teacher/exams', label: '招考信息', hint: '考公 / 考编 / 考研', icon: 'doc' },
    { path: '/teacher/approvals', label: '工作流审批', hint: '人工审核执行申请', icon: 'doc' },
    { path: '/teacher/kg', label: '知识图谱', hint: '专业-课程-岗位-技能', icon: 'graph' }
  ],
  student: [
    { path: '/student', label: '我的画像', hint: '预警 + 岗位推荐', icon: 'self' },
    { path: '/student/grades', label: '成绩单', hint: '每学年课程成绩', icon: 'doc' },
    { path: '/student/jobs', label: '岗位库', hint: '企业岗位搜索', icon: 'briefcase' },
    { path: '/student/exams', label: '招考信息', hint: '考公 / 考编 / 考研', icon: 'doc' },
    { path: '/student/career', label: '报考分析', hint: '按你的指标算竞争力', icon: 'target' },
    { path: '/student/interview', label: '模拟面试', hint: '简历诊断 + 多轮演练', icon: 'mic' },
    { path: '/student/kg', label: '知识图谱', hint: '专业-课程-岗位-技能', icon: 'graph' },
    { path: '/student/forecast', label: '学业预测', hint: '下学期成绩与风险', icon: 'trend' }
  ]
}

const menus = computed(() => MENUS[role] || MENUS.student)
const drawer = ref(false)
const chatOpen = ref(false)
const chatSeed = ref('')

// 每个板块的专属 AI 问法（与后端智能体真实能力一一对应，不是装饰）。
// askAI() 不带参数 = 只开抽屉，由用户自由提问。
const PAGE_AI = {
  'teacher-overview': [
    { q: 'AI2301 这学期整体情况怎么样', note: '班级概貌：人数、绩点、挂科率、意向分布' },
    { q: 'AI2301 班的预警名单有哪些人', note: '预警名单，可追问红色/橙色等级' }
  ],
  'teacher-students': [
    { q: '查一个学生的四维画像', note: '输入姓名即可看单个学生的画像与标签' },
    { q: 'AI2301 的预警阈值是多少', note: '当前班级的预警判定标准' }
  ],
  'teacher-grades': [
    { q: 'AI2301 上学期红色预警有哪些人', note: '按学期 + 等级过滤的预警名单' },
    { q: 'AI2301 全班的成绩排名怎么样', note: '班级与同专业名次，引擎按加权均分实算' }
  ],
  'teacher-jobs': [
    { q: 'AI2301 和岗位要求的差距在哪', note: '班级能力 vs 目标岗位的缺口分析' }
  ],
  'teacher-exams': [
    { q: '联网查一下最新的公开招聘信息', note: '联网搜索，带原文链接' },
    { q: '2027 国考职位表里有哪些计算机类岗位', note: '国家公务员局职位表逐职位明细，带官方链接' }
  ],
  'teacher-approvals': [
    { q: '帮我跑一遍班级周报', note: '工作流：多步流程一键执行，结果可送审' }
  ],
  'teacher-kg': [
    { q: '公司制度里报销的住宿标准是多少', note: '知识库检索，给文档名和页码' }
  ],
  'student-home': [
    { q: '我这学期的学业预警情况怎么样', note: '你的预警状态与原因' },
    { q: '有哪些岗位适合我？为什么？', note: '基于你的画像推荐岗位' }
  ],
  'student-grades': [
    { q: '我这学期有什么挂科风险', note: '按你的真实成绩实算' }
  ],
  'student-jobs': [
    { q: '有哪些岗位适合我？为什么？', note: '岗位推荐 + 推荐理由' }
  ],
  'student-interview': [
    { q: '帮我跑一遍求职体检', note: '工作流：简历→差距→演练一站式体检' }
  ],
  'student-exams': [
    { q: '联网查一下最新的公开招聘信息', note: '联网搜索招考公告，带原文链接' },
    { q: '2027 国考职位表里有哪些计算机类岗位', note: '职位表实抓，含学历与专业要求' }
  ],
  'student-kg': [
    { q: '公司制度里报销的住宿标准是多少', note: '知识库检索，给文档名和页码' }
  ],
  'student-forecast': [
    { q: '我这学期有什么挂科风险', note: '学业预警：按你的真实成绩实算' },
    { q: '根据我的成绩，我适合考公还是考研', note: '结合你的指标给方向建议' }
  ],
  'student-career': [
    { q: '考公、考编、考研分别要准备多少学时', note: '投入维度怎么算，一句话讲清' }
  ]
}

const aiChips = computed(() => PAGE_AI[route.name] || [])

function askAI(question) {
  chatSeed.value = String(question || '').trim()
  chatOpen.value = true
}

const isMobile = ref(false)
const scrolled = ref(false)
let media = null

// 取「最长匹配」而非「第一个匹配」：否则 /teacher/exams 会被 /teacher 抢先命中，
// 页头就永远停在「班级总览」。
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
  if (route.path === path) return true
  if (!route.path.startsWith(`${path}/`)) return false
  // 前缀命中还要让位：若存在更长的菜单也命中当前路径（如 /teacher/students 同时
  // 命中 /teacher 与 /teacher/students），只有最长者亮——与 currentItem 同口径
  return !menus.value.some(
    (item) =>
      item.path !== path &&
      item.path.length > path.length &&
      (route.path === item.path || route.path.startsWith(`${item.path}/`))
  )
}

function syncViewport(event) {
  isMobile.value = event.matches
  if (!event.matches) drawer.value = false
}

function onScroll() {
  scrolled.value = window.scrollY > 4
}

const identityText = computed(() => {
  if (role === 'teacher') {
    const tenant = localStorage.getItem('qh_tenant_id')
    return tenant ? `教师 ${tenant} 校` : '教师'
  }
  return localStorage.getItem('qh_student_no') || '学生'
})

const statusText = computed(() => {
  const map = { ok: '服务正常', degraded: '部分降级', down: '服务不可达', checking: '检测中' }
  return map[health.status] || health.status
})

function dotClass(state) {
  if (state === 'ok') return 'dot-ok'
  if (state === 'down') return 'dot-bad'
  return 'dot-warn'
}

// 整体状态 = 最差的那个组件：全 ok 才亮绿灯，其余情况点开看是哪一项出问题
const overallDot = computed(() => {
  const states = [health.db, health.duckdb, health.llm === 'configured' ? 'ok' : 'warn']
  if (states.every((s) => s === 'ok')) return 'dot-ok'
  if (states.some((s) => s === 'down')) return 'dot-bad'
  return 'dot-warn'
})

function logout() {
  clearSession()
  router.push('/login')
}

onMounted(() => {
  media = window.matchMedia(MOBILE_QUERY)
  isMobile.value = media.matches
  media.addEventListener('change', syncViewport)
  window.addEventListener('scroll', onScroll, { passive: true })
  onScroll()
})

onBeforeUnmount(() => {
  media?.removeEventListener('change', syncViewport)
  window.removeEventListener('scroll', onScroll)
})
</script>

<style scoped>
.shell {
  min-height: 100vh;
  background: transparent;
}

/* ---------- 顶栏：64px，白底 82% + 毛玻璃 ---------- */
.topnav {
  position: sticky;
  top: 0;
  z-index: 40;
  height: 64px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: saturate(180%) blur(14px);
  -webkit-backdrop-filter: saturate(180%) blur(14px);
  border-bottom: 1px solid #eceef7;
  transition: box-shadow 200ms ease, border-color 200ms ease;
}

.topnav.is-scrolled {
  box-shadow: 0 6px 20px rgba(33, 40, 90, 0.06);
  border-bottom-color: #e6e9f5;
}

.topnav-inner {
  height: 100%;
  /* 与 .page-main 同一容器宽度：左右留白 = max(24, (视口-1680)/2)；≥1800px 见文末媒体查询 */
  width: min(1680px, calc(100% - 48px));
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  align-items: center;
  gap: 18px;
}

/* 品牌：紫蓝渐变方块 + 两行字 */
.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
  text-decoration: none;
}

.brand-mark {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  border-radius: 10px;
  background:
    radial-gradient(120% 120% at 25% 10%, rgba(255, 255, 255, 0.45), transparent 45%),
    linear-gradient(135deg, #6366f1 0%, #5b5bd6 55%, #7c3aed 100%);
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 6px 14px rgba(99, 102, 241, 0.28);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
  min-width: 0;
}

.brand-title {
  font-size: 14.5px;
  font-weight: 650;
  letter-spacing: -0.01em;
  color: #171a2b;
  white-space: nowrap;
}

.brand-sub {
  font-size: 11px;
  color: #9297ab;
  white-space: nowrap;
}

/* 导航 pill：横向排列，不换行；极窄时自身横向滚动（无滚动条） */
.nav {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 1 1 auto;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.nav::-webkit-scrollbar {
  display: none;
}

.nav-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 999px;
  font-size: 13.5px;
  font-weight: 500;
  color: #5b6178;
  text-decoration: none;
  white-space: nowrap;
  transition: background-color 150ms ease, color 150ms ease;
}

.nav-pill:hover {
  background: #f4f4fb;
  color: #4a4ac0;
}

.nav-pill.is-active {
  background: #efedff;
  color: #4f46e5;
  font-weight: 600;
}

.nav-icon {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0.85;
}

.nav-pill.is-active .nav-icon {
  opacity: 1;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
  margin-left: auto;
}

.status-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border: 1px solid #eceef7;
  border-radius: 999px;
  background: #fff;
  color: #5b6178;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.status-btn:hover {
  background: #f1efff;
  color: #4a4ac0;
}

.clock {
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: #9297ab;
  white-space: nowrap;
}

.user-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 3px 10px 3px 3px;
  border: 1px solid #eceef7;
  border-radius: 999px;
  background: #fff;
  font-family: inherit;
  font-size: 12.5px;
  color: #171a2b;
  cursor: pointer;
  transition: background-color 150ms ease, border-color 150ms ease;
}

.user-btn:hover {
  background: #f7f7fd;
  border-color: #e0e3f2;
}

.user-avatar {
  width: 26px;
  height: 26px;
  flex: 0 0 26px;
  border-radius: 8px;
  background: linear-gradient(135deg, #eef0ff, #f3e8ff);
  color: #4f46e5;
  font-size: 11.5px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.user-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-pop {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-pop-name {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #171a2b;
}

.user-pop-role {
  margin: 0 0 8px;
  font-size: 12px;
  color: #9297ab;
}

.logout-btn {
  border: 0;
  border-radius: 8px;
  padding: 6px 10px;
  background: #f4f3ff;
  color: #5b5bd6;
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.logout-btn:hover {
  background: #fee2e2;
  color: #b91c1c;
}

.icon-btn {
  width: 34px;
  height: 34px;
  border: 1px solid #eceef7;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 150ms ease;
}

.icon-btn:hover {
  background: #f1efff;
}

.hamburger,
.hamburger::before,
.hamburger::after {
  display: block;
  width: 16px;
  height: 1.5px;
  background: #5b6178;
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

.health-pop {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
  color: #5b6178;
}

.hp-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hp-row span {
  width: 60px;
  color: #9297ab;
}

.hp-row b {
  color: #171a2b;
  font-weight: 500;
  margin-left: auto;
}

.hp-refresh {
  margin-top: 2px;
  align-self: flex-end;
}

.ghost-btn {
  border: 1px solid #eceef7;
  border-radius: 999px;
  background: #fff;
  color: #5b6178;
  font-size: 12px;
  font-family: inherit;
  padding: 5px 12px;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.ghost-btn:hover:not(:disabled) {
  background: #f1efff;
  color: #4a4ac0;
}

.ghost-btn:disabled {
  opacity: 0.6;
  cursor: default;
}

/* ---------- 本页 AI 助手条：全宽浅紫渐变底，内容与页面同宽 ---------- */
.ai-strip {
  background: linear-gradient(90deg, rgba(99, 102, 241, 0.09), rgba(124, 58, 237, 0.05) 55%, rgba(255, 255, 255, 0));
  border-bottom: 1px solid rgba(99, 102, 241, 0.12);
}

.ai-strip-inner {
  /* 与 .page-main 同宽同偏移，再各留 24px —— 这样 AI 问法条第一枚 chip、
     页面标题、第一张卡片的左边缘落在同一条竖线上。
     不用 100vw 参与计算：竖向滚动条会让 100vw 比 clientWidth 多 ~15px，
     1920 下会偏 7~8px。 */
  width: min(1680px, calc(100% - 48px));
  margin: 0 auto;
  padding: 9px 24px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.ai-strip-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 650;
  color: #4f46e5;
  white-space: nowrap;
}

.ai-strip-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 6px;
  background: linear-gradient(135deg, #6366f1, #0ea5e9);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.ai-chip {
  border: 1px solid rgba(99, 102, 241, 0.24);
  background: rgba(255, 255, 255, 0.86);
  color: #4338ca;
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
  box-shadow: 0 1px 3px rgba(79, 70, 229, 0.06);
}

.ai-chip:hover {
  background: #5b5bd6;
  border-color: #5b5bd6;
  color: #fff;
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(91, 91, 214, 0.24);
}

.ai-more {
  border: none;
  background: none;
  color: #6366f1;
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  padding: 4px 6px;
  white-space: nowrap;
}

.ai-more:hover {
  text-decoration: underline;
}

/* ---------- 内容区：与顶栏同容器（1680px 封顶，≥1800px 再放宽），页面自带 24px 内边距 ---------- */
.page-main {
  width: min(1680px, calc(100% - 48px));
  margin: 0 auto;
  padding: 0;
}

.page-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 18px 24px 0;
  min-width: 0;
}

.page-title {
  margin: 0;
  font-size: 17px;
  font-weight: 650;
  letter-spacing: -0.02em;
  color: #171a2b;
  white-space: nowrap;
}

.page-sub {
  margin: 0;
  font-size: 12px;
  color: #9297ab;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 8px;
  display: inline-block;
  background: #d4d4d8;
  flex: 0 0 7px;
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

/* ---------- 移动端导航抽屉 ---------- */
.scrim {
  position: fixed;
  inset: 0;
  z-index: 44;
  background: rgba(24, 24, 27, 0.42);
}

.nav-drawer {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 45;
  width: 268px;
  max-width: 84vw;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-right: 1px solid #eceef7;
  box-shadow: 0 12px 40px rgba(24, 24, 27, 0.16);
  transform: translateX(-100%);
  transition: transform 200ms cubic-bezier(0.22, 0.61, 0.36, 1);
}

.nav-drawer.is-open {
  transform: translateX(0);
}

.drawer-brand {
  height: 60px;
  flex: 0 0 60px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  border-bottom: 1px solid #eceef7;
}

.drawer-nav {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 10px 8px;
}

.drawer-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 11px;
  margin: 2px 0;
  border-radius: 10px;
  color: #5b6178;
  text-decoration: none;
  transition: background-color 150ms ease, color 150ms ease;
}

.drawer-item:hover {
  background: #f4f4fb;
  color: #4a4ac0;
}

.drawer-item.is-active {
  background: #efedff;
  color: #4f46e5;
  font-weight: 600;
}

.drawer-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.drawer-label {
  font-size: 14px;
  line-height: 1.35;
}

.drawer-hint {
  font-size: 11px;
  color: #9297ab;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.drawer-item.is-active .drawer-hint {
  color: #818cf8;
}

.drawer-foot {
  flex: 0 0 auto;
  border-top: 1px solid #eceef7;
  padding: 10px;
}

.user-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  background: #fff;
  border: 1px solid #eceef7;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(33, 40, 90, 0.04);
}

.user-meta {
  min-width: 0;
  flex: 1 1 auto;
}

.user-role {
  font-size: 11px;
  color: #9297ab;
}

/* ---------- 悬浮 AI 助手入口（右下角小人） ---------- */
.assistant-fab {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 43;
  width: 92px;
  height: 92px;
  padding: 0;
  border: 0;
  border-radius: 22px;
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
  top: 2px;
  right: 2px;
  padding: 1px 6px;
  border-radius: 8px;
  background: linear-gradient(135deg, #6366f1, #7c3aed);
  color: #fff;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid #fff;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.3);
}

/* 抽屉本体：抹掉默认内边距，交给 ChatDrawer 自己排布 */
.chat-drawer :deep(.el-drawer__body) {
  padding: 0;
}

/* ---------- 宽屏放宽容器：2200/2560 下左右不再空一大片。
   三处必须同步放宽（顶栏 / AI 问法条 / 内容区），否则三者左缘会错开。
   不用 100vw 参与计算：竖向滚动条会让 100vw 比 clientWidth 宽约 15px。 ---------- */
@media (min-width: 1800px) {
  .topnav-inner,
  .ai-strip-inner,
  .page-main {
    width: min(1920px, calc(100% - 64px));
  }
}

/* ---------- 1180px 以下：顶栏收窄，先砍次要信息保「不换行」 ---------- */
@media (max-width: 1180px) {
  .topnav-inner {
    gap: 12px;
    padding: 0 24px;
  }

  .brand-sub,
  .clock,
  .status-text,
  .user-name {
    display: none;
  }

  .status-btn {
    padding: 5px 8px;
  }

  .user-btn {
    padding: 3px;
  }

  .nav-pill {
    padding: 7px 10px;
    font-size: 13px;
  }
}

@media (max-width: 1023px) {
  .topnav {
    height: 56px;
  }

  .topnav-inner {
    height: 56px;
    width: 100%;
    padding: 0 16px;
    gap: 10px;
  }

  /* 手机上不再留 24px 容器内缩，交给页面自身的 16px 内边距 */
  .page-main {
    width: 100%;
  }

  /* 手机上 AI 问法条横向滑动，不折行占高 */
  .ai-strip-inner {
    width: 100%;
    flex-wrap: nowrap;
    overflow-x: auto;
    scrollbar-width: none;
    padding: 8px 16px;
  }

  .ai-strip-inner::-webkit-scrollbar {
    display: none;
  }

  .ai-strip-label span:last-child {
    display: none;
  }

  .page-head {
    flex-direction: column;
    gap: 1px;
    padding: 12px 16px 0;
  }

  .page-title {
    font-size: 16px;
  }

  .assistant-fab {
    right: 12px;
    bottom: 12px;
    width: 72px;
    height: 72px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .nav-pill,
  .ai-chip,
  .assistant-fab,
  .nav-drawer,
  .topnav {
    transition: none;
  }
}
</style>
