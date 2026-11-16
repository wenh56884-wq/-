<template>
  <div ref="pageRoot" class="page bento-page">
    <div class="bento-grid">
    <!-- 航线页头：一句话结论 + 关键指标 + 主按钮。数值取自 class-overview / warnings 的分布 -->
    <RouteHero
      class="bento-span-4 hero-slot qh-reveal qh-hero"
      :style="{ '--qh-index': 0 }"
      tone="teacher"
      :eyebrow="`本学期结论 · ${overview.term || term || '-'}`"
      :title="heroConclusion"
      desc="班级概貌、预警名单与阈值同源同口径，未通过 Critic 回查的数字不会展示。"
      :stats="[
        { label: '红/橙/黄预警', value: warnTotal, suffix: '人', tone: 'red' },
        { label: '班级均分', value: gpaText },
        { label: '挂科率', value: fmtRate(overview.fail_rate) }
      ]"
    >
      <template #actions>
        <el-button type="primary" @click="goJobs">查看岗位</el-button>
        <el-button @click="goWarning">查看预警</el-button>
        <el-button @click="askAI('给我班级的整体学业情况')">问 AI</el-button>
      </template>
    </RouteHero>

    <section class="bento-card bento-span-4 filter-bar qh-reveal" :style="{ '--qh-index': 1 }">
      <el-form inline @submit.prevent>
        <el-form-item label="学院">
          <el-select
            v-model="college"
            clearable
            filterable
            placeholder="全部学院"
            style="width: 180px"
            @change="onCollegeChange"
          >
            <el-option v-for="c in colleges" :key="c.college" :label="c.college" :value="c.college">
              <span>{{ c.college }}</span>
              <span class="option-note">{{ c.class_cnt }} 班 / {{ c.student_cnt }} 人</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="专业">
          <el-select
            v-model="major"
            clearable
            filterable
            :placeholder="college ? '全部专业' : '请先选学院'"
            :disabled="!college"
            style="width: 200px"
            @change="onMajorChange"
          >
            <el-option v-for="m in majorOptions" :key="m.college + '/' + m.major" :label="m.major" :value="m.major">
              <span>{{ m.major }}</span>
              <span class="option-note">{{ m.class_cnt }} 班 / {{ m.student_cnt }} 人</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="班级">
          <el-select
            v-model="className"
            filterable
            :placeholder="classes.length ? '请选择班级' : '加载中…'"
            style="width: 200px"
            @change="onClassChange"
          >
            <el-option v-for="k in filteredClasses" :key="k.class_name" :label="k.class_name" :value="k.class_name">
              <span>{{ k.class_name }}</span>
              <span class="option-note">{{ k.headcount }} 人 · {{ majorLabel(k) }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="学期">
          <el-input v-model="term" placeholder="如 2025-2026-2" style="width: 160px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="loadAll">查询</el-button>
          <el-button @click="reset">重置</el-button>
          <el-button @click="openThresholds">预警阈值</el-button>
        </el-form-item>
      </el-form>
      <div class="engine-line">
        <span>引擎版本：{{ warnings.engine_version || overview.engine_version || '-' }}</span>
        <span>画像版本：{{ warnings.calc_version || overview.calc_version || '-' }}</span>
        <span>数据于 {{ clock.ago(lastLoadAt) }}</span>
        <span v-if="errorTip" class="err">{{ errorTip }}</span>
        <el-switch v-model="autoRefresh" size="small" active-text="自动刷新" class="auto-switch" />
        <router-link to="/teacher/students" class="to-files">看学生个人档案 →</router-link>
      </div>
    </section>

    <article class="bento-card stat-card stat-red qh-reveal" :style="{ '--qh-index': 2 }" role="button" tabindex="0"
      @click="goWarning" @keyup.enter="goWarning">
      <div class="stat-top">
        <span class="bento-icon qh-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M12 3l9 16H3L12 3z" /><path d="M12 9v4M12 16h.01" /></svg>
        </span>
        <span class="stat-label">红色预警</span>
        <span class="qh-arrow" aria-hidden="true">↗</span>
      </div>
      <div class="bento-stat"><count-number :value="dist.red" /></div>
    </article>

    <article class="bento-card stat-card stat-orange qh-reveal" :style="{ '--qh-index': 3 }" role="button" tabindex="0"
      @click="goWarning" @keyup.enter="goWarning">
      <div class="stat-top">
        <span class="bento-icon qh-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></svg>
        </span>
        <span class="stat-label">橙色预警</span>
        <span class="qh-arrow" aria-hidden="true">↗</span>
      </div>
      <div class="bento-stat"><count-number :value="dist.orange" /></div>
    </article>

    <article class="bento-card stat-card stat-yellow qh-reveal" :style="{ '--qh-index': 4 }" role="button" tabindex="0"
      @click="goWarning" @keyup.enter="goWarning">
      <div class="stat-top">
        <span class="bento-icon qh-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><path d="M12 4a6 6 0 0 0-6 6v4l-2 3h16l-2-3v-4a6 6 0 0 0-6-6z" /><path d="M10 19a2 2 0 0 0 4 0" /></svg>
        </span>
        <span class="stat-label">黄色预警</span>
        <span class="qh-arrow" aria-hidden="true">↗</span>
      </div>
      <div class="bento-stat"><count-number :value="dist.yellow" /></div>
    </article>

    <article class="bento-card stat-card stat-normal qh-reveal" :style="{ '--qh-index': 5 }" role="button" tabindex="0"
      @click="goOverview" @keyup.enter="goOverview">
      <div class="stat-top">
        <span class="bento-icon qh-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3" /><path d="M3 20a6 6 0 0 1 12 0M16 5a3 3 0 0 1 0 6M18 20a5 5 0 0 0-3-4.5" /></svg>
        </span>
        <span class="stat-label">班级人数 / 均分</span>
        <span class="qh-arrow" aria-hidden="true">↗</span>
      </div>
      <div class="bento-stat">
        <count-number :value="overview.headcount" />
        <span class="stat-sep">/</span>
        <count-number :value="overview.avg_gpa" :decimals="1" />
      </div>
    </article>

    <section ref="overviewCard" class="bento-card bento-span-2 bento-row-2 overview-card qh-reveal"
      :style="{ '--qh-index': 6 }"
      v-loading="loading">
      <div class="hero-head">
        <div>
          <p class="bento-eyebrow">班级概貌</p>
          <h2 class="hero-class-name">{{ overview.class_name || '请选择班级' }}</h2>
          <p class="bento-sub">{{ currentCollege || '—' }} · {{ currentMajors }}</p>
        </div>
        <el-tag size="small" effect="plain">{{ overview.term || term || '—' }}</el-tag>
      </div>

      <div class="hero-metrics">
        <div>
          <span>在册人数</span>
          <b><count-number :value="overview.headcount" /></b>
        </div>
        <div>
          <span>班级均分</span>
          <b><count-number :value="overview.avg_gpa" :decimals="1" /></b>
        </div>
        <div>
          <span>挂科率</span>
          <b>{{ fmtRate(overview.fail_rate) }}</b>
        </div>
        <div>
          <span>挂科人数</span>
          <b><count-number :value="overview.fail_students" /></b>
        </div>
      </div>

      <div class="hero-split">
        <div class="split-bar" aria-hidden="true">
          <span class="seg seg-red" :style="{ flex: dist.red || 0 }" />
          <span class="seg seg-orange" :style="{ flex: dist.orange || 0 }" />
          <span class="seg seg-yellow" :style="{ flex: dist.yellow || 0 }" />
          <span class="seg seg-none" :style="{ flex: dist.none || 0 }" />
        </div>
        <div class="split-legend">
          <span><i class="dot dot-red" />红 {{ dist.red || 0 }}</span>
          <span><i class="dot dot-orange" />橙 {{ dist.orange || 0 }}</span>
          <span><i class="dot dot-yellow" />黄 {{ dist.yellow || 0 }}</span>
          <span><i class="dot dot-none" />正常 {{ dist.none || 0 }}</span>
        </div>
      </div>

      <div class="hero-info">
        <div><span>学院</span><b>{{ currentCollege || '-' }}</b></div>
        <div><span>专业</span><b>{{ currentMajors || '-' }}</b></div>
      </div>

      <div class="hero-links">
        <router-link to="/teacher/students" class="hero-link">学生档案</router-link>
        <router-link to="/teacher/jobs" class="hero-link">岗位库</router-link>
        <router-link to="/teacher/exams" class="hero-link">招考信息</router-link>
        <router-link to="/teacher/kg" class="hero-link">知识图谱</router-link>
      </div>

      <div class="hero-foot">
        {{ overview.term || term || '-' }} · 引擎 {{ warnings.engine_version || overview.engine_version || '-' }}
        · 画像 {{ warnings.calc_version || overview.calc_version || '-' }} · 数据于 {{ clock.ago(lastLoadAt) }}
      </div>
    </section>

    <section class="bento-card bento-span-2 chart-card qh-reveal" :style="{ '--qh-index': 7 }" v-loading="loading">
      <div class="card-head">
        <h3 class="bento-title">预警等级分布</h3>
        <span class="bento-eyebrow">按当前班级</span>
      </div>
      <div ref="barRef" class="chart-box"></div>
    </section>

    <section class="bento-card bento-span-2 risk-card qh-reveal" :style="{ '--qh-index': 8 }">
      <div class="card-head">
        <h3 class="bento-title">高风险 Top5</h3>
        <span class="bento-eyebrow">点击行看画像</span>
      </div>
      <el-empty v-if="!overview.top_risk_students?.length" description="暂无数据" />
      <ul v-else class="risk-list">
        <li v-for="(s, i) in overview.top_risk_students" :key="s.student_no"
          class="risk-row" :style="{ '--qh-index': Math.min(i, 11) }">
          <el-tag :type="levelType(s.level)" size="small">{{ s.student_no }}</el-tag>
          <span class="risk-name">{{ s.name || '—' }}</span>
          <span class="risk-score">{{ s.risk_score }}</span>
        </li>
      </ul>
    </section>

    <section class="bento-card bento-span-4 intent-card qh-reveal" :style="{ '--qh-index': 10 }" v-loading="loading">
      <div class="intent-head">
        <span class="card-title" style="margin: 0">职业目标分布</span>
        <el-tag size="small" effect="plain">
          已填写 {{ overview.career_intent?.filled ?? 0 }} / {{ overview.career_intent?.total ?? 0 }} 人
        </el-tag>
      </div>
      <el-empty v-if="!(overview.career_intent?.total)" description="暂无学生数据" />
      <div v-else class="intent-grid">
        <div
          v-for="(item, i) in intentItems"
          :key="item.key"
          class="intent-item"
          :style="{ '--intent-color': item.color, '--qh-index': Math.min(i, 11) }"
        >
          <div class="intent-label">{{ item.label }}</div>
          <div class="intent-value"><count-number :value="item.value" /></div>
          <div class="intent-rate">{{ item.rate }}</div>
        </div>
      </div>
    </section>

    <section ref="warningTableCard" class="bento-card bento-span-4 table-card qh-reveal" :style="{ '--qh-index': 11 }">
      <div class="card-title">
        预警名单（点击行看四维画像）
        <el-tag v-if="!loading" size="small" :type="(warnings.items || []).length ? 'danger' : 'success'"
          effect="plain" class="wl-count">
          {{ (warnings.items || []).length }} 人
        </el-tag>
        <span class="wl-hint">仅列出红/橙/黄色预警学生；全班风险分布见上方图表，分数最高者见「高风险 Top5」</span>
      </div>
      <el-table
        v-loading="loading"
        :data="warnings.items || []"
        border
        stripe
        max-height="420"
        @row-click="openProfile"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-box">
              <div><b>归因：</b>
                <span v-if="!row.reasons?.length">无触发项</span>
                <span v-for="(r, i) in row.reasons" :key="i" class="reason">{{ r }}</span>
              </div>
              <div><b>可用指标：</b>{{ row.coverage }} 项<span v-if="row.missing?.length">（缺失：{{ row.missing.join('、') }}）</span></div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="student_no" label="学号" width="130" />
        <el-table-column prop="name" label="姓名" width="100" />
        <el-table-column label="等级" width="110">
          <template #default="{ row }">
            <el-tag :type="levelType(row.level)" effect="dark">{{ levelText(row.level) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="risk_score" label="风险分" width="100" sortable />
        <el-table-column label="归因摘要" min-width="280">
          <template #default="{ row }">
            <span v-if="row.reasons?.length" class="table-reason">
              {{ row.reasons[0] }}<template v-if="row.reasons.length > 1"> 等 {{ row.reasons.length }} 项</template>
            </span>
            <span v-else class="table-reason muted">无触发项</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openProfile(row)">画像</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !(warnings.items || []).length" description="本学期该班暂无红/橙/黄色预警学生（可看上方「高风险 Top5」提前关注）" />
    </section>
    </div>

    <el-dialog v-model="thresholdDialog" title="班级预警阈值" width="760px">
      <div class="threshold-head">
        <span>班级：<b>{{ className || '-' }}</b></span>
        <span class="muted">留空 = 回退租户默认 / 引擎默认</span>
      </div>
      <el-table v-loading="thresholdLoading" :data="thresholdRows" border size="small">
        <el-table-column prop="label" label="指标" width="110" />
        <el-table-column label="权重" width="115">
          <template #default="{ row }">
            <el-input-number
              v-if="row.metric !== 'level' && row.metric !== 'gpa_drop_slope'"
              v-model="row.weight" :min="0" :max="10" :step="0.1" size="small"
              controls-position="right" :value-on-clear="null"
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="黄色阈值" width="125">
          <template #default="{ row }">
            <el-input-number
              v-model="row.yellow_value" :min="0" :step="1" size="small"
              controls-position="right" :value-on-clear="null"
            />
          </template>
        </el-table-column>
        <el-table-column label="橙色阈值" width="125">
          <template #default="{ row }">
            <el-input-number
              v-if="row.metric !== 'gpa_drop_slope'"
              v-model="row.orange_value" :min="0" :step="1" size="small"
              controls-position="right" :value-on-clear="null"
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="红色阈值" width="125">
          <template #default="{ row }">
            <el-input-number
              v-if="row.metric !== 'gpa_drop_slope'"
              v-model="row.red_value" :min="0" :step="1" size="small"
              controls-position="right" :value-on-clear="null"
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ thresholdSourceText(row.source) }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div class="threshold-tip">{{ thresholdTip }}</div>
      <template #footer>
        <el-button @click="thresholdDialog = false">取消</el-button>
        <el-button type="primary" :loading="thresholdSaving" @click="saveThresholds">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="drawer" :title="`${profile.name || ''}（${profile.student_no || ''}）画像`" size="520px">
      <div v-loading="profileLoading" class="drawer-panel">
        <el-empty v-if="!profile.student_no && !profileLoading" description="未加载到画像" />
        <template v-else>
          <div class="profile-head">
            <div class="profile-avatar">{{ (profile.name || '?').slice(0, 1) }}</div>
            <div class="profile-head-main">
              <div class="profile-head-name">{{ profile.name || '—' }}</div>
              <div class="profile-head-sub">{{ profile.class_name || '—' }} · {{ profile.major || '—' }}</div>
            </div>
            <div class="profile-head-meta">
              <el-tag v-if="profile.grade" size="small" effect="plain" round>{{ profile.grade }}</el-tag>
              <span class="muted">画像 v{{ profile.calc_version || '-' }}</span>
            </div>
          </div>

          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="学院">{{ profile.college || '-' }}</el-descriptions-item>
            <el-descriptions-item label="专业">{{ profile.major || '-' }}</el-descriptions-item>
            <el-descriptions-item label="班级">{{ profile.class_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="数据源">{{ profile.source || '-' }}</el-descriptions-item>
          </el-descriptions>
          <div class="tag-line">
            <el-tag v-for="t in profile.tags || []" :key="t" class="tag-item" effect="light" round>{{ t }}</el-tag>
            <span v-if="!(profile.tags || []).length" class="muted">暂无画像标签</span>
          </div>

          <div class="card-title">四维画像</div>
          <div ref="radarRef" class="chart-box radar-box"></div>

          <div class="card-title">
            职业差距<template v-if="gap.target_direction">（目标方向：{{ gap.target_direction }}）</template>
          </div>
          <el-empty v-if="!gapLoading && gapEmpty" :image-size="88" :description="gapEmptyText" />
          <template v-else>
            <div v-show="!gapLoading" ref="gapRef" class="chart-box"></div>
            <div class="gap-note">口径：需求侧关键词出现率 − 班级具备率；≥30% 红档、≥10% 橙档</div>
          </template>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'

import http from '../api/http'
import router from '../router'
import CountNumber from '../components/CountNumber.vue'
import RouteHero from '../components/brand/RouteHero.vue'
import { useClock } from '../composables/useSystemStatus'
import { useReveal } from '../composables/useReveal'

// 入场编排：只给卡片加 opacity/transform 渐显；chart-box 高度固定，reveal 不影响 ECharts 初始化尺寸
const pageRoot = ref(null)
const { refresh } = useReveal(pageRoot)

function queueReveal() {
  nextTick(refresh)
}

const LEVEL_TEXT = { red: '红色', orange: '橙色', yellow: '黄色', none: '正常', unknown: '数据不足' }
const LEVEL_TYPE = { red: 'danger', orange: 'warning', yellow: 'warning', none: 'success', unknown: 'info' }
const COLORS = ['#e5484d', '#f5a623', '#f0c808', '#4cb971', '#5f6672']

const HISTORY_KEY = 'qh_class_history'
const className = ref(localStorage.getItem('qh_last_class') || '')
const term = ref('2025-2026-2')
const colleges = ref([])
const classes = ref([])
const majors = ref([])
const college = ref('')
const major = ref('')
const loading = ref(false)
const errorTip = ref('')
const autoRefresh = ref(false)
const lastLoadAt = ref(null)
let timer = null
const clock = useClock()
const overview = ref({})
const warnings = ref({})
const barRef = ref(null)
const radarRef = ref(null)
let barChart = null
let radarChart = null

const dist = computed(() => warnings.value.distribution || {})

// Hero：红/橙/黄合计与一句话结论，全部取自 /teacher/warnings 的分布与 /teacher/class-overview
const warnTotal = computed(() =>
  ['red', 'orange', 'yellow'].reduce((acc, key) => acc + Number(dist.value[key] || 0), 0)
)

const gpaText = computed(() => {
  const value = overview.value?.avg_gpa
  return value === null || value === undefined ? '-' : Number(value).toFixed(1)
})

const heroConclusion = computed(() => {
  const ov = overview.value || {}
  if (!ov.class_name) return '先在上方选择班级，即可看到本学期整体结论与预警名单'
  const total = Number(ov.headcount || 0)
  if (!warnTotal.value) {
    return `${ov.class_name} 本学期共 ${total} 人、均分 ${gpaText.value}，暂无红/橙/黄色预警学生`
  }
  const rate = total ? ((warnTotal.value / total) * 100).toFixed(1) : '-'
  return (
    `${ov.class_name} 本学期共 ${total} 人、均分 ${gpaText.value}，` +
    `红/橙/黄色预警 ${warnTotal.value} 人（占 ${rate}%），建议先看下方名单`
  )
})

const overviewCard = ref(null)
const warningTableCard = ref(null)

function scrollToCard(target) {
  const node = target.value?.$el || target.value
  node?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
}

function goJobs() {
  router.push('/teacher/jobs')
}

// 预警名单就在本页，主按钮滚动过去，而不是把教师带走
function goWarning() {
  scrollToCard(warningTableCard)
}

function goOverview() {
  scrollToCard(overviewCard)
}

// 让常驻的助手抽屉打开并自动发问：ShellLayout 不在本次改动范围，走窗口事件
function askAI(question) {
  window.dispatchEvent(new CustomEvent('qh:ask-ai', { detail: { question } }))
}

const INTENT_META = [
  { key: '考公', label: '考公', color: '#dc2626' },
  { key: '考研', label: '考研', color: '#d97706' },
  { key: '考编', label: '考编', color: '#16a34a' },
  { key: '就业', label: '就业', color: '#1951c3' },
  { key: '未填写', label: '未填写', color: '#9aa1ad' }
]

// 职业目标人数全部来自 /teacher/class-overview，前端只做展示，不做任何推断
const intentItems = computed(() => {
  const info = overview.value?.career_intent || {}
  const distMap = info.distribution || {}
  const total = Number(info.total || 0)
  return INTENT_META.map((item) => {
    const value = Number(distMap[item.key] || 0)
    return {
      ...item,
      value,
      rate: total ? `${((value / total) * 100).toFixed(1)}%` : '-'
    }
  })
})

const thresholdDialog = ref(false)
const thresholdLoading = ref(false)
const thresholdSaving = ref(false)
const thresholdRows = ref([])
const thresholdTip = ref('')
// 阈值列存的是「加权得分」而非原始门次/出勤率；不写清楚，教师按直觉填 1/2/3 或 0.9
// 会把整班风险分压到 0（2026-10-29 已踩过这个坑），所以打开弹窗先显示口径。
const THRESHOLD_TIP = '口径：挂科门次填加权得分（黄15/橙30/红45）；出勤率黄色=起算率、橙色=拿满率、红色=得分上限；均分下滑黄色=起算分差、橙色=起算固定分、红色=得分上限。'

const drawer = ref(false)
const profileLoading = ref(false)
const profile = ref({})
const gapLoading = ref(false)
const gap = ref({})
const gapRef = ref(null)
let gapChart = null

function levelText(level) {
  return LEVEL_TEXT[level] || level || '-'
}

function levelType(level) {
  return LEVEL_TYPE[level] || 'info'
}

function fmtRate(v) {
  return v === null || v === undefined ? '-' : `${(Number(v) * 100).toFixed(1)}%`
}

function rememberClass(name) {
  if (!name) return
  const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  const next = [name, ...history.filter((item) => item !== name)].slice(0, 10)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
  localStorage.setItem('qh_last_class', name)
}

// 三级级联：学院 → 专业 → 班级
const majorOptions = computed(() =>
  college.value ? majors.value.filter((item) => item.college === college.value) : []
)

const filteredClasses = computed(() => {
  let list = classes.value
  if (college.value) list = list.filter((item) => item.college === college.value)
  // 一个班可能挂多个专业，只要包含所选专业就算命中
  if (major.value) list = list.filter((item) => (item.majors || []).includes(major.value))
  return list
})

// 学院/专业取自己那份班级目录（同源数据），不依赖任何前端推断
const currentClassMeta = computed(() =>
  classes.value.find((item) => item.class_name === className.value) || null
)
const currentCollege = computed(() => currentClassMeta.value?.college || '')
const currentMajors = computed(() => (currentClassMeta.value?.majors || []).join('、') || '-')

// 班级目录来自后端（本租户可见范围），前端不做任何推断
async function loadDirectory() {
  try {
    const { data } = await http.get('/teacher/classes')
    classes.value = data?.classes || []
    colleges.value = data?.colleges || []
    majors.value = data?.majors || []
    if (!classes.value.length) {
      ElMessage.warning(data?.note || '当前账号未绑定任何任教班级，请联系管理员配置')
    }
    if (!className.value) {
      const remembered = localStorage.getItem('qh_last_class')
      const hit = classes.value.find((item) => item.class_name === remembered)
      className.value = hit ? hit.class_name : (classes.value[0]?.class_name || '')
      if (hit) {
        college.value = hit.college
        major.value = (hit.majors || [])[0] || ''
      }
    }
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '班级目录加载失败')
  }
}

// 班级选项里的专业标注：单专业直接显示，多专业显示数量
function majorLabel(item) {
  const list = item?.majors || []
  if (!list.length) return '专业未填'
  return list.length === 1 ? list[0] : `${list.length} 个专业`
}

// 换学院：专业清空，班级落到该学院第一个班
function onCollegeChange(value) {
  major.value = ''
  const list = value ? filteredClasses.value : classes.value
  if (!list.some((item) => item.class_name === className.value)) {
    className.value = list[0]?.class_name || ''
    rememberClass(className.value)
    loadClass()
  }
}

// 换专业：班级落到该专业第一个班
function onMajorChange() {
  const list = filteredClasses.value
  if (!list.some((item) => item.class_name === className.value)) {
    className.value = list[0]?.class_name || ''
    rememberClass(className.value)
    loadClass()
  }
}

async function loadClass(reportError = true) {
  const klass = String(className.value || '').trim()
  if (!klass) {
    ElMessage.warning('请先选择班级')
    return
  }
  rememberClass(klass)
  errorTip.value = ''
  try {
    const [ovRes, wnRes] = await Promise.all([
      http.get('/teacher/class-overview', { params: { class_name: klass, term: term.value } }),
      http.get('/teacher/warnings', { params: { class_name: klass, term: term.value, level: 'red,orange,yellow' } })
    ])
    overview.value = ovRes.data || {}
    warnings.value = wnRes.data || {}
    lastLoadAt.value = new Date()
    await nextTick()
    renderBar()
  } catch (err) {
    overview.value = {}
    warnings.value = {}
    if (reportError) {
      errorTip.value = err?.response?.data?.detail || '加载失败'
    }
    renderBar()
  }
  queueReveal()
}

async function loadAll() {
  loading.value = true
  try {
    await loadClass()
  } finally {
    loading.value = false
  }
}

function reset() {
  college.value = ''
  major.value = ''
  className.value = classes.value[0]?.class_name || ''
  term.value = '2025-2026-2'
  overview.value = {}
  warnings.value = {}
  errorTip.value = ''
  renderBar()
}

watch(autoRefresh, (on) => {
  if (timer) clearInterval(timer)
  timer = on ? setInterval(loadClass, 30000) : null
})

function onClassChange() {
  // 直接选班级时把上级两项补齐，保证三级筛选状态与当前班级一致
  const meta = classes.value.find((item) => item.class_name === className.value)
  if (meta) {
    if (!college.value) college.value = meta.college || ''
    if (!major.value) major.value = (meta.majors || [])[0] || ''
  }
  rememberClass(className.value)
  loadClass()
}

function renderBar() {
  if (!barRef.value) return
  barChart = barChart || echarts.init(barRef.value)
  const labels = ['红色', '橙色', '黄色', '正常', '数据不足']
  const keys = ['red', 'orange', 'yellow', 'none', 'unknown']
  barChart.setOption(
    {
      animationDuration: 800,
      animationEasing: 'cubicOut',
      grid: { left: 48, right: 16, top: 24, bottom: 32 },
      xAxis: { type: 'category', data: labels, axisLabel: { color: '#4e5969' } },
      yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#e4e7ee' } } },
      tooltip: { trigger: 'axis' },
      series: [
        {
          type: 'bar',
          barWidth: 36,
          label: { show: true, position: 'top' },
          data: keys.map((key, index) => ({
            value: dist.value[key] ?? 0,
            itemStyle: { color: COLORS[index], borderRadius: [4, 4, 0, 0] }
          }))
        }
      ]
    },
    true
  )
}

function thresholdSourceText(source) {
  const map = { class: '班级覆盖', tenant: '租户默认', default: '引擎默认' }
  return map[source] || source || '-'
}

async function openThresholds() {
  const klass = String(className.value || '').trim()
  if (!klass) {
    ElMessage.warning('请先选择班级')
    return
  }
  thresholdDialog.value = true
  thresholdLoading.value = true
  thresholdTip.value = THRESHOLD_TIP
  try {
    const { data } = await http.get('/teacher/warning-thresholds', {
      params: { class_name: klass }
    })
    thresholdRows.value = (data?.thresholds || []).map((row) => ({ ...row }))
  } catch (err) {
    thresholdTip.value = err?.response?.data?.detail || '阈值加载失败'
  } finally {
    thresholdLoading.value = false
  }
}

async function saveThresholds() {
  const klass = String(className.value || '').trim()
  if (!klass) return
  thresholdSaving.value = true
  thresholdTip.value = ''
  try {
    const payload = {
      thresholds: thresholdRows.value.map((row) => ({
        metric: row.metric,
        weight: row.weight,
        yellow_value: row.yellow_value,
        orange_value: row.orange_value,
        red_value: row.red_value
      }))
    }
    await http.put('/teacher/warning-thresholds', payload, {
      params: { class_name: klass }
    })
    ElMessage.success('阈值已保存，预警结果已按新口径重算')
    thresholdDialog.value = false
    await loadClass()
  } catch (err) {
    thresholdTip.value = err?.response?.data?.detail || '阈值保存失败'
  } finally {
    thresholdSaving.value = false
  }
}

async function openProfile(row) {
  drawer.value = true
  profileLoading.value = true
  profile.value = { student_no: row?.student_no, name: row?.name }
  renderRadar({})
  loadGap()
  try {
    const { data } = await http.get(`/teacher/student/${encodeURIComponent(row.student_no)}`, {
      params: { term: term.value }
    })
    profile.value = data || {}
    await nextTick()
    renderRadar(profile.value)
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '画像加载失败')
  } finally {
    profileLoading.value = false
  }
}

function renderRadar(data) {
  if (!radarRef.value) return
  radarChart = radarChart || echarts.init(radarRef.value)
  const dims = data?.dimensions || {}
  const names = { study: '学业', behavior: '行为', interest: '兴趣', ability: '能力' }
  const keys = Object.keys(names)
  radarChart.setOption(
    {
      animationDuration: 800,
      animationEasing: 'cubicOut',
      tooltip: { trigger: 'item' },
      radar: {
        indicator: keys.map((key) => ({ name: names[key], max: 1 })),
        radius: '66%',
        axisName: { color: '#4e5969' },
        splitArea: { areaStyle: { color: ['rgba(37, 99, 235, 0.03)', 'rgba(37, 99, 235, 0.06)'] } },
        splitLine: { lineStyle: { color: '#e4e7ee' } }
      },
      series: [
        {
          type: 'radar',
          areaStyle: { opacity: 0.18 },
          lineStyle: { color: '#1951c3', width: 2 },
          itemStyle: { color: '#1951c3' },
          symbolSize: 6,
          data: [
            {
              name: '四维画像',
              value: keys.map((key) => (dims[key] === null || dims[key] === undefined ? 0 : Number(dims[key])))
            }
          ]
        }
      ]
    },
    true
  )
}

// 职业差距是否无有效数据：接口没返回项，或所有维度的两侧比率都缺失（unknown）
const gapEmpty = computed(() => {
  if (gapLoading.value) return false
  const gaps = gap.value.gaps || []
  if (!gaps.length) return true
  return gaps.every((g) => g.class_rate == null && g.demand_rate == null)
})

// 空态要讲清楚原因，而不是渲染一张全是 0 的空图误导教师
const gapEmptyText = computed(() => {
  if (!gap.value.target_direction) {
    return '本班本学期暂无岗位浏览记录，无法确定目标方向与需求侧数据'
  }
  if (!gap.value.class_ability?.sample) {
    return '本班学生特征数据缺失，无法计算班级具备率'
  }
  return '岗位需求侧数据不足，暂时无法计算差距'
})

async function loadGap() {
  const klass = String(className.value || '').trim()
  if (!klass) return
  gapLoading.value = true
  try {
    const { data } = await http.get('/teacher/career-gap', {
      params: { class_name: klass, term: term.value }
    })
    gap.value = data || {}
    await nextTick()
    renderGap(gap.value)
  } catch (err) {
    gap.value = {}
    ElMessage.error(err?.response?.data?.detail || '职业差距加载失败')
  } finally {
    gapLoading.value = false
  }
}

function renderGap(data) {
  if (!gapRef.value) return
  gapChart = gapChart || echarts.init(gapRef.value)
  const rows = (data?.gaps || []).slice().reverse() // ECharts Y 轴自下而上，反转后顺序与接口一致
  gapChart.setOption(
    {
      animationDuration: 800,
      animationEasing: 'cubicOut',
      grid: { left: 80, right: 24, top: 28, bottom: 28 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { data: ['班级具备率', '岗位需求率'], textStyle: { color: '#4e5969' } },
      xAxis: { type: 'value', max: 1, splitLine: { lineStyle: { color: '#e4e7ee' } } },
      yAxis: {
        type: 'category',
        data: rows.map((row) => row.dimension),
        axisLabel: { color: '#4e5969' }
      },
      series: [
        {
          name: '班级具备率',
          type: 'bar',
          data: rows.map((row) => row.class_rate ?? 0),
          itemStyle: { color: '#4cb971', borderRadius: [0, 4, 4, 0] }
        },
        {
          name: '岗位需求率',
          type: 'bar',
          data: rows.map((row) => row.demand_rate ?? 0),
          itemStyle: {
            color: (params) => {
              const level = rows[params.dataIndex]?.level
              return level === 'red' ? '#e5484d' : level === 'orange' ? '#f5a623' : '#5f6672'
            },
            borderRadius: [0, 4, 4, 0]
          }
        }
      ]
    },
    true
  )
}

function onResize() {
  barChart?.resize()
  radarChart?.resize()
  gapChart?.resize()
}

watch(
  () => drawer.value,
  async (opened) => {
    if (opened) {
      await nextTick()
      radarChart?.resize()
    }
  }
)

onMounted(async () => {
  queueReveal()
  await loadDirectory()
  await loadAll()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('resize', onResize)
  barChart?.dispose()
  radarChart?.dispose()
  gapChart?.dispose()
  barChart = null
  radarChart = null
  gapChart = null
})
</script>

<style scoped>
.filter-bar {
  padding: 16px 18px;
}

.filter-bar :deep(.el-form-item) {
  margin-bottom: 10px;
}

.engine-line {
  font-size: 12px;
  color: #5f6672;
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.auto-switch {
  margin-left: auto;
}

.to-files {
  color: var(--qh-red);
  text-decoration: none;
  font-size: 12px;
}

.option-note {
  float: right;
  margin-left: 12px;
  font-size: 12px;
  color: #a9aeb8;
}

.err {
  color: var(--qh-red);
  margin-left: 12px;
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
  font-size: 13px;
  line-height: 1;
  color: #1951c3;
  opacity: 0;
  transform: translate(-2px, 2px);
  transition:
    opacity 180ms var(--bento-ease),
    transform 180ms var(--bento-ease);
}

.stat-card .qh-arrow {
  opacity: 0.45;
  transform: none;
}

.stat-card:hover .qh-arrow {
  opacity: 1;
  transform: translate(0, 0);
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 128px;
  cursor: pointer;
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

.stat-card .bento-icon {
  width: 38px;
  height: 38px;
  flex-basis: 38px;
}

.stat-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--qh-text-mute);
}

/* 三张预警统计卡保留语义色：数字按等级着色，图标块统一淡紫 */
.stat-red .bento-stat { color: var(--qh-red); }
.stat-orange .bento-stat { color: var(--qh-orange); }
.stat-yellow .bento-stat { color: #b98900; }

.stat-value {
  font-size: 24px;
  font-weight: 600;
  color: var(--qh-text);
  line-height: 1.3;
  font-variant-numeric: tabular-nums;
}

@media (min-width: 1024px) {
  .stat-value {
    font-size: 30px;
  }
}

.stat-value.small {
  font-size: 20px;
  color: var(--qh-text);
}

.stat-sep {
  margin: 0 6px;
  font-size: 18px;
  font-weight: 500;
  color: var(--bento-mute);
}

/* 班级概貌卡：已从 hero-card 改名，避免与顶部 Hero 撞样式（渐变紫底会让深色文字发灰） */
.overview-card {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 100%;
}

.hero-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.hero-class-name {
  margin: 0;
  font-size: clamp(26px, 2.6vw, 36px);
  font-weight: 700;
  line-height: 1.15;
  color: var(--bento-text);
}

.hero-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 16px 0;
  border-top: 1px solid var(--bento-border);
  border-bottom: 1px solid var(--bento-border);
}

.hero-metrics div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.hero-metrics span {
  font-size: 12px;
  color: var(--bento-mute);
}

.hero-metrics b {
  font-size: 24px;
  font-weight: 680;
  color: var(--bento-text);
  font-variant-numeric: tabular-nums;
}

.hero-split {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.split-bar {
  display: flex;
  height: 10px;
  gap: 2px;
  overflow: hidden;
  border-radius: 999px;
  background: #eef0f5;
}

.seg {
  display: block;
  height: 100%;
  min-width: 0;
}

.seg-red { background: #e5484d; }
.seg-orange { background: #f5a623; }
.seg-yellow { background: #f0c808; }
.seg-none { background: #4cb971; }

.split-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--bento-sub);
}

.split-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 999px;
}

.dot-red { background: #e5484d; }
.dot-orange { background: #f5a623; }
.dot-yellow { background: #f0c808; }
.dot-none { background: #4cb971; }

.hero-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hero-info div {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.hero-info span {
  flex: 0 0 40px;
  font-size: 12px;
  color: var(--bento-mute);
}

.hero-info b {
  font-size: 13px;
  font-weight: 500;
  line-height: 1.5;
  color: var(--bento-text);
}

.hero-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hero-link {
  padding: 6px 12px;
  border-radius: 999px;
  background: #eef0f5;
  color: var(--bento-sub);
  font-size: 12px;
  text-decoration: none;
  transition:
    background-color 200ms var(--bento-ease),
    color 200ms var(--bento-ease),
    transform 200ms var(--bento-ease);
}

.hero-link:hover {
  background: #16181d;
  color: #fff;
  transform: translateY(-1px);
}

.hero-foot {
  margin-top: auto;
  font-size: 12px;
  line-height: 1.6;
  color: var(--bento-mute);
}

.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.chart-card {
  display: flex;
  flex-direction: column;
}

.risk-card {
  display: flex;
  flex-direction: column;
}

.threshold-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--qh-text-sub);
}

.threshold-tip {
  min-height: 18px;
  margin-top: 8px;
  color: var(--qh-red);
  font-size: 12px;
}

.intent-card {
  margin-top: 0;
}

.intent-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.intent-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 16px;
}

.intent-item {
  border: 1px solid var(--qh-border);
  border-radius: 16px;
  background: #f7f8fa;
  padding: 14px 16px;
  transition: transform 220ms var(--bento-ease), box-shadow 220ms var(--bento-ease);
}

.intent-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(16, 24, 40, 0.06);
}

.intent-label {
  font-size: 13px;
  color: var(--qh-text-sub);
}

.intent-value {
  font-size: 26px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--intent-color);
  font-variant-numeric: tabular-nums;
}

.intent-rate {
  font-size: 12px;
  color: var(--qh-text-mute);
}

@media (max-width: 900px) {
  .intent-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.chart-box {
  height: 300px;
  width: 100%;
}

.radar-box {
  margin-top: 8px;
  height: 280px;
}

.profile-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  margin-bottom: 14px;
  /* Apple 风格：纯灰底，替代原来的淡蓝渐变 */
  background: #f7f8fa;
  border-radius: 14px;
}

.profile-avatar {
  flex: 0 0 44px;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: #1951c3;
  color: #fff;
  font-size: 20px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.profile-head-name {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.3;
}

.profile-head-sub {
  font-size: 12px;
  color: #5f6672;
  margin-top: 2px;
}

.profile-head-meta {
  margin-left: auto;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.drawer-panel :deep(.el-descriptions) {
  margin-bottom: 4px;
}

.table-card {
  margin-top: 0;
}

.table-card .card-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.wl-count {
  margin-left: 2px;
}

.wl-hint {
  font-size: 12px;
  font-weight: 400;
  color: var(--bento-sub, #8a919f);
  white-space: normal;
}

.expand-box {
  padding: 4px 12px;
  font-size: 13px;
  color: #4e5969;
  line-height: 1.9;
}

.table-reason {
  font-size: 13px;
  color: var(--bento-sub);
}

.table-reason.muted {
  color: var(--bento-mute);
}

.reason {
  margin-left: 8px;
  background: #f2f3f5;
  border-radius: 4px;
  padding: 2px 6px;
}

.risk-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.risk-list li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  font-size: 13px;
}

.risk-name {
  color: #4e5969;
}

.risk-score {
  margin-left: auto;
  font-weight: 600;
  color: var(--qh-red);
}

.gap-note {
  font-size: 12px;
  color: #5f6672;
  margin-top: 6px;
}

.tag-line {
  margin: 12px 0 4px;
}

.tag-item {
  margin-right: 6px;
}
/* ---------- 入场动效（仅 transform/opacity/filter，不改布局尺寸） ---------- */
/* Hero 光斑：一道极淡的斜向高光缓慢扫过，本页唯一的无限点缀 */
.qh-hero::after {
  content: '';
  position: absolute;
  z-index: 0;
  top: -60%;
  left: -30%;
  width: 40%;
  height: 220%;
  background: linear-gradient(100deg, transparent 40%, rgba(255, 255, 255, 0.06) 50%, transparent 60%);
  transform: translateX(-60%) rotate(12deg);
  animation: hero-sweep 9s ease-in-out infinite;
  pointer-events: none;
}

@keyframes hero-sweep {
  0%, 55% { opacity: 0; transform: translateX(-60%) rotate(12deg); }
  70% { opacity: 1; }
  90%, 100% { opacity: 0; transform: translateX(320%) rotate(12deg); }
}

/* Hero 关键数字：一次性浮入强调，不做数字滚动改写（CountNumber 保持原样） */
.qh-hero :deep(.route-stat) {
  animation: stat-in 560ms var(--bento-ease, ease) backwards;
}

.qh-hero :deep(.route-stat:nth-child(2)) { animation-delay: 100ms; }
.qh-hero :deep(.route-stat:nth-child(3)) { animation-delay: 200ms; }

@keyframes stat-in {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: none; }
}

/* 高风险 Top5 / 职业目标格：逐行浮入；fill=backwards 结束后不锁 transform，hover 位移仍生效 */
.risk-row,
.intent-item {
  animation: row-in 420ms var(--bento-ease, ease) backwards;
  animation-delay: calc(var(--qh-index, 0) * 60ms);
}

@keyframes row-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}

@media (prefers-reduced-motion: reduce) {
  .qh-hero::after,
  .qh-hero :deep(.route-stat),
  .risk-row,
  .intent-item {
    animation: none;
  }

  .stat-card,
  .intent-item,
  .hero-link {
    transition: none;
  }

  .stat-card:hover,
  .intent-item:hover,
  .hero-link:hover {
    transform: none;
  }
}

/* 触屏设备关闭 hover 位移，避免点按后卡片卡在浮起态 */
@media (pointer: coarse) {
  .stat-card:hover,
  .intent-item:hover,
  .hero-link:hover {
    transform: none;
  }
}
</style>
