<!-- 考证中心：谁负责考什么、差什么、能获得什么、什么时候报名考试、如何报名。
     日期全部来自官方公告入库（带来源链接与核实日期）；学生端另有 AI 个性化推荐
     （按目标去向 / 专业 / 年级 / 已持证书排序，理由与差距全部可解释）。 -->
<template>
  <div class="page bento-page">
    <div class="bento-grid">
      <el-alert
        type="info"
        :closable="false"
        class="freshness bento-span-4"
        show-icon
      >
        证书日期均来自官方公告（每条附来源链接可核对，标「预计」为官方未公布、按历年规律推算）。
        <span v-if="recNote" class="freshness-note">{{ recNote }}</span>
      </el-alert>

      <!-- AI 个性化推荐（仅学生）：为什么推荐、差什么，逐条可解释 -->
      <el-card
        v-if="isStudent && recItems.length"
        shadow="never"
        class="rec-panel bento-span-4"
      >
        <template #header>
          <div class="rec-head">
            <span class="rec-title">AI 为你推荐（{{ recIntent || '按你的画像' }}）</span>
            <span class="rec-sub">{{ recMajor }} · {{ recGrade }} · 已持证书 {{ recOwned.length ? recOwned.join('、') : '暂未登记' }}</span>
          </div>
        </template>
        <article
          v-for="(it, idx) in recItems"
          :key="'rec-' + it.cert_id"
          class="rec-item"
        >
          <div class="rec-rank">{{ idx + 1 }}</div>
          <div class="rec-body">
            <div class="rec-line1">
              <b>{{ it.short_name || it.name }}</b>
              <span class="pill" :class="statusClass(it.status)">{{ it.status }}</span>
              <span v-if="it.days_to_deadline !== null && it.status === '报名中'"
                class="pill urgent">剩 {{ it.days_to_deadline }} 天截止</span>
              <span class="rec-org">{{ it.org }}</span>
            </div>
            <ul class="rec-reasons">
              <li v-for="(r, i) in it.match_reasons.slice(0, 4)" :key="i">为什么：{{ r }}</li>
            </ul>
            <div class="rec-gap">
              <b>差什么：</b>{{ it.gaps[0] }}
            </div>
          </div>
        </article>
      </el-card>

      <!-- 筛选条 -->
      <el-card shadow="never" class="filter-bar bento-span-4">
        <el-form inline @submit.prevent>
          <el-form-item label="状态">
            <el-radio-group v-model="statusFilter">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button v-for="s in STATUS_ALL" :key="s" :value="s">{{ s }}</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="搜索">
            <el-input
              v-model="keyword"
              placeholder="如 四级 / 软考 / 教资 / 普通话"
              clearable
              style="width: 220px"
            />
          </el-form-item>
          <el-form-item class="filter-actions">
            <span class="filter-total">共 <b>{{ filtered.length }}</b> 项</span>
          </el-form-item>
        </el-form>
      </el-card>

      <!-- 目录卡片 -->
      <article
        v-for="it in filtered"
        :key="it.cert_id"
        class="bento-card cert-card bento-span-2"
      >
        <div class="cert-head">
          <div class="cert-name">
            <b>{{ it.short_name || it.name }}</b>
            <span class="pill" :class="statusClass(it.status)">{{ it.status }}</span>
            <span v-if="it.days_to_deadline !== null && it.status === '报名中'"
              class="pill urgent">剩 {{ it.days_to_deadline }} 天截止</span>
            <span v-if="it.days_to_exam !== null && it.days_to_exam >= 0 && it.days_to_exam <= 14"
              class="pill urgent">{{ it.days_to_exam }} 天后开考</span>
          </div>
          <span class="cert-level" :class="'lv-' + levelClass(it.level)">{{ it.level }}</span>
        </div>

        <div class="cert-meta">主办方：{{ it.org }} · {{ it.level_subject }}</div>

        <dl class="cert-facts">
          <div><dt>报名时间</dt><dd>{{ regText(it) }}</dd><dd v-if="it.status_note" class="muted">{{ it.status_note }}</dd></div>
          <div><dt>考试时间</dt><dd>{{ it.exam_text }}</dd><dd v-if="it.date_note" class="muted">{{ it.date_note }}</dd></div>
          <div><dt>考试频次</dt><dd>{{ it.cycle }}</dd></div>
          <div><dt>报名费</dt><dd>{{ it.fee }}</dd></div>
          <div><dt>如何报名</dt><dd>{{ it.how_to_apply }}</dd></div>
          <div><dt>能获得什么</dt><dd>{{ it.benefits }}</dd></div>
          <div><dt>报名前提</dt><dd>{{ it.prerequisites }}</dd></div>
        </dl>

        <div class="cert-links">
          <a v-if="it.apply_url" :href="it.apply_url" target="_blank" rel="noopener"
            class="cert-link">报名官网 ↗</a>
          <a v-if="it.source_url" :href="it.source_url" target="_blank" rel="noopener"
            class="cert-link ghost">依据公告 ↗</a>
          <span v-if="it.verified_at" class="cert-verified">核实于 {{ it.verified_at }}</span>
        </div>
      </article>

      <el-empty v-if="!loading && !filtered.length" description="没有匹配的证书" class="bento-span-4" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import http, { currentRole } from '../api/http'

const STATUS_ALL = ['报名中', '未开始', '常年可报', '已截止']

const isStudent = currentRole() === 'student'
const loading = ref(true)
const items = ref([])

// AI 推荐区（学生登录态才有）
const recItems = ref([])
const recNote = ref('')
const recIntent = ref('')
const recMajor = ref('')
const recGrade = ref('')
const recOwned = ref([])

const statusFilter = ref('')
const keyword = ref('')

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return items.value.filter((it) => {
    if (statusFilter.value && it.status !== statusFilter.value) return false
    if (!kw) return true
    return [it.name, it.short_name, it.org, it.level_subject,
      ...(it.tags || [])].some((f) => String(f || '').toLowerCase().includes(kw))
  })
})

function regText(it) {
  if (it.reg_start && it.reg_deadline) {
    return `${it.reg_start} ~ ${it.reg_deadline}`
  }
  return '常年开放（按测试站/考点批次）'
}

function statusClass(status) {
  if (status === '报名中') return 'st-open'
  if (status === '未开始') return 'st-upcoming'
  if (status === '常年可报') return 'st-anytime'
  return 'st-closed'
}

function levelClass(level) {
  if (String(level).includes('核心')) return 'core'
  if (String(level).includes('推荐')) return 'rec'
  return 'opt'
}

onMounted(async () => {
  try {
    const [{ data: catalog }, maybeRec] = await Promise.all([
      http.get('/cert/list', { params: { limit: 30 } }),
      isStudent ? http.get('/cert/recommend', { params: { limit: 4 } }).catch(() => null)
        : Promise.resolve(null)
    ])
    items.value = catalog.items || []
    recNote.value = catalog.note || ''
    if (maybeRec?.data) {
      recItems.value = maybeRec.data.items || []
      recIntent.value = maybeRec.data.intent || ''
      recMajor.value = maybeRec.data.major || ''
      recGrade.value = maybeRec.data.grade || ''
      recOwned.value = maybeRec.data.items?.[0]?.owned || []
    }
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* AI 推荐区：浅色面板 + 顶部靛蓝→青发丝线，局部提亮不推翻白底 */
.rec-panel { grid-column: span 4; position: relative; }
.rec-panel::before {
  content: '';
  position: absolute;
  top: 0;
  left: 20px;
  right: 20px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(25, 81, 195, 0.5) 32%, rgba(0, 194, 255, 0.75) 52%, rgba(25, 81, 195, 0.5) 72%, transparent);
  pointer-events: none;
}
.rec-head { display: flex; flex-direction: column; gap: 2px; }
/* 渐变文字：标题落在科技渐变上 */
.rec-title {
  font-weight: 600;
  background: var(--tech-gradient, linear-gradient(135deg, #1951c3 0%, #2b7ae0 50%, #00c2ff 100%));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.rec-sub { font-size: 12px; color: var(--qh-text-2, #6b7280); }
.rec-item { display: flex; gap: 12px; padding: 10px 0; border-top: 1px solid var(--qh-border, #e5e7eb); }
.rec-item:first-of-type { border-top: 0; }
/* 排名数字：科技渐变底 + 青色光晕 + 复用全局滚动入场动画 */
.rec-rank {
  flex: none; width: 26px; height: 26px; border-radius: 8px;
  display: grid; place-items: center; font-weight: 700; font-size: 13px;
  color: #fff;
  font-variant-numeric: tabular-nums;
  background: var(--tech-gradient, linear-gradient(135deg, #1951c3 0%, #2b7ae0 50%, #00c2ff 100%));
  box-shadow: 0 0 14px -4px rgba(0, 194, 255, 0.5);
  animation: qh-tech-count-in 0.6s cubic-bezier(0.16, 1, 0.3, 1) both;
}
.rec-body { flex: 1; min-width: 0; }
.rec-line1 { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rec-org { color: var(--qh-text-2, #6b7280); font-size: 12px; }
.rec-reasons { margin: 6px 0 0; padding-left: 18px; color: var(--qh-text-2, #4b5563); font-size: 13px; }
.rec-reasons li { margin: 2px 0; }
.rec-gap { margin-top: 6px; font-size: 13px; color: #b45309; }

.cert-card { display: flex; flex-direction: column; gap: 8px; }
.cert-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.cert-name { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.cert-level {
  flex: none; font-size: 12px; padding: 2px 8px; border-radius: 999px;
  background: #f3f4f6; color: #4b5563;
}
.cert-level.lv-core { background: #fef3c7; color: #92400e; }
.cert-level.lv-rec { background: #e0f2fe; color: #075985; }
.cert-meta { font-size: 12px; color: var(--qh-text-2, #6b7280); }
.cert-facts { margin: 0; display: grid; gap: 4px; font-size: 13px; }
.cert-facts > div { display: flex; gap: 8px; }
.cert-facts dt { flex: none; width: 72px; color: var(--qh-text-2, #6b7280); }
.cert-facts dd { margin: 0; flex: 1; min-width: 0; }
.muted { color: var(--qh-text-3, #9ca3af); font-size: 12px; }

.pill { font-size: 12px; padding: 1px 8px; border-radius: 999px; }
.st-open { background: #dcfce7; color: #166534; }
.st-upcoming { background: #e0e7ff; color: #3730a3; }
.st-anytime { background: #f3f4f6; color: #4b5563; }
.st-closed { background: #fee2e2; color: #991b1b; }
.urgent { background: #ffedd5; color: #9a3412; }

.cert-links { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: auto; }
.cert-link {
  font-size: 13px;
  color: var(--tech-blue, #1951c3);
  text-decoration: none;
  transition: color 180ms ease, text-shadow 180ms ease;
}
.cert-link:hover {
  color: var(--tech-cyan, #00c2ff);
  text-shadow: 0 0 12px rgba(0, 194, 255, 0.45);
}
.cert-link.ghost { color: var(--qh-text-2, #6b7280); }
.cert-verified { font-size: 12px; color: var(--qh-text-3, #9ca3af); }

@media (max-width: 560px) {
  .cert-facts > div { flex-direction: column; gap: 0; }
  .cert-facts dt { width: auto; }
}
</style>
