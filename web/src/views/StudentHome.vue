<template>
  <div class="page">
    <el-alert class="trust-bar" type="success" :closable="false" show-icon
      title="所有数值来自确定性引擎，经 Critic 审核通过" />

    <div class="live-bar">
      <span>数据于 {{ clock.ago(lastLoadAt) }}</span>
      <el-switch v-model="autoRefresh" size="small" active-text="30 秒自动刷新" />
      <el-button size="small" :loading="warningLoading || recLoading" @click="reloadAll">立即刷新</el-button>
      <span class="live-tip">不想问？去「智能助手」直接提问</span>
    </div>

    <el-card v-loading="warningLoading" shadow="never" class="info-card">
      <div class="card-title">本人信息</div>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="学号">{{ warning.student_no || '-' }}</el-descriptions-item>
        <el-descriptions-item label="姓名">{{ warning.name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="学期">{{ warning.term || '-' }}</el-descriptions-item>
        <el-descriptions-item label="预警等级">
          <el-tag :type="levelType(warning.level)" effect="dark">{{ levelText(warning.level) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="风险分">
          <span class="risk-score"><count-number :value="warning.risk_score" /></span>
        </el-descriptions-item>
        <el-descriptions-item label="可用指标">
          {{ warning.coverage ?? '-' }} 项
          <span v-if="warning.missing?.length" class="missing">（缺失：{{ warning.missing.join('、') }}）</span>
        </el-descriptions-item>
      </el-descriptions>

      <div class="card-title reason-title">预警归因</div>
      <el-empty v-if="warningLoading === false && !(warning.reasons || []).length" description="本学期暂无触发项" />
      <div v-else class="reason-line">
        <el-tag v-for="(item, index) in warning.reasons || []" :key="index" type="danger" effect="plain">
          {{ item }}
        </el-tag>
      </div>

      <div class="card-title reason-title">本人指标</div>
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="均分">{{ metric('gpa') }}</el-descriptions-item>
        <el-descriptions-item label="成绩下滑">{{ metric('gpa_drop') }}</el-descriptions-item>
        <el-descriptions-item label="出勤率">{{ metricRate('attendance_rate') }}</el-descriptions-item>
        <el-descriptions-item label="班级排名百分位">{{ metric('class_rank_pct') }}</el-descriptions-item>
      </el-descriptions>
      <div class="engine-line">
        预警引擎 {{ warning.engine_version || '-' }} · 画像版本 {{ warning.calc_version || '-' }}
        <span v-if="warningTip" class="err">{{ warningTip }}</span>
      </div>
    </el-card>

    <el-card shadow="never" class="rec-card">
      <template #header>
        <div class="rec-head">
          <span class="card-title" style="margin: 0">岗位推荐</span>
          <el-input-number v-model="topN" :min="1" :max="20" size="small" />
          <el-button type="primary" size="small" :loading="recLoading" @click="loadRecommendations">
            刷新推荐
          </el-button>
        </div>
      </template>

      <el-empty v-if="!recLoading && !items.length" :description="recTip || '暂无推荐结果'" />
      <div v-for="(item, index) in items" :key="item.job_id" class="rec-item">
        <div class="rec-top">
          <span class="rec-index">{{ index + 1 }}</span>
          <span class="rec-title">{{ item.title }}</span>
          <span class="rec-company">{{ item.company }}</span>
          <span class="rec-city">{{ item.city || '城市不限' }}</span>
          <span class="rec-salary">{{ salaryText(item) }}</span>
          <span class="rec-score">匹配度 {{ fmtScore(item.final_score) }}</span>
        </div>
        <div class="rec-tags">
          <el-tag type="success" size="small" effect="plain"
            v-for="(t, i) in item.hit_items || []" :key="'h' + i">✓ {{ t }}</el-tag>
          <el-tag type="warning" size="small" effect="plain"
            v-for="(t, i) in item.gap_items || []" :key="'g' + i">△ {{ t }}</el-tag>
        </div>
        <div class="rec-advice">建议：{{ item.advice || '—' }}</div>
      </div>
      <div class="engine-line">
        推荐引擎 {{ recs.recommend_version || '-' }} · 候选池 {{ recs.candidate_cnt ?? '-' }} 条
        <span v-if="recs.note" class="err">{{ recs.note }}</span>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import http from '../api/http'
import CountNumber from '../components/CountNumber.vue'
import { useClock } from '../composables/useSystemStatus'

const LEVEL_TEXT = { red: '红色预警', orange: '橙色预警', yellow: '黄色预警', none: '正常', unknown: '数据不足' }
const LEVEL_TYPE = { red: 'danger', orange: 'warning', yellow: 'warning', none: 'success', unknown: 'info' }

const autoRefresh = ref(false)
const lastLoadAt = ref(null)
let timer = null
const clock = useClock()

const term = ref('2025-2026-2')
const topN = ref(5)
const warningLoading = ref(false)
const recLoading = ref(false)
const warningTip = ref('')
const recTip = ref('')
const warning = ref({})
const recs = ref({})
const items = ref([])

function levelText(level) {
  return LEVEL_TEXT[level] || level || '-'
}

function levelType(level) {
  return LEVEL_TYPE[level] || 'info'
}

function metric(key) {
  const value = warning.value?.metrics?.[key]
  return value === null || value === undefined ? '-' : value
}

function metricRate(key) {
  const value = warning.value?.metrics?.[key]
  return value === null || value === undefined ? '-' : `${(Number(value) * 100).toFixed(1)}%`
}

function fmtScore(score) {
  return score === null || score === undefined ? '-' : Number(score).toFixed(4)
}

function salaryText(item) {
  const min = item.salary_min
  const max = item.salary_max
  if (min === null || min === undefined || max === null || max === undefined) return '薪资面议'
  return `${Math.round(Number(min))}-${Math.round(Number(max))}`
}

async function loadWarning() {
  warningLoading.value = true
  warningTip.value = ''
  try {
    const { data } = await http.get('/student/warning', { params: { term: term.value } })
    warning.value = data || {}
  } catch (err) {
    warning.value = {}
    warningTip.value = err?.response?.data?.detail || '预警数据加载失败'
  } finally {
    warningLoading.value = false
  }
}

async function loadRecommendations() {
  recLoading.value = true
  recTip.value = ''
  try {
    const { data } = await http.get('/student/recommendations', {
      params: { term: term.value, top_n: topN.value }
    })
    recs.value = data || {}
    items.value = data?.items || []
    if (!items.value.length) {
      recTip.value = data?.note || '本学期没有可用推荐（成绩或专业数据不足）'
    }
  } catch (err) {
    recs.value = {}
    items.value = []
    recTip.value = err?.response?.data?.detail || '推荐数据加载失败'
    ElMessage.error(recTip.value)
  } finally {
    recLoading.value = false
  }
}

async function reloadAll() {
  await Promise.all([loadWarning(), loadRecommendations()])
  lastLoadAt.value = new Date()
}

watch(autoRefresh, (on) => {
  if (timer) clearInterval(timer)
  timer = on ? setInterval(reloadAll, 30000) : null
})

onMounted(async () => {
  await reloadAll()
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.trust-bar {
  margin-bottom: 12px;
  font-weight: 600;
}

.live-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 12px;
  font-size: 12px;
  color: #86909c;
  background: #fff;
  border: 1px solid #e5e6eb;
  border-radius: 6px;
  padding: 6px 12px;
}

.live-tip {
  margin-left: auto;
}

.info-card {
  margin-bottom: 12px;
}

.reason-title {
  margin-top: 12px;
}

.reason-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.risk-score {
  font-size: 18px;
  font-weight: 600;
  color: var(--qh-red);
}

.missing {
  color: #86909c;
}

.engine-line {
  margin-top: 10px;
  font-size: 12px;
  color: #86909c;
}

.err {
  color: var(--qh-red);
  margin-left: 10px;
}

.rec-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.rec-item {
  border: 1px solid #e5e6eb;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: #fff;
}

.rec-top {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.rec-index {
  width: 22px;
  height: 22px;
  line-height: 22px;
  text-align: center;
  border-radius: 50%;
  background: var(--qh-red);
  color: #fff;
  font-size: 12px;
}

.rec-title {
  font-weight: 600;
}

.rec-company,
.rec-city {
  color: #4e5969;
  font-size: 13px;
}

.rec-salary {
  color: var(--qh-orange);
  font-size: 13px;
}

.rec-score {
  margin-left: auto;
  font-weight: 600;
  color: var(--qh-red);
}

.rec-tags {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.rec-advice {
  margin-top: 6px;
  font-size: 13px;
  color: #4e5969;
}
</style>
