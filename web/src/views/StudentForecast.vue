<template>
  <div class="page bento-page">
    <div class="bento-grid">
      <el-alert class="trust-bar bento-span-4" type="success" :closable="false" show-icon
        title="预测数值来自确定性引擎（按学期序列加权回归外推），非大模型生成" />

      <div class="live-bar bento-span-4">
        <span v-if="data.available">
          预测目标学期 {{ data.next_term }}（基线 {{ data.base_term }}）
        </span>
        <span v-else>暂不可预测</span>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
      </div>

      <el-card v-loading="loading" shadow="never" class="bento-span-2">
        <template #header>
          <span class="card-title">下学期均分预测</span>
        </template>
        <template v-if="gpa.predicted !== null && gpa.predicted !== undefined">
          <div class="fc-hero">{{ gpa.predicted }}</div>
          <div class="fc-sub">
            95% 区间 {{ gpa.low }} ~ {{ gpa.high }}
          </div>
          <div class="fc-tags">
            <el-tag size="small" :type="trendType(gpa.trend)">趋势 {{ gpa.trend }}</el-tag>
            <el-tag size="small" effect="plain">斜率 {{ gpa.slope }} 分/学期</el-tag>
            <el-tag size="small" effect="plain">置信 {{ gpa.confidence }}（{{ gpa.terms_used }} 学期）</el-tag>
          </div>
        </template>
        <el-empty v-else description="历史学期不足，无法预测" :image-size="60" />
      </el-card>

      <el-card v-loading="loading" shadow="never" class="bento-span-2">
        <template #header>
          <span class="card-title">挂科风险 / 预警走向</span>
        </template>
        <template v-if="data.available">
          <div class="fc-hero">
            {{ fail.predicted === null || fail.predicted === undefined ? '—' : fail.predicted }}
            <span class="fc-unit">门</span>
          </div>
          <div class="fc-sub">下学期预计挂科门数（趋势 {{ fail.trend }}）</div>
          <div class="fc-tags">
            <el-tag size="small" :type="levelType(level.level)">
              预警走向 {{ levelText(level.level) }}
            </el-tag>
            <el-tag size="small" effect="plain">风险分 {{ level.risk_score ?? '—' }}</el-tag>
          </div>
          <ul v-if="level.reasons?.length" class="fc-reasons">
            <li v-for="(r, i) in level.reasons" :key="i">{{ r }}</li>
          </ul>
        </template>
        <el-empty v-else description="暂无预测" :image-size="60" />
      </el-card>

      <el-card v-loading="loading" shadow="never" class="bento-span-4">
        <template #header>
          <span class="card-title">历史学期序列（预测依据）</span>
        </template>
        <el-table v-if="history.length" :data="history" size="small" max-height="240">
          <el-table-column prop="term" label="学期" width="130" />
          <el-table-column prop="gpa" label="均分" width="100" />
          <el-table-column prop="fail_count" label="挂科门数" width="100" />
          <el-table-column prop="course_count" label="课程数" />
        </el-table>
        <el-empty v-else description="无历史成绩" :image-size="60" />
      </el-card>

      <el-card v-loading="loading" shadow="never" class="bento-span-4">
        <template #header>
          <span class="card-title">需重点补强的课程</span>
        </template>
        <el-table v-if="risky.length" :data="risky" size="small" max-height="240">
          <el-table-column prop="course_name" label="课程" min-width="140" />
          <el-table-column prop="last_score" label="最近得分" width="100" />
          <el-table-column label="该课挂科率" width="110">
            <template #default="{ row }">{{ pct(row.course_fail_rate) }}</template>
          </el-table-column>
          <el-table-column label="风险" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="riskType(row.risk_level)">{{ row.risk_level }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无薄弱课程" :image-size="60" />

        <div v-if="data.assumptions?.length" class="fc-note">
          <div class="fc-note-title">口径说明</div>
          <ul>
            <li v-for="(a, i) in data.assumptions" :key="i">{{ a }}</li>
          </ul>
        </div>
      </el-card>

      <div v-if="tip" class="bento-span-4">
        <el-alert type="info" :closable="false" show-icon :title="tip" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import http from '../api/http'

const loading = ref(false)
const tip = ref('')
const data = ref({})

const gpa = computed(() => data.value.gpa_forecast || {})
const fail = computed(() => data.value.fail_forecast || {})
const level = computed(() => data.value.level_forecast || {})
const history = computed(() => data.value.history || [])
const risky = computed(() => data.value.risky_courses || [])

function trendType(t) {
  if (t === '上升') return 'success'
  if (t === '下降') return 'danger'
  return 'info'
}

function levelType(l) {
  if (l === 'red') return 'danger'
  if (l === 'orange' || l === 'yellow') return 'warning'
  if (l === 'none') return 'success'
  return 'info'
}

function levelText(l) {
  const map = {
    red: '红色预警', orange: '橙色预警', yellow: '黄色预警',
    none: '正常', unknown: '数据不足'
  }
  return map[l] || '—'
}

function riskType(r) {
  if (r === '高') return 'danger'
  if (r === '中') return 'warning'
  return 'info'
}

function pct(v) {
  return v === null || v === undefined ? '—' : (Number(v) * 100).toFixed(1) + '%'
}

async function load() {
  loading.value = true
  tip.value = ''
  try {
    const { data: res } = await http.get('/forecast/me')
    data.value = res || {}
    if (res && !res.available) {
      tip.value = res.reason || '历史数据不足，暂不可预测'
    }
  } catch (err) {
    data.value = {}
    tip.value = err?.response?.data?.detail || '预测数据加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.fc-hero {
  font-size: 40px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--qh-text, #1f2937);
}

.fc-unit {
  font-size: 16px;
  font-weight: 400;
  margin-left: 4px;
  color: #6b7280;
}

.fc-sub {
  margin-top: 6px;
  color: #6b7280;
  font-size: 13px;
}

.fc-tags {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.fc-reasons {
  margin: 12px 0 0;
  padding-left: 18px;
  color: #4b5563;
  font-size: 13px;
}

.fc-note {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed #e5e7eb;
  color: #6b7280;
  font-size: 12px;
}

.fc-note-title {
  font-weight: 600;
  margin-bottom: 6px;
}

.fc-note ul {
  margin: 0;
  padding-left: 18px;
}
</style>
