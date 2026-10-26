import axios from 'axios'
import { ElMessage } from 'element-plus'

import router from '../router'

// axios 实例：开发态走 /api（Vite proxy rewrite 到后端根路径）；
// 生产构建由 FastAPI 同源托管，后端路由没有 /api 前缀，故直接走根路径
const http = axios.create({
  baseURL: import.meta.env.DEV ? '/api' : '/',
  timeout: 30000
})

export function saveSession(role, token, extra = {}) {
  localStorage.setItem('qh_token', token)
  localStorage.setItem('qh_role', role)
  Object.entries(extra).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      localStorage.setItem(`qh_${key}`, String(value))
    }
  })
}

export function clearSession() {
  localStorage.removeItem('qh_token')
  localStorage.removeItem('qh_role')
  localStorage.removeItem('qh_student_no')
  localStorage.removeItem('qh_tenant_id')
}

export function currentRole() {
  return localStorage.getItem('qh_role') || ''
}

// 请求拦截：带 JWT
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('qh_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：只有 401（token 失效）才清登录态并回 /login；
// 403 是“已登录但无权访问该数据”（如跨租户/角色不符），应保留登录态并提示具体原因。
http.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail || error?.message || '请求失败'
    if (status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      clearSession()
      router.push('/login')
      return Promise.reject(error)
    }
    ElMessage.error(typeof detail === 'string' ? detail : '请求失败')
    return Promise.reject(error)
  }
)

export default http
