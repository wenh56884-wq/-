import { createRouter, createWebHistory } from 'vue-router'

// 全部按需加载：单页面应用一次性打进主包会到 2MB+，首屏（登录页）
// 要把 12 个页面和 ECharts 全下载完才出现内容。改成访问时才拉对应 chunk，
// 首屏只取登录页那一小块。ShellLayout 是登录后立刻要用的骨架，仍单独成块。
const ShellLayout = () => import('../layout/ShellLayout.vue')
const Assessment = () => import('../views/Assessment.vue')
const Assistant = () => import('../views/Assistant.vue')
const CareerForecast = () => import('../views/CareerForecast.vue')
const ElectiveAdvice = () => import('../views/ElectiveAdvice.vue')
const ExamNotices = () => import('../views/ExamNotices.vue')
const GradeReport = () => import('../views/GradeReport.vue')
const InterviewRoom = () => import('../views/InterviewRoom.vue')
const KgView = () => import('../views/KgView.vue')
const JobList = () => import('../views/JobList.vue')
const Login = () => import('../views/Login.vue')
const NotFound = () => import('../views/NotFound.vue')
const StudentForecast = () => import('../views/StudentForecast.vue')
const StudentHome = () => import('../views/StudentHome.vue')
const TeacherDashboard = () => import('../views/TeacherDashboard.vue')
const TeacherStudents = () => import('../views/TeacherStudents.vue')
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
      { path: '', name: 'teacher-overview', component: TeacherDashboard,
        meta: { title: '班级总览' } },
      { path: 'students', name: 'teacher-students', component: TeacherStudents,
        meta: { title: '学生档案' } },
      { path: 'grades', name: 'teacher-grades', component: GradeReport,
        meta: { title: '成绩单' } },
      { path: 'jobs', name: 'teacher-jobs', component: JobList,
        meta: { title: '岗位库' } },
      { path: 'exams', name: 'teacher-exams', component: ExamNotices,
        meta: { title: '招考信息' } },
      { path: 'approvals', name: 'teacher-approvals', component: WorkflowApprovals,
        meta: { title: '工作流审批' } },
      { path: 'kg', name: 'teacher-kg', component: KgView,
        meta: { title: '知识图谱' } },
      { path: 'assistant', name: 'teacher-assistant', component: Assistant,
        meta: { title: 'AI 助手' } },
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
      { path: 'grades', name: 'student-grades', component: GradeReport,
        meta: { title: '成绩单' } },
      { path: 'jobs', name: 'student-jobs', component: JobList,
        meta: { title: '岗位库' } },
      { path: 'interview', name: 'student-interview', component: InterviewRoom,
        meta: { title: '模拟面试' } },
      { path: 'exams', name: 'student-exams', component: ExamNotices,
        meta: { title: '招考信息' } },
      { path: 'kg', name: 'student-kg', component: KgView,
        meta: { title: '知识图谱' } },
      { path: 'forecast', name: 'student-forecast', component: StudentForecast,
        meta: { title: '学业预测' } },
      { path: 'assessment', name: 'student-assessment', component: Assessment,
        meta: { title: '职业测评' } },
      { path: 'assistant', name: 'student-assistant', component: Assistant,
        meta: { title: 'AI 助手' } },
      { path: 'career', name: 'student-career', component: CareerForecast,
        meta: { title: '报考分析' } },
      { path: 'elective', name: 'student-elective', component: ElectiveAdvice,
        meta: { title: '选课推荐' } },
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
