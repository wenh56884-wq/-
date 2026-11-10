<template>
  <div class="login-shell">
    <!-- 左：3D 生涯导航核心 + 品牌叠层 -->
    <section class="field-side">
      <VideoBackdrop class="login-video" :scrim="0" object-position="51% 8%" />
      <div class="field-overlay">
        <div class="brand-top">
          <span class="brand-mark">启</span>
          <span class="brand-kicker">QIHANG · 生涯领域控制台</span>
        </div>

        <div class="brand-copy">
          <h1 class="brand-title">把学业风险<br />变成可执行的下一步</h1>
          <p class="brand-sub">
            教师看班级预警，学生看岗位差距。所有数字由确定性引擎算出，
            AI 只负责把结论说成人话。
          </p>
          <div class="brand-chips">
            <span>确定性引擎</span>
            <span>多智能体</span>
            <span>多租户隔离</span>
          </div>
          <!-- 教师端入口链接：管理员把 /login?role=teacher 发给辅导员即可直达教师身份 -->
          <a class="teacher-link" href="/login?role=teacher"
             @click.prevent="goRole('teacher')">
            辅导员入口 →
          </a>

          <!-- 落地门：先看到品牌介绍，点「开始使用」才放登录表单 -->
          <button
            type="button"
            class="enter-btn"
            :class="{ 'is-gone': stage !== 'welcome' }"
            @click="enterLogin"
          >
            开始使用
            <svg class="enter-arw" viewBox="0 0 12 10" fill="none" aria-hidden="true">
              <path d="M0.8 5h10M7.1 1.4 10.9 5l-3.8 3.6" stroke="currentColor"
                    stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </section>

    <!-- 右：登录控制卡（点「开始使用」后才出现） -->
    <section class="form-side" :class="{ 'is-live': stage === 'login' }" :aria-hidden="stage !== 'login'">
      <div class="form-card">
        <div class="panel-head">
          <div>
            <p class="panel-eyebrow">WELCOME BACK</p>
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
              placeholder="学生初始口令为学号"
              @keyup.enter="onLogin"
            />
          </el-form-item>

          <el-button class="login-btn" :loading="loading" @click="onLogin">
            进入工作台
          </el-button>
        </el-form>

        <div class="demo-box">
          <strong>演示账号（点一下自动填入）</strong>
          <button type="button" class="demo-item"
                  @click="fillDemo('teacher', 'T001', 'teacher@123')">
            教师：T001 / teacher@123
          </button>
          <button type="button" class="demo-item"
                  @click="fillDemo('student', 'AI20230001', 'AI20230001')">
            学生（大四）：AI20230001 / AI20230001
          </button>
          <button type="button" class="demo-item"
                  @click="fillDemo('student', 'AI20260001', 'AI20260001')">
            学生（大一）：AI20260001 / AI20260001
          </button>
        </div>
        <p class="role-hint">
          辅导员入口：<code>/login?role=teacher</code>（链接直达教师身份，账号与口令照旧）
        </p>
      </div>
    </section>
  </div>
</template>

<script setup>
import { nextTick, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import http, { saveSession } from '../api/http'
import VideoBackdrop from '../components/VideoBackdrop.vue'

const form = reactive({ role: 'teacher', account: 'T001', password: 'teacher@123' })
const loading = ref(false)
const router = useRouter()
const route = useRoute()

/* 落地门：welcome 只展示品牌层，点「开始使用」才放登录表单 */
const stage = ref('welcome')
const accountRef = ref(null)

// 教师端入口链接（/login?role=teacher）：直达并跳到登录表单，免去再点一次
function goRole(role) {
  form.role = role
  if (stage.value === 'welcome') enterLogin()
}
// URL 带 ?role=teacher|student 时跟随链接预选身份
watch(
  () => route.query.role,
  (val) => { if (val === 'teacher' || val === 'student') form.role = val },
  { immediate: true }
)

function enterLogin() {
  stage.value = 'login'
  nextTick(() => accountRef.value?.focus())
}

// 演示账号一键填充：省得手输学号时把 8 位写成 7 位
function fillDemo(role, account, password) {
  form.role = role
  form.account = account
  form.password = password
}

async function onLogin() {
  if (!form.account || !form.password) {
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
    ElMessage.success(`登录成功：${form.role === 'teacher' ? '教师端' : '学生端'}`)
    router.push(typeof route.query.redirect === 'string' ? route.query.redirect : target)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-shell {
  position: relative;
  display: flex;
  min-height: 100vh;
  min-height: 100svh;
  overflow: hidden;
  background:
    radial-gradient(circle at 76% 12%, rgba(70, 201, 191, 0.12), transparent 30%),
    var(--cf-bg);
}

/* 左：3D 生涯导航核心 */
.field-side {
  position: relative;
  flex: 1 1 100%;
  width: 100%;
  min-width: 100%;
  display: flex;
  min-height: 100vh;
  isolation: isolate;
  overflow: hidden;
  background: #082d35;
}

.field-side::before,
.field-side::after {
  content: '';
  position: absolute;
  z-index: 1;
  pointer-events: none;
  border-radius: 50%;
  filter: blur(2px);
  display: none;
}

.field-side::before {
  width: 58vw;
  height: 58vw;
  left: -18vw;
  top: -20vw;
  background: radial-gradient(circle, rgba(70, 201, 191, 0.24), transparent 66%);
  animation: login-orbit-glow 12s ease-in-out infinite alternate;
}

.field-side::after {
  width: 44vw;
  height: 44vw;
  right: -18vw;
  bottom: -22vw;
  background: radial-gradient(circle, rgba(25, 81, 195, 0.16), transparent 68%);
  animation: login-orbit-glow 15s ease-in-out -4s infinite alternate-reverse;
}

.field-side :deep(.career-field) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  border-radius: 0;
  background:
    radial-gradient(circle at 50% 48%, rgba(21, 89, 92, 0.72), transparent 28%),
    linear-gradient(145deg, #082d35 0%, #0b3d43 52%, #142b45 100%);
}

.field-side :deep(.login-video) {
  z-index: 0;
  background: #000;
}

.field-side :deep(.login-video .vb-video) {
  width: max(100vw, calc(100dvh * 1.6));
  height: max(62.5vw, 100dvh);
  left: 50%;
  top: 50%;
  right: auto;
  bottom: auto;
  transform: translate(-50%, -50%);
  object-fit: cover;
  object-position: 51% 8%;
}

.field-side :deep(.login-video .vb-scrim) {
  background: transparent !important;
}

.field-side :deep(.career-field::before) {
  background-image:
    linear-gradient(rgba(143, 218, 210, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(143, 218, 210, 0.07) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(circle at 50% 50%, #000 0%, transparent 82%);
}

.field-side :deep(.career-field::after) {
  inset: 22px;
  border-color: rgba(143, 218, 210, 0.2);
  border-radius: 18px;
}

.field-side :deep(.career-field__canvas) {
  opacity: 0.9;
}

.field-side :deep(.career-field__topline),
.field-side :deep(.career-field__footer) {
  color: rgba(209, 242, 238, 0.62);
}

.field-side :deep(.career-field__brand) {
  color: #d1f2ee;
}

.field-side :deep(.career-field__mode) {
  border-left-color: rgba(143, 218, 210, 0.28);
}

.field-side :deep(.career-field__axis--x) {
  background: linear-gradient(90deg, transparent, rgba(143, 218, 210, 0.3), transparent);
}

.field-side :deep(.career-field__axis--y) {
  background: linear-gradient(180deg, transparent, rgba(143, 218, 210, 0.24), transparent);
}

.field-side :deep(.career-field__node) {
  border-color: rgba(143, 218, 210, 0.24);
  background: rgba(5, 34, 41, 0.48);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.14);
  color: #d1f2ee;
}

.field-side :deep(.career-field__node small) {
  color: rgba(183, 225, 220, 0.6);
}

.field-side :deep(.career-field__fallback-ring) {
  border-color: rgba(143, 218, 210, 0.24);
}

.field-side :deep(.career-field__fallback-ring--two) {
  border-color: rgba(255, 134, 108, 0.42);
}

.field-overlay {
  position: relative;
  z-index: 3;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 24px;
  padding: clamp(28px, 5vw, 68px);
  width: 100%;
  pointer-events: none;
}

.brand-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  position: relative;
  overflow: hidden;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(145deg, #3b6ee5 0%, #1951c3 52%, #0f9d8a 120%);
  color: #fff;
  font-size: 19px;
  font-weight: 700;
  box-shadow:
    0 8px 22px rgba(25, 81, 195, 0.42),
    inset 0 1px 0 rgba(255, 255, 255, 0.42);
}

.brand-kicker {
  font-family: var(--cf-font-mono);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: rgba(209, 242, 238, 0.76);
}

/* 标题做轻微渐变字：白 → 浅青，深色视频上更亮眼，也不影响可读性 */
.brand-title {
  margin: 0;
  font-size: clamp(26px, 2.4vw, 36px);
  line-height: 1.2;
  font-weight: 700;
  color: #f5fffd;
  background: linear-gradient(118deg, #ffffff 0%, #eafffb 46%, #b9f3ea 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  text-shadow: none;
  text-wrap: balance;
  /* 视频里有亮区，给一行极淡的投影兜底行高对比 */
  filter: drop-shadow(0 2px 18px rgba(2, 20, 28, 0.5));
}

.brand-sub {
  margin: 14px 0 0;
  max-width: 36ch;
  font-size: 14px;
  line-height: 1.7;
  color: rgba(209, 242, 238, 0.72);
}

.brand-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.brand-chips span {
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid rgba(143, 218, 210, 0.3);
  background: rgba(5, 34, 41, 0.34);
  backdrop-filter: blur(10px) saturate(140%);
  -webkit-backdrop-filter: blur(10px) saturate(140%);
  font-family: var(--cf-font-mono);
  font-size: 11px;
  font-weight: 500;
  color: rgba(232, 255, 251, 0.9);
  transition: border-color 220ms var(--qh-ease), background-color 220ms var(--qh-ease),
    transform 220ms var(--qh-ease);
}

.brand-chips span:hover {
  border-color: rgba(185, 243, 234, 0.5);
  background: rgba(15, 157, 138, 0.22);
  transform: translateY(-1px);
}

/* 落地门的「开始使用」：白底胶囊 + 箭头，视频之上要够亮才显眼 */
.enter-btn {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  margin-top: 24px;
  padding: 13px 22px 13px 26px;
  border: 0;
  border-radius: 999px;
  background: #ffffff;
  color: var(--cf-ink, #0d2b30);
  font-family: var(--cf-font-sans, inherit);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  pointer-events: auto;
  box-shadow: 0 10px 30px rgba(1, 23, 31, 0.32);
  transition:
    background-color 300ms var(--qh-ease),
    box-shadow 300ms var(--qh-ease),
    transform 300ms var(--qh-ease),
    opacity 240ms ease,
    visibility 0s;
}

.enter-btn:hover {
  background: #f2fffc;
  box-shadow: 0 14px 38px rgba(1, 23, 31, 0.38);
}

.enter-btn:active {
  transform: scale(0.98);
}

.enter-arw {
  width: 13px;
  height: 11px;
  flex: 0 0 auto;
  display: block;
  transition: transform 300ms var(--qh-ease);
}

.enter-btn:hover .enter-arw {
  transform: translateX(3px);
}

/* 点下去之后整颗按钮退场，让位给登录卡（同样只淡出，不位移） */
.enter-btn.is-gone {
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition:
    opacity 180ms ease,
    visibility 0s linear 180ms;
}

@keyframes login-orbit-glow {
  from { transform: translate3d(-2%, -1%, 0) scale(0.96); opacity: 0.72; }
  to { transform: translate3d(3%, 2%, 0) scale(1.04); opacity: 1; }
}

/* 右：登录控制卡 */
.form-side {
  position: absolute;
  inset: 0;
  z-index: 10;
  width: 100%;
  max-width: none;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 32px;
  background: transparent;
  pointer-events: none;
  /* 落地门：默认收起，点「开始使用」后淡入。
     只做透明度 —— 位移和缩放会读成「弹窗跳出」，跟整页的静态气质冲突。
     visibility 负责把整块从 Tab 序和读屏里摘掉。 */
  opacity: 0;
  visibility: hidden;
  transition:
    opacity 240ms ease,
    visibility 0s linear 240ms;
}

.form-side.is-live {
  opacity: 1;
  visibility: visible;
  transition:
    opacity 240ms ease,
    visibility 0s;
}

.form-card {
  position: relative;
  width: min(440px, calc(100vw - 48px));
  padding: 30px 32px;
  background: rgba(255, 255, 255, 0.97);
  border: 1px solid rgba(228, 231, 238, 0.92);
  border-radius: var(--qh-radius-xl);
  box-shadow:
    0 30px 80px rgba(1, 23, 31, 0.34),
    0 2px 8px rgba(1, 23, 31, 0.12),
    0 0 0 1px rgba(255, 255, 255, 0.6) inset;
  display: flex;
  flex-direction: column;
  gap: 16px;
  pointer-events: auto;
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  overflow: hidden;
}

/* 卡片顶部一道靛蓝→青的渐变发丝线：整块玻璃立起来的关键一笔 */
.form-card::before {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  height: 3px;
  background: linear-gradient(90deg, #2d61dd, #1951c3 46%, #0f9d8a);
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.panel-eyebrow {
  margin: 0 0 4px;
  font-family: var(--cf-font-mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--cf-teal);
}

.panel-title {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--cf-ink);
}

.panel-sub {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--cf-mid);
}

.panel-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--cf-teal-soft);
  color: var(--cf-teal);
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
  border-radius: var(--qh-radius-lg);
  border: 1px solid var(--cf-line);
  box-shadow: none;
  transition: all 220ms ease;
}

.login-btn {
  width: 100%;
  height: 46px;
  margin-top: 4px;
  border: 0;
  border-radius: var(--qh-radius-lg);
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
    0 10px 24px rgba(79, 70, 229, 0.28),
    inset 0 1px 0 rgba(255, 255, 255, 0.22);
  transition:
    transform 300ms var(--qh-ease),
    box-shadow 300ms var(--qh-ease),
    background-image 300ms var(--qh-ease);
}

.login-btn:hover {
  background-image: linear-gradient(135deg, #3b6ee5 0%, #1f5ad0 52%, #14419c 100%);
  box-shadow:
    0 14px 30px rgba(79, 70, 229, 0.34),
    inset 0 1px 0 rgba(255, 255, 255, 0.26);
  transform: translateY(-1px);
}

.login-btn:active {
  transform: translateY(0) scale(0.99);
}

.demo-box {
  display: grid;
  gap: 5px;
  padding: 12px 14px;
  border: 1px solid var(--cf-line);
  border-radius: var(--qh-radius-lg);
  background: var(--cf-bg-deep);
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
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  font-size: 12px;
  color: var(--cf-coral);
  text-align: left;
  cursor: pointer;
}

.demo-item:hover {
  text-decoration: underline;
}

/* 响应式：移动端堆叠，3D 核心降为矮横幅，登录卡在下方 */
@media (max-width: 1023px) {
  .login-shell {
    min-height: 100svh;
  }

  .field-side {
    min-height: 100svh;
  }

  .field-side::before {
    width: 90vw;
    height: 90vw;
    left: -24vw;
    top: -42vw;
  }

  .field-side::after {
    width: 70vw;
    height: 70vw;
    right: -28vw;
    bottom: -48vw;
  }

  .field-overlay {
    padding: 20px 20px 18px;
    gap: 14px;
  }

  .brand-title {
    font-size: 22px;
  }

  .brand-sub {
    font-size: 13px;
  }

  .field-side :deep(.career-field__node) {
    background: rgba(5, 34, 41, 0.58);
  }

  .form-side {
    padding: 20px;
  }

  .form-card {
    width: min(440px, calc(100vw - 40px));
    padding: 24px 22px;
  }

  .field-overlay {
    padding: 20px;
  }

  .brand-copy {
    max-width: 260px;
    margin-top: 80px;
  }

  /* 压暗文案但不动 .brand-copy 整块 —— 里面的「开始使用」按钮不能跟着变淡
    （父级 opacity 会成组生效，子元素无法超出） */
  .brand-title,
  .brand-sub,
  .brand-chips {
    opacity: 0.72;
  }
}

@media (prefers-reduced-motion: reduce) {
  .field-side::before,
  .field-side::after {
    animation: none;
  }

  .form-side,
  .form-side.is-live,
  .enter-btn,
  .enter-arw {
    transition: none;
  }
}

/* 教师端入口链接：品牌侧，珊瑚红圆角胶囊，hover 轻微提亮 */
.teacher-link {
  display: inline-block;
  margin-top: 18px;
  padding: 6px 16px;
  border-radius: 999px;
  border: 1px solid var(--cf-line);
  background: rgba(255, 255, 255, 0.86);
  color: var(--cf-coral);
  font-size: 13.5px;
  font-weight: 600;
  text-decoration: none;
  transition: color 160ms var(--qh-ease), border-color 160ms var(--qh-ease),
    background-color 160ms var(--qh-ease);
}

.teacher-link:hover {
  background: var(--cf-coral-soft);
  border-color: var(--cf-coral);
}

/* 教师入口提示：等宽小字，方便复制链接 */
.role-hint {
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--cf-mid);
}

.role-hint code {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px;
  background: var(--cf-bg-deep);
  color: var(--cf-coral);
  border-radius: 6px;
  padding: 2px 6px;
}

@media (prefers-reduced-motion: reduce) {
  .teacher-link {
    transition: none;
  }
}
</style>
