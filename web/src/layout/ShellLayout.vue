<template>
  <div class="shell">
    <header class="shell-header">
      <div class="brand">
        <span class="brand-mark">启</span>
        <div class="brand-text">
          <div class="brand-title">启航 · 生涯与岗位匹配系统</div>
          <div class="brand-sub">确定性引擎算数 · 大模型负责表达</div>
        </div>
      </div>

      <div class="pulse">
        <span class="pulse-item">
          <i class="dot" :class="dotClass(health.db)"></i>MySQL <b>{{ health.db }}</b>
        </span>
        <span class="pulse-item">
          <i class="dot" :class="dotClass(health.duckdb)"></i>DuckDB <b>{{ health.duckdb }}</b>
        </span>
        <span class="pulse-item">
          <i class="dot" :class="health.llm === 'configured' ? 'dot-ok' : 'dot-warn'"></i>
          LLM <b>{{ health.llm }}</b>
        </span>
        <el-tag size="small" :type="statusTag" effect="plain">{{ statusText }}</el-tag>
        <span class="pulse-time">健康检测 {{ ago(health.lastCheckAt) }}</span>
        <el-button size="small" link :loading="health.checking" @click="refresh">立即刷新</el-button>
      </div>

      <div class="who">
        <span class="who-clock">{{ timeText }}</span>
        <el-tag size="small" :type="role === 'teacher' ? 'danger' : 'success'" effect="dark">
          {{ role === 'teacher' ? '教师' : '学生' }}
        </el-tag>
        <span class="who-name">{{ identityText }}</span>
        <el-button size="small" @click="logout">退出</el-button>
      </div>
    </header>

    <div class="shell-body">
      <aside class="shell-aside">
        <el-menu :default-active="$route.path" router>
          <el-menu-item v-for="item in menus" :key="item.path" :index="item.path">
            <span class="menu-label">{{ item.label }}</span>
            <span class="menu-hint">{{ item.hint }}</span>
          </el-menu-item>
        </el-menu>
        <div class="aside-foot">
          <div class="aside-line">数值全部来自接口，前端不做任何计算</div>
          <div class="aside-line">所有结论经 Critic 数值回查</div>
        </div>
      </aside>

      <main class="shell-main">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { clearSession, currentRole } from '../api/http'
import { useClock, useSystemStatus } from '../composables/useSystemStatus'

const { health, refresh } = useSystemStatus()
// 解构后才能在模板里自动解包（timeText 是 computed）
const { timeText, ago } = useClock()
const router = useRouter()
const role = currentRole()

const MENUS = {
  teacher: [
    { path: '/teacher', label: '班级总览', hint: '全班预警与概貌' },
    { path: '/teacher/students', label: '学生档案', hint: '全班→个人详情' },
    { path: '/assistant', label: '智能助手', hint: '多智能体问答' }
  ],
  student: [
    { path: '/student', label: '我的画像', hint: '预警 + 岗位推荐' },
    { path: '/assistant', label: '智能助手', hint: '多智能体问答' }
  ]
}

const menus = computed(() => MENUS[role] || MENUS.student)

const identityText = computed(() => {
  if (role === 'teacher') {
    const tenant = localStorage.getItem('qh_tenant_id')
    return tenant ? `教师 · 租户 ${tenant}` : '教师'
  }
  return localStorage.getItem('qh_student_no') || '学生'
})

const statusText = computed(() => {
  const map = { ok: '服务正常', degraded: '部分降级', down: '服务不可达', checking: '检测中' }
  return map[health.status] || health.status
})

const statusTag = computed(() => {
  const map = { ok: 'success', degraded: 'warning', down: 'danger', checking: 'info' }
  return map[health.status] || 'info'
})

function dotClass(state) {
  if (state === 'ok') return 'dot-ok'
  if (state === 'down') return 'dot-bad'
  return 'dot-warn'
}

function logout() {
  clearSession()
  router.push('/login')
}
</script>

<style scoped>
.shell {
  min-height: 100vh;
  background: var(--qh-bg);
}

.shell-header {
  height: 60px;
  background: #fff;
  border-bottom: 1px solid #e5e6eb;
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 0 20px;
  position: sticky;
  top: 0;
  z-index: 20;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 260px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: var(--qh-red);
  color: #fff;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.brand-title {
  font-weight: 600;
  font-size: 15px;
}

.brand-sub {
  font-size: 12px;
  color: #86909c;
}

.pulse {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 12px;
  color: #4e5969;
  flex: 1;
  justify-content: center;
  flex-wrap: wrap;
}

.pulse-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.pulse-item b {
  color: #1f2329;
}

.pulse-time {
  color: #86909c;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  background: #c9cdd4;
}

.dot-ok {
  background: #4cb971;
  animation: pulse-ring 2s infinite;
}

.dot-warn {
  background: var(--qh-orange);
}

.dot-bad {
  background: var(--qh-red);
  animation: pulse-ring 1s infinite;
}

.who {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.who-clock {
  font-variant-numeric: tabular-nums;
  color: #4e5969;
  font-size: 13px;
}

.who-name {
  color: #1f2329;
}

.shell-body {
  display: flex;
  align-items: flex-start;
}

.shell-aside {
  width: 200px;
  flex: 0 0 200px;
  background: #fff;
  border-right: 1px solid #e5e6eb;
  min-height: calc(100vh - 60px);
  display: flex;
  flex-direction: column;
}

.shell-main {
  flex: 1;
  min-width: 0;
  padding: 0;
}

.menu-label {
  font-size: 14px;
}

.menu-hint {
  margin-left: 8px;
  font-size: 11px;
  color: #a9aeb8;
}

.aside-foot {
  margin-top: auto;
  padding: 12px;
  font-size: 11px;
  color: #a9aeb8;
  line-height: 1.8;
  border-top: 1px dashed #e5e6eb;
}

@keyframes pulse-ring {
  0% {
    box-shadow: 0 0 0 0 rgba(76, 185, 113, 0.5);
  }
  70% {
    box-shadow: 0 0 0 6px rgba(76, 185, 113, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(76, 185, 113, 0);
  }
}
</style>
