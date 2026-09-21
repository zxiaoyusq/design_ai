import { createRouter, createWebHistory } from 'vue-router'

import HomeView from '@/views/HomeView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/article-trends',
      name: 'article-trends',
      component: () => import('@/views/ArticleTrendsView.vue'),
    },
    {
      path: '/high-trends',
      name: 'high-trends',
      component: () => import('@/views/HighTrendsView.vue'),
    },
    {
      path: '/design-modification',
      name: 'design-modification',
      component: () => import('@/views/DesignModificationView.vue'),
    },
    {
      path: '/user-research',
      name: 'user-research',
      component: () => import('@/views/UserResearchView.vue'),
    },
    {
      path: '/projects',
      name: 'projects',
      component: () => import('@/views/ProjectsView.vue'),
    },
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
  ],
})
