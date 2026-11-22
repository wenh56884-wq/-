<template>
  <div class="page bento-page quality-page" v-loading="loading">
    <div class="bento-grid">
      <RouteHero
        class="bento-span-4 quality-hero-slot"
        tone="teacher"
        eyebrow="智能体质量 · 近 7 天 · 本租户"
        title="每一次回答，都留下可回查的证据。"
        desc="问答量、降级率、好评率与平均耗时全部来自审计日志实数；每条回答都走「意图 → 工具 → 表达 → Critic 回查」，通过才输出。"
      >
        <template #actions>
          <el-button type="primary" @click="askAgent">去问一句</el-button>
          <el-button :loading="loading" @click="load">刷新</el-button>
        </template>
      </RouteHero>

      <article
        v-for="kpi in kpis"
        :key="kpi.key"
        class="bento-card quality-stat"
      >
        <div class="quality-stat__top">
          <span class="bento-icon qh-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path :d="kpi.icon" /></svg>
          </span>
          <span class="quality-stat__label">{{ kpi.label }}</span>
        </div>
        <div class="quality-stat__value">{{ kpi.value }}</div>
        <div class="quality-stat__sub">{{ kpi.sub }}</div>
      </article>

      <section class="bento-card bento-span-2 quality-pipeline-card">
        <div class="quality-card-head">
          <div>
            <h3 class="bento-title">执行链路</h3>
            <p class="bento-sub">固定五段：意图识别 → 工具取数 → 文本生成 → Critic 回查 → 输出。</p>
          </div>
          <span class="quality-engine">graph-v5 · critic-v3</span>
        </div>
        <AgentPipeline status="passed" :attempts="1" class="quality-pipeline" />
        <div class="quality-legend">
          <span><i class="dot dot-green" />通过</span>
          <span><i class="dot dot-gold" />驳回重写</span>
          <span><i class="dot dot-red" />超限降级</span>
        </div>
        <p class="quality-note">
          通过 = 草稿中的每个数值都能在工具结果里找到；驳回 = 回退重写，最多 2 次；
          仍不通过 = 输出不含数字的安全话术，并标记为降级。
          只差在小数位（68.4 写成 68）按舍入放行并单独记审计，不触发重写。
        </p>
      </section>

      <section class="bento-card bento-span-2 quality-read-card">
        <div class="quality-card-head">
          <h3 class="bento-title">怎么读这些数</h3>
          <span class="quality-engine">审计日志 · 只读</span>
        </div>
        <ul class="quality-read-list">
          <li><b>问答量</b>：近 7 天本租户教师发起的智能体请求数。</li>
          <li><b>降级率</b>：超限兜底次数 / 全部问答；没有数据时显示 —，不估算。</li>
          <li><b>好评率</b>：只统计学生/教师的主动评价；没有评价显示 —。</li>
          <li><b>平均耗时</b>：端到端请求耗时，含工具与 Critic，不含前端渲染。</li>
          <li>
            每条回答可在助手抽屉里展开「执行与回查」，看到工具名、生成方式、
            本轮核对过的数值和 trace id。
          </li>
          <li>
            演示环境的历史请求包含自动化测试与注入用例，质量趋势以新增请求为准。
          </li>
        </ul>
        <div class="quality-links">
          <router-link to="/teacher/assistant" class="quality-link">打开 AI 助手 →</router-link>
          <router-link to="/teacher/approvals" class="quality-link">看工作流审批 →</router-link>
        </div>
      </section>

      <section class="bento-card bento-span-4 capabilities-card">
        <div class="quality-card-head">
          <div>
            <h3 class="bento-title">能力自检</h3>
            <p class="bento-sub">不写「已支持」，只报可验证的事实：知识库、工作流、联网、记忆的当前状态。</p>
          </div>
          <span class="quality-engine">{{ capabilities.length }} 项</span>
        </div>

        <div v-if="loadError" class="quality-error">{{ loadError }}</div>
        <div v-else class="capability-grid">
          <div
            v-for="item in capabilities"
            :key="item.key"
            class="capability-item"
            :class="{ 'is-off': !item.ready }"
          >
            <span class="capability-dot" :class="item.ready ? 'is-on' : 'is-off'" />
            <div class="capability-main">
              <div class="capability-name">
                {{ item.name }}
                <span class="capability-state">{{ item.ready ? '可用' : '未配置' }}</span>
              </div>
              <div class="capability-detail">{{ item.detail }}</div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
// AgentQuality：教师端「智能体质量」页。
// 数据来自 /chat/metrics（审计日志近 7 天）与 /chat/capabilities（能力自检），
// 不在这里做任何二次推算；没有数据就显示 —。

import { computed, onMounted, ref } from 'vue'

import http from '../api/http'
import AgentPipeline from '../components/agent/AgentPipeline.vue'
import RouteHero from '../components/brand/RouteHero.vue'
import { useAssistant } from '../composables/useAssistant'

const loading = ref(false)
const loadError = ref('')
const metrics = ref({})
const capabilities = ref([])
const { ask } = useAssistant()

const kpis = computed(() => {
  const m = metrics.value || {}
  return [
    {
      key: 'total',
      label: '近 7 天问答量',
      value: m.chat_total == null ? '—' : String(m.chat_total),
      sub: '本租户教师发起的请求',
      icon: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'
    },
    {
      key: 'degraded',
      label: '降级率',
      value: formatRate(m.degraded_rate),
      sub: m.chat_total ? `${m.degraded_total ?? 0} 次超限兜底` : '暂无数据',
      icon: 'M12 3l9 16H3L12 3zM12 9v4M12 16h.01'
    },
    {
      key: 'like',
      label: '好评率',
      value: formatRate(m.like_rate),
      sub: (m.feedback_up || 0) + (m.feedback_down || 0)
        ? `${m.feedback_up || 0} 好评 / ${m.feedback_down || 0} 差评`
        : '暂无主动评价',
      icon: 'M7 10v11M3 10h4v11H3zM7 10l4-7a2 2 0 0 1 4 0v4h4a2 2 0 0 1 2 2l-2 8H8'
    },
    {
      key: 'latency',
      label: '平均耗时',
      value: formatMs(m.avg_duration_ms),
      sub: '端到端 · 含工具与 Critic',
      icon: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2'
    }
  ]
})

function formatRate(value) {
  if (value === null || value === undefined) return '—'
  return `${(Number(value) * 100).toFixed(1)}%`
}

function formatMs(value) {
  if (value === null || value === undefined) return '—'
  const ms = Number(value)
  if (!Number.isFinite(ms)) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

function askAgent() {
  ask('AI2301 这学期预警情况怎么样')
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [metricsRes, capsRes] = await Promise.all([
      http.get('/chat/metrics'),
      http.get('/chat/capabilities')
    ])
    metrics.value = metricsRes.data || {}
    capabilities.value = Array.isArray(capsRes.data?.items) ? capsRes.data.items : []
  } catch (err) {
    loadError.value = err?.response?.data?.detail || err?.message || '质量数据加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.quality-page {
  padding-top: 0;
}

.quality-stat {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-height: 132px;
}

.quality-stat__top {
  display: flex;
  align-items: center;
  gap: 9px;
}

.quality-stat__label {
  color: var(--bento-mute);
  font-size: 13px;
  font-weight: 500;
}

.quality-stat__value {
  color: var(--bento-text);
  font-size: 32px;
  font-weight: 680;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.quality-stat__sub {
  color: var(--bento-mute);
  font-size: 11.5px;
  line-height: 1.5;
}

.quality-pipeline-card,
.quality-read-card,
.capabilities-card {
  padding: 22px 24px;
}

.quality-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 10px;
}

.quality-card-head .bento-sub {
  margin-top: 4px;
  font-size: 13px;
}

.quality-engine {
  flex: 0 0 auto;
  padding: 3px 8px;
  border: 1px solid var(--bento-border);
  border-radius: 999px;
  color: var(--bento-mute);
  font-family: var(--cf-font-mono);
  font-size: 10px;
  white-space: nowrap;
}

.quality-pipeline {
  padding: 16px 0 6px;
}

.quality-legend {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 8px;
  color: var(--bento-sub);
  font-size: 11.5px;
}

.quality-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.quality-legend .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.dot-green { background: #0f9d8a; }
.dot-gold { background: #d99a00; }
.dot-red { background: #d83b32; }

.quality-note {
  margin: 12px 0 0;
  color: var(--bento-mute);
  font-size: 12px;
  line-height: 1.7;
}

.quality-read-list {
  margin: 4px 0 0;
  padding-left: 18px;
  color: var(--bento-sub);
  font-size: 13px;
  line-height: 1.85;
}

.quality-read-list b {
  color: var(--bento-text);
}

.quality-links {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 16px;
}

.quality-link {
  color: var(--qh-primary);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.quality-link:hover {
  text-decoration: underline;
}

.quality-error {
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff0ef;
  color: #b42318;
  font-size: 13px;
  line-height: 1.6;
}

.capability-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.capability-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid #edf0f5;
  border-radius: 12px;
  background: #fbfcfe;
}

.capability-item.is-off {
  background: #fafafa;
}

.capability-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  margin-top: 5px;
  border-radius: 50%;
  background: #c9d0da;
}

.capability-dot.is-on { background: #0f9d8a; }
.capability-dot.is-off { background: #d99a00; }

.capability-main {
  min-width: 0;
}

.capability-name {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--bento-text);
  font-size: 13px;
  font-weight: 600;
}

.capability-state {
  padding: 1px 6px;
  border-radius: 999px;
  background: #e8f8f4;
  color: #0b7d70;
  font-size: 9.5px;
  font-weight: 600;
}

.capability-item.is-off .capability-state {
  background: #fff7e6;
  color: #9a5b00;
}

.capability-detail {
  margin-top: 4px;
  color: var(--bento-mute);
  font-size: 11.5px;
  line-height: 1.55;
}

@media (max-width: 900px) {
  .quality-stat__value {
    font-size: 27px;
  }

  .capability-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px) {
  .bento-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quality-hero-slot,
  .quality-pipeline-card,
  .quality-read-card,
  .capabilities-card {
    grid-column: 1 / -1;
  }

  .quality-pipeline-card,
  .quality-read-card,
  .capabilities-card {
    padding: 18px;
  }

  .quality-stat {
    min-height: 112px;
  }

  .quality-stat__value {
    font-size: 25px;
  }
}
</style>
