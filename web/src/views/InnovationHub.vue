<!-- 创新全景：三屏纵向叙事。页面只呈现后端 /innovation/overview 的结构化事实，
     不计算任何分数、人数、比例；缺失值显示空态，接口失败显示错误态，绝不用示例数字兜底。 -->
<template>
  <div class="page bento-page innovation-hub" :class="{ 'is-ready': ready }">
    <header class="hub-top">
      <div class="hub-title">
        <p class="eyebrow">INNOVATION PANORAMA · 创新全景</p>
        <h1>看得见的证据链，核得实的数据</h1>
        <p class="hub-lede">所有数值来自在线引擎与数据源，逐条标注来源、口径与时间。</p>
      </div>
      <div class="hub-meta">
        <span class="meta-chip">{{ roleLabel }}</span>
        <span class="meta-chip">范围：{{ scopeText }}</span>
        <span class="meta-chip">数据时间：{{ asOfText }}</span>
        <button type="button" class="quiet-btn" @click="load">刷新</button>
      </div>
    </header>

    <!-- 接口未就绪：只显示错误与重试，不渲染任何数字 -->
    <div v-if="error" class="state-panel is-error" role="alert">
      <h2>{{ error }}</h2>
      <p>本页不使用示例数字、历史快照或模拟场次代替真实结果，请稍后重试。</p>
      <button type="button" class="primary-btn" @click="load">重试</button>
    </div>
    <div v-else-if="loading" class="state-panel" role="status">
      <span class="loading-dot" aria-hidden="true" />
      正在读取创新全景数据…
    </div>

    <template v-else>
      <!-- ================= 屏 1：从推荐到结果 ================= -->
      <section class="screen" aria-labelledby="innov-result-title">
        <div class="hero">
          <div class="hero-copy">
            <p class="screen-kicker">01 / 从推荐到结果</p>
            <h2 id="innov-result-title">从「推荐了多少岗位」，转向「是否真正拿到机会」</h2>
            <p>
              模拟面试场次、岗位就绪度与岗位库记录都是可回溯的事实；真实面试机会尚未采集，
              不用模拟场次替代。
            </p>
          </div>
          <ul class="hero-rail" aria-label="本页叙事主线">
            <li>证据链</li>
            <li>数据溯源</li>
            <li>师生闭环</li>
          </ul>
        </div>

        <div class="kpi-grid">
          <article
            v-for="(kpi, index) in kpis"
            :key="kpi.key || kpi.label || index"
            class="kpi-card reveal"
            :class="{ 'is-absent': !isAvailable(kpi) }"
            :style="{ '--i': index }"
          >
            <div class="kpi-head">
              <span class="kpi-label">{{ kpi.label || '未命名指标' }}</span>
              <span class="status-chip" :class="isAvailable(kpi) ? 'is-on' : 'is-off'">
                {{ isAvailable(kpi) ? '已采集' : '未采集' }}
              </span>
            </div>
            <p class="kpi-value" :class="{ 'is-absent': !isAvailable(kpi) }">
              <template v-if="isAvailable(kpi)">
                {{ stringOf(kpi.value) }}<small v-if="kpi.unit">{{ kpi.unit }}</small>
              </template>
              <template v-else>{{ absenceText(kpi) }}</template>
            </p>
            <p v-if="kpi.note" class="kpi-note">{{ kpi.note }}</p>
            <div class="kpi-foot">
              <span>来源：{{ kpi.source_table || '未记录' }}</span>
              <span>引擎：{{ kpi.engine_version || '未记录' }}</span>
              <span>截至：{{ kpi.as_of ? dayOrAbsent(kpi.as_of) : '未记录' }}</span>
            </div>
          </article>
        </div>
        <p v-if="!kpis.length" class="empty-inline">暂无事实卡记录</p>
      </section>

      <!-- ================= 屏 2：测—推—练—补 ================= -->
      <section class="screen" aria-labelledby="innov-loop-title">
        <div class="screen-head">
          <div>
            <p class="screen-kicker">02 / 测—推—练—补</p>
            <h2 id="innov-loop-title">学业如何成为岗位证据，差距如何回到下一步训练</h2>
          </div>
          <p class="screen-note">四步摘要逐条来自引擎结构化结果，并标注来源表。</p>
        </div>

        <ol class="step-grid">
          <li
            v-for="(step, index) in steps"
            :key="step.key || step.label || index"
            class="step-card reveal"
            :class="{ 'is-absent': !step.available || !step.summary }"
            :style="{ '--i': index, '--step-accent': stepAccents[index % stepAccents.length] }"
          >
            <span class="step-index" aria-hidden="true">0{{ index + 1 }}</span>
            <div class="step-body">
              <h3>{{ step.label || '未命名步骤' }}</h3>
              <p>{{ step.available && step.summary ? step.summary : '暂无记录' }}</p>
              <p class="step-source">来源：{{ step.source_table || '未记录' }}</p>
            </div>
          </li>
        </ol>
        <p v-if="!steps.length" class="empty-inline">暂无闭环步骤记录</p>

        <!-- 本人实例：默认收起；学生本人可见，教师端不展示个人证据链 -->
        <details v-if="!isTeacher" class="instance">
          <summary>展开本人实例：岗位技能 — 课程成绩 — 简历证据</summary>
          <div v-if="instance" class="instance-body">
            <div class="instance-head">
              <span>岗位：{{ instance.job_title || '未记录' }}</span>
              <span>引擎匹配分：{{ numberOrAbsent(instance.final_score) }}</span>
              <span class="instance-caveat">匹配分是匹配度，不是录用概率</span>
            </div>
            <div class="instance-cols">
              <div class="instance-col">
                <h4>命中证据</h4>
                <ul v-if="itemTexts(instance.hit_items).length" class="evidence-list">
                  <li v-for="(text, i) in itemTexts(instance.hit_items)" :key="i">{{ text }}</li>
                </ul>
                <p v-else class="empty-inline">暂无命中记录</p>
              </div>
              <div class="instance-col">
                <h4>缺口</h4>
                <ul v-if="itemTexts(instance.gap_items).length" class="evidence-list">
                  <li v-for="(text, i) in itemTexts(instance.gap_items)" :key="i">{{ text }}</li>
                </ul>
                <p v-else class="empty-inline">暂无缺口记录</p>
              </div>
              <div class="instance-col">
                <h4>课程证据与分位</h4>
                <div v-if="asArray(instance.evidence).length" class="table-wrap">
                  <table class="compact-table">
                    <caption>引擎返回的课程成绩与分位</caption>
                    <thead>
                      <tr><th scope="col">课程</th><th scope="col">成绩</th><th scope="col">分位</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="(ev, i) in asArray(instance.evidence)" :key="i">
                        <td>{{ ev?.course || '未记录课程' }}</td>
                        <td>{{ numberOrAbsent(ev?.score) }}</td>
                        <td>{{ numberOrAbsent(ev?.percentile) }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p v-else class="empty-inline">未找到课程映射</p>
              </div>
            </div>
          </div>
          <p v-else class="empty-inline">暂无本人实例数据</p>
        </details>
        <p v-else class="privacy-note">
          教师端仅展示任教范围内的聚合步骤，不展示学生姓名、简历原文或面试原文。
        </p>
      </section>

      <!-- ================= 屏 3：可信事实与区域产业 ================= -->
      <section class="screen" aria-labelledby="innov-trust-title">
        <div class="screen-head">
          <div>
            <p class="screen-kicker">03 / 可信事实与区域产业</p>
            <h2 id="innov-trust-title">每一个数字都能回到出处</h2>
          </div>
          <p class="screen-note">岗位供给与浏览/收藏兴趣分母不同，分两张图呈现，不合并为成功率。</p>
        </div>

        <!-- 全国岗位供给分布：省级着色 + 城市气泡。边界取本地 /geo/china.json，不访问外网；
             着色只读后端 province_counts，缺失 / 0 的省不着色、不补 0。 -->
        <article class="chart-card is-map">
          <div class="chart-head">
            <div class="chart-title">
              <h3>全国岗位供给分布</h3>
              <p class="chart-sub">
                在库岗位条数快照 · 数据时间 {{ asOfText }}
                <template v-if="unmappedCities > 0"> · 另有 {{ unmappedCities }} 个城市未纳入省级聚合</template>
              </p>
            </div>
          </div>
          <template v-if="mapReady">
            <div class="chart-area">
              <div
                ref="mapRef"
                class="chart-canvas is-map"
                role="img"
                :aria-label="mapAria"
              />
              <div v-if="provinceValues.length" class="heat-legend is-map">
                <span>{{ provinceMin }}</span>
                <span class="heat-ramp" aria-hidden="true" />
                <span>{{ provinceMax }}</span>
                <span class="heat-unit">在库岗位条数</span>
              </div>
            </div>
          </template>
          <p v-else class="empty-inline is-map">{{ mapEmptyText }}</p>
        </article>

        <div class="trust-grid">
          <!-- 供给：全宽呈现，热力矩阵需要横向空间才看得清 91 格 -->
          <article class="chart-card is-wide">
            <div class="chart-head">
              <div class="chart-title">
                <h3>城市 × 行业岗位供给</h3>
                <p class="chart-sub">
                  {{ supplyMode === 'heatmap' ? '单色阶热力矩阵（有效单元 ≥ 20）' : '水平条形（有效单元 < 20）' }}
                  · 数据时间 {{ asOfText }}
                </p>
              </div>
              <button
                type="button"
                class="view-toggle"
                :aria-pressed="tableViews.supply"
                @click="toggleView('supply')"
              >{{ tableViews.supply ? '看图表' : '看表格' }}</button>
            </div>
            <template v-if="supplyCells.length">
              <div v-show="!tableViews.supply" class="chart-area">
                <div
                  ref="supplyRef"
                  class="chart-canvas is-tall"
                  role="img"
                  :aria-label="supplyAria"
                  tabindex="0"
                />
                <div v-if="supplyMode === 'heatmap'" class="heat-legend">
                  <span>{{ heatMin }}</span>
                  <span class="heat-ramp" aria-hidden="true" />
                  <span>{{ heatMax }}</span>
                  <span class="heat-unit">记录数</span>
                </div>
              </div>
              <div v-show="tableViews.supply" class="table-wrap">
                <table class="compact-table">
                  <caption>岗位供给读数（可排序；口径：岗位库记录数）</caption>
                  <thead>
                    <tr>
                      <th scope="col"><button type="button" @click="toggleSort('supply', 'city')">城市 {{ sortGlyph('supply', 'city') }}</button></th>
                      <th scope="col"><button type="button" @click="toggleSort('supply', 'industry')">行业 {{ sortGlyph('supply', 'industry') }}</button></th>
                      <th scope="col"><button type="button" @click="toggleSort('supply', 'count')">岗位库记录 {{ sortGlyph('supply', 'count') }}</button></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, i) in sortedRows('supply', supplyCells)" :key="`${row.city}-${row.industry}-${i}`">
                      <td>{{ row.city }}</td><td>{{ row.industry }}</td><td>{{ row.count }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
            <p v-else class="empty-inline">暂无岗位供给记录</p>
          </article>

          <article class="source-panel">
            <div class="panel-head">
              <h3>事实来源</h3>
              <p class="chart-sub">核实时间与抓取时间分别标注，不混用</p>
            </div>
            <div v-if="sources.length" class="source-list">
              <article
                v-for="(source, index) in sources"
                :key="source.name || index"
                class="source-card reveal"
                :class="source.kind === 'verified' ? 'is-verified' : source.kind === 'fetched' ? 'is-fetched' : null"
                :style="{ '--i': index }"
              >
                <div class="source-top">
                  <h4>{{ source.name || '未命名来源' }}</h4>
                  <span class="source-badge">{{ kindText(source.kind) }}</span>
                </div>
                <p class="source-meta">
                  <span>记录数：{{ numberOrAbsent(source.records) }}</span>
                  <span>{{ datePrefix(source.kind) }}：{{ dayOrAbsent(source.latest_verified_at) }}</span>
                </p>
                <a v-if="source.link" :href="source.link" target="_blank" rel="noopener noreferrer">
                  查看原文 <span aria-hidden="true">↗</span>
                </a>
                <span v-else class="source-nolink">未提供链接</span>
              </article>
            </div>
            <p v-else class="empty-inline">暂无来源记录</p>
          </article>

          <!-- 兴趣：独立分母，单独一张图 -->
          <article class="chart-card is-interest">
            <div class="chart-head">
              <div class="chart-title">
                <h3>浏览 / 收藏兴趣排行</h3>
                <p class="chart-sub">口径：岗位浏览与收藏行为 · 数据时间 {{ asOfText }}</p>
              </div>
              <button
                type="button"
                class="view-toggle"
                :aria-pressed="tableViews.interest"
                @click="toggleView('interest')"
              >{{ tableViews.interest ? '看图表' : '看表格' }}</button>
            </div>
            <template v-if="interestRows.length">
              <div v-show="!tableViews.interest" class="chart-area">
                <div
                  ref="interestRef"
                  class="chart-canvas"
                  role="img"
                  :aria-label="interestAria"
                  tabindex="0"
                />
              </div>
              <div v-show="tableViews.interest" class="table-wrap">
                <table class="compact-table">
                  <caption>兴趣读数（可排序；浏览/收藏次数，不代表就业结果）</caption>
                  <thead>
                    <tr>
                      <th scope="col"><button type="button" @click="toggleSort('interest', 'job')">岗位 {{ sortGlyph('interest', 'job') }}</button></th>
                      <th scope="col"><button type="button" @click="toggleSort('interest', 'views')">次数 {{ sortGlyph('interest', 'views') }}</button></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, i) in sortedRows('interest', interestRows)" :key="`${row.job}-${i}`">
                      <td>{{ row.job }}</td><td>{{ row.views }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
            <p v-else class="empty-inline">暂无浏览 / 收藏兴趣记录</p>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { getInnovationOverview } from '../api/innovation'
import echarts from '../utils/echarts'

const data = ref(null)
const loading = ref(true)
const error = ref('')

const supplyRef = ref(null)
const interestRef = ref(null)
const charts = {}
const tableViews = reactive({ supply: false, interest: false })
const sortState = reactive({
  supply: { key: 'count', dir: 'desc' },
  interest: { key: 'views', dir: 'desc' }
})
// 系统「减少动态效果」可能在页面打开后被切换：保留 MediaQueryList 并监听 change，
// 否则已初始化的 ECharts 仍带着首次读取的 animation 快照跑动画。
const motionQuery = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  ? window.matchMedia('(prefers-reduced-motion: reduce)')
  : null
let reduceMotion = !!motionQuery?.matches

function onMotionChange(event) {
  reduceMotion = !!event.matches
  renderAll()
}

// 测—推—练—补四步共用单一靛蓝色阶（与供给热力矩阵同色系），闭环分段但不引入第二主色
const stepAccents = ['#123a8f', '#1951c3', '#3f70d4', '#6c92e9']

let revealObserver = null
let revealFallback = null

function setupReveal() {
  clearTimeout(revealFallback)
  if (reduceMotion || !('IntersectionObserver' in window)) {
    document.querySelectorAll('.innovation-hub .reveal').forEach((el) => el.classList.add('is-in'))
    return
  }
  revealObserver?.disconnect()
  revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-in')
        revealObserver?.unobserve(entry.target)
      }
    })
  }, { threshold: 0.12, rootMargin: '0px 0px -24px 0px' })
  const targets = document.querySelectorAll('.innovation-hub .reveal')
  targets.forEach((el) => revealObserver.observe(el))
  // 兜底：打印、无头截图或用户长时间不滚动时，3 秒后全部显示，页面绝不停留在空白
  revealFallback = setTimeout(() => {
    targets.forEach((el) => el.classList.add('is-in'))
    revealObserver?.disconnect()
  }, 3000)
}

// ---------- 纯展示辅助：不计算业务数值，只判定缺失与格式化后端原值 ----------
function asArray(value) {
  return Array.isArray(value) ? value : []
}

function stringOf(value) {
  return typeof value === 'number' || typeof value === 'string' ? String(value) : ''
}

function numberOrAbsent(value) {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '暂无记录'
}

function dayOrAbsent(value) {
  if (typeof value !== 'string' || !value) return '日期未记录'
  return /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : value
}

function isAvailable(kpi) {
  return kpi?.available === true
    && kpi.value !== null && kpi.value !== undefined && kpi.value !== ''
}

function absenceText(kpi) {
  return kpi?.key === 'real_interview' ? '尚未采集' : '暂无记录'
}

function datePrefix(kind) {
  if (kind === 'verified') return '核实于'
  if (kind === 'fetched') return '最近抓取'
  return '记录时间'
}

function kindText(kind) {
  if (kind === 'verified') return '已核实'
  if (kind === 'fetched') return '抓取记录'
  return '类型未标注'
}

function itemTexts(items) {
  return asArray(items).map((item) => {
    if (typeof item === 'string') return item
    if (!item || typeof item !== 'object') return '记录项'
    return item.name || item.label || item.skill || item.text || item.title || '记录项'
  })
}

// ---------- 只读视图模型 ----------
const screens = computed(() => data.value?.screens || {})
const kpis = computed(() => asArray(screens.value.result?.kpis))
const steps = computed(() => asArray(screens.value.loop?.steps))
const instance = computed(() => screens.value.loop?.instance || null)
const sources = computed(() => asArray(screens.value.trust?.sources))
const supply = computed(() => screens.value.trust?.supply || null)
const interest = computed(() => asArray(screens.value.trust?.interest))
const ready = computed(() => !!data.value && !loading.value && !error.value)

const role = computed(() => data.value?.role || '')
const isTeacher = computed(() => role.value === 'teacher')
const roleLabel = computed(() => {
  if (role.value === 'teacher') return '教师视图'
  if (role.value === 'student') return '学生视图'
  return '角色未标注'
})
const asOfText = computed(() => data.value?.as_of || '时间未记录')
const scopeText = computed(() => {
  const scope = data.value?.scope
  if (!scope) return '范围未标注'
  const klass = scope.class_id === null || scope.class_id === undefined
    ? '全部班级' : String(scope.class_id)
  return `租户 ${numberOrAbsent(scope.tenant_id)} · 班级 ${klass}`
})

// 有效单元：城市、行业、计数都来自后端，计数为 0 / 缺失的不画进坐标轴
const supplyCells = computed(() => asArray(supply.value?.cells).filter(
  (cell) => cell && cell.city && cell.industry
    && typeof cell.count === 'number' && Number.isFinite(cell.count) && cell.count > 0
))
const supplyMode = computed(() => (supplyCells.value.length >= 20 ? 'heatmap' : 'bar'))
const supplyCities = computed(() => uniqueStrings([
  ...asArray(supply.value?.cities), ...supplyCells.value.map((cell) => cell.city)
]))
const supplyIndustries = computed(() => uniqueStrings([
  ...asArray(supply.value?.industries), ...supplyCells.value.map((cell) => cell.industry)
]))
const interestRows = computed(() => interest.value.filter(
  (row) => row && row.job && typeof row.views === 'number' && Number.isFinite(row.views)
))

// 城市 → 在库岗位数（后端 supply.city_counts，键是 supply.cities 的子集）。
// 非对象一律兜底空对象：缺读数只省略数字，绝不补 0。
const cityCounts = computed(() => {
  const raw = supply.value?.city_counts
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}
})

// ---------- 全国岗位供给分布（地图） ----------
// 城市坐标是唯一允许的来源：这里没有的城市一律跳过并计数，绝不按省心 / 质心推算。
const CITY_COORDS = Object.freeze({
  北京: [116.41, 39.90], 上海: [121.47, 31.23], 广州: [113.26, 23.13], 深圳: [114.06, 22.55],
  杭州: [120.15, 30.28], 南京: [118.80, 32.06], 武汉: [114.31, 30.60], 成都: [104.07, 30.67],
  苏州: [120.62, 31.32], 宁波: [121.55, 29.87], 东莞: [113.75, 23.02], 合肥: [117.28, 31.86],
  郑州: [113.62, 34.75], 重庆: [106.55, 29.56], 西安: [108.94, 34.34], 长沙: [112.94, 28.23],
  天津: [117.20, 39.13], 昆明: [102.83, 24.88], 佛山: [113.12, 23.02], 无锡: [120.31, 31.49],
  石家庄: [114.51, 38.04], 沈阳: [123.43, 41.80], 大连: [121.62, 38.91], 南宁: [108.37, 22.82],
  贵阳: [106.63, 26.65], 嘉兴: [120.76, 30.75], 南通: [120.89, 31.98], 惠州: [114.42, 23.11],
  珠海: [113.58, 22.27], 常州: [119.97, 31.81]
})
const MAP_NAME = 'qh-china'
const MAP_SOURCE = '/geo/china.json'
const MAP_BUBBLE_MIN = 6
const MAP_BUBBLE_MAX = 20

const mapRef = ref(null)
const mapStatus = ref('loading')   // loading | ready | empty | failed
const mapSkipped = ref(0)          // supply.cities 里缺绘图坐标（或缺读数）而被跳过的城市数

// 省 → 在库岗位条数。只收有限正数：缺失 / 0 / 脏值都不进着色，也不补 0。
const provinceValues = computed(() => {
  const raw = supply.value?.province_counts
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return []
  return Object.keys(raw)
    .map((name) => ({ name, value: raw[name] }))
    .filter((item) => item.name && typeof item.value === 'number' && Number.isFinite(item.value) && item.value > 0)
})
const provinceMax = computed(() => Math.max(0, ...provinceValues.value.map((item) => item.value)))
const provinceMin = computed(() => (provinceValues.value.length ? Math.min(...provinceValues.value.map((item) => item.value)) : 0))

const unmappedCities = computed(() => {
  const raw = supply.value?.unmapped_cities
  return typeof raw === 'number' && Number.isFinite(raw) && raw > 0 ? raw : 0
})

// 城市气泡：名字取 supply.cities，数值取 supply.city_counts，坐标只认 CITY_COORDS。
// 缺坐标 / 缺读数 / 非正数都跳过；跳过数单独回报，不用别处的数字顶替。
const mapBubbles = computed(() => {
  const points = []
  let skipped = 0
  for (const city of uniqueStrings(asArray(supply.value?.cities))) {
    const coords = CITY_COORDS[city]
    const count = cityCounts.value?.[city]
    if (!coords || typeof count !== 'number' || !Number.isFinite(count) || count <= 0) {
      skipped += 1
      continue
    }
    points.push({ name: city, value: [coords[0], coords[1], count] })
  }
  return { points, skipped }
})

// 容器是否挂载：有省级读数且边界没加载失败即可，不能依赖 mapStatus==='ready'
// （ready 要等容器画完才成立，拿它当 v-if 条件会让容器永远不出现）
const mapReady = computed(() => mapStatus.value !== 'failed' && provinceValues.value.length > 0)
const mapEmptyText = computed(() => (
  mapStatus.value === 'failed'
    ? '地图边界数据加载失败，暂无法绘制全国分布'
    : '暂无省级岗位供给记录'
))
const mapAria = computed(() => {
  const skipped = mapBubbles.value.skipped
  const tail = skipped > 0 ? `，另有 ${skipped} 个城市缺少绘图坐标未标注` : ''
  return `全国岗位供给分布地图，省级颜色深浅表示在库岗位条数快照，共 ${provinceValues.value.length} 个省级行政区有记录，`
    + `最大 ${provinceMax.value}、最小 ${provinceMin.value} 条，圆点为主要城市在库岗位条数${tail}`
})

const heatMin = computed(() => Math.min(...supplyCells.value.map((cell) => cell.count)))
const heatMax = computed(() => Math.max(...supplyCells.value.map((cell) => cell.count)))
const supplyAria = computed(() => `岗位供给${supplyMode.value === 'heatmap' ? '热力矩阵' : '水平条形图'}，取值来自后端岗位库记录，城市标签后为在库岗位数，数据时间 ${asOfText.value}`)
const interestAria = computed(() => `浏览与收藏兴趣水平条形图，取值来自后端行为日志，数据时间 ${asOfText.value}`)

function uniqueStrings(values) {
  return [...new Set(values.filter((v) => typeof v === 'string' && v))]
}

// ---------- 表格视图与排序 ----------
function toggleView(key) {
  tableViews[key] = !tableViews[key]
  if (!tableViews[key]) nextTick(() => charts[key]?.resize())
}

function toggleSort(key, column) {
  const state = sortState[key]
  if (state.key === column) {
    state.dir = state.dir === 'desc' ? 'asc' : 'desc'
  } else {
    state.key = column
    state.dir = 'desc'
  }
}

function sortGlyph(key, column) {
  const state = sortState[key]
  if (state.key !== column) return '↕'
  return state.dir === 'asc' ? '↑' : '↓'
}

function sortedRows(key, rows) {
  const { key: column, dir } = sortState[key]
  const sign = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const left = a[column]
    const right = b[column]
    if (typeof left === 'number' && typeof right === 'number') return (left - right) * sign
    return String(left ?? '').localeCompare(String(right ?? ''), 'zh-CN') * sign
  })
}

// ---------- ECharts：按需注册的类型见 utils/echarts.js，页面只 setOption ----------
const INDIGO_RAMP = ['#cddaff', '#9db8f5', '#6c92e9', '#3f70d4', '#1951c3']

function indigoRamp(ratio) {
  const index = Math.min(INDIGO_RAMP.length - 1, Math.max(0, Math.round(ratio * (INDIGO_RAMP.length - 1))))
  return INDIGO_RAMP[index]
}

function chartOf(key, el) {
  if (!el) return null
  if (!charts[key]) charts[key] = echarts.init(el)
  return charts[key]
}

function renderHeatmap() {
  const chart = chartOf('supply', supplyRef.value)
  if (!chart) return
  const cities = supplyCities.value
  const industries = supplyIndustries.value
  const points = supplyCells.value.map((cell) => [
    Math.max(0, industries.indexOf(cell.industry)),
    Math.max(0, cities.indexOf(cell.city)),
    cell.count
  ])
  const counts = points.map((point) => point[2])
  const min = Math.min(...counts)
  const max = Math.max(...counts)
  chart.setOption({
    animation: !reduceMotion,
    animationDuration: 220,
    grid: { left: 112, right: 20, top: 14, bottom: 28 },
    tooltip: {
      position: 'top',
      formatter: (p) => `${cities[p.value[1]]} · ${industries[p.value[0]]}<br/>岗位库记录：${p.value[2]}`
    },
    xAxis: {
      type: 'category', data: industries,
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { show: true, lineStyle: { color: '#eef0f5', width: 1 } },
      axisLabel: { color: '#5f6672', fontSize: 11, interval: 0, rotate: industries.length > 6 ? 30 : 0 }
    },
    yAxis: {
      type: 'category', data: cities,
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { show: true, lineStyle: { color: '#eef0f5', width: 1 } },
      axisLabel: {
        color: '#5f6672', fontSize: 11,
        // 有后端读数才追在库岗位数；没有就只显示城市名，不补 0、不显示 null
        formatter: (name) => {
          const count = cityCounts.value?.[name]
          return typeof count === 'number' && Number.isFinite(count) ? `${name} ${count}` : name
        }
      }
    },
    // 图例用下方 HTML 色阶呈现：ECharts 内置 visualMap 在窄容器里会竖起来压住分类轴标签
    visualMap: {
      show: false, min, max, calculable: false,
      inRange: { color: INDIGO_RAMP }
    },
    series: [{
      type: 'heatmap', data: points,
      label: {
        show: true, color: '#fff', fontSize: 11,
        textBorderColor: 'rgba(11, 18, 32, 0.55)', textBorderWidth: 2
      },
      itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 2 }
    }]
  }, true)
}

function renderBars(key, el, rows, labelOf, valueOf, seriesName) {
  const chart = chartOf(key, el)
  if (!chart) return
  // 倒序让大值在顶部，柱体 24px 内、末端 4px 圆角、柱间 2px 缝
  const display = [...rows].reverse()
  const last = Math.max(1, display.length - 1)
  chart.setOption({
    animation: !reduceMotion,
    animationDuration: 220,
    animationDurationUpdate: 220,
    grid: { left: 8, right: 58, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'item',
      formatter: (p) => `${p.name}<br/>${seriesName}：${p.value}`
    },
    xAxis: {
      type: 'value', min: 0,
      splitLine: { lineStyle: { color: '#eef0f5', width: 1 } },
      axisLabel: { color: '#5f6672', fontSize: 11 }
    },
    yAxis: {
      type: 'category', data: display.map(labelOf),
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: '#5f6672', fontSize: 11, width: 132, overflow: 'truncate' }
    },
    series: [{
      name: seriesName, type: 'bar',
      data: display.map(valueOf),
      barMaxWidth: 24, barCategoryGap: 2,
      itemStyle: {
        borderRadius: [0, 4, 4, 0],
        color: (p) => indigoRamp(p.dataIndex / last)
      },
      label: { show: true, position: 'right', color: '#16181d', fontSize: 11 }
    }]
  }, true)
}

// ---------- 全国地图：省级着色 + 城市气泡 ----------
let mapRegistering = null   // 并发调用共用同一次 registerMap，不重复 fetch
let mapRenderToken = 0      // 每次渲染自增：异步取边界期间若被更新的渲染盖过，旧的那次作废

async function ensureMapRegistered() {
  if (mapRegistering) return mapRegistering
  mapRegistering = (async () => {
    if (!echarts.getMap(MAP_NAME)) {
      // 只取本地 /geo/china.json：不访问外网，也不在失败时退到任何远程 CDN
      const response = await fetch(MAP_SOURCE)
      if (!response.ok) throw new Error(`geo http ${response.status}`)
      const geojson = await response.json()
      if (!geojson || !Array.isArray(geojson.features) || !geojson.features.length) {
        throw new Error('geo features missing')
      }
      echarts.registerMap(MAP_NAME, geojson)
    }
    return true
  })()
  try {
    await mapRegistering
  } catch (err) {
    mapRegistering = null   // 失败不缓存：下次刷新允许重试
    throw err
  }
}

function bubbleSize(count, max) {
  // sqrt 缩放到 6~20：面积与数值成正比，避免大城市气泡按半径平方级放大压住邻省
  const ratio = max > 0 ? Math.sqrt(count / max) : 0
  return MAP_BUBBLE_MIN + (MAP_BUBBLE_MAX - MAP_BUBBLE_MIN) * ratio
}

// 省 → 5 档靛蓝色阶（与热力图 INDIGO_RAMP 同一组色）。档位 = 数值 / 最大值映射到 0~4 后四舍五入；
// 只有后端给了正数读数的省才会进来，缺失 / 0 的省不生成 region，保持 geo 的底色。
function provinceColor(value, max) {
  if (max <= 0) return INDIGO_RAMP[0]
  const ratio = Math.min(1, Math.max(0, value / max))
  const index = Math.round(ratio * (INDIGO_RAMP.length - 1))
  return INDIGO_RAMP[index]
}

// 常显标签只给在库岗位数排名前 3 的城市，按名次排好序返回（offset 要按名次交错分配）；
// 同数按城市名排序，保证同输入同结果
function topBubbleNames(points, limit = 3) {
  return [...points]
    .sort((a, b) => (b.value[2] - a.value[2]) || a.name.localeCompare(b.name, 'zh-CN'))
    .slice(0, limit)
    .map((point) => point.name)
}

// 前三名坐标极近（南京 / 杭州 / 上海），标签按名次往三个方向错开，避免叠字
const TOP_LABEL_OFFSETS = [[10, -10], [-12, -6], [6, 14]]

async function renderMap() {
  // 入口只看「有省级读数 + 容器已挂载」；mapReady 要等 setOption 成功后才成立，不能在这里当门槛
  const token = ++mapRenderToken
  if (!provinceValues.value.length || !mapRef.value) return
  try {
    await ensureMapRegistered()
  } catch (err) {
    if (token === mapRenderToken) mapStatus.value = 'failed'
    return
  }
  // await 期间数据可能已刷新或组件已卸载：过期的那一次不往容器上画
  if (token !== mapRenderToken || !mapRef.value) return
  const chart = chartOf('map', mapRef.value)
  if (!chart) return
  const { points, skipped } = mapBubbles.value
  mapSkipped.value = skipped
  const max = provinceMax.value || 1
  const labeled = topBubbleNames(points)
  chart.setOption({
    animation: !reduceMotion,
    animationDuration: 220,
    tooltip: {
      trigger: 'item',
      backgroundColor: '#fff',
      borderColor: '#e4e7ee',
      textStyle: { color: '#16181d', fontSize: 12 },
      formatter: (p) => {
        if (p.seriesType === 'scatter') return `${p.name}<br/>在库岗位：${p.value[2]} 条`
        // 只报后端真实读数；没有读数的省如实说「无记录」，不显示 0
        const hit = provinceValues.value.find((item) => item.name === p.name)
        return hit ? `${p.name}<br/>在库岗位：${hit.value} 条` : `${p.name}<br/>在库岗位：无记录`
      }
    },
    // 布局只由 geo 一处控制：不再并存 map 系列与 geo 组件（两套布局会把图挤偏），
    // 省级着色走 geo.regions，按 GeoJSON properties.name 逐省匹配 areaColor。
    geo: {
      map: MAP_NAME,
      roam: false,
      layoutCenter: ['50%', '50%'],
      layoutSize: '95%',
      itemStyle: { areaColor: '#f2f4f8', borderColor: '#cbd5e1' },
      // 省名不在图上常显（东部密集区会叠成一团），只在 tooltip 里给
      label: { show: false },
      emphasis: { label: { show: false }, itemStyle: { areaColor: '#9db8f5' } },
      select: { disabled: true },
      regions: provinceValues.value.map((item) => ({
        name: item.name,
        itemStyle: { areaColor: provinceColor(item.value, max) }
      }))
    },
    series: [
      {
        name: '城市在库岗位',
        type: 'scatter',
        coordinateSystem: 'geo',
        data: points,
        symbolSize: (val) => bubbleSize(val[2], max),
        itemStyle: { color: 'rgba(25, 81, 195, 0.75)', borderColor: '#fff', borderWidth: 1 },
        // 常显标签只给排名前 3 的城市，其余关闭、只靠 tooltip
        label: {
          show: true, fontSize: 11, color: '#16181d',
          // 第 1/2/3 名分别往右上、左上、右下错位；非前三名文案为空，offset 无可见影响
          offset: (p) => TOP_LABEL_OFFSETS[Math.max(0, labeled.indexOf(p.name))] || [0, 0],
          formatter: (p) => (labeled.includes(p.name) ? `${p.name} ${p.value[2]}` : '')
        },
        labelLayout: { hideOverlap: true },
        emphasis: { scale: 1.2 }
      }
    ]
  }, true)
  chart.resize()
  mapStatus.value = 'ready'
}

function renderAll() {
  if (supplyCells.value.length) {
    if (supplyMode.value === 'heatmap') {
      renderHeatmap()
    } else {
      const rows = [...supplyCells.value].sort((a, b) => b.count - a.count).slice(0, 15)
      renderBars('supply', supplyRef.value, rows,
        (row) => `${row.city} · ${row.industry}`, (row) => row.count, '岗位库记录')
    }
  }
  if (interestRows.value.length) {
    const rows = [...interestRows.value].sort((a, b) => b.views - a.views).slice(0, 15)
    renderBars('interest', interestRef.value, rows,
      (row) => row.job, (row) => row.views, '浏览/收藏次数')
  }
  // 地图：无省级读数即空态；有读数才去取边界并绘制（内部异步，失败自行降级为空态文案）
  mapRenderToken += 1   // 作废上一次还没画完的渲染
  if (!provinceValues.value.length) {
    mapStatus.value = 'empty'
    return
  }
  // 上一轮可能停在 failed：本轮有读数就重新从 loading 走一遍，失败文案不会赖着不走
  mapStatus.value = 'loading'
  // 容器受 v-if 控制，要等这一轮 DOM 更新挂上 ref 才能初始化 ECharts
  nextTick(() => renderMap())
}

function onResize() {
  Object.values(charts).forEach((chart) => chart?.resize())
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const response = await getInnovationOverview()
    data.value = response?.data || null
  } catch (err) {
    data.value = null
    const status = err?.response?.status
    error.value = `接口未就绪（${status || '网络异常'}）`
  } finally {
    loading.value = false
  }
  await nextTick()
  if (!error.value) renderAll()
  setupReveal()
}

onMounted(async () => {
  await load()
  window.addEventListener('resize', onResize)
  motionQuery?.addEventListener?.('change', onMotionChange)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  motionQuery?.removeEventListener?.('change', onMotionChange)
  clearTimeout(revealFallback)
  revealObserver?.disconnect()
  revealObserver = null
  Object.values(charts).forEach((chart) => chart?.dispose())
  Object.keys(charts).forEach((key) => delete charts[key])
})
</script>

<style scoped>
.innovation-hub {
  --qh-innovation-canvas: var(--cf-bg, #f7f8fa);
  --qh-innovation-surface: var(--cf-surface-solid, #ffffff);
  --qh-innovation-ink: var(--cf-ink, #16181d);
  --qh-innovation-muted: var(--cf-mid, #5f6672);
  --qh-innovation-border: var(--cf-line, #e4e7ee);
  --qh-innovation-primary: var(--qh-primary, #1951c3);
  --qh-innovation-primary-soft: var(--qh-primary-soft, #e9efff);
  --qh-innovation-positive: var(--cf-teal, #0f9d8a);
  --qh-innovation-warning: var(--cf-warning, #c98900);
  --qh-innovation-danger: var(--cf-danger, #d83b32);
  --qh-innovation-radius-card: var(--bento-radius, 16px);
  --qh-innovation-gap: 20px;
  --qh-innovation-display-bg: #0b1220;
  --qh-innovation-display-surface: #111827;
  --qh-innovation-display-ink: #f8fafc;
  --qh-innovation-display-muted: #cbd5e1;
  --qh-innovation-ease: cubic-bezier(0.25, 0.1, 0.25, 1);

  min-width: 0;
  color: var(--qh-innovation-ink);
}

.innovation-hub :focus-visible {
  outline: 2px solid var(--qh-innovation-primary);
  outline-offset: 2px;
}

/* ---------- 页头 ---------- */
.hub-top {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 22px;
}

.hub-title { min-width: 0; }
.eyebrow, .screen-kicker {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin: 0 0 4px;
  color: var(--qh-innovation-primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.eyebrow::before, .screen-kicker::before {
  content: '';
  width: 18px;
  height: 2px;
  border-radius: 1px;
  background: linear-gradient(90deg, var(--qh-innovation-primary), #3f70d4);
}

.hub-title h1 {
  margin: 0;
  font-size: clamp(19px, 1.8vw, 22px);
  line-height: 1.35;
  letter-spacing: -0.02em;
}

.hub-lede {
  margin: 6px 0 0;
  color: var(--qh-innovation-muted);
  font-size: 13px;
}

.hub-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.meta-chip {
  padding: 4px 10px;
  border: 1px solid var(--qh-innovation-border);
  border-radius: 999px;
  background: var(--qh-innovation-surface);
  color: var(--qh-innovation-muted);
  font-size: 12px;
}

.quiet-btn, .view-toggle, .primary-btn {
  font: inherit;
  cursor: pointer;
  border-radius: 8px;
  transition: background-color 260ms var(--qh-innovation-ease),
    border-color 260ms var(--qh-innovation-ease),
    box-shadow 260ms var(--qh-innovation-ease);
}

.quiet-btn {
  padding: 5px 12px;
  border: 1px solid var(--qh-innovation-border);
  background: var(--qh-innovation-surface);
  color: var(--qh-innovation-muted);
  font-size: 12px;
}

.quiet-btn:hover { border-color: var(--qh-innovation-primary); color: var(--qh-innovation-primary); }
.primary-btn {
  padding: 8px 18px;
  border: 1px solid var(--qh-innovation-primary);
  background: var(--qh-innovation-primary);
  color: #fff;
  font-size: 13px;
}
.primary-btn:hover { box-shadow: 0 4px 14px rgba(25, 81, 195, 0.24); }

/* ---------- 加载 / 错误 / 空态 ---------- */
.state-panel {
  min-height: 260px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 10px;
  padding: 28px;
  border: 1px solid var(--qh-innovation-border);
  border-radius: var(--qh-innovation-radius-card);
  background: var(--qh-innovation-surface);
  color: var(--qh-innovation-muted);
}

.state-panel.is-error { border-color: rgba(216, 59, 50, 0.4); }
.state-panel h2 { margin: 0; color: var(--qh-innovation-danger); font-size: 18px; }
.state-panel p { margin: 0; font-size: 13px; }
.loading-dot {
  width: 10px; height: 10px;
  border: 2px solid var(--qh-innovation-primary);
  border-right-color: transparent;
  border-radius: 50%;
  animation: qh-spin 800ms linear infinite;
}
@keyframes qh-spin { to { transform: rotate(360deg); } }

.empty-inline {
  margin: 8px 0 0;
  padding: 10px 0;
  color: var(--qh-innovation-muted);
  font-size: 13px;
}

/* ---------- 三屏通用 ---------- */
.screen { margin-bottom: 32px; }
.screen:last-child { margin-bottom: 0; }
.screen-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 16px;
}
.screen-head h2 {
  margin: 0;
  font-size: clamp(17px, 1.6vw, 21px);
  line-height: 1.45;
}
.screen-note {
  max-width: 420px;
  margin: 0;
  color: var(--qh-innovation-muted);
  font-size: 12px;
}

/* 进入动效：只做 opacity + 4px 位移，不做数字滚动；滚动到视口才触发（IO 加 is-in） */
.reveal {
  opacity: 0;
  transform: translateY(4px);
  transition: opacity 260ms var(--qh-innovation-ease),
    transform 260ms var(--qh-innovation-ease);
  transition-delay: calc(var(--i, 0) * 35ms);
}
.is-ready .reveal.is-in { opacity: 1; transform: translateY(0); }

/* ---------- 屏 1 ---------- */
.hero {
  position: relative;
  overflow: hidden;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 28px 30px;
  margin-bottom: var(--qh-innovation-gap);
  border-radius: var(--qh-innovation-radius-card);
  background:
    radial-gradient(circle at 84% 12%, rgba(25, 81, 195, 0.28), transparent 42%),
    radial-gradient(circle at 8% 120%, rgba(15, 157, 138, 0.18), transparent 46%),
    var(--qh-innovation-display-bg);
  color: var(--qh-innovation-display-ink);
}
/* 细网格纹理 + 底部渐隐收边，提升演示海报感 */
.hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(148, 163, 184, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.07) 1px, transparent 1px);
  background-size: 30px 30px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,0.9), transparent 88%);
  pointer-events: none;
}
.hero-copy { position: relative; z-index: 1; max-width: 720px; min-width: 0; }
.hero .screen-kicker { color: #9db8f5; }
.hero .screen-kicker::before { background: linear-gradient(90deg, #6c92e9, #9db8f5); }
.hero h2 { margin: 0; font-size: clamp(19px, 2vw, 25px); line-height: 1.4; }
.hero p:last-child { margin: 10px 0 0; color: var(--qh-innovation-display-muted); font-size: 13px; }
.hero-rail {
  position: relative;
  z-index: 1;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 0;
  padding: 0;
  list-style: none;
}
.hero-rail li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid rgba(157, 184, 245, 0.34);
  border-radius: 999px;
  background: rgba(79, 139, 255, 0.1);
  font-size: 12px;
  color: #cbd9f7;
}
.hero-rail li::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #6c92e9;
  box-shadow: 0 0 6px rgba(108, 146, 233, 0.9);
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--qh-innovation-gap);
}

.kpi-card, .step-card, .instance, .source-panel, .chart-card {
  min-width: 0;
  border: 1px solid var(--qh-innovation-border);
  border-radius: var(--qh-innovation-radius-card);
  background: var(--qh-innovation-surface);
}

.kpi-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 20px 18px 16px;
  overflow: hidden;
  transition: transform 260ms var(--qh-innovation-ease),
    box-shadow 260ms var(--qh-innovation-ease),
    border-color 260ms var(--qh-innovation-ease);
}
.kpi-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  background: linear-gradient(90deg, #1951c3, #4f8bff);
  opacity: 0;
  transition: opacity 260ms var(--qh-innovation-ease);
}
.kpi-card.is-absent::before { background: linear-gradient(90deg, #c98900, #e5b45a); }
.kpi-card:hover {
  transform: translateY(-3px);
  border-color: rgba(25, 81, 195, 0.38);
  box-shadow: 0 10px 28px rgba(23, 43, 90, 0.1);
}
.kpi-card:hover::before { opacity: 1; }
.kpi-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.kpi-label { font-size: 13px; color: var(--qh-innovation-muted); }
.status-chip {
  flex: none;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 11px;
  border: 1px solid var(--qh-innovation-border);
  color: var(--qh-innovation-muted);
}
.status-chip.is-on { border-color: rgba(15, 157, 138, 0.4); color: var(--qh-innovation-positive); background: rgba(15, 157, 138, 0.07); }
.status-chip.is-off { border-color: rgba(201, 137, 0, 0.4); color: var(--qh-innovation-warning); background: rgba(201, 137, 0, 0.07); }
.kpi-value {
  margin: 14px 0 6px;
  font-size: 34px;
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  background: linear-gradient(120deg, #123a8f, #1951c3 55%, #3f70d4);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.kpi-value small { margin-left: 4px; font-size: 13px; font-weight: 500; color: var(--qh-innovation-muted); -webkit-text-fill-color: var(--qh-innovation-muted); }
.kpi-value.is-absent {
  font-size: 21px;
  letter-spacing: 0;
  background: none;
  color: var(--qh-innovation-muted);
  -webkit-text-fill-color: var(--qh-innovation-muted);
}
.kpi-note { margin: 0 0 8px; font-size: 12px; color: var(--qh-innovation-muted); }
.kpi-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--qh-innovation-border);
  color: var(--qh-innovation-muted);
  font-size: 11px;
}

/* ---------- 屏 2 ---------- */
.step-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--qh-innovation-gap);
  margin: 0;
  padding: 0;
  list-style: none;
}
.step-card {
  position: relative;
  display: flex;
  gap: 12px;
  padding: 18px;
  transition: transform 260ms var(--qh-innovation-ease),
    box-shadow 260ms var(--qh-innovation-ease),
    border-color 260ms var(--qh-innovation-ease);
}
.step-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  border-radius: var(--qh-innovation-radius-card) var(--qh-innovation-radius-card) 0 0;
  background: var(--step-accent, var(--qh-innovation-primary));
  opacity: 0.85;
}
.step-card:hover {
  transform: translateY(-3px);
  border-color: color-mix(in srgb, var(--step-accent, var(--qh-innovation-primary)) 40%, var(--qh-innovation-border));
  box-shadow: 0 10px 28px rgba(23, 43, 90, 0.1);
}
/* 步骤间连接箭头：表达测→推→练→补的推进方向，闭环语义 */
.step-card:not(:last-child)::after {
  content: '→';
  position: absolute;
  top: 50%;
  right: calc(-1 * var(--qh-innovation-gap) - 10px);
  transform: translateY(-50%);
  color: #7c8698;
  font-size: 17px;
  font-weight: 600;
  z-index: 1;
}
.step-index {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--step-accent, var(--qh-innovation-primary)) 12%, transparent);
  color: var(--step-accent, var(--qh-innovation-primary));
  font-size: 15px;
  font-weight: 700;
}
.step-body { min-width: 0; }
.step-body h3 { margin: 0 0 6px; font-size: 15px; }
.step-body p { margin: 0; font-size: 13px; line-height: 1.6; }
.step-card.is-absent .step-body p { color: var(--qh-innovation-muted); }
.step-source { margin-top: 8px !important; color: var(--qh-innovation-muted); font-size: 11px !important; }

.instance { margin-top: var(--qh-innovation-gap); padding: 0 20px; background: linear-gradient(180deg, rgba(25, 81, 195, 0.03), transparent 96px); }
.instance > summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 15px 0;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--qh-innovation-primary);
  list-style: none;
}
.instance > summary::-webkit-details-marker { display: none; }
.instance > summary::before {
  content: '▸';
  font-size: 11px;
  transition: transform 260ms var(--qh-innovation-ease);
}
.instance[open] > summary::before { transform: rotate(90deg); }
.instance > summary:hover { color: #2b6ae0; }
.instance-body { padding-bottom: 18px; }
.instance-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  padding: 12px 0;
  border-top: 1px solid var(--qh-innovation-border);
  font-size: 13px;
}
.instance-caveat { color: var(--qh-innovation-warning); }
.instance-cols {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 8px;
}
.instance-col { min-width: 0; }
.instance-col h4 { margin: 0 0 8px; font-size: 13px; }
.evidence-list { margin: 0; padding-left: 18px; font-size: 12px; line-height: 1.7; }
.privacy-note {
  margin: var(--qh-innovation-gap) 0 0;
  padding: 12px 16px;
  border: 1px dashed var(--qh-innovation-border);
  border-radius: 8px;
  color: var(--qh-innovation-muted);
  font-size: 12px;
}

/* ---------- 屏 3 ---------- */
/* 全国地图：全宽独占一行，不进下面的 trust-grid（不打乱既有 grid-template-areas） */
.chart-card.is-map { margin-bottom: var(--qh-innovation-gap); }
.chart-canvas.is-map { height: 420px; }
/* 复刻 .heat-legend：同一色阶、同一字号，只把左内边距归零（地图没有 y 轴标签需要对齐） */
.heat-legend.is-map { justify-content: center; padding-left: 0; }
.empty-inline.is-map { min-height: 420px; display: flex; align-items: center; justify-content: center; }

/* 供给全宽在上，来源与兴趣并列在下：热力矩阵需要横向空间，左右也不再失衡 */
.trust-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  grid-template-areas:
    'supply supply'
    'sources interest';
  gap: var(--qh-innovation-gap);
  align-items: start;
}
.chart-card.is-wide { grid-area: supply; }
.source-panel { grid-area: sources; }
.chart-card.is-interest { grid-area: interest; align-self: start; }
.chart-card.is-interest .chart-canvas { height: 322px; }
.source-panel { padding: 20px; }
.panel-head, .chart-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.panel-head h3, .chart-title h3 { margin: 0; font-size: 14px; }
.chart-sub { margin: 4px 0 0; color: var(--qh-innovation-muted); font-size: 11px; line-height: 1.5; }
.source-list { display: flex; flex-direction: column; gap: 8px; }
.source-card {
  position: relative;
  padding: 11px 12px 11px 16px;
  border: 1px solid var(--qh-innovation-border);
  border-radius: 8px;
  background: var(--qh-innovation-canvas);
  transition: background-color 260ms var(--qh-innovation-ease),
    border-color 260ms var(--qh-innovation-ease);
}
.source-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 3px;
  border-radius: 2px;
  background: #9aa3b2;
}
.source-card.is-verified::before { background: var(--qh-innovation-positive); }
.source-card.is-fetched::before { background: #6c92e9; }
.source-card:hover { background: var(--qh-innovation-surface); border-color: rgba(25, 81, 195, 0.32); }
.source-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.source-top h4 { margin: 0; font-size: 13px; }
.source-badge {
  flex: none;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 11px;
  color: var(--qh-innovation-muted);
  background: var(--qh-innovation-surface);
  border: 1px solid var(--qh-innovation-border);
}
.is-verified .source-badge { border-color: rgba(15, 157, 138, 0.4); color: var(--qh-innovation-positive); }
.is-fetched .source-badge { border-color: rgba(108, 146, 233, 0.45); color: #1951c3; }
.source-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 8px 0;
  color: var(--qh-innovation-muted);
  font-size: 12px;
}
.source-card a { font-size: 12px; color: var(--qh-innovation-primary); text-decoration: none; }
.source-card a:hover { text-decoration: underline; }
.source-nolink { font-size: 12px; color: var(--qh-innovation-muted); }

.chart-card {
  padding: 20px;
  transition: border-color 260ms var(--qh-innovation-ease),
    box-shadow 260ms var(--qh-innovation-ease);
}
.chart-card:hover { border-color: rgba(25, 81, 195, 0.24); box-shadow: 0 6px 20px rgba(23, 43, 90, 0.06); }
.chart-title { min-width: 0; }
.view-toggle {
  flex: none;
  padding: 4px 10px;
  border: 1px solid var(--qh-innovation-border);
  border-radius: 999px;
  background: var(--qh-innovation-surface);
  color: var(--qh-innovation-primary);
  font-size: 11px;
}
.view-toggle:hover { border-color: var(--qh-innovation-primary); background: var(--qh-innovation-primary-soft); }
.chart-area { width: 100%; min-width: 0; }
.chart-canvas { width: 100%; height: 286px; }
.chart-canvas.is-tall { height: 348px; }
.heat-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 96px;
  color: var(--qh-innovation-muted);
  font-size: 11px;
}
.heat-ramp {
  width: 120px;
  height: 10px;
  border-radius: 5px;
  background: linear-gradient(90deg, #cddaff, #9db8f5, #6c92e9, #3f70d4, #1951c3);
}
.heat-unit { margin-left: 2px; }
.table-wrap { width: 100%; max-width: 100%; overflow-x: auto; }
.compact-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.compact-table caption {
  margin-bottom: 6px;
  color: var(--qh-innovation-muted);
  font-size: 11px;
  text-align: left;
}
.compact-table th, .compact-table td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--qh-innovation-border);
  text-align: left;
  white-space: nowrap;
}
.compact-table th { color: var(--qh-innovation-muted); font-weight: 600; background: var(--qh-innovation-canvas); }
.compact-table tbody tr { transition: background-color 260ms var(--qh-innovation-ease); }
.compact-table tbody tr:hover { background: var(--qh-innovation-primary-soft); }
.compact-table th button {
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.compact-table th button:hover { color: var(--qh-innovation-primary); }

/* ---------- 响应式：375px 不横向溢出 ---------- */
@media (max-width: 1180px) {
  .kpi-grid, .step-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .step-card::after { display: none; }
  .trust-grid {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: 'supply' 'sources' 'interest';
  }
}

@media (max-width: 700px) {
  .instance-cols { grid-template-columns: minmax(0, 1fr); }
  .hero { padding: 20px; }
  .hero-rail { display: none; }
  .hub-meta { width: 100%; }
  .chart-canvas { height: 250px; }
  .chart-canvas.is-tall { height: 300px; }
  .chart-canvas.is-map { height: 300px; }
  .empty-inline.is-map { min-height: 300px; }
  .heat-legend { padding-left: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .innovation-hub *,
  .innovation-hub *::before,
  .innovation-hub *::after {
    animation: none !important;
    transition: none !important;
  }
  .reveal { opacity: 1 !important; transform: none !important; }
}
</style>
