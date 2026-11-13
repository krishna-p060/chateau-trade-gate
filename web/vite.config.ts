import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const GATE = 'http://127.0.0.1:8400'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: GATE, changeOrigin: true },
      '/.well-known': { target: GATE, changeOrigin: true },
      '/docs': { target: GATE, changeOrigin: true },
      '/openapi.json': { target: GATE, changeOrigin: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
