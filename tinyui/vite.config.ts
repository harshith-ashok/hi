import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

// Fixed port: hi/server/cors.py only allows this exact origin to talk to the backend.
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { port: 5176, strictPort: true },
  build: { chunkSizeWarningLimit: 700 }, // mermaid is loaded on demand and is large by nature
})
