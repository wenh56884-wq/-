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

<style scoped>
/* 机会库科技感：只在本板块内升级共享 HubBar，浅色底不变，
   深色只出现在激活分段的渐变里，不改组件本身与其他板块。 */
.hub-page :deep(.hubbar) {
  border-bottom-color: rgba(25, 81, 195, 0.16);
}

/* 吸顶栏底部一道两端消隐的靛蓝→青发丝线 */
.hub-page :deep(.hubbar::after) {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(25, 81, 195, 0.45) 28%,
    rgba(0, 194, 255, 0.7) 50%,
    rgba(25, 81, 195, 0.45) 72%,
    transparent 100%
  );
  pointer-events: none;
}

.hub-page :deep(.seg-btn.on) {
  background: var(--tech-gradient, linear-gradient(135deg, #1951c3 0%, #2b7ae0 50%, #00c2ff 100%));
  box-shadow:
    0 4px 14px rgba(25, 81, 195, 0.3),
    0 0 16px -6px rgba(0, 194, 255, 0.45);
}

.hub-page :deep(.seg-btn:hover:not(.on)) {
  color: var(--tech-blue, #1951c3);
  background: rgba(0, 194, 255, 0.08);
}

@media (prefers-reduced-motion: reduce) {
  .hub-page :deep(.seg-btn) {
    transition: none;
  }
}
</style>
