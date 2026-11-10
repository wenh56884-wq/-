# CareerFieldCanvas

启航前端改版的装饰性 3D 主视觉。组件只表现“学业、能力、方向、岗位”之间的关系，不接收、计算或生成任何业务数值。

## 依赖

```json
{
  "three": "0.170.0"
}
```

Three.js 通过动态 `import('three')` 加载。建议只在登录页或学生首页使用，不要让所有数据页静态依赖该组件。

## Props

| 属性 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `variant` | `'full' \| 'compact'` | `'full'` | 全屏 Hero 或小尺寸主视觉 |
| `paused` | `Boolean` | `false` | 页面抽屉、弹窗打开或标签隐藏时暂停动画 |
| `quality` | `'auto' \| 'high' \| 'low'` | `'auto'` | `auto` 会根据触摸设备降低像素比和细节 |
| `interactive` | `Boolean` | `true` | 是否允许鼠标产生轻微视差 |

## 使用方式

```vue
<script setup>
import { defineAsyncComponent, ref } from 'vue'

const CareerFieldCanvas = defineAsyncComponent(
  () => import('../components/career-field/CareerFieldCanvas.vue')
)

const interactionPaused = ref(false)
</script>

<template>
  <CareerFieldCanvas
    variant="full"
    :paused="interactionPaused"
    quality="auto"
  />
</template>
```

## 行为

- WebGL 或 Three.js 加载失败时自动显示 CSS/SVG 风格回退。
- 支持 `prefers-reduced-motion`，开启后只渲染静帧。
- 通过 `IntersectionObserver` 在组件离开视口后暂停渲染。
- 页面进入后台时停止有效绘制。
- 手机和触摸设备自动降低抗锯齿、像素比、粒子和环细分。
- 组件销毁时释放几何体、材质和 WebGL 上下文相关资源。

## 业务约束

- 不得把随机数注入场景后当作真实分数、排名、人数或比例展示。
- 需要显示业务数据时，由页面把引擎结果放在组件外侧的 HUD 中。
- 不修改 API 请求、身份注入或租户隔离逻辑。
- 中文源码统一 UTF-8。
