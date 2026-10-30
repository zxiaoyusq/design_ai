<script setup lang="ts">
// 主导航统一维护模块名称与顺序，避免进入不同页面后入口不一致。
const modules = [
  { path: '/dna-v2', title: 'DNA提取V2' },
  { path: '/article-trends', title: '趋势洞察' },
  { path: '/user-research', title: '用户调研' },
  { path: '/high-trends', title: '高潜趋势' },
  { path: '/moodboards', title: '情绪版生成' },
] as const
</script>

<template>
  <nav aria-label="主导航">
    <RouterLink v-for="module in modules" :key="module.path" :to="module.path" active-class="active">
      {{ module.title }}
    </RouterLink>
  </nav>
</template>
