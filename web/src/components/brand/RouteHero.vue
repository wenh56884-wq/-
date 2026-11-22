<template>
  <section class="route-hero">
    <div class="route-hero__content">
      <div class="route-hero__copy">
        <p v-if="eyebrow" class="route-hero__eyebrow">{{ eyebrow }}</p>
        <h2 class="route-hero__title">{{ title }}</h2>
        <p v-if="desc" class="route-hero__desc">{{ desc }}</p>
        <div v-if="$slots.actions" class="route-hero__actions">
          <slot name="actions" />
        </div>
      </div>

      <div v-if="stats.length" class="route-hero__stats">
        <div
          v-for="stat in stats"
          :key="stat.label"
          class="route-stat"
          :class="stat.tone ? `route-stat--${stat.tone}` : ''"
        >
          <span class="route-stat__label">{{ stat.label }}</span>
          <b class="route-stat__value">
            {{ stat.value }}<small v-if="stat.suffix">{{ stat.suffix }}</small>
          </b>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
// RouteHero：教师/学生首页的「本页结论」面板。
//
// 设计口径（2026-11-19 统一）：
// 原先是深色渐变横幅 + 漂移光斑 + 胶囊 eyebrow + 扫光动画 + 白字按钮，
// 学生首页、教师首页、校园洞察、职业搜索各有一块，且色相各不相同（墨绿/藏青/金色）。
// 结果是「每个页面都像另一个产品的落地页」，与浅色工作区、靛蓝品牌色互相打架。
// 现在改为与全站卡片同一族的说明面板：白底 + 1px 中性边 + 12px 圆角，
// 标题用墨色、指标用等宽数字、语义色只作用在数值上。信息不变，装饰去掉。

defineProps({
  tone: { type: String, default: 'teacher' }, // 保留兼容：仅影响未指定 tone 的指标配色
  eyebrow: { type: String, default: '' },
  title: { type: String, default: '' },
  desc: { type: String, default: '' },
  // [{ label, value, suffix?, tone?: 'red'|'orange'|'yellow'|'good'|'unknown' }]
  stats: { type: Array, default: () => [] }
})
</script>

<style scoped>
.route-hero {
  padding: 20px 24px;
  border: 1px solid #e7eaf1;
  border-radius: 14px;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
}

.route-hero__content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  flex-wrap: wrap;
  width: 100%;
}

.route-hero__copy {
  flex: 1 1 420px;
  min-width: 0;
}

/* 期次信息（如「本学期结论 · 2025-2026-2」）：普通小字，不再做成胶囊标签，
   也不加字距——它不是装饰性的眉标，是一行数据注解。 */
.route-hero__eyebrow {
  margin: 0 0 6px;
  color: var(--cf-faint);
  font-size: 12.5px;
  font-weight: 500;
}

.route-hero__title {
  margin: 0;
  max-width: 62ch;
  color: var(--cf-ink);
  font-size: 21px;
  font-weight: 680;
  line-height: 1.5;
  letter-spacing: -0.02em;
  text-wrap: balance;
  /* 允许在空格/标点处换行，但不把「预警」这类中文词拆成两行 */
  word-break: keep-all;
  overflow-wrap: anywhere;
}

.route-hero__desc {
  margin: 6px 0 0;
  max-width: 68ch;
  color: var(--qh-text-sub);
  font-size: 13.5px;
  line-height: 1.7;
}

.route-hero__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

/* 指标：浅灰底小方片，数值等宽，语义色只染色数字 */
.route-hero__stats {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.route-stat {
  min-width: 104px;
  padding: 10px 14px;
  border: 1px solid #ecf0f6;
  border-radius: 10px;
  background: #f8f9fc;
}

.route-stat__label {
  display: block;
  color: var(--cf-faint);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
}

.route-stat__value {
  display: block;
  margin-top: 2px;
  color: var(--cf-ink);
  font-size: 24px;
  font-weight: 680;
  line-height: 1.25;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.route-stat__value small {
  margin-left: 2px;
  font-size: 12px;
  font-weight: 500;
  color: var(--cf-faint);
}

.route-stat--red .route-stat__value { color: #c0392b; }
.route-stat--orange .route-stat__value { color: #b45f06; }
.route-stat--yellow .route-stat__value { color: #9a6a05; }
.route-stat--good .route-stat__value { color: #0f7a5a; }
.route-stat--unknown .route-stat__value { color: var(--cf-mid); }

@media (max-width: 1023px) {
  .route-hero {
    padding: 18px 18px;
  }

  .route-hero__title {
    font-size: 19px;
  }

  .route-stat {
    flex: 1 1 96px;
  }
}

/* 手机端：按钮竖排等宽、三个指标三等分。
   之前 flex-wrap 让第二个按钮换行、第三个指标独占一行，视觉上参差不齐。 */
@media (max-width: 560px) {
  .route-hero {
    padding: 16px;
  }

  .route-hero__content {
    gap: 14px;
  }

  .route-hero__actions {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }

  .route-hero__actions :slotted(*) {
    width: 100%;
    margin-left: 0;
  }

  .route-hero__stats {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    width: 100%;
  }

  .route-stat {
    min-width: 0;
    padding: 9px 10px;
  }

  .route-stat__label {
    overflow: hidden;
    font-size: 11.5px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .route-stat__value {
    font-size: 19px;
  }
}
</style>
