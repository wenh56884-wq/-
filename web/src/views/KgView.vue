<template>
  <div class="page bento-page">
    <div class="bento-grid">
    <el-alert class="trust-bar bento-span-4" type="success" :closable="false" show-icon
      title="图谱由真实库表构建：专业—开设→课程—培养→技能 ←要求—岗位；每条边可回溯到库表" />

    <el-card
      v-for="(s, i) in statCards"
      :key="s.label"
      shadow="never"
      class="stat-card"
      :class="i === 0 || i >= 3 ? 'bento-span-2' : ''"
    >
      <div class="stat-num">{{ s.value }}</div>
      <div class="stat-label">{{ s.label }}</div>
    </el-card>

    <el-card shadow="never" class="block-card bento-span-2 bento-row-2">
      <template #header>
        <div class="head-row">
          <span class="card-title">以技能为中心的邻接子图</span>
          <span class="muted">构建于 {{ builtAt || '…' }}</span>
        </div>
      </template>
      <div class="ctrl-row">
        <el-select v-model="skill" filterable placeholder="选择技能（按岗位需求量排序）" class="sel">
          <el-option v-for="s in skills" :key="s[0]" :value="s[0]" :label="`${s[0]}（${s[1]} 个岗位）`" />
        </el-select>
        <el-button type="primary" :loading="graphLoading" :disabled="!skill" @click="loadNeighborhood">查看邻接图</el-button>
        <el-divider direction="vertical" />
        <el-select v-model="major" filterable placeholder="选择专业（查课程链）" class="sel">
          <el-option v-for="m in majors" :key="m[0]" :value="m[0]" :label="m[0]" />
        </el-select>
        <el-button :loading="chainLoading" :disabled="!major" @click="loadChain">专业→课程→技能</el-button>
      </div>

      <div v-if="nb" class="viz-wrap">
        <svg :viewBox="`0 0 680 460`" class="viz">
          <!-- 连线 -->
          <line v-for="(n, i) in ringNodes" :key="'l' + i"
            :x1="340" :y1="230" :x2="n.x" :y2="n.y"
            :stroke="n.group === 'job' ? '#f59e0b' : '#3b82f6'" stroke-opacity="0.35" />
          <!-- 中心技能 -->
          <circle cx="340" cy="230" r="34" fill="#10b981" />
          <text x="340" y="235" text-anchor="middle" fill="#fff" font-size="13" font-weight="700">{{ nb.center }}</text>
          <!-- 环绕节点 -->
          <g v-for="(n, i) in ringNodes" :key="n.id">
            <circle :cx="n.x" :cy="n.y" :r="n.group === 'job' ? 22 : 18"
              :fill="n.group === 'job' ? '#fbbf24' : '#93c5fd'" />
            <text :x="n.x" :y="n.y - (n.group === 'job' ? 30 : 26)" text-anchor="middle"
              fill="currentColor" font-size="11">
              {{ n.short }}
            </text>
          </g>
        </svg>
        <div class="viz-legend">
          <span><i class="dot" style="background:#10b981" />技能（中心）</span>
          <span><i class="dot" style="background:#fbbf24" />要求该技能的岗位（{{ nb.job_total }} 个，展示 {{ nb.jobs.length }}）</span>
          <span><i class="dot" style="background:#93c5fd" />培养该技能的课程</span>
        </div>
      </div>
    </el-card>

      <el-card shadow="never" class="block-card bento-span-2">
        <template #header>
          <span class="card-title">技能 → 岗位（{{ jobsBySkill.total }}）</span>
        </template>
        <el-table v-if="jobsBySkill.items" :data="jobsBySkill.items" size="small" height="320">
          <el-table-column prop="title" label="岗位" min-width="150" show-overflow-tooltip />
          <el-table-column prop="company" label="单位" min-width="110" show-overflow-tooltip />
          <el-table-column label="薪资上限" width="90">
            <template #default="{ row }">{{ row.salary_max ? '¥' + row.salary_max : '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="70">
            <template #default="{ row }">
              <el-button link type="primary" :disabled="!major" @click="explainFor(row)">解释链</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" class="block-card bento-span-2">
        <template #header><span class="card-title">专业 → 课程 → 技能（{{ skillsByMajor.total }} 项）</span></template>
        <div v-if="skillsByMajor.skills" class="chain-list">
          <div v-for="s in skillsByMajor.skills" :key="s.skill" class="chain-item">
            <el-tag size="small" effect="plain">{{ s.skill }}</el-tag>
            <span class="via">经 {{ s.via_courses.join('、') }}</span>
          </div>
          <div v-if="!skillsByMajor.skills.length" class="muted">先在上方选择专业</div>
        </div>
      </el-card>

    <el-card v-if="explain" shadow="never" class="block-card bento-span-4">
      <template #header>
        <div class="head-row"><span class="card-title">解释链：{{ explain.major }} → {{ explain.job }}</span>
          <el-tag type="success">{{ explain.summary }}</el-tag>
        </div>
      </template>
      <div class="explain-flow">
        <template v-for="(c, i) in explain.chain" :key="i">
          <div class="flow-node">
            <div class="fn-course">{{ c.courses.join('、') || '（无课程映射）' }}</div>
            <div class="fn-arrow">↓ 培养</div>
            <div class="fn-skill">{{ c.owned_as }}</div>
            <div class="fn-arrow">↓ 满足</div>
            <div class="fn-job">{{ c.skill }}</div>
          </div>
        </template>
      </div>
      <el-alert v-if="explain.missing.length" type="warning" :closable="false" class="mt8"
        :title="`缺口技能（${explain.missing.length} 项）：${explain.missing.join('、')}`" />
    </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import http from '../api/http'

const stats = ref(null)
const builtAt = ref('')
const skills = ref([])
const majors = ref([])
const skill = ref(null)
const major = ref(null)
const nb = ref(null)
const graphLoading = ref(false)
const chainLoading = ref(false)
const jobsBySkill = ref({ items: [] })
const skillsByMajor = ref({ skills: [] })
const explain = ref(null)

const statCards = computed(() => [
  { label: '专业', value: stats.value?.nodes_by_kind?.major || '-' },
  { label: '课程', value: stats.value?.nodes_by_kind?.course || '-' },
  { label: '技能', value: stats.value?.nodes_by_kind?.skill || '-' },
  { label: '岗位', value: stats.value?.nodes_by_kind?.job || '-' },
  { label: '关系边', value: stats.value?.edges || '-' }
])

const ringNodes = computed(() => {
  if (!nb.value) return []
  const nodes = []
  const all = [
    ...nb.value.jobs.map((j) => ({ ...j, group: 'job' })),
    ...nb.value.courses.map((c) => ({ ...c, group: 'course' }))
  ]
  const n = all.length
  all.forEach((item, i) => {
    const angle = (Math.PI * 2 * i) / Math.max(1, n) - Math.PI / 2
    const radius = item.group === 'job' ? 175 : 120
    nodes.push({
      ...item,
      x: 340 + radius * Math.cos(angle),
      y: 230 + radius * Math.sin(angle) * 0.85,
      short: item.label.length > 9 ? item.label.slice(0, 9) + '…' : item.label
    })
  })
  return nodes
})

async function loadStats() {
  const { data } = await http.get('/kg/stats')
  stats.value = data
  builtAt.value = data.built_at
}

async function loadFacets() {
  const { data } = await http.get('/kg/facets')
  skills.value = data.skills
  majors.value = data.majors
  if (data.skills.length) skill.value = data.skills[0][0]
  if (data.majors.length) major.value = data.majors[0][0]
}

async function loadNeighborhood() {
  graphLoading.value = true
  try {
    const { data } = await http.get('/kg/neighborhood', { params: { skill: skill.value } })
    nb.value = data
    const { data: jb } = await http.get('/kg/jobs-by-skill', { params: { skill: skill.value, limit: 15 } })
    jobsBySkill.value = jb
  } finally {
    graphLoading.value = false
  }
}

async function loadChain() {
  chainLoading.value = true
  try {
    const { data } = await http.get('/kg/skills-by-major', { params: { major: major.value } })
    skillsByMajor.value = data
    explain.value = null
  } finally {
    chainLoading.value = false
  }
}

async function explainFor(row) {
  const { data } = await http.get('/kg/explain', { params: { major: major.value, job_id: row.id } })
  explain.value = data
  explain.value.job = row.title
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
}

onMounted(async () => {
  await Promise.all([loadStats(), loadFacets()])
  await loadNeighborhood()
  await loadChain()
})
</script>

<style scoped>
.page { display: block; }
.trust-bar { border-radius: 16px; margin-bottom: 0; }
.card-title { font-weight: 600; }
.stat-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  justify-content: center;
  min-height: 112px;
  text-align: center;
}
.stat-num { font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums; }
.stat-label { font-size: 12px; color: var(--bento-mute); }
.muted { color: var(--bento-mute); font-size: 12px; }
.ctrl-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.sel { width: 280px; }
.viz-wrap { display: flex; flex-direction: column; align-items: center; }
.viz { width: 100%; max-width: 720px; color: var(--el-text-color-primary); }
.viz-legend { display: flex; gap: 16px; font-size: 12px; color: var(--el-text-color-secondary); }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; }
.chain-list { max-height: 320px; overflow: auto; }
.chain-item { margin: 6px 0; font-size: 13px; }
.via { margin-left: 8px; color: var(--el-text-color-secondary); font-size: 12px; }
.head-row { display: flex; align-items: center; gap: 8px; }
.explain-flow { display: flex; gap: 14px; flex-wrap: wrap; }
.flow-node { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 10px 14px; text-align: center; min-width: 150px; }
.fn-course { font-size: 12px; color: var(--el-color-primary); max-width: 170px; }
.fn-skill { font-size: 13px; font-weight: 700; color: var(--el-color-success); }
.fn-job { font-size: 13px; font-weight: 700; color: var(--el-color-warning); }
.fn-arrow { font-size: 11px; color: var(--el-text-color-secondary); margin: 2px 0; }
.mt8 { margin-top: 8px; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
