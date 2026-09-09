import { createRouter, createWebHistory } from 'vue-router'

import HomeView from '@/views/HomeView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/high-trends',
      name: 'high-trends',
      component: () => import('@/views/HighTrendsView.vue'),
    },
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
  ],
})
