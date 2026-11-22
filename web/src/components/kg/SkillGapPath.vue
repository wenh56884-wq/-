<template>
  <el-card shadow="never" class="block-card bento-span-4 gap-card">
    <template #header>
      <div class="head-row">
        <span class="card-title">岗位能力差距路径</span>
        <el-tag v-if="path?.found" size="small" effect="light"
          :type="missing.length ? 'danger' : 'success'">
          {{ missing.length ? `缺口 ${missing.length} 项` : '技能已全覆盖' }}
        </el-tag>
        <span class="muted">专业与身份均取自后端登录态</span>
      </div>
    </template>

    <div class="ctrl-row">
      <el-select v-model="jobId" class="job-select" filterable clearable
        :loading="jobsLoading" :disabled="jobsLoading || !jobs.length"
        :placeholder="jobsLoading ? '正在加载岗位…' : '选择目标岗位'"
        @change="onJobChange">
        <el-option v-for="j in jobs" :key="j.id" :value="j.id" :label="jobLabel(j)" />
      </el-select>
      <el-tag v-if="jobSource === 'recommend'" size="small" type="success" effect="plain">
        来源：本人岗位推荐
      </el-tag>
      <el-tag v-else-if="jobSource === 'catalog'" size="small" effect="plain">
        来源：岗位库兜底
      </el-tag>
      <el-button type="primary" :loading="pathLoading" :disabled="!jobId" @click="loadPath">
        查看差距
      </el-button>
    </div>

    <div class="result-zone" v-loading="pathLoading" element-loading-text="正在计算差距…">
      <div v-if="jobsLoading" class="state-box">正在加载岗位…</div>
      <div v-else-if="jobsError" class="state-box state-warn">
        <span>{{ jobsError }}</span>
        <el-button size="small" text @click="loadJobs">重试</el-button>
      </div>
      <div v-else-if="!jobs.length" class="state-box state-idle">
        <div class="state-title">暂无可选岗位</div>
        <div class="state-desc">本人推荐为空，岗位库也没有返回数据。</div>
      </div>
      <div v-else-if="!jobId" class="state-box state-idle">
        <div class="state-title">未选择岗位</div>
        <div class="state-desc">
          从上方选择目标岗位后，按本人专业生成「专业 → 课程 → 技能 → 岗位」路径；
          红色为课程链未覆盖的技能。
        </div>
      </div>
      <div v-else-if="pathError" class="state-box state-warn">
        <span>{{ pathError }}</span>
        <el-button size="small" text @click="loadPath">重试</el-button>
      </div>
      <template v-else-if="path">
        <el-alert v-if="!path.found" type="warning" :closable="false" class="mt12"
          :title="path.reason || '该岗位暂不在知识图谱中'" />
        <template v-else>
          <el-alert type="success" :closable="false" class="mt12" :title="path.summary" />

          <div class="path-flow">
            <div class="stage stage-major">
              <div class="stage-label">专业</div>
              <div class="stage-main">{{ path.major }}</div>
              <div class="stage-sub">本人登录专业</div>
            </div>
            <div class="flow-arrow">→</div>

            <div class="stage">
              <div class="stage-label">课程</div>
              <div class="chips">
                <el-tag v-for="c in courseNames" :key="c" size="small" effect="plain">{{ c }}</el-tag>
                <span v-if="!courseNames.length" class="stage-empty">无课程映射</span>
              </div>
            </div>
            <div class="flow-arrow">→</div>

            <div class="stage">
              <div class="stage-label">
                技能 <span class="stage-count">{{ covered.length }} / {{ required.length }}</span>
              </div>
              <div class="chips">
                <el-tag v-for="s in covered" :key="'c-' + s" size="small" type="success" effect="plain">
                  ✓ {{ s }}
                </el-tag>
                <el-tag v-for="s in missing" :key="'m-' + s" size="small" type="danger" effect="dark">
                  缺 {{ s }}
                </el-tag>
                <span v-if="!required.length" class="stage-empty">岗位暂无技能要求</span>
              </div>
            </div>
            <div class="flow-arrow">→</div>

            <div class="stage stage-job">
              <div class="stage-label">岗位</div>
              <div class="stage-main">{{ path.job }}</div>
              <div v-if="selectedJob" class="stage-sub">{{ jobSub(selectedJob) }}</div>
            </div>
          </div>

          <div v-if="path.chain?.length" class="chain-block">
            <div class="block-label">已覆盖链路（课程 → 技能 → 岗位）</div>
            <div class="chain-rows">
              <div v-for="(c, i) in path.chain" :key="i" class="chain-row">
                <span class="chip chip-course">
                  {{ c.courses?.length ? c.courses.join('、') : '（无课程映射）' }}
                </span>
                <span class="chain-arrow">→</span>
                <span class="chip chip-skill">{{ c.owned_as }}</span>
                <span class="chain-arrow">→</span>
                <span class="chip chip-job">{{ c.job }}</span>
              </div>
            </div>
          </div>

          <div v-if="missing.length" class="gap-band">
            <div class="block-label">岗位要求但课程链未覆盖（{{ missing.length }} 项）</div>
            <div class="chips">
              <el-tag v-for="s in missing" :key="s" type="danger" effect="dark" size="small">{{ s }}</el-tag>
            </div>
          </div>
        </template>
      </template>
    </div>
  </el-card>
</template>

<script setup>
// 学生端「岗位能力差距路径」：专业 → 课程 → 技能 → 岗位。
// 岗位来自本人推荐（空则岗位库兜底），required/covered/missing/chain/summary
// 全部原样取自 /kg/path/my（engine.kg 确定性计算），前端只做展示，不重算匹配。
import { computed, onMounted, ref } from 'vue'
import http from '../../api/http'

const jobs = ref([])
const jobsLoading = ref(false)
const jobsError = ref('')
const jobSource = ref('')
const jobId = ref(null)
const path = ref(null)
const pathLoading = ref(false)
const pathError = ref('')

const selectedJob = computed(() => jobs.value.find((j) => j.id === jobId.value) || null)
const required = computed(() => path.value?.required || [])
const covered = computed(() => path.value?.covered || [])
const missing = computed(() => path.value?.missing || [])
const courseNames = computed(() => {
  const names = []
  for (const c of path.value?.chain || []) {
    for (const name of c.courses || []) {
      if (!names.includes(name)) names.push(name)
    }
  }
  return names
})

function jobLabel(j) {
  return j.company ? `${j.title} · ${j.company}` : j.title
}

function jobSub(j) {
  return [j.company, j.city].filter(Boolean).join(' · ')
}

let pathSeq = 0

async function loadJobs() {
  jobsLoading.value = true
  jobsError.value = ''
  pathSeq += 1
  pathLoading.value = false
  jobId.value = null
  path.value = null
  pathError.value = ''
  try {
    let items = []
    try {
      const { data } = await http.get('/student/recommendations', { params: { top_n: 30 } })
      items = (data?.items || [])
        .map((it) => ({
          id: Number(it.job_id),
          title: it.title || `岗位 ${it.job_id}`,
          company: it.company || '',
          city: it.city || ''
        }))
        .filter((it) => it.id > 0)
      if (items.length) jobSource.value = 'recommend'
    } catch {
      // 推荐接口不可用时继续走岗位库兜底
    }
    if (!items.length) {
      const { data } = await http.get('/job/list', { params: { page: 1, page_size: 50 } })
      items = (data?.items || [])
        .map((it) => ({
          id: Number(it.id),
          title: it.title || `岗位 ${it.id}`,
          company: it.company || '',
          city: it.city || ''
        }))
        .filter((it) => it.id > 0)
      jobSource.value = 'catalog'
    }
    jobs.value = items
    if (!items.length) jobsError.value = '暂无可用岗位：本人推荐为空，岗位库也未返回数据。'
  } catch (err) {
    jobs.value = []
    jobsError.value = err?.response?.data?.detail || '岗位列表加载失败'
  } finally {
    jobsLoading.value = false
  }
}

async function loadPath() {
  const jid = jobId.value
  if (!jid) return
  const seq = ++pathSeq
  pathLoading.value = true
  pathError.value = ''
  try {
    const { data } = await http.get('/kg/path/my', { params: { job_id: jid } })
    if (seq !== pathSeq) return
    path.value = data
  } catch (err) {
    if (seq !== pathSeq) return
    path.value = null
    pathError.value = err?.response?.data?.detail || '差距路径加载失败'
  } finally {
    if (seq === pathSeq) pathLoading.value = false
  }
}

function onJobChange() {
  pathSeq += 1
  pathLoading.value = false
  path.value = null
  pathError.value = ''
  if (jobId.value) loadPath()
}

onMounted(loadJobs)
</script>

<style scoped>
.gap-card { min-width: 0; }
.head-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.card-title { font-weight: 600; }
.muted { margin-left: auto; color: var(--bento-mute); font-size: 13.5px; }
.ctrl-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.job-select { width: min(420px, 100%); }
.mt12 { margin-top: 12px; }
.result-zone { position: relative; min-height: 96px; margin-top: 12px; }
.state-box {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 18px;
  border: 1px dashed var(--el-border-color);
  border-radius: 10px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
.state-idle { flex-direction: column; align-items: flex-start; gap: 4px; }
.state-warn { border-color: var(--el-color-warning-light-5); color: var(--el-color-warning-dark-2); }
.state-title { font-weight: 600; color: var(--el-text-color-primary); }
.state-desc { color: var(--el-text-color-secondary); font-size: 13.5px; }

.path-flow {
  display: grid;
  grid-template-columns:
    minmax(120px, 0.9fr) 24px minmax(160px, 1.2fr) 24px
    minmax(180px, 1.4fr) 24px minmax(130px, 1fr);
  align-items: stretch;
  gap: 6px;
  margin-top: 14px;
}
.stage {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: var(--el-fill-color-extra-light);
}
.stage-major {
  border-color: var(--el-color-primary-light-7);
  background: var(--el-color-primary-light-9);
}
.stage-job {
  border-color: var(--el-color-warning-light-7);
  background: var(--el-color-warning-light-9);
}
.stage-label { margin-bottom: 6px; font-size: 12.5px; font-weight: 600; color: var(--el-text-color-secondary); }
.stage-count { font-weight: 400; }
.stage-main { font-size: 15px; font-weight: 700; overflow-wrap: anywhere; }
.stage-sub { margin-top: 4px; font-size: 12.5px; color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
.stage-empty { font-size: 13px; color: var(--el-text-color-secondary); }
.flow-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-placeholder);
  font-size: 18px;
}
.chips { display: flex; flex-wrap: wrap; gap: 6px; }

.chain-block, .gap-band { margin-top: 14px; }
.block-label { margin-bottom: 8px; font-size: 13px; font-weight: 600; color: var(--el-text-color-secondary); }
.chain-rows { display: flex; flex-direction: column; gap: 6px; }
.chain-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13.5px; }
.chip {
  display: inline-block;
  max-width: 100%;
  padding: 3px 10px;
  border-radius: 999px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.chip-course { background: var(--el-color-primary-light-9); color: var(--el-color-primary-dark-2); }
.chip-skill { background: var(--el-color-success-light-9); color: var(--el-color-success-dark-2); font-weight: 600; }
.chip-job { background: var(--el-color-warning-light-9); color: var(--el-color-warning-dark-2); font-weight: 600; }
.chain-arrow { color: var(--el-text-color-placeholder); }
.gap-band {
  padding: 12px 14px;
  border: 1px solid var(--el-color-danger-light-7);
  border-radius: 12px;
  background: var(--el-color-danger-light-9);
}
.gap-band .block-label { color: var(--el-color-danger-dark-2); }

@media (max-width: 900px) {
  .path-flow { grid-template-columns: 1fr; }
  .flow-arrow { transform: rotate(90deg); }
  .muted { margin-left: 0; }
}
</style>
