import io

p = 'D:/qihang/web/src/components/lab/GroupRoom.vue'
s = io.open(p, encoding='utf-8').read()

# 1) 选择器：远程搜索（输入关键词搜全库 2931 条，不局限于已载入的分层样本）
old_sel = '''          <el-select
            id="gr-job"
            v-model="jobId"
            class="gr-select"
            filterable
            clearable
            :loading="jobsLoading"
            placeholder="选择岗位（默认数据分析岗）"
          >
            <el-option v-for="j in jobs" :key="j.id" :value="j.id" :label="jobLabel(j)" />
          </el-select>
          <p v-if="jobsError" class="gr-hint warn">
            岗位列表加载失败，将按「{{ defaultJobTitle }}」开局
          </p>
          <p v-else class="gr-hint">议题会按岗位方向生成，和你选的方向有关。</p>'''
new_sel = '''          <el-select
            id="gr-job"
            v-model="jobId"
            class="gr-select"
            filterable
            clearable
            remote
            :remote-method="searchJobs"
            :loading="jobsLoading"
            placeholder="搜索或选择岗位（全行业，支持输入关键词）"
          >
            <el-option v-for="j in jobs" :key="j.id" :value="j.id" :label="jobLabel(j)" />
          </el-select>
          <p v-if="jobsError" class="gr-hint warn">
            岗位列表加载失败，将按「{{ defaultJobTitle }}」开局
          </p>
          <p v-else class="gr-hint">
            默认按行业各取一个代表岗位（共 {{ jobTotal }} 个行业）；输入关键词可搜全部岗位。
          </p>'''
assert s.count(old_sel) == 1
s = s.replace(old_sel, new_sel)

# 2) 脚本：分层加载 + 远程搜索
old_js = '''async function loadJobs() {
  jobsLoading.value = true
  jobsError.value = ''
  try {
    const { data } = await http.get('/interview/jobs', { params: { limit: 20 } })
    const items = Array.isArray(data?.items) ? data.items : []
    jobs.value = items.filter((j) => j && j.id != null)
    if (jobs.value.length && jobId.value == null) jobId.value = jobs.value[0].id
  } catch (err) {
    jobs.value = []
    jobsError.value = errText(err)
  } finally {
    jobsLoading.value = false
  }
}'''
new_js = '''// 初始用「行业分层」样本：岗位表头部是成片的 IT 岗，按编号取前 20 条会
// 让人以为岗位库只有计算机岗。diverse=1 让 82 个行业各出一个代表。
// 输入关键词时走远程搜索，覆盖全库。
const jobTotal = ref(0)
let jobSeq = 0

async function searchJobs(keyword) {
  const kw = String(keyword || '').trim()
  const seq = ++jobSeq
  jobsLoading.value = true
  try {
    if (!kw) {
      await loadJobs()
      return
    }
    const { data } = await http.get('/interview/jobs',
      { params: { limit: 30, keyword: kw } })
    if (seq !== jobSeq) return          // 已有更新的搜索，丢弃旧结果
    jobTotal.value = data?.total || 0
    jobs.value = (Array.isArray(data?.items) ? data.items : []).filter((j) => j && j.id != null)
  } catch (err) {
    if (seq === jobSeq) {
      jobs.value = []
      jobsError.value = errText(err)
    }
  } finally {
    if (seq === jobSeq) jobsLoading.value = false
  }
}

async function loadJobs() {
  jobsLoading.value = true
  jobsError.value = ''
  try {
    const { data } = await http.get('/interview/jobs', { params: { diverse: 1, limit: 60 } })
    const items = Array.isArray(data?.items) ? data.items : []
    jobs.value = items.filter((j) => j && j.id != null)
    jobTotal.value = data?.total || jobs.value.length
    if (jobs.value.length && jobId.value == null) jobId.value = jobs.value[0].id
  } catch (err) {
    jobs.value = []
    jobsError.value = errText(err)
  } finally {
    jobsLoading.value = false
  }
}'''
assert s.count(old_js) == 1
s = s.replace(old_js, new_js)

io.open(p, 'w', encoding='utf-8').write(s)
print('group frontend ok')
