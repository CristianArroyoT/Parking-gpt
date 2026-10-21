<script setup lang="ts">
/**
 * T-19 (2026-10-21): vista "Mi perfil" del cliente.
 *
 * Tres bloques:
 *   1. Datos de perfil → nombre y teléfono (``PATCH /users/me/profile``).
 *      El email y el rol **no** son editables: los cambia el administrador.
 *   2. Información de la cuenta (email, rol, id) en modo lectura.
 *   3. Cambio de contraseña → reutiliza el mismo endpoint que el modal del
 *      sidebar (``PATCH /users/me/password``), a través del store de auth,
 *      para que las reglas de validación sean idénticas en los dos sitios.
 */
import { onMounted, ref } from 'vue'
import AppLayout from '@/layouts/AppLayout.vue'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import { getMyProfile, updateMyProfile } from '@/api/userScope'

const auth = useAuthStore()
const ui = useUiStore()

const loading = ref(true)
const saving = ref(false)
const error = ref<string | null>(null)

const form = ref({ full_name: '', phone: '' })

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const user = await getMyProfile()
    form.value = { full_name: user.full_name, phone: user.phone ?? '' }
    auth.user = user
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudo cargar tu perfil')
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  error.value = null
  if (form.value.full_name.trim().length < 2) {
    error.value = 'El nombre debe tener al menos 2 caracteres.'
    return
  }
  saving.value = true
  try {
    const user = await updateMyProfile({
      full_name: form.value.full_name.trim(),
      // El teléfono vacío se envía como null: así se puede quitar.
      phone: form.value.phone.trim() === '' ? null : form.value.phone.trim(),
    })
    auth.user = user
    form.value = { full_name: user.full_name, phone: user.phone ?? '' }
    ui.pushToast('success', 'Perfil actualizado')
  } catch (err: unknown) {
    error.value = extractError(err, 'No se pudo guardar el perfil')
  } finally {
    saving.value = false
  }
}

// ── Cambio de contraseña ────────────────────────────────────────────────

const pwd = ref({ current: '', next: '', confirm: '' })
const pwdLoading = ref(false)
const pwdError = ref<string | null>(null)

async function changePassword(): Promise<void> {
  pwdError.value = null
  if (!pwd.value.current || !pwd.value.next || !pwd.value.confirm) {
    pwdError.value = 'Rellena todos los campos.'
    return
  }
  if (pwd.value.next !== pwd.value.confirm) {
    pwdError.value = 'La nueva contraseña no coincide.'
    return
  }
  if (pwd.value.next.length < 8) {
    pwdError.value = 'La nueva contraseña debe tener al menos 8 caracteres.'
    return
  }
  pwdLoading.value = true
  try {
    await auth.changeMyPassword(pwd.value.current, pwd.value.next)
    pwd.value = { current: '', next: '', confirm: '' }
    ui.pushToast('success', 'Contraseña actualizada')
  } catch (err: unknown) {
    pwdError.value = extractError(err, 'No se pudo cambiar la contraseña')
  } finally {
    pwdLoading.value = false
  }
}

const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrador',
  gestor: 'Gestor de parking',
  operador: 'Operador',
  cliente: 'Cliente',
}

function extractError(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail ?? anyErr.message ?? fallback
  }
  return fallback
}

onMounted(load)
</script>

<template>
  <AppLayout>
    <h1 class="text-2xl font-semibold tracking-tight mb-1">Mi perfil</h1>
    <p class="text-sm text-slate-500 mb-6">Datos personales y acceso a tu cuenta</p>

    <div v-if="loading" class="text-sm text-slate-500">Cargando…</div>

    <template v-else>
      <div class="grid gap-6 lg:grid-cols-2">
        <!-- Datos de perfil -->
        <section class="bg-white rounded-xl shadow-card p-5">
          <h2 class="font-semibold mb-4">Datos personales</h2>

          <form class="space-y-4" @submit.prevent="save">
            <div>
              <label class="block text-sm font-medium text-slate-700 mb-1" for="perfil-email">
                Correo electrónico
              </label>
              <input
                id="perfil-email"
                type="email"
                :value="auth.user?.email ?? ''"
                disabled
                class="w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500"
              />
              <p class="mt-1 text-xs text-slate-500">
                El correo es tu identidad de acceso: lo cambia el administrador.
              </p>
            </div>

            <div>
              <label class="block text-sm font-medium text-slate-700 mb-1" for="perfil-nombre">
                Nombre completo
              </label>
              <input
                id="perfil-nombre"
                v-model="form.full_name"
                type="text"
                maxlength="255"
                required
                :disabled="saving"
                class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-slate-700 mb-1" for="perfil-telefono">
                Teléfono
              </label>
              <input
                id="perfil-telefono"
                v-model="form.phone"
                type="tel"
                maxlength="32"
                placeholder="+34 600 000 000"
                :disabled="saving"
                class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
              />
              <p class="mt-1 text-xs text-slate-500">Déjalo vacío si no quieres teléfono.</p>
            </div>

            <div class="flex items-center gap-3 pt-1">
              <button
                type="submit"
                class="px-3 py-2 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                :disabled="saving"
              >
                {{ saving ? 'Guardando…' : 'Guardar cambios' }}
              </button>
              <span class="text-xs text-slate-500">
                Rol:
                {{ auth.user ? (ROLE_LABEL[auth.user.role] ?? auth.user.role) : '—' }}
              </span>
            </div>
          </form>
        </section>

        <!-- Contraseña -->
        <section class="bg-white rounded-xl shadow-card p-5">
          <h2 class="font-semibold mb-4">Contraseña</h2>

          <form class="space-y-4" @submit.prevent="changePassword">
            <div>
              <label class="block text-sm font-medium text-slate-700 mb-1" for="perfil-pwd-actual">
                Contraseña actual
              </label>
              <input
                id="perfil-pwd-actual"
                v-model="pwd.current"
                type="password"
                autocomplete="current-password"
                required
                :disabled="pwdLoading"
                class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-slate-700 mb-1" for="perfil-pwd-nueva">
                Nueva contraseña
              </label>
              <input
                id="perfil-pwd-nueva"
                v-model="pwd.next"
                type="password"
                autocomplete="new-password"
                required
                minlength="8"
                :disabled="pwdLoading"
                class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
              />
              <p class="mt-1 text-xs text-slate-500">Mínimo 8 caracteres.</p>
            </div>

            <div>
              <label class="block text-sm font-medium text-slate-700 mb-1" for="perfil-pwd-confirm">
                Confirmar nueva contraseña
              </label>
              <input
                id="perfil-pwd-confirm"
                v-model="pwd.confirm"
                type="password"
                autocomplete="new-password"
                required
                minlength="8"
                :disabled="pwdLoading"
                class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-slate-100"
              />
            </div>

            <p
              v-if="pwdError"
              class="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-md px-3 py-2"
              role="alert"
            >
              {{ pwdError }}
            </p>

            <div class="flex justify-end pt-1">
              <button
                type="submit"
                class="px-3 py-2 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                :disabled="pwdLoading"
              >
                {{ pwdLoading ? 'Guardando…' : 'Cambiar contraseña' }}
              </button>
            </div>
          </form>
        </section>
      </div>

      <p
        v-if="error"
        class="mt-4 text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-md px-3 py-2"
        role="alert"
      >
        {{ error }}
      </p>
    </template>
  </AppLayout>
</template>
