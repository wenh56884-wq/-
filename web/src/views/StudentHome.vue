<template>
  <div class="page">
    <el-alert class="trust-bar" type="success" :closable="false" show-icon
      title="所有数值来自确定性引擎，经 Critic 审核通过" />

    <div class="live-bar">
      <span>数据于 {{ clock.ago(lastLoadAt) }}</span>
      <el-switch v-model="autoRefresh" size="small" active-text="30 秒自动刷新" />
      <el-button size="small" :loading="warningLoading || recLoading" @click="reloadAll">立即刷新</el-button>
      <span class="live-tip">不想问？点右下角 AI 小人直接提问</span>
    </div>

    <el-card v-loading="guideLoading" shadow="never" class="guide-card">
      <template #header>
        <div class="guide-head">
          <span class="card-title" style="margin: 0">生涯规划</span>
          <el-tag size="small" effect="plain">{{ guide.grade || '年级未知' }}</el-tag>
          <el-tag v-if="guide.intent" size="small" type="success" effect="dark">{{ guide.intent }}</el-tag>
          <el-tag v-if="guide.needs_intent" size="small" type="warning" effect="dark">待选方向</el-tag>
        </div>
      </template>

      <template v-if="guide.needs_intent">
        <el-alert type="warning" :closable="false" show-icon
          title="大一新生先选定方向：考公 / 考研 / 考编 / 就业。选定后系统生成四年规划。" />
        <div class="intent-row">
          <el-radio-group v-model="selectedIntent">
            <el-radio-button v-for="opt in guide.options || []" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </el-radio-button>
          </el-radio-group>
          <el-button type="primary" :loading="intentSaving" :disabled="!selectedIntent" @click="saveIntent">
            保存目标并生成规划
          </el-button>
        </div>
        <div class="intent-desc">{{ selectedIntentDesc }}</div>
      </template>

      <template v-else>
        <div class="guide-headline">{{ guide.headline }}</div>
        <div class="guide-meta">
          <span>方向：<b>{{ guide.direction?.name || '待探索' }}</b></span>
          <span class="muted">（{{ directionSourceText }}）</span>
          <el-button link type="primary" @click="showIntentPicker = !showIntentPicker">
            {{ showIntentPicker ? '收起' : '调整目标' }}
          </el-button>
        </div>

        <div v-if="showIntentPicker" class="intent-row">
          <el-radio-group v-model="selectedIntent">
            <el-radio-button v-for="opt in guide.options || []" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </el-radio-button>
          </el-radio-group>
          <el-button type="primary" :loading="intentSaving" :disabled="!selectedIntent" @click="saveIntent">
            保存目标
          </el-button>
        </div>

        <div class="guide-steps">
          <div v-for="(step, index) in guide.steps || []" :key="index" class="guide-step">
            <div class="step-head">
              <span class="step-index">{{ index + 1 }}</span>
              <span class="step-stage">{{ step.阶段 }}</span>
            </div>
            <div class="step-goal">{{ step.目标 }}</div>
            <ul class="step-actions">
              <li v-for="(action, i) in step.行动 || []" :key="i">{{ action }}</li>
            </ul>
          </div>
        </div>
        <div class="engine-line">
          规划引擎 {{ guide.engine_version || '-' }} · {{ guide.note }}
          <span v-if="guideTip" class="err">{{ guideTip }}</span>
        </div>
      </template>
    </el-card>

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
      <!-- 紧凑小格子：自适应列数 + 入场逐格浮现 -->
      <div class="rec-grid">
        <div
          v-for="(item, index) in items"
          :key="item.job_id"
          class="rec-cell"
          :style="{ animationDelay: `${Math.min(index, 8) * 45}ms` }"
        >
          <div class="cell-top">
            <span class="cell-index">{{ index + 1 }}</span>
            <span class="cell-score" :title="`匹配度 ${fmtScore(item.final_score)}`">
              {{ fmtScore(item.final_score) }}
            </span>
          </div>
          <div class="cell-title" :title="item.title">{{ item.title }}</div>
          <div class="cell-meta" :title="`${item.company || ''} · ${item.city || '城市不限'}`">
            {{ item.company || '公司未填' }} · {{ item.city || '城市不限' }}
          </div>
          <div class="cell-salary">{{ salaryText(item) }} 元/月</div>
          <div class="cell-tags">
            <span v-for="(t, i) in (item.hit_items || []).slice(0, 2)" :key="'h' + i" class="mini-tag hit">
              ✓ {{ t }}
            </span>
            <span v-for="(t, i) in (item.gap_items || []).slice(0, 1)" :key="'g' + i" class="mini-tag gap">
              △ {{ t }}
            </span>
            <span
              v-if="(item.hit_items || []).length + (item.gap_items || []).length > 3"
              class="mini-tag more"
              :title="[...(item.hit_items || []), ...(item.gap_items || [])].join('、')"
            >+{{ (item.hit_items || []).length + (item.gap_items || []).length - 3 }}</span>
          </div>
          <div class="cell-advice" :title="item.advice || ''">建议：{{ item.advice || '—' }}</div>
        </div>
      </div>
      <div class="engine-line">
        推荐引擎 {{ recs.recommend_version || '-' }} · 候选池 {{ recs.candidate_cnt ?? '-' }} 条
        <span v-if="recs.note" class="err">{{ recs.note }}</span>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
const guideLoading = ref(false)
const guideTip = ref('')
const intentSaving = ref(false)
const guide = ref({})
const selectedIntent = ref('')
const showIntentPicker = ref(false)
const warningLoading = ref(false)
const recLoading = ref(false)
const warningTip = ref('')
const recTip = ref('')
const warning = ref({})
const recs = ref({})
const items = ref([])

const directionSourceText = computed(() => {
  const map = { 'profile.interest': '来自画像兴趣', intent: '由目标推导', none: '待补充' }
  return map[guide.value?.direction?.source] || '待补充'
})

const selectedIntentDesc = computed(() => {
  const opt = (guide.value?.options || []).find((item) => item.value === selectedIntent.value)
  return opt?.desc || ''
})

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

async function loadGuide() {
  guideLoading.value = true
  guideTip.value = ''
  try {
    const { data } = await http.get('/career/guide', { params: { term: term.value } })
    guide.value = data || {}
    selectedIntent.value = data?.intent || ''
  } catch (err) {
    guide.value = {}
    guideTip.value = err?.response?.data?.detail || '生涯规划加载失败'
  } finally {
    guideLoading.value = false
  }
}

async function saveIntent() {
  const value = String(selectedIntent.value || '').trim()
  if (!value) {
    ElMessage.warning('请先选择目标')
    return
  }
  intentSaving.value = true
  try {
    await http.put('/career/intent', { intent: value })
    ElMessage.success(`已保存目标：${value}`)
    showIntentPicker.value = false
    await loadGuide()
  } catch (err) {
    const detail = err?.response?.data?.detail || '目标保存失败'
    ElMessage.error(detail)
    guideTip.value = detail
  } finally {
    intentSaving.value = false
  }
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
  // 规划卡不参与 30 秒自动刷新：避免学生正在选择目标时被定时请求重置选项
  await Promise.all([loadWarning(), loadRecommendations()])
  lastLoadAt.value = new Date()
}

watch(autoRefresh, (on) => {
  if (timer) clearInterval(timer)
  timer = on ? setInterval(reloadAll, 30000) : null
})

onMounted(async () => {
  await Promise.all([reloadAll(), loadGuide()])
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

.guide-card,
.info-card {
  margin-bottom: 12px;
}

.guide-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.guide-headline {
  font-size: 16px;
  font-weight: 600;
  margin: 4px 0 8px;
}

.guide-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
  color: #4e5969;
  margin-bottom: 10px;
}

.intent-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.intent-desc {
  font-size: 12px;
  color: #86909c;
  margin-top: 8px;
}

.guide-steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  margin-top: 10px;
}

.guide-step {
  border: 1px solid #e5e6eb;
  border-radius: 6px;
  padding: 10px 12px;
  background: #fff;
}

.step-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-index {
  width: 20px;
  height: 20px;
  border-radius: 8px;
  background: var(--qh-red);
  color: #fff;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.step-stage {
  font-weight: 600;
}

.step-goal {
  font-size: 12px;
  color: #4e5969;
  margin: 6px 0;
}

.step-actions {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  color: #4e5969;
  line-height: 1.8;
}

.muted {
  color: #86909c;
  font-size: 12px;
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

/* 推荐小格子：自适应列数，窄屏 1 列，中屏 2 列，宽屏 3 列 */
.rec-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 10px;
}

.rec-cell {
  border: 1px solid var(--qh-border);
  border-radius: var(--qh-radius-lg);
  padding: 10px 12px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  animation: cell-in 220ms ease-out both;
  transition: transform 150ms ease, box-shadow 150ms ease;
}

.rec-cell:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(24, 24, 27, 0.08);
}

@keyframes cell-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.cell-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cell-index {
  width: 20px;
  height: 20px;
  line-height: 20px;
  text-align: center;
  border-radius: 8px;
  background: var(--qh-red);
  color: #fff;
  font-size: 11px;
}

.cell-score {
  font-size: 13px;
  font-weight: 600;
  color: var(--qh-red);
  font-variant-numeric: tabular-nums;
}

.cell-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--qh-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-meta {
  font-size: 12px;
  color: var(--qh-text-sub);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-salary {
  font-size: 13px;
  color: var(--qh-orange);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.cell-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-height: 20px;
}

.mini-tag {
  font-size: 11px;
  line-height: 18px;
  padding: 0 6px;
  border-radius: 8px;
  border: 1px solid var(--qh-border);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.mini-tag.hit {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
}

.mini-tag.gap {
  background: #fffbeb;
  border-color: #fde68a;
  color: #b45309;
}

.mini-tag.more {
  background: #f4f4f5;
  color: var(--qh-text-sub);
  cursor: help;
}

.cell-advice {
  font-size: 12px;
  color: var(--qh-text-sub);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

@media (prefers-reduced-motion: reduce) {
  .rec-cell {
    animation: none;
    transition: none;
  }
}
</style>
