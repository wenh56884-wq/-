import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发端口 5173；后端无 /api 前缀，故 proxy 里把 /api 前缀 rewrite 掉
export default defineConfig({
  plugins: [vue()],
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
  build: {
    // 将 Element Plus 与 ECharts 从应用入口拆出，降低首屏 chunk 体积并消除单包告警。
    // 两个按需路由级依赖自身仍会超过 Vite 默认 500KB 阈值，提升阈值避免把正常 vendor chunk 当成构建失败。
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('node_modules/echarts') || id.includes('node_modules\\echarts')) return 'echarts'
          if (id.includes('node_modules/element-plus') || id.includes('node_modules\\element-plus')) return 'element-plus'
          return 'vendor'
        }
      }
    }
  }
})
