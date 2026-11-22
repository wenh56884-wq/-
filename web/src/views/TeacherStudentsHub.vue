<!-- 学生板块（教师端）：班级总览 → 学生档案 → 全班成绩，同一个对象的三层视角。
     原来三个入口在侧栏里并排，教师看完总览要去档案里找人、再跳成绩页，来回三次。 -->
<template>
  <div class="hub-page">
    <HubBar v-model="tab" :tabs="tabs" aria-label="学生板块切换" @change="go" />

    <div v-show="tab === 'overview'"><TeacherDashboard /></div>
    <div v-show="tab === 'roster'"><TeacherStudents /></div>
    <div v-show="tab === 'grades'"><GradeReport /></div>
  </div>
</template>

<script setup>
import HubBar from '../components/hub/HubBar.vue'
import { useTabQuery } from '../composables/useTabQuery'
import GradeReport from './GradeReport.vue'
import TeacherDashboard from './TeacherDashboard.vue'
import TeacherStudents from './TeacherStudents.vue'

const tabs = [
  { key: 'overview', label: '班级总览', hint: '全班预警、绩点与意向分布' },
  { key: 'roster', label: '学生档案', hint: '点开单个学生看四维画像' },
  { key: 'grades', label: '全班成绩', hint: '按学期看课程成绩与班级排名' }
]

const { tab, go } = useTabQuery(tabs)
</script>
