import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Fixed port: hi/cors.py only allows this exact origin to talk to the backend.
export default defineConfig({
  plugins: [vue()],
  server: { port: 5173, strictPort: true },
})
