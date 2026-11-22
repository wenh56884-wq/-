<template>
  <div class="page bento-page">
    <div class="bento-grid">
      <el-alert
        class="trust-bar bento-span-4"
        type="success"
        :closable="false"
        show-icon
        title="选课方案由选课规划智能体（DeepSeek）生成；覆盖率、缺口、学分与得分全部由确定性引擎 elective-v2 算出，模型只引用不生成，数值经 critic 逐条回查；选课约束按教务处通知与学生手册执行"
      />

      <!-- 智能体建议（主角） -->
      <div class="bento-card bento-span-4 agent-card">
        <p class="bento-eyebrow">选课规划智能体</p>
        <div class="agent-head">
          <h3 class="bento-title">让智能体为你规划选课</h3>
          <div class="agent-acts">
            <el-button type="primary" :loading="advising" @click="advise()">
              {{ advice ? '重新规划' : '开始规划' }}
            </el-button>
          </div>
        </div>
        <p class="bento-sub">
          智能体读取引擎算出的技能缺口与候选课，结合你的专业与已选方向给出个性化方案；
          方案里的每门课都来自真实选修课池，编造课名会被白名单拒收。
        </p>

        <div v-if="advising" class="agent-loading">
          <el-skeleton :rows="3" animated />
          <p class="agent-loading-text">智能体正在分析你的技能缺口…</p>
        </div>

        <template v-else-if="advice">
          <el-alert
            v-if="advice.degraded"
            class="agent-degraded"
            type="warning"
            :closable="false"
            show-icon
            :title="degradedText"
          />
          <div class="agent-reply">{{ advice.reply }}</div>

          <div v-if="planCourses.length" class="plan-chips">
            <span class="plan-label">建议选修顺序</span>
            <div v-for="(c, i) in planCourses" :key="c.name" class="plan-chip">
              <span class="plan-idx">{{ i + 1 }}</span>
              <div class="plan-main">
                <b>{{ c.name }}</b>
                <small>{{ c.direction }}方向 · {{ c.credit }}学分 · 得分 {{ c.score }}</small>
              </div>
            </div>
          </div>
          <p v-if="planRejected.length" class="plan-rejected">
            以下课名不在候选池，已被白名单拒收：{{ planRejected.join('、') }}
          </p>

          <div class="agent-meta">
            <el-tag v-if="advice.critic?.passed" size="small" type="success" effect="plain">
              数值回查通过
            </el-tag>
            <el-tag v-if="advice.critic?.retries > 0" size="small" type="warning" effect="plain">
              重写 {{ advice.critic.retries }} 次
            </el-tag>
            <el-tag size="small" effect="plain">{{ advice.engine_version }}</el-tag>
          </div>

          <div class="agent-ask">
            <el-input
              v-model="question"
              maxlength="200"
              placeholder="追问智能体，如：先补哪门课？学分怎么搭配？"
              :disabled="advising"
              @keyup.enter="advise(question)"
            />
            <el-button :loading="advising" @click="advise(question)">追问</el-button>
          </div>
        </template>

        <el-empty
          v-else-if="!loading && !hasGaps"
          :description="facts.note || '暂无技能缺口，无需补课'"
          :image-size="56"
        />
      </div>

      <!-- 证据面板：目标岗位 -->
      <div class="bento-card bento-span-2">
        <p class="bento-eyebrow">目标岗位 · 引擎事实</p>
        <template v-if="target.source">
          <h3 class="bento-title">{{ target.title || '方向聚合技能要求' }}</h3>
          <p class="bento-sub">{{ target.company || (target.directions || []).join('、') }}</p>
          <div class="target-tags">
            <el-tag size="small" :type="target.source === 'hybrid_top' ? 'success' : 'warning'" effect="dark">
              {{ target.source === 'hybrid_top' ? '头部推荐岗位' : '选修方向聚合' }}
            </el-tag>
            <el-tag v-if="target.direction" size="small" effect="plain">{{ target.direction }}方向</el-tag>
          </div>
        </template>
        <el-empty v-else description="暂无目标岗位：先看一次岗位推荐" :image-size="56" />
        <div class="act-row">
          <el-button size="small" @click="goJobs">去岗位库</el-button>
        </div>
      </div>

      <!-- 证据面板：覆盖与缺口 -->
      <div class="bento-card bento-span-2">
        <p class="bento-eyebrow">技能覆盖 · 已修 + 已选累计</p>
        <template v-if="(facts.required || []).length">
          <div class="cover-line">
            <b>{{ (facts.covered || []).length }}/{{ (facts.required || []).length }}</b>
            <small>项技能已覆盖</small>
          </div>
          <el-progress
            :percentage="Math.round((facts.coverage || 0) * 100)"
            :stroke-width="10"
            :status="(facts.skill_gaps || []).length ? undefined : 'success'"
          />
          <div class="gap-tags">
            <el-tag
              v-for="g in facts.skill_gaps || []"
              :key="'gap-' + g"
              size="small"
              type="danger"
              effect="plain"
            >
              缺 {{ g }}
            </el-tag>
            <el-tag
              v-for="c in facts.covered || []"
              :key="'cov-' + c"
              size="small"
              type="success"
              effect="plain"
            >
              {{ c }}
            </el-tag>
          </div>
        </template>
        <el-empty v-else description="暂无可核对的技能要求" :image-size="56" />
      </div>

      <!-- 证据面板：候选课排序 -->
      <div class="bento-card bento-span-4">
        <p class="bento-eyebrow">候选课排序 · 补口占比 0.7 + 方向契合 0.3（引擎实算）</p>
        <el-table
          v-if="(facts.recommendations || []).length"
          :data="facts.recommendations"
          size="small"
          max-height="360"
        >
          <el-table-column prop="name" label="课程" min-width="170" show-overflow-tooltip />
          <el-table-column prop="direction" label="方向" width="80" />
          <el-table-column prop="credit" label="学分" width="70" />
          <el-table-column label="可补缺口" min-width="160">
            <template #default="{ row }">
              <el-tag v-for="f in row.fills" :key="f" size="small" type="danger" effect="plain" class="fill-tag">
                {{ f }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="score" label="得分" width="90" />
          <el-table-column prop="reason" label="理由" min-width="240" show-overflow-tooltip />
        </el-table>
        <el-empty v-else :description="facts.note || '课池中暂无能补缺口的课程'" :image-size="56" />
        <p v-if="facts.note" class="evidence-note">{{ facts.note }}</p>
      </div>

      <!-- 证据面板：选课政策（教务处通知 + 学生手册） -->
      <div class="bento-card bento-span-4 policy-card">
        <p class="bento-eyebrow">选课政策 · 教务处通知 + 学生手册</p>
        <div class="policy-head">
          <el-tag size="small" :type="windowTagType" effect="dark">{{ windowLabel }}</el-tag>
          <span v-if="windowInfo.text" class="policy-window">{{ windowInfo.text }}</span>
          <el-tag v-if="windowInfo.applies_to_current_term === false" size="small" type="info" effect="plain">
            通知窗口与当前学期不一致
          </el-tag>
        </div>
        <ul v-if="(policy.rules || []).length" class="policy-rules">
          <li v-for="(r, i) in policy.rules" :key="i">{{ r }}</li>
        </ul>
        <div v-if="(gened.modules || []).length" class="policy-gened">
          <p class="policy-sub">
            {{ gened.required_cohort }}级毕业前必修选修模块
            <template v-if="gened.applicable">（适用你所在年级）</template>
            <template v-else>（你所在年级 {{ gened.cohort || '未确认' }}，清单仅供参考）</template>
            · 专业类别：{{ { art: '艺术类', engineering: '工科类', other: '其他' }[gened.major_category] || '其他' }}
          </p>
          <div class="gap-tags">
            <el-tag
              v-for="m in gened.modules"
              :key="m.name"
              size="small"
              effect="plain"
              :type="m.exempt ? 'info' : (m.covered ? 'success' : 'danger')"
            >
              {{ m.name }}{{ m.exempt ? '（豁免）' : (m.covered ? '（已覆盖）' : '（未覆盖）') }}
            </el-tag>
          </div>
          <p v-if="gened.note" class="evidence-note">{{ gened.note }}</p>
        </div>
        <div v-if="credits.total_required" class="policy-credits">
          <div class="cover-line">
            <b>{{ credits.remaining }}</b>
            <small>学分距毕业最低总学分 {{ credits.total_required }}（已修 {{ credits.earned }} · 已选 {{ credits.elected }}）</small>
          </div>
          <p class="evidence-note">
            手册结构：通识 {{ credits.structure?.general }} / 专业 {{ credits.structure?.major }} / 实践 {{ credits.structure?.practice }} 学分，置换上限 {{ credits.substitution_cap }} 学分。{{ credits.note }}
          </p>
        </div>
        <div class="policy-source">
          <a v-if="policy.source?.url" :href="policy.source.url" target="_blank" rel="noopener">
            {{ policy.source.title }} ↗
          </a>
          <a v-if="policy.entry?.url" :href="policy.entry.url" target="_blank" rel="noopener">
            选课入口：{{ policy.entry.path }} ↗
          </a>
          <span v-if="credits.source" class="evidence-note">{{ credits.source }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '../api/http'

const router = useRouter()
const loading = ref(false)
const advising = ref(false)
const facts = ref({})
const advice = ref(null)
const question = ref('')
const error = ref('')

const target = computed(() => facts.value.target || {})
const policy = computed(() => facts.value.policy || {})
const windowInfo = computed(() => facts.value.window || {})
const gened = computed(() => facts.value.gened || {})
const credits = computed(() => facts.value.credits || {})
const windowTagType = computed(() => (
  windowInfo.value.state === 'open' ? 'success'
    : (windowInfo.value.state === 'before' ? 'warning' : 'info')))
const windowLabel = computed(() => (
  windowInfo.value.state === 'open' ? '选课窗口开放中'
    : (windowInfo.value.state === 'before' ? '选课窗口未开放' : '选课窗口已结束')))
const hasGaps = computed(() => (facts.value.skill_gaps || []).length > 0)
const planCourses = computed(() => advice.value?.plan?.courses || [])
const planRejected = computed(() => advice.value?.plan?.rejected || [])
const degradedText = computed(() => {
  const map = {
    llm_unavailable: '模型暂时不在线：以下为引擎模板稿，数值与候选课不受影响',
    critic_rejected: '模型稿未通过数值回查：已降级为引擎模板稿，数值以引擎为准'
  }
  return map[advice.value?.reason] || '已降级为引擎模板稿'
})

function goJobs() {
  router.push('/student/opportunity')
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data: res } = await http.get('/elective/advice')
    facts.value = res || {}
    if ((res?.skill_gaps || []).length && !advice.value) advise()
  } catch (err) {
    error.value = err?.response?.data?.detail || '选课数据加载失败'
    facts.value = { note: error.value }
  } finally {
    loading.value = false
  }
}

async function advise(message) {
  advising.value = true
  try {
    const { data: res } = await http.post('/elective/advise', {
      message: message || null
    }, { timeout: 180000 })
    advice.value = res || null
    if (res?.facts) facts.value = res.facts
  } catch (err) {
    advice.value = {
      reply: err?.response?.data?.detail || '智能体暂时不可用，请稍后再试',
      degraded: true,
      reason: 'llm_unavailable',
      plan: { courses: [], rejected: [] },
      critic: { passed: false, retries: 0 },
      engine_version: 'elective-v2'
    }
  } finally {
    advising.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.trust-bar {
  margin-bottom: 0;
  font-weight: 600;
}

.agent-card {
  border-left: 3px solid var(--el-color-primary);
}

.agent-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.agent-loading {
  padding: 12px 0;
}

.agent-loading-text {
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.agent-degraded {
  margin: 10px 0;
}

.agent-reply {
  margin: 12px 0;
  padding: 14px 16px;
  background: var(--el-fill-color-light);
  border-radius: 10px;
  white-space: pre-wrap;
  line-height: 1.8;
  font-size: 14px;
}

.plan-chips {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 10px 0;
}

.plan-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.plan-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}

.plan-idx {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
}

.plan-main {
  display: flex;
  flex-direction: column;
}

.plan-main small {
  color: var(--el-text-color-secondary);
}

.plan-rejected {
  color: var(--el-color-warning);
  font-size: 12px;
}

.agent-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 8px 0;
}

.agent-ask {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.target-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 8px 0;
}

.cover-line {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}

.cover-line b {
  font-size: 26px;
}

.cover-line small {
  color: var(--el-text-color-secondary);
}

.gap-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.fill-tag {
  margin-right: 4px;
}

.evidence-note {
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.policy-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.policy-window {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.policy-rules {
  margin: 0 0 10px;
  padding-left: 18px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.policy-sub {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.policy-credits {
  margin-top: 10px;
}

.policy-source {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 10px;
}

.policy-source a {
  font-size: 12px;
  color: var(--el-color-primary);
  text-decoration: none;
}

.act-row {
  margin-top: 10px;
}
</style>