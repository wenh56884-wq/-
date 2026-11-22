<template>
  <div class="page bento-page">
    <div class="bento-grid">
      <!-- 作用说明：审批页最容易变成「一排按钮」，先说清这条链路是什么 -->
      <div class="flow-guide bento-span-4">
        <div class="flow-guide-head">
          <span class="flow-guide-title">工作流审批是干什么的</span>
          <span class="flow-guide-sub">把「会替学生取数据的一串操作」交给人把关</span>
        </div>
        <div class="flow-steps">
          <div class="flow-step">
            <span class="flow-num">1</span>
            <div>
              <b>学生发起</b>
              <p>在 AI 助手里说「帮我跑一遍<b>求职体检（审批演示）</b>」这类流程。</p>
            </div>
          </div>
          <span class="flow-arrow">→</span>
          <div class="flow-step">
            <span class="flow-num">2</span>
            <div>
              <b>系统挂起</b>
              <p>设了「需要审批」的流程不会立刻执行，<b>一步都不跑</b>，先在这里排队等审。</p>
            </div>
          </div>
          <span class="flow-arrow">→</span>
          <div class="flow-step">
            <span class="flow-num">3</span>
            <div>
              <b>教师裁决</b>
              <p>通过 → 才真正执行（用<b>提交者本人</b>的身份取数）；驳回 → 永远不跑，意见会反馈给学生。</p>
            </div>
          </div>
        </div>
      </div>

      <el-card shadow="never" class="bento-span-4">
        <template #header>
          <div class="approval-head">
            <el-tabs v-model="tab" class="approval-tabs">
              <el-tab-pane label="待我审批" name="pending">
                <template #label>
                  待我审批<span v-if="items.length" class="pending-badge">{{ items.length }}</span>
                </template>
              </el-tab-pane>
              <el-tab-pane label="最近处理" name="history" />
            </el-tabs>
            <el-button size="small" :loading="loading" @click="load">刷新</el-button>
          </div>
        </template>

        <!-- ============ 待审批 ============ -->
        <template v-if="tab === 'pending'">
          <el-alert
            v-if="!loading && !items.length"
            class="approval-empty"
            type="info"
            :closable="false"
            show-icon
            title="当前没有待审批的申请"
            description="学生在 AI 助手触发「需要审批」的流程后，申请会出现在这里。没有申请说明还没人触发，不代表系统有问题。"
          />

          <el-table v-else v-loading="loading" :data="items" style="width: 100%">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="expand-body">
                  <p class="expand-caption">通过后将按以下顺序执行（以提交者本人的身份取数）：</p>
                  <ol class="step-list">
                    <li v-for="(st, i) in row.steps" :key="i">
                      <b>{{ st.title }}</b>
                      <span class="step-tool">{{ st.tool }}</span>
                      <span v-if="st.on_error === 'continue'" class="step-cont">失败可跳过</span>
                      <span v-else class="step-stop">失败即停</span>
                    </li>
                  </ol>
                  <p v-if="row.description" class="expand-desc">{{ row.description }}</p>
                  <p v-if="Object.keys(row.inputs || {}).length" class="expand-desc">
                    入参：{{ JSON.stringify(row.inputs) }}
                  </p>
                  <el-alert
                    v-if="row.definition_changed"
                    type="warning"
                    :closable="false"
                    show-icon
                    class="expand-warn"
                    title="提交后流程定义被改动过"
                    description="本次审批仍按「提交时」的步骤执行，审批的就是学生当时看到的那份流程。"
                  />
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="工作流 / 单号" min-width="180">
              <template #default="{ row }">
                <div class="wf-name-cell">
                  <span class="wf-name-text">{{ row.name }}</span>
                  <span class="wf-no">#{{ row.id }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="提交人" width="118">
              <template #default="{ row }">
                {{ row.submitted_by?.name }}
                <span class="actor-tag">（{{ actorText(row.submitted_by?.actor_type) }}）</span>
              </template>
            </el-table-column>
            <el-table-column label="将执行" min-width="176">
              <template #default="{ row }">
                <span class="step-preview">{{ stepPreview(row.steps) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="104">
              <template #default="{ row }">
                <span class="ts" :title="fmtTime(row.submitted_at)">{{ fmtShort(row.submitted_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="审批意见" width="156">
              <template #default="{ row }">
                <el-input
                  v-model="comments[row.id]"
                  size="small"
                  placeholder="意见（可留空）"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="148" fixed="right">
              <template #default="{ row }">
                <div class="act-cell">
                  <el-button
                    size="small"
                    type="success"
                    :loading="busyId === row.id"
                    @click="decide(row, 'approve')"
                  >通过</el-button>
                  <el-button
                    size="small"
                    type="danger"
                    :loading="busyId === row.id"
                    @click="decide(row, 'reject')"
                  >驳回</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </template>

        <!-- ============ 最近处理 ============ -->
        <template v-else>
          <el-empty v-if="!loading && !history.length" description="还没有审批记录" />
          <el-table v-else v-loading="loading" :data="history" style="width: 100%">
            <el-table-column label="工作流 / 单号" min-width="180">
              <template #default="{ row }">
                <div class="wf-name-cell">
                  <span class="wf-name-text">{{ row.name }}</span>
                  <span class="wf-no">#{{ row.run_id }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="结论" width="196">
              <template #default="{ row }">
                <el-tag :type="row.action === 'approve' ? 'success' : 'danger'" size="small">
                  {{ row.action === 'approve' ? '已通过' : '已驳回' }}
                </el-tag>
                <el-tag v-if="row.action === 'approve'" size="small" class="run-tag"
                        :type="row.status === 'success' ? 'success' : 'warning'">
                  {{ statusText(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="提交人" width="104">
              <template #default="{ row }">{{ row.submitted_by?.name }}</template>
            </el-table-column>
            <el-table-column label="审批人" width="104">
              <template #default="{ row }">{{ row.approver_name }}</template>
            </el-table-column>
            <el-table-column label="意见" min-width="170">
              <template #default="{ row }">
                <span v-if="row.comment">{{ row.comment }}</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="处理时间" width="104">
              <template #default="{ row }">
                <span class="ts" :title="fmtTime(row.decided_at)">{{ fmtShort(row.decided_at) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </template>

        <!-- 闭环说明：教师最想知道的是「我点完之后，学生那边看到什么」 -->
        <div class="after-note">
          <span class="after-item"><b>通过</b>学生首页「流程申请」显示「已执行完成」+ 逐步结果</span>
          <span class="after-item"><b>驳回</b>显示「已驳回」+ 你的意见原文，学生可改完再来</span>
          <span class="after-item"><b>执行中异常</b>学生看到失败原因，不会只看到"没反应"</span>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
// 职责：教师端「工作流审批」——人工审核学生/教师发起的流程执行申请。
// 链路：学生 AI 助手触发 → 挂起排队 → 这里通过（以提交者身份执行）或驳回（一步不跑）。
// 通过才真正执行步骤；驳回意见会出现在学生端「流程申请」里。
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs'

import http from '../api/http'

const tab = ref('pending')
const items = ref([])
const history = ref([])
const loading = ref(false)
const busyId = ref(0)
const comments = reactive({})

function actorText(type) {
  return type === 'teacher' ? '教师' : '学生'
}

function statusText(s) {
  return { success: '执行成功', failed: '执行失败', running: '执行中' }[s] || s
}

function fmtTime(iso) {
  if (!iso) return ''
  return String(iso).replace('T', ' ').slice(0, 19)
}

// 列表里只给到分钟：审批看的是「先后」，秒没有信息量；完整时间挂在 title 上
function fmtShort(iso) {
  if (!iso) return ''
  const s = String(iso).replace('T', ' ')
  return s.slice(5, 16)
}

// 展开前先给一行预览：不想展开的教师也能看出这一单是干什么的
function stepPreview(steps) {
  const names = (steps || []).map(s => s.title)
  return names.length > 3 ? names.slice(0, 3).join(' → ') + ' …' : names.join(' → ')
}

async function load() {
  loading.value = true
  try {
    const [p, h] = await Promise.all([
      http.get('/workflow/approvals/pending', { params: { limit: 50 } }),
      http.get('/workflow/approvals/history', { params: { limit: 30 } })
    ])
    items.value = p.data?.items || []
    history.value = h.data?.items || []
  } catch {
    items.value = []
    history.value = []
  } finally {
    loading.value = false
  }
}

async function decide(row, action) {
  // 通过会真正执行步骤（且以提交者身份跑），驳回则一步不跑——两者都不可逆，
  // 所以先确认，避免误点。取消时 ElMessageBox 会 reject，直接返回即可。
  const approve = action === 'approve'
  const who = row.submitted_by?.name ? `（提交人 ${row.submitted_by.name}）` : ''
  const steps = (row.steps || []).map(s => s.title).join(' → ')
  const warn = row.definition_changed
    ? '\n注意：提交后流程定义被改动过，本次按「提交时快照」执行。'
    : ''
  try {
    await ElMessageBox.confirm(
      (approve
        ? `通过后才会真正执行「${row.name}」${who}。\n将执行：${steps}\n以提交者本人的身份取数。`
        : `驳回后「${row.name}」一步都不会执行，意见会反馈给学生。`) + warn,
      approve ? '确认通过并执行？' : '确认驳回？',
      {
        type: approve ? 'warning' : 'error',
        confirmButtonText: approve ? '通过并执行' : '驳回',
        cancelButtonText: '再看看',
        distinguishCancelAndClose: true
      }
    )
  } catch {
    return
  }

  busyId.value = row.id
  try {
    const { data } = await http.post(`/workflow/runs/${row.id}/decide`, {
      action,
      comment: comments[row.id] || null
    })
    ElMessage.success(
      action === 'approve'
        ? `已通过：${String(data?.summary || '').slice(0, 60)}`
        : `已驳回「${row.name}」，工作流没有执行，意见已记录。`
    )
    delete comments[row.id]
    await load()
  } finally {
    busyId.value = 0
  }
}

onMounted(load)
</script>

<style scoped>
/* ---- 作用说明卡 ---- */
.flow-guide {
  padding: 18px 22px;
  border: 1px solid var(--bento-border, #e4e7ee);
  border-radius: 16px;
  background: linear-gradient(180deg, #fbfdff, #f6f9fc);
}

.flow-guide-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 14px;
}

.flow-guide-title {
  font-size: 15px;
  font-weight: 700;
}

.flow-guide-sub {
  font-size: 12.5px;
  color: var(--bento-sub, #6b7280);
}

.flow-steps {
  display: flex;
  align-items: stretch;
  gap: 10px;
}

.flow-step {
  display: flex;
  flex: 1;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--bento-border, #e4e7ee);
  border-radius: 12px;
  background: #fff;
}

.flow-num {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  border-radius: 50%;
  background: #eef6f4;
  color: #0f9d8a;
  font-size: 12px;
  font-weight: 700;
}

.flow-step b {
  font-size: 13px;
}

.flow-step p {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.65;
  color: var(--bento-sub, #5f6672);
}

.flow-step p b {
  font-size: 12px;
  color: var(--bento-text, #16181d);
}

.flow-arrow {
  align-self: center;
  color: #b9c2cf;
  font-size: 16px;
}

/* ---- Tab 与徽标 ---- */
.approval-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.approval-tabs {
  flex: 1;
  margin-bottom: -16px;
}

.approval-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}

.pending-badge {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  margin-left: 6px;
  padding: 0 5px;
  border-radius: 999px;
  background: #e05a4e;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
}

.actor-tag {
  color: var(--bento-sub, #6b7280);
  font-size: 12px;
}

/* ---- 展开明细 ---- */
.expand-body {
  padding: 6px 12px 10px 46px;
}

.expand-caption {
  margin: 0 0 8px;
  font-size: 12.5px;
  font-weight: 600;
}

.step-list {
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: step;
}

.step-list li {
  position: relative;
  padding: 7px 0 7px 34px;
  border-bottom: 1px dashed #eef0f4;
  font-size: 13px;
}

.step-list li::before {
  counter-increment: step;
  content: counter(step);
  position: absolute;
  left: 0;
  top: 7px;
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #eef2f7;
  color: #5a6472;
  font-size: 11px;
  font-weight: 600;
}

.step-tool {
  margin-left: 10px;
  padding: 1px 7px;
  border-radius: 6px;
  background: #f4f6f9;
  color: #8a93a3;
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 11px;
}

.step-cont,
.step-stop {
  margin-left: 10px;
  font-size: 11px;
  color: #98a1b0;
}

.step-stop {
  color: #c08a2e;
}

.expand-desc {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--bento-sub, #5f6672);
}

.expand-warn {
  margin-top: 12px;
}

.ts {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: var(--bento-sub, #5f6672);
  font-size: 12px;
}

.wf-name-cell {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.wf-name-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-no {
  flex: 0 0 auto;
  color: #a6aebb;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

/* 两个按钮紧排并排：默认 el-button 的 12px 左外边距会把「驳回」挤到下一行 */
.act-cell {
  display: flex;
  gap: 6px;
  white-space: nowrap;
}

.act-cell :deep(.el-button + .el-button) {
  margin-left: 0;
}

.act-cell :deep(.el-button) {
  padding-left: 10px;
  padding-right: 10px;
}


.step-preview {
  font-size: 12px;
  color: var(--bento-sub, #5f6672);
}

.muted {
  color: #b0b7c3;
}

/* 闭环说明：一行三句，说明裁决后学生端看到什么 */
.after-note {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 22px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--bento-border, #e4e7ee);
  font-size: 12px;
  color: var(--bento-sub, #5f6672);
}

.after-item b {
  margin-right: 4px;
  color: var(--bento-text, #16181d);
  font-weight: 600;
}

.run-tag {
  margin-left: 8px;
}

/* 空状态不是成功提示：降成中性底，只让图标保留「已清空」的绿色 */
.approval-empty.el-alert {
  background: #f8fafc;
  border: 1px solid var(--bento-border, #e4e7ee);
  border-radius: 14px;
}

.approval-empty :deep(.el-alert__icon) {
  color: #0f9d8a;
}

.approval-empty :deep(.el-alert__title) {
  color: var(--bento-text, #16181d);
  font-weight: 600;
}

.approval-empty :deep(.el-alert__description) {
  color: var(--bento-sub, #5f6672);
  line-height: 1.7;
}

@media (max-width: 760px) {
  .flow-steps {
    flex-direction: column;
  }

  .flow-arrow {
    transform: rotate(90deg);
    align-self: center;
  }
}
</style>
