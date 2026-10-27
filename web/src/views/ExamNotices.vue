<template>
  <div class="page">
    <!-- 数据新鲜度：让用户知道这份数据是哪天抓的，不是"实时" -->
    <el-alert
      v-if="lastSuccess"
      type="info"
      :closable="false"
      class="freshness"
      show-icon
    >
      数据每周从官方渠道自动更新，上次同步：{{ lastSuccess }}
      <span class="freshness-note">（公告原文链接可逐条核对）</span>
    </el-alert>

    <el-card shadow="never" class="filter-bar">
      <el-form inline @submit.prevent>
        <el-form-item label="类型">
          <el-radio-group v-model="examType" @change="reload">
            <el-radio-button value="">全部</el-radio-button>
            <el-radio-button value="civil">考公</el-radio-button>
            <el-radio-button value="institution">考编</el-radio-button>
            <el-radio-button value="postgraduate">考研</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="标题">
          <el-input
            v-model="keyword"
            placeholder="如 公务员 / 事业单位 / 硕士"
            clearable
            style="width: 200px"
            @keyup.enter="reload"
            @clear="reload"
          />
        </el-form-item>
        <el-form-item label="地区">
          <el-input v-model="region" placeholder="如 重庆" clearable style="width: 120px"
            @keyup.enter="reload" @clear="reload" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="onlyOpen" @change="reload">只看在招</el-checkbox>
          <el-checkbox v-model="includeClosed" @change="reload">含已截止</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="reload">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 各类型条数概览 -->
    <div class="type-stats">
      <div v-for="t in stats" :key="t.exam_type" class="type-chip" :class="{ active: examType === t.exam_type }"
        @click="pickType(t.exam_type)">
        <span class="chip-label">{{ t.label }}</span>
        <span class="chip-num">{{ t.total }}</span>
        <span class="chip-open">在招 {{ t.open }}</span>
      </div>
    </div>

    <el-card shadow="never" v-loading="loading">
      <el-empty v-if="!loading && !items.length" description="没有符合条件的公告" />

      <div v-for="it in items" :key="it.id" class="notice-item" @click="openDetail(it)">
        <div class="notice-head">
          <el-tag size="small" :type="tagType(it.exam_type)" effect="plain">
            {{ it.exam_type_label }}
          </el-tag>
          <span class="notice-title">{{ it.title }}</span>
          <el-tag v-if="it.status === 'open'" size="small" type="success">在招</el-tag>
          <el-tag v-else-if="it.status === 'closed'" size="small" type="info">已截止</el-tag>
        </div>
        <div class="notice-meta">
          <span v-if="it.org_name">发布：{{ it.org_name }}</span>
          <span v-if="it.publish_date">日期：{{ it.publish_date }}</span>
          <span v-if="it.signup_end" class="deadline">报名截止：{{ it.signup_end }}</span>
          <span v-if="it.headcount">招 {{ it.headcount }} 人</span>
        </div>
        <!-- 要求摘要：缺失的显式写「详见公告」，不渲染成「不限」 -->
        <div class="notice-reqs">
          <span v-for="r in reqSummary(it)" :key="r.label" class="req">
            <b>{{ r.label }}</b>{{ r.value }}
            <em v-if="!r.filled" class="req-missing">详见公告</em>
          </span>
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

    <!-- 详情抽屉：原文全文 + 官网链接 -->
    <el-drawer v-model="drawer" :title="detail?.title || '公告详情'" size="640px">
      <div v-if="detail" class="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="类型">{{ detail.exam_type_label }}</el-descriptions-item>
          <el-descriptions-item label="地区">{{ detail.region || '—' }}</el-descriptions-item>
          <el-descriptions-item label="发布单位">{{ detail.org_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="发布日期">{{ detail.publish_date || '—' }}</el-descriptions-item>
          <el-descriptions-item label="报名开始">{{ detail.signup_start || '—' }}</el-descriptions-item>
          <el-descriptions-item label="报名截止">{{ detail.signup_end || '—' }}</el-descriptions-item>
          <el-descriptions-item label="笔试日期">{{ detail.exam_date || '—' }}</el-descriptions-item>
          <el-descriptions-item label="招录人数">{{ detail.headcount ?? '—' }}</el-descriptions-item>
        </el-descriptions>

        <h4 class="sec-title">报考要求</h4>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item v-for="r in detailReqs" :key="r.key" :label="r.label">
            <span v-if="r.value">{{ r.value }}</span>
            <span v-else class="missing">公告未单独说明（具体岗位要求以附件岗位表为准）</span>
          </el-descriptions-item>
        </el-descriptions>

        <h4 class="sec-title">公告原文</h4>
        <div class="raw-text">{{ detail.raw_text || '（未抓到正文，请点下方链接查看原文）' }}</div>

        <el-button
          v-if="detail.detail_url"
          type="primary"
          class="official-link"
          tag="a"
          :href="detail.detail_url"
          target="_blank"
          rel="noopener noreferrer"
        >
          打开官方原文核对
        </el-button>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import http from '../api/http'

const EXAM_TYPE_TAG = { civil: 'danger', institution: 'warning', postgraduate: 'success' }

const examType = ref('')
const keyword = ref('')
const region = ref('')
const onlyOpen = ref(false)
const includeClosed = ref(false)

const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

const stats = ref([])
const lastSuccess = ref('')

const drawer = ref(false)
const detail = ref(null)

const REQ_FIELDS = [
  { key: 'education_req', label: '学历' },
  { key: 'degree_req', label: '学位' },
  { key: 'major_req', label: '专业' },
  { key: 'age_req', label: '年龄' },
  { key: 'political_req', label: '政治面貌' },
  { key: 'exp_req', label: '工作经历' },
  { key: 'cert_req', label: '资格证书' },
  { key: 'other_req', label: '其他' }
]

const detailReqs = computed(() =>
  REQ_FIELDS.map((f) => ({ ...f, value: detail.value?.[f.key] || '' }))
)

function tagType(t) {
  return EXAM_TYPE_TAG[t] || 'info'
}

function reqSummary(it) {
  // 列表只挑 3 条最有代表性的要求做摘要
  const pick = ['education_req', 'age_req', 'major_req']
  const labelMap = { education_req: '学历', age_req: '年龄', major_req: '专业' }
  return pick.map((k) => ({
    label: `${labelMap[k]} `,
    value: it[k] || '',
    filled: Boolean(it[k])
  }))
}

async function loadStats() {
  try {
    const { data } = await http.get('/exam/stats')
    stats.value = data.by_type || []
    lastSuccess.value = (data.last_success_at || '').slice(0, 16)
  } catch {
    stats.value = []
  }
}

async function loadList() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize }
    if (examType.value) params.exam_type = examType.value
    if (keyword.value) params.keyword = keyword.value
    if (region.value) params.region = region.value
    if (onlyOpen.value) params.only_open = true
    if (includeClosed.value) params.include_closed = true
    const { data } = await http.get('/exam/notices', { params })
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

function pickType(t) {
  examType.value = examType.value === t ? '' : t
  reload()
}

function onPage(p) {
  page.value = p
  loadList()
}

async function openDetail(it) {
  const { data } = await http.get(`/exam/notices/${it.id}`)
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
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px;
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
.type-stats {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.type-chip {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  background: var(--el-bg-color);
}
.type-chip:hover {
  border-color: var(--el-color-primary);
}
.type-chip.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.chip-label {
  font-weight: 600;
}
.chip-num {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-color-primary);
}
.chip-open {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.notice-item {
  padding: 12px 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  cursor: pointer;
}
.notice-item:hover {
  background: var(--el-fill-color-light);
}
.notice-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.notice-title {
  flex: 1;
  font-weight: 600;
  line-height: 1.5;
}
.notice-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.deadline {
  color: var(--el-color-danger);
  font-weight: 600;
}
.notice-reqs {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.req b {
  color: var(--el-text-color-secondary);
  font-weight: 500;
  margin-right: 2px;
}
.req-missing {
  color: var(--el-color-warning);
  font-style: normal;
}
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
.detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.sec-title {
  margin: 8px 0 0;
  font-size: 14px;
  color: var(--el-text-color-primary);
}
.missing {
  color: var(--el-color-warning);
}
.raw-text {
  white-space: pre-wrap;
  max-height: 320px;
  overflow: auto;
  padding: 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}
.official-link {
  align-self: flex-start;
}
</style>
