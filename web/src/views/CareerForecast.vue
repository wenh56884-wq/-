<template>
  <div class="page bento-page">
    <div class="bento-grid">
      <el-alert
        class="trust-bar bento-span-4"
        type="success"
        :closable="false"
        show-icon
        title="四维评分、档位与提升杠杆全部由确定性引擎（career-forecast-v1）算出，不调用大模型；本页不给录取概率"
      />

      <div class="live-bar bento-span-4">
        <el-radio-group v-model="goal" size="small" :disabled="loading" @change="load">
          <el-radio-button v-for="g in GOALS" :key="g.value" :value="g.value">
            {{ g.label }}
          </el-radio-button>
        </el-radio-group>
        <span v-if="data.available">
          基准日 {{ data.as_of }} · 模板 {{ data.template_version || '-' }} · {{ data.engine }}
        </span>
        <span v-else>{{ data.reason || '正在读取你的成绩与公告数据…' }}</span>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
      </div>

      <!-- 方向未定 / 不适用：不硬凑结论 -->
      <div v-if="!loading && !data.available" class="bento-card bento-span-4">
        <p class="bento-eyebrow">报考分析</p>
        <h3 class="bento-title">{{ data.needs_intent ? '先选定方向' : '这条方向不适用本页' }}</h3>
        <p class="bento-sub">{{ data.reason }}</p>
        <div class="act-row">
          <el-button v-if="data.needs_intent" type="primary" @click="goHome">去选方向</el-button>
          <el-button v-else @click="goHome">回我的画像</el-button>
        </div>
      </div>

      <template v-else-if="data.available">
        <!-- 结论 -->
        <div class="bento-card bento-span-2 verdict" :class="'tier-' + tier.key">
          <p class="bento-eyebrow">{{ data.goal }} · {{ data.goal_label }}</p>
          <div class="tier-line">
            <span class="tier-badge">{{ composite.tier }}</span>
            <div class="tier-num">
              <b>{{ composite.score }}</b>
              <small>/100 规则分</small>
            </div>
          </div>
          <p class="tier-label">{{ composite.tier_label }}</p>
          <div class="tier-tags">
            <el-tag size="small" effect="plain">
              置信度 {{ confText(composite.confidence) }}
            </el-tag>
            <el-tag size="small" effect="plain">{{ composite.dims_used }}/4 维有数据</el-tag>
            <el-tag v-if="savedIntent" size="small" type="info" effect="plain">
              方向取自职业意向
            </el-tag>
          </div>
          <p class="tier-note">{{ composite.score_note }}</p>
          <div class="stu-line">
            <span>{{ data.student?.grade || '年级未知' }} · {{ data.student?.major || '专业未知' }}</span>
            <span v-if="peer.line">同侪样本 {{ peer.line }}</span>
          </div>
        </div>

        <!-- 考试窗口 -->
        <div class="bento-card bento-span-2">
          <p class="bento-eyebrow">考试窗口</p>
          <template v-if="window">
            <div class="win-date">{{ window.日期 }}</div>
            <p class="win-sub">{{ window.说明 }}</p>
            <div class="win-tags">
              <el-tag size="small" :type="window.依据 === '真实公告' ? 'success' : 'warning'" effect="dark">
                {{ window.依据 }}
              </el-tag>
              <el-tag size="small" effect="plain">剩余 {{ window.剩余周数 }} 周</el-tag>
              <el-tag size="small" effect="plain">基准 {{ timeline.baseline_hours }} 小时</el-tag>
            </div>
            <p class="win-why">{{ timeline.window_reason }}</p>
            <div v-if="altWindows.length" class="win-alt">
              <span class="win-alt-title">其它窗口</span>
              <div v-for="w in altWindows" :key="w.日期" class="win-alt-row">
                <b>{{ w.日期 }}</b>
                <span>{{ w.说明 }}</span>
                <em>{{ w.剩余周数 }} 周</em>
              </div>
            </div>
          </template>
          <el-empty v-else description="没有可用的考试窗口" :image-size="56" />
        </div>

        <!-- 四维 -->
        <div class="bento-card bento-span-4">
          <p class="bento-eyebrow">四维拆解 · 每一项都能倒推回你的成绩单或真实公告</p>
          <div class="dim-list">
            <div v-for="d in dimensions" :key="d.key" class="dim-row">
              <div class="dim-head">
                <span class="dim-name">{{ d.名称 }}</span>
                <span class="dim-weight">权重 {{ Math.round((d.权重 || 0) * 100) }}%</span>
                <span class="dim-score" :class="'lv-' + d.level">
                  {{ d.score === null ? '—' : d.score }}
                </span>
                <el-tag size="small" :type="levelType(d.level)" effect="plain">{{ d.level_text }}</el-tag>
              </div>
              <div class="bar">
                <i
                  class="bar-fill"
                  :class="'lv-' + d.level"
                  :style="{ width: (d.score === null ? 0 : d.score) + '%' }"
                />
              </div>
              <p class="dim-evidence">{{ d.evidence }}</p>
              <p class="dim-source">数据来源：{{ d.source }}</p>
            </div>
          </div>
        </div>

        <!-- 提升杠杆 -->
        <!-- 门槛 -->
        <div class="bento-card bento-span-2">
          <p class="bento-eyebrow">硬门槛逐项比对</p>
          <div v-if="gates.length" class="gate-list">
            <div v-for="g in gates" :key="g.key" class="gate-row" :class="'st-' + g.当前状态">
              <span class="gate-dot" />
              <div class="gate-main">
                <div class="gate-name">
                  {{ g.项目 }}
                  <el-tag v-if="g.hard" size="small" type="danger" effect="plain">硬性</el-tag>
                </div>
                <div class="gate-req">要求 {{ g.要求 }}<template v-if="g.当前值 !== null && g.当前值 !== undefined"> · 当前 {{ g.当前值 }}</template></div>
                <div v-if="g.说明" class="gate-note">{{ g.说明 }}</div>
              </div>
              <span class="gate-status">{{ gateText(g.当前状态) }}</span>
            </div>
          </div>
          <el-empty v-else description="规则模板缺少门槛定义" :image-size="56" />
        </div>

        <!-- 阶段排期 -->
        <div class="bento-card bento-span-2">
          <p class="bento-eyebrow">阶段排期 · 按主窗口倒推</p>
          <div v-if="phases.length" class="phase-list">
            <div v-for="(p, i) in phases" :key="i" class="phase-row">
              <span class="phase-idx">{{ i + 1 }}</span>
              <div class="phase-main">
                <div class="phase-top">
                  <b>{{ p.阶段 }}</b>
                  <em>{{ p.周数 }} 周</em>
                </div>
                <div class="phase-range">{{ p.时间范围 }}</div>
                <div class="phase-task">{{ p.核心任务 }}</div>
              </div>
            </div>
          </div>
          <el-empty v-else description="剩余周数不足，无法切分阶段" :image-size="56" />
        </div>

        <!-- 建议 -->
        <div class="bento-card bento-span-4">
          <p class="bento-eyebrow">建议 · 每条都挂着一个真实差值</p>
          <div v-if="advice.length" class="advice-list">
            <div v-for="(a, i) in advice" :key="i" class="advice-row">
              <span class="advice-p" :class="'p' + a.优先级">P{{ a.优先级 }}</span>
              <div class="advice-main">
                <div class="advice-type">{{ a.类型 }}</div>
                <div class="advice-act">{{ a.动作 }}</div>
                <div class="advice-basis">{{ a.依据 }}</div>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无需处理的短板" :image-size="56" />
        </div>

        <!-- 明细折叠区：三张大表默认收起，首屏只留结论 -->
        <div class="bento-card bento-span-4">
          <el-collapse class="detail-collapse">
            <el-collapse-item name="leverage">
              <template #title>
                <span class="dc-title">提升杠杆 · 按「补上之后总分涨多少」排序</span>
                <el-tag v-if="leverage.length" size="small" effect="plain" class="dc-tag">{{ leverage.length }} 项</el-tag>
              </template>
              <p class="bento-sub">
                每一项都重算了一遍四维与档位：改的是你自己的可改变条件，不是话术。
              </p>
              <el-table v-if="leverage.length" :data="leverage" size="small" class="lev-table">
                <el-table-column prop="项目" label="可改变项" min-width="150" />
                <el-table-column label="当前 → 目标" min-width="180">
                  <template #default="{ row }">
                    <span class="lev-now">{{ row.当前 }}</span>
                    <span class="lev-arrow">→</span>
                    <span class="lev-goal">{{ row.目标 }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="总分变化" width="110">
                  <template #default="{ row }">
                    <b class="lev-delta">+{{ row.综合分变化 }}</b>
                  </template>
                </el-table-column>
                <el-table-column label="档位" width="120">
                  <template #default="{ row }">
                    <el-tag v-if="row.跨档" size="small" type="success" effect="dark">
                      {{ row.当前档位 }} → {{ row.达成后档位 }}
                    </el-tag>
                    <span v-else class="lev-flat">{{ row.当前档位 }} → {{ row.达成后档位 }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="维度变化" min-width="150">
                  <template #default="{ row }">
                    <span v-for="(v, k) in row.维度变化" :key="k" class="dim-delta">{{ k }} +{{ v }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="代价" label="代价" min-width="130" />
                <el-table-column prop="依据" label="依据" min-width="220" show-overflow-tooltip />
              </el-table>
              <el-empty v-else description="没有可再优化的可改变项" :image-size="56" />
            </el-collapse-item>

            <el-collapse-item name="notice">
              <template #title>
                <span class="dc-title">真实招考公告 · {{ data.goal }} 对应的 {{ opp.total }} 条（官网抓取）</span>
                <el-tag v-if="opp.open_count" size="small" type="success" effect="plain" class="dc-tag">
                  在报名 {{ opp.open_count }} 条
                </el-tag>
              </template>
              <p class="bento-sub">
                在报名 <b>{{ opp.open_count ?? 0 }}</b> 条
                <template v-if="opp.headcount">· 已抓到招录人数合计 <b>{{ opp.headcount }}</b> 人</template>
                <template v-if="opp.latest_published">· 最近一条发布于 {{ opp.latest_published }}</template>
              </p>
              <el-table v-if="opp.items && opp.items.length" :data="opp.items" size="small" max-height="300">
                <el-table-column prop="标题" label="公告" min-width="260" show-overflow-tooltip />
                <el-table-column prop="招录单位" label="单位" min-width="140" show-overflow-tooltip />
                <el-table-column label="招录" width="80">
                  <template #default="{ row }">{{ row.招录人数 ?? '—' }}</template>
                </el-table-column>
                <el-table-column label="报名截止" width="150">
                  <template #default="{ row }">
                    <span>{{ row.报名截止 || '未抽取' }}</span>
                    <el-tag
                      v-if="row.距截止天数 !== null && row.距截止天数 !== undefined"
                      size="small"
                      :type="row.距截止天数 >= 0 ? 'success' : 'info'"
                      effect="plain"
                      class="dl-tag"
                    >
                      {{ row.距截止天数 >= 0 ? '剩 ' + row.距截止天数 + ' 天' : '已截止' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="原文" width="90">
                  <template #default="{ row }">
                    <a v-if="row.原文链接" :href="row.原文链接" target="_blank" rel="noreferrer" class="src-link">
                      点开核对
                    </a>
                    <span v-else>—</span>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-else description="公告库里还没有该方向的记录" :image-size="56" />
            </el-collapse-item>

            <el-collapse-item name="caveat">
              <template #title>
                <span class="dc-title">口径与限制 · 请先读完再看结论</span>
                <el-tag size="small" effect="plain" class="dc-tag">{{ (data.caveats || []).length }} 条</el-tag>
              </template>
              <ul class="caveat-list">
                <li v-for="(c, i) in data.caveats || []" :key="i">{{ c }}</li>
              </ul>
              <div class="src-grid">
                <div v-for="(s, i) in data.sources || []" :key="i" class="src-item">
                  <span class="src-dim">{{ s.维度 }}</span>
                  <span class="src-name">{{ s.来源 }}</span>
                  <el-tag size="small" :type="s.性质.startsWith('真实') ? 'success' : 'warning'" effect="plain">
                    {{ s.性质 }}
                  </el-tag>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </template>

      <div v-else class="bento-card bento-span-4">
        <el-skeleton :rows="6" animated />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '../api/http'

const GOALS = [
  { value: '考公', label: '考公' },
  { value: '考编', label: '考编' },
  { value: '考研', label: '考研' }
]

const router = useRouter()
const loading = ref(false)
const goal = ref('')
const data = ref({})

const composite = computed(() => data.value.composite || {})
const dimensions = computed(() => data.value.dimensions || [])
const gates = computed(() => data.value.gates || [])
const leverage = computed(() => data.value.leverage || [])
const advice = computed(() => data.value.advice || [])
const timeline = computed(() => data.value.timeline || {})
const window = computed(() => timeline.value.window || null)
const altWindows = computed(() => timeline.value.alternatives || [])
const phases = computed(() => timeline.value.phases || [])
const opp = computed(() => data.value.opportunities || {})
const savedIntent = computed(() => data.value.intent_source === 'saved')

const tier = computed(() => {
  const t = composite.value.tier || '?'
  const map = { A: 'a', B: 'b', C: 'c', D: 'd' }
  return { key: map[t] || 'u' }
})

// 同侪样本的一句话说明，直接取学业维度的 evidence 前半段
const peer = computed(() => {
  const d = dimensions.value.find((x) => x.key === 'academic')
  if (!d || !d.evidence) return { line: '' }
  const m = String(d.evidence).match(/同专业同年级\s*(\d+)\s*人中排第\s*(\d+)/)
  return { line: m ? `${m[1]} 人第 ${m[2]}` : '' }
})

function levelType(l) {
  if (l === 'strong') return 'success'
  if (l === 'fair') return 'primary'
  if (l === 'weak') return 'warning'
  if (l === 'poor') return 'danger'
  return 'info'
}

function confText(c) {
  const map = { high: '高（四维齐全）', medium: '中（缺一维）', low: '低（数据不足）' }
  return map[c] || '—'
}

function gateText(s) {
  const map = { pass: '通过', fail: '不满足', unknown: '缺数据' }
  return map[s] || s
}

function goHome() {
  router.push('/student')
}

async function load() {
  loading.value = true
  try {
    const params = goal.value ? { goal: goal.value } : {}
    const { data: res } = await http.get('/career/forecast', { params })
    data.value = res || {}
    if (res && res.available && res.goal) goal.value = res.goal
  } catch (err) {
    data.value = { available: false, reason: err?.response?.data?.detail || '报考分析加载失败' }
  } finally {
    loading.value = false
  }
}

onMounted(load)
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
  flex-wrap: wrap;
  font-size: 12px;
  color: #86909c;
  background: #fff;
  border: 1px solid #f4f4f5;
  border-radius: 14px;
  padding: 8px 14px;
}

.act-row {
  margin-top: 16px;
}

/* 结论卡 */
.verdict {
  border-left: 4px solid #a1a1aa;
}

.verdict.tier-a { border-left-color: #16a34a; }
.verdict.tier-b { border-left-color: #2563eb; }
.verdict.tier-c { border-left-color: #d97706; }
.verdict.tier-d { border-left-color: #dc2626; }
.verdict.tier-u { border-left-color: #a1a1aa; }

.tier-line {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 4px;
}

.tier-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 18px;
  font-size: 26px;
  font-weight: 700;
  color: #fff;
  background: #a1a1aa;
}

.tier-a .tier-badge { background: #16a34a; }
.tier-b .tier-badge { background: #2563eb; }
.tier-c .tier-badge { background: #d97706; }
.tier-d .tier-badge { background: #dc2626; }

.tier-num b {
  font-size: 34px;
  font-weight: 700;
  line-height: 1;
  color: var(--bento-text, #18181b);
  font-variant-numeric: tabular-nums;
}

.tier-num small {
  margin-left: 4px;
  font-size: 12px;
  color: var(--bento-mute, #a1a1aa);
}

.tier-label {
  margin: 10px 0 0;
  font-size: 14px;
  font-weight: 600;
  color: #3f3f46;
}

.tier-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.tier-note {
  margin: 10px 0 0;
  font-size: 12px;
  color: #a1a1aa;
}

.stu-line {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #e4e4e7;
  font-size: 12px;
  color: #71717a;
}

/* 考试窗口 */
.win-date {
  margin-top: 4px;
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--bento-text, #18181b);
  font-variant-numeric: tabular-nums;
}

.win-sub {
  margin: 6px 0 0;
  font-size: 13px;
  color: #52525b;
}

.win-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.win-why {
  margin: 10px 0 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: #71717a;
}

.win-alt {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed #e4e4e7;
}

.win-alt-title {
  font-size: 12px;
  font-weight: 600;
  color: #a1a1aa;
}

.win-alt-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 6px;
  font-size: 12.5px;
  color: #52525b;
}

.win-alt-row b {
  font-variant-numeric: tabular-nums;
}

.win-alt-row span {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.win-alt-row em {
  font-style: normal;
  color: #a1a1aa;
}

/* 四维 */
.dim-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
  margin-top: 6px;
}

.dim-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.dim-name {
  font-size: 14px;
  font-weight: 650;
  color: var(--bento-text, #18181b);
}

.dim-weight {
  font-size: 11.5px;
  color: #a1a1aa;
}

.dim-score {
  margin-left: auto;
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: #52525b;
}

.dim-score.lv-strong { color: #16a34a; }
.dim-score.lv-fair { color: #2563eb; }
.dim-score.lv-weak { color: #d97706; }
.dim-score.lv-poor { color: #dc2626; }

.bar {
  height: 6px;
  margin-top: 8px;
  border-radius: 999px;
  background: #f4f4f5;
  overflow: hidden;
}

.bar-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: #a1a1aa;
  transition: width 420ms cubic-bezier(0.22, 0.61, 0.36, 1);
}

.bar-fill.lv-strong { background: linear-gradient(90deg, #16a34a, #4ade80); }
.bar-fill.lv-fair { background: linear-gradient(90deg, #2563eb, #60a5fa); }
.bar-fill.lv-weak { background: linear-gradient(90deg, #d97706, #fbbf24); }
.bar-fill.lv-poor { background: linear-gradient(90deg, #dc2626, #f87171); }

.dim-evidence {
  margin: 8px 0 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: #3f3f46;
}

.dim-source {
  margin: 3px 0 0;
  font-size: 11.5px;
  color: #a1a1aa;
}

/* 杠杆 */
.lev-now { color: #71717a; }
.lev-arrow { margin: 0 6px; color: #d4d4d8; }
.lev-goal { font-weight: 600; color: #18181b; }
.lev-delta { color: #16a34a; font-variant-numeric: tabular-nums; }
.lev-flat { color: #a1a1aa; font-size: 12px; }

.dim-delta {
  display: inline-block;
  margin-right: 8px;
  font-size: 12px;
  color: #2563eb;
}

/* 门槛 */
.gate-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 6px;
}

.gate-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px dashed #f4f4f5;
}

.gate-row:last-child {
  border-bottom: 0;
}

.gate-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  margin-top: 6px;
  border-radius: 999px;
  background: #d4d4d8;
}

.st-pass .gate-dot { background: #16a34a; }
.st-fail .gate-dot { background: #dc2626; }
.st-unknown .gate-dot { background: #d4d4d8; }

.gate-main {
  flex: 1;
  min-width: 0;
}

.gate-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #18181b;
}

.gate-req {
  margin-top: 2px;
  font-size: 12px;
  color: #71717a;
}

.gate-note {
  margin-top: 2px;
  font-size: 11.5px;
  color: #a1a1aa;
  line-height: 1.5;
}

.gate-status {
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: 600;
  color: #a1a1aa;
}

.st-pass .gate-status { color: #16a34a; }
.st-fail .gate-status { color: #dc2626; }

/* 阶段 */
.phase-list {
  margin-top: 8px;
}

.phase-row {
  display: flex;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px dashed #f4f4f5;
}

.phase-row:last-child {
  border-bottom: 0;
}

.phase-idx {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  margin-top: 2px;
  border-radius: 8px;
  background: #f4f4f5;
  font-size: 12px;
  font-weight: 600;
  color: #71717a;
}

.phase-main {
  flex: 1;
  min-width: 0;
}

.phase-top {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.phase-top b {
  font-size: 13.5px;
  color: #18181b;
}

.phase-top em {
  font-style: normal;
  font-size: 11.5px;
  color: #a1a1aa;
}

.phase-range {
  margin-top: 2px;
  font-size: 11.5px;
  color: #a1a1aa;
  font-variant-numeric: tabular-nums;
}

.phase-task {
  margin-top: 4px;
  font-size: 12.5px;
  line-height: 1.6;
  color: #52525b;
}

/* 建议 */
.advice-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 8px;
}

.advice-row {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 14px;
  background: #fafafa;
}

.advice-p {
  flex: 0 0 auto;
  height: 22px;
  padding: 0 8px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  line-height: 22px;
  color: #fff;
  background: #a1a1aa;
}

.advice-p.p1 { background: #dc2626; }
.advice-p.p2 { background: #d97706; }
.advice-p.p3 { background: #2563eb; }
.advice-p.p4 { background: #a1a1aa; }

.advice-main {
  flex: 1;
  min-width: 0;
}

.advice-type {
  font-size: 11.5px;
  font-weight: 600;
  color: #a1a1aa;
}

.advice-act {
  margin-top: 2px;
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.6;
  color: #18181b;
}

.advice-basis {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: #71717a;
}

/* 机会表 */
.dl-tag {
  margin-left: 6px;
}

.src-link {
  color: #2563eb;
  text-decoration: none;
}

.src-link:hover {
  text-decoration: underline;
}

/* 口径 */
.caveat-list {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #52525b;
  font-size: 12.5px;
  line-height: 1.75;
}

.src-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 8px 18px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed #e4e4e7;
}

.src-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #52525b;
}

.src-dim {
  flex: 0 0 auto;
  font-weight: 600;
  color: #18181b;
}

.src-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 768px) {
  .tier-badge {
    width: 46px;
    height: 46px;
    font-size: 22px;
  }

  .tier-num b {
    font-size: 28px;
  }

  .win-date {
    font-size: 24px;
  }
}
/* 明细折叠区：标题行与计数徽标 */
.detail-collapse :deep(.el-collapse-item__header) {
  height: 44px;
  line-height: 44px;
}

.dc-title {
  font-size: 13px;
  font-weight: 500;
  color: #1f2329;
}

.dc-tag {
  margin-left: 8px;
}
</style>
