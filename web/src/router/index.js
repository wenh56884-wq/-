import { createRouter, createWebHistory } from 'vue-router'

import Login from '../views/Login.vue'
import TeacherDashboard from '../views/TeacherDashboard.vue'
import StudentHome from '../views/StudentHome.vue'

const routes = [
  { path: '/', redirect: '/login' },
  { path: '/login', name: 'login', component: Login },
  { path: '/teacher', name: 'teacher', component: TeacherDashboard, meta: { role: 'teacher' } },
  { path: '/student', name: 'student', component: StudentHome, meta: { role: 'student' } }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 全局守卫：无 token 一律回登录；角色与路由不匹配时回自己的主页
router.beforeEach((to) => {
  const token = localStorage.getItem('qh_token')
  const role = localStorage.getItem('qh_role')
  if (to.path !== '/login' && !token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta?.role && role && to.meta.role !== role) {
    return { path: role === 'teacher' ? '/teacher' : '/student' }
  }
  if (to.path === '/login' && token) {
    return { path: role === 'teacher' ? '/teacher' : '/student' }
  }
  return true
})

export default router
