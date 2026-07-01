/**
 * Router principal con guard de autenticación + RBAC.
 * Cada ruta declara los roles permitidos en `meta.roles`; el guard
 * redirige a /login si no hay sesión y a /forbidden si el rol no encaja.
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, layout: 'blank' },
  },
  // Sprint Fase 4 (2026-07-01): redirect por rol en vez de llevar
  // siempre a /dashboard (admin-only → "Acceso denegado" para gestor/
  // operador/cliente).
  {
    path: '/',
    redirect: () => {
      const auth = useAuthStore()
      switch (auth.role) {
        case 'admin':    return { name: 'dashboard' }
        case 'gestor':   return { name: 'gestor-map' }
        case 'operador': return { name: 'operador-live' }
        case 'cliente':  return { name: 'cliente-tickets' }
        default:         return { name: 'login' }
      }
    },
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/admin/DashboardView.vue'),
    meta: { roles: ['admin'] },
  },
  {
    path: '/dashboard/gestor',
    name: 'gestor-dashboard',
    component: () => import('@/views/gestor/DashboardGestor.vue'),
    meta: { roles: ['admin', 'gestor'] },
  },
  {
    path: '/admin/parkings',
    name: 'admin-parkings',
    component: () => import('@/views/admin/ParkingsView.vue'),
    meta: { roles: ['admin'] },
  },
  {
    path: '/admin/users',
    name: 'admin-users',
    component: () => import('@/views/admin/UsersView.vue'),
    meta: { roles: ['admin'] },
  },
  {
    path: '/admin/tariffs',
    name: 'admin-tariffs',
    component: () => import('@/views/admin/TariffsView.vue'),
    meta: { roles: ['admin'] },
  },
  {
    path: '/mapa',
    name: 'gestor-map',
    component: () => import('@/views/gestor/MapView.vue'),
    meta: { roles: ['admin', 'gestor'] },
  },
  {
    path: '/cameras',
    name: 'gestor-cameras',
    component: () => import('@/views/gestor/CamerasView.vue'),
    meta: { roles: ['admin', 'gestor'] },
  },
  {
    path: '/calibrate/:parkingId/:cameraId',
    name: 'gestor-calibrate',
    component: () => import('@/views/gestor/CalibrateView.vue'),
    meta: { roles: ['admin', 'gestor'] },
  },
  {
    path: '/vivo',
    name: 'operador-live',
    component: () => import('@/views/operador/LiveView.vue'),
    meta: { roles: ['admin', 'gestor', 'operador'] },
  },
  {
    path: '/operador/alta-manual',
    name: 'operador-manual',
    component: () => import('@/views/operador/ManualEntryView.vue'),
    meta: { roles: ['admin', 'gestor', 'operador'] },
  },
  {
    path: '/mis-tickets',
    name: 'cliente-tickets',
    component: () => import('@/views/cliente/TicketsView.vue'),
    meta: { roles: ['admin', 'cliente'] },
  },
  {
    path: '/forbidden',
    name: 'forbidden',
    component: () => import('@/views/ForbiddenView.vue'),
    meta: { public: true, layout: 'blank' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { public: true, layout: 'blank' },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  const allowed = to.meta.roles as string[] | undefined
  if (allowed && auth.role && !allowed.includes(auth.role)) {
    return { name: 'forbidden' }
  }
  return true
})