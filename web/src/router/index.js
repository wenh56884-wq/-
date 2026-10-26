import { createRouter, createWebHistory } from 'vue-router'

import ShellLayout from '../layout/ShellLayout.vue'
import Login from '../views/Login.vue'
import StudentHome from '../views/StudentHome.vue'
import TeacherDashboard from '../views/TeacherDashboard.vue'
import TeacherStudents from '../views/TeacherStudents.vue'

const routes = [
  { path: '/', redirect: '/login' },
  { path: '/login', name: 'login', component: Login },
  {
    path: '/teacher',
    component: ShellLayout,
    meta: { role: 'teacher' },
    children: [
      { path: '', name: 'teacher-overview', component: TeacherDashboard },
      { path: 'students', name: 'teacher-students', component: TeacherStudents }
    ]
  },
  {
    path: '/student',
    component: ShellLayout,
    meta: { role: 'student' },
    children: [{ path: '', name: 'student-home', component: StudentHome }]
  },
  // 智能助手已改为右下角悬浮抽屉，这里保留旧地址做重定向，避免历史链接白屏
  {
    path: '/assistant',
    redirect: () => (localStorage.getItem('qh_role') === 'teacher' ? '/teacher' : '/student')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
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
