import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:3001' },
    watch: {
      ignored: [
        '**/ml/data/**',
        '**/ml/artifacts/**',
        '**/logs/**',
        '**/.codex-logs/**',
        '**/output/**',
      ],
    },
  },
  preview: { port: 5173, proxy: { '/api': 'http://localhost:3001' } },
})
