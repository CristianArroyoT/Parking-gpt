<script setup lang="ts">
/**
 * Recuperación de contraseña (T-22).
 *
 * Es la página a la que apunta el enlace del correo
 * (`/recuperar-contrasena?token=...`, ver
 * `app/services/password_reset_email.py`). Tiene dos modos:
 *
 * 1. **Sin token** (el usuario acaba de decidir que olvidó su clave):
 *    pide el enlace por correo. La respuesta es SIEMPRE la misma haya o
 *    no cuenta con ese email — por eso no se distingue un caso del
 *    otro en pantalla: decirlo sería un oráculo de enumeración de
 *    cuentas.
 * 2. **Con token** (el usuario viene del correo): permite fijar la
 *    contraseña nueva. El token es de un solo uso y caduca.
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  requestPasswordReset,
  resetPassword,
} from '@/api/passwordReset'

const route = useRoute()
const router = useRouter()

/** El token llega en la query del enlace del correo. */
const token = computed(() => {
  const t = route.query.token
  return typeof t === 'string' ? t : ''
})

const email = ref('')
const password = ref('')
const confirm = ref('')

const sending = ref(false)
const done = ref(false)
const error = ref('')

async function pedirEnlace(): Promise<void> {
  error.value = ''
  if (!email.value.trim()) {
    error.value = 'Indica tu email.'
    return
  }
  sending.value = true
  try {
    await requestPasswordReset(email.value.trim())
    done.value = true
  } catch (err: unknown) {
    error.value =
      typeof err === 'object' && err !== null
        ? ((err as { response?: { data?: { detail?: string } } }).response?.data
            ?.detail ?? 'No se pudo enviar el correo. Inténtalo más tarde.')
        : 'No se pudo enviar el correo. Inténtalo más tarde.'
  } finally {
    sending.value = false
  }
}

async function cambiarClave(): Promise<void> {
  error.value = ''
  if (password.value.length < 8) {
    error.value = 'La contraseña debe tener al menos 8 caracteres.'
    return
  }
  if (password.value !== confirm.value) {
    error.value = 'Las contraseñas no coinciden.'
    return
  }
  sending.value = true
  try {
    await resetPassword(token.value, password.value)
    done.value = true
  } catch (err: unknown) {
    error.value =
      typeof err === 'object' && err !== null
        ? ((err as { response?: { data?: { detail?: string } } }).response?.data
            ?.detail ??
          'El enlace no es válido o ha caducado. Pide uno nuevo.')
        : 'El enlace no es válido o ha caducado. Pide uno nuevo.'
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-slate-100 flex items-center justify-center p-6 antialiased">
    <div class="w-full max-w-sm">
      <div class="flex flex-col items-center gap-3 mb-8">
        <img
          src="/logo-solidapp.png?v=2"
          alt="solidAPP"
          class="max-h-14 max-w-full rounded bg-white"
        />
        <div class="text-xs text-slate-500">Gestión de parkings</div>
      </div>

      <div class="bg-white rounded-2xl shadow-lg p-8">
        <template v-if="done">
          <h1 class="text-xl font-semibold text-slate-900">
            {{ token ? 'Contraseña actualizada' : 'Revisa tu correo' }}
          </h1>
          <p class="mt-2 text-sm text-slate-600">
            <template v-if="token">
              Ya puedes iniciar sesión con la contraseña nueva.
            </template>
            <template v-else>
              Si ese email está registrado, te hemos enviado un enlace para
              cambiar la contraseña. El enlace caduca en 30 minutos.
            </template>
          </p>
          <button
            type="button"
            class="btn-primary w-full py-2.5 mt-6"
            @click="router.push({ name: 'login' })"
          >
            Ir al inicio de sesión
          </button>
        </template>

        <template v-else-if="token">
          <h1 class="text-xl font-semibold text-slate-900">Nueva contraseña</h1>
          <p class="mt-1 text-sm text-slate-500">
            Elige la contraseña con la que vas a entrar a partir de ahora.
          </p>

          <form class="mt-6 space-y-4" @submit.prevent="cambiarClave">
            <div>
              <label for="new-password" class="block text-sm font-medium text-slate-700">
                Contraseña nueva
              </label>
              <input
                id="new-password"
                v-model="password"
                type="password"
                required
                minlength="8"
                autocomplete="new-password"
                placeholder="••••••••"
                class="input"
              />
            </div>
            <div>
              <label for="confirm-password" class="block text-sm font-medium text-slate-700">
                Repite la contraseña
              </label>
              <input
                id="confirm-password"
                v-model="confirm"
                type="password"
                required
                minlength="8"
                autocomplete="new-password"
                placeholder="••••••••"
                class="input"
              />
            </div>

            <p v-if="error" class="text-sm text-rose-600">{{ error }}</p>

            <button type="submit" class="btn-primary w-full py-2.5" :disabled="sending">
              {{ sending ? 'Guardando…' : 'Cambiar contraseña' }}
            </button>
          </form>
        </template>

        <template v-else>
          <h1 class="text-xl font-semibold text-slate-900">Recuperar contraseña</h1>
          <p class="mt-1 text-sm text-slate-500">
            Te enviamos un enlace para cambiar la contraseña
          </p>

          <form class="mt-6 space-y-4" @submit.prevent="pedirEnlace">
            <div>
              <label for="reset-email" class="block text-sm font-medium text-slate-700">
                Email
              </label>
              <input
                id="reset-email"
                v-model="email"
                type="email"
                required
                autocomplete="email"
                placeholder="usuario@solidapp.es"
                class="input"
              />
            </div>

            <p v-if="error" class="text-sm text-rose-600">{{ error }}</p>

            <button type="submit" class="btn-primary w-full py-2.5" :disabled="sending">
              {{ sending ? 'Enviando…' : 'Enviar enlace' }}
            </button>
          </form>

          <button
            type="button"
            class="w-full mt-4 text-sm text-slate-500 hover:text-slate-700"
            @click="router.push({ name: 'login' })"
          >
            Volver al inicio de sesión
          </button>
        </template>
      </div>
    </div>
  </div>
</template>
