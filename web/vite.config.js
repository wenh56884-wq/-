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
  }
})
