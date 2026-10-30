import { createRouter, createWebHistory } from 'vue-router'

import HomeView from '@/views/HomeView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/trend-quality/review',
      name: 'trend-quality-review',
      component: () => import('@/views/TrendQualityReviewView.vue'),
    },
    {
      path: '/dna-v2',
      name: 'dna-v2',
      component: () => import('@/views/DnaV2View.vue'),
    },
    {
      path: '/article-trends',
      name: 'article-trends',
      component: () => import('@/views/ArticleTrendsView.vue'),
    },
    {
      path: '/high-trends/image-review',
      name: 'high-trend-image-review',
      component: () => import('@/views/HighTrendImageReviewView.vue'),
    },
    {
      path: '/high-trends',
      name: 'high-trends',
      component: () => import('@/views/HighTrendsView.vue'),
    },
    {
      path: '/moodboards',
      name: 'moodboards',
      component: () => import('@/views/MoodboardsView.vue'),
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

// 保留原始导航异常，并把懒加载故障交给独立提示；普通业务错误不会触发自动重载。
router.onError((error: Error) => {
  console.error(error)
  window.dispatchEvent(new CustomEvent('app:module-load-error', { detail: error.message }))
})

export default router
