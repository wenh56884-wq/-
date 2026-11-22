<template>
  <div class="pet-pad" @pointerdown.stop>
    <div class="pad-head">
      <span class="pad-title">让{{ name }}跑个腿</span>
      <button class="pad-close" type="button" aria-label="收起" @click="$emit('close')">×</button>
    </div>

    <div class="pad-chips">
      <button
        v-for="cmd in commands"
        :key="cmd.key"
        class="pad-chip"
        type="button"
        @click="$emit('run', cmd)"
      >
        {{ cmd.label }}
      </button>
    </div>

    <form class="pad-input" @submit.prevent="submit">
      <input
        ref="inputEl"
        v-model="text"
        type="text"
        maxlength="24"
        placeholder="比如：带我去成绩单"
        aria-label="告诉小航要做什么"
      />
      <button type="submit" :disabled="!text.trim()">走起</button>
    </form>

    <div class="pad-foot">
      <button class="pad-link" type="button" @click="$emit('ask')">有问题？问 AI →</button>
    </div>
  </div>
</template>

<script setup>
// 宠物的「跑腿面板」：贴在宠物头顶，点一条指令它就自己走过去把入口点开。
import { nextTick, onMounted, ref } from 'vue'

defineProps({
  commands: { type: Array, default: () => [] },
  // 宠物名字：跟着用户自定义的人格走，别写死
  name: { type: String, default: '小航' }
})

const emit = defineEmits(['run', 'submit', 'ask', 'close'])

const text = ref('')
const inputEl = ref(null)

function submit() {
  const value = text.value.trim()
  if (!value) return
  emit('submit', value)
  text.value = ''
}

onMounted(async () => {
  await nextTick()
  inputEl.value?.focus({ preventScroll: true })
})
</script>

<style scoped>
.pet-pad {
  position: absolute;
  right: 0;
  bottom: calc(100% + 10px);
  width: 262px;
  padding: 10px 12px 8px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(20, 40, 90, 0.08);
  box-shadow: 0 12px 32px rgba(16, 32, 64, 0.18);
  z-index: 3;
  animation: pad-in 160ms ease-out;
}

@keyframes pad-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.pad-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.pad-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2a44;
}

.pad-close {
  border: 0;
  background: transparent;
  color: #8a93a6;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}

.pad-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 132px;
  overflow-y: auto;
}

.pad-chip {
  border: 1px solid rgba(124, 108, 248, 0.26);
  background: rgba(124, 108, 248, 0.06);
  color: #46417a;
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease, transform 120ms ease;
}

.pad-chip:hover {
  background: rgba(124, 108, 248, 0.14);
  border-color: rgba(124, 108, 248, 0.48);
  transform: translateY(-1px);
}

.pad-input {
  display: flex;
  gap: 6px;
  margin-top: 10px;
}

.pad-input input {
  flex: 1;
  min-width: 0;
  height: 30px;
  padding: 0 9px;
  border-radius: 8px;
  border: 1px solid rgba(20, 40, 90, 0.14);
  font-size: 12px;
  color: #1f2a44;
  outline: none;
}

.pad-input input:focus {
  border-color: #3b6ee5;
  box-shadow: 0 0 0 2px rgba(124, 108, 248, 0.16);
}

.pad-input button {
  height: 30px;
  padding: 0 12px;
  border: 0;
  border-radius: 8px;
  background: linear-gradient(135deg, #8f7ffb 0%, #3b6ee5 100%);
  color: #fff;
  font-size: 12px;
  cursor: pointer;
  transition: transform 120ms ease, filter 120ms ease;
}

.pad-input button:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.05);
}

.pad-input button:disabled {
  opacity: 0.45;
  cursor: default;
}

.pad-foot {
  margin-top: 6px;
  text-align: right;
}

.pad-link {
  border: 0;
  background: transparent;
  color: #3b6ee5;
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}

.pad-link:hover {
  text-decoration: underline;
}
</style>
