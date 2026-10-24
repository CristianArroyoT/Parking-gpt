<script setup lang="ts">
// Componente raíz: sólo aloja el router outlet. El layout se aplica
// por ruta desde el propio router (meta.layout).
//
// T-174 (2026-10-24): el contenedor de toasts vive AQUÍ (en la raíz) y
// no dentro del layout. Al cerrar sesión la app navega al login con el
// router (sin recargar la página), el layout se desmonta y, con el
// contenedor dentro, el toast de «Sesión cerrada» no llegaba a verse
// nunca: la recarga se lo comía.
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
</script>

<template>
  <RouterView />

  <div class="fixed top-4 right-4 z-50 space-y-2">
    <div
      v-for="t in ui.toasts"
      :key="t.id"
      :class="[
        'rounded-lg shadow-card px-4 py-3 text-sm max-w-sm bg-white border cursor-pointer',
        t.type === 'success' && 'border-emerald-300 text-emerald-800',
        t.type === 'warn' && 'border-amber-300 text-amber-800',
        t.type === 'error' && 'border-rose-300 text-rose-800',
        t.type === 'info' && 'border-slate-300 text-slate-800',
      ]"
      role="status"
      aria-live="polite"
      @click="ui.dismissToast(t.id)"
    >
      {{ t.message }}
    </div>
  </div>
</template>
