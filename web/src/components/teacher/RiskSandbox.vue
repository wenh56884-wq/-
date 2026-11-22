<template>
  <section class="bento-card risk-sandbox">
    <div class="sandbox-head">
      <div>
        <p class="bento-eyebrow">班级风险沙盘</p>
        <h3 class="bento-title">绩点 × 风险分 散点图</h3>
        <p class="bento-sub">
          {{ className || '当前班级' }} · {{ term || '本学期' }} · 横轴绩点/均分，纵轴风险分
        </p>
      </div>
      <span class="sandbox-hint">点击散点查看画像</span>
    </div>

    <div v-loading="loading" class="sandbox-body">
      <el-empty
        v-if="!loading && !points.length"
        :image-size="96"
        description="暂无可绘制的绩点/风险分数据"
      />
      <div
        v-show="points.length"
        ref="chartRef"
        class="sandbox-chart"
        role="img"
        :aria-label="ariaLabel"
      />
    </div>

    <p class="sandbox-foot">
      仅展示同时具备绩点与风险分的学生；点的颜色对应引擎预警等级，数值均由预警引擎计算。
    </p>
  </section>
</template>

<script setup>
// RiskSandbox：教师端风险沙盘，把 warning_list 的 risk_score × metrics.gpa 画成可点击散点
// 本组件只做过滤与展示，不计算任何风险分/等级/绩点；点击散点抛出原始行给父级开画像
// 数据源为父级传入的 warning_list items，缺绩点或风险分的行直接跳过，不用 0 顶替
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts from '../../utils/echarts'

const props = defineProps({
  items: { type: Array, default: () => [] },
  className: { type: String, default: '' },
  term: { type: String, default: '' },
  loading: { type: Boolean, default: false }
})

const emit = defineEmits(['select'])

// 与教师端预警分布同色系：等级由引擎给出，这里只负责把等级映射成颜色
const LEVELS = [
  { key: 'red', label: '红色预警', color: '#e5484d' },
  { key: 'orange', label: '橙色预警', color: '#f5a623' },
  { key: 'yellow', label: '黄色预警', color: '#f0c808' },
  { key: 'none', label: '正常', color: '#4cb971' },
  { key: 'unknown', label: '数据不足', color: '#8a919f' }
]
const LEVEL_KEYS = new Set(LEVELS.map((item) => item.key))
const LEVEL_TEXT = Object.fromEntries(LEVELS.map((item) => [item.key, item.label]))

const chartRef = ref(null)
let chart = null

function hasValue(value) {
  return value !== null && value !== undefined && value !== ''
}

function levelOf(row) {
  return LEVEL_KEYS.has(row?.level) ? row.level : 'unknown'
}

// 只保留引擎同时返回了风险分与 metrics.gpa 的学生；缺任一项就不画，避免用 0 顶替
const points = computed(() =>
  (props.items || [])
    .filter((row) => hasValue(row?.risk_score) && hasValue(row?.metrics?.gpa))
    .map((row) => ({
      row,
      level: levelOf(row),
      gpa: Number(row.metrics.gpa),
      score: Number(row.risk_score)
    }))
    .filter((item) => Number.isFinite(item.gpa) && Number.isFinite(item.score))
)

const ariaLabel = computed(
  () => `班级风险散点图：GPA 与风险分，共 ${points.value.length} 名可绘制学生`
)

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function tooltipRow(label, value) {
  return `<div style="display:flex;justify-content:space-between;gap:18px;line-height:1.8">
    <span style="color:#8a919f">${label}</span>
    <b style="color:#16181d;font-weight:600">${escapeHtml(value)}</b>
  </div>`
}

function tooltipHtml(params) {
  // ECharts formatter 传的是 series.data 项：value=[gpa, risk]，row/level 是随点携带的原值
  const data = params?.data || {}
  const row = data.row || {}
  const [gpa, score] = Array.isArray(data.value) ? data.value : []
  const gpaText = Number.isFinite(Number(gpa)) ? Number(gpa).toFixed(1) : '—'
  const level = data.level || 'unknown'
  return [
    `<div style="font-size:12px;color:#16181d;min-width:150px">`,
    tooltipRow('姓名', row.name || '—'),
    tooltipRow('学号', row.student_no || '—'),
    tooltipRow('风险分', score),
    tooltipRow('GPA / 均分', gpaText),
    tooltipRow('等级', LEVEL_TEXT[level] || level || '—'),
    `</div>`
  ].join('')
}

function buildSeries() {
  // 只给当前有数据的等级建系列，避免图例出现「正常 0 人」这类空项误导教师
  return LEVELS
    .map((level) => ({
      level,
      data: points.value
        .filter((point) => point.level === level.key)
        .map((point) => ({
          value: [point.gpa, point.score],
          level: point.level,
          row: point.row
        }))
    }))
    .filter((item) => item.data.length)
    .map(({ level, data }) => ({
      name: level.label,
      type: 'scatter',
      cursor: 'pointer',
      symbolSize: 12,
      itemStyle: { color: level.color, opacity: 0.9 },
      emphasis: { scale: 1.5, itemStyle: { opacity: 1 } },
      data
    }))
}

function render() {
  if (!chartRef.value) return
  if (!points.value.length) {
    chart?.clear()
    return
  }
  if (!chart) {
    chart = echarts.init(chartRef.value)
    chart.on('click', (params) => {
      // 打开画像抽屉前收起提示框，避免抽屉关闭后残留在页面上
      chart.dispatchAction({ type: 'hideTip' })
      const row = params?.data?.row
      if (row) emit('select', row)
    })
  }
  chart.setOption(
    {
      grid: { left: 56, right: 28, top: 48, bottom: 58 },
      legend: {
        top: 0,
        left: 0,
        icon: 'circle',
        itemWidth: 9,
        itemHeight: 9,
        textStyle: { color: '#4e5969', fontSize: 12 }
      },
      tooltip: {
        trigger: 'item',
        confine: true,
        formatter: (params) => tooltipHtml(params)
      },
      xAxis: {
        type: 'value',
        name: 'GPA / 均分',
        nameLocation: 'middle',
        nameGap: 32,
        scale: true,
        nameTextStyle: { color: '#8a919f' },
        axisLabel: { color: '#4e5969' },
        splitLine: { lineStyle: { color: '#e4e7ee' } }
      },
      yAxis: {
        type: 'value',
        name: '风险分',
        // 引擎风险分固定裁剪在 0~100，固定轴域便于横向比较，不是前端推算
        min: 0,
        max: 100,
        nameTextStyle: { color: '#8a919f' },
        axisLabel: { color: '#4e5969' },
        splitLine: { lineStyle: { color: '#e4e7ee' } }
      },
      series: buildSeries()
    },
    true
  )
  chart.resize()
}

watch(points, async () => {
  await nextTick()
  render()
})

function onResize() {
  chart?.resize()
  // 视口变化后旧坐标的提示框可能留在页面外，主动收起
  chart?.dispatchAction({ type: 'hideTip' })
}

onMounted(async () => {
  window.addEventListener('resize', onResize)
  await nextTick()
  render()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.risk-sandbox {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sandbox-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.sandbox-head .bento-title {
  margin: 2px 0 4px;
}

.sandbox-hint {
  flex: 0 0 auto;
  padding: 4px 10px;
  border-radius: 999px;
  background: #eef0f5;
  color: var(--bento-sub, #5f6672);
  font-size: 12px;
  white-space: nowrap;
}

.sandbox-body {
  min-height: 320px;
}

.sandbox-chart {
  width: 100%;
  height: 320px;
  min-width: 0;
  /* ECharts 收起提示框时只改 visibility，仍占布局；裁掉越界部分避免移动端横向滚动 */
  overflow: hidden;
}

.sandbox-foot {
  margin: 0;
  color: var(--bento-mute, #8a919f);
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 700px) {
  .sandbox-hint {
    white-space: normal;
  }

  .sandbox-chart {
    height: 280px;
  }
}
</style>
