/**
 * Router principal con guard de autenticación + RBAC.
 * Cada ruta declara los roles permitidos en `meta.roles`; el guard
 * redirige a /login si no hay sesión y a /forbidden si el rol no encaja.
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { isPwaMode } from '@/pwa/mode'
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
  // Sprint UI Costes + Reportería + Dashboard KPIs (2026-07-06):
  // CRUD de costes operativos y reporte de margen salen del dashboard
  // y pasan a vistas dedicadas accesibles desde el sidebar.
  {
    path: '/admin/costs',
    name: 'admin-costs',
    component: () => import('@/views/admin/CostsView.vue'),
    meta: { roles: ['admin'] },
  },
  {
    path: '/admin/reports',
    name: 'admin-reports',
    component: () => import('@/views/admin/ReportsView.vue'),
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
  // T-19 (2026-10-21): "Mis vehículos" y "Mi perfil" del cliente.
  // El guard por rol es el de siempre: ``meta.roles`` + redirección a
  // /forbidden si el rol no encaja.
  {
    path: '/mis-vehiculos',
    name: 'cliente-vehiculos',
    component: () => import('@/views/cliente/VehiclesView.vue'),
    meta: { roles: ['admin', 'cliente'] },
  },
  {
    path: '/mi-perfil',
    name: 'cliente-perfil',
    component: () => import('@/views/cliente/ProfileView.vue'),
    meta: { roles: ['admin', 'cliente'] },
  },
  // T-20 (2026-10-21): log de entradas/salidas, alertas activas y
  // operadores del gestor.
  {
    path: '/gestor/movimientos',
    name: 'gestor-movimientos',
    component: () => import('@/views/gestor/MovementsView.vue'),
    meta: { roles: ['admin', 'gestor'] },
  },
  {
    path: '/gestor/alertas',
    name: 'gestor-alertas',
    component: () => import('@/views/gestor/AlertsView.vue'),
    meta: { roles: ['admin', 'gestor'] },
  },
  {
    path: '/gestor/operadores',
    name: 'gestor-operadores',
    component: () => import('@/views/gestor/OperatorsView.vue'),
    meta: { roles: ['admin', 'gestor'] },
  },
  // T-18 (2026-10-21): CRUD de planes y suscripciones (admin).
  {
    path: '/admin/planes',
    name: 'admin-planes',
    component: () => import('@/views/admin/PlansView.vue'),
    meta: { roles: ['admin'] },
  },
  // T-18 (2026-10-21): "Mi plan" del cliente (plan, alta/vencimiento,
  // % de descuento y próximo cobro contable).
  {
    path: '/mi-plan',
    name: 'cliente-plan',
    component: () => import('@/views/cliente/MyPlanView.vue'),
    meta: { roles: ['admin', 'cliente'] },
  },
  // T-24 (2026-10-21): plaza asignada y pagos pendientes del cliente
  // (pantallas de la PWA instalable).
  {
    path: '/mi-plaza',
    name: 'cliente-plazas',
    component: () => import('@/views/cliente/MySpotView.vue'),
    meta: { roles: ['admin', 'cliente'] },
  },
  {
    path: '/pagos',
    name: 'cliente-pagos',
    component: () => import('@/views/cliente/PaymentsView.vue'),
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
  // T-24 (2026-10-21): la PWA instalada es **sólo para el cliente**
  // (decisión D4: un solo codebase, instalable, sin tiendas). Dentro de
  // ella, cualquier ruta que no sea del cliente se redirige a "Mis
  // tickets" en vez de dejar al usuario en una pantalla de gestión.
  // Se comparan nombres de ruta (no paths) para no depender del prefijo.
  if (
    isPwaMode() &&
    typeof to.name === 'string' &&
    !to.name.startsWith('cliente-') &&
    to.name !== 'login'
  ) {
    return { name: 'cliente-tickets' }
  }
  return true
})