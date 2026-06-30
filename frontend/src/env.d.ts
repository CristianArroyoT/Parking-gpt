/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const component: DefineComponent<{}, {}, any>
  export default component
}

interface ImportMetaEnv {
  // Vacío por diseño: el frontend SIEMPRE habla con rutas relativas
  // '/api/v1' que Vite redirige al backend mediante el proxy interno
  // configurado en vite.config.ts (lee VITE_PROXY_TARGET, que no es
  // inyectado al bundle).
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}