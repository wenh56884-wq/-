<!-- 自选字段导出：先勾字段，再选格式，导出的表就只包含你要的列。
     字段目录来自后端 /export/fields（与导出接口同一份定义），前端不维护第二套，
     否则总有一天会出现「界面能勾、导出来没有」的字段。 -->
<template>
  <el-dialog
    :model-value="modelValue"
    :title="meta.label || '自选字段导出'"
    width="760px"
    append-to-body
    class="exp-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="load"
  >
    <div class="exp">
      <header class="exp-head">
        <p class="exp-desc">{{ meta.desc || '勾选你想要的字段' }}</p>
        <div class="exp-tools">
          <input v-model="kw" class="exp-search" type="text" placeholder="搜索字段，如 GPA / 出勤 / 学分" />
          <button class="exp-link" type="button" @click="selectAll">全选</button>
          <button class="exp-link" type="button" @click="clearAll">清空</button>
        </div>
      </header>

      <div v-if="loading" class="exp-loading">字段目录加载中…</div>
      <div v-else-if="error" class="exp-error">{{ error }}</div>

      <div v-else class="exp-body">
        <section v-for="g in shownGroups" :key="g.name" class="exp-group">
          <header class="exp-group-head">
            <span class="exp-group-name">{{ g.name }}</span>
            <span class="exp-group-count">{{ pickedIn(g) }}/{{ g.fields.length }}</span>
            <button class="exp-link" type="button" @click="toggleGroup(g)">
              {{ pickedIn(g) === g.fields.length ? '取消本组' : '全选本组' }}
            </button>
          </header>
          <div class="exp-fields">
            <label
              v-for="f in g.fields"
              :key="f.key"
              class="exp-field"
              :class="{ on: !!picked[f.key] }"
            >
              <el-checkbox v-model="picked[f.key]" :label="f.label" />
            </label>
          </div>
        </section>
        <p v-if="!shownGroups.length" class="exp-empty">没有匹配「{{ kw }}」的字段</p>
      </div>
    </div>

    <template #footer>
      <div class="exp-foot">
        <span class="exp-count">已选 <b>{{ pickedKeys.length }}</b> / {{ total }} 列</span>
        <div class="exp-fmt" role="group" aria-label="导出格式">
          <button
            v-for="f in FORMATS"
            :key="f.value"
            type="button"
            class="fmt-btn"
            :class="{ on: fmt === f.value }"
            @click="fmt = f.value"
          >
            {{ f.label }}
          </button>
        </div>
        <el-button @click="emit('update:modelValue', false)">取消</el-button>
        <el-button type="primary" :loading="busy" :disabled="!pickedKeys.length" @click="submit">
          导出 {{ pickedKeys.length ? `${pickedKeys.length} 列` : '' }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import http from '../../api/http'
import { downloadFile } from '../../utils/download'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 下载接口完整路径，如 /export/students 或 /export/student-grades/AI20230001
  url: { type: String, required: true },
  // 字段目录的数据集名：students / grades / student-grades / my-grades
  dataset: { type: String, required: true },
  // 跟随页面当前筛选的参数（班级 / 学期 / 等级）
  params: { type: Object, default: () => ({}) },
  fallbackName: { type: String, default: '导出' }
})
const emit = defineEmits(['update:modelValue', 'done'])

const FORMATS = [
  { value: 'xlsx', label: 'Excel' },
  { value: 'csv', label: 'CSV' },
  { value: 'json', label: 'JSON' }
]

const loading = ref(false)
const busy = ref(false)
const error = ref('')
const meta = ref({})
const groups = ref([])
const picked = reactive({})
const kw = ref('')
const fmt = ref('xlsx')

const total = computed(() => groups.value.reduce((n, g) => n + g.fields.length, 0))

// 顺序固定按目录顺序，不按勾选顺序——与后端投影口径一致
const pickedKeys = computed(() => {
  const out = []
  groups.value.forEach((g) => g.fields.forEach((f) => {
    if (picked[f.key]) out.push(f.key)
  }))
  return out
})

const shownGroups = computed(() => {
  const q = kw.value.trim().toLowerCase()
  if (!q) return groups.value
  return groups.value
    .map((g) => ({
      ...g,
      fields: g.fields.filter(
        (f) => f.label.toLowerCase().includes(q) || f.key.toLowerCase().includes(q)
      )
    }))
    .filter((g) => g.fields.length)
})

function pickedIn(group) {
  return group.fields.filter((f) => picked[f.key]).length
}

function selectAll() {
  groups.value.forEach((g) => g.fields.forEach((f) => { picked[f.key] = true }))
}

function clearAll() {
  groups.value.forEach((g) => g.fields.forEach((f) => { picked[f.key] = false }))
}

function toggleGroup(group) {
  const all = pickedIn(group) === group.fields.length
  group.fields.forEach((f) => { picked[f.key] = !all })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await http.get('/export/fields', { params: { dataset: props.dataset } })
    meta.value = { label: data.label, desc: data.desc }
    groups.value = data.groups || []
    // 默认全选：多数人点开只是想换个格式，不想再勾十八个框
    groups.value.forEach((g) => g.fields.forEach((f) => {
      if (picked[f.key] === undefined) picked[f.key] = true
    }))
  } catch (e) {
    error.value = e?.response?.data?.detail || '字段目录加载失败'
    groups.value = []
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!pickedKeys.value.length) {
    ElMessage.warning('至少选一个字段')
    return
  }
  busy.value = true
  try {
    const name = await downloadFile(
      props.url,
      { ...props.params, fields: pickedKeys.value.join(','), fmt: fmt.value },
      `${props.fallbackName}.${fmt.value}`
    )
    ElMessage.success(`已导出 ${pickedKeys.value.length} 列：${name}`)
    emit('done', name)
    emit('update:modelValue', false)
  } catch {
    // 失败原因由 http 拦截器统一提示
  } finally {
    busy.value = false
  }
}

// 换数据集时重置勾选，避免上一个数据集的 key 残留
watch(
  () => props.dataset,
  () => {
    Object.keys(picked).forEach((k) => delete picked[k])
    if (props.modelValue) load()
  }
)
</script>

<style scoped>
.exp {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.exp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.exp-desc {
  margin: 0;
  font-size: 12.5px;
  color: var(--cf-mid);
}

.exp-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}

.exp-search {
  width: 220px;
  height: 32px;
  padding: 0 11px;
  border: 1px solid var(--cf-line);
  border-radius: 9px;
  background: #fff;
  font-family: inherit;
  font-size: 13px;
  color: var(--cf-ink);
}

.exp-search:focus {
  outline: none;
  border-color: #93b4e8;
  box-shadow: 0 0 0 3px rgba(25, 81, 195, 0.12);
}

.exp-link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--cf-coral);
  font-family: inherit;
  font-size: 12.5px;
  cursor: pointer;
}

.exp-link:hover {
  text-decoration: underline;
}

/* 字段区滚动：18 个字段全铺开会把弹窗撑到屏幕外 */
.exp-body {
  max-height: 46vh;
  overflow-y: auto;
  padding-right: 4px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.exp-group {
  border: 1px solid var(--cf-line);
  border-radius: 12px;
  padding: 10px 12px 12px;
  background: #fcfdff;
}

.exp-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.exp-group-name {
  font-size: 12.5px;
  font-weight: 650;
  color: var(--cf-ink);
}

.exp-group-count {
  font-size: 11.5px;
  color: var(--cf-faint);
  font-variant-numeric: tabular-nums;
}

.exp-group-head .exp-link {
  margin-left: auto;
}

.exp-fields {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px 10px;
}

.exp-field {
  display: flex;
  align-items: center;
  min-height: 34px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease;
}

.exp-field:hover {
  background: #f2f6ff;
}

.exp-field.on {
  border-color: #dbe6fb;
  background: #f6f9ff;
}

.exp-loading,
.exp-error,
.exp-empty {
  padding: 26px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--cf-faint);
}

.exp-error {
  color: var(--cf-danger);
}

.exp-foot {
  display: flex;
  align-items: center;
  gap: 12px;
}

.exp-count {
  font-size: 12.5px;
  color: var(--cf-mid);
}

.exp-count b {
  color: var(--cf-ink);
  font-variant-numeric: tabular-nums;
}

.exp-fmt {
  display: inline-flex;
  gap: 2px;
  margin-left: auto;
  padding: 3px;
  border: 1px solid var(--cf-line);
  border-radius: 9px;
  background: #f7f8fa;
}

.fmt-btn {
  padding: 5px 12px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--cf-mid);
  font-family: inherit;
  font-size: 12.5px;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.fmt-btn.on {
  background: #fff;
  color: var(--cf-coral);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(16, 24, 40, 0.1);
}

@media (max-width: 720px) {
  .exp-fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .exp-search {
    width: 100%;
  }

  .exp-tools {
    width: 100%;
  }

  .exp-foot {
    flex-wrap: wrap;
  }

  .exp-fmt {
    margin-left: 0;
  }
}
</style>
