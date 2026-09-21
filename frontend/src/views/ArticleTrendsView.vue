<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowLeftOutlined, ArrowRightOutlined, BulbOutlined, LinkOutlined, SearchOutlined } from '@ant-design/icons-vue'

import { articleTrends } from '@/data/articleTrends'
import type { ArticleTrend } from '@/types/articleTrend'

const keyword = ref('')
const source = ref('')
const category = ref('')
const subcategory = ref('')
const startDate = ref('')
const endDate = ref('')
const sortOrder = ref<'newest' | 'oldest'>('newest')
const selectedId = ref(articleTrends[0]?.id ?? '')
const selectedImageIndex = ref(0)
const previewOpen = ref(false)
const previewIndex = ref(0)
const detailPanel = ref<HTMLElement | null>(null)

function sourceName(article: ArticleTrend) {
  if (!article.sourceUrl) return '来源未提供'
  try {
    return new URL(article.sourceUrl).hostname.replace(/^www\./, '')
  } catch {
    return article.sourceUrl
  }
}

const sources = [...new Set(articleTrends.map(sourceName))].sort()
const categories = [...new Set(articleTrends.map(article => article.category).filter((value): value is string => Boolean(value)))].sort()
const subcategories = computed(() => [...new Set(articleTrends
  .filter(article => !category.value || article.category === category.value)
  .flatMap(article => article.subcategories))].sort())

watch(category, () => { subcategory.value = '' })

const invalidDateRange = computed(() => Boolean(startDate.value && endDate.value && startDate.value > endDate.value))
const filteredArticles = computed(() => {
  if (invalidDateRange.value) return []
  const query = keyword.value.trim().toLocaleLowerCase()
  const matches = articleTrends.filter(article => {
    if (source.value && sourceName(article) !== source.value) return false
    if (category.value && article.category !== category.value) return false
    if (subcategory.value && !article.subcategories.includes(subcategory.value)) return false
    if (startDate.value && article.releaseDate < startDate.value) return false
    if (endDate.value && article.releaseDate > endDate.value) return false
    if (!query) return true
    return [article.title, article.originalTitle, article.summary, article.category, ...article.subcategories, ...article.tags]
      .some(value => value?.toLocaleLowerCase().includes(query))
  })
  return sortOrder.value === 'newest' ? matches : matches.reverse()
})

// 筛选后若原选中项不可见，详情同步切到首条，避免列表与右侧内容不一致。
watch(filteredArticles, articles => {
  if (articles.some(article => article.id === selectedId.value)) return
  selectedId.value = articles[0]?.id ?? ''
  selectedImageIndex.value = 0
  previewOpen.value = false
})

const selectedArticle = computed(() => filteredArticles.value.find(article => article.id === selectedId.value) ?? null)
const selectedImage = computed(() => selectedArticle.value?.images[selectedImageIndex.value] ?? '')

function selectArticle(article: ArticleTrend) {
  selectedId.value = article.id
  selectedImageIndex.value = 0
  previewOpen.value = false
  if (window.matchMedia('(max-width: 700px)').matches) {
    void nextTick(() => detailPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
}

function resetFilters() {
  keyword.value = ''
  source.value = ''
  category.value = ''
  subcategory.value = ''
  startDate.value = ''
  endDate.value = ''
  sortOrder.value = 'newest'
}

function showImage(index: number) {
  selectedImageIndex.value = index
  previewIndex.value = index
  previewOpen.value = true
}

function movePreview(step: number) {
  const count = selectedArticle.value?.images.length ?? 0
  if (count) {
    previewIndex.value = (previewIndex.value + step + count) % count
    selectedImageIndex.value = previewIndex.value
  }
}
</script>

<template>
  <div class="app-shell article-shell">
    <div class="ambient ambient-one"></div><div class="ambient ambient-two"></div>
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="用户审美洞察与趋势捕捉首页"><span class="brand-mark"><span></span></span><span class="brand-copy"><strong>用户审美洞察与趋势捕捉</strong></span></RouterLink>
      <nav aria-label="主导航"><RouterLink to="/">DNA 提取</RouterLink><RouterLink class="active" to="/article-trends">趋势洞察</RouterLink><RouterLink to="/high-trends">高潜趋势</RouterLink><RouterLink to="/design-modification">设计修改</RouterLink><RouterLink to="/user-research">用研聚合</RouterLink><RouterLink to="/projects">我的项目</RouterLink></nav>
      <div class="system-state"><span></span> 审美洞察工作台</div>
    </header>

    <main>
      <section class="hero article-hero">
        <div class="hero-badge"><BulbOutlined /> TREND LIBRARY</div>
        <p>浏览文章中的设计趋势，查看原文摘要与关联图片。</p>
      </section>

      <section class="filter-panel" aria-label="文章筛选">
        <div class="filter-field keyword-field"><label for="article-keyword">关键词</label><div class="search-input"><SearchOutlined /><input id="article-keyword" v-model="keyword" type="search" placeholder="搜索标题、摘要或标签" /></div></div>
        <div class="filter-field"><label for="article-source">来源</label><select id="article-source" v-model="source"><option value="">全部来源</option><option v-for="item in sources" :key="item" :value="item">{{ item }}</option></select></div>
        <div class="filter-field"><label for="article-category">一级分类</label><select id="article-category" v-model="category"><option value="">全部分类</option><option v-for="item in categories" :key="item" :value="item">{{ item }}</option></select></div>
        <div class="filter-field"><label for="article-subcategory">二级分类</label><select id="article-subcategory" v-model="subcategory"><option value="">全部子分类</option><option v-for="item in subcategories" :key="item" :value="item">{{ item }}</option></select></div>
        <div class="filter-field date-field"><label for="article-start">发布日期起</label><input id="article-start" v-model="startDate" type="date" :max="endDate || undefined" /></div>
        <div class="filter-field date-field"><label for="article-end">发布日期止</label><input id="article-end" v-model="endDate" type="date" :min="startDate || undefined" /></div>
        <button class="reset-button" type="button" @click="resetFilters">重置</button>
        <p v-if="invalidDateRange" class="date-error">开始日期不能晚于结束日期。</p>
      </section>

      <section class="article-layout">
        <div class="article-list">
          <div class="list-heading">
            <div><h1>趋势列表 <span>{{ filteredArticles.length }} / {{ articleTrends.length }}</span></h1><p>按发布日期选取最近 {{ articleTrends.length }} 篇文章</p></div>
            <div class="sort-controls" aria-label="排序方式"><button type="button" :class="{ active: sortOrder === 'newest' }" :aria-pressed="sortOrder === 'newest'" @click="sortOrder = 'newest'">最新优先</button><button type="button" :class="{ active: sortOrder === 'oldest' }" :aria-pressed="sortOrder === 'oldest'" @click="sortOrder = 'oldest'">最早优先</button></div>
          </div>
          <div v-if="filteredArticles.length" class="article-grid">
            <button v-for="article in filteredArticles" :key="article.id" class="article-card" :class="{ selected: selectedId === article.id }" type="button" :aria-pressed="selectedId === article.id" @click="selectArticle(article)">
              <div class="card-image"><img v-if="article.images[0]" :src="article.images[0]" :alt="article.title" loading="lazy" /><span v-else>暂无图片</span></div>
              <div class="card-content"><span class="card-category">{{ article.category || '未分类' }}</span><h2>{{ article.title }}</h2><div class="card-tags"><span v-for="tag in article.tags.slice(0, 3)" :key="tag">{{ tag }}</span></div><div class="card-meta"><span>{{ sourceName(article) }}</span><time :datetime="article.releaseDate">{{ article.releaseDate }}</time></div></div>
            </button>
          </div>
          <div v-else class="empty-state"><SearchOutlined /><p>没有符合条件的文章</p><button type="button" @click="resetFilters">清除筛选</button></div>
        </div>

        <aside ref="detailPanel" class="detail-panel" aria-label="趋势详情">
          <template v-if="selectedArticle">
            <div class="detail-heading"><div><span class="eyebrow">TREND DETAIL</span><h2>趋势详情</h2></div><a v-if="selectedArticle.detailUrl" :href="selectedArticle.detailUrl" target="_blank" rel="noopener noreferrer" aria-label="打开文章原文" title="打开文章原文"><LinkOutlined /></a></div>
            <div class="detail-content">
              <button v-if="selectedImage" class="featured-image" type="button" aria-label="放大查看当前图片" @click="showImage(selectedImageIndex)"><img :src="selectedImage" :alt="`${selectedArticle.title}，图片 ${selectedImageIndex + 1}`" /></button>
              <div class="detail-title-block"><p class="detail-overline">{{ selectedArticle.category || '未分类' }} · {{ sourceName(selectedArticle) }}</p><h3>{{ selectedArticle.title }}</h3><p v-if="selectedArticle.originalTitle && selectedArticle.originalTitle !== selectedArticle.title" class="original-title">{{ selectedArticle.originalTitle }}</p><time :datetime="selectedArticle.releaseDate">发布于 {{ selectedArticle.releaseDate }}</time></div>
              <div class="detail-section"><h4>趋势描述</h4><p class="summary">{{ selectedArticle.summary || '源表未提供摘要。' }}</p></div>
              <div v-if="selectedArticle.subcategories.length" class="detail-section"><h4>二级分类</h4><div class="detail-tags"><span v-for="item in selectedArticle.subcategories" :key="item">{{ item }}</span></div></div>
              <div v-if="selectedArticle.tags.length" class="detail-section"><h4>特征标签</h4><div class="detail-tags"><span v-for="tag in selectedArticle.tags" :key="tag">{{ tag }}</span></div></div>
              <div v-if="selectedArticle.images.length" class="detail-section"><h4>关联图片 <span>{{ selectedArticle.images.length }} 张</span></h4><div class="image-grid"><button v-for="(image, index) in selectedArticle.images" :key="image" type="button" :class="{ active: selectedImageIndex === index }" :aria-label="`查看第 ${index + 1} 张图片`" @click="selectedImageIndex = index"><img :src="image" :alt="`${selectedArticle.title}，图片 ${index + 1}`" loading="lazy" /></button></div></div>
              <p class="source-note">文章 ID {{ selectedArticle.id }} · 表格第 {{ selectedArticle.sourceRow }} 行</p>
            </div>
            <div class="detail-footer"><a v-if="selectedArticle.detailUrl" :href="selectedArticle.detailUrl" target="_blank" rel="noopener noreferrer">阅读原文 <ArrowRightOutlined /></a><a v-else-if="selectedArticle.sourceUrl" :href="selectedArticle.sourceUrl" target="_blank" rel="noopener noreferrer">查看来源 <ArrowRightOutlined /></a></div>
          </template>
          <div v-else class="detail-empty">选择一篇文章查看详情</div>
        </aside>
      </section>
    </main>
    <footer><span>用户审美洞察与趋势捕捉 · AI 审美洞察平台</span><span>文章内容与图片来自本地资料</span></footer>

    <a-modal v-model:open="previewOpen" class="article-image-modal" :footer="null" centered :width="960" :title="selectedArticle?.title">
      <div v-if="selectedArticle" class="preview-content" :class="{ 'single-image': selectedArticle.images.length === 1 }"><button v-if="selectedArticle.images.length > 1" type="button" aria-label="上一张图片" @click="movePreview(-1)"><ArrowLeftOutlined /></button><img :src="selectedArticle.images[previewIndex]" :alt="`${selectedArticle.title}，图片 ${previewIndex + 1}`" /><button v-if="selectedArticle.images.length > 1" type="button" aria-label="下一张图片" @click="movePreview(1)"><ArrowRightOutlined /></button></div>
      <p v-if="selectedArticle" class="preview-count">{{ previewIndex + 1 }} / {{ selectedArticle.images.length }}</p>
    </a-modal>
  </div>
</template>

<style scoped>
.article-hero { padding: 62px 0 34px; }
.article-hero p { margin: 14px 0 0; color: var(--muted); font-size: 14px; }
.filter-panel { display: grid; grid-template-columns: minmax(210px, 1.5fr) repeat(3, minmax(120px, 1fr)) repeat(2, minmax(130px, 1fr)) auto; gap: 12px; align-items: end; padding: 20px; background: var(--card); border: 1px solid var(--line); border-radius: 20px; box-shadow: 0 12px 38px rgba(53, 44, 105, .06); }
.filter-field { display: grid; gap: 7px; min-width: 0; }
.filter-field label { color: #867d94; font-size: 11px; }
.filter-field input, .filter-field select { width: 100%; min-width: 0; height: 38px; padding: 0 10px; color: #4b405b; background: #fcfbfe; border: 1px solid #e6e0ed; border-radius: 9px; font-size: 12px; }
.filter-field input:focus, .filter-field select:focus { outline: 2px solid #bbb0ed; outline-offset: 1px; }
.search-input { position: relative; }
.search-input :deep(.anticon) { position: absolute; top: 12px; left: 11px; color: #a199ae; }
.search-input input { padding-left: 32px; }
.reset-button { height: 38px; padding: 0 14px; color: #695b8a; background: #f2eef9; border: 0; border-radius: 9px; cursor: pointer; font-size: 12px; }
.reset-button:hover { background: #e9e2f6; }
.date-error { grid-column: 1 / -1; margin: 0; color: #ae5260; font-size: 12px; }
.article-layout { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 20px; align-items: start; margin: 28px 0 65px; }
.article-list { min-width: 0; }
.list-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 0 0 14px; }
.list-heading h1 { margin: 0; color: #342c47; font-size: 18px; }
.list-heading h1 span { margin-left: 7px; color: #9e93ad; font-size: 13px; font-weight: 400; }
.list-heading p { margin: 5px 0 0; color: #9e93ad; font-size: 11px; }
.sort-controls { display: flex; flex-shrink: 0; gap: 3px; padding: 3px; background: #edeaf3; border-radius: 10px; }
.sort-controls button { padding: 7px 10px; color: #8b819c; background: transparent; border: 0; border-radius: 7px; cursor: pointer; font-size: 11px; }
.sort-controls button.active { color: #58449e; background: white; box-shadow: 0 2px 8px rgba(53, 44, 105, .08); }
.article-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.article-card { overflow: hidden; min-width: 0; padding: 0; text-align: left; background: white; border: 1px solid #e8e2ee; border-radius: 16px; box-shadow: 0 8px 26px rgba(53, 44, 105, .04); cursor: pointer; transition: transform .2s, border-color .2s, box-shadow .2s; }
.article-card:hover { transform: translateY(-3px); box-shadow: 0 12px 28px rgba(53, 44, 105, .1); }
.article-card.selected { border-color: #8e7adf; box-shadow: 0 0 0 2px rgba(98, 87, 216, .13); }
.card-image { height: 165px; background: #eeeaf3; color: var(--muted); display: grid; place-items: center; }
.card-image img { width: 100%; height: 100%; object-fit: cover; }
.card-content { padding: 14px 15px 15px; }
.card-category { color: #6953a5; font-size: 10px; }
.card-content h2 { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; min-height: 40px; margin: 7px 0 10px; color: #342c47; font-size: 13px; font-weight: 600; line-height: 1.5; }
.card-tags, .detail-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.card-tags { min-height: 23px; }
.card-tags span, .detail-tags span { padding: 4px 8px; color: #725f91; background: #f2eef8; border-radius: 7px; font-size: 10px; }
.card-meta { display: flex; justify-content: space-between; gap: 5px; margin-top: 12px; padding-top: 10px; border-top: 1px solid #f0edf3; color: #9c93a8; font-size: 10px; }
.card-meta span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.card-meta time { flex-shrink: 0; }
.detail-panel { position: sticky; top: 18px; display: flex; flex-direction: column; max-height: calc(100vh - 36px); overflow: hidden; background: white; border: 1px solid #e7e1ee; border-radius: 18px; box-shadow: 0 12px 38px rgba(53, 44, 105, .07); }
.detail-heading { display: flex; justify-content: space-between; align-items: center; padding: 17px 18px; border-bottom: 1px solid #eee8f3; }
.detail-heading .eyebrow { color: #a692c4; font-size: 9px; letter-spacing: .12em; }
.detail-heading h2 { margin: 4px 0 0; color: #3c3052; font-size: 16px; }
.detail-heading a { display: grid; width: 30px; height: 30px; place-items: center; color: #7663aa; background: #f3eff9; border-radius: 8px; }
.detail-content { overflow-y: auto; padding: 18px; }
.featured-image { display: block; overflow: hidden; width: 100%; height: 210px; padding: 0; background: #f1edf6; border: 0; border-radius: 12px; cursor: zoom-in; }
.featured-image img { width: 100%; height: 100%; object-fit: contain; }
.detail-title-block { padding: 16px 0 19px; border-bottom: 1px solid #f0edf3; }
.detail-overline { margin: 0 0 8px; color: #765db5; font-size: 10px; }
.detail-title-block h3 { margin: 0; color: #332943; font-size: 17px; line-height: 1.55; }
.original-title { margin: 8px 0 0; color: #968d9d; font-size: 11px; line-height: 1.6; }
.detail-title-block time { display: block; margin-top: 10px; color: #a69cad; font-size: 10px; }
.detail-section { margin-top: 19px; }
.detail-section h4 { margin: 0 0 9px; color: #8a7d9b; font-size: 11px; font-weight: 500; }
.detail-section h4 span { color: #ada3b8; }
.summary { margin: 0; color: #5d5368; font-size: 12px; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }
.image-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; }
.image-grid button { aspect-ratio: 1; overflow: hidden; padding: 0; background: #f1edf6; border: 2px solid transparent; border-radius: 7px; cursor: pointer; }
.image-grid button.active { border-color: #8e7adf; }
.image-grid img { width: 100%; height: 100%; object-fit: cover; }
.source-note { margin: 20px 0 0; color: #aaa0b1; font-size: 10px; }
.detail-footer { padding: 13px 18px; border-top: 1px solid #eee8f3; }
.detail-footer a { display: flex; justify-content: center; align-items: center; gap: 8px; width: 100%; padding: 10px; color: white; background: #6257d8; border-radius: 9px; text-decoration: none; font-size: 12px; }
.detail-footer a:hover { background: #453aa9; }
.detail-empty, .empty-state { display: grid; justify-items: center; gap: 10px; padding: 65px 20px; color: #9c91aa; text-align: center; }
.empty-state { background: white; border: 1px dashed #d9d0e3; border-radius: 16px; }
.empty-state p { margin: 0; }
.empty-state button { color: #6257d8; background: none; border: 0; cursor: pointer; }
.preview-content { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; }
.preview-content.single-image { display: block; }
.preview-content img { display: block; width: 100%; max-height: 72vh; object-fit: contain; }
.preview-content button { width: 34px; height: 34px; color: #6257d8; background: #f2eef9; border: 0; border-radius: 50%; cursor: pointer; }
.preview-count { margin: 10px 0 0; color: #8f859d; font-size: 11px; text-align: center; }
@media (max-width: 1100px) { .filter-panel { grid-template-columns: repeat(3, minmax(0, 1fr)); } .keyword-field { grid-column: span 2; } .reset-button { width: fit-content; } }
@media (max-width: 900px) { .article-layout { grid-template-columns: minmax(0, 1fr) 320px; } .article-grid { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .article-hero { padding-top: 42px; } .filter-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); } .keyword-field { grid-column: 1 / -1; } .article-layout { grid-template-columns: 1fr; } .article-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .detail-panel { position: static; max-height: none; } .detail-content { overflow: visible; } }
@media (max-width: 520px) { .article-grid { grid-template-columns: 1fr; } .filter-panel { padding: 15px; } .list-heading { align-items: flex-start; } .sort-controls button { padding: 6px; } }
</style>
