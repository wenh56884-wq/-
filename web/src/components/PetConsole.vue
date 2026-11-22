<template>
  <!-- 宠物陪伴控制条：输入框 + 发送 + 专注开关 + 设置；窄屏折叠成右下角圆形入口 -->
  <div
    class="pet-console"
    :class="{ 'is-focus': pet.state.focusMode, 'is-collapsed': collapsed }"
  >
    <button
      v-if="collapsed"
      class="pet-expand"
      type="button"
      aria-label="打开小航对话"
      title="和小航聊聊"
      @click="expand"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
      <span class="pet-expand-ai">AI</span>
    </button>

    <template v-else>
      <input
        ref="inputEl"
        v-model="text"
        class="pet-input"
        :placeholder="placeholder"
        maxlength="200"
        :disabled="pet.state.sending"
        @keydown.enter="send"
      />
      <button class="pet-send" type="button" :disabled="pet.state.sending || !text.trim()" @click="send">
        说
      </button>
      <button
        v-if="pet.state.available"
        class="pet-focus"
        type="button"
        title="跑腿面板：点一条，宠物替你打开对应页面"
        @click="togglePad"
      >
        跑腿
      </button>
      <button
        class="pet-focus"
        type="button"
        :class="{ on: pet.state.focusMode }"
        :title="pet.state.focusMode ? '专注模式：宠物不主动说话' : '陪伴模式：宠物会主动搭话'"
        @click="toggleFocus"
      >
        {{ pet.state.focusMode ? '专注' : '陪伴' }}
      </button>
      <button class="pet-config" type="button" title="宠物设置" @click="openSettings">⚙</button>
      <button
        class="pet-collapse"
        type="button"
        aria-label="收起小航对话"
        @click="collapse"
      >
        ×
      </button>

      <!-- 跑腿面板：贴在控制条上方，点指令直达页面或问 AI -->
      <PetCommandPad
        v-if="padOpen"
        :commands="padCommands"
        :name="pet.state.name"
        @run="runCommand"
        @submit="submitCommand"
        @ask="askAssistant"
        @close="padOpen = false"
      />
    </template>
  </div>

  <ElDialog v-model="showSettings" title="宠物设置" width="min(380px, 92vw)" append-to-body>
    <ElForm label-width="60px" label-position="left">
      <ElFormItem label="名字">
        <ElInput v-model="form.name" maxlength="40" show-word-limit />
      </ElFormItem>
      <ElFormItem label="语气">
        <ElInput v-model="form.tone" maxlength="80" show-word-limit />
      </ElFormItem>
      <ElFormItem label="问候语">
        <ElInput v-model="form.greeting" type="textarea" :rows="2" maxlength="200" show-word-limit />
      </ElFormItem>
      <ElFormItem label="鼓励池">
        <div class="encourage-list">
          <div v-for="(item, idx) in form.encourage" :key="idx" class="encourage-row">
            <ElInput v-model="form.encourage[idx]" maxlength="40" show-word-limit />
            <ElButton size="small" type="danger" plain @click="removeEncourage(idx)">删</ElButton>
          </div>
          <ElButton
            size="small"
            type="primary"
            plain
            :disabled="form.encourage.length >= 10"
            @click="addEncourage"
          >
            + 添加
          </ElButton>
          <div class="encourage-hint">最多 10 条，宠物主动安慰时随机选用</div>
        </div>
      </ElFormItem>
      <ElFormItem label="记住的">
        <div class="memories-list">
          <div v-if="!pet.state.memories.length" class="memories-empty">
            还没有记住什么，多聊聊就有了
          </div>
          <div v-for="m in pet.state.memories" :key="m.id" class="memories-item">
            <template v-if="editingId === m.id">
              <ElInput
                v-model="editingText"
                size="small"
                maxlength="60"
                show-word-limit
                @keydown.enter.prevent="saveMemory(m.id)"
              />
              <ElButton size="small" type="primary" plain @click="saveMemory(m.id)">存</ElButton>
              <ElButton size="small" @click="cancelEdit">取消</ElButton>
            </template>
            <template v-else>
              <span class="memories-text">· {{ m.content }}</span>
              <span class="memories-ops">
                <button type="button" class="memories-btn" title="编辑这条记忆" @click="startEdit(m)">改</button>
                <button type="button" class="memories-btn is-danger" title="删除这条记忆" @click="removeMemory(m.id)">删</button>
              </span>
            </template>
          </div>
        </div>
      </ElFormItem>
    </ElForm>
    <template #footer>
      <ElButton size="small" @click="showSettings = false">取消</ElButton>
      <ElButton size="small" type="primary" :disabled="!form.name.trim()" @click="saveSettings">保存</ElButton>
    </template>
  </ElDialog>
</template>

<script setup>
// PetConsole：宠物对话输入 + 跑腿面板 + 专注开关 + 人格/鼓励池/长期记忆设置弹窗。只调 usePet。
// 跑腿指令直达路由（不再做"宠物走到侧栏再点开"）：确定、快、演示稳。
import { ref, computed, reactive, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs'
import { usePet } from '../composables/usePet'
import { useAssistant } from '../composables/useAssistant'
import { matchCommand, visibleCommands, resolveCommandPath } from '../composables/usePetCommand'
import PetCommandPad from './PetCommandPad.vue'

const router = useRouter()
const pet = usePet()
const { ask: askInAssistant } = useAssistant()

const text = ref('')
const showSettings = ref(false)
const padOpen = ref(false)
const padCommands = ref([])
const editingId = ref(0)
const editingText = ref('')
const form = reactive({ name: '', tone: '', greeting: '', encourage: [] })

// 控制条默认收成右下角一个 54px 圆形入口，点开才展开：
// 320px 的常驻输入条会盖住图表、表格和手机正文，聊天入口不需要一直占着。
const collapsed = ref(true)
const inputEl = ref(null)

async function expand() {
  collapsed.value = false
  await nextTick()
  inputEl.value?.focus({ preventScroll: true })
}

function collapse() {
  collapsed.value = true
  padOpen.value = false
}

const placeholder = computed(() => `和${pet.state.name}聊聊…`)

function send() {
  const t = text.value.trim()
  if (!t) return
  pet.chat(t)
  text.value = ''
}

function togglePad() {
  // 打开时按当前角色现算指令，登录/切角色后不用刷新页面
  padCommands.value = visibleCommands()
  padOpen.value = !padOpen.value
}

// 执行一条指令：直达路由（或拉起 AI 抽屉），宠物说一句承接的话
function runCommand(cmd) {
  padOpen.value = false
  pet.markInteract()
  pet.state.bubbleText = cmd.line
  if (cmd.action === 'ask') {
    askInAssistant()
    return
  }
  const path = resolveCommandPath(cmd)
  if (path) router.push(path)
}

// 自由输入：命中关键词就走指令，没命中交给 AI 兜底
function submitCommand(value) {
  const cmd = matchCommand(value)
  if (cmd) {
    runCommand(cmd)
    return
  }
  padOpen.value = false
  pet.markInteract()
  pet.state.bubbleText = `这个我想不准，交给 AI 帮你答～`
  askInAssistant(value)
}

// 面板底部"问 AI"链接：不带问题，只拉起抽屉
function askAssistant() {
  padOpen.value = false
  pet.markInteract()
  askInAssistant()
}

function toggleFocus() {
  pet.setFocus(!pet.state.focusMode)
}

async function openSettings() {
  await pet.loadMemories()
  const p = pet.state.personality
  form.name = p.name
  form.tone = p.tone
  form.greeting = p.greeting
  form.encourage = [...(p.encourage || [])]
  showSettings.value = true
}

function addEncourage() {
  if (form.encourage.length < 10) form.encourage.push('')
}

function removeEncourage(idx) {
  form.encourage.splice(idx, 1)
}

function saveSettings() {
  const name = form.name.trim()
  if (!name) return
  pet.setPersonality({
    name,
    tone: form.tone.trim(),
    greeting: form.greeting.trim(),
    encourage: form.encourage.map((e) => e.trim()).filter(Boolean),
  })
  showSettings.value = false
}

/* ---------------- 长期记忆管理 ---------------- */

function startEdit(m) {
  editingId.value = m.id
  editingText.value = m.content
}

function cancelEdit() {
  editingId.value = 0
  editingText.value = ''
}

async function saveMemory(id) {
  const text = editingText.value.trim()
  if (!text) return
  const ok = await pet.updateMemory(id, text)
  if (ok) {
    ElMessage.success('记好了')
    cancelEdit()
  } else {
    ElMessage.error('没存上，再试一次？')
  }
}

async function removeMemory(id) {
  try {
    await ElMessageBox.confirm('删掉这条记忆后，小航就不再记得这件事了，确定？', '删除记忆', {
      confirmButtonText: '删掉',
      cancelButtonText: '算了',
      type: 'warning',
    })
  } catch (e) {
    return // 用户取消
  }
  const ok = await pet.deleteMemory(id)
  if (ok) ElMessage.success('忘掉了')
  else ElMessage.error('没删掉，再试一次？')
}
</script>

<style scoped>
.pet-console {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 46;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(14px) saturate(1.4);
  -webkit-backdrop-filter: blur(14px) saturate(1.4);
  border: 1px solid #e3e6f0;
  border-radius: 999px;
  /* 双层影：近投影收形 + 远环境影托底，比单层更"浮" */
  box-shadow:
    0 4px 12px rgba(40, 50, 90, 0.10),
    0 14px 32px rgba(40, 50, 90, 0.10);
  width: 320px;
  max-width: calc(100vw - 48px);
  transition: border-color 0.25s ease, box-shadow 0.25s ease;
}

/* 输入聚焦：整条控制条响应，边框与光晕轻轻点亮 */
.pet-console:focus-within {
  border-color: #c3b8fc;
  box-shadow:
    0 4px 12px rgba(40, 50, 90, 0.10),
    0 14px 32px rgba(124, 108, 248, 0.16),
    0 0 0 3px rgba(124, 108, 248, 0.10);
}

/* 收起态：整条退成一颗圆形按钮，圆形本身由 .pet-expand 绘制 */
.pet-console.is-collapsed {
  width: 54px;
  height: 54px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  justify-content: center;
}

.pet-console.is-collapsed:focus-within {
  box-shadow: none;
}

.pet-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 14px;
  color: #2a2d45;
  padding: 6px 10px;
}

.pet-input::placeholder {
  color: #6b7280;
}

.pet-send {
  border: none;
  background: linear-gradient(135deg, #8f7ffb 0%, #3b6ee5 55%, #6a5ce8 100%);
  color: #fff;
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 13px;
  cursor: pointer;
  box-shadow: 0 3px 10px rgba(124, 108, 248, 0.32);
  transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.15s ease;
}

.pet-send:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 5px 14px rgba(124, 108, 248, 0.42);
  filter: brightness(1.05);
}

.pet-send:active:not(:disabled) {
  transform: translateY(0) scale(0.96);
  box-shadow: 0 2px 6px rgba(124, 108, 248, 0.3);
}

.pet-send:disabled {
  background: #c5c0e8;
  box-shadow: none;
  cursor: not-allowed;
}

.pet-focus {
  border: 1px solid #e3e6f0;
  background: #fff;
  color: #6b7080;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.pet-focus:hover {
  border-color: #cfd4e8;
  color: #4a4e6b;
  transform: translateY(-1px);
}

.pet-focus.on {
  border-color: #0f9d8a;
  color: #0f9d8a;
  background: #eafaf7;
}

.pet-focus.on:hover {
  border-color: #0f9d8a;
  color: #0f9d8a;
}

.pet-config {
  border: none;
  background: transparent;
  color: #6b7280;
  cursor: pointer;
  font-size: 16px;
  padding: 4px 6px;
  border-radius: 6px;
  transition: color 0.2s, background 0.2s, transform 0.15s ease;
}

.pet-config:hover {
  color: #3b6ee5;
  background: #f0eefc;
}

.pet-config:active {
  transform: rotate(24deg);
}

.encourage-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.encourage-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

.encourage-row :deep(.el-input) {
  flex: 1;
}

.encourage-hint {
  font-size: 11px;
  color: #6b7280;
  margin-top: 2px;
}

.memories-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.memories-empty {
  font-size: 12px;
  color: #6b7280;
}

.memories-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #4a4e6b;
  line-height: 1.5;
}

.memories-text {
  flex: 1;
  min-width: 0;
  word-break: break-all;
}

.memories-ops {
  display: inline-flex;
  gap: 4px;
  flex-shrink: 0;
}

.memories-btn {
  border: none;
  background: transparent;
  color: #6b7280;
  cursor: pointer;
  font-size: 12px;
  padding: 1px 5px;
  border-radius: 6px;
  transition: color 0.15s, background 0.15s;
}

.memories-btn:hover {
  color: #3b6ee5;
  background: #f0eefc;
}

.memories-btn.is-danger:hover {
  color: #e05a4f;
  background: #fdeeee;
}

/* ---------- 窄屏折叠入口 ---------- */
.pet-expand {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 54px;
  height: 54px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: linear-gradient(135deg, #8f7ffb 0%, #3b6ee5 58%, #1951c3 100%);
  color: #fff;
  cursor: pointer;
  box-shadow:
    0 4px 10px rgba(40, 50, 90, 0.12),
    0 12px 26px rgba(59, 110, 229, 0.28);
  transition: transform 180ms ease, box-shadow 180ms ease;
}

.pet-expand svg {
  width: 23px;
  height: 23px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.pet-expand-ai {
  position: absolute;
  top: -3px;
  right: -3px;
  display: grid;
  place-items: center;
  min-width: 20px;
  height: 20px;
  padding: 0 4px;
  border-radius: 999px;
  background: #fff;
  color: #1951c3;
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.18);
}

.pet-expand:hover {
  transform: translateY(-2px) scale(1.03);
  box-shadow:
    0 6px 14px rgba(40, 50, 90, 0.16),
    0 16px 32px rgba(59, 110, 229, 0.36);
}

.pet-expand:active {
  transform: scale(0.97);
}

.pet-collapse {
  position: absolute;
  top: -9px;
  right: -7px;
  z-index: 2;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid #e3e6f0;
  border-radius: 50%;
  background: #fff;
  color: #6b7080;
  box-shadow: 0 3px 10px rgba(15, 23, 42, 0.12);
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
}

.pet-collapse:hover {
  border-color: #cfd4e8;
  color: #3b6ee5;
}

@media (max-width: 1023px) {
  .pet-console {
    right: 12px;
    bottom: max(12px, env(safe-area-inset-bottom));
    width: min(360px, calc(100vw - 24px));
    max-width: none;
    padding: 7px;
    flex-wrap: wrap;
    border-radius: 18px;
  }

  .pet-console.is-collapsed {
    width: 54px;
    height: 54px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: transparent;
    box-shadow: none;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }

  .pet-console.is-collapsed:focus-within {
    box-shadow: none;
  }

  .pet-console.is-collapsed .pet-expand {
    width: 54px;
    height: 54px;
  }

  /* iOS 聚焦输入框时字号 <16px 会自动放大页面 */
  .pet-input {
    flex: 1 1 120px;
    font-size: 16px;
  }

  .pet-send,
  .pet-focus {
    min-height: 40px;
  }

  .pet-config {
    min-width: 34px;
    min-height: 34px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .pet-expand {
    transition: none;
  }

  .pet-expand:hover,
  .pet-expand:active {
    transform: none;
  }
}
</style>
