<!-- 机会库：企业岗位 + 招考公告 + 考证中心。三条路都是「毕业去哪」，放在一起才比得出来。
     岗位库与招考页内部本来就是按角色取数，教师/学生共用这一个板块。 -->
<template>
  <div class="hub-page">
    <HubBar v-model="tab" :tabs="tabs" aria-label="机会库切换" @change="go" />

    <div v-show="tab === 'jobs'"><JobList /></div>
    <div v-show="tab === 'exams'"><ExamNotices /></div>
    <div v-show="tab === 'certs'"><CertHub /></div>
  </div>
</template>

<script setup>
import HubBar from '../components/hub/HubBar.vue'
import { useTabQuery } from '../composables/useTabQuery'
import CertHub from './CertHub.vue'
import ExamNotices from './ExamNotices.vue'
import JobList from './JobList.vue'

const tabs = [
  { key: 'jobs', label: '企业岗位', hint: '企业岗位周更，按你的画像算匹配' },
  { key: 'exams', label: '招考公告', hint: '考公 / 考编 / 考研，带官方原文链接' },
  { key: 'certs', label: '考证中心', hint: '谁考什么、差什么、什么时候报名，AI 说明为什么' }
]

const { tab, go } = useTabQuery(tabs)
</script>
