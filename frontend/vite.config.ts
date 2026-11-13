import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Dev only: forward API calls to the FastAPI backend. /api/x -> http://127.0.0.1:8000/x
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/api': {
        target: 'http://127.0.0.1:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: { environment: 'node', include: ['src/**/*.test.{ts,tsx}'] },
})
