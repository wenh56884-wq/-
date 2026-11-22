import io

p = 'D:/qihang/web/src/views/WorkflowApprovals.vue'
s = io.open(p, encoding='utf-8').read()

start = s.index('            <el-table-column prop="id" label="单号" width="72" />\n            <el-table-column prop="name" label="工作流" min-width="168" />')
end = s.index('          </el-table>\n        </template>\n\n        <!-- ============ 最近处理 ============ -->')

new_cols = """            <el-table-column label="工作流 / 单号" min-width="180">
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
            <el-table-column label="操作" width="156" fixed="right">
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
"""
s = s[:start] + new_cols + s[end:]

# 历史表：单号并入名称列，压缩其它列
old_hist = """            <el-table-column prop="run_id" label="单号" width="72" />
            <el-table-column prop="name" label="工作流" min-width="150" />
            <el-table-column label="结论" width="200">"""
new_hist = """            <el-table-column label="工作流 / 单号" min-width="180">
              <template #default="{ row }">
                <div class="wf-name-cell">
                  <span class="wf-name-text">{{ row.name }}</span>
                  <span class="wf-no">#{{ row.run_id }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="结论" width="196">"""
assert s.count(old_hist) == 1
s = s.replace(old_hist, new_hist)

old_people = """            <el-table-column label="提交人" width="120">
              <template #default="{ row }">{{ row.submitted_by?.name }}</template>
            </el-table-column>
            <el-table-column label="审批人" width="120">
              <template #default="{ row }">{{ row.approver_name }}</template>
            </el-table-column>
            <el-table-column label="意见" min-width="160">"""
new_people = """            <el-table-column label="提交人" width="104">
              <template #default="{ row }">{{ row.submitted_by?.name }}</template>
            </el-table-column>
            <el-table-column label="审批人" width="104">
              <template #default="{ row }">{{ row.approver_name }}</template>
            </el-table-column>
            <el-table-column label="意见" min-width="170">"""
assert s.count(old_people) == 1
s = s.replace(old_people, new_people)

s = s.replace("""            <el-table-column label="处理时间" width="112">""",
              """            <el-table-column label="处理时间" width="104">""")

# 样式：时间两行 + 名称单元格 + 按钮紧排
old_css = """.ts {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: var(--bento-sub, #5f6672);
}"""
new_css = """/* 时间两段显示：日期在上、时分在下。单行「11-18 22:53」在窄列里必然被截断，
   两行既省宽又不丢信息；完整值在 title 里。 */
.ts {
  display: inline-flex;
  flex-direction: column;
  line-height: 1.4;
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
}"""
assert s.count(old_css) == 1
s = s.replace(old_css, new_css)

# fmtShort 改成「日期 + 换行 + 时分」
old_fmt = """function fmtShort(iso) {
  if (!iso) return ''
  const s = String(iso).replace('T', ' ')
  return s.slice(5, 16)
}"""
new_fmt = """function fmtShort(iso) {
  if (!iso) return ''
  const s = String(iso).replace('T', ' ')
  return s.slice(5, 10) + ' ' + s.slice(11, 16)
}"""
assert s.count(old_fmt) == 1
s = s.replace(old_fmt, new_fmt)

io.open(p, 'w', encoding='utf-8').write(s)
print('patched')
