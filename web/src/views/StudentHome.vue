<template>
  <div class="page bento-page">
    <div class="bento-grid">
    <el-alert class="trust-bar bento-span-4" type="success" :closable="false" show-icon
      title="所有数值来自确定性引擎，经 Critic 审核通过" />

    <div class="live-bar bento-span-4">
      <span>数据于 {{ clock.ago(lastLoadAt) }}</span>
      <el-switch v-model="autoRefresh" size="small" active-text="30 秒自动刷新" />
      <el-button size="small" :loading="warningLoading || recLoading" @click="reloadAll">立即刷新</el-button>
      <button
        class="bell-btn"
        type="button"
        :class="{ 'has-new': unreadCnt > 0 }"
        :title="unreadCnt ? `${unreadCnt} 条新竞赛通知` : '暂无新竞赛通知'"
        @click="openNotices"
      >
        <svg viewBox="0 0 24 24" class="bell-icon" aria-hidden="true">
          <path d="M12 4a5 5 0 0 0-5 5v3l-1.5 2.5h13L17 12V9a5 5 0 0 0-5-5z" />
          <path d="M10 17.5a2 2 0 0 0 4 0" />
        </svg>
        <span>竞赛通知</span>
        <span v-if="unreadCnt" class="bell-badge">{{ unreadCnt > 99 ? '99+' : unreadCnt }}</span>
      </button>
      <span class="live-tip">不想问？点右下角 AI 小人直接提问</span>
    </div>

    <el-card v-loading="guideLoading" shadow="never" class="guide-card bento-span-2 bento-row-2">
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

    <el-card v-loading="warningLoading" shadow="never" class="info-card bento-span-2">
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

    <el-card shadow="never" class="quick-card bento-span-2">
      <template #header>
        <div class="card-title" style="margin: 0">快捷入口</div>
      </template>
      <div class="quick-grid">
        <router-link to="/student/grades" class="quick-item">
          <span class="quick-name">成绩单</span>
          <span class="quick-desc">每学年课程成绩</span>
        </router-link>
        <router-link to="/student/interview" class="quick-item">
          <span class="quick-name">模拟面试</span>
          <span class="quick-desc">简历出题 · 逐题点评</span>
        </router-link>
        <router-link to="/student/jobs" class="quick-item">
          <span class="quick-name">岗位库</span>
          <span class="quick-desc">按方向筛选岗位</span>
        </router-link>
        <router-link to="/student/exams" class="quick-item">
          <span class="quick-name">招考信息</span>
          <span class="quick-desc">考公 / 考编 / 考研</span>
        </router-link>
        <router-link to="/student/kg" class="quick-item">
          <span class="quick-name">知识图谱</span>
          <span class="quick-desc">专业—课程—岗位</span>
        </router-link>
      </div>
    </el-card>

    <el-card shadow="never" class="rec-card bento-span-4">
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
      <!-- 紧凑小格子：自适应列数 + 入场逐格浮现；点开看详情与行动清单 -->
      <div class="rec-grid">
        <div
          v-for="(item, index) in items"
          :key="item.job_id"
          class="rec-cell"
          role="button"
          tabindex="0"
          :style="{ animationDelay: `${Math.min(index, 8) * 45}ms` }"
          @click="openDetail(item)"
          @keyup.enter="openDetail(item)"
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
          <div v-if="item.peer_count" class="cell-peer" :title="item.reasons?.potential || ''">
            同段位 {{ item.peer_count }} 人关注 · 协同 {{ item.cf_score }}
          </div>
        </div>
      </div>
      <div class="engine-line">
        推荐引擎 {{ recs.recommend_version || '-' }} · 候选池 {{ recs.candidate_cnt ?? '-' }} 条
        <span v-if="recs.note" class="err">{{ recs.note }}</span>
      </div>
    </el-card>
    </div>

    <!-- 岗位详情抽屉：完整打分 + 建议 + 需要做的 + 该参加的比赛 -->
    <el-drawer v-model="detailOpen" :size="drawerSize" direction="rtl" :with-header="false">
      <div v-if="active" class="detail-shell drawer-panel">
        <header class="detail-head">
          <div class="detail-head-text">
            <div class="detail-title" :title="active.title">{{ active.title }}</div>
            <div class="detail-sub">{{ active.company || '公司未填' }} · {{ active.city || '城市不限' }}</div>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭详情" @click="detailOpen = false">
            <svg viewBox="0 0 24 24" class="ico"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </header>

        <div class="detail-body">
          <div class="detail-kpis">
            <div class="kpi">
              <div class="kpi-label">综合匹配</div>
              <div class="kpi-value">{{ fmtScore(active.final_score) }}</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">薪资区间</div>
              <div class="kpi-value small">{{ salaryText(active) }} 元/月</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">成绩门槛</div>
              <div class="kpi-value small">{{ active.min_gpa ?? '-' }} 分</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">同伴热度</div>
              <div class="kpi-value small">{{ active.peer_count ?? '—' }} 人</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">岗位方向</div>
              <div class="kpi-value small">{{ active.direction || '-' }}</div>
            </div>
          </div>

          <div class="sec-title">四维打分</div>
          <div class="dim-list">
            <div v-for="(value, key) in active.dims || {}" :key="key" class="dim-row">
              <span class="dim-name">{{ DIM_TEXT[key] || key }}</span>
              <span class="dim-bar"><i :style="{ width: `${Math.round(Number(value || 0) * 100)}%` }" /></span>
              <span class="dim-value">{{ fmtScore(value) }}</span>
            </div>
          </div>

          <div v-if="active.reasons" class="sec-title">三段式理由（内容 / 课程链 / 同伴证据）</div>
          <div v-if="active.reasons" class="reason-block">
            <div class="reason-row"><span class="rk">内容匹配</span><span>{{ active.reasons.knowledge }}</span></div>
            <div class="reason-row"><span class="rk">课程链</span><span>{{ active.reasons.skill }}</span></div>
            <div class="reason-row"><span class="rk">同伴证据</span><span>{{ active.reasons.potential }}</span></div>
            <div v-if="active.cf_score != null" class="reason-row">
              <span class="rk">协同权重</span><span>{{ active.cf_score }}（召回B，0.7×内容 + 0.3×协同）</span>
            </div>
          </div>

          <div class="sec-title">为什么推荐给你</div>
          <ul class="ul-hit">
            <li v-for="(t, i) in active.hit_items || []" :key="'h' + i">{{ t }}</li>
            <li v-if="!(active.hit_items || []).length">暂无可归因的命中项</li>
          </ul>

          <div class="sec-title">还差什么</div>
          <ul class="ul-gap">
            <li v-for="(t, i) in active.gap_items || []" :key="'g' + i">{{ t }}</li>
            <li v-if="!(active.gap_items || []).length">当前没有检测到明显缺口</li>
          </ul>

          <div class="sec-title">需要做的</div>
          <ol class="ol-action">
            <li v-for="(t, i) in active.action_items || []" :key="'a' + i">{{ t }}</li>
            <li v-if="!(active.action_items || []).length">{{ active.advice || '保持当前节奏即可' }}</li>
          </ol>

          <div class="sec-title">
            该参加的比赛
            <el-radio-group v-model="track" size="small" class="track-switch" @change="loadCompetitions">
              <el-radio-button value="就业">就业</el-radio-button>
              <el-radio-button value="考公">考公</el-radio-button>
            </el-radio-group>
          </div>
          <div v-if="compLoading" class="comp-loading">正在按你的方向筛选官方竞赛…</div>
          <div v-else-if="!(competitions.length)" class="comp-loading">暂无匹配的竞赛</div>
          <div v-else class="comp-list">
            <div v-for="c in competitions" :key="c.competition_id" class="comp-cell">
              <div class="comp-top">
                <span class="comp-cat" :class="'cat-' + String(c.category || '').toLowerCase()">
                  {{ c.category }} 类
                </span>
                <span class="comp-name" :title="c.name">{{ c.name }}</span>
              </div>
              <div class="comp-org">{{ c.org_unit }}</div>
              <div class="comp-why">{{ c.match_reason }}</div>
              <div v-if="c.reward" class="comp-reward">认定/奖励：{{ c.reward }}</div>
              <a class="comp-link" :href="c.source_url" target="_blank" rel="noopener">
                查看官方通知 →
              </a>
            </div>
          </div>
          <div class="engine-line">
            竞赛库 {{ comps.engine_version || '-' }} · 候选 {{ comps.candidate_cnt ?? '-' }} 项 ·
            来源：重庆财经学院教务处
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 竞赛通知中心：官方一发布即推送 -->
    <el-drawer v-model="noticeOpen" :size="drawerSize" direction="rtl" :with-header="false">
      <div class="detail-shell drawer-panel">
        <header class="detail-head">
          <div class="detail-head-text">
            <div class="detail-title">竞赛通知</div>
            <div class="detail-sub">重庆财经学院教务处发布，系统定期自动同步</div>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭通知" @click="noticeOpen = false">
            <svg viewBox="0 0 24 24" class="ico"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </header>
        <div class="detail-body">
          <el-empty v-if="!notices.length" description="暂无新通知" />
          <div v-for="n in notices" :key="n.title" class="notice-cell">
            <div class="notice-date">{{ n.published_at }}</div>
            <div class="notice-title">{{ n.title }}</div>
            <a class="comp-link" :href="n.url" target="_blank" rel="noopener">打开原文 →</a>
          </div>
          <div class="engine-line">已读水位：{{ lastReadAt || '未读' }}</div>
        </div>
      </div>
    </el-drawer>
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

const DIM_TEXT = {
  major_match: '专业匹配',
  gpa_gate: '成绩门槛',
  skill_cover: '技能覆盖',
  interest_fit: '兴趣方向'
}

// ---- 岗位详情抽屉 ----
const detailOpen = ref(false)
const active = ref(null)
const drawerSize = computed(() => (window.innerWidth < 768 ? '100%' : '480px'))
const track = ref('就业')
const compLoading = ref(false)
const comps = ref({})
const competitions = ref([])

async function openDetail(item) {
  active.value = item
  detailOpen.value = true
  await loadCompetitions()
}

async function loadCompetitions() {
  const item = active.value
  if (!item) return
  compLoading.value = true
  try {
    const { data } = await http.get('/student/competitions', {
      params: { track: track.value, direction: item.direction || '', job_title: item.title || '', limit: 6 }
    })
    comps.value = data || {}
    competitions.value = data?.items || []
  } catch (err) {
    comps.value = {}
    competitions.value = []
    ElMessage.error(err?.response?.data?.detail || '竞赛推荐加载失败')
  } finally {
    compLoading.value = false
  }
}

// ---- 竞赛通知推送 ----
const noticeOpen = ref(false)
const notices = ref([])
const unreadCnt = ref(0)
const lastReadAt = ref('')
let noticeTimer = null

async function loadNotices() {
  try {
    const { data } = await http.get('/student/notices', { params: { limit: 20 } })
    unreadCnt.value = Number(data?.unread_cnt || 0)
    lastReadAt.value = data?.last_read_at || ''
    if (!noticeOpen.value) return
    notices.value = data?.items || []
  } catch {
    unreadCnt.value = 0
  }
}

async function openNotices() {
  noticeOpen.value = true
  await loadNotices()
}

watch(noticeOpen, async (opened) => {
  if (opened) return
  if (!unreadCnt.value) return
  // 关闭通知即视为已读：把水位推到当前时间，之后的新通知才会再提醒
  try {
    await http.post('/student/notices/read')
    unreadCnt.value = 0
    await loadNotices()
  } catch {
    /* 标记失败不影响使用 */
  }
})

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
  await Promise.all([reloadAll(), loadGuide(), loadNotices()])
  // 每 60 秒查一次未读：官方发布新通知后，这里会自己亮红点
  noticeTimer = setInterval(loadNotices, 60000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (noticeTimer) clearInterval(noticeTimer)
})
</script>

<style scoped>
.trust-bar {
  margin-bottom: 0;
  font-weight: 600;
}

.live-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 0;
  font-size: 12px;
  color: #86909c;
  background: #fff;
  border: 1px solid #f4f4f5;
  border-radius: 14px;
  padding: 8px 14px;
}

.live-tip {
  margin-left: auto;
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.quick-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px;
  border: 1px solid #f4f4f5;
  border-radius: 16px;
  background: #fafafa;
  text-decoration: none;
  transition:
    transform 220ms var(--qh-ease),
    background-color 220ms var(--qh-ease),
    color 220ms var(--qh-ease);
}

.quick-item:hover {
  transform: translateY(-2px);
  background: #18181b;
  color: #fff;
}

.quick-name {
  font-size: 14px;
  font-weight: 600;
}

.quick-desc {
  font-size: 12px;
  color: #71717a;
}

.quick-item:hover .quick-desc {
  color: rgba(255, 255, 255, 0.76);
}

.guide-card,
.info-card,
.rec-card {
  margin-bottom: 0;
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

.cell-peer {
  font-size: 11px;
  color: var(--el-color-success);
  margin-top: 2px;
}
.reason-block { font-size: 13px; line-height: 1.7; }
.reason-row { display: flex; gap: 8px; margin: 4px 0; }
.reason-row .rk {
  flex: none; width: 64px; color: var(--el-text-color-secondary); font-size: 12px;
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

/* ---------- 竞赛通知铃铛 ---------- */
.bell-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--qh-border, #e4e4e7);
  border-radius: 8px;
  background: #ffffff;
  color: var(--qh-text-sub, #52525b);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.bell-btn:hover {
  background: #eff6ff;
  color: #1d4ed8;
}

.bell-btn.has-new {
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}

.bell-icon {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.bell-badge {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--qh-red, #dc2626);
  color: #ffffff;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
}

/* ---------- 详情 / 通知抽屉 ---------- */
.detail-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fafafa;
}

.detail-head {
  flex: 0 0 auto;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  background: #ffffff;
  border-bottom: 1px solid var(--qh-border, #e4e4e7);
}

.detail-head-text {
  min-width: 0;
}

.detail-title {
  font-size: 14px;
  font-weight: 600;
  color: #18181b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.detail-sub {
  font-size: 12px;
  color: #a1a1aa;
}

.icon-btn {
  width: 30px;
  height: 30px;
  margin-left: auto;
  border: 1px solid var(--qh-border, #e4e4e7);
  border-radius: 8px;
  background: #ffffff;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 150ms ease;
}

.icon-btn:hover {
  background: #f4f4f5;
}

.ico {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: #52525b;
  stroke-width: 1.8;
  stroke-linecap: round;
}

.detail-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 14px 16px 20px;
}

.detail-kpis {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.kpi {
  background: #ffffff;
  border: 1px solid var(--qh-border, #e4e4e7);
  border-radius: 8px;
  padding: 8px 10px;
}

.kpi-label {
  font-size: 12px;
  color: #a1a1aa;
}

.kpi-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--qh-red, #dc2626);
  font-variant-numeric: tabular-nums;
}

.kpi-value.small {
  font-size: 14px;
  color: #18181b;
}

.sec-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 16px 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: #18181b;
}

.track-switch {
  margin-left: auto;
}

.dim-list {
  background: #ffffff;
  border: 1px solid var(--qh-border, #e4e4e7);
  border-radius: 8px;
  padding: 10px;
}

.dim-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.dim-row + .dim-row {
  margin-top: 8px;
}

.dim-name {
  flex: 0 0 72px;
  color: #52525b;
}

.dim-bar {
  flex: 1 1 auto;
  height: 6px;
  border-radius: 8px;
  background: #f4f4f5;
  overflow: hidden;
}

.dim-bar i {
  display: block;
  height: 100%;
  background: #2563eb;
  border-radius: 8px;
}

.dim-value {
  flex: 0 0 56px;
  text-align: right;
  color: #18181b;
  font-variant-numeric: tabular-nums;
}

.ul-hit,
.ul-gap {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.9;
  color: #52525b;
}

.ul-gap {
  color: #b45309;
}

.ol-action {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 2;
  color: #18181b;
}

.comp-loading {
  font-size: 12px;
  color: #a1a1aa;
}

.comp-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.comp-cell {
  background: #ffffff;
  border: 1px solid var(--qh-border, #e4e4e7);
  border-radius: 8px;
  padding: 10px 12px;
}

.comp-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.comp-cat {
  flex: 0 0 auto;
  padding: 0 6px;
  border-radius: 8px;
  background: #eff6ff;
  border: 1px solid #dbeafe;
  color: #1d4ed8;
  font-size: 11px;
  line-height: 18px;
}

.comp-cat.cat-a {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
}

.comp-name {
  font-size: 13px;
  font-weight: 600;
  color: #18181b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.comp-org {
  margin-top: 2px;
  font-size: 12px;
  color: #a1a1aa;
}

.comp-why {
  margin-top: 4px;
  font-size: 12px;
  color: #52525b;
}

.comp-reward {
  margin-top: 4px;
  font-size: 11px;
  color: #a1a1aa;
}

.comp-link {
  display: inline-block;
  margin-top: 6px;
  font-size: 12px;
  color: #2563eb;
  text-decoration: none;
}

.comp-link:hover {
  text-decoration: underline;
}

.notice-cell {
  background: #ffffff;
  border: 1px solid var(--qh-border, #e4e4e7);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
}

.notice-date {
  font-size: 11px;
  color: #a1a1aa;
}

.notice-title {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.6;
  color: #18181b;
}

@media (prefers-reduced-motion: reduce) {
  .rec-cell {
    animation: none;
    transition: none;
  }

  .bell-btn,
  .icon-btn {
    transition: none;
  }
}
</style>
