import io

p = 'D:/qihang/web/src/views/WorkflowApprovals.vue'
s = io.open(p, encoding='utf-8').read()

block = """/* 时间是两段：日期在上、时分在下。单行「11-18 22:53」在窄列里必然被截，
   两行既省宽又不丢信息。 */
.ts {
  display: inline-flex;
  flex-direction: column;
  line-height: 1.35;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: var(--bento-sub, #5f6672);
  font-size: 12px;
}

.ts::before {
  content: attr(data-date);
}
"""

n = s.count(block)
assert n == 2, n
# 保留第一处，删掉第二处
first = s.index(block)
second = s.index(block, first + len(block))
s = s[:second] + s[second + len(block):]

# 同理清理重复的 wf-name-cell / wf-no / act-cell（若重复）
def dedup(text: str, marker: str, tail: str = ""):
    a = text.find(marker)
    if a < 0:
        return text
    b = text.find(marker, a + 1)
    if b < 0:
        return text
    end = text.find("}", b)
    # 删除到该块结束（含尾部空行）
    cut_end = end + 2
    return text[:b] + text[cut_end:]

for marker in (".wf-name-cell {", ".wf-name-text {", ".wf-no {", ".act-cell {"):
    s = dedup(s, marker)

io.open(p, 'w', encoding='utf-8').write(s)
print("dedup ok")
