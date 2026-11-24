<template>
  <div class="shell">
    <!-- ============ 左侧竖排侧边栏：品牌 + 主导航 + 本页 AI 问法 ============ -->
    <aside v-if="!isMobile" class="sidebar" aria-label="主导航">
      <router-link class="brand" to="/" aria-label="启航首页">
        <span class="brand-mark">启</span>
        <span class="brand-text">
          <span class="brand-title">启航</span>
          <span class="brand-sub">重庆财经学院</span>
        </span>
      </router-link>

      <nav ref="sideNav" class="side-nav">
        <span
          class="side-indicator"
          :class="{ 'is-on': indicatorOn }"
          :style="{ transform: `translateY(${indicatorY}px)` }"
          aria-hidden="true"
        />
        <router-link
          v-for="item in menus"
          :key="item.path"
          :to="item.path"
          class="side-item"
          :class="{ 'is-active': isActive(item.path) }"
          :title="item.hint"
        >
          <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path :d="ICONS[item.icon]" />
          </svg>
          <span class="side-label">{{ item.label }}</span>
        </router-link>
      </nav>

      <!-- 本页 AI 问法：跟着导航往下排，窄屏随侧栏一起收进抽屉 -->
      <div v-if="aiChips.length" class="side-ai">
        <p class="ai-rail-label">
          <span class="ai-rail-dot">AI</span>
          <span class="ai-rail-label-text">本页可以直接问</span>
        </p>
        <button
          v-for="c in aiChips"
          :key="c.q"
          class="ai-rail-item"
          type="button"
          :title="'让 AI 回答：' + c.q"
          @click="askAI(c.q)"
        >
          {{ c.q }}
        </button>
        <button class="ai-rail-more" type="button" @click="askAI()">更多问题…</button>
      </div>
    </aside>

    <!-- ============ 右侧主区：顶栏只留状态与账号，内容在其下 ============ -->
    <div class="shell-main">
      <header class="topbar" :class="{ 'is-scrolled': scrolled }">
        <div class="topbar-inner">
          <router-link v-if="isMobile" class="brand brand-compact" to="/" aria-label="启航首页">
            <span class="brand-mark">启</span>
            <span class="brand-title">启航</span>
          </router-link>

          <!-- 页面标题：原先在正文顶部，挪进顶栏后正文直接从内容开始。
               顶栏是 sticky 的，滚动时标题一直可见，反而比原来更好定位。 -->
          <div v-else class="topbar-title">
            <h1 class="topbar-title-main">{{ currentLabel }}</h1>
            <p class="topbar-title-sub">{{ currentHint }}</p>
          </div>

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
            ref="menuBtn"
            class="icon-btn"
            type="button"
            aria-label="打开导航"
            aria-controls="mobile-nav"
            :aria-expanded="drawer ? 'true' : 'false'"
            @click="drawer = true"
          >
            <span class="hamburger" />
          </button>
          </div>
        </div>
      </header>

      <main class="page-main" :inert="isMobile && drawer ? '' : null">
        <!-- 桌面端标题已上移到顶栏；移动端顶栏塞不下，仍放在正文顶部 -->
        <div v-if="isMobile" class="page-head">
          <h1 class="page-title">{{ currentLabel }}</h1>
          <p class="page-sub">{{ currentHint }}</p>
        </div>
        <router-view v-slot="{ Component }">
          <Transition name="qh-page" mode="out-in">
            <component :is="Component" />
          </Transition>
        </router-view>
      </main>
    </div>

    <!-- 移动端导航抽屉：不保留常驻侧栏 -->
    <template v-if="isMobile">
      <div v-if="drawer" class="scrim" @click="drawer = false" />
      <aside
        id="mobile-nav"
        ref="drawerEl"
        class="nav-drawer"
        :class="{ 'is-open': drawer }"
        role="dialog"
        aria-modal="true"
        aria-label="主导航"
        :inert="drawer ? null : ''"
      >
        <div class="drawer-brand">
          <span class="brand-mark">启</span>
          <div class="brand-text">
            <span class="brand-title">启航</span>
            <span class="brand-sub">重庆财经学院</span>
          </div>
          <button
            class="drawer-close"
            type="button"
            aria-label="关闭导航"
            @click="drawer = false"
          >
            ×
          </button>
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

        <!-- 桌面端侧栏里的 AI 问法，移到抽屉里，别让窄屏丢掉这个入口 -->
        <div v-if="aiChips.length" class="drawer-ai">
          <p class="drawer-ai-label">
            <span class="ai-rail-dot">AI</span>本页可以直接问
          </p>
          <button
            v-for="c in aiChips"
            :key="c.q"
            class="ai-rail-item"
            type="button"
            @click="askAI(c.q); drawer = false"
          >
            {{ c.q }}
          </button>
        </div>

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

    <!-- 右下角的入口已经交给全局宠物（鲸鱼娘）：点它即拉起这里的抽屉，
         不再单独放一个悬浮按钮，避免两个入口在同一角落互相压住 -->
    <ChatDrawer
      v-model="chatOpen"
      :seed-question="chatSeed"
      @seed-consumed="chatSeed = ''"
    />
    <NotificationCenter v-if="role === 'student'" />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { clearSession, currentRole } from '../api/http'
import ChatDrawer from '../components/ChatDrawer.vue'
import NotificationCenter from '../components/notifications/NotificationCenter.vue'
import { useAssistant } from '../composables/useAssistant'
import { useClock, useSystemStatus } from '../composables/useSystemStatus'

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
  // 校园洞察：行为脉搏（心电波形），对应到馆/消费/考勤等行为信号
  pulse: 'M22 12h-4l-3 9L9 3l-3 9H2',
  // 报考分析：靶心 + 箭，对应「按指标评估能打到哪」
  target: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
  // 职业测评：剪贴板（板夹 + 纸 + 勾）
  clipboard: 'M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2M9 14l2 2 4-4',
  // 联网搜索：放大镜 + 地球经纬，对应「跳出本地库去查外部网页」
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35M11 3a8 8 0 0 1 0 16M3 11h16M11 3c2.5 2 2.5 14 0 16M11 3c-2.5 2-2.5 14 0 16'
}

const MOBILE_QUERY = '(max-width: 1023px)'

const { health, refresh } = useSystemStatus()
const { timeText, ago } = useClock()
const router = useRouter()
const route = useRoute()
const role = currentRole()

// 智能助手是右下角悬浮入口（抽屉），不占导航位
const MENUS = {
  // 11 → 8：学生总览 / 档案 / 成绩合并成「学生」，岗位库 / 招考合并成「机会库」。
  // 侧栏做减法比做加法难——每多一项，演示时被点开的概率就被摊薄一点。
  teacher: [
    { path: '/teacher', label: '学生', hint: '班级总览 · 学生档案 · 全班成绩', icon: 'users' },
    { path: '/teacher/assistant', label: 'AI 助手', hint: '联网搜索 + 深度思考', icon: 'chat' },
    { path: '/teacher/agent-quality', label: '智能体质量', hint: '回查 / 降级 / 能力自检', icon: 'trend' },
    { path: '/teacher/career', label: '生涯规划', hint: '十域数据全景档案', icon: 'target' },
    { path: '/teacher/campus', label: '校园洞察', hint: '图书馆 / 消费 / 考勤 / 活动', icon: 'pulse' },
    { path: '/teacher/opportunity', label: '机会库', hint: '企业岗位 + 招考公告', icon: 'briefcase' },
    { path: '/teacher/approvals', label: '工作流审批', hint: '人工审核执行申请', icon: 'doc' },
    { path: '/teacher/kg', label: '知识图谱', hint: '专业-课程-岗位-技能', icon: 'graph' },
    { path: '/teacher/innovation', label: '创新全景', hint: '证据链 · 数据溯源 · 师生闭环', icon: 'grid' }
  ],
  student: [
    { path: '/student', label: '我的画像', hint: '预警 + 岗位推荐', icon: 'self' },
    { path: '/student/assistant', label: 'AI 助手', hint: '联网搜索 + 深度思考', icon: 'chat' },
    { path: '/student/academic', label: '学业', hint: '成绩明细 · 学业预测 · 选课建议', icon: 'doc' },
    { path: '/student/opportunity', label: '机会库', hint: '企业岗位 + 招考公告', icon: 'briefcase' },
    { path: '/student/plan', label: '生涯规划', hint: '报考分析 + 职业测评', icon: 'target' },
    { path: '/student/interview', label: '模拟面试', hint: '实战演练 + 复盘实验室', icon: 'mic' },
    { path: '/student/kg', label: '知识图谱', hint: '专业-课程-岗位-技能', icon: 'graph' },
    { path: '/student/campus', label: '校园洞察', hint: '校园行为五域洞察', icon: 'pulse' },
    { path: '/student/innovation', label: '创新全景', hint: '证据链 · 数据溯源 · 师生闭环', icon: 'grid' }
  ]
}

const menus = computed(() => MENUS[role] || MENUS.student)
const drawer = ref(false)
const menuBtn = ref(null)
const drawerEl = ref(null)
// 抽屉开关与宠物共用同一份状态：宠物点开后，这里的抽屉会立即响应
const { open: chatOpen, seed: chatSeed, ask } = useAssistant()

// 每个板块的专属 AI 问法（与后端智能体真实能力一一对应，不是装饰）。
// askAI() 不带参数 = 只开抽屉，由用户自由提问。
const PAGE_AI = {
  'teacher-students-hub': [
    { q: 'AI2301 这学期整体情况怎么样', note: '班级概貌：人数、绩点、挂科率、意向分布' },
    { q: 'AI2301 班的预警名单有哪些人', note: '预警名单，可追问红色 / 橙色等级' },
    { q: '查一个学生的四维画像', note: '输入姓名即可看单个学生的画像与标签' }
  ],
  'teacher-career': [
    { q: '按班级查看全班的生涯规划档案', note: '十域数据全景：成绩/预警/预测/岗位/面试/竞赛/测评/选课/招考/图谱' },
    { q: 'AI2301 就业方向的学生有哪些，岗位匹配如何', note: '按方向过滤学生档案并看岗位匹配前列' }
  ],
  'teacher-campus': [
    { q: 'AI2301 哪些学生校园投入偏低，原因是什么', note: '低投入名单：出勤 / 到馆 / 消费规律触发项' },
    { q: 'AI2301 的图书馆到馆和考勤整体情况怎么样', note: '班级五域行为聚合，数值由引擎实算' }
  ],
  'teacher-opportunity': [
    { q: 'AI2301 和岗位要求的差距在哪', note: '班级能力 vs 目标岗位的缺口分析' },
    { q: '联网查一下最新的公开招聘信息', note: '联网搜索招考公告，带原文链接' }
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
  'student-academic': [
    { q: '我这学期有什么挂科风险', note: '按你的真实成绩实算' },
    { q: '我选什么课能补技能缺口', note: '引擎算缺口，选课规划智能体给个性化方案' }
  ],
  'student-opportunity': [
    { q: '有哪些岗位适合我？为什么？', note: '岗位推荐 + 推荐理由' },
    { q: '2027 国考职位表里有哪些计算机类岗位', note: '职位表实抓，含学历与专业要求' }
  ],
  'student-plan': [
    { q: '根据我的成绩，我适合考公还是考研', note: '结合你的指标给方向建议' },
    { q: '考公、考编、考研分别要准备多少学时', note: '投入维度怎么算，一句话讲清' }
  ],
  'student-interview': [
    { q: '帮我跑一遍求职体检', note: '工作流：简历→差距→演练一站式体检' }
  ],
  'student-kg': [
    { q: '公司制度里报销的住宿标准是多少', note: '知识库检索，给文档名和页码' }
  ],
  'student-campus': [
    { q: '我的学习投入分是怎么算出来的', note: '到馆 40% + 出勤 30% + 消费规律 30%，引擎实算' },
    { q: '我这学期的到馆和出勤情况怎么样', note: '图书馆 / 考勤按学期序列展示' }
  ]
}

const aiChips = computed(() => PAGE_AI[route.name] || [])

function askAI(question) {
  ask(question)
}

const isMobile = ref(false)
const scrolled = ref(false)
let media = null

// 侧栏 active 指示条：只测量位置、用 transform 滑动，不参与菜单/路由逻辑
const sideNav = ref(null)
const indicatorY = ref(0)
const indicatorOn = ref(false)

function syncIndicator() {
  const nav = sideNav.value
  const active = nav?.querySelector('.side-item.is-active')
  if (!active) {
    indicatorOn.value = false
    return
  }
  indicatorY.value = active.offsetTop + active.offsetHeight / 2 - 12
  indicatorOn.value = true
}

watch(
  () => route.path,
  async () => {
    await nextTick()
    syncIndicator()
  }
)

watch(isMobile, async (mobile) => {
  if (!mobile) {
    await nextTick()
    syncIndicator()
  }
})

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

function onKeydown(event) {
  if (event.key === 'Escape' && drawer.value) drawer.value = false
}

// 移动端抽屉打开时锁住页面滚动，并把焦点移进抽屉；关闭后把焦点还给汉堡按钮
watch(drawer, async (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
  // 宠物与控制条也是 fixed 层，抽屉打开时让位，避免压住菜单和底部用户卡
  document.body.classList.toggle('nav-open', open)
  await nextTick()
  if (open) {
    drawerEl.value?.querySelector('.drawer-item')?.focus()
  } else if (isMobile.value) {
    menuBtn.value?.focus?.()
  }
})

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
  window.addEventListener('keydown', onKeydown)
  onScroll()
  nextTick(syncIndicator)
})

onBeforeUnmount(() => {
  media?.removeEventListener('change', syncViewport)
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
  document.body.classList.remove('nav-open')
})
</script>

<style scoped>
.shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 236px minmax(0, 1fr);
  align-items: start;
  background: transparent;
}

/* ---------- 左侧栏：品牌 + 导航 + 本页问法，整列吸顶 ----------
   深藏青实底（参考 xsc dashboard 的 #161c2b 侧栏），不再用毛玻璃白 */
.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 16px 14px;
  background: #161c2b;
  border-right: 1px solid #07070d;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.16) transparent;
}

.side-nav {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 14px;
}

/* active 指示条：固定高度，只靠 translateY 在菜单间平滑滑动 */
.side-indicator {
  position: absolute;
  left: -8px;
  top: 0;
  width: 3px;
  height: 24px;
  border-radius: 999px;
  background: #bfdbfe;
  opacity: 0;
  transition:
    transform 300ms cubic-bezier(0.16, 1, 0.3, 1),
    opacity 200ms ease;
  pointer-events: none;
}

.side-indicator.is-on {
  opacity: 1;
}

.side-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13.5px;
  font-weight: 500;
  color: #969eaf;
  text-decoration: none;
  white-space: nowrap;
  transition: background-color 140ms ease, color 140ms ease;
}

.side-item:hover {
  background: #1951c3;
  color: #fff;
}

/* 选中态对齐参考站：深蓝实底 + 右缘 3px 浅蓝指示条（inset 阴影实现，不挤压布局） */
.side-item.is-active {
  background: #1951c3;
  color: #fff;
  font-weight: 600;
  box-shadow: inset -3px 0 0 0 #a3beff;
}

/* ---------- 右侧主区 + 顶栏：只留状态与账号 ---------- */
.shell-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 100vh;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  flex: 0 0 56px;
  height: 56px;
  background: rgba(247, 248, 250, 0.86);
  backdrop-filter: saturate(180%) blur(16px);
  -webkit-backdrop-filter: saturate(180%) blur(16px);
  border-bottom: 1px solid var(--cf-line);
  transition: box-shadow 200ms ease;
}

.topbar.is-scrolled {
  background: rgba(248, 250, 252, 0.72);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom-color: rgba(148, 163, 184, 0.35);
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.08);
}

.topbar-inner {
  height: 100%;
  /* 和 .page-main 用同一套容器算式 + 同样的 24px 内边距，
     标题文字与正文卡片才会落在同一条竖线上 */
  width: min(1680px, calc(100% - 48px));
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 顶栏里的页面标题：沿用原 .page-head 的排版（标题与副标题按基线对齐） */
.topbar-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

/* 页标题是这一屏的最大标题，必须压过卡片标题（20px 的 .bento-title 除外，
   它只出现在卡片内做区块名）。原来 15px 比卡片标题还小，层级是反的；
   17px 在 1680px 宽画布上仍偏小，抬到 19px 并加重到 680。 */
.topbar-title-main {
  margin: 0;
  font-size: 19px;
  font-weight: 680;
  letter-spacing: -0.02em;
  color: var(--cf-ink);
  white-space: nowrap;
}

.topbar-title-sub {
  margin: 0;
  padding-left: 2px;
  font-size: 12.5px;
  color: var(--cf-faint);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
  position: relative;
  overflow: hidden;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  border-radius: 10px;
  /* 品牌标：靛蓝→青的斜向渐变，右上角一点高光，胜过纯黑方块 */
  background: linear-gradient(145deg, #3b6ee5 0%, #1951c3 52%, #0f9d8a 120%);
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow:
    0 6px 16px rgba(25, 81, 195, 0.32),
    inset 0 1px 0 rgba(255, 255, 255, 0.42);
}

/* 品牌标扫光：8 秒一次，很慢，只作为入口处的“活气” */
.brand-mark::after {
  content: '';
  position: absolute;
  top: -60%;
  bottom: -60%;
  left: -140%;
  width: 120%;
  background: linear-gradient(105deg, transparent 40%, rgba(255, 255, 255, 0.55) 50%, transparent 60%);
  transform: rotate(8deg);
  animation: brand-shine 8s ease-in-out infinite;
  pointer-events: none;
}

@keyframes brand-shine {
  0%, 74% { left: -140%; }
  88%, 100% { left: 140%; }
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
  color: var(--cf-ink);
  white-space: nowrap;
}

/* 白字只属于深底（桌面侧栏 / 移动抽屉）；浅色顶栏里的品牌保持墨色 */
.sidebar .brand-title,
.nav-drawer .brand-title {
  color: #fff;
}

.brand-sub {
  font-size: 11px;
  color: var(--cf-faint);
  white-space: nowrap;
}

.sidebar .brand-sub,
.nav-drawer .brand-sub {
  color: #969eaf;
}

/* 导航图标：横向 pill 和竖排侧栏共用，尺寸一致 */
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

.side-item.is-active .nav-icon {
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
  border: 1px solid var(--cf-line);
  border-radius: 999px;
  background: var(--cf-surface-solid);
  color: var(--cf-mid);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.status-btn:hover {
  background: var(--cf-coral-soft);
  color: var(--cf-coral);
}

.clock {
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--cf-faint);
  white-space: nowrap;
}

.user-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 3px 10px 3px 3px;
  border: 1px solid var(--cf-line);
  border-radius: 999px;
  background: var(--cf-surface-solid);
  font-family: inherit;
  font-size: 12.5px;
  color: var(--cf-ink);
  cursor: pointer;
  transition: background-color 150ms ease, border-color 150ms ease;
}

.user-btn:hover {
  background: #f7f7fd;
  border-color: var(--cf-line-strong);
}

.user-avatar {
  width: 26px;
  height: 26px;
  flex: 0 0 26px;
  border-radius: 8px;
  /* 淡蓝底 + Apple 蓝字，替代原来的紫渐变 */
  background: var(--cf-coral-soft);
  color: var(--cf-coral);
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
  color: var(--cf-ink);
}

.user-pop-role {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--cf-faint);
}

.logout-btn {
  border: 0;
  border-radius: 8px;
  padding: 6px 10px;
  background: var(--cf-coral-soft);
  color: var(--cf-coral);
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 300ms var(--qh-ease, ease), color 300ms var(--qh-ease, ease);
}

.logout-btn:hover {
  background: var(--cf-coral-soft);
  color: var(--cf-danger);
}

.icon-btn {
  width: 34px;
  height: 34px;
  border: 1px solid var(--cf-line);
  border-radius: 10px;
  background: var(--cf-surface-solid);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 150ms ease;
}

.icon-btn:hover {
  background: var(--cf-coral-soft);
}

.hamburger,
.hamburger::before,
.hamburger::after {
  display: block;
  width: 16px;
  height: 1.5px;
  background: var(--cf-mid);
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
  color: var(--cf-mid);
}

.hp-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hp-row span {
  width: 60px;
  color: var(--cf-faint);
}

.hp-row b {
  color: var(--cf-ink);
  font-weight: 500;
  margin-left: auto;
}

.hp-refresh {
  margin-top: 2px;
  align-self: flex-end;
}

.ghost-btn {
  border: 1px solid var(--cf-line);
  border-radius: 999px;
  background: var(--cf-surface-solid);
  color: var(--cf-mid);
  font-size: 12px;
  font-family: inherit;
  padding: 5px 12px;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.ghost-btn:hover:not(:disabled) {
  background: var(--cf-coral-soft);
  color: var(--cf-coral);
}

.ghost-btn:disabled {
  opacity: 0.6;
  cursor: default;
}

/* ---------- 侧栏里的本页问法：跟在导航下方，分隔线与导航拉开层次 ---------- */
.side-ai {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  min-width: 0;
  /* 不能压到底：侧栏底部是宠物立绘的固定位置，问法压下去会被整个盖住。
     菜单减到 8 项后下方留白是正常的，宁可空着也不要藏起来。 */
  margin-top: 16px;
  padding: 14px 12px 4px;
  border-top: 1px solid #272d3c;
}

.ai-rail-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 2px;
  font-size: 12.5px;
  font-weight: 650;
  color: #a3beff;
  white-space: nowrap;
}

.ai-rail-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 6px;
  background: linear-gradient(140deg, #3b6ee5, #1951c3 60%, #0f9d8a 130%);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  box-shadow: 0 3px 8px rgba(25, 81, 195, 0.3);
}

.ai-rail-item {
  border: 1px solid #272d3c;
  background: rgba(255, 255, 255, 0.06);
  color: #c8d3e8;
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 12.5px;
  font-family: inherit;
  line-height: 1.5;
  /* 横排时是 nowrap 的胶囊；改成竖栏后必须允许折行，
     否则长问法会把侧栏撑宽、把正文挤窄。 */
  text-align: left;
  white-space: normal;
  word-break: break-word;
  cursor: pointer;
  transition:
    background-color 200ms var(--qh-ease, ease),
    border-color 200ms var(--qh-ease, ease),
    color 200ms var(--qh-ease, ease),
    box-shadow 200ms var(--qh-ease, ease);
  box-shadow: none;
}

.ai-rail-item:hover {
  background: #1951c3;
  border-color: transparent;
  color: #fff;
}

.ai-rail-more {
  align-self: flex-start;
  border: none;
  background: none;
  color: #a3beff;
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  padding: 4px 2px;
  white-space: nowrap;
}

.ai-rail-more:hover {
  text-decoration: underline;
}

/* ---------- 内容区：在右侧主区里再居中一层（1680px 封顶） ----------
   上下左右的呼吸统一交给 .bento-page 的 24px（手机 16px），这里不再额外加顶部
   padding，否则「顶栏→首卡」是 44px、左右只有 24px，首屏会显得头轻脚重。 */
.page-main {
  width: min(1680px, calc(100% - 48px));
  min-width: 0;
  margin: 0 auto;
  padding: 0;
}

/* 少数没有 .bento-page 包裹的页面（如 404）自己补回同一套内距；
   排除移动端专用的 .page-head，它的内距由 1023px 断点自己管 */
.page-main > :not(.bento-page):not(.page-head) {
  padding: 24px;
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
  color: var(--cf-ink);
  white-space: nowrap;
}

.page-sub {
  margin: 0;
  font-size: 12px;
  color: var(--cf-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 8px;
  display: inline-block;
  background: var(--cf-line-strong);
  flex: 0 0 7px;
}

.dot-ok {
  background: var(--cf-teal);
}

.dot-warn {
  background: var(--cf-warning);
}

.dot-bad {
  background: var(--cf-danger);
}

/* ---------- 移动端导航抽屉 ---------- */
.scrim {
  position: fixed;
  inset: 0;
  z-index: 44;
  background: rgba(14, 58, 61, 0.42);
}

.nav-drawer {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 45;
  width: 268px;
  max-width: 84vw;
  display: flex;
  flex-direction: column;
  /* 与桌面侧栏同款深藏青，移动端/桌面端导航一个观感 */
  background: #161c2b;
  border-right: 1px solid #07070d;
  box-shadow: 0 12px 40px rgba(7, 7, 13, 0.3);
  transform: translateX(-100%);
  transition: transform 200ms cubic-bezier(0.22, 0.61, 0.36, 1);
}

.nav-drawer.is-open {
  transform: translateX(0);
}

.drawer-brand {
  position: relative;
  height: 60px;
  flex: 0 0 60px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 64px 0 16px;
  border-bottom: 1px solid #272d3c;
}

.drawer-close {
  position: absolute;
  top: 50%;
  right: 8px;
  transform: translateY(-50%);
  width: 44px;
  height: 44px;
  padding: 0;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.06);
  color: #c8d3e8;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
}

.drawer-close:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
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
  color: #969eaf;
  text-decoration: none;
  transition: background-color 150ms ease, color 150ms ease;
}

.drawer-item:hover {
  background: #1951c3;
  color: #fff;
}

.drawer-item.is-active {
  background: #1951c3;
  color: #fff;
  font-weight: 600;
  box-shadow: inset -3px 0 0 0 #a3beff;
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
  color: var(--cf-faint);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.drawer-item.is-active .drawer-hint {
  color: #c8d3e8;
}

/* 抽屉里的 AI 问法：跟桌面侧栏同一套深底卡片样式 */
.drawer-ai {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #272d3c;
}

.drawer-ai-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 12.5px;
  font-weight: 650;
  color: #a3beff;
}

.drawer-foot {
  flex: 0 0 auto;
  border-top: 1px solid var(--cf-line);
  padding: 10px;
}

.user-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  background: var(--cf-surface-solid);
  border: 1px solid var(--cf-line);
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(16, 24, 40, 0.04);
}

.user-meta {
  min-width: 0;
  flex: 1 1 auto;
}

.user-role {
  font-size: 11px;
  color: var(--cf-faint);
}

/* 抽屉本体：抹掉默认内边距，交给 ChatDrawer 自己排布 */
.chat-drawer :deep(.el-drawer__body) {
  padding: 0;
}

/* ---------- 宽屏放宽内容区：2200/2560 下右侧不再空一大片。
   不用 100vw 参与计算：竖向滚动条会让 100vw 比 clientWidth 宽约 15px。 ---------- */
@media (min-width: 1800px) {
  .topbar-inner,
  .page-main {
    width: min(1920px, calc(100% - 64px));
  }
}

/* ---------- 1180px 以下：侧栏收窄，顶栏先砍次要信息保「不换行」 ---------- */
@media (max-width: 1180px) {
  .shell {
    grid-template-columns: 208px minmax(0, 1fr);
  }

  .topbar-inner {
    gap: 10px;
  }

  /* 只砍顶栏里的次要信息；抽屉里要保留姓名，否则只剩「学生账号 · 退出」 */
  .topbar-inner .clock,
  .topbar-inner .status-text,
  .topbar-inner .user-name {
    display: none;
  }

  .status-btn {
    padding: 5px 8px;
  }

  .user-btn {
    padding: 3px;
  }
}

@media (max-width: 1023px) {
  /* 侧栏整体收起（v-if 已不渲染），栅格随之退化成单列 */
  .shell {
    display: block;
  }

  .shell-main {
    min-height: 100vh;
  }

  .topbar,
  .topbar-inner {
    height: 56px;
    flex-basis: 56px;
  }

  /* 手机上顶栏铺满整宽，左右各 16px 与页面内边距对齐 */
  .topbar-inner {
    width: 100%;
    padding: 0 16px;
    gap: 10px;
  }

  .brand-compact {
    gap: 8px;
  }

  .brand-compact .brand-mark {
    width: 28px;
    height: 28px;
    flex: 0 0 28px;
    border-radius: 9px;
    font-size: 13px;
  }

  .brand-compact .brand-title {
    font-size: 15px;
  }

  /* 手机上不再留 24px 容器内缩，交给页面自身的 16px 内边距；
     标题仍在正文里（.page-head），顶部留白由它给，这里不重复加 */
  .page-main {
    width: 100%;
    padding-top: 0;
    /* 左下宠物（64px）+ 右下 AI 入口（fixed）会盖住正文末尾，
       统一预留一条安全区，避免最后一张卡或按钮被压住 */
    padding-bottom: 104px;
  }

  /* 顶栏状态点只保留绿点信息时，手机上会成为一个没有语义的孤立圆点，
     运维细节不属于学生/教师主路径，窄屏直接收起（抽屉里仍有入口价值不大） */
  .status-btn {
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

}

@media (prefers-reduced-motion: reduce) {
  .side-item,
  .ai-rail-item,
  .nav-drawer,
  .topbar,
  .side-indicator {
    transition: none !important;
  }

  .side-item:hover {
    transform: none !important;
  }
}

/* ---------- 统一壳层的高级化收口 ---------- */
.sidebar {
  padding: 20px 16px 16px;
  /* 去掉左上角那团蓝色径向光斑：它在深底上形成一块与品牌无关的亮区，
     和主区已经清干净的画布不再呼应。只留极轻的上下明暗，保证列有层次。 */
  background: linear-gradient(180deg, #151c29 0%, #111722 100%);
  border-right-color: rgba(255, 255, 255, 0.07);
}

.side-nav {
  gap: 4px;
  margin-top: 20px;
}

.side-item {
  min-height: 46px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 12px;
  font-size: 14px;
  color: #aeb9cd;
}

.side-item:hover {
  background: rgba(255, 255, 255, 0.07);
  border-color: transparent;
  color: #fff;
}

/* 选中态：只留「一层淡蓝底色 + 左缘 3px 指示条」。
   之前是渐变实块 + 右缘内阴影 + 独立滑动指示条三重强调，同一处说了三遍；
   淡底比实块安静，和浅色主区的强调程度也对得上。 */
.side-item.is-active {
  background: rgba(93, 134, 232, 0.18);
  border-color: transparent;
  color: #fff;
  box-shadow: none;
}

/* 菜单项只做颜色过渡；原先悬停右移 2px 会让整列菜单“跟着鼠标晃”，
   在固定的导航上属于噪音，去掉位移。 */
.side-item {
  transition: background-color 140ms ease, color 140ms ease;
}

@media (pointer: coarse) {
  .side-item:hover {
    transform: none;
  }
}

.topbar {
  height: 64px;
  flex-basis: 64px;
  background: rgba(248, 250, 252, 0.82);
  border-bottom-color: rgba(203, 213, 225, 0.84);
}

.topbar-inner {
  height: 64px;
}

.topbar-title-main {
  font-size: 22px;
  letter-spacing: -0.025em;
}

.topbar-title-sub {
  font-size: 13px;
}

.status-btn,
.user-btn,
.icon-btn {
  min-height: 40px;
  border-color: rgba(203, 213, 225, 0.92);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
}

.status-btn:hover,
.user-btn:hover,
.icon-btn:hover {
  border-color: rgba(147, 170, 220, 0.9);
  background: #ffffff;
  box-shadow: 0 6px 16px rgba(30, 64, 175, 0.1);
}

.user-avatar {
  width: 30px;
  height: 30px;
  flex-basis: 30px;
  border-radius: 10px;
  background: linear-gradient(145deg, #dbeafe, #e0e7ff);
  color: #1e40af;
  font-size: 12px;
}

.page-main {
  isolation: isolate;
}

@media (max-width: 1023px) {
  .topbar,
  .topbar-inner {
    height: 60px;
    flex-basis: 60px;
  }

  .topbar-inner {
    padding-inline: 14px;
  }

  /* 手机上 34px 的图标按钮低于 44px 触控红线，统一放大 */
  .icon-btn {
    width: 44px;
    height: 44px;
    border-radius: 12px;
  }

  .nav-drawer {
    width: min(320px, 88vw);
    background:
      radial-gradient(300px 220px at 6% 0%, rgba(71, 112, 223, 0.22), transparent 72%),
      linear-gradient(180deg, #111827 0%, #161c2b 52%, #101827 100%);
  }

  .drawer-item {
    min-height: 48px;
    border: 1px solid transparent;
  }

  .drawer-foot .logout-btn {
    min-height: 44px;
    padding: 10px 14px;
  }

  .drawer-item.is-active {
    border-color: rgba(147, 197, 253, 0.22);
    box-shadow: inset 3px 0 0 #bfdbfe, 0 8px 18px rgba(2, 6, 23, 0.18);
  }
}
</style>
