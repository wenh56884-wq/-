<template>
  <div class="page nf">
    <div class="nf-card">
      <div class="nf-code">404</div>
      <h2 class="nf-title">这个页面不存在</h2>
      <p class="nf-desc">
        地址可能输错了，或者这个板块没有对你当前登录的角色开放。
      </p>
      <div class="nf-actions">
        <el-button type="primary" @click="goHome">回到我的主页</el-button>
        <el-button v-if="canBack" @click="goBack">返回上一页</el-button>
      </div>
      <p class="nf-path">
        访问地址：<code>{{ route.fullPath }}</code>
      </p>
    </div>
  </div>
</template>

<script setup>
// 职责：路由兜底页。既挂在顶层（/abc），也挂在 /teacher、/student 内部
// （/teacher/xxx），后者带侧栏，用户还能继续导航，不会整屏白掉。
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { currentRole } from '../api/http'

const route = useRoute()
const router = useRouter()

// 只有「本应用内确实有上一页」才给返回按钮，避免退回站外空白页
const canBack = computed(() => window.history.length > 1)

function goHome() {
  router.push(currentRole() === 'teacher' ? '/teacher' : '/student')
}

function goBack() {
  router.back()
}
</script>

<style scoped>
.nf {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 52vh;
}

.nf-card {
  max-width: 440px;
  padding: 32px 28px;
  text-align: center;
  background: var(--qh-surface);
  border: 1px solid var(--qh-border);
  border-radius: var(--qh-radius-xl);
}

.nf-code {
  font-size: 56px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: 0.04em;
  color: #e4e4e7;
  font-variant-numeric: tabular-nums;
}

.nf-title {
  margin: 14px 0 6px;
  font-size: 17px;
  font-weight: 600;
  color: var(--qh-text);
}

.nf-desc {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--qh-text-sub);
}

.nf-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 20px;
}

.nf-path {
  margin: 16px 0 0;
  font-size: 12px;
  color: var(--qh-text-mute);
  word-break: break-all;
}

.nf-path code {
  padding: 2px 6px;
  border-radius: 6px;
  background: #f4f4f5;
  font-size: 11.5px;
}
</style>
