<template>
  <div class="login-shell">
    <div class="bento-grid login-grid">
      <!-- 大卡片：品牌主视觉 -->
      <section class="bento-card bento-card--gradient bento-span-2 bento-row-2 login-hero">
        <div class="hero-top">
          <span class="hero-mark">启</span>
          <span class="hero-kicker">QIHANG · 生涯与岗位匹配</span>
        </div>

        <div class="hero-copy">
          <h1 class="hero-title">把学业风险<br />变成可执行的下一步</h1>
          <p class="hero-sub">
            教师看班级预警，学生看岗位差距。所有数字由确定性引擎算出，
            AI 只负责把结论说成人话。
          </p>
          <div class="hero-chips">
            <span>确定性引擎</span>
            <span>多智能体</span>
            <span>多租户隔离</span>
          </div>
        </div>

        <div class="hero-metrics">
          <div>
            <b>10,000</b>
            <span>在校学生</span>
          </div>
          <div>
            <b>2,931</b>
            <span>岗位画像</span>
          </div>
          <div>
            <b>3,477</b>
            <span>图谱节点</span>
          </div>
        </div>
      </section>

      <!-- 大卡片：登录 -->
      <section class="bento-card bento-span-2 bento-row-2 login-panel">
        <div class="panel-head">
          <div>
            <p class="bento-eyebrow">欢迎回来</p>
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
          <strong>演示账号</strong>
          <span>教师：T001 / teacher@123</span>
          <span>学生：AI20230001 / AI20230001</span>
        </div>
      </section>

      <!-- 小卡片：四个能力 -->
      <article class="bento-card feature-card">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 4.5-3 7.5-7 10-4-2.5-7-5.5-7-10V6l7-3z" /></svg>
        </span>
        <h3>学业预警</h3>
        <p>三色风险 + 逐条归因，先发现再干预。</p>
      </article>

      <article class="bento-card feature-card">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></svg>
        </span>
        <h3>岗位匹配</h3>
        <p>专业、成绩、技能、兴趣四维加权推荐。</p>
      </article>

      <article class="bento-card feature-card">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
        </span>
        <h3>模拟面试</h3>
        <p>简历出题、逐题点评、报告与差距清单。</p>
      </article>

      <article class="bento-card feature-card">
        <span class="bento-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="10" rx="3" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>
        </span>
        <h3>数据隔离</h3>
        <p>身份只来自登录态，租户过滤在数据层。</p>
      </article>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import http, { saveSession } from '../api/http'

const form = reactive({ role: 'teacher', account: 'T001', password: 'teacher@123' })
const loading = ref(false)
const router = useRouter()
const route = useRoute()

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
  min-height: 100vh;
  padding: 28px 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(900px 520px at 8% 0%, #fff7ed 0%, transparent 60%),
    radial-gradient(760px 460px at 100% 100%, #ecfeff 0%, transparent 55%),
    var(--bento-bg);
}

.login-grid {
  width: min(1180px, 100%);
}

.login-hero {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 22px;
  padding: 32px;
  min-height: 440px;
  overflow: hidden;
}

.hero-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hero-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.18);
  font-size: 22px;
  font-weight: 700;
}

.hero-kicker {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: rgba(255, 255, 255, 0.82);
}

.hero-copy {
  max-width: none;
}

.hero-title {
  margin: 0;
  max-width: 100%;
  font-size: clamp(30px, 2.8vw, 40px);
  line-height: 1.16;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #fff;
  text-wrap: balance;
}

.hero-sub {
  margin: 16px 0 0;
  font-size: 14px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.88);
  max-width: 34ch;
}

.hero-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.hero-chips span {
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  font-size: 12px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.95);
}

.hero-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding-top: 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.22);
}

.hero-metrics div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.hero-metrics b {
  font-size: 22px;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
}

.hero-metrics span {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.78);
}

.login-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 30px 32px;
  min-height: 440px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.panel-title {
  margin: 0;
  font-size: 30px;
  font-weight: 680;
  line-height: 1.2;
  color: var(--bento-text);
}

.panel-sub {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--bento-sub);
}

.panel-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  background: #f0fdf4;
  color: #15803d;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.panel-badge i {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #22c55e;
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
  border-radius: 12px;
  border: 1px solid var(--bento-border-strong);
  box-shadow: none;
  transition: all 220ms var(--bento-ease);
}

.role-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: #18181b;
  border-color: #18181b;
  color: #fff;
}

.login-btn {
  width: 100%;
  height: 46px;
  margin-top: 4px;
  border: 0;
  border-radius: 14px;
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  background: #18181b;
  --el-button-bg-color: #18181b;
  --el-button-border-color: #18181b;
  --el-button-hover-bg-color: #27272a;
  --el-button-hover-border-color: #27272a;
  --el-button-active-bg-color: #18181b;
  transition: transform 200ms var(--bento-ease), box-shadow 200ms var(--bento-ease),
    background-color 200ms var(--bento-ease);
}

.login-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 24px rgba(24, 24, 27, 0.18);
}

.login-btn:active {
  transform: scale(0.98);
}

.demo-box {
  margin-top: auto;
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid var(--bento-border);
  border-radius: 14px;
  background: #fafafa;
  font-size: 12px;
  color: var(--bento-sub);
}

.demo-box strong {
  color: var(--bento-text);
  font-size: 12px;
}

.feature-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 18px;
}

.feature-card h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  color: var(--bento-text);
}

.feature-card p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--bento-sub);
}

@media (max-width: 700px) {
  .login-shell {
    padding: 16px 12px;
    align-items: flex-start;
  }

  .login-hero,
  .login-panel {
    min-height: auto;
    padding: 22px;
  }

  .hero-title {
    font-size: 30px;
  }

  .hero-metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
