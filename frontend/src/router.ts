import { createRouter, createWebHistory } from 'vue-router'

import HomeView from '@/views/HomeView.vue'

export default createRouter({
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
