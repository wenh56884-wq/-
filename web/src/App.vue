<template>
  <!-- 全站中文 locale：不再用 app.use(ElementPlus) 整包注册，改由 ConfigProvider 提供 -->
  <el-config-provider :locale="zhCn">
    <router-view v-slot="{ Component }">
      <Transition name="qh-page" mode="out-in">
        <component :is="Component" />
      </Transition>
    </router-view>
    <!-- 宠物全局陪伴层：跨路由常驻。桌面固定左下角，点身体会回应，
         点头顶 "AI" 角标打开右侧助手抽屉；移动端缩到 64px 且不接收点击
         （避免压住按钮），滚动时淡出。登录页与 AI 助手页不渲染：
         登录页会挡住「开始使用」，助手页本身就是全屏对话工作台。 -->
    <template v-if="showPet">
      <PetSprite
        ref="petRef"
        :size="petSize"
        :edge="petEdge"
        :mood="pet.state.mood"
        badge="AI"
        :poses="petPoses"
        :dimmed="assistantOpen || petHidden"
        @click="onPetClick"
        @badge-click="openAssistant"
      >
        <PetBubble
          :text="pet.state.bubbleText"
          :max-width="petSize < 150 ? 168 : 240"
          @hidden="pet.clearBubble"
        />
      </PetSprite>
      <PetConsole />
    </template>
  </el-config-provider>
</template>

<script setup>
// App 只做路由出口 + 全局宠物陪伴层：宠物层不随路由切换消失，正是"陪伴"的体现。
import { watch, ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import PetSprite from './components/PetSprite.vue'
import PetBubble from './components/PetBubble.vue'
import PetConsole from './components/PetConsole.vue'
import petSideImg from './assets/pet/whale-side.webp'
import petFrontImg from './assets/pet/whale-front.webp'
import { usePet } from './composables/usePet'
import { useAssistant } from './composables/useAssistant'

const route = useRoute()
// 助手页本身就是一个全屏对话工作台，再叠一个宠物聊天入口只会抢焦点；
// 登录页也被排除（未登录时宠物接口全部 401，且会挡住登录按钮）。
const showPet = computed(
  () => route.path !== '/login' && !route.path.endsWith('/assistant')
)

const pet = usePet()
const petRef = ref(null)
const { open: assistantOpen, ask: openAssistant } = useAssistant()

// 窄屏宠物缩到 64px（与右下角 AI 入口同量级）：208px 会压住正文、筛选卡和统计数字。
// 桌面 156px：208px 时立绘几乎占满侧栏底部、压住 AI 问法区的收尾，
// 也把注意力从导航上抢走。缩到 156 后它退成“陪伴层”，仍能看清表情。
const petSize = ref(window.innerWidth <= 1023 ? 56 : 156)
const petEdge = ref(window.innerWidth <= 1023 ? 6 : 20)
// 手机上滚动时先让宠物淡出，停止滚动 900ms 再回来，避免它一直盖住列表底部。
const petHidden = ref(false)
let scrollTimer = null

function syncPetSize() {
  const compact = window.innerWidth <= 1023
  petSize.value = compact ? 56 : 156
  petEdge.value = compact ? 6 : 20
  if (!compact) petHidden.value = false
}

function onScroll() {
  if (window.innerWidth > 1023) return
  petHidden.value = true
  clearTimeout(scrollTimer)
  scrollTimer = setTimeout(() => {
    petHidden.value = false
  }, 900)
}

onMounted(() => {
  syncPetSize()
  window.addEventListener('resize', syncPetSize, { passive: true })
  window.addEventListener('scroll', onScroll, { passive: true })
})

onBeforeUnmount(() => {
  clearTimeout(scrollTimer)
  window.removeEventListener('resize', syncPetSize)
  window.removeEventListener('scroll', onScroll)
})

// 姿态：待机侧视，说话正视（组件内置定时器到点回待机）
const petPoses = { idle: petSideImg, talk: petFrontImg }

// 气泡出现/变化时，让宠物切到说话姿态
watch(
  () => pet.state.bubbleText,
  (text) => {
    if (text) petRef.value?.speak(text)
  }
)

// 点宠物：说问候或随机鼓励（陪伴感，不弹助手抽屉）
function onPetClick() {
  pet.markInteract()
  pet.onPetClick()
}
</script>
