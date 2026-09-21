<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowRightOutlined, PictureOutlined, SearchOutlined, TeamOutlined } from '@ant-design/icons-vue'

import { researchCohorts, researchImages, researchMethod, researchUsers } from '@/data/userResearch'
import type { ResearchCohort, ResearchUser } from '@/types/userResearch'

type Tab = 'overview' | 'gallery' | 'users'
const activeTab = ref<Tab>('overview')
const activeCohortId = ref(researchCohorts[0]?.id ?? '')
const userFilter = ref('')
const keyword = ref('')
const selectedUserId = ref(researchUsers[0]?.id ?? '')
const previewImageId = ref('')
const detailPanel = ref<HTMLElement | null>(null)

const photoUserCount = researchUsers.filter(user => user.enjoyCount > 0).length
const activeCohort = computed(() => researchCohorts.find(group => group.id === activeCohortId.value) ?? researchCohorts[0]!)
const filteredUsers = computed(() => {
  const query = keyword.value.trim().toLocaleLowerCase()
  return researchUsers.filter(user => {
    if (userFilter.value && user.cohortId !== userFilter.value) return false
    return !query || [user.id, user.bid, user.country, user.profession, user.phoneBrand]
      .some(value => value.toLocaleLowerCase().includes(query))
  })
})
watch(filteredUsers, users => {
  if (!users.some(user => user.id === selectedUserId.value)) selectedUserId.value = users[0]?.id ?? ''
})
const selectedUser = computed(() => filteredUsers.value.find(user => user.id === selectedUserId.value) ?? null)
const selectedUserCohort = computed(() => researchCohorts.find(group => group.id === selectedUser.value?.cohortId))
const previewImage = computed(() => researchImages[previewImageId.value])

function countryLabel(value: string) {
  return ({ Indonesia: '印尼', Malaysia: '马来西亚', Pakistan: '巴基斯坦', India: '印度' } as Record<string, string>)[value] ?? value
}

function genderLabel(value: string) {
  return ({ male: '男', female: '女' } as Record<string, string>)[value] ?? value
}

function cellTone(count: number, total: number) {
  const share = total ? count / total : 0
  if (share >= 0.65) return 'heart'
  if (share >= 0.35) return 'strong'
  if (share > 0) return 'medium'
  return 'empty'
}

function openCohort(group: ResearchCohort) {
  activeCohortId.value = group.id
  activeTab.value = 'gallery'
}

function showCohortUsers() {
  userFilter.value = activeCohortId.value
  keyword.value = ''
  activeTab.value = 'users'
}

function selectUser(user: ResearchUser) {
  selectedUserId.value = user.id
  if (window.matchMedia('(max-width: 780px)').matches) {
    void nextTick(() => detailPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
}
</script>

<template>
  <div class="app-shell research-shell">
    <div class="ambient ambient-one"></div><div class="ambient ambient-two"></div>
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="用户审美洞察与趋势捕捉首页"><span class="brand-mark"><span></span></span><span class="brand-copy"><strong>用户审美洞察与趋势捕捉</strong></span></RouterLink>
      <nav aria-label="主导航"><RouterLink to="/">DNA 提取</RouterLink><RouterLink to="/article-trends">趋势洞察</RouterLink><RouterLink to="/high-trends">高潜趋势</RouterLink><RouterLink to="/design-modification">设计修改</RouterLink><RouterLink class="active" to="/user-research">用研聚合</RouterLink><RouterLink to="/projects">我的项目</RouterLink></nav>
      <div class="system-state"><span></span> 审美洞察工作台</div>
    </header>

    <main>
      <section class="hero research-hero">
        <div><span class="hero-badge"><TeamOutlined /> USER RESEARCH</span><h1>用研聚合</h1><p>从本地用研记录查看人群分组、图片偏好与原始摘录。</p></div>
        <div class="sample-stats" aria-label="样本概况">
          <div><strong>{{ researchUsers.length }}</strong><span>位用户</span></div>
          <div><strong>{{ photoUserCount }}</strong><span>位有 ENJOY 图片</span></div>
          <div><strong>{{ researchCohorts.length }}</strong><span>个人群组</span></div>
        </div>
      </section>

      <div class="method-note"><span class="method-dot"></span><span>演示数据 · {{ researchMethod }} 图片只展示该组成员标记为 ENJOY 的本地原图。分组不代表已验证的视觉风格。</span></div>

      <div class="research-tabs" role="tablist" aria-label="用研视图">
        <button type="button" role="tab" :aria-selected="activeTab === 'overview'" :class="{ active: activeTab === 'overview' }" @click="activeTab = 'overview'">聚类概览</button>
        <button type="button" role="tab" :aria-selected="activeTab === 'gallery'" :class="{ active: activeTab === 'gallery' }" @click="activeTab = 'gallery'">偏好图片</button>
        <button type="button" role="tab" :aria-selected="activeTab === 'users'" :class="{ active: activeTab === 'users' }" @click="activeTab = 'users'">用户记录</button>
      </div>

      <section v-if="activeTab === 'overview'" class="tab-body" aria-label="聚类概览">
        <div class="section-heading">
          <div><span class="eyebrow">COHORT × IMAGE SET</span><h2>人群偏好矩阵</h2><p>单元格为本组喜欢该列任一图片的用户数；列图集取对应人群的高频 ENJOY 图片。</p></div>
        </div>
        <div class="matrix-scroll">
          <table class="matrix-table">
            <thead>
              <tr>
                <th scope="col">人群 / 偏好图集</th>
                <th v-for="(topic, index) in researchCohorts.slice(0, 4)" :key="topic.id" scope="col">
                  <button type="button" class="matrix-topic" @click="openCohort(topic)">
                    <span class="topic-images"><img v-for="imageId in topic.imageIds.slice(0, 3)" :key="imageId" :src="researchImages[imageId]?.src" alt="" loading="lazy" /></span>
                    <span>图集 {{ String(index + 1).padStart(2, '0') }}</span>
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="group in researchCohorts" :key="group.id">
                <th scope="row"><button type="button" class="matrix-row-button" @click="openCohort(group)"><strong>{{ group.name }}</strong><small>{{ group.userIds.length }} 位用户</small></button></th>
                <td v-for="(count, index) in group.overlaps" :key="index">
                  <button type="button" class="matrix-cell" :aria-label="`${group.name}：${count} / ${group.userIds.length} 位用户喜欢图集 ${index + 1}`" @click="openCohort(group)">
                    <span class="matrix-symbol" :class="cellTone(count, group.userIds.length)">{{ cellTone(count, group.userIds.length) === 'heart' ? '♥' : '●' }}</span>
                    <small>{{ count }} / {{ group.userIds.length }}</small>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="matrix-legend"><span><i class="legend-heart">♥</i> 高共现 ≥65%</span><span><i class="legend-strong">●</i> 中等共现 ≥35%</span><span><i class="legend-medium">●</i> 少量共现</span><span><i class="legend-empty">●</i> 无该图集反馈</span></p>

        <div class="section-heading cards-heading"><div><span class="eyebrow">COHORTS</span><h2>人群组概览</h2><p>点击卡片查看本组喜欢的图片及成员。</p></div></div>
        <div class="cohort-grid">
          <button v-for="(group, index) in researchCohorts" :key="group.id" type="button" class="cohort-card" @click="openCohort(group)">
            <div class="cohort-card-top"><span class="cohort-number">{{ String(index + 1).padStart(2, '0') }}</span><span class="cohort-country">{{ group.country === 'Pakistan / India' ? '巴基斯坦 / 印度' : countryLabel(group.country) }}</span></div>
            <h3>{{ group.name }}</h3>
            <p>{{ group.userIds.length }} 位用户 · {{ group.enjoyCount }} 条 ENJOY 反馈</p>
            <div v-if="group.imageIds.length" class="cohort-thumbs"><img v-for="imageId in group.imageIds.slice(0, 4)" :key="imageId" :src="researchImages[imageId]?.src" :alt="`${group.name} 喜欢的图片`" loading="lazy" /></div>
            <div v-else class="no-thumbs">这些用户暂无 ENJOY 图片反馈</div>
            <span class="card-link">查看偏好图片 <ArrowRightOutlined /></span>
          </button>
        </div>
      </section>

      <section v-else-if="activeTab === 'gallery'" class="tab-body" aria-label="偏好图片">
        <div class="section-heading gallery-heading">
          <div><span class="eyebrow">ENJOY IMAGE GALLERY</span><h2>人群偏好图片</h2><p>按组内不同用户标记 ENJOY 的人数排序；点击图片查看原图。</p></div>
          <label class="select-label">选择人群<select v-model="activeCohortId"><option v-for="group in researchCohorts" :key="group.id" :value="group.id">{{ group.name }}</option></select></label>
        </div>
        <div class="gallery-summary">
          <div><span class="cohort-number">{{ String(researchCohorts.indexOf(activeCohort) + 1).padStart(2, '0') }}</span><div><h3>{{ activeCohort.name }}</h3><p>{{ activeCohort.userIds.length }} 位用户 · {{ activeCohort.enjoyCount }} 条 ENJOY 反馈</p></div></div>
          <button type="button" @click="showCohortUsers">查看组内用户 <ArrowRightOutlined /></button>
        </div>
        <div v-if="activeCohort.imageIds.length" class="gallery-grid">
          <button v-for="imageId in activeCohort.imageIds" :key="imageId" type="button" class="gallery-card" @click="previewImageId = imageId">
            <span class="gallery-image"><img :src="researchImages[imageId]?.src" :alt="`${activeCohort.name} 的 ENJOY 图片 ${imageId}`" loading="lazy" /></span>
            <span class="gallery-caption"><span>{{ activeCohort.imageVotes[imageId] }} 位组内用户 ENJOY</span><small>{{ imageId }}</small></span>
          </button>
        </div>
        <div v-else class="empty-gallery"><PictureOutlined /><h3>暂无 ENJOY 图片</h3><p>这组保留访谈记录，可在用户记录中查看原文摘录。</p><button type="button" @click="showCohortUsers">查看用户记录</button></div>
      </section>

      <section v-else class="tab-body" aria-label="用户记录">
        <div class="section-heading"><div><span class="eyebrow">SOURCE RECORDS</span><h2>用户记录</h2><p>仅展示本次选中的 50 位用户；图片与摘录均可回查源 ID。</p></div></div>
        <div class="user-controls"><label class="select-label">人群<select v-model="userFilter"><option value="">全部人群</option><option v-for="group in researchCohorts" :key="group.id" :value="group.id">{{ group.name }}</option></select></label><label class="search-label"><SearchOutlined /><input v-model="keyword" type="search" placeholder="搜索用户 ID、国家、职业或品牌" aria-label="搜索用户" /></label><span>{{ filteredUsers.length }} / {{ researchUsers.length }} 位用户</span></div>
        <div class="user-layout">
          <div class="user-list">
            <button v-for="user in filteredUsers" :key="user.id" type="button" class="user-item" :class="{ selected: selectedUserId === user.id }" @click="selectUser(user)">
              <span class="user-avatar">{{ user.id }}</span>
              <span class="user-item-main"><strong>用户 #{{ user.id }}</strong><small>{{ countryLabel(user.country) }} · {{ researchCohorts.find(group => group.id === user.cohortId)?.name }}</small></span>
              <span class="user-enjoy">{{ user.enjoyCount }} ENJOY</span>
            </button>
            <div v-if="!filteredUsers.length" class="user-empty">没有符合条件的用户。</div>
          </div>
          <aside ref="detailPanel" class="user-detail" aria-label="用户详情">
            <template v-if="selectedUser">
              <div class="detail-top"><span class="eyebrow">USER {{ selectedUser.id }}</span><h3>用户 #{{ selectedUser.id }}</h3><p>{{ selectedUserCohort?.name }} · {{ countryLabel(selectedUser.country) }}</p></div>
              <div class="profile-tags"><span v-if="selectedUser.age">{{ selectedUser.age }} 岁</span><span>{{ genderLabel(selectedUser.gender) }}</span><span v-if="selectedUser.profession">{{ selectedUser.profession }}</span><span v-if="selectedUser.phoneBrand">在用 {{ selectedUser.phoneBrand }}</span></div>
              <div class="detail-counts"><div><strong>{{ selectedUser.enjoyCount }}</strong><span>ENJOY 反馈</span></div><div><strong>{{ selectedUser.dislikeCount }}</strong><span>DISLIKE 反馈</span></div></div>
              <div class="detail-section">
                <h4>喜欢的图片 <span>{{ selectedUser.images.length }} 张展示</span></h4>
                <div v-if="selectedUser.images.length" class="user-images"><button v-for="imageId in selectedUser.images" :key="imageId" type="button" @click="previewImageId = imageId"><img :src="researchImages[imageId]?.src" :alt="`用户 ${selectedUser.id} 标记 ENJOY 的图片 ${imageId}`" loading="lazy" /></button></div>
                <p v-else class="missing-note">源记录没有 ENJOY 图片反馈。</p>
              </div>
              <div class="detail-section">
                <h4>源记录摘录 <span>{{ selectedUser.excerpts.length }} 条</span></h4>
                <p class="excerpt-note">问答分析来自源文件 ai_analysis 字段，并非用户逐字原话。</p>
                <div v-if="selectedUser.excerpts.length" class="excerpt-list"><article v-for="item in selectedUser.excerpts" :key="`${item.kind}-${item.id}`"><small>{{ item.kind }} #{{ item.id }}</small><h5>{{ item.question }}</h5><p>{{ item.answer }}</p></article></div>
                <p v-else class="missing-note">该用户没有关联的问答或需求文本。</p>
              </div>
              <p class="source-id">源用户 ID {{ selectedUser.id }} · BID {{ selectedUser.bid }}</p>
            </template>
            <div v-else class="user-empty">选择一位用户查看记录。</div>
          </aside>
        </div>
      </section>
    </main>

    <footer><span>用户审美洞察与趋势捕捉 · AI 审美洞察平台</span><span>资料来源：data/userreseach_data</span></footer>
    <a-modal :open="Boolean(previewImageId)" :footer="null" centered :width="850" title="ENJOY 图片" @cancel="previewImageId = ''">
      <div v-if="previewImage" class="preview-body"><img :src="previewImage.src" :alt="`用研偏好图片 ${previewImage.id}`" /><p>图片 ID {{ previewImage.id }} · 本次 50 人样本中 {{ previewImage.enjoyedBy }} 位用户标记 ENJOY</p></div>
    </a-modal>
  </div>
</template>

<style scoped>
.research-hero { max-width: none; display: flex; align-items: end; justify-content: space-between; gap: 28px; padding: 62px 0 36px; }
.research-hero h1 { margin: 14px 0 8px; font-size: 42px; line-height: 1.15; }
.research-hero p { margin: 0; color: var(--muted); font-size: 14px; }
.sample-stats { display: flex; gap: 26px; flex-shrink: 0; padding: 14px 0 6px; }
.sample-stats div { display: grid; gap: 2px; min-width: 70px; }
.sample-stats strong { color: #4d409b; font-size: 29px; line-height: 1; }
.sample-stats span { color: var(--muted); font-size: 11px; }
.method-note { display: flex; gap: 9px; align-items: start; padding: 12px 16px; color: #756a8c; background: #eeeaf8; border: 1px solid #e4ddf5; border-radius: 11px; font-size: 11px; line-height: 1.7; }
.method-dot { width: 7px; height: 7px; flex: 0 0 auto; margin-top: 6px; background: #8d7bcc; border-radius: 50%; }
.research-tabs { display: flex; gap: 5px; width: fit-content; margin: 25px 0; padding: 5px; background: #eae7f2; border-radius: 13px; }
.research-tabs button { min-width: 110px; padding: 9px 17px; border: 0; border-radius: 9px; background: transparent; color: #766d87; cursor: pointer; font-size: 12px; }
.research-tabs button.active { color: #4d409b; background: white; box-shadow: 0 4px 12px rgba(68, 56, 117, .1); font-weight: 600; }
.tab-body { margin-bottom: 70px; }
.section-heading { display: flex; justify-content: space-between; align-items: end; gap: 20px; margin: 0 0 17px; }
.section-heading h2 { margin: 6px 0 5px; color: #302b40; font-size: 20px; }
.section-heading p { margin: 0; color: #91899f; font-size: 11px; line-height: 1.6; }
.matrix-scroll { overflow-x: auto; background: #23232a; border: 1px solid #38363f; border-radius: 18px; box-shadow: 0 18px 35px rgba(34, 31, 52, .15); }
.matrix-table { width: 100%; min-width: 760px; border-collapse: collapse; table-layout: fixed; }
.matrix-table th:first-child { width: 210px; }
.matrix-table th, .matrix-table td { border-right: 1px solid #38373f; border-bottom: 1px solid #38373f; text-align: center; }
.matrix-table tr > :last-child { border-right: 0; }
.matrix-table tbody tr:last-child > * { border-bottom: 0; }
.matrix-table thead th { padding: 16px 8px 12px; background: #2c2b33; }
.matrix-table thead th:first-child { padding-left: 18px; text-align: left; color: #c8c5ce; font-size: 12px; }
.matrix-topic, .matrix-row-button, .matrix-cell { width: 100%; border: 0; background: transparent; color: #e7e5ec; cursor: pointer; }
.matrix-topic { display: grid; justify-items: center; gap: 7px; font-size: 11px; }
.matrix-topic:hover, .matrix-row-button:hover { color: #aaa1ff; }
.topic-images { display: flex; justify-content: center; gap: 3px; width: 100%; }
.topic-images img { width: 33px; height: 47px; object-fit: contain; background: #181820; border: 1px solid #50505a; border-radius: 5px; }
.matrix-row-button { display: grid; gap: 4px; padding: 14px 18px; text-align: left; }
.matrix-row-button strong { font-size: 12px; }
.matrix-row-button small { color: #8f8d98; font-size: 10px; }
.matrix-cell { display: grid; justify-items: center; gap: 2px; min-height: 60px; padding: 9px; }
.matrix-cell:hover { background: #2d2b37; }
.matrix-symbol { font-size: 20px; line-height: 1; }
.matrix-symbol.heart { color: #ff786e; }
.matrix-symbol.strong { color: #77cf8e; }
.matrix-symbol.medium { color: #b9a3da; }
.matrix-symbol.empty { color: #55545e; }
.matrix-cell small { color: #9b99a3; font-size: 9px; }
.matrix-legend { display: flex; flex-wrap: wrap; gap: 16px; margin: 13px 2px 0; color: #867e91; font-size: 10px; }
.matrix-legend span { display: flex; align-items: center; gap: 5px; }
.matrix-legend i { font-size: 14px; font-style: normal; }
.legend-heart { color: #ff786e; }.legend-strong { color: #77cf8e; }.legend-medium { color: #b9a3da; }.legend-empty { color: #88868e; }
.cards-heading { margin-top: 38px; }
.cohort-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 15px; }
.cohort-card { display: block; min-width: 0; padding: 20px; background: white; border: 1px solid #e8e2ef; border-radius: 16px; text-align: left; cursor: pointer; box-shadow: 0 10px 25px rgba(53, 44, 105, .04); transition: transform .2s, box-shadow .2s; }
.cohort-card:hover { transform: translateY(-3px); box-shadow: 0 15px 28px rgba(53, 44, 105, .1); }
.cohort-card-top { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.cohort-number { display: grid; width: 34px; height: 34px; place-items: center; color: #6b5fba; background: #eeeafd; border-radius: 10px; font-family: 'DM Mono', monospace; font-size: 12px; }
.cohort-country { color: #a29aac; font-size: 10px; }
.cohort-card h3 { margin: 16px 0 4px; color: #302b40; font-size: 16px; }
.cohort-card p { margin: 0; color: #92899f; font-size: 11px; }
.cohort-thumbs { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; height: 92px; margin: 17px 0; }
.cohort-thumbs img { width: 100%; height: 100%; object-fit: contain; background: #f1eef6; border-radius: 8px; }
.no-thumbs { display: grid; height: 92px; margin: 17px 0; place-items: center; color: #a49cad; background: #f4f2f7; border-radius: 8px; font-size: 11px; }
.card-link { display: flex; align-items: center; gap: 6px; color: #6c5bb7; font-size: 11px; font-weight: 600; }
.gallery-heading { align-items: center; }
.select-label { display: grid; gap: 6px; color: #8d839b; font-size: 10px; }
.select-label select { min-width: 180px; height: 38px; padding: 0 11px; color: #51455f; background: white; border: 1px solid #e2ddeb; border-radius: 9px; font-size: 12px; }
.gallery-summary { display: flex; justify-content: space-between; align-items: center; gap: 15px; padding: 17px 19px; margin-bottom: 16px; background: white; border: 1px solid #e8e2ef; border-radius: 14px; }
.gallery-summary > div { display: flex; align-items: center; gap: 12px; }
.gallery-summary h3 { margin: 0 0 4px; color: #332c44; font-size: 15px; }.gallery-summary p { margin: 0; color: #958ca0; font-size: 11px; }
.gallery-summary button, .empty-gallery button { padding: 9px 12px; color: #6151af; background: #f0ecfb; border: 0; border-radius: 8px; cursor: pointer; font-size: 11px; }
.gallery-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.gallery-card { overflow: hidden; padding: 0; text-align: left; background: white; border: 1px solid #e8e2ef; border-radius: 14px; cursor: pointer; }
.gallery-card:hover { border-color: #a99be1; }
.gallery-image { display: grid; height: 220px; place-items: center; background: #f4f1f8; }
.gallery-image img { max-width: 100%; max-height: 100%; object-fit: contain; }
.gallery-caption { display: grid; gap: 5px; padding: 12px; color: #584a83; font-size: 11px; }
.gallery-caption small { color: #a39aaa; font-size: 9px; overflow-wrap: anywhere; }
.empty-gallery { display: grid; justify-items: center; gap: 8px; padding: 60px 20px; color: #a39aaa; background: white; border: 1px solid #e8e2ef; border-radius: 14px; text-align: center; }
.empty-gallery :deep(.anticon) { font-size: 27px; }.empty-gallery h3 { margin: 0; color: #60566e; font-size: 15px; }.empty-gallery p { margin: 0 0 8px; font-size: 11px; }
.user-controls { display: flex; align-items: end; gap: 12px; margin-bottom: 16px; }
.search-label { position: relative; flex: 1; max-width: 360px; }.search-label :deep(.anticon) { position: absolute; top: 12px; left: 11px; color: #a59bad; }
.search-label input { width: 100%; height: 38px; padding: 0 11px 0 31px; color: #51455f; background: white; border: 1px solid #e2ddeb; border-radius: 9px; font-size: 12px; }
.user-controls > span { margin-left: auto; color: #958ca0; font-size: 11px; }
.user-layout { display: grid; grid-template-columns: 350px minmax(0, 1fr); gap: 18px; align-items: start; }
.user-list { overflow-y: auto; max-height: 800px; background: white; border: 1px solid #e8e2ef; border-radius: 14px; }
.user-item { display: flex; align-items: center; gap: 10px; width: 100%; padding: 13px; text-align: left; background: transparent; border: 0; border-bottom: 1px solid #eeeaf2; cursor: pointer; }
.user-item:last-child { border-bottom: 0; }.user-item:hover, .user-item.selected { background: #f6f3fc; }
.user-avatar { display: grid; flex: 0 0 33px; height: 33px; place-items: center; color: #6b5fba; background: #eeeafd; border-radius: 50%; font-size: 10px; }
.user-item-main { display: grid; gap: 3px; min-width: 0; }.user-item-main strong { color: #453b55; font-size: 12px; }.user-item-main small { overflow: hidden; color: #9c93a8; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.user-enjoy { margin-left: auto; color: #9185a4; font-size: 10px; white-space: nowrap; }
.user-detail { min-width: 0; padding: 23px; background: white; border: 1px solid #e8e2ef; border-radius: 14px; }
.detail-top h3 { margin: 6px 0 3px; color: #302b40; font-size: 21px; }.detail-top p { margin: 0; color: #92899f; font-size: 11px; }
.profile-tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 17px 0; }.profile-tags span { padding: 5px 9px; color: #776690; background: #f1edf8; border-radius: 7px; font-size: 10px; }
.detail-counts { display: flex; gap: 30px; padding: 14px 0; border-top: 1px solid #eeeaf2; border-bottom: 1px solid #eeeaf2; }.detail-counts div { display: grid; gap: 3px; }.detail-counts strong { color: #594a9e; font-size: 18px; }.detail-counts span { color: #9b92a5; font-size: 10px; }
.detail-section { margin-top: 20px; }.detail-section h4 { margin: 0 0 11px; color: #453b55; font-size: 13px; }.detail-section h4 span { margin-left: 5px; color: #a39aaa; font-size: 10px; font-weight: 400; }
.user-images { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }.user-images button { overflow: hidden; height: 115px; padding: 0; background: #f3f0f7; border: 0; border-radius: 8px; cursor: pointer; }.user-images img { width: 100%; height: 100%; object-fit: contain; }
.missing-note { margin: 0; color: #a49bad; font-size: 11px; }
.excerpt-list { display: grid; gap: 9px; }.excerpt-list article { padding: 12px 14px; background: #f8f6fb; border-radius: 9px; }.excerpt-list small { color: #8e7fc1; font-size: 10px; }.excerpt-list h5 { margin: 5px 0; color: #51465f; font-size: 11px; }.excerpt-list p { margin: 0; color: #71677c; font-size: 11px; line-height: 1.7; }
.excerpt-note { margin: -3px 0 10px; color: #9c93a8; font-size: 10px; }
.source-id { margin: 22px 0 0; color: #aaa1b2; font-family: 'DM Mono', monospace; font-size: 10px; overflow-wrap: anywhere; }.user-empty { padding: 30px; color: #aaa1b2; text-align: center; font-size: 12px; }
.preview-body { display: grid; justify-items: center; gap: 10px; }.preview-body img { max-width: 100%; max-height: 72vh; object-fit: contain; }.preview-body p { margin: 0; color: #888095; font-size: 11px; overflow-wrap: anywhere; }
@media (max-width: 980px) { .cohort-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.user-layout { grid-template-columns: 290px minmax(0, 1fr); } }
@media (max-width: 780px) { .research-hero { display: block; padding-top: 46px; }.sample-stats { gap: 25px; margin-top: 22px; }.user-layout { grid-template-columns: 1fr; }.user-list { max-height: 340px; }.gallery-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) { .research-hero h1 { font-size: 36px; }.sample-stats { justify-content: space-between; }.sample-stats strong { font-size: 25px; }.research-tabs { width: 100%; }.research-tabs button { flex: 1; min-width: 0; padding: 9px 7px; }.cohort-grid { grid-template-columns: 1fr; }.gallery-heading { display: block; }.gallery-heading .select-label { margin-top: 14px; }.gallery-summary { align-items: start; flex-direction: column; }.gallery-grid { gap: 10px; }.gallery-image { height: 170px; }.user-controls { flex-wrap: wrap; }.user-controls .search-label { flex: 1 1 160px; }.user-controls > span { width: 100%; margin: 0; }.user-images { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
