<!-- 生涯规划：先测（软技能五维），再算（考公/考编/考研竞争力）。
     顺序是刻意的——测评是「我是谁」，报考分析是「我能打到哪」，先看自己再看门。 -->
<template>
  <div class="hub-page">
    <HubBar v-model="tab" :tabs="tabs" aria-label="生涯规划切换" @change="go" />

    <div v-show="tab === 'career'"><CareerForecast /></div>
    <div v-show="tab === 'assessment'"><Assessment /></div>
  </div>
</template>

<script setup>
import HubBar from '../components/hub/HubBar.vue'
import { useTabQuery } from '../composables/useTabQuery'
import Assessment from './Assessment.vue'
import CareerForecast from './CareerForecast.vue'

const tabs = [
  { key: 'career', label: '报考分析', hint: '按你的指标算考公 / 考编 / 考研竞争力' },
  { key: 'assessment', label: '职业测评', hint: '软技能五维画像，看适合什么类型的工作' }
]

const { tab, go } = useTabQuery(tabs)
</script>
