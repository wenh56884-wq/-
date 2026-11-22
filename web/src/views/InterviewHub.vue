<!-- 模拟面试板块：实战演练（原模拟面试）+ 复盘实验室（原面试实验室）两个工位。
     原来侧栏两个入口，学生练完一场还要自己去另一个入口找复盘，路径是断的。 -->
<template>
  <div class="hub-page">
    <HubBar v-model="tab" :tabs="tabs" aria-label="模拟面试板块切换" @change="go" />

    <!-- v-show 而非 v-if：面试进行中切到实验室再切回来，不能把答题进度弄丢 -->
    <div v-show="tab === 'practice'">
      <InterviewRoom />
    </div>
    <div v-show="tab === 'lab'">
      <InterviewLab @practice="go('practice')" />
    </div>
  </div>
</template>

<script setup>
import HubBar from '../components/hub/HubBar.vue'
import { useTabQuery } from '../composables/useTabQuery'
import InterviewLab from './InterviewLab.vue'
import InterviewRoom from './InterviewRoom.vue'

const tabs = [
  { key: 'practice', label: '实战演练', hint: '简历 → 动态出题 → 逐题点评 → 评分报告' },
  { key: 'lab', label: '复盘实验室', hint: '先看结论，再挑工具：六个维度查清一场面试为什么这样' }
]

const { tab, go } = useTabQuery(tabs, { param: 'mode' })
</script>
