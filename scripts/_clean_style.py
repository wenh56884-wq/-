import io

p = 'D:/qihang/web/src/views/WorkflowApprovals.vue'
lines = io.open(p, encoding='utf-8').read().split('\n')

# 行号从 0 开始：保留到 .nowrap 之前（原 486 行），再跳到 .step-preview（原 698 行）
head_end = None
step_start = None
for i, ln in enumerate(lines):
    if ln.startswith('.nowrap {'):
        head_end = i
        break
for i in range(head_end, len(lines)):
    if lines[i].startswith('.step-preview {'):
        step_start = i
        break
assert head_end is not None and step_start is not None

clean = """.ts {
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

"""

out = lines[:head_end] + clean.split('\n') + lines[step_start:]
io.open(p, 'w', encoding='utf-8').write('\n'.join(out))
print('cleaned', head_end, step_start)
