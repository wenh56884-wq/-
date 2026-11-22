import axios from 'axios'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'

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
  // 广播登录事件：宠物等全局常驻组件监听后重拉登录态相关的数据
  window.dispatchEvent(new CustomEvent('qh:session'))
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
  async (error) => {
    const status = error?.response?.status
    let detail = error?.response?.data?.detail || error?.message || '请求失败'
    // 导出接口用 responseType:'blob'：失败时后端返回的 JSON 也包在 Blob 里，
    // 直接取 .detail 拿到的是 undefined，用户只会看到一句「请求失败」
    if (error?.response?.data instanceof Blob) {
      try {
        const parsed = JSON.parse(await error.response.data.text())
        if (parsed?.detail) detail = parsed.detail
      } catch {
        /* 非 JSON（真的是文件）就保留原提示 */
      }
    }
    if (status === 401) {
      ElMessage.error('登录已失效，请重新登录')
      clearSession()
      router.push('/login')
      return Promise.reject(error)
    }
    // 宠物是陪伴层：接口失败由宠物气泡兜底，不弹全局错误
    // （proactive 每分钟轮询一次，后端不可用时否则会每分钟弹一条）
    if (String(error?.config?.url || '').startsWith('/pet/')) {
      return Promise.reject(error)
    }
    ElMessage.error(typeof detail === 'string' ? detail : '请求失败')
    return Promise.reject(error)
  }
)

export default http
