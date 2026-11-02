<template>
  <div class="page bento-page">
    <div class="bento-grid">
      <el-alert class="trust-bar bento-span-4" :type="configured === false ? 'warning' : 'info'"
        :closable="false" show-icon :title="engineText" />

      <!-- ---------- 搜索条 ---------- -->
      <el-card shadow="never" class="bento-span-4 search-card">
        <div class="search-row">
          <el-input v-model="query" size="large" clearable placeholder="输入要查询的问题，如「2026 国考报名条件」"
            @keyup.enter="run">
            <template #prefix>
              <svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35" />
              </svg>
            </template>
          </el-input>
          <el-button type="primary" size="large" :loading="loading" @click="run">搜索</el-button>
        </div>

        <div class="quick-row">
          <span class="quick-label">试试：</span>
          <button v-for="q in QUICK_QUERIES" :key="q" type="button" class="quick-chip"
            @click="useQuick(q)">
            {{ q }}
          </button>
        </div>
      </el-card>

      <!-- ---------- 左右分栏：结果列表 | 摘要详情 ---------- -->
      <div class="bento-span-4 ws-split">
        <el-card v-loading="loading" shadow="never" class="ws-list">
          <template #header>
            <div class="ws-head">
              <span class="card-title">搜索结果</span>
              <span v-if="results.length" class="ws-count">共 {{ results.length }} 条</span>
            </div>
          </template>

          <div v-if="results.length" class="ws-items">
            <button v-for="(r, i) in results" :key="r.url + i" type="button" class="ws-item"
              :class="{ 'is-active': i === activeIndex }" @click="activeIndex = i">
              <div class="ws-item-head">
                <span class="ws-item-no">[{{ i + 1 }}]</span>
                <span class="ws-item-host">{{ hostOf(r.url) }}</span>
              </div>
              <div class="ws-item-title">{{ r.title || r.url }}</div>
              <div v-if="r.snippet" class="ws-item-snippet">{{ r.snippet }}</div>
            </button>
          </div>

          <el-empty v-else :description="emptyText" :image-size="70" />
        </el-card>

        <el-card shadow="never" class="ws-detail">
          <template #header>
            <span class="card-title">来源详情</span>
          </template>

          <template v-if="active">
            <div class="ws-detail-host">{{ hostOf(active.url) }}</div>
            <h3 class="ws-detail-title">{{ active.title || active.url }}</h3>
            <p class="ws-detail-snippet">{{ active.snippet || '（该结果未提供摘要，请打开原网页查看）' }}</p>

            <div class="ws-detail-url">
              <span class="ws-detail-url-label">原文地址</span>
              <span class="ws-detail-url-text">{{ active.url }}</span>
            </div>

            <div class="ws-detail-actions">
              <el-button type="primary" @click="openActive">新窗口打开 →</el-button>
              <el-button @click="copyUrl">复制链接</el-button>
            </div>

            <p class="ws-detail-note">
              右侧显示的是搜索引擎返回的摘要，不是本系统生成的结论。
              全文需跳转到原站核对——绝大多数网站禁止被嵌入 iframe，直接内嵌会白屏。
            </p>
          </template>

          <el-empty v-else description="从左侧选一条结果，这里显示它的来源与摘要" :image-size="70" />
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api/http'

// 演示时点一下就能出结果，省得现场手打关键词
const QUICK_QUERIES = ['2026 国考报名条件', '软件工程师 校招 要求', '重庆 事业单位 招聘']

const query = ref('')
const loading = ref(false)
const data = ref(null) // 引擎原样返回：{ configured, provider, query, results, error, took_ms }
const activeIndex = ref(0)

const results = computed(() => data.value?.results || [])
const active = computed(() => results.value[activeIndex.value] || null)
// 没搜过之前 data 为 null，此时不显示「未配置」警告，只在中立状态待命
const configured = computed(() => (data.value ? data.value.configured !== false : true))

const engineText = computed(() => {
  if (!data.value) {
    return '联网搜索由外部搜索引擎提供，每条结果都带真实链接，可点开核对原文；回答不做二次加工'
  }
  if (data.value.configured === false) {
    return `当前没有联网能力：${data.value.error || '未配置搜索密钥'}`
  }
  const bits = [`引擎 ${data.value.engine_version || 'web-v1'}`]
  if (data.value.provider) bits.push(`服务商 ${data.value.provider}`)
  if (results.value.length) bits.push(`${results.value.length} 条结果`)
  if (data.value.took_ms !== undefined) bits.push(`耗时 ${data.value.took_ms} ms`)
  if (data.value.cached) bits.push('命中 10 分钟缓存')
  return bits.join(' · ')
})

const emptyText = computed(() => {
  if (!data.value) return '输入关键词开始搜索'
  if (data.value.configured === false) return '未配置联网搜索密钥，当前不具备联网能力'
  if (data.value.error) return data.value.error
  return '没有搜到结果，换个说法试试'
})

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch (err) {
    return ''
  }
}

function useQuick(text) {
  query.value = text
  run()
}

async function run() {
  const q = query.value.trim()
  if (!q) {
    ElMessage.warning('请先输入搜索关键词')
    return
  }
  loading.value = true
  activeIndex.value = 0
  try {
    const { data: res } = await http.get('/web/search', { params: { q, top_k: 8 } })
    data.value = res || null
    // 未配置 / 出错 / 空结果都要说清楚，不能让界面停在「转圈完了什么都没有」
    if (res && res.configured === false) {
      ElMessage.warning(res.error || '当前未配置联网搜索密钥，没有联网能力')
    } else if (res?.error) {
      ElMessage.error(res.error)
    } else if (res && !(res.results || []).length) {
      ElMessage.info('没有搜到结果')
    }
  } catch (err) {
    data.value = null
    // 后端接口未就绪时是 404，明说是接口没实现，别让人去查网络或密钥
    const status = err?.response?.status
    ElMessage.error(status === 404 ? '搜索接口尚未就绪（后端未实现 /web/search）' : '搜索失败')
  } finally {
    loading.value = false
  }
}

function openActive() {
  if (active.value?.url) window.open(active.value.url, '_blank', 'noopener')
}

async function copyUrl() {
  const url = active.value?.url
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success('链接已复制')
  } catch (err) {
    ElMessage.warning('浏览器拒绝了剪贴板访问，请手动复制')
  }
}
</script>

<style scoped>
.search-card {
  padding-bottom: 4px;
}

.search-row {
  display: flex;
  gap: 12px;
}

.search-row .el-input {
  flex: 1 1 auto;
}

.search-icon {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: var(--bento-mute);
  stroke-width: 2;
  stroke-linecap: round;
}

.quick-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.quick-label {
  font-size: 14px;
  color: var(--bento-mute);
}

.quick-chip {
  padding: 5px 12px;
  border: 1px solid var(--bento-border);
  border-radius: 999px;
  background: #ffffff;
  font-size: 14px;
  color: var(--bento-sub);
  cursor: pointer;
  transition:
    border-color 180ms var(--bento-ease),
    background-color 180ms var(--bento-ease),
    color 180ms var(--bento-ease);
}

.quick-chip:hover {
  border-color: var(--bento-accent);
  background: var(--bento-accent-soft);
  color: var(--bento-accent);
}

/* ---------- 左右分栏 ---------- */
.ws-split {
  display: flex;
  align-items: flex-start;
  gap: var(--bento-gap);
}

.ws-list {
  flex: 1 1 42%;
  min-width: 0;
}

.ws-detail {
  flex: 1 1 58%;
  min-width: 0;
  position: sticky;
  top: 0;
}

.ws-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.ws-count {
  font-size: 14px;
  color: var(--bento-mute);
}

.ws-items {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ws-item {
  display: block;
  width: 100%;
  padding: 13px 15px;
  border: 1px solid var(--bento-border);
  border-radius: var(--bento-radius-sm);
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  transition:
    transform 180ms var(--bento-ease),
    border-color 180ms var(--bento-ease),
    background-color 180ms var(--bento-ease);
}

.ws-item:hover {
  transform: translateY(-1px);
  border-color: #ded9ff;
  background: #fbfbff;
}

.ws-item.is-active {
  border-color: var(--bento-accent);
  background: var(--bento-accent-soft);
}

.ws-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.ws-item-no {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--bento-accent);
  font-variant-numeric: tabular-nums;
}

.ws-item-host {
  font-size: 13.5px;
  color: var(--bento-mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ws-item-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.6;
  color: var(--bento-text);
}

.ws-item-snippet {
  margin-top: 5px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--bento-sub);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ---------- 详情 ---------- */
.ws-detail-host {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--bento-accent-soft);
  color: var(--bento-accent);
  font-size: 13.5px;
}

.ws-detail-title {
  margin: 12px 0 14px;
  font-size: 17px;
  font-weight: 650;
  line-height: 1.7;
  color: var(--bento-text);
}

.ws-detail-snippet {
  margin: 0 0 18px;
  font-size: 14px;
  line-height: 1.9;
  color: var(--bento-sub);
}

.ws-detail-url {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 11px 14px;
  border-radius: var(--bento-radius-sm);
  background: #f7f8fd;
}

.ws-detail-url-label {
  flex: 0 0 auto;
  font-size: 13.5px;
  color: var(--bento-mute);
}

.ws-detail-url-text {
  min-width: 0;
  font-size: 14px;
  color: var(--bento-sub);
  word-break: break-all;
}

.ws-detail-actions {
  display: flex;
  gap: 10px;
  margin: 18px 0 14px;
}

.ws-detail-note {
  margin: 0;
  padding-top: 14px;
  border-top: 1px dashed var(--bento-border-strong);
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--bento-mute);
}

@media (max-width: 1023px) {
  .ws-split {
    flex-direction: column;
  }

  .ws-detail {
    position: static;
  }
}
</style>
