<!-- 学业板块：把我的成绩（过去）、学业预测（未来）、选课建议（该补什么）放在同一页。
     原来三块各占一个侧栏位，学生要在三个入口之间来回跳才看得出「谁因谁果」。 -->
<template>
  <div class="hub-page">
    <HubBar v-model="tab" :tabs="tabs" aria-label="学业板块切换" @change="go" />

    <!-- v-show 而不是 v-if：三块都带筛选与图表状态，切走再切回不该重新拉一遍 -->
    <div v-show="tab === 'grades'"><GradeReport /></div>
    <div v-show="tab === 'forecast'"><StudentForecast /></div>
    <div v-show="tab === 'elective'"><ElectiveAdvice /></div>
  </div>
</template>

<script setup>
import HubBar from '../components/hub/HubBar.vue'
import { useTabQuery } from '../composables/useTabQuery'
import ElectiveAdvice from './ElectiveAdvice.vue'
import GradeReport from './GradeReport.vue'
import StudentForecast from './StudentForecast.vue'

const tabs = [
  { key: 'grades', label: '成绩明细', hint: '按学年看每一门课的成绩与排名' },
  { key: 'forecast', label: '学业预测', hint: '下学期会考成什么样、哪门有挂科风险' },
  { key: 'elective', label: '选课建议', hint: '技能缺口 → 这学期该选哪几门课' }
]

const { tab, go } = useTabQuery(tabs)
</script>
