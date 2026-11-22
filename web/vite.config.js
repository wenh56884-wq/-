import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'

// Element Plus 2.x 的官方 resolver 从 `element-plus/es` 桶文件导入，
// 桶里的默认安装器会把整套组件带进来（实测 794KB 没降）。
// 这里直接指向每个组件的 index.mjs；子组件（FormItem/TableColumn 等）
// 没有独立入口，映射回父组件目录。
const EP_SUBCOMPONENTS = {
  'collapse-item': 'collapse',
  'descriptions-item': 'descriptions',
  'form-item': 'form',
  option: 'select',
  'option-group': 'select',
  'radio-button': 'radio',
  'radio-group': 'radio',
  'tab-pane': 'tabs',
  'table-column': 'table'
}

function kebabCase(value) {
  return value
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .replace(/([A-Z])([A-Z][a-z])/g, '$1-$2')
    .toLowerCase()
}

function ElementPlusPerComponentResolver() {
  return {
    type: 'component',
    resolve(name) {
      if (!name.startsWith('El')) return undefined
      const partial = kebabCase(name.slice(2))
      const dir = EP_SUBCOMPONENTS[partial] || partial
      return {
        name,
        from: `element-plus/es/components/${dir}/index.mjs`,
        // 样式用组件自己的目录（FormItem 的样式在 form-item，不在 form）
        sideEffects: [`element-plus/es/components/${partial}/style/css`]
      }
    }
  }
}

// 开发端口 5173；后端无 /api 前缀，故 proxy 里把 /api 前缀 rewrite 掉。
// 构建产物（vite preview）里 axios baseURL 是 '/'，请求直接走同源路径，
// 因此 preview 代理按后端真实路由前缀逐一转发到 8000。
const BACKEND_PREFIXES = [
  '/auth', '/assessment', '/career', '/chat', '/elective', '/exam', '/export',
  '/forecast', '/grades', '/interview', '/job', '/kb', '/kg', '/pet', '/qb',
  '/student', '/teacher', '/web', '/workflow', '/notifications'
]

// 页面路由与 API 前缀同名（/student、/teacher、/kg…），整段转发会让深链接
// 拿到后端返回的 HTML 而不是前端入口。这里显式列出前端页面路由，命中即跳过代理。
const PAGE_ROUTES = [
  '/login', '/assistant',
  '/student', '/student/academic', '/student/opportunity', '/student/plan',
  '/student/interview', '/student/kg', '/student/campus', '/student/assistant',
  '/teacher', '/teacher/career', '/teacher/campus', '/teacher/opportunity',
  '/teacher/approvals', '/teacher/kg', '/teacher/assistant', '/teacher/agent-quality'
]

const backendProxy = Object.fromEntries(
  BACKEND_PREFIXES.map((p) => [
    p,
    {
      target: 'http://127.0.0.1:8000',
      changeOrigin: true,
      // 命中页面路由时返回原路径，交给静态资源 + SPA fallback 处理
      bypass(req) {
        const path = (req.url || '').split('?')[0].replace(/\/+$/, '') || '/'
        return PAGE_ROUTES.includes(path) ? req.url : undefined
      }
    }
  ])
)

export default defineConfig({
  plugins: [
    vue(),
    // 模板里的 el-* 按需引入，避免 main.js 注册整包 Element Plus。
    // 样式仍由 main.js 引完整 index.css，避免按需样式漏掉 v-loading/Message。
    Components({
      resolvers: [ElementPlusPerComponentResolver()],
      dts: false
    })
  ],
  server: {
    // 开发模式允许同一局域网的设备访问；仅适合可信局域网，不是公网部署。
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
    proxy: backendProxy
  },
  build: {
    // 将 Element Plus 与 ECharts 从应用入口拆出，降低首屏 chunk 体积并消除单包告警。
    // 两个按需路由级依赖自身仍会超过 Vite 默认 500KB 阈值，提升阈值避免把正常 vendor chunk 当成构建失败。
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('node_modules/echarts') || id.includes('node_modules\\echarts')) return 'echarts'
          // Vue 核心/路由/axios 固定成 vendor；Element Plus 不再强制聚成一个
          // chunk，交给 Rollup 按路由实际引用拆分，登录页只带自己用到的组件。
          if (/node_modules[\\/](vue|@vue|vue-router|axios)[\\/]/.test(id)) return 'vendor'
          return undefined
        }
      }
    }
  }
})
