import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { useAuthStore } from './stores/auth'
import { registerServiceWorker } from './pwa/registerServiceWorker'
import './style.css'

const app = createApp(App)
app.use(createPinia())

// Hidratamos la sesión antes de montar el router para que los guards
// tengan ya el estado de usuario (o la falta de él).
const auth = useAuthStore()
auth.restore().finally(() => {
  app.use(router)
  app.mount('#app')
  // T-24 (PWA): el service worker sólo se registra en producción (ver
  // `pwa/registerServiceWorker.ts`). No cachea `/api/`: los datos en
  // vivo se piden siempre a la red.
  registerServiceWorker()
})