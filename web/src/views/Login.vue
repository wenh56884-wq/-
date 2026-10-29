<template>
  <div class="login-shell">
    <div class="login-wrap">
      <!-- 左：渐变品牌区 -->
      <section class="brand-side">
        <div class="brand-top">
          <span class="brand-mark">启</span>
          <span class="brand-kicker">QIHANG · 生涯与岗位匹配</span>
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
        </div>

        <div class="brand-metrics">
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

      <!-- 右：白色表单卡 -->
      <section class="form-side">
        <div class="form-card">
          <div class="panel-head">
            <div>
              <p class="panel-eyebrow">欢迎回来</p>
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
        </div>

        <ul class="feature-list">
          <li>
            <span class="feature-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 4.5-3 7.5-7 10-4-2.5-7-5.5-7-10V6l7-3z" /></svg>
            </span>
            <b>学业预警</b><span>三色风险 + 逐条归因</span>
          </li>
          <li>
            <span class="feature-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></svg>
            </span>
            <b>岗位匹配</b><span>四维加权推荐</span>
          </li>
          <li>
            <span class="feature-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
            </span>
            <b>模拟面试</b><span>逐题点评与报告</span>
          </li>
          <li>
            <span class="feature-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="10" rx="3" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>
            </span>
            <b>数据隔离</b><span>租户过滤在数据层</span>
          </li>
        </ul>
      </section>
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

// 演示账号一键填充：省得手输学号时把 8 位写成 7 位（AI20260001 vs AI2026001）
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
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px 24px;
  background:
    radial-gradient(900px 520px at 8% 0%, #eef0ff 0%, transparent 60%),
    radial-gradient(760px 460px at 100% 100%, #e8f6ff 0%, transparent 55%),
    var(--qh-bg, #f5f7fc);
}

.login-wrap {
  width: min(1180px, 100%);
  display: grid;
  grid-template-columns: minmax(0, 1.06fr) minmax(0, 0.94fr);
  gap: 22px;
  align-items: stretch;
}

/* ---------- 左：渐变品牌区 ---------- */
.brand-side {
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 26px;
  padding: 34px 36px;
  border-radius: var(--qh-radius-xl, 16px);
  color: #fff;
  background:
    radial-gradient(120% 130% at 84% -6%, rgba(255, 255, 255, 0.24), transparent 46%),
    linear-gradient(135deg, #6366f1 0%, #5b5bd6 52%, #7c3aed 100%);
  box-shadow: 0 14px 34px rgba(91, 91, 214, 0.26);
}

/* 细网格底纹：不外链图片，纯 CSS */
.brand-side::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.07) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: linear-gradient(200deg, rgba(0, 0, 0, 0.85), transparent 62%);
  -webkit-mask-image: linear-gradient(200deg, rgba(0, 0, 0, 0.85), transparent 62%);
  pointer-events: none;
}

.brand-side > * {
  position: relative;
}

.brand-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.22);
  font-size: 20px;
  font-weight: 700;
}

.brand-kicker {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: rgba(255, 255, 255, 0.85);
}

.brand-title {
  margin: 0;
  font-size: clamp(28px, 2.6vw, 38px);
  line-height: 1.18;
  font-weight: 700;
  letter-spacing: -0.01em;
  text-wrap: balance;
}

.brand-sub {
  margin: 14px 0 0;
  max-width: 36ch;
  font-size: 14px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.88);
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
  border: 1px solid rgba(255, 255, 255, 0.26);
  background: rgba(255, 255, 255, 0.14);
  font-size: 12px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.95);
}

.brand-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding-top: 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.24);
}

.brand-metrics div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.brand-metrics b {
  font-size: 22px;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
}

.brand-metrics span {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
}

/* ---------- 右：白色表单卡 + 能力清单 ---------- */
.form-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
  justify-content: center;
  min-width: 0;
}

.form-card {
  padding: 30px 32px;
  background: var(--qh-surface, #fff);
  border: 1px solid var(--qh-border, #eceef7);
  border-radius: var(--qh-radius-xl, 16px);
  box-shadow: var(--qh-shadow, 0 2px 10px rgba(33, 40, 90, 0.04), 0 8px 24px rgba(33, 40, 90, 0.04));
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.panel-eyebrow {
  margin: 0 0 4px;
  font-size: 12px;
  font-weight: 600;
  color: #9297ab;
}

.panel-title {
  margin: 0;
  font-size: 28px;
  font-weight: 680;
  line-height: 1.2;
  color: #171a2b;
}

.panel-sub {
  margin: 6px 0 0;
  font-size: 13px;
  color: #5b6178;
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
  border: 1px solid var(--qh-border, #eceef7);
  box-shadow: none;
  transition: all 220ms ease;
}

.role-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: var(--qh-primary, #5b5bd6);
  border-color: var(--qh-primary, #5b5bd6);
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
  background: linear-gradient(135deg, #6366f1, #5b5bd6);
  --el-button-bg-color: #5b5bd6;
  --el-button-border-color: #5b5bd6;
  --el-button-hover-bg-color: #4a4ac0;
  --el-button-hover-border-color: #4a4ac0;
  --el-button-active-bg-color: #3f3fae;
  transition: transform 200ms ease, box-shadow 200ms ease, background-color 200ms ease;
}

.login-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 28px rgba(91, 91, 214, 0.32);
}

.login-btn:active {
  transform: scale(0.98);
}

.demo-box {
  display: grid;
  gap: 5px;
  padding: 12px 14px;
  border: 1px solid var(--qh-border, #eceef7);
  border-radius: 14px;
  background: #f7f8fd;
  font-size: 12px;
  color: #5b6178;
}

.demo-box strong {
  color: #171a2b;
  font-size: 12px;
}

.demo-item {
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  font-size: 12px;
  color: var(--qh-primary, #5b5bd6);
  text-align: left;
  cursor: pointer;
}

.demo-item:hover {
  text-decoration: underline;
}

.feature-list {
  margin: 0;
  padding: 14px 18px;
  list-style: none;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 18px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--qh-border, #eceef7);
  border-radius: 14px;
}

.feature-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: 12.5px;
  color: #5b6178;
}

.feature-list b {
  flex: 0 0 auto;
  color: #171a2b;
  font-weight: 600;
}

.feature-list li span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feature-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  border-radius: 9px;
  background: var(--qh-primary-soft, #f0eeff);
  color: var(--qh-primary, #5b5bd6);
}

.feature-icon svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* ---------- 响应式 ---------- */
@media (max-width: 1023px) {
  .login-wrap {
    grid-template-columns: 1fr;
    max-width: 560px;
    margin: 0 auto;
  }

  .brand-side {
    padding: 24px 24px 22px;
    gap: 18px;
  }

  .brand-metrics {
    padding-top: 14px;
  }

  .brand-metrics b {
    font-size: 18px;
  }

  .form-card {
    padding: 24px 22px;
  }
}

@media (max-width: 700px) {
  .login-shell {
    padding: 16px 12px;
    align-items: flex-start;
  }

  .feature-list {
    grid-template-columns: 1fr;
  }
}
</style>
