<template>
  <div class="login-shell" :class="{ 'is-leaving': leaving }">
    <!-- 左：两江启航叙事场景 -->
    <section class="login-hero" aria-label="重庆财经学院启航系统介绍">
      <LoginScene />

      <div class="login-hero__inner">
        <header class="brand-lockup">
          <span class="brand-mark">启</span>
          <div class="brand-lockup__text">
            <span class="brand-name">启航</span>
            <span class="brand-school">重庆财经学院 · 生涯与岗位匹配</span>
          </div>
        </header>

        <div class="hero-copy">
          <h1 class="hero-title">把山城的起伏，<br />走成你的上升曲线。</h1>
          <p class="hero-sub">
            教师看见班级的下一步，学生看见自己的下一站。
            所有数字由确定性引擎算出，AI 只负责把结论说清楚。
          </p>

          <div class="hero-actions">
            <button class="enter-btn" type="button" @click="focusLogin">
              开始使用
              <svg class="enter-arw" viewBox="0 0 12 10" fill="none" aria-hidden="true">
                <path
                  d="M0.8 5h10M7.1 1.4 10.9 5l-3.8 3.6"
                  stroke="currentColor"
                  stroke-width="1.35"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
            <a
              class="teacher-link"
              href="/login?role=teacher"
              @click.prevent="goRole('teacher')"
            >
              辅导员入口 →
            </a>
          </div>

          <div class="hero-tags" aria-label="系统特性">
            <span>确定性引擎</span>
            <span>多智能体</span>
            <span>多租户隔离</span>
          </div>
        </div>

        <footer class="hero-foot">
          <span>重庆财经学院 · 启航</span>
          <span>学业预警 / 岗位匹配 / 生涯规划</span>
        </footer>
      </div>
    </section>

    <!-- 右：登录控制台 -->
    <section ref="formPanelRef" class="login-panel" aria-label="登录">
      <div class="login-card">
        <div class="panel-head">
          <div>
            <h2 class="panel-title">登录启航</h2>
            <p class="panel-sub">选择身份，进入你的工作台</p>
          </div>
          <span class="panel-badge"><i />安全登录</span>
        </div>

        <el-form label-position="top" class="login-form" @submit.prevent="onLogin">
          <el-form-item label="身份">
            <el-radio-group v-model="form.role" class="role-switch">
              <el-radio-button value="teacher">教师端</el-radio-button>
              <el-radio-button value="student">学生端</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item :label="form.role === 'teacher' ? '工号' : '学号'">
            <el-input
              ref="accountRef"
              v-model="form.account"
              size="large"
              autocomplete="username"
              :placeholder="form.role === 'teacher' ? '如 T001' : '如 AI20230001'"
            />
          </el-form-item>

          <el-form-item label="口令">
            <el-input
              v-model="form.password"
              size="large"
              type="password"
              show-password
              autocomplete="current-password"
              :placeholder="`演示账号口令：${DEMO_PASSWORD}`"
              @keyup.enter="onLogin"
            />
          </el-form-item>

          <el-button class="login-btn" :loading="loading" @click="onLogin">
            进入工作台
          </el-button>
        </el-form>

        <div v-if="!publicDemoMode" class="demo-box">
          <strong>演示账号（点一下自动填入，统一口令 {{ DEMO_PASSWORD }}）</strong>
          <button type="button" class="demo-item" @click="fillDemo('teacher', 'T001', DEMO_PASSWORD)">
            教师：T001 / {{ DEMO_PASSWORD }}
          </button>
          <button type="button" class="demo-item" @click="fillDemo('student', 'AI20230001', DEMO_PASSWORD)">
            学生（大四）：AI20230001 / {{ DEMO_PASSWORD }}
          </button>
          <button type="button" class="demo-item" @click="fillDemo('student', 'AI20260001', DEMO_PASSWORD)">
            学生（大一）：AI20260001 / {{ DEMO_PASSWORD }}
          </button>
        </div>
        <div v-else class="demo-box">
          <strong>公网临时演示账号</strong>
          <span>教师：T001</span>
          <span>学生：AI20260001（大一） · AI20250001（大二）</span>
          <span>AI20240004（大三） · AI20230001（大四）</span>
          <span>临时公网共享口令：{{ DEMO_PASSWORD }}</span>
        </div>

        <p class="role-hint">
          {{ publicDemoMode ? '临时演示仅开放上述模拟账号。' : '辅导员入口：' }}
          <code v-if="!publicDemoMode">/login?role=teacher</code>
          <template v-if="!publicDemoMode">（链接直达教师身份，账号与口令照旧）</template>
        </p>
      </div>

      <p class="panel-foot">数据由确定性引擎计算 · 身份由后端登录态注入</p>
      <p class="login-live" role="status" aria-live="polite">{{ liveMessage }}</p>
    </section>
  </div>
</template>

<script setup>
// Login：重庆财经学院「两江启航」登录页。
// 左侧是 SVG 山水叙事场景 + 品牌航线，右侧是稳定的登录工作台；
// 不再使用全屏视频/玻璃遮罩，首屏更轻，表单始终可见。

import { nextTick, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'

import http, { saveSession } from '../api/http'
import LoginScene from '../components/brand/LoginScene.vue'

const publicDemoMode = import.meta.env.VITE_PUBLIC_DEMO_MODE === 'true'
// 本地演示账号统一口令；这是登录页公开的演示凭证，不是生产密钥。
const DEMO_PASSWORD = import.meta.env.VITE_DEMO_PASSWORD || '123456h'
const form = reactive({
  role: 'teacher',
  account: 'T001',
  password: publicDemoMode ? '' : DEMO_PASSWORD
})
const loading = ref(false)
// 纯视觉状态：成功跳转瞬间整页轻 fade；liveMessage 供屏幕阅读器播报
const leaving = ref(false)
const liveMessage = ref('')
const router = useRouter()
const route = useRoute()
const accountRef = ref(null)
const formPanelRef = ref(null)

// URL 带 ?role=teacher|student 时跟随链接预选身份
watch(
  () => route.query.role,
  (val) => {
    if (val === 'teacher' || val === 'student') form.role = val
  },
  { immediate: true }
)

function focusLogin() {
  if (window.innerWidth < 900) {
    formPanelRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  nextTick(() => {
    accountRef.value?.focus?.({ preventScroll: window.innerWidth < 900 })
  })
}

function goRole(role) {
  form.role = role
  focusLogin()
}

// 演示账号一键填充：省得手输学号时把 8 位写成 7 位
function fillDemo(role, account, password) {
  form.role = role
  form.account = account
  form.password = password
}

async function onLogin() {
  if (!form.account || !form.password) {
    liveMessage.value = '请填写账号与口令'
    ElMessage.warning('请填写账号与口令')
    return
  }
  loading.value = true
  try {
    const { data } = await http.post('/auth/login', {
      role: form.role,
      account: form.account,
      password: form.password
    })
    saveSession(data.role, data.access_token, {
      student_no: data.student_no,
      tenant_id: data.tenant_id
    })
    const target = data.role === 'teacher' ? '/teacher' : '/student'
    liveMessage.value = '登录成功，正在进入工作台'
    ElMessage.success(`登录成功：${form.role === 'teacher' ? '教师端' : '学生端'}`)
    // 跳转不等待动画：fade 与路由切换并行，不阻塞导航
    leaving.value = true
    router.push(typeof route.query.redirect === 'string' ? route.query.redirect : target)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-shell {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(420px, 0.9fr);
  min-height: 100vh;
  min-height: 100svh;
  background: #06171d;
  transition: opacity 320ms var(--qh-ease);
}

/* 登录成功跳转瞬间的轻 fade：与路由切换并行，不阻塞导航 */
.login-shell.is-leaving {
  opacity: 0;
}

/* ---------- 左侧叙事场景 ---------- */
.login-hero {
  position: relative;
  min-height: 100vh;
  min-height: 100svh;
  overflow: hidden;
  isolation: isolate;
}

.login-hero__inner {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 24px;
  padding: clamp(28px, 4.6vw, 64px);
  pointer-events: none;
}

.brand-lockup {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  align-self: flex-start;
  animation: login-rise 0.7s cubic-bezier(0.22, 0.61, 0.36, 1) 0.1s both;
}

.brand-mark {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  border-radius: 12px;
  background: linear-gradient(145deg, #3b6ee5 0%, #1951c3 52%, #0f9d8a 120%);
  color: #fff;
  font-size: 19px;
  font-weight: 700;
  box-shadow:
    0 8px 22px rgba(25, 81, 195, 0.4),
    inset 0 1px 0 rgba(255, 255, 255, 0.42);
}

.brand-lockup__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.brand-name {
  color: #f4fffd;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: 0.02em;
}

.brand-school {
  color: rgba(226, 244, 242, 0.62);
  font-size: 11.5px;
  line-height: 1.4;
  letter-spacing: 0.05em;
}

.hero-copy {
  position: relative;
  z-index: 2;
  max-width: 620px;
  margin-top: auto;
}

.hero-title {
  margin: 0;
  color: #f4fffd;
  font-size: clamp(30px, 3.2vw, 48px);
  font-weight: 700;
  line-height: 1.18;
  letter-spacing: -0.025em;
  text-wrap: balance;
  text-shadow: 0 2px 26px rgba(2, 14, 18, 0.32);
  animation: login-title-in 0.85s cubic-bezier(0.22, 0.61, 0.36, 1) 0.24s both;
}

.hero-sub {
  margin: 16px 0 0;
  max-width: 46ch;
  color: rgba(226, 244, 242, 0.7);
  font-size: 15px;
  line-height: 1.75;
  animation: login-rise 0.7s ease 0.44s both;
}

.hero-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 24px;
  pointer-events: auto;
  animation: login-rise 0.7s ease 0.58s both;
}

.enter-btn {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 12px 20px 12px 24px;
  border: 0;
  border-radius: 999px;
  background: #f4fffd;
  color: #0b2830;
  font-family: var(--cf-font-sans, inherit);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 12px 30px rgba(2, 14, 18, 0.3);
  transition:
    transform 240ms var(--qh-ease),
    box-shadow 240ms var(--qh-ease),
    background-color 240ms var(--qh-ease);
}

.enter-btn:hover {
  background: #fff;
  transform: translateY(-1px);
  box-shadow: 0 16px 38px rgba(2, 14, 18, 0.36);
}

.enter-btn:active {
  transform: translateY(0) scale(0.98);
}

.enter-arw {
  width: 13px;
  height: 11px;
  display: block;
  transition: transform 240ms var(--qh-ease);
}

.enter-btn:hover .enter-arw {
  transform: translateX(3px);
}

.teacher-link {
  display: inline-flex;
  align-items: center;
  padding: 10px 16px;
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  color: #eaf8f4;
  font-size: 13.5px;
  font-weight: 550;
  text-decoration: none;
  transition:
    border-color 200ms var(--qh-ease),
    background-color 200ms var(--qh-ease),
    color 200ms var(--qh-ease);
}

.teacher-link:hover {
  border-color: rgba(216, 180, 90, 0.62);
  background: rgba(216, 180, 90, 0.12);
  color: #f1d58f;
}

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 22px;
  animation: login-rise 0.7s ease 0.7s both;
}

.hero-tags span {
  padding: 5px 10px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(236, 248, 244, 0.66);
  font-family: var(--cf-font-mono);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.hero-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.09);
  color: rgba(226, 244, 242, 0.42);
  font-family: var(--cf-font-mono);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  animation: login-rise 0.8s ease 0.82s both;
}

/* ---------- 右侧登录工作台 ---------- */
.login-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
  min-height: 100vh;
  min-height: 100svh;
  padding: 48px 40px;
  background:
    radial-gradient(520px 300px at 100% 0%, rgba(111, 201, 193, 0.1), transparent 64%),
    linear-gradient(180deg, #f7fafa 0%, #f1f5f5 100%);
  border-left: 1px solid rgba(216, 180, 90, 0.16);
}

.login-card {
  position: relative;
  width: min(420px, 100%);
  padding: 30px 32px 26px;
  border: 1px solid #e1e7e8;
  border-radius: 20px;
  background: #ffffff;
  box-shadow:
    0 1px 2px rgba(8, 24, 28, 0.04),
    0 24px 60px rgba(8, 24, 28, 0.1);
  animation: login-card-in 0.75s cubic-bezier(0.22, 0.61, 0.36, 1) 0.32s both;
}

/* 卡顶 1px 品牌航线：把左侧场景的线收进表单 */
.login-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 24px;
  right: 24px;
  height: 1px;
  background: linear-gradient(90deg, rgba(111, 201, 193, 0), #d8b45a 52%, rgba(111, 201, 193, 0));
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}

.panel-title {
  margin: 0;
  color: var(--cf-ink);
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.panel-sub {
  margin: 6px 0 0;
  color: var(--cf-mid);
  font-size: 13px;
  line-height: 1.5;
}

.panel-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--cf-teal-soft);
  color: #0b7d70;
  font-family: var(--cf-font-mono);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.panel-badge i {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--cf-teal);
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.role-switch {
  width: 100%;
}

.role-switch :deep(.el-radio-button) {
  flex: 1;
}

.role-switch :deep(.el-radio-button__inner) {
  width: 100%;
  border-radius: 10px;
  border: 1px solid var(--cf-line);
  box-shadow: none;
  transition: all 200ms ease;
}

.login-btn {
  position: relative;
  overflow: hidden;
  width: 100%;
  height: 46px;
  margin-top: 6px;
  border: 0;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  background: transparent;
  --el-button-bg-color: transparent;
  --el-button-border-color: transparent;
  --el-button-hover-bg-color: transparent;
  --el-button-hover-border-color: transparent;
  --el-button-active-bg-color: transparent;
  background-image: linear-gradient(135deg, #2d61dd 0%, #1951c3 52%, #14419c 100%);
  box-shadow:
    0 10px 24px rgba(25, 81, 195, 0.24),
    inset 0 1px 0 rgba(255, 255, 255, 0.22);
  transition:
    transform 240ms var(--qh-ease),
    box-shadow 240ms var(--qh-ease),
    background-image 240ms var(--qh-ease);
}

/* hover 微光：低亮度白色高光层，只动 opacity */
.login-btn::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.16), transparent 62%);
  opacity: 0;
  transition: opacity 240ms var(--qh-ease);
  pointer-events: none;
}

.login-btn:hover {
  background-image: linear-gradient(135deg, #3b6ee5 0%, #1f5ad0 52%, #14419c 100%);
  box-shadow:
    0 14px 30px rgba(25, 81, 195, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.26);
  transform: translateY(-1px);
}

.login-btn:hover::after {
  opacity: 1;
}

.login-btn:active {
  transform: translateY(0) scale(0.98);
}

.demo-box {
  display: grid;
  gap: 5px;
  margin-top: 16px;
  padding: 12px 14px;
  border: 1px solid #dce7e5;
  border-radius: 12px;
  background: linear-gradient(135deg, #f4faf9, #f7fbfb);
  font-family: var(--cf-font-mono);
  font-size: 12px;
  color: var(--cf-mid);
}

.demo-box strong {
  color: var(--cf-ink);
  font-family: var(--cf-font-sans);
  font-size: 12px;
}

.demo-item {
  position: relative;
  overflow: hidden;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: none;
  font: inherit;
  font-size: 12px;
  color: var(--cf-coral);
  text-align: left;
  cursor: pointer;
  transition: transform 200ms var(--qh-ease);
}

/* hover 扫光：一次性低亮度靛蓝高光扫过 */
.demo-item::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(105deg, transparent 34%, rgba(25, 81, 195, 0.12) 50%, transparent 66%);
  transform: translateX(-110%);
  pointer-events: none;
}

.demo-item:hover {
  text-decoration: underline;
  transform: translateY(-1px);
}

.demo-item:hover::after {
  animation: demo-sweep 0.7s var(--qh-ease);
}

.demo-item:focus-visible {
  outline: 2px solid rgba(25, 81, 195, 0.55);
  outline-offset: 2px;
}

@keyframes demo-sweep {
  to {
    transform: translateX(110%);
  }
}

.role-hint {
  margin: 12px 0 0;
  color: var(--cf-mid);
  font-size: 12.5px;
  line-height: 1.6;
}

.role-hint code {
  padding: 2px 6px;
  border-radius: 6px;
  background: var(--cf-bg-deep);
  color: var(--cf-coral);
  font-family: var(--cf-font-mono);
  font-size: 12px;
}

.panel-foot {
  margin: 0;
  color: var(--cf-faint);
  font-family: var(--cf-font-mono);
  font-size: 10.5px;
  letter-spacing: 0.04em;
  text-align: center;
  animation: login-rise 0.8s ease 0.56s both;
}

/* 屏幕阅读器专用播报区：视觉隐藏但可被 aria-live 读出 */
.login-live {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}

/* ---------- 入场编排 keyframes（只动 transform/opacity/clip-path） ---------- */
@keyframes login-rise {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes login-title-in {
  from {
    opacity: 0;
    transform: translateY(16px);
    clip-path: inset(0 0 100% 0);
  }
  to {
    opacity: 1;
    transform: translateY(0);
    clip-path: inset(0 0 0 0);
  }
}

@keyframes login-card-in {
  from {
    opacity: 0;
    transform: translateY(18px) scale(0.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* ---------- 响应式：窄屏先保住场景，再落到表单 ---------- */
@media (max-width: 1200px) {
  .login-panel {
    padding: 36px 24px;
  }
}

@media (max-width: 1023px) {
  .login-shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .login-hero {
    min-height: 540px;
  }

  .login-hero__inner {
    padding: 30px 26px;
  }

  .hero-title {
    font-size: clamp(28px, 5.2vw, 36px);
  }

  .hero-sub {
    max-width: 52ch;
  }

  .login-panel {
    min-height: 0;
    padding: 30px 20px 40px;
    border-left: 0;
    border-top: 1px solid rgba(216, 180, 90, 0.16);
  }

  .login-card {
    width: min(520px, 100%);
  }
}

@media (max-width: 600px) {
  .login-hero {
    min-height: 470px;
  }

  .login-hero__inner {
    padding: 22px 18px;
  }

  .brand-mark {
    width: 36px;
    height: 36px;
    flex-basis: 36px;
    font-size: 17px;
  }

  .brand-name {
    font-size: 17px;
  }

  .brand-school {
    font-size: 10.5px;
  }

  .hero-title {
    font-size: 27px;
  }

  .hero-sub {
    margin-top: 12px;
    font-size: 13.5px;
    line-height: 1.7;
  }

  .hero-actions {
    margin-top: 18px;
  }

  .hero-tags {
    margin-top: 16px;
  }

  .hero-foot {
    margin-top: 18px;
  }

  .hero-foot span:last-child {
    display: none;
  }

  .login-panel {
    padding: 22px 12px 30px;
  }

  .login-card {
    padding: 24px 20px 22px;
    border-radius: 16px;
  }

  .panel-title {
    font-size: 23px;
  }

  .panel-badge {
    padding: 5px 8px;
    font-size: 10px;
  }

  .demo-box,
  .demo-item {
    font-size: 12.5px;
    line-height: 1.6;
  }
}

@media (pointer: coarse) {
  /* 触屏不做 hover 抬升/扫光，避免粘滞 hover 态 */
  .demo-item:hover {
    transform: none;
  }

  .demo-item:hover::after {
    animation: none;
  }

  .enter-btn:hover,
  .login-btn:hover {
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .login-shell,
  .enter-btn,
  .enter-arw,
  .teacher-link,
  .login-btn,
  .login-btn::after,
  .demo-item {
    transition: none;
  }

  .brand-lockup,
  .hero-title,
  .hero-sub,
  .hero-actions,
  .hero-tags,
  .hero-foot,
  .login-card,
  .panel-foot,
  .demo-item::after {
    animation: none;
  }

  .demo-item::after {
    display: none;
  }

  .enter-btn:hover,
  .login-btn:hover,
  .demo-item:hover {
    transform: none;
  }
}
</style>
