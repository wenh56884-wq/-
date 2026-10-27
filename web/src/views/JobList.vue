<template>
  <div class="page bento-page">
    <div class="bento-grid">
    <!-- 数据新鲜度：数据不是"实时"的，必须让学生知道是哪天同步的 -->
    <el-alert
      v-if="lastSuccess"
      type="info"
      :closable="false"
      class="freshness bento-span-4"
      show-icon
    >
      岗位每周从公开招聘渠道自动更新，上次同步：{{ lastSuccess }}
      <span class="freshness-note">（薪资/学历均取原文，未标注的显示「未标注」，不做推测）</span>
    </el-alert>

    <el-card shadow="never" class="filter-bar bento-span-4">
      <el-form inline @submit.prevent>
        <el-form-item label="关键词">
          <el-input
            v-model="keyword"
            placeholder="岗位名 / 单位名，如 数据 / 阿里"
            clearable
            style="width: 210px"
            @keyup.enter="reload"
            @clear="reload"
          />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="industry" placeholder="如 互联网" clearable style="width: 130px"
            @keyup.enter="reload" @clear="reload" />
        </el-form-item>
        <el-form-item label="学历">
          <el-select v-model="education" clearable placeholder="不限" style="width: 110px" @change="reload">
            <el-option label="博士" value="博士" />
            <el-option label="硕士" value="硕士" />
            <el-option label="本科" value="本科" />
            <el-option label="大专" value="大专" />
          </el-select>
        </el-form-item>
        <el-form-item label="月薪≥">
          <el-select v-model="salaryMin" clearable style="width: 110px" @change="reload">
            <el-option label="不限" :value="0" />
            <el-option label="5000" :value="5000" />
            <el-option label="10000" :value="10000" />
            <el-option label="15000" :value="15000" />
            <el-option label="20000" :value="20000" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="includeClosed" @change="reload">含已下架</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="reload">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 概览：总量 / 在招 / 单位数 / 行业数 -->
    <article class="bento-card stat-card">
      <div class="stat-top">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="13" rx="3" /><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 12h18" /></svg>
        </span>
        <span class="stat-label">岗位总数</span>
      </div>
      <div class="bento-stat">{{ stats.total ?? '—' }}</div>
    </article>

    <article class="bento-card stat-card">
      <div class="stat-top">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" /><path d="M8.5 12.5l2.5 2.5 4.5-5" /></svg>
        </span>
        <span class="stat-label">在招</span>
      </div>
      <div class="bento-stat">{{ stats.open ?? '—' }}</div>
    </article>

    <article class="bento-card stat-card">
      <div class="stat-top">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M4 20V6a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v14M15 10h3a2 2 0 0 1 2 2v8M3 20h18M8 8h3M8 12h3M8 16h3" /></svg>
        </span>
        <span class="stat-label">招聘单位</span>
      </div>
      <div class="bento-stat">{{ stats.companies ?? '—' }}</div>
    </article>

    <article class="bento-card stat-card">
      <div class="stat-top">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M12 3l8 4.5-8 4.5-8-4.5L12 3zM4 12l8 4.5 8-4.5M4 16.5l8 4.5 8-4.5" /></svg>
        </span>
        <span class="stat-label">覆盖行业</span>
      </div>
      <div class="bento-stat">{{ stats.industries ?? '—' }}</div>
    </article>

    <section class="bento-card bento-span-4 industry-card">
      <div class="card-head">
        <h3 class="bento-title">行业分布</h3>
        <span class="bento-eyebrow">按在招岗位</span>
      </div>
      <div class="top-tags">
        <span v-for="t in stats.top_industries || []" :key="t.industry" class="top-tag">
          {{ t.industry }} {{ t.total }}
        </span>
        <span v-if="!(stats.top_industries || []).length" class="empty-note">暂无行业数据</span>
      </div>
    </section>

    <el-card shadow="never" v-loading="loading" class="bento-span-4 list-card">
      <el-empty v-if="!loading && !items.length" description="没有符合条件的岗位" />

      <div v-for="it in items" :key="it.id" class="job-item" @click="openDetail(it)">
        <div class="job-head">
          <span class="job-title">{{ it.title }}</span>
          <!-- 薪资缺失时显示「未标注」，绝不显示 0 或「面议」 -->
          <span v-if="it.salary_text" class="job-salary">{{ it.salary_text }}</span>
          <span v-else class="job-salary missing">薪资未标注</span>
          <el-tag v-if="it.status === 'closed'" size="small" type="info">已下架</el-tag>
        </div>
        <div class="job-meta">
          <span class="job-company">{{ it.company }}</span>
          <span v-if="it.industry">{{ it.industry }}</span>
          <span>{{ it.city }}{{ it.district ? '-' + it.district : '' }}</span>
          <span v-if="it.experience">{{ it.experience }}</span>
          <!-- 学历同为缺失：显示未标注，与「不限」区分开 -->
          <el-tag v-if="it.education" size="small" effect="plain">{{ it.education }}</el-tag>
          <span v-else class="missing">学历未标注</span>
          <span v-if="it.headcount">招 {{ it.headcount }} 人</span>
        </div>
        <div v-if="it.skill_tags?.length" class="job-skills">
          <el-tag v-for="s in it.skill_tags" :key="s" size="small" type="info" effect="plain">
            {{ s }}
          </el-tag>
        </div>
        <div v-if="it.description" class="job-desc">{{ it.description }}</div>
      </div>

      <el-pagination
        v-if="total > pageSize"
        class="pager"
        background
        layout="prev, pager, next, total"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        @current-change="onPage"
      />
    </el-card>
    </div>

    <!-- 详情抽屉：完整 JD + 投递原文链接 -->
    <el-drawer v-model="drawer" :title="detail?.title || '岗位详情'" size="620px">
      <div v-if="detail" class="detail drawer-panel">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="招聘单位">{{ detail.company }}</el-descriptions-item>
          <el-descriptions-item label="行业">{{ detail.industry || '未标注' }}</el-descriptions-item>
          <el-descriptions-item label="工作地点">
            {{ detail.city }}{{ detail.district ? '-' + detail.district : '' }}
          </el-descriptions-item>
          <el-descriptions-item label="月薪">{{ detail.salary_text || '未标注' }}</el-descriptions-item>
          <el-descriptions-item label="学历">{{ detail.education || '未标注' }}</el-descriptions-item>
          <el-descriptions-item label="经验">{{ detail.experience || '未标注' }}</el-descriptions-item>
          <el-descriptions-item label="招聘人数">{{ detail.headcount ?? '未标注' }}</el-descriptions-item>
          <el-descriptions-item label="发布日期">{{ detail.published_at || '未标注' }}</el-descriptions-item>
        </el-descriptions>

        <h4 class="sec-title">技能标签</h4>
        <div v-if="detail.skill_tags?.length" class="job-skills">
          <el-tag v-for="s in detail.skill_tags" :key="s" size="small" type="info" effect="plain">
            {{ s }}
          </el-tag>
        </div>
        <p v-else class="missing">该岗位原文未提及可识别的技能关键词。</p>

        <h4 class="sec-title">职位介绍</h4>
        <div class="jd-text">{{ decodeEntities(detail.description) || '（未抓到职位介绍，请点下方链接查看原文）' }}</div>

        <el-button
          v-if="detail.apply_url"
          type="primary"
          class="official-link"
          tag="a"
          :href="detail.apply_url"
          target="_blank"
          rel="noopener noreferrer"
        >
          打开原岗位页
        </el-button>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'

import http from '../api/http'
import { decodeEntities } from '../utils/text'

const keyword = ref('')
const industry = ref('')
const education = ref('')
const salaryMin = ref(0)
const includeClosed = ref(false)

const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

const stats = ref({})
const lastSuccess = ref('')

const drawer = ref(false)
const detail = ref(null)

async function loadStats() {
  try {
    const { data } = await http.get('/job/stats')
    stats.value = data || {}
    lastSuccess.value = (data.last_success_at || '').slice(0, 16)
  } catch {
    stats.value = {}
  }
}

async function loadList() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize }
    if (keyword.value) params.keyword = keyword.value
    if (industry.value) params.industry = industry.value
    if (education.value) params.education = education.value
    if (salaryMin.value) params.salary_min = salaryMin.value
    if (includeClosed.value) params.include_closed = true
    const { data } = await http.get('/job/list', { params })
    items.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  loadList()
}

function onPage(p) {
  page.value = p
  loadList()
}

async function openDetail(it) {
  const { data } = await http.get(`/job/list/${it.id}`)
  detail.value = data
  drawer.value = true
}

onMounted(() => {
  loadStats()
  loadList()
})
</script>

<style scoped>
.page {
  display: block;
  padding: 0;
}
.freshness {
  margin-bottom: 0;
}
.freshness-note {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: 6px;
}
.filter-bar :deep(.el-form-item) {
  margin-bottom: 0;
}
.stat-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 128px;
}

.stat-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stat-card .bento-icon {
  width: 38px;
  height: 38px;
  flex-basis: 38px;
}

.stat-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--bento-mute);
}

.industry-card {
  padding: 18px 20px;
}

.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.top-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.top-tag {
  font-size: 12px;
  padding: 6px 12px;
  border-radius: 999px;
  background: #f4f4f5;
  color: var(--bento-sub);
}

.empty-note {
  font-size: 12px;
  color: var(--bento-mute);
}
.job-item {
  padding: 12px 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  cursor: pointer;
}
.job-item:hover {
  background: var(--el-fill-color-light);
}
.job-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.job-title {
  flex: 1;
  font-weight: 600;
  font-size: 15px;
  line-height: 1.5;
}
.job-salary {
  font-weight: 600;
  color: var(--el-color-danger);
  font-variant-numeric: tabular-nums;
}
.missing {
  color: var(--el-text-color-placeholder);
  font-weight: 400;
}
.job-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.job-company {
  color: var(--el-text-color-regular);
  font-weight: 500;
}
.job-skills {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.job-desc {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.detail {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sec-title {
  margin: 14px 0 4px;
  font-size: 14px;
  font-weight: 600;
}
.jd-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.8;
  padding: 12px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  max-height: 46vh;
  overflow-y: auto;
}
.official-link {
  align-self: flex-start;
  margin-top: 12px;
}
</style>
