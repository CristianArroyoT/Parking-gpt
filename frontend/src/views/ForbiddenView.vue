<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="min-h-screen bg-slate-100 grid place-items-center p-6">
    <div class="bg-white rounded-2xl shadow-lg p-10 max-w-md text-center">
      <div class="text-6xl mb-4">🔒</div>
      <h1 class="text-xl font-semibold text-slate-900">Acceso denegado</h1>
      <p class="mt-2 text-sm text-slate-500">
        Tu rol no tiene permiso para acceder a esta sección.
      </p>
      <RouterLink to="/login" class="btn-primary inline-block mt-6">Iniciar sesión con otra cuenta</RouterLink>
    </div>
  </div>
</template>