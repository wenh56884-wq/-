<template>
  <div class="page bento-page">
    <div class="bento-grid">
      <el-card shadow="never" class="bento-span-4">
        <template #header>
          <div class="approval-head">
            <span class="approval-title">待我审批的工作流</span>
            <el-button size="small" :loading="loading" @click="load">刷新</el-button>
          </div>
        </template>

        <el-alert
          v-if="!loading && !items.length"
          type="success"
          :closable="false"
          show-icon
          title="当前没有待审批的工作流"
          description="教师把某个工作流设为「需要审批」后，师生触发它不会立刻执行，会先挂起并出现在这里；通过才真正跑，驳回则一步都不会跑。"
        />

        <el-table v-else v-loading="loading" :data="items" style="width: 100%">
          <el-table-column prop="id" label="单号" width="72" />
          <el-table-column prop="name" label="工作流" min-width="150">
            <template #default="{ row }">
              {{ row.name }}
              <el-tag v-if="row.definition_changed" size="small" type="warning">
                定义已改动
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="提交人" width="150">
            <template #default="{ row }">
              {{ row.submitted_by?.name }}
              <span class="actor-tag">（{{ actorText(row.submitted_by?.actor_type) }}）</span>
            </template>
          </el-table-column>
          <el-table-column label="提交时间" width="168">
            <template #default="{ row }">{{ fmtTime(row.submitted_at) }}</template>
          </el-table-column>
          <el-table-column label="审批意见" min-width="180">
            <template #default="{ row }">
              <el-input
                v-model="comments[row.id]"
                size="small"
                placeholder="可不填，驳回建议写明原因"
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
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
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>
  </div>
</template>

<script setup>
// 职责：教师端「待我审批」——人工审核工作流的执行申请。
// 说明：审批通过才真正执行步骤，且用的是**提交者**的身份（学生提交的流程只会取到他本人的数据）。
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import http from '../api/http'

const items = ref([])
const loading = ref(false)
const busyId = ref(0)
const comments = reactive({})

function actorText(type) {
  return type === 'teacher' ? '教师' : '学生'
}

function fmtTime(iso) {
  if (!iso) return ''
  return String(iso).replace('T', ' ').slice(0, 19)
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/workflow/approvals/pending', { params: { limit: 50 } })
    items.value = data?.items || []
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

async function decide(row, action) {
  // 通过会真正执行步骤（且以提交者身份跑），驳回则一步不跑——两者都不可逆，
  // 所以先确认，避免误点。取消时 ElMessageBox 会 reject，直接返回即可。
  const approve = action === 'approve'
  const who = row.submitted_by?.name ? `（提交人 ${row.submitted_by.name}）` : ''
  const warn = row.definition_changed
    ? '\n注意：提交后流程定义被改动过，本次按「提交时快照」执行。'
    : ''
  try {
    await ElMessageBox.confirm(
      (approve
        ? `通过后才会真正执行「${row.name}」，并以提交者的身份取数${who}。`
        : `驳回后「${row.name}」一步都不会执行，需由提交人重新发起。`) + warn,
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
        : `已驳回「${row.name}」，工作流没有执行。`
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
.approval-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.approval-title {
  font-size: 15px;
  font-weight: 600;
}

.actor-tag {
  color: var(--bento-sub, #6b7280);
  font-size: 12px;
}
</style>
