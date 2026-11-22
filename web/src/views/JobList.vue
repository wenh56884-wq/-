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
        <el-form-item class="filter-actions">
          <span class="filter-total">
            共 <b>{{ total }}</b> 条
            <template v-if="lastSuccess">· 上次同步 {{ lastSuccess }}</template>
          </span>
          <el-button type="primary" :loading="loading" @click="reload">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 概览：总量 / 在招 / 单位数 / 行业数 -->
    <article class="bento-card stat-card">
      <div class="stat-top">
        <span class="bento-icon qh-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="13" rx="3" /><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 12h18" /></svg>
        </span>
        <span class="stat-label">岗位总数</span>
      </div>
      <div class="bento-stat">{{ stats.total ?? '—' }}</div>
    </article>

    <article class="bento-card stat-card">
      <div class="stat-top">
        <span class="bento-icon qh-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" /><path d="M8.5 12.5l2.5 2.5 4.5-5" /></svg>
        </span>
        <span class="stat-label">在招</span>
      </div>
      <div class="bento-stat">{{ stats.open ?? '—' }}</div>
    </article>

    <article class="bento-card stat-card">
      <div class="stat-top">
        <span class="bento-icon qh-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M4 20V6a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v14M15 10h3a2 2 0 0 1 2 2v8M3 20h18M8 8h3M8 12h3M8 16h3" /></svg>
        </span>
        <span class="stat-label">招聘单位</span>
      </div>
      <div class="bento-stat">{{ stats.companies ?? '—' }}</div>
    </article>

    <article class="bento-card stat-card">
      <div class="stat-top">
        <span class="bento-icon qh-icon" aria-hidden="true">
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
      <div class="top-tags" aria-label="按行业筛选岗位">
        <button
          v-for="(t, index) in stats.top_industries || []"
          :key="t.industry || `unknown-${index}`"
          class="top-tag"
          :class="{ active: !!t.industry && industry === t.industry, 'is-muted': !t.industry }"
          type="button"
          :disabled="!t.industry"
          :aria-pressed="!!t.industry && industry === t.industry"
          :title="!t.industry
            ? '这些岗位未标注行业，无法按行业筛选'
            : industry === t.industry ? `取消${t.industry}筛选` : `查看${t.industry}岗位`"
          @click="toggleIndustry(t.industry)"
        >
          <span>{{ t.industry || '未标注' }}</span>
          <b>{{ t.total }}</b>
        </button>
        <span v-if="!(stats.top_industries || []).length" class="empty-note">暂无行业数据</span>
      </div>
    </section>

    <el-card shadow="never" v-loading="loading" class="bento-span-4 list-card">
      <el-empty v-if="!loading && !items.length" description="没有符合条件的岗位" />

      <div v-for="it in items" :key="it.id" class="job-item" @click="openDetail(it)">
        <div class="job-top">
          <span class="bento-icon qh-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path :d="industryIcon(it.industry)" /></svg>
          </span>
          <div class="job-main">
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
          <span class="qh-arrow" aria-hidden="true">↗</span>
        </div>
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
        <div v-if="jdSections.length" class="jd-box">
          <section v-for="(sec, si) in jdSections" :key="si" class="jd-sec">
            <div v-if="sec.heading" class="jd-sec-head">
              <span class="jd-sec-name">{{ sec.heading }}</span>
              <em v-if="sec.items.some((i) => i.no)" class="jd-sec-count">
                {{ sec.items.length }} 条
              </em>
            </div>
            <ul class="jd-items">
              <li v-for="(it, ii) in sec.items" :key="ii" class="jd-item">
                <span v-if="it.no" class="jd-no">{{ it.no }}</span>
                <div class="jd-copy">
                  <p v-for="(p, pi) in it.parts" :key="pi" :class="['jd-p', { 'jd-en': p.en }]">
                    {{ p.text }}
                  </p>
                </div>
              </li>
            </ul>
          </section>
        </div>
        <p v-else class="missing">（未抓到职位介绍，请点下方链接查看原文）</p>

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
import { computed, onMounted, ref } from 'vue'

import http from '../api/http'
import { parseJd } from '../utils/text'

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

// 职位介绍按「小标题 + 编号条目 + 中英分行」解析，纯展示层结构，不改写原文
const jdSections = computed(() => parseJd(detail.value?.description))

// 行业图标块：只按行业名挑图形，不动任何岗位数据；认不出就用通用公文包
const INDUSTRY_ICONS = [
  { test: /互联网|软件|信息|计算机|通信|电子|数据/, path: 'M3 5h18v11H3zM2 19h20M8 16h8' },
  { test: /金融|银行|证券|保险|投资|基金|会计/, path: 'M3 8h18v8H3zM12 8v8M7 12h10' },
  { test: /教育|培训|学校|院校/, path: 'M12 4l9 4-9 4-9-4 9-4zM5 11v5c0 1.7 3.1 3 7 3s7-1.3 7-3v-5' },
  { test: /医疗|医药|生物|健康|护理/, path: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 8v8M8 12h8' },
  { test: /制造|机械|汽车|工业|材料|化工|能源/, path: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 3v3M12 18v3M4.2 7l2.6 1.5M17.2 15.5l2.6 1.5M4.2 17l2.6-1.5M17.2 8.5l2.6-1.5' },
  { test: /地产|建筑|工程|物业|装饰/, path: 'M4 20V8l8-4 8 4v12M9 20v-6h6v6' }
]

const DEFAULT_INDUSTRY_ICON =
  'M3 8h18v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8zM9 8V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18'

function industryIcon(industry) {
  const name = String(industry || '').trim()
  if (!name) return DEFAULT_INDUSTRY_ICON
  const hit = INDUSTRY_ICONS.find((item) => item.test.test(name))
  return hit ? hit.path : DEFAULT_INDUSTRY_ICON
}

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

function toggleIndustry(value) {
  const next = String(value || '').trim()
  if (!next) return
  industry.value = industry.value === next ? '' : next
  reload()
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
  font-size: 13.5px;
  margin-left: 6px;
}
/* 筛选区：白色圆角卡 + 软阴影，与统计卡同一套观感 */
.filter-bar {
  background: #ffffff;
  border: 1px solid var(--bento-border);
  border-radius: 18px;
  box-shadow:
    0 1px 2px rgba(16, 24, 40, 0.04),
    0 8px 20px rgba(16, 24, 40, 0.05);
}

.filter-bar :deep(.el-card__body) {
  padding: 16px 18px;
}

.filter-bar :deep(.el-form) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}

.filter-bar :deep(.el-form-item) {
  margin-bottom: 0;
}

/* 查询整组靠右：右侧不再空一大片，并显示当前筛选出的条数 */
.filter-actions {
  margin-left: auto;
  margin-right: 0;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.filter-total {
  font-size: 13.5px;
  color: var(--el-text-color-secondary);
}

.filter-total b {
  color: #16181d;
  font-size: 14px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 128px;
  background: #ffffff;
  border: 1px solid var(--bento-border);
  border-radius: 18px;
  box-shadow:
    0 1px 2px rgba(16, 24, 40, 0.04),
    0 8px 20px rgba(16, 24, 40, 0.05);
  transition:
    transform 220ms var(--bento-ease),
    box-shadow 220ms var(--bento-ease),
    border-color 220ms var(--bento-ease);
}

.stat-card:hover {
  transform: translateY(-2px);
  border-color: #baccf0;
  box-shadow:
    0 2px 6px rgba(25, 81, 195, 0.1),
    0 12px 28px rgba(16, 24, 40, 0.07);
}

.stat-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 统计卡右上角 ↗：与左侧淡紫图标块配成统一的卡片收口 */
.stat-card .stat-top::after {
  content: '↗';
  margin-left: auto;
  font-size: 14px;
  line-height: 1;
  color: #1951c3;
  opacity: 0.45;
  transition: opacity 180ms var(--bento-ease);
}

.stat-card:hover .stat-top::after {
  opacity: 1;
}

/* 参考站卡片三件套：白卡 + 左上角淡紫图标块 + 右上角 ↗ */
.qh-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  border-radius: 12px;
  background: var(--bento-accent-soft);
  color: var(--bento-accent);
}

.bento-icon svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.qh-arrow {
  font-size: 14px;
  line-height: 1;
  color: #1951c3;
  opacity: 0.45;
}

.stat-card:hover .qh-arrow {
  opacity: 1;
}

.stat-label {
  font-size: 14px;
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
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 40px;
  border: 1px solid transparent;
  font-family: inherit;
  font-size: 13.5px;
  padding: 6px 12px;
  border-radius: 999px;
  background: #eef0f5;
  color: var(--bento-sub);
  cursor: pointer;
  transition: transform 160ms ease, background-color 160ms ease,
    border-color 160ms ease, color 160ms ease, box-shadow 160ms ease;
}
.top-tag b {
  font-size: 12px;
  font-weight: 700;
  color: var(--bento-mute);
  font-variant-numeric: tabular-nums;
}
.top-tag:hover {
  transform: translateY(-1px);
  background: #e7edff;
  border-color: #b9c9ff;
  color: #1746a2;
}
.top-tag:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.24);
  outline-offset: 2px;
}
.top-tag.active {
  background: #1951c3;
  border-color: #1951c3;
  color: #fff;
  box-shadow: 0 5px 14px rgba(25, 81, 195, 0.22);
}
.top-tag.active b {
  color: rgba(255, 255, 255, 0.82);
}
.top-tag:disabled,
.top-tag.is-muted {
  cursor: default;
  opacity: 0.72;
}
.top-tag.is-muted:hover {
  transform: none;
  border-color: transparent;
  background: #eef0f5;
  color: var(--bento-sub);
}

.empty-note {
  font-size: 13.5px;
  color: var(--bento-mute);
}

@media (max-width: 700px) {
  /* 四张概览卡改成 2×2，筛选区/行业分布/列表仍通栏 */
  .bento-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .freshness,
  .filter-bar,
  .industry-card,
  .list-card {
    grid-column: 1 / -1;
  }

  .stat-card {
    min-height: 112px;
  }

  .stat-card .bento-stat {
    font-size: 30px;
  }
}

/* 手机端概览卡：图标块 38px + 四字标签在 173px 卡内会把「岗位总数」拆成两行，
   缩到 30px 并让标签不换行，2×2 保持整齐 */
@media (max-width: 560px) {
  .stat-card {
    gap: 6px;
    min-height: 0;
    padding: 12px 13px;
  }

  .stat-top {
    gap: 8px;
  }

  .stat-card .qh-icon {
    width: 30px;
    height: 30px;
    flex: 0 0 30px;
    border-radius: 9px;
  }

  .stat-card .qh-icon svg {
    width: 16px;
    height: 16px;
  }

  .stat-label {
    overflow: hidden;
    font-size: 12.5px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .stat-card .bento-stat {
    font-size: 26px;
  }

  .stat-card .stat-top::after {
    display: none;
  }
}
.job-item {
  padding: 12px 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  cursor: pointer;
}
.job-item:hover {
  background: var(--el-fill-color-light);
}

/* 岗位卡：左侧行业图标块（淡紫），右侧 ↗ 提示可点开看完整 JD */
.job-top {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.job-main {
  flex: 1 1 auto;
  min-width: 0;
}

.job-top .qh-arrow {
  margin-top: 4px;
}

.job-item:hover .qh-arrow {
  opacity: 1;
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
  font-size: 13.5px;
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
  font-size: 13.5px;
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
.jd-box {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 16px 18px 18px;
  background: #fff;
  border: 1px solid #f1f1f3;
  border-radius: 12px;
}

.jd-sec-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px dashed #e4e7ee;
}

.jd-sec-name {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: #16181d;
}

.jd-sec-count {
  margin-left: auto;
  font-size: 12.5px;
  font-style: normal;
  color: #6b7280;
}

.jd-items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.jd-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.jd-no {
  flex: 0 0 20px;
  width: 20px;
  height: 20px;
  margin-top: 2px;
  border-radius: 6px;
  background: rgba(37, 99, 235, 0.08);
  color: #1951c3;
  font-size: 12.5px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.jd-copy {
  min-width: 0;
}

.jd-p {
  margin: 0;
  font-size: 14px;
  line-height: 1.75;
  color: #3f3f46;
  word-break: break-word;
}

.jd-p + .jd-p {
  margin-top: 2px;
}

.jd-p.jd-en {
  font-size: 13.5px;
  line-height: 1.6;
  color: #6b7280;
}
.official-link {
  align-self: flex-start;
  margin-top: 12px;
}
</style>
