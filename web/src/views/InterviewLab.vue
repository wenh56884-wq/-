<!-- 复盘实验室：把一场面试的结果接回课程 / 成绩 / 同辈，七个工位放在一页。
     最前面是「总览」——先把六个工具串成一条结论，再让人挑工具。 -->
<template>
  <div class="lab">
    <header class="lab-head">
      <div class="lab-id">
        <h2 class="lab-title">复盘实验室</h2>
        <p class="lab-sub">投之前查差什么，面之后查为什么，再学会像面试官一样看人。</p>
      </div>
      <div class="lab-meta">
        <span class="meta-num">{{ finished.length }}</span>
        <span class="meta-label">场已完成</span>
      </div>
    </header>

    <nav class="lab-tabs" role="tablist" aria-label="实验室工位">
      <button v-for="t in tabs" :key="t.key" class="lab-tab" :class="{ on: tab === t.key }"
              type="button" role="tab" :aria-selected="tab === t.key" @click="switchTab(t.key)">
        {{ t.label }}
      </button>
    </nav>

    <div v-show="tab === 'overview'" class="pane">
      <LabOverview @go="onJump" />
    </div>

    <div v-show="tab === 'panel'" class="pane">
      <div class="picker">
        <span class="picker-label">选择已完成的一场面试</span>
        <el-select v-model="sid" placeholder="选一场" style="width: 320px" :loading="loading"
                   @change="onPick">
          <el-option v-for="s in finished" :key="s['编号']"
                     :label="`${s['岗位名称'] || '通用面试'} · ${String(s['完成时间'] || s['创建时间'] || '').slice(0, 10)} · ${s['总分'] ?? '—'} 分`"
                     :value="s['编号']" />
        </el-select>
        <button class="picker-go" type="button" @click="onJump('practice')">去答新的一场 →</button>
      </div>

      <template v-if="sid">
        <RoundtableView :session-id="sid" />
        <div class="grid2">
          <AttributionView :session-id="sid" />
          <PeerBench :session-id="sid" />
        </div>
      </template>
      <div v-else class="empty">
        <div class="empty-icon">◎</div>
        <p>还没有已完成的面试。先答完一场，这里才会长出三位面试官的争执与你的失分落点。</p>
        <button class="empty-cta" type="button" @click="onJump('practice')">去实战演练 →</button>
      </div>
    </div>

    <div v-show="tab === 'ready'" class="pane">
      <ReadinessView />
    </div>

    <div v-show="tab === 'passport'" class="pane">
      <PassportView :refresh-key="passportKey" />
    </div>

    <div v-show="tab === 'voice'" class="pane">
      <ExpressionLab />
    </div>

    <div v-show="tab === 'group'" class="pane">
      <GroupRoom />
    </div>

    <div v-show="tab === 'judge'" class="pane">
      <CalibrationView />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import http from '../api/http'
import AttributionView from '../components/lab/AttributionView.vue'
import CalibrationView from '../components/lab/CalibrationView.vue'
import ExpressionLab from '../components/lab/ExpressionLab.vue'
import GroupRoom from '../components/lab/GroupRoom.vue'
import LabOverview from '../components/lab/LabOverview.vue'
import PassportView from '../components/lab/PassportView.vue'
import PeerBench from '../components/lab/PeerBench.vue'
import ReadinessView from '../components/lab/ReadinessView.vue'
import RoundtableView from '../components/lab/RoundtableView.vue'

const emit = defineEmits(['practice'])

const tabs = [
  { key: 'overview', label: '总览' },
  { key: 'panel', label: '圆桌评审' },
  { key: 'ready', label: '岗位就绪' },
  { key: 'passport', label: '能力护照' },
  { key: 'voice', label: '表达力' },
  { key: 'group', label: '群面' },
  { key: 'judge', label: '当面试官' }
]
const tab = ref('overview')
const sid = ref(null)
const history = ref([])
const loading = ref(true)
const passportKey = ref(0)

const finished = computed(() => history.value.filter((s) => s['状态'] === 'finished'))

function switchTab(key) {
  tab.value = key
  // 首次进入护照时拉一次，之后按 key 刷新
  if (key === 'passport') passportKey.value += 1
}

// 总览里的「下一步」可能指向实战演练（不属于本实验室的工位），
// 那就交给外面的板块导航去切，不要在实验室里硬塞一个假 Tab。
function onJump(key) {
  if (key === 'practice') {
    emit('practice')
    return
  }
  if (!tabs.some((t) => t.key === key)) return
  switchTab(key)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function onPick() {
  // 切换场次后各卡片自行重拉
}

onMounted(async () => {
  try {
    const { data } = await http.get('/interview/history/me')
    history.value = data?.items || []
    if (finished.value.length) sid.value = finished.value[0]['编号']
  } catch (e) {
    history.value = []
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* 深色控制台：整站是浅色，这里刻意做成一块「数据台」，
   和上面的浅色二级导航形成明确分区，而不是一条黑边贴在白顶栏下面。 */
.lab {
  margin: 16px 24px 40px;
  /* 撑到接近满屏：内容短的工位（群面 / 当面试官）如果只露出一小块深色，
     下面接一大片浅底，会像页面被截断；铺满才像一块「工作台」。 */
  min-height: calc(100vh - 178px);
  padding: 22px 22px 26px;
  border: 1px solid #1b2534;
  border-radius: 14px;
  background:
    radial-gradient(620px 260px at 8% -6%, rgba(37, 99, 235, 0.16), transparent 68%),
    radial-gradient(520px 240px at 96% 0%, rgba(13, 148, 136, 0.1), transparent 70%),
    linear-gradient(180deg, #0b1220 0%, #0d1117 46%, #0a0f18 100%);
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.16);
  color: #e5e7eb;
}

.lab-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
}

.lab-title {
  margin: 0 0 4px;
  font-size: 22px;
  font-weight: 680;
  letter-spacing: -0.01em;
  color: #f8fafc;
}

.lab-sub {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: #94a3b8;
}

.lab-meta {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.55);
}

.meta-num {
  font-size: 24px;
  font-weight: 750;
  line-height: 1;
  color: #fff;
  font-variant-numeric: tabular-nums;
}

.meta-label {
  font-size: 11.5px;
  color: #94a3b8;
}

/* 工位切换：深底分段控件，选中态用靛蓝实底 + 轻微发光 */
.lab-tabs {
  display: flex;
  gap: 3px;
  margin-top: 16px;
  padding: 4px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 12px;
  background: rgba(8, 13, 22, 0.72);
  overflow-x: auto;
  scrollbar-width: none;
}

.lab-tabs::-webkit-scrollbar {
  display: none;
}

.lab-tab {
  flex: 0 0 auto;
  padding: 8px 15px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: #9ca3af;
  font-family: inherit;
  font-size: 13px;
  font-weight: 550;
  white-space: nowrap;
  cursor: pointer;
  transition: color 160ms ease, background-color 160ms ease, box-shadow 160ms ease;
}

.lab-tab:hover {
  color: #e5e7eb;
  background: rgba(148, 163, 184, 0.1);
}

.lab-tab.on {
  color: #fff;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.32);
}

.pane {
  margin-top: 18px;
}

.picker {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.picker-label {
  font-size: 12.5px;
  color: #94a3b8;
}

.picker-go {
  margin-left: auto;
  padding: 6px 12px;
  border: 1px solid rgba(96, 165, 250, 0.32);
  border-radius: 9px;
  background: rgba(37, 99, 235, 0.14);
  color: #bfdbfe;
  font-family: inherit;
  font-size: 12.5px;
  cursor: pointer;
}

.picker-go:hover {
  background: rgba(37, 99, 235, 0.26);
  color: #fff;
}

.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 16px;
}

.empty {
  padding: 64px 24px;
  text-align: center;
  border: 1px dashed rgba(148, 163, 184, 0.22);
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.4);
  color: #94a3b8;
}

.empty-icon {
  margin-bottom: 10px;
  font-size: 34px;
  color: #1e293b;
}

.empty p {
  margin: 0 auto 14px;
  max-width: 520px;
  font-size: 13px;
  line-height: 1.7;
}

.empty-cta {
  padding: 7px 16px;
  border: 0;
  border-radius: 9px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}

/* Element Plus 在下拉里是浅色，浮层不受 scoped 影响，这里只调触发框 */
.lab :deep(.el-select__wrapper) {
  background: rgba(15, 23, 42, 0.6);
  box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.2) inset;
}

.lab :deep(.el-select__placeholder),
.lab :deep(.el-select__selected-item) {
  color: #cbd5e1;
  font-size: 12.5px;
}

@media (max-width: 1023px) {
  .lab {
    margin: 12px 16px 32px;
    min-height: calc(100vh - 154px);
    padding: 18px 14px 20px;
    border-radius: 16px;
  }

  .lab-title {
    font-size: 19px;
  }

  .lab-tab {
    padding: 8px 13px;
    min-height: 36px;
  }

  .grid2 {
    grid-template-columns: 1fr;
  }

  .picker-go {
    margin-left: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lab-tab {
    transition: none;
  }
}
</style>
