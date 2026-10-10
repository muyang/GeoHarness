import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发代理：/node/* → GeoNode（默认 127.0.0.1:8787）。
// 浏览器直连跨域节点需要节点侧开 GEONODE_CORS_ORIGINS；代理路径则同源，零配置。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5175,
    proxy: {
      // 正则上下文 '^/node/'：**必须**带尾斜杠 —— 前缀写法 '/node' 会把
      // '/node_modules/...' 一并吞掉转发给节点（全部 404，页面白屏）。
      '^/node/': {
        target: process.env.GEONODE_URL || 'http://127.0.0.1:8787',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/node\//, '/')
      }
    }
  },
  build: { outDir: 'dist', chunkSizeWarningLimit: 4000 }
})
