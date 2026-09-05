import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Fixed port, not Vite's "increment if busy" default — hi/cors.py's
// allowlist is scoped to this exact origin (a deliberate choice over a
// wildcard, since hi/ipc/server.py's whole point is being unreachable
// from anything but a known local caller); a silently-different port
// would just look like a broken CORS setup instead of a clear error.
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: true,
  },
})
