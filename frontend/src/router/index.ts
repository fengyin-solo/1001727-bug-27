import { createRouter, createWebHistory } from 'vue-router'

import Dashboard from '@/views/Dashboard.vue'
const Boiler = () => import('@/views/boiler/index.vue')
const Vessel = () => import('@/views/vessel/index.vue')
const Pressurepipe = () => import('@/views/pressurepipe/index.vue')
const Crane = () => import('@/views/crane/index.vue')
const Elevator = () => import('@/views/elevator/index.vue')
const Forklift = () => import('@/views/forklift/index.vue')
const Plan = () => import('@/views/plan/index.vue')
const Spotcheck = () => import('@/views/spotcheck/index.vue')
const Lubricate = () => import('@/views/lubricate/index.vue')
const Inspect = () => import('@/views/inspect/index.vue')
const Report = () => import('@/views/report/index.vue')
const Hazard = () => import('@/views/hazard/index.vue')
const Rectify = () => import('@/views/rectify/index.vue')
const Register = () => import('@/views/register/index.vue')
const Operator = () => import('@/views/operator/index.vue')
const Spare = () => import('@/views/spare/index.vue')
const Contract = () => import('@/views/contract/index.vue')
const Settle = () => import('@/views/settle/index.vue')
const Dispatch = () => import('@/views/dispatch/index.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/boiler', name: 'boiler', component: Boiler },
    { path: '/vessel', name: 'vessel', component: Vessel },
    { path: '/pressurepipe', name: 'pressurepipe', component: Pressurepipe },
    { path: '/crane', name: 'crane', component: Crane },
    { path: '/elevator', name: 'elevator', component: Elevator },
    { path: '/forklift', name: 'forklift', component: Forklift },
    { path: '/plan', name: 'plan', component: Plan },
    { path: '/spotcheck', name: 'spotcheck', component: Spotcheck },
    { path: '/lubricate', name: 'lubricate', component: Lubricate },
    { path: '/inspect', name: 'inspect', component: Inspect },
    { path: '/report', name: 'report', component: Report },
    { path: '/hazard', name: 'hazard', component: Hazard },
    { path: '/rectify', name: 'rectify', component: Rectify },
    { path: '/register', name: 'register', component: Register },
    { path: '/operator', name: 'operator', component: Operator },
    { path: '/spare', name: 'spare', component: Spare },
    { path: '/contract', name: 'contract', component: Contract },
    { path: '/settle', name: 'settle', component: Settle },
    { path: '/dispatch', name: 'dispatch', component: Dispatch },
  ],
})

export default router
