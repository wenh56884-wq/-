// web/src/utils/echarts.js
// 职责：按需注册图表与组件，避免把整包 ECharts（823KB）打进三个用到图表的页面。
// 新增图表类型时在这里补注册，不要在页面里改回 import 'echarts'。

import * as echarts from 'echarts/core'
import { BarChart, LineChart, RadarChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  RadarComponent,
  TooltipComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  LineChart,
  RadarChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  RadarComponent,
  TooltipComponent,
  CanvasRenderer
])

export default echarts

// ---------- 科技感图表渐变：纯视觉工具，不参与任何业务计算 ----------
// 供各图表 series.areaStyle / itemStyle 取用，统一走 --tech-chart-* 同色系。
// 用法：areaStyle: { color: techAreaGradient() }
export function techAreaGradient() {
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: 'rgba(25, 81, 195, 0.42)' },
    { offset: 0.6, color: 'rgba(43, 122, 224, 0.16)' },
    { offset: 1, color: 'rgba(0, 194, 255, 0.02)' }
  ])
}

// 柱状图自下而上的靛蓝→青渐变
export function techBarGradient() {
  return new echarts.graphic.LinearGradient(0, 1, 0, 0, [
    { offset: 0, color: 'rgba(0, 194, 255, 0.55)' },
    { offset: 1, color: '#1951c3' }
  ])
}
