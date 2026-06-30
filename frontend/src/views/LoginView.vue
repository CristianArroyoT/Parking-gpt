<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()
const route = useRoute()

const email = ref('')
const password = ref('')

async function submit(): Promise<void> {
  try {
    await auth.login(email.value, password.value)
    const redirect = (route.query.redirect as string) || '/'
    ui.pushToast('success', 'Bienvenido a solidAPP')
    router.push(redirect)
  } catch {
    // El mensaje ya quedó en auth.error
  }
}

function fillDemo(role: 'admin' | 'gestor' | 'operador' | 'cliente'): void {
  const map: Record<string, [string, string]> = {
    admin:    ['admin@solidapp.es', 'admin12345'],
    gestor:   ['gestor.madrid@solidapp.es', 'gestor1234'],
    operador: ['operador.madrid@solidapp.es', 'oper12345'],
    cliente:  ['cliente.demo@solidapp.es', 'cliente1234'],
  }
  const [e, p] = map[role]
  email.value = e
  password.value = p
}
</script>

<template>
  <div class="min-h-screen bg-slate-100 flex items-center justify-center p-6 antialiased">
    <div class="w-full max-w-sm">
      <div class="flex items-center gap-3 justify-center mb-8">
        <div class="h-12 w-12 rounded-xl bg-slate-900 text-white grid place-items-center font-bold text-lg">s</div>
        <div>
          <div class="font-semibold tracking-tight text-2xl text-slate-900">solidAPP</div>
          <div class="text-xs text-slate-500">Gestión de parkings</div>
        </div>
      </div>

      <div class="bg-white rounded-2xl shadow-lg p-8">
        <h1 class="text-xl font-semibold text-slate-900">Iniciar sesión</h1>
        <p class="mt-1 text-sm text-slate-500">Accede con tu email corporativo</p>

        <form class="mt-6 space-y-4" @submit.prevent="submit">
          <div>
            <label for="email" class="block text-sm font-medium text-slate-700">Email</label>
            <input id="email" v-model="email" type="email" required
              placeholder="usuario@solidapp.es" class="input" autocomplete="email" />
          </div>
          <div>
            <label for="password" class="block text-sm font-medium text-slate-700">Contraseña</label>
            <input id="password" v-model="password" type="password" required
              placeholder="••••••••" class="input" autocomplete="current-password" />
          </div>

          <p v-if="auth.error" class="text-sm text-rose-600">{{ auth.error }}</p>

          <button type="submit" class="btn-primary w-full py-2.5" :disabled="auth.loading">
            {{ auth.loading ? 'Entrando…' : 'Iniciar sesión' }}
          </button>
        </form>

        <div class="mt-6 border-t border-slate-200 pt-4">
          <p class="text-xs uppercase tracking-wide text-slate-500 mb-2">Cuentas demo</p>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <button type="button" class="btn-secondary" @click="fillDemo('admin')">Admin</button>
            <button type="button" class="btn-secondary" @click="fillDemo('gestor')">Gestor</button>
            <button type="button" class="btn-secondary" @click="fillDemo('operador')">Operador</button>
            <button type="button" class="btn-secondary" @click="fillDemo('cliente')">Cliente</button>
          </div>
        </div>
      </div>

      <p class="mt-6 text-center text-xs text-slate-500">
        © 2026 solidAPP · Datos protegidos bajo LOPDGDD
      </p>
    </div>
  </div>
</template>