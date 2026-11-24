import { createRouter, createWebHistory } from 'vue-router'

// 全部按需加载：单页面应用一次性打进主包会到 2MB+，首屏（登录页）
// 要把 12 个页面和 ECharts 全下载完才出现内容。改成访问时才拉对应 chunk，
// 首屏只取登录页那一小块。ShellLayout 是登录后立刻要用的骨架，仍单独成块。
const ShellLayout = () => import('../layout/ShellLayout.vue')
const AgentQuality = () => import('../views/AgentQuality.vue')
const Assistant = () => import('../views/Assistant.vue')
const CampusInsight = () => import('../views/CampusInsight.vue')
const InterviewHub = () => import('../views/InterviewHub.vue')
const InnovationHub = () => import('../views/InnovationHub.vue')

// 聚合板块：几个强相关的旧页面合并成一个板块，二级 Tab 见各自视图
const AcademicHub = () => import('../views/AcademicHub.vue')
const OpportunityHub = () => import('../views/OpportunityHub.vue')
const PlanHub = () => import('../views/PlanHub.vue')
const TeacherStudentsHub = () => import('../views/TeacherStudentsHub.vue')

const KgView = () => import('../views/KgView.vue')
const Login = () => import('../views/Login.vue')
const NotFound = () => import('../views/NotFound.vue')
const StudentHome = () => import('../views/StudentHome.vue')
const TeacherCareerSearch = () => import('../views/TeacherCareerSearch.vue')
const TeacherCampusInsight = () => import('../views/TeacherCampusInsight.vue')
// 联网搜索已并入 AI 助手页（/assistant 内「联网搜索」模式渲染 WebSearch 组件）
const WorkflowApprovals = () => import('../views/WorkflowApprovals.vue')

// meta.title 与侧栏菜单 label 保持一致：浏览器标签、历史记录、窗口标题同源，
// 演示时多页切换也能看出当前是哪一页。
const routes = [
  { path: '/', redirect: '/login' },
  { path: '/login', name: 'login', component: Login, meta: { title: '登录' } },
  {
    path: '/teacher',
    component: ShellLayout,
    meta: { role: 'teacher' },
    children: [
      { path: '', name: 'teacher-students-hub', component: TeacherStudentsHub,
        meta: { title: '学生' } },
      // 旧地址一律保留：侧栏合并了，书签与别处发来的链接不能白屏。
      // 转发时带上原 query（如 ?student_no=），否则「从档案点成绩」会丢掉是哪个人。
      { path: 'students', redirect: (to) => ({ path: '/teacher', query: { ...to.query, tab: 'roster' } }) },
      { path: 'grades', redirect: (to) => ({ path: '/teacher', query: { ...to.query, tab: 'grades' } }) },
      { path: 'career', name: 'teacher-career', component: TeacherCareerSearch,
        meta: { title: '生涯规划' } },
      { path: 'campus', name: 'teacher-campus', component: TeacherCampusInsight,
        meta: { title: '校园洞察' } },
      { path: 'opportunity', name: 'teacher-opportunity', component: OpportunityHub,
        meta: { title: '机会库' } },
      { path: 'jobs', redirect: '/teacher/opportunity' },
      { path: 'exams', redirect: '/teacher/opportunity?tab=exams' },
      { path: 'approvals', name: 'teacher-approvals', component: WorkflowApprovals,
        meta: { title: '工作流审批' } },
      { path: 'kg', name: 'teacher-kg', component: KgView,
        meta: { title: '知识图谱' } },
      { path: 'innovation', name: 'teacher-innovation', component: InnovationHub,
        meta: { title: '创新全景' } },
      { path: 'assistant', name: 'teacher-assistant', component: Assistant,
        meta: { title: 'AI 助手' } },
      { path: 'agent-quality', name: 'teacher-agent-quality', component: AgentQuality,
        meta: { title: '智能体质量' } },
      // 侧栏内的无效地址：保留侧栏，只把内容区换成 404，不至于整屏白掉
      { path: ':pathMatch(.*)*', name: 'teacher-not-found', component: NotFound,
        meta: { title: '页面不存在' } }
    ]
  },
  {
    path: '/student',
    component: ShellLayout,
    meta: { role: 'student' },
    children: [
      { path: '', name: 'student-home', component: StudentHome,
        meta: { title: '我的画像' } },
      { path: 'academic', name: 'student-academic', component: AcademicHub,
        meta: { title: '学业' } },
      { path: 'grades', redirect: '/student/academic' },
      { path: 'forecast', redirect: '/student/academic?tab=forecast' },
      { path: 'elective', redirect: '/student/academic?tab=elective' },
      { path: 'opportunity', name: 'student-opportunity', component: OpportunityHub,
        meta: { title: '机会库' } },
      { path: 'jobs', redirect: '/student/opportunity' },
      { path: 'exams', redirect: '/student/opportunity?tab=exams' },
      { path: 'plan', name: 'student-plan', component: PlanHub,
        meta: { title: '生涯规划' } },
      { path: 'career', redirect: '/student/plan' },
      { path: 'assessment', redirect: '/student/plan?tab=assessment' },
      { path: 'interview', name: 'student-interview', component: InterviewHub,
        meta: { title: '模拟面试' } },
      // 旧链接保持可用：实验室已并入模拟面试板块的第二个工位
      { path: 'lab', redirect: '/student/interview?mode=lab' },
      { path: 'kg', name: 'student-kg', component: KgView,
        meta: { title: '知识图谱' } },
      { path: 'campus', name: 'student-campus', component: CampusInsight,
        meta: { title: '校园洞察' } },
      { path: 'assistant', name: 'student-assistant', component: Assistant,
        meta: { title: 'AI 助手' } },
      { path: 'innovation', name: 'student-innovation', component: InnovationHub,
        meta: { title: '创新全景' } },
      { path: ':pathMatch(.*)*', name: 'student-not-found', component: NotFound,
        meta: { title: '页面不存在' } }
    ]
  },
  // 智能助手已升级为独立页面，旧的 /assistant 地址重定向到新页，避免历史链接白屏
  {
    path: '/assistant',
    redirect: () => (localStorage.getItem('qh_role') === 'teacher'
      ? '/teacher/assistant' : '/student/assistant')
  },
  // 顶层兜底：必须放在最后，否则会抢先匹配掉上面的正常路由
  { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFound,
    meta: { title: '页面不存在' } }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  // 切页回到顶部（滚动发生在 window 上，不是内部容器）；
  // 浏览器前进 / 后退时恢复原位置，长列表翻页返回不会丢位置。
  scrollBehavior(to, from, savedPosition) {
    return savedPosition || { top: 0 }
  }
})

router.afterEach((to) => {
  const title = to.meta?.title
  document.title = title ? `启航 · ${title}` : '启航'
})

// 全局守卫：无 token 一律回登录；角色与路由不匹配时回自己的主页
router.beforeEach((to) => {
  const token = localStorage.getItem('qh_token')
  const role = localStorage.getItem('qh_role')
  const home = role === 'teacher' ? '/teacher' : '/student'
  if (!token) {
    return to.path === '/login' ? true : { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login') {
    return { path: home }
  }
  // meta.role 写在父路由上，需用 matched 逐层检查
  const need = to.matched.map((record) => record.meta?.role).find((value) => value)
  if (need && role && need !== role) {
    return { path: home }
  }
  return true
})

export default router
