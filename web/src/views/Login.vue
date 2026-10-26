<template>
  <div class="login-wrap">
    <el-card class="login-card" shadow="always">
      <template #header>
        <div class="login-title">启航 · 学业预警与职业发展助手</div>
      </template>

      <el-form label-position="top" @submit.prevent="onLogin">
        <el-form-item label="身份">
          <el-radio-group v-model="form.role">
            <el-radio value="teacher">教师</el-radio>
            <el-radio value="student">学生</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="form.role === 'teacher' ? '工号' : '学号'">
          <el-input v-model="form.account" autocomplete="username" placeholder="教师 T001 / 学生学号" />
        </el-form-item>
        <el-form-item label="口令">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="学生初始口令为学号"
            @keyup.enter="onLogin"
          />
        </el-form-item>
        <el-button type="primary" class="login-btn" :loading="loading" @click="onLogin">
          登录
        </el-button>
      </el-form>

      <el-alert type="info" :closable="false" show-icon title="演示账号">
        <template #default>
          <div>教师：T001 / teacher@123</div>
          <div>学生：学号登录（初始口令 = 学号，如 AI2022001）</div>
        </template>
      </el-alert>
    </el-card>
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
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--qh-bg);
}

.login-card {
  width: 420px;
}

.login-title {
  font-size: 18px;
  font-weight: 600;
  text-align: center;
}

.login-btn {
  width: 100%;
  margin-bottom: 12px;
}
</style>
