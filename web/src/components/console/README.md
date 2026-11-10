# Console primitives

供 Medusa 式启航前端复用的无业务组件：

| 组件 | 用途 |
|---|---|
| `ConsoleCard.vue` | 浅青毛玻璃技术卡片，支持标题、编号、操作区和 footer |
| `ConsoleStat.vue` | 单个确定性指标，不负责计算或格式化业务值 |
| `StatusPill.vue` | 带文字的状态 pill，颜色不是唯一状态提示 |

统一依赖以下 CSS 变量；未定义时组件内有安全回退值：

```css
--cf-line
--cf-ink
--cf-mid
--cf-faint
--cf-coral
--cf-teal
--cf-teal-soft
--cf-warning
--cf-danger
--cf-radius
--cf-shadow
```

使用示例：

```vue
<ConsoleCard index="01" eyebrow="ACADEMIC SIGNAL" title="本学期预警">
  <template #actions>
    <StatusPill tone="active" label="数据正常" />
  </template>

  <div class="stat-grid">
    <ConsoleStat
      label="风险分"
      :value="warning.risk_score"
      unit="SCORE"
      code="EXACT"
      tone="warning"
      :detail="warning.term"
    />
  </div>
</ConsoleCard>
```

业务约束：

- `ConsoleStat.value` 只接收现有接口或引擎返回的值。
- 不在组件内部做四舍五入、排名、比例或人数计算。
- 卡片不得写死身份、租户或接口请求。
