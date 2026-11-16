<template>
  <router-view v-slot="{ Component }">
    <Transition name="qh-page" mode="out-in">
      <component :is="Component" />
    </Transition>
  </router-view>
  <!-- 宠物全局陪伴层：跨路由常驻，固定驻留在左下角、不移动，会主动说话；
       点击身体会蹦跳回应，点它头顶的 "AI" 角标 = 打开右侧助手抽屉。
       登录页不渲染：宠物固定在左下角会压住「开始使用」按钮挡住登录入口
       （实测 .enter-btn 命中 pet-img），且未登录时 personality/state/memories
       全部 401，陪伴层没有意义。 -->
  <template v-if="showPet">
    <PetSprite
      ref="petRef"
      :size="208"
      :mood="pet.state.mood"
      badge="AI"
      :poses="petPoses"
      :dimmed="assistantOpen"
      @click="onPetClick"
      @badge-click="openAssistant"
    >
      <PetBubble :text="pet.state.bubbleText" @hidden="pet.clearBubble" />
    </PetSprite>
    <PetConsole />
  </template>
</template>

<script setup>
// App 只做路由出口 + 全局宠物陪伴层：宠物层不随路由切换消失，正是"陪伴"的体现。
import { watch, ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import PetSprite from './components/PetSprite.vue'
import PetBubble from './components/PetBubble.vue'
import PetConsole from './components/PetConsole.vue'
import whaleSidePng from './assets/pet/whale-side.png'
import whaleFrontPng from './assets/pet/whale-front.png'
import { usePet } from './composables/usePet'
import { useAssistant } from './composables/useAssistant'

const route = useRoute()
const showPet = computed(() => route.path !== '/login')

const pet = usePet()
const petRef = ref(null)
const { open: assistantOpen, ask: openAssistant } = useAssistant()

// 姿态：待机侧视，说话正视（组件内置定时器到点回待机）
const petPoses = { idle: whaleSidePng, talk: whaleFrontPng }

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
