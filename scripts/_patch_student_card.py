import io

p = 'D:/qihang/web/src/views/StudentHome.vue'
s = io.open(p, encoding='utf-8').read()

# 1) 卡片条件：有申请记录，或本租户有「需要审批」的流程 → 都显示
old_head = """    <el-card v-if="wfRuns.length" shadow="never" class="wf-card bento-span-4 qh-reveal" :style="{ '--qh-index': 7 }">
      <template #header>
        <div class="wf-head">
          <span class="card-title" style="margin: 0">流程申请</span>
          <span class="wf-hint">在 AI 助手说「帮我跑一遍〈流程名〉」即可发起；需审批的流程由教师通过后执行</span>
        </div>
      </template>
      <div class="wf-list">"""
new_head = """    <el-card v-if="wfRuns.length || wfAvailable.length" shadow="never"
             class="wf-card bento-span-4 qh-reveal" :style="{ '--qh-index': 7 }">
      <template #header>
        <div class="wf-head">
          <span class="card-title" style="margin: 0">流程申请</span>
          <span class="wf-hint">点下面的流程即可提交；需教师审批，通过后才执行（只用你自己的数据）</span>
        </div>
      </template>
      <div v-if="wfRuns.length" class="wf-list">"""
assert s.count(old_head) == 1
s = s.replace(old_head, new_head)

# 2) 列表结束后接「可申请的流程」按钮区
old_tail = """          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="rec-card bento-span-4 qh-reveal" :style="{ '--qh-index': 7 }">"""
new_tail = """          </div>
        </div>
      </div>

      <!-- 可申请的流程：没有这块，卡片只对「已经玩过的人」可见，新学生永远发现不了 -->
      <div v-if="wfAvailable.length" class="wf-apply" :class="{ 'has-runs': wfRuns.length }">
        <span class="wf-apply-label">可申请的流程</span>
        <button v-for="w in wfAvailable" :key="w.id" type="button" class="wf-chip"
                :title="w.description || ''" @click="applyWorkflow(w)">
          <b>{{ w.name }}</b>
          <span v-if="w.description" class="wf-chip-desc">{{ w.description }}</span>
        </button>
      </div>
    </el-card>

    <el-card shadow="never" class="rec-card bento-span-4 qh-reveal" :style="{ '--qh-index': 7 }">"""
assert s.count(old_tail) == 1
s = s.replace(old_tail, new_tail)

# 3) 脚本：可用流程 + 点击发起
old_js = """const wfRuns = ref([])"""
new_js = """const wfRuns = ref([])
const wfAvailable = ref([])"""
assert s.count(old_js) == 1
s = s.replace(old_js, new_js)

old_load = """async function loadWfRuns() {
  try {
    const { data } = await http.get('/workflow/my-runs', { params: { limit: 5 } })
    wfRuns.value = data?.items || []
  } catch {
    wfRuns.value = []
  }
}"""
new_load = """async function loadWfRuns() {
  try {
    const { data } = await http.get('/workflow/my-runs', { params: { limit: 5 } })
    wfRuns.value = data?.items || []
    wfAvailable.value = data?.available || []
  } catch {
    wfRuns.value = []
    wfAvailable.value = []
  }
}

// 点流程 = 在 AI 助手里发出「帮我跑一遍 X」。走同一条链路，不在页面另开接口，
// 保证「页面点的」和「嘴上说的」是同一件事。
async function applyWorkflow(w) {
  try {
    await ElMessageBox.confirm(
      `「${w.name}」会提交给教师审批，通过后才执行，且只读取你自己的数据。`,
      '确认提交申请？',
      { type: 'info', confirmButtonText: '提交申请', cancelButtonText: '再看看' }
    )
  } catch {
    return
  }
  askAI(`帮我跑一遍${w.name}`)
}"""
assert s.count(old_load) == 1
s = s.replace(old_load, new_load)

# 4) 引入 ElMessageBox
old_imp = """import { ElMessage } from 'element-plus/es/components/message/index.mjs'"""
new_imp = """import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs'"""
assert s.count(old_imp) == 1
s = s.replace(old_imp, new_imp)

# 5) 样式
old_css = """.wf-list {"""
new_css = """/* 可申请的流程：一行小胶囊，说明它是什么、点了会发生什么 */
.wf-apply {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.wf-apply.has-runs {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--bento-border, #e4e7ee);
}

.wf-apply-label {
  font-size: 12px;
  color: var(--bento-sub, #6b7280);
}

.wf-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  max-width: 100%;
  padding: 7px 14px;
  border: 1px solid #cfe3df;
  border-radius: 999px;
  background: #f4fbf9;
  color: #0f7a6b;
  font-family: inherit;
  font-size: 12.5px;
  cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease;
}

.wf-chip:hover {
  border-color: #0f9d8a;
  background: #ecf8f5;
}

.wf-chip b {
  font-weight: 600;
  white-space: nowrap;
}

.wf-chip-desc {
  color: #6b8f89;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 420px;
}

@media (max-width: 760px) {
  .wf-chip-desc {
    display: none;
  }
}

.wf-list {"""
assert s.count(old_css) == 1
s = s.replace(old_css, new_css)

io.open(p, 'w', encoding='utf-8').write(s)
print('student card ok')
