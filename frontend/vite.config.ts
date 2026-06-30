import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Proxy de /api al backend en :8000. Lee VITE_PROXY_TARGET por si la
// pila expone el backend en otro host (Docker compose, k8s, etc.).
// Ojo: la variable se llama así (no VITE_API_BASE) precisamente para
// que Vite NO la inyecte en el bundle del frontend. El bundle debe
// usar SIEMPRE rutas relativas '/api/v1' para pasar por este proxy.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})