<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="min-h-screen bg-slate-100 grid place-items-center p-6">
    <div class="bg-white rounded-2xl shadow-lg p-10 max-w-md text-center">
      <div class="text-6xl mb-4">🅿️</div>
      <h1 class="text-xl font-semibold text-slate-900">Página no encontrada</h1>
      <p class="mt-2 text-sm text-slate-500">La ruta solicitada no existe en solidAPP.</p>
      <RouterLink to="/" class="btn-primary inline-block mt-6">Volver al inicio</RouterLink>
    </div>
  </div>
</template>