<template>
  <div class="page bento-page">
    <div class="bento-grid">
    <!-- 数据新鲜度：让用户知道这份数据是哪天抓的，不是"实时" -->
    <el-alert
      v-if="lastSuccess"
      type="info"
      :closable="false"
      class="freshness bento-span-4"
      show-icon
    >
      数据每周从官方渠道自动更新，上次同步：{{ lastSuccess }}
      <span class="freshness-note">（公告原文链接可逐条核对）</span>
    </el-alert>

    <el-card shadow="never" class="filter-bar bento-span-4">
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
        <el-form-item class="filter-actions">
          <span class="filter-total">
            共 <b>{{ total }}</b> 条
            <template v-if="lastSuccess">· 上次同步 {{ lastSuccess }}</template>
          </span>
          <el-button type="primary" :loading="loading" @click="reload">查询</el-button>
          <el-button @click="resetFilter">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 各类型条数概览 -->
    <article
      class="bento-card stat-card type-card"
      :class="{ active: examType === '' }"
      role="button"
      tabindex="0"
      @click="pickType('')"
      @keyup.enter="pickType('')"
    >
      <div class="stat-top">
        <span class="bento-icon qh-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M12 3l8 4.5-8 4.5-8-4.5L12 3zM4 12l8 4.5 8-4.5M4 16.5l8 4.5 8-4.5" /></svg>
        </span>
        <span class="stat-label">全部公告</span>
        <span class="qh-arrow" aria-hidden="true">↗</span>
      </div>
      <div class="bento-stat">{{ statTotals.total }}<small>在招 {{ statTotals.open }}</small></div>
    </article>

    <article
      v-for="t in stats"
      :key="t.exam_type"
      class="bento-card stat-card type-card"
      :class="{ active: examType === t.exam_type }"
      role="button"
      tabindex="0"
      @click="pickType(t.exam_type)"
      @keyup.enter="pickType(t.exam_type)"
    >
      <div class="stat-top">
        <span class="bento-icon qh-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M7 3h7l4 4v14H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" /><path d="M14 3v4h4M9 13h6M9 17h4" /></svg>
        </span>
        <span class="stat-label">{{ t.label }}</span>
        <span class="qh-arrow" aria-hidden="true">↗</span>
      </div>
      <div class="bento-stat">{{ t.total }}<small>在招 {{ t.open }}</small></div>
    </article>

    <!-- 国考职位表入口：公告只有通用条件，具体岗位在这里逐条可查 -->
    <el-card v-if="gk.total_positions" shadow="never" class="bento-span-4 gk-entry">
      <div class="gk-entry-main">
        <span class="bento-icon qh-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M7 3h7l4 4v14H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" />
            <path d="M14 3v4h4M9 13h6M9 17h4" /></svg>
        </span>
        <div class="gk-entry-text">
          <div class="gk-entry-title">
            {{ gk.year }} 国家公务员考试职位表
            <el-tag size="small" type="danger" effect="plain">国考</el-tag>
          </div>
          <div class="gk-entry-sub">
            共 {{ gk.total_positions }} 个职位、计划招录 {{ gk.total_headcount }} 人
            · 可按部门 / 学历 / 政治面貌 / 工作地点筛选
          </div>
        </div>
        <el-button type="primary" @click="openGk">查看具体职位</el-button>
      </div>
    </el-card>

    <el-card shadow="never" v-loading="loading" class="bento-span-4 list-card">
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
        <!-- 要求摘要：只展示真抓到值的字段，全空就整行不渲染 -->
        <div v-if="reqSummary(it).length" class="notice-reqs">
          <span v-for="r in reqSummary(it)" :key="r.label" class="req">
            <b>{{ r.label }}</b>{{ r.value }}
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
    </div>

    <!-- 详情抽屉：原文全文 + 官网链接 -->
    <el-drawer v-model="drawer" :title="detail?.title || '公告详情'" size="640px">
      <div v-if="detail" class="detail drawer-panel">
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
        <div class="req-list">
          <div v-for="r in filledReqs" :key="r.key" class="req-row">
            <span class="req-label">{{ r.label }}</span>
            <span class="req-text">{{ r.value }}</span>
          </div>
          <div v-if="!filledReqs.length" class="req-hint">
            公告未单独说明报考要求，具体岗位要求以附件岗位表为准。
          </div>
          <div v-else-if="missingLabels.length" class="req-hint">
            {{ missingLabels.join('、') }}公告未单独说明，具体以附件岗位表为准。
          </div>
        </div>

        <h4 class="sec-title">公告原文</h4>
        <div class="raw-text">{{ decodeEntities(detail.raw_text) || '（未抓到正文，请点下方链接查看原文）' }}</div>

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

    <!-- 国考职位表：逐职位明细（部门 / 用人司局 / 专业 / 学历 / 人数 / 地点） -->
    <el-drawer v-model="gkDrawer" :title="`${gk.year || ''} 国考职位表`" size="80%">
      <div class="gk-toolbar">
        <el-input
          v-model="gkQuery.keyword"
          placeholder="职位 / 部门 / 专业 / 职位代码"
          clearable
          style="width: 220px"
          @keyup.enter="loadGk(1)"
          @clear="loadGk(1)"
        />
        <el-input
          v-model="gkQuery.dept"
          placeholder="部门名称，如 国家税务总局"
          clearable
          style="width: 210px"
          @keyup.enter="loadGk(1)"
          @clear="loadGk(1)"
        />
        <el-select
          v-model="gkQuery.education"
          placeholder="学历"
          clearable
          style="width: 170px"
          @change="loadGk(1)"
        >
          <el-option
            v-for="e in gk.educations || []"
            :key="e.name"
            :label="`${e.name}（${e.positions}）`"
            :value="e.name"
          />
        </el-select>
        <el-select
          v-model="gkQuery.political"
          placeholder="政治面貌"
          clearable
          style="width: 180px"
          @change="loadGk(1)"
        >
          <el-option
            v-for="p in gk.politicals || []"
            :key="p.name"
            :label="`${p.name}（${p.positions}）`"
            :value="p.name"
          />
        </el-select>
        <el-input
          v-model="gkQuery.place"
          placeholder="工作地点，如 重庆"
          clearable
          style="width: 160px"
          @keyup.enter="loadGk(1)"
          @clear="loadGk(1)"
        />
        <el-button type="primary" @click="loadGk(1)">查询</el-button>
        <el-button @click="resetGk">重置</el-button>
      </div>

      <div class="gk-summary">
        匹配 <b>{{ gkTotal }}</b> 个职位，计划招录 <b>{{ gkTotalHeadcount }}</b> 人
        <span class="gk-summary-note">· 点击任意一行查看完整要求</span>
      </div>

      <el-table
        v-loading="gkLoading"
        :data="gkItems"
        size="small"
        class="gk-table"
        @row-click="openGkDetail"
      >
        <el-table-column prop="dept_name" label="部门" min-width="160" show-overflow-tooltip />
        <el-table-column prop="bureau" label="用人司局" min-width="140" show-overflow-tooltip />
        <el-table-column prop="position_name" label="招考职位" min-width="190" show-overflow-tooltip />
        <el-table-column prop="headcount" label="人数" width="70" align="center" />
        <el-table-column prop="education" label="学历" width="140" show-overflow-tooltip />
        <el-table-column prop="major" label="专业" min-width="230" show-overflow-tooltip />
        <el-table-column prop="political" label="政治面貌" width="140" show-overflow-tooltip />
        <el-table-column prop="work_place" label="工作地点" width="150" show-overflow-tooltip />
      </el-table>

      <el-pagination
        v-if="gkTotal > gkPageSize"
        class="pager"
        background
        layout="prev, pager, next, total"
        :total="gkTotal"
        :page-size="gkPageSize"
        :current-page="gkPage"
        @current-change="loadGk"
      />

      <div class="gk-source">
        数据来源：国家公务员局《中央机关及其直属机构 {{ gk.year }} 年度考试录用公务员招考简章》（.xls 逐职位解析，原文可核对）
        <a v-if="gk.source_url" :href="gk.source_url" target="_blank" rel="noopener noreferrer">
          打开官方专题
        </a>
      </div>
    </el-drawer>

    <el-dialog
      v-model="gkDetailVisible"
      :title="gkDetail?.position_name || '职位详情'"
      width="780px"
    >
      <div v-if="gkDetail" class="gk-detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="年度">{{ gkDetail.year }}</el-descriptions-item>
          <el-descriptions-item label="简章分类">{{ gkDetail.category || '—' }}</el-descriptions-item>
          <el-descriptions-item label="部门">{{ gkDetail.dept_name }}</el-descriptions-item>
          <el-descriptions-item label="部门代码">{{ gkDetail.dept_code }}</el-descriptions-item>
          <el-descriptions-item label="用人司局">{{ gkDetail.bureau || '—' }}</el-descriptions-item>
          <el-descriptions-item label="机构性质">{{ gkDetail.org_nature || '—' }}</el-descriptions-item>
          <el-descriptions-item label="招考职位">{{ gkDetail.position_name }}</el-descriptions-item>
          <el-descriptions-item label="职位代码">{{ gkDetail.position_code }}</el-descriptions-item>
          <el-descriptions-item label="招录人数">{{ gkDetail.headcount ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="机构层级">{{ gkDetail.org_level || '—' }}</el-descriptions-item>
          <el-descriptions-item label="考试类别">{{ gkDetail.exam_category || '—' }}</el-descriptions-item>
          <el-descriptions-item label="职位属性">{{ gkDetail.position_attr || '—' }}</el-descriptions-item>
          <el-descriptions-item label="学历">{{ gkDetail.education || '—' }}</el-descriptions-item>
          <el-descriptions-item label="学位">{{ gkDetail.degree || '—' }}</el-descriptions-item>
          <el-descriptions-item label="政治面貌">{{ gkDetail.political || '—' }}</el-descriptions-item>
          <el-descriptions-item label="基层工作最低年限">{{ gkDetail.work_years || '—' }}</el-descriptions-item>
          <el-descriptions-item label="服务基层项目经历">{{ gkDetail.grassroots_project || '—' }}</el-descriptions-item>
          <el-descriptions-item label="专业能力测试">{{ gkDetail.pro_test || '—' }}</el-descriptions-item>
          <el-descriptions-item label="面试人员比例">{{ gkDetail.interview_ratio || '—' }}</el-descriptions-item>
          <el-descriptions-item label="工作地点">{{ gkDetail.work_place || '—' }}</el-descriptions-item>
          <el-descriptions-item label="落户地点">{{ gkDetail.settle_place || '—' }}</el-descriptions-item>
          <el-descriptions-item label="部门网站">{{ gkDetail.dept_site || '—' }}</el-descriptions-item>
          <el-descriptions-item label="咨询电话" :span="2">
            {{ [gkDetail.phone1, gkDetail.phone2, gkDetail.phone3].filter(Boolean).join(' / ') || '—' }}
          </el-descriptions-item>
        </el-descriptions>
        <div class="gk-detail-block">
          <b>专业要求</b>
          <p>{{ gkDetail.major || '公告未写专业要求' }}</p>
        </div>
        <div v-if="gkDetail.intro" class="gk-detail-block">
          <b>职位简介</b>
          <p>{{ gkDetail.intro }}</p>
        </div>
        <div v-if="gkDetail.remark" class="gk-detail-block">
          <b>备注</b>
          <p>{{ gkDetail.remark }}</p>
        </div>
      </div>
      <template #footer>
        <el-button
          v-if="gkDetail?.notice_url"
          type="primary"
          tag="a"
          :href="gkDetail.notice_url"
          target="_blank"
          rel="noopener noreferrer"
        >
          打开官方专题核对
        </el-button>
        <el-button @click="gkDetailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

import http from '../api/http'
import { decodeEntities } from '../utils/text'

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

// 国考职位表
const gk = ref({ year: null, total_positions: 0, total_headcount: 0, educations: [], politicals: [] })
const gkDrawer = ref(false)
const gkLoading = ref(false)
const gkItems = ref([])
const gkTotal = ref(0)
const gkTotalHeadcount = ref(0)
const gkPage = ref(1)
const gkPageSize = 20
const gkQuery = reactive({ keyword: '', dept: '', education: '', political: '', place: '' })
const gkDetail = ref(null)
const gkDetailVisible = ref(false)

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

// 抓取文本首尾常残留成对引号，仅展示层修剪，不动库里的原文
function cleanReq(v) {
  return String(v || '')
    .trim()
    .replace(/^["“”']+/, '')
    .replace(/["“”']+$/, '')
    .trim()
}

const detailReqs = computed(() =>
  REQ_FIELDS.map((f) => ({ ...f, value: cleanReq(detail.value?.[f.key]) }))
)

const filledReqs = computed(() => detailReqs.value.filter((r) => r.value))

const missingLabels = computed(() =>
  detailReqs.value.filter((r) => !r.value).map((r) => r.label)
)

const statTotals = computed(() =>
  (stats.value || []).reduce(
    (acc, t) => ({
      total: acc.total + Number(t.total || 0),
      open: acc.open + Number(t.open || 0)
    }),
    { total: 0, open: 0 }
  )
)

function tagType(t) {
  return EXAM_TYPE_TAG[t] || 'info'
}

function reqSummary(it) {
  // 列表只挑「真的抓到值」的前 3 条要求展示；没抓到的字段直接不渲染，
  // 不再刷一排「详见公告」——详情抽屉里本来就有完整的缺失清单。
  const pick = ['education_req', 'major_req', 'political_req', 'age_req', 'cert_req', 'exp_req']
  const labelMap = {
    education_req: '学历',
    major_req: '专业',
    political_req: '政治面貌',
    age_req: '年龄',
    cert_req: '证书',
    exp_req: '经历'
  }
  return pick
    .filter((k) => it[k])
    .slice(0, 3)
    .map((k) => ({ label: `${labelMap[k]} `, value: it[k], filled: true }))
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

// 筛选条件一次性归零（「只看在招 / 含已截止」两个开关一起复位，避免留下隐性过滤）
function resetFilter() {
  examType.value = ''
  keyword.value = ''
  region.value = ''
  onlyOpen.value = false
  includeClosed.value = false
  reload()
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

// ----------------------------------------------------------------
// 国考职位表
// ----------------------------------------------------------------
async function loadGkFacets() {
  try {
    const { data } = await http.get('/exam/positions/facets')
    gk.value = data
  } catch {
    gk.value = {
      year: null,
      total_positions: 0,
      total_headcount: 0,
      educations: [],
      politicals: [],
      source_url: ''
    }
  }
}

async function loadGk(page = 1) {
  gkPage.value = page
  gkLoading.value = true
  try {
    const params = { page, page_size: gkPageSize }
    for (const [key, value] of Object.entries(gkQuery)) {
      if (value) params[key] = value
    }
    const { data } = await http.get('/exam/positions', { params })
    gkItems.value = data.items || []
    gkTotal.value = data.total || 0
    gkTotalHeadcount.value = data.total_headcount || 0
    if (data.year) gk.value.year = data.year
  } finally {
    gkLoading.value = false
  }
}

function openGk() {
  gkDrawer.value = true
  if (!gkItems.value.length) loadGk(1)
}

function resetGk() {
  Object.keys(gkQuery).forEach((key) => {
    gkQuery[key] = ''
  })
  gkItems.value = []
  loadGk(1)
}

async function openGkDetail(row) {
  const { data } = await http.get(`/exam/positions/${row.id}`)
  gkDetail.value = data
  gkDetailVisible.value = true
}

onMounted(() => {
  loadStats()
  loadList()
  loadGkFacets()
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
.filter-bar {
  background: #ffffff;
  border: 1px solid var(--bento-border);
  border-radius: 18px;
  box-shadow:
    0 1px 2px rgba(23, 26, 43, 0.04),
    0 8px 20px rgba(23, 26, 43, 0.05);
}

.filter-bar :deep(.el-card__body) {
  padding: 16px 18px;
}

/* 查询/重置整组靠右：内联表单改成 flex，右侧不再空一大片 */
.filter-bar :deep(.el-form) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}

.filter-bar :deep(.el-form-item) {
  margin-bottom: 0;
}

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
  color: #18181b;
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
    0 1px 2px rgba(23, 26, 43, 0.04),
    0 8px 20px rgba(23, 26, 43, 0.05);
  transition:
    transform 220ms var(--bento-ease),
    box-shadow 220ms var(--bento-ease),
    border-color 220ms var(--bento-ease);
}

.stat-card:hover {
  transform: translateY(-2px);
  border-color: #ded9ff;
  box-shadow:
    0 2px 6px rgba(91, 91, 214, 0.1),
    0 12px 28px rgba(23, 26, 43, 0.07);
}

.stat-top {
  display: flex;
  align-items: center;
  gap: 10px;
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
  color: #b9b1ea;
  opacity: 0;
  transform: translate(-2px, 2px);
  transition:
    opacity 180ms var(--bento-ease),
    transform 180ms var(--bento-ease);
}

.stat-card:hover .qh-arrow {
  opacity: 1;
  transform: translate(0, 0);
}

.stat-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--bento-mute);
}

.type-card {
  cursor: pointer;
}

.type-card.active {
  border-color: #18181b;
  box-shadow:
    0 0 0 2px rgba(24, 24, 27, 0.08),
    var(--bento-shadow);
}

.type-card.active .bento-icon {
  color: #18181b;
  background: #e4e4e7;
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
  font-size: 13.5px;
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
  font-size: 13.5px;
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
  margin: 10px 0 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}
.sec-title::before {
  content: '';
  width: 3px;
  height: 14px;
  border-radius: 2px;
  background: #2563eb;
}
.req-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.req-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 10px;
}
.req-label {
  flex: 0 0 auto;
  margin-top: 1px;
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.08);
  color: #2563eb;
  font-size: 13.5px;
  font-weight: 600;
  line-height: 20px;
}
.req-text {
  font-size: 14px;
  line-height: 1.75;
  color: var(--el-text-color-regular);
  word-break: break-word;
  min-width: 0;
}
.req-hint {
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px dashed var(--el-border-color);
  color: var(--el-text-color-secondary);
  font-size: 13.5px;
  line-height: 1.6;
}
.raw-text {
  white-space: pre-wrap;
  max-height: 320px;
  overflow: auto;
  padding: 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}
.official-link {
  align-self: flex-start;
}

/* 国考职位表：入口卡同样走白卡 + 软阴影，与统计卡同一套观感 */
.gk-entry {
  background: #ffffff;
  border: 1px solid var(--bento-border);
  border-radius: 18px;
  box-shadow:
    0 1px 2px rgba(23, 26, 43, 0.04),
    0 8px 20px rgba(23, 26, 43, 0.05);
}

.gk-entry :deep(.el-card__body) {
  padding: 18px 20px;
}

.gk-entry-main {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.gk-entry-text {
  flex: 1 1 260px;
  min-width: 0;
}

.gk-entry-main :deep(.el-button) {
  margin-left: auto;
}
.gk-entry-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
}
.gk-entry-sub {
  margin-top: 6px;
  font-size: 13.5px;
  color: var(--el-text-color-secondary);
}
.gk-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.gk-summary {
  margin-bottom: 10px;
  font-size: 14px;
  color: var(--el-text-color-regular);
}
.gk-summary b {
  color: #18181b;
  font-size: 16px;
}
.gk-summary-note {
  font-size: 13.5px;
  color: var(--el-text-color-secondary);
}
.gk-table :deep(.el-table__row) {
  cursor: pointer;
}

/* 职位抽屉保持信息密度：行高收紧、列宽不动，一屏能多看几行 */
.gk-table :deep(.el-table__cell) {
  padding: 5px 0;
}
.gk-source {
  margin-top: 12px;
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
.gk-source a {
  margin-left: 6px;
  color: #2563eb;
}
.gk-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.gk-detail-block {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--el-fill-color-lighter);
  font-size: 14px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}
.gk-detail-block b {
  color: var(--el-text-color-primary);
}
.gk-detail-block p {
  margin: 4px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
