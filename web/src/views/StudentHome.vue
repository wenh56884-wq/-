<template>
  <div ref="pageRoot" class="page bento-page">
    <FreshmanGuide
      :open="freshmanGuideOpen"
      :grade="guide.grade || '大一'"
      @complete="finishFreshmanGuide(true)"
      @skip="finishFreshmanGuide(false)"
    />
    <div class="bento-grid">
    <!-- 航线页头：一句话结论 + 关键指标 + 主按钮。结论只组织引擎返回的数值，不做任何推断 -->
    <RouteHero
      class="bento-span-4 qh-reveal qh-hero"
      :style="{ '--qh-index': 0 }"
      tone="student"
      :eyebrow="`本学期结论 · ${warning.term || term || '-'}`"
      :title="heroConclusion"
      desc="让启航智能体帮你看懂预警、匹配岗位、拆解能力差距；所有数值由确定性引擎实算并回查。"
      :stats="[
        { label: '预警等级', value: levelText(warning.level), tone: levelTone },
        { label: '风险分', value: warning.risk_score ?? '—' },
        { label: '已匹配岗位', value: items.length, suffix: '个' }
      ]"
    >
      <template #actions>
        <el-button type="primary" @click="goJobs">查看岗位</el-button>
        <el-button @click="goWarning">查看预警</el-button>
        <el-button @click="askAI('我这学期的学业预警情况怎么样？')">问启航智能体</el-button>
      </template>
    </RouteHero>

    <el-alert class="trust-bar bento-span-4 qh-reveal" :style="{ '--qh-index': 1 }" type="success" :closable="false" show-icon
      title="所有数值由确定性引擎实算，未通过校验的数字不会展示" />

    <div class="live-bar bento-span-4 qh-reveal" :style="{ '--qh-index': 2 }">
      <span>数据于 {{ clock.ago(lastLoadAt) }}</span>
      <el-switch v-model="autoRefresh" size="small" active-text="30 秒自动刷新" />
      <el-button size="small" :loading="warningLoading || recLoading" @click="reloadAll">立即刷新</el-button>
      <button
        class="bell-btn"
        type="button"
        :class="{ 'has-new': unreadCnt > 0 }"
        :title="unreadCnt ? `${unreadCnt} 条新竞赛通知` : '暂无新竞赛通知'"
        @click="openNotices"
      >
        <svg viewBox="0 0 24 24" class="bell-icon" aria-hidden="true">
          <path d="M12 4a5 5 0 0 0-5 5v3l-1.5 2.5h13L17 12V9a5 5 0 0 0-5-5z" />
          <path d="M10 17.5a2 2 0 0 0 4 0" />
        </svg>
        <span>竞赛通知</span>
        <span v-if="unreadCnt" class="bell-badge">{{ unreadCnt > 99 ? '99+' : unreadCnt }}</span>
      </button>
    </div>

    <section class="twin-panel bento-span-4 qh-reveal" :style="{ '--qh-index': 3 }" aria-labelledby="twin-title">
      <div class="twin-visual" aria-hidden="true">
        <div class="twin-visual-top"><span>QH / DIGITAL TWIN</span><i></i></div>
        <div class="twin-stage">
          <svg class="twin-sphere" viewBox="0 0 240 200" role="presentation">
            <defs>
              <radialGradient id="twinGlow" cx="50%" cy="46%" r="55%">
                <stop offset="0" stop-color="#8ff0ff" stop-opacity=".55" />
                <stop offset=".38" stop-color="#4a8cf7" stop-opacity=".3" />
                <stop offset="1" stop-color="#172b66" stop-opacity="0" />
              </radialGradient>
              <radialGradient id="twinCoreFill" cx="38%" cy="32%" r="72%">
                <stop offset="0" stop-color="#ffffff" />
                <stop offset=".45" stop-color="#c9ecff" />
                <stop offset="1" stop-color="#6aa6ff" />
              </radialGradient>
              <linearGradient id="twinStroke" x1="0" y1="0" x2="1" y2="1">
                <stop stop-color="#9df1ff" />
                <stop offset="1" stop-color="#7c8fff" />
              </linearGradient>
              <radialGradient id="twinSweepR" cx="50%" cy="50%" r="50%">
                <stop offset="0" stop-color="#7ce4ee" stop-opacity=".55" />
                <stop offset="1" stop-color="#7ce4ee" stop-opacity="0" />
              </radialGradient>
              <path id="twinOrbA" d="M 42 96 a 78 25 0 1 0 156 0 a 78 25 0 1 0 -156 0" fill="none" />
              <path id="twinOrbB" d="M 64 96 a 56 46 0 1 1 112 0 a 56 46 0 1 1 -112 0" fill="none" />
              <path id="twinOrbC" d="M 38 96 a 82 82 0 1 0 164 0 a 82 82 0 1 0 -164 0" fill="none" />
            </defs>

            <!-- 中心辉光 -->
            <circle class="twin-glow" cx="120" cy="96" r="94" fill="url(#twinGlow)" />

            <!-- 星尘：三组不同相位闪烁 -->
            <g class="twin-dust d1">
              <circle cx="46" cy="42" r="1.5" /><circle cx="188" cy="60" r="1.2" />
              <circle cx="72" cy="158" r="1.4" /><circle cx="196" cy="142" r="1.1" />
            </g>
            <g class="twin-dust d2">
              <circle cx="30" cy="112" r="1.1" /><circle cx="150" cy="24" r="1.5" />
              <circle cx="102" cy="178" r="1.2" /><circle cx="214" cy="98" r="1.3" />
            </g>
            <g class="twin-dust d3">
              <circle cx="58" cy="76" r="1" /><circle cx="176" cy="172" r="1.3" />
              <circle cx="132" cy="12" r="1.1" /><circle cx="16" cy="66" r="1" />
            </g>

            <!-- 雷达扫描扇面 -->
            <g class="twin-radar">
              <path d="M120 96 L120 12 A84 84 0 0 1 193 54 Z" fill="url(#twinSweepR)" />
              <path d="M120 96 L120 12" stroke="#a5f3fc" stroke-opacity=".55" stroke-width="1.2" />
            </g>

            <!-- 外圈虚线光环（慢旋） -->
            <g class="twin-halo">
              <circle cx="120" cy="96" r="90" fill="none" stroke="#7c9dff" stroke-opacity=".5" stroke-dasharray="2 10" />
              <circle cx="120" cy="96" r="97" fill="none" stroke="#59e0c8" stroke-opacity=".18" />
            </g>

            <!-- 球面经纬网 -->
            <g class="twin-wire" stroke="#8deaff" fill="none">
              <ellipse cx="120" cy="96" rx="78" ry="25" stroke-opacity=".2" />
              <ellipse cx="120" cy="96" rx="56" ry="46" stroke-opacity=".14" />
              <ellipse cx="120" cy="96" rx="26" ry="78" stroke-opacity=".16" />
              <ellipse cx="120" cy="96" rx="58" ry="82" stroke-opacity=".1" />
              <path d="M69 78c28 20 74 20 102 0M69 114c28-20 74-20 102 0" stroke-opacity=".12" />
            </g>

            <!-- 陀螺仪双环（异速反向旋转） -->
            <g class="twin-ring ring-a">
              <ellipse cx="120" cy="96" rx="78" ry="25" fill="none" stroke="url(#twinStroke)" stroke-opacity=".85" stroke-width="1.4" />
            </g>
            <g class="twin-ring ring-b">
              <ellipse cx="120" cy="96" rx="56" ry="46" fill="none" stroke="#59e0c8" stroke-opacity=".6" stroke-width="1.2" />
            </g>

            <!-- 扩散脉冲（双相位） -->
            <circle class="twin-pulse p1" cx="120" cy="96" r="27" fill="none" stroke="#9fe6ff" />
            <circle class="twin-pulse p2" cx="120" cy="96" r="27" fill="none" stroke="#59e0c8" />

            <!-- 能量核心 -->
            <circle cx="120" cy="96" r="29" fill="rgba(88,140,255,.24)" />
            <circle cx="120" cy="96" r="21" fill="url(#twinCoreFill)" fill-opacity=".8" />
            <circle class="twin-core-halo" cx="120" cy="96" r="21" fill="none" stroke="#d9f4ff" stroke-opacity=".7" />
            <circle class="twin-core-dot" cx="120" cy="96" r="5.5" fill="#ffffff" fill-opacity=".9" />

            <!-- 沿轨道运行的粒子 -->
            <circle class="twin-mote" r="4" fill="#a5f3fc">
              <animateMotion dur="26s" repeatCount="indefinite"><mpath href="#twinOrbC" /></animateMotion>
            </circle>
            <circle class="twin-mote" r="3" fill="#7ce4ee">
              <animateMotion dur="26s" begin="-8.67s" repeatCount="indefinite"><mpath href="#twinOrbC" /></animateMotion>
            </circle>
            <circle class="twin-mote" r="3.5" fill="#8affd9">
              <animateMotion dur="13s" repeatCount="indefinite"><mpath href="#twinOrbB" /></animateMotion>
            </circle>

            <!-- 随轨道漂移的三枚数据标签 -->
            <g class="twin-chip">
              <animateMotion dur="26s" repeatCount="indefinite"><mpath href="#twinOrbC" /></animateMotion>
              <rect x="-18" y="-11" width="36" height="22" rx="11" fill="rgba(11,26,58,.9)" stroke="#7ce4ee" stroke-opacity=".8" />
              <text y="4" text-anchor="middle" fill="#d8f2ff" font-size="10">学业</text>
            </g>
            <g class="twin-chip">
              <animateMotion dur="26s" begin="-8.67s" repeatCount="indefinite"><mpath href="#twinOrbC" /></animateMotion>
              <rect x="-18" y="-11" width="36" height="22" rx="11" fill="rgba(11,26,58,.9)" stroke="#7ce4ee" stroke-opacity=".8" />
              <text y="4" text-anchor="middle" fill="#d8f2ff" font-size="10">岗位</text>
            </g>
            <g class="twin-chip">
              <animateMotion dur="26s" begin="-17.33s" repeatCount="indefinite"><mpath href="#twinOrbC" /></animateMotion>
              <rect x="-18" y="-11" width="36" height="22" rx="11" fill="rgba(9,32,52,.9)" stroke="#59e0c8" stroke-opacity=".8" />
              <text y="4" text-anchor="middle" fill="#d6fff2" font-size="10">生涯</text>
            </g>

            <!-- 十字准轴（虚线流动） -->
            <path class="twin-axis" d="M28 96h20m144 0h40M120 6v16m0 146v18" stroke="#7ce4ee" stroke-opacity=".45" />
          </svg>
        </div>
        <div class="twin-visual-bottom"><strong>STUDENT MODEL</strong><span>学业 · 生涯 · 岗位</span></div>
      </div>
      <div class="twin-content">
        <div class="twin-heading">
          <div>
            <p class="twin-eyebrow">QIHANG · PERSONAL DIGITAL TWIN</p>
            <h2 id="twin-title">我的数字孪生</h2>
            <p class="twin-intro">把已核验的学业状态、生涯目标与岗位推荐汇成一份可更新的个人镜像。</p>
          </div>
          <span class="twin-live"><i></i> {{ warningLoading || recLoading ? '同步中' : '数据已连接' }}</span>
        </div>
        <div class="twin-facts" aria-label="数字孪生画像摘要">
          <div class="twin-fact">
            <span>学业状态</span>
            <strong>{{ levelText(warning.level) }}</strong>
            <small>{{ warning.term || term || '等待学期数据' }}</small>
          </div>
          <div class="twin-fact">
            <span>风险分</span>
            <strong>{{ warning.risk_score ?? '—' }}</strong>
            <small>来自学业预警引擎</small>
          </div>
          <div class="twin-fact">
            <span>生涯方向</span>
            <strong>{{ guide.direction?.name || (guide.needs_intent ? '待选择' : '待同步') }}</strong>
            <small>{{ directionSourceText }}</small>
          </div>
          <div class="twin-fact">
            <span>岗位匹配</span>
            <strong>{{ items.length }}<em> 个</em></strong>
            <small>当前推荐结果</small>
          </div>
        </div>
        <div class="twin-foot">
          <span>镜像依据：学业预警 · 生涯目标 · 岗位推荐</span>
          <el-button class="twin-ask" @click="askAI('请基于我的数字孪生画像中已同步的学业状态、生涯方向和岗位推荐，帮我解读当前情况，并给出下一步建议；缺失的信息请明确说明，不要推测。')">
            让智能体解读画像 <span aria-hidden="true">↗</span>
          </el-button>
        </div>
      </div>
    </section>

    <el-card ref="guideCard" v-loading="guideLoading" shadow="never"
      class="guide-card bento-span-2 qh-reveal"
      :style="{ '--qh-index': 4 }">
      <template #header>
        <div class="guide-head">
          <span class="card-title" style="margin: 0">生涯规划</span>
          <el-tag size="small" effect="plain">{{ guide.grade || '年级未知' }}</el-tag>
          <el-tag v-if="guide.intent" size="small" type="success" effect="dark">{{ guide.intent }}</el-tag>
          <el-tag v-if="guide.needs_intent" size="small" type="warning" effect="dark">待选方向</el-tag>
        </div>
      </template>

      <!-- 新生引导：只要后端判定 needs_intent（大一且未选方向），每次进首页都会走到这里 -->
      <template v-if="guide.needs_intent">
        <div class="onboard">
          <div class="onboard-head">
            <span class="onboard-badge">新生引导 · 第一步</span>
            <h3 class="onboard-title">先选定毕业方向，系统才会给你四年规划</h3>
            <p class="onboard-sub">
              你现在是{{ guide.grade || '大一' }}，还没选方向。选定后，下面的四年规划、
              岗位推荐和竞赛清单都会按这个方向来算。
            </p>
          </div>

          <div class="onboard-pick">
            <button v-for="opt in guide.options || []" :key="opt.value" type="button"
              class="pick-card" :class="{ 'is-on': selectedIntent === opt.value }"
              :aria-pressed="selectedIntent === opt.value"
              @click="selectedIntent = opt.value">
              <span class="pick-name">{{ opt.label }}</span>
              <span class="pick-desc">{{ opt.desc }}</span>
            </button>
          </div>

          <div class="onboard-foot">
            <el-button type="primary" size="large" :loading="intentSaving"
              :disabled="!selectedIntent" @click="saveIntent">
              保存方向并生成规划
            </el-button>
            <span class="onboard-hint">
              {{ selectedIntentDesc || '选一个方向，这里会显示它的说明' }}
            </span>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="guide-headline">{{ guide.headline }}</div>
        <div class="guide-meta">
          <span>方向：<b>{{ guide.direction?.name || '待探索' }}</b></span>
          <span class="muted">（{{ directionSourceText }}）</span>
          <el-button link type="primary" @click="showIntentPicker = !showIntentPicker">
            {{ showIntentPicker ? '收起' : '调整目标' }}
          </el-button>
        </div>

        <div v-if="showIntentPicker" class="intent-row">
          <el-radio-group v-model="selectedIntent">
            <el-radio-button v-for="opt in guide.options || []" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </el-radio-button>
          </el-radio-group>
          <el-button type="primary" :loading="intentSaving" :disabled="!selectedIntent" @click="saveIntent">
            保存目标
          </el-button>
        </div>

        <CareerRoute
          :all-steps="guide.all_steps || []"
          :steps="guide.steps || []"
          :stage="guide.stage || 'unknown'"
          :grade="guide.grade || ''"
          :direction="guide.direction?.name || ''"
        />
        <!-- 底部补齐：本周行动（取规划第一步前 3 条）+ 两个落地 CTA，左侧不留空槽 -->
        <div v-if="weekActions.length" class="week-box">
          <div class="week-head">
            <span class="week-title">本周行动</span>
            <span class="week-sub">摘自「{{ guide.steps[0]?.阶段 || '第一步' }}」</span>
          </div>
          <label v-for="(action, i) in weekActions" :key="i" class="week-item">
            <input type="checkbox" class="week-check" />
            <span class="week-text">{{ action }}</span>
          </label>
        </div>

        <div class="guide-cta">
          <router-link to="/student/academic" class="guide-cta-btn">
            去看成绩单<span class="cta-arrow" aria-hidden="true">↗</span>
          </router-link>
          <router-link to="/student/opportunity" class="guide-cta-btn">
            去看岗位库<span class="cta-arrow" aria-hidden="true">↗</span>
          </router-link>
        </div>

        <div class="engine-line">
          规划引擎 {{ guide.engine_version || '-' }} · {{ guide.note }}
          <span v-if="guideTip" class="err">{{ guideTip }}</span>
        </div>
      </template>

      <!-- 选课联动：引擎事实直引、零 LLM 调用；新生 onboarding 分支也可见 -->
      <div v-if="guide.elective" class="elective-link-box">
        <div class="elective-link-head">
          <span class="elective-link-title">选课联动 · 技能缺口</span>
          <el-tag
            v-if="guide.elective.window"
            size="small"
            :type="guide.elective.window.state === 'open' ? 'success' : (guide.elective.window.state === 'before' ? 'warning' : 'info')"
          >
            {{ guide.elective.window.state === 'open' ? '选课窗口开放中' : (guide.elective.window.state === 'before' ? '选课窗口未开放' : '选课窗口已结束') }}
          </el-tag>
        </div>
        <template v-if="guide.elective.available">
          <div v-if="(guide.elective.recommendations || []).length" class="elective-chips">
            <span v-for="(rec, i) in guide.elective.recommendations" :key="rec.name" class="elective-chip">
              <span class="elective-idx">{{ i + 1 }}</span>
              {{ rec.name }} · {{ rec.credit }}学分 · 得分 {{ rec.score }}
            </span>
          </div>
          <div v-if="guide.elective.gened?.applicable && (guide.elective.gened?.uncovered || []).length" class="elective-gened">
            <span class="elective-gened-label">{{ guide.elective.gened.required_cohort }}级通识必修模块尚未覆盖：</span>
            <el-tag v-for="m in guide.elective.gened.uncovered" :key="m" type="danger" size="small">{{ m }}</el-tag>
          </div>
          <div v-if="guide.elective.credits" class="elective-credits">
            毕业最低总学分 {{ guide.elective.credits.total_required }} · 已修 {{ guide.elective.credits.earned }} · 已选 {{ guide.elective.credits.elected }} · 剩余 {{ guide.elective.credits.remaining }} 学分
          </div>
          <div class="elective-link-cta">
            <router-link to="/student/academic?tab=elective" class="guide-cta-btn">
              让智能体规划选课<span class="cta-arrow" aria-hidden="true">↗</span>
            </router-link>
            <a
              v-if="guide.elective.entry?.url"
              :href="guide.elective.entry.url"
              target="_blank"
              rel="noopener"
              class="elective-entry-link"
            >教务系统选课入口 ↗</a>
          </div>
        </template>
        <div v-else class="elective-note">{{ guide.elective.note }}</div>
      </div>
    </el-card>

    <el-card ref="warningCard" v-loading="warningLoading" shadow="never" class="info-card bento-span-2 qh-reveal" :style="{ '--qh-index': 5 }">
      <div class="card-title">本人信息</div>
      <el-descriptions class="profile-descriptions" :column="3" border size="small">
        <el-descriptions-item label="学号">{{ warning.student_no || '-' }}</el-descriptions-item>
        <el-descriptions-item label="姓名">{{ warning.name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="学期">{{ warning.term || '-' }}</el-descriptions-item>
        <el-descriptions-item label="预警等级">
          <el-tag :type="levelType(warning.level)" effect="dark">{{ levelText(warning.level) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="风险分">
          <span class="risk-score"><count-number :value="warning.risk_score" /></span>
        </el-descriptions-item>
        <el-descriptions-item label="可用指标">
          {{ warning.coverage ?? '-' }} 项
          <span v-if="warning.missing?.length" class="missing">（缺失：{{ warning.missing.join('、') }}）</span>
        </el-descriptions-item>
      </el-descriptions>

      <div class="card-title reason-title">预警归因</div>
      <el-empty v-if="warningLoading === false && !(warning.reasons || []).length" description="本学期暂无触发项" />
      <div v-else class="reason-line">
        <el-tag v-for="(item, index) in warning.reasons || []" :key="index" type="danger" effect="plain">
          {{ item }}
        </el-tag>
      </div>

      <div class="card-title reason-title">本人指标</div>
      <el-descriptions class="profile-descriptions profile-metrics" :column="2" border size="small">
        <el-descriptions-item label="均分">{{ metric('gpa') }}</el-descriptions-item>
        <el-descriptions-item label="成绩下滑">{{ metric('gpa_drop') }}</el-descriptions-item>
        <el-descriptions-item label="出勤率">{{ metricRate('attendance_rate') }}</el-descriptions-item>
        <el-descriptions-item label="班级排名百分位">{{ metric('class_rank_pct') }}</el-descriptions-item>
      </el-descriptions>
      <div class="engine-line">
        预警引擎 {{ warning.engine_version || '-' }} · 画像版本 {{ warning.calc_version || '-' }}
        <span v-if="warningTip" class="err">{{ warningTip }}</span>
      </div>
    </el-card>

    <el-card shadow="never" class="profile-recommendations bento-span-2 qh-reveal" :style="{ '--qh-index': 6 }">
      <template #header>
        <div class="profile-rec-head">
          <div>
            <span class="card-title">为你匹配的岗位</span>
            <span class="profile-rec-sub">从推荐结果先看两条，点开查看理由与差距</span>
          </div>
          <el-button link type="primary" @click="goJobs">查看全部岗位 <span aria-hidden="true">↗</span></el-button>
        </div>
      </template>
      <el-empty v-if="!recLoading && !items.length" description="当前没有可展示的岗位推荐" />
      <div v-else class="profile-rec-list" v-loading="recLoading">
        <button v-for="(item, index) in profileJobs" :key="item.job_id ?? item.id ?? item.title"
          class="profile-job" type="button" @click="openDetail(item)">
          <span class="profile-job-main">
            <span class="profile-job-label">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="profile-job-copy">
              <span class="profile-job-title">{{ item.title }}</span>
              <span class="profile-job-meta">{{ item.company || '企业未标注' }}<template v-if="item.city"> · {{ item.city }}</template></span>
              <span v-if="item.gap_items?.length" class="profile-job-gap">待补：{{ item.gap_items[0] }}</span>
              <span v-else class="profile-job-hit">{{ item.hit_items?.[0] || item.advice || '推荐理由详见岗位详情' }}</span>
            </span>
          </span>
          <span class="profile-job-score"><b>{{ fmtScore(item.final_score) }}</b>匹配分<span class="profile-job-arrow" aria-hidden="true">↗</span></span>
        </button>
      </div>
      <div class="engine-line">推荐引擎 {{ recs.engine_version || '-' }} · 只展示接口已返回的推荐结果</div>
    </el-card>

    <el-card shadow="never" class="quick-card bento-span-4 qh-reveal" :style="{ '--qh-index': 7 }">
      <template #header>
        <div class="card-title" style="margin: 0">快捷入口</div>
      </template>
      <div class="quick-grid">
        <router-link v-for="q in quickLinks" :key="q.to" :to="q.to" class="quick-item">
          <span class="bento-icon qh-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path :d="q.icon" /></svg>
          </span>
          <span class="qh-arrow" aria-hidden="true">↗</span>
          <span class="quick-name">{{ q.name }}</span>
          <span class="quick-desc">{{ q.desc }}</span>
        </router-link>
      </div>
    </el-card>

    <!-- 流程申请：AI 助手里触发的「需要审批」工作流，提交后不是黑盒——
         状态、教师驳回意见、执行结果都在这里闭环。 -->
    <el-card v-if="wfRuns.length || wfAvailable.length" shadow="never"
             class="wf-card bento-span-4 qh-reveal" :style="{ '--qh-index': 7 }">
      <template #header>
        <div class="wf-head">
          <span class="card-title" style="margin: 0">流程申请</span>
          <span class="wf-hint">点下面的流程即可提交；需教师审批，通过后才执行（只用你自己的数据）</span>
        </div>
      </template>
      <div v-if="wfRuns.length" class="wf-list">
        <div v-for="r in wfRuns" :key="r.id" class="wf-item">
          <div class="wf-item-main">
            <span class="wf-name">{{ r.name }}</span>
            <el-tag :type="wfTone(r.status)" size="small">{{ r.status_text }}</el-tag>
            <span v-if="r.error" class="wf-err" :title="r.error">{{ r.error }}</span>
          </div>
          <div class="wf-item-sub">
            <span>提交于 {{ fmtTs(r.submitted_at) }}</span>
            <span v-if="r.steps?.length">执行：{{ r.steps.map(x => x.title).join(' → ') }}</span>
            <span v-if="r.decided?.action === 'reject'" class="wf-reject">
              教师意见：{{ r.decided.comment || '（未填写）' }}
            </span>
            <span v-else-if="r.decided?.action === 'approve' && r.decided.comment" class="wf-ok">
              教师意见：{{ r.decided.comment }}
            </span>
          </div>
        </div>
      </div>

      <!-- 可申请的流程：没有这块，卡片只对「已经玩过的人」可见，新学生永远发现不了 -->
      <div v-if="wfAvailable.length" class="wf-apply" :class="{ 'has-runs': wfRuns.length }">
        <span class="wf-apply-label">可申请的流程</span>
        <button v-for="w in wfAvailable" :key="w.id" type="button" class="wf-chip"
                :title="w.description || ''" @click="applyWorkflow(w)">
          <b>{{ w.name }}</b>
          <span v-if="w.description" class="wf-chip-desc">{{ w.description }}</span>
        </button>
      </div>
    </el-card>

    <el-card shadow="never" class="rec-card bento-span-4 qh-reveal" :style="{ '--qh-index': 7 }">
      <template #header>
        <div class="rec-head">
          <span class="card-title" style="margin: 0">岗位推荐</span>
          <el-input-number v-model="topN" :min="1" :max="20" size="small" />
          <el-button type="primary" size="small" :loading="recLoading" @click="loadRecommendations">
            刷新推荐
          </el-button>
        </div>
      </template>

      <el-empty v-if="!recLoading && !items.length" :description="recTip || '暂无推荐结果'" />
      <!-- 紧凑小格子：自适应列数 + 入场逐格浮现；点开看详情与行动清单 -->
      <div class="rec-grid">
        <div
          v-for="(item, index) in items"
          :key="item.job_id"
          class="rec-cell"
          role="button"
          tabindex="0"
          :style="{ animationDelay: `${Math.min(index, 8) * 45}ms` }"
          @click="openDetail(item)"
          @keyup.enter="openDetail(item)"
        >
          <div class="cell-top">
            <span class="cell-index">{{ index + 1 }}</span>
            <span class="cell-score" :title="`匹配度 ${fmtScore(item.final_score)}`">
              {{ fmtScore(item.final_score) }}
            </span>
          </div>
          <div class="cell-title" :title="item.title">{{ item.title }}</div>
          <div class="cell-meta" :title="`${item.company || ''} · ${item.city || '城市不限'}`">
            {{ item.company || '公司未填' }} · {{ item.city || '城市不限' }}
          </div>
          <div class="cell-salary">{{ salaryText(item) }} 元/月</div>
          <div class="cell-tags">
            <span v-for="(t, i) in (item.hit_items || []).slice(0, 2)" :key="'h' + i" class="mini-tag hit">
              ✓ {{ t }}
            </span>
            <span v-for="(t, i) in (item.gap_items || []).slice(0, 1)" :key="'g' + i" class="mini-tag gap">
              △ {{ t }}
            </span>
            <span
              v-if="(item.hit_items || []).length + (item.gap_items || []).length > 3"
              class="mini-tag more"
              :title="[...(item.hit_items || []), ...(item.gap_items || [])].join('、')"
            >+{{ (item.hit_items || []).length + (item.gap_items || []).length - 3 }}</span>
          </div>
          <div class="cell-advice" :title="item.advice || ''">建议：{{ item.advice || '—' }}</div>
          <div v-if="item.peer_count" class="cell-peer" :title="item.reasons?.potential || ''">
            同段位 {{ item.peer_count }} 人关注 · 协同 {{ item.cf_score }}
          </div>
        </div>
      </div>
      <div class="engine-line">
        推荐引擎 {{ recs.recommend_version || '-' }} · 候选池 {{ recs.candidate_cnt ?? '-' }} 条
        <span v-if="recs.note" class="err">{{ recs.note }}</span>
      </div>
    </el-card>
    </div>

    <!-- 岗位详情抽屉：完整打分 + 建议 + 需要做的 + 该参加的比赛 -->
    <el-drawer v-model="detailOpen" :size="drawerSize" direction="rtl" :with-header="false">
      <div v-if="active" class="detail-shell drawer-panel">
        <header class="detail-head">
          <div class="detail-head-text">
            <div class="detail-title" :title="active.title">{{ active.title }}</div>
            <div class="detail-sub">{{ active.company || '公司未填' }} · {{ active.city || '城市不限' }}</div>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭详情" @click="detailOpen = false">
            <svg viewBox="0 0 24 24" class="ico"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </header>

        <div class="detail-body">
          <div class="detail-kpis">
            <div class="kpi">
              <div class="kpi-label">综合匹配</div>
              <div class="kpi-value">{{ fmtScore(active.final_score) }}</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">薪资区间</div>
              <div class="kpi-value small">{{ salaryText(active) }} 元/月</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">成绩门槛</div>
              <div class="kpi-value small">{{ active.min_gpa ?? '-' }} 分</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">同伴热度</div>
              <div class="kpi-value small">{{ active.peer_count ?? '—' }} 人</div>
            </div>
            <div class="kpi">
              <div class="kpi-label">岗位方向</div>
              <div class="kpi-value small">{{ active.direction || '-' }}</div>
            </div>
          </div>

          <div class="sec-title">{{ dimTitle }}</div>
          <div class="dim-list">
            <div v-for="(value, key) in active.dims || {}" :key="key" class="dim-row">
              <span class="dim-name">{{ DIM_TEXT[key] || key }}</span>
              <span class="dim-bar"><i :style="{ width: `${Math.round(Number(value || 0) * 100)}%` }" /></span>
              <span class="dim-value">{{ fmtScore(value) }}</span>
            </div>
          </div>

          <div v-if="active.reasons" class="sec-title">三段式理由（内容 / 课程链 / 同伴证据）</div>
          <div v-if="active.reasons" class="reason-block">
            <div class="reason-row"><span class="rk">内容匹配</span><span>{{ active.reasons.knowledge }}</span></div>
            <div class="reason-row"><span class="rk">课程链</span><span>{{ active.reasons.skill }}</span></div>
            <div class="reason-row"><span class="rk">同伴证据</span><span>{{ active.reasons.potential }}</span></div>
            <div v-if="active.cf_score != null" class="reason-row">
              <span class="rk">协同权重</span><span>{{ active.cf_score }}（召回B，0.7×内容 + 0.3×协同）</span>
            </div>
          </div>

          <div class="sec-title">为什么推荐给你</div>
          <ul class="ul-hit">
            <li v-for="(t, i) in active.hit_items || []" :key="'h' + i">{{ t }}</li>
            <li v-if="!(active.hit_items || []).length">暂无可归因的命中项</li>
          </ul>

          <div class="sec-title">还差什么</div>
          <ul class="ul-gap">
            <li v-for="(t, i) in active.gap_items || []" :key="'g' + i">{{ t }}</li>
            <li v-if="!(active.gap_items || []).length">当前没有检测到明显缺口</li>
          </ul>

          <div class="sec-title">需要做的</div>
          <ol class="ol-action">
            <li v-for="(t, i) in active.action_items || []" :key="'a' + i">{{ t }}</li>
            <li v-if="!(active.action_items || []).length">{{ active.advice || '保持当前节奏即可' }}</li>
          </ol>

          <div class="sec-title">
            该参加的比赛
            <el-radio-group v-model="track" size="small" class="track-switch" @change="loadCompetitions">
              <el-radio-button value="就业">就业</el-radio-button>
              <el-radio-button value="考公">考公</el-radio-button>
            </el-radio-group>
          </div>
          <div v-if="compLoading" class="comp-loading">正在按你的方向筛选官方竞赛…</div>
          <div v-else-if="!(competitions.length)" class="comp-loading">暂无匹配的竞赛</div>
          <div v-else class="comp-list">
            <div v-for="c in competitions" :key="c.competition_id" class="comp-cell">
              <div class="comp-top">
                <span class="comp-cat" :class="'cat-' + String(c.category || '').toLowerCase()">
                  {{ c.category }} 类
                </span>
                <span class="comp-name" :title="c.name">{{ c.name }}</span>
              </div>
              <div class="comp-org">{{ c.org_unit }}</div>
              <div class="comp-why">{{ c.match_reason }}</div>
              <div v-if="c.reward" class="comp-reward">认定/奖励：{{ c.reward }}</div>
              <a class="comp-link" :href="c.source_url" target="_blank" rel="noopener">
                查看官方通知 →
              </a>
            </div>
          </div>
          <div class="engine-line">
            竞赛库 {{ comps.engine_version || '-' }} · 候选 {{ comps.candidate_cnt ?? '-' }} 项 ·
            来源：重庆财经学院教务处
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 竞赛通知中心：官方一发布即推送 -->
    <el-drawer v-model="noticeOpen" :size="drawerSize" direction="rtl" :with-header="false">
      <div class="detail-shell drawer-panel">
        <header class="detail-head">
          <div class="detail-head-text">
            <div class="detail-title">竞赛通知</div>
            <div class="detail-sub">重庆财经学院教务处发布，系统定期自动同步</div>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭通知" @click="noticeOpen = false">
            <svg viewBox="0 0 24 24" class="ico"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </header>
        <div class="detail-body">
          <el-empty v-if="!notices.length" description="暂无新通知" />
          <div v-for="n in notices" :key="n.title" class="notice-cell">
            <div class="notice-date">{{ n.published_at }}</div>
            <div class="notice-title">{{ n.title }}</div>
            <a class="comp-link" :href="n.url" target="_blank" rel="noopener">打开原文 →</a>
          </div>
          <div class="engine-line">已读水位：{{ lastReadAt || '未读' }}</div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs'

import http from '../api/http'
import router from '../router'
import CareerRoute from '../components/career/CareerRoute.vue'
import FreshmanGuide from '../components/FreshmanGuide.vue'
import RouteHero from '../components/brand/RouteHero.vue'
import { useClock } from '../composables/useSystemStatus'
import { useReveal } from '../composables/useReveal'

// 入场编排：只给卡片加 opacity/transform 渐显，不改任何数据与布局尺寸
const pageRoot = ref(null)
const { refresh } = useReveal(pageRoot)

function queueReveal() {
  nextTick(refresh)
}

const LEVEL_TEXT = { red: '红色预警', orange: '橙色预警', yellow: '黄色预警', none: '正常', unknown: '数据不足' }
const LEVEL_TYPE = { red: 'danger', orange: 'warning', yellow: 'warning', none: 'success', unknown: 'info' }

const autoRefresh = ref(false)
const lastLoadAt = ref(null)
let timer = null
const clock = useClock()

const term = ref('2025-2026-2')
const topN = ref(5)
const guideLoading = ref(false)
const guideTip = ref('')
const intentSaving = ref(false)
const guide = ref({})
const selectedIntent = ref('')
const showIntentPicker = ref(false)
const freshmanGuideOpen = ref(false)
const guideCard = ref(null)
const warningLoading = ref(false)
const recLoading = ref(false)
const warningTip = ref('')
const recTip = ref('')
const warning = ref({})
const recs = ref({})
const items = ref([])
const FRESHMAN_GUIDE_STORAGE_VERSION = 'v1'

// 快捷入口：6 个刚好填满 2 列网格，与侧栏可见页面一一对应（不新增不存在的路由）
const QUICK_LINKS = [
  {
    to: '/student/academic',
    name: '成绩单',
    desc: '每学年课程成绩',
    icon: 'M7 3h7l4 4v14H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM14 3v4h4M9 13h6M9 17h4'
  },
  {
    to: '/student/academic?tab=forecast',
    name: '学业预测',
    desc: '下学期绩点与风险',
    icon: 'M4 18V9M10 18V5M16 18v-6M2 18h20'
  },
  {
    to: '/student/interview',
    name: '模拟面试',
    desc: '简历出题 · 逐题点评',
    icon: 'M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3'
  },
  {
    to: '/student/opportunity',
    name: '岗位库',
    desc: '按方向筛选岗位',
    icon: 'M3 8h18v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8zM9 8V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18'
  },
  {
    to: '/student/opportunity?tab=exams',
    name: '招考信息',
    desc: '考公 / 考编 / 考研',
    icon: 'M12 4l9 4-9 4-9-4 9-4zM5 11v5c0 1.7 3.1 3 7 3s7-1.3 7-3v-5'
  },
  {
    to: '/student/kg',
    name: '知识图谱',
    desc: '专业—课程—岗位',
    icon: 'M6 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM12 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM7.5 7.5l3 5M16.5 7.5l-3 5M8 9h8'
  }
]

const quickLinks = QUICK_LINKS
const warningCard = ref(null)

// Hero 一句话结论：只把引擎返回的等级 / 触发项 / 推荐条数组装成一句话，不产生新数值
const heroConclusion = computed(() => {
  const info = warning.value || {}
  const who = info.name ? `${info.name}，` : ''
  const jobCnt = items.value.length
  if (!info.level) return '本学期预警数据还在计算，稍后可查看完整结论'
  if (info.level === 'none') {
    return `${who}本学期未触发预警项，已按你的画像匹配 ${jobCnt} 个岗位`
  }
  if (info.level === 'unknown') {
    return `${who}本学期可用指标不足，暂不判定等级；已按现有数据匹配 ${jobCnt} 个岗位`
  }
  const reasons = info.reasons || []
  const why = reasons.length ? `触发原因：${reasons.slice(0, 2).join('、')}` : '暂无触发项'
  return `${who}本学期为${levelText(info.level)}，${why}；已匹配 ${jobCnt} 个岗位，优先补齐下方缺口`
})

// 航线页头的等级语义色：none/normal 走「正常」青绿，其他沿用红/橙/黄
const levelTone = computed(() => {
  const level = warning.value?.level
  if (!level || level === 'unknown') return 'unknown'
  if (level === 'none' || level === 'normal' || level === 'green') return 'good'
  return level
})

// 本周行动：直接取规划第一步的前 3 条，缺数据就不渲染这一段（不造数）
const weekActions = computed(() => {
  const first = (guide.value?.steps || [])[0]
  return ((first?.行动) || []).slice(0, 3)
})

// 首页摘要复用岗位推荐接口，不另造完成率/能力分，也不发起新的评分请求
const profileJobs = computed(() => items.value.slice(0, 2))

function goJobs() {
  router.push('/student/opportunity')
}

// 预警明细就在本页，主按钮直接滚过去，而不是把用户带走
// ---------- 流程申请（工作流）----------
// 只取自己发起的记录；教师通过 / 驳回后这里能看到结果与意见
const wfRuns = ref([])
const wfAvailable = ref([])

function wfTone(status) {
  return { pending: 'warning', running: 'primary', success: 'success',
           failed: 'danger', rejected: 'info' }[status] || 'info'
}

function fmtTs(iso) {
  return iso ? String(iso).replace('T', ' ').slice(0, 16) : ''
}

async function loadWfRuns() {
  try {
    const { data } = await http.get('/workflow/my-runs', { params: { limit: 5 } })
    wfRuns.value = data?.items || []
    wfAvailable.value = data?.available || []
  } catch {
    wfRuns.value = []
    wfAvailable.value = []
  }
}

// 点流程 = 在 AI 助手里发出「帮我跑一遍 X」。走同一条链路，不在页面另开接口，
// 保证「页面点的」和「嘴上说的」是同一件事。
async function applyWorkflow(w) {
  try {
    await ElMessageBox.confirm(
      `「${w.name}」会提交给教师审批，通过后才执行，且只读取你自己的数据。`,
      '确认提交申请？',
      { type: 'info', confirmButtonText: '提交申请', cancelButtonText: '再看看' }
    )
  } catch {
    return
  }
  askAI(`帮我跑一遍${w.name}`)
}

function goWarning() {
  const node = warningCard.value?.$el || warningCard.value
  node?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
}

// 让常驻的助手抽屉打开并自动发问：ShellLayout 不在本次改动范围，走窗口事件
function askAI(question) {
  window.dispatchEvent(new CustomEvent('qh:ask-ai', { detail: { question } }))
}

const directionSourceText = computed(() => {
  const map = { 'profile.interest': '来自画像兴趣', intent: '由目标推导', none: '待补充' }
  return map[guide.value?.direction?.source] || '待补充'
})

const selectedIntentDesc = computed(() => {
  const opt = (guide.value?.options || []).find((item) => item.value === selectedIntent.value)
  return opt?.desc || ''
})

function levelText(level) {
  return LEVEL_TEXT[level] || level || '-'
}

function levelType(level) {
  return LEVEL_TYPE[level] || 'info'
}

function metric(key) {
  const value = warning.value?.metrics?.[key]
  return value === null || value === undefined ? '-' : value
}

function metricRate(key) {
  const value = warning.value?.metrics?.[key]
  return value === null || value === undefined ? '-' : `${(Number(value) * 100).toFixed(1)}%`
}

function fmtScore(score) {
  return score === null || score === undefined ? '-' : Number(score).toFixed(4)
}

function salaryText(item) {
  const min = item.salary_min
  const max = item.salary_max
  if (min === null || min === undefined || max === null || max === undefined) return '薪资面议'
  return `${Math.round(Number(min))}-${Math.round(Number(max))}`
}

const DIM_TEXT = {
  major_match: '专业匹配',
  gpa_gate: '成绩门槛',
  skill_cover: '技能覆盖',
  interest_fit: '兴趣方向',
  // 做过软技能测评时后端会在 dims 里多给这两维；没做过则完全回落四维
  soft_skills: '职业素养',
  potential: '发展潜力'
}

// 维度数不固定：有测评数据是六维，否则四维，标题跟着实际维度走
const DIM_CN = ['零', '一', '二', '三', '四', '五', '六', '七']
const dimTitle = computed(() => {
  const n = Object.keys(active.value?.dims || {}).length || 4
  return `${DIM_CN[n] || n} 维打分`
})

// ---- 岗位详情抽屉 ----
const detailOpen = ref(false)
const active = ref(null)
const drawerSize = computed(() => (window.innerWidth < 768 ? '100%' : '480px'))
const track = ref('就业')
const compLoading = ref(false)
const comps = ref({})
const competitions = ref([])

async function openDetail(item) {
  active.value = item
  detailOpen.value = true
  await loadCompetitions()
}

async function loadCompetitions() {
  const item = active.value
  if (!item) return
  compLoading.value = true
  try {
    const { data } = await http.get('/student/competitions', {
      params: { track: track.value, direction: item.direction || '', job_title: item.title || '', limit: 6 }
    })
    comps.value = data || {}
    competitions.value = data?.items || []
  } catch (err) {
    comps.value = {}
    competitions.value = []
    ElMessage.error(err?.response?.data?.detail || '竞赛推荐加载失败')
  } finally {
    compLoading.value = false
  }
}

// ---- 竞赛通知推送 ----
const noticeOpen = ref(false)
const notices = ref([])
const unreadCnt = ref(0)
const lastReadAt = ref('')
let noticeTimer = null

async function loadNotices() {
  try {
    const { data } = await http.get('/student/notices', { params: { limit: 20 } })
    unreadCnt.value = Number(data?.unread_cnt || 0)
    lastReadAt.value = data?.last_read_at || ''
    if (!noticeOpen.value) return
    notices.value = data?.items || []
  } catch {
    unreadCnt.value = 0
  }
}

async function openNotices() {
  noticeOpen.value = true
  await loadNotices()
}

watch(noticeOpen, async (opened) => {
  if (opened) return
  if (!unreadCnt.value) return
  // 关闭通知即视为已读：把水位推到当前时间，之后的新通知才会再提醒
  try {
    await http.post('/student/notices/read')
    unreadCnt.value = 0
    await loadNotices()
  } catch {
    /* 标记失败不影响使用 */
  }
})

async function loadGuide() {
  guideLoading.value = true
  guideTip.value = ''
  try {
    const { data } = await http.get('/career/guide', { params: { term: term.value } })
    guide.value = data || {}
    selectedIntent.value = data?.intent || ''
  } catch (err) {
    guide.value = {}
    guideTip.value = err?.response?.data?.detail || '生涯规划加载失败'
  } finally {
    guideLoading.value = false
    queueReveal()
  }
}

async function saveIntent() {
  const value = String(selectedIntent.value || '').trim()
  if (!value) {
    ElMessage.warning('请先选择目标')
    return
  }
  intentSaving.value = true
  try {
    await http.put('/career/intent', { intent: value })
    ElMessage.success(`已保存目标：${value}`)
    showIntentPicker.value = false
    await loadGuide()
  } catch (err) {
    const detail = err?.response?.data?.detail || '目标保存失败'
    ElMessage.error(detail)
    guideTip.value = detail
  } finally {
    intentSaving.value = false
  }
}

function freshmanGuideStorageKey() {
  const studentNo = localStorage.getItem('qh_student_no') || 'anonymous'
  return `qh_freshman_guide_${FRESHMAN_GUIDE_STORAGE_VERSION}_${studentNo}`
}

function maybeOpenFreshmanGuide() {
  const grade = String(guide.value?.grade || '')
  if (!grade.includes('大一')) return
  if (localStorage.getItem(freshmanGuideStorageKey()) === 'done') return
  freshmanGuideOpen.value = true
}

async function finishFreshmanGuide(scrollToDirection) {
  freshmanGuideOpen.value = false
  try {
    localStorage.setItem(freshmanGuideStorageKey(), 'done')
  } catch {
    /* 浏览器禁用本地存储时仍允许完成引导 */
  }
  if (!scrollToDirection) return
  await nextTick()
  const node = guideCard.value?.$el || guideCard.value
  node?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
}

async function loadWarning() {
  warningLoading.value = true
  warningTip.value = ''
  try {
    const { data } = await http.get('/student/warning', { params: { term: term.value } })
    warning.value = data || {}
  } catch (err) {
    warning.value = {}
    warningTip.value = err?.response?.data?.detail || '预警数据加载失败'
  } finally {
    warningLoading.value = false
  }
}

async function loadRecommendations() {
  recLoading.value = true
  recTip.value = ''
  try {
    const { data } = await http.get('/student/recommendations', {
      params: { term: term.value, top_n: topN.value }
    })
    recs.value = data || {}
    items.value = data?.items || []
    if (!items.value.length) {
      recTip.value = data?.note || '本学期没有可用推荐（成绩或专业数据不足）'
    }
  } catch (err) {
    recs.value = {}
    items.value = []
    recTip.value = err?.response?.data?.detail || '推荐数据加载失败'
    ElMessage.error(recTip.value)
  } finally {
    recLoading.value = false
  }
}

async function reloadAll() {
  // 规划卡不参与 30 秒自动刷新：避免学生正在选择目标时被定时请求重置选项
  await Promise.all([loadWarning(), loadRecommendations()])
  lastLoadAt.value = new Date()
  queueReveal()
}

watch(autoRefresh, (on) => {
  if (timer) clearInterval(timer)
  timer = on ? setInterval(reloadAll, 30000) : null
})

onMounted(async () => {
  queueReveal()
  const guideTask = loadGuide().then(maybeOpenFreshmanGuide)
  const pageTask = Promise.all([reloadAll(), loadNotices(), loadWfRuns()])
  await Promise.all([guideTask, pageTask])
  // 每 60 秒查一次未读：官方发布新通知后，这里会自己亮红点
  noticeTimer = setInterval(loadNotices, 60000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (noticeTimer) clearInterval(noticeTimer)
})
</script>

<style scoped>
/* ---- 流程申请 ---- */
.wf-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}

.wf-hint {
  font-size: 12px;
  color: var(--bento-sub, #6b7280);
}

/* 可申请的流程：一行小胶囊，说明它是什么、点了会发生什么 */
.wf-apply {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.wf-apply.has-runs {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--bento-border, #e4e7ee);
}

.wf-apply-label {
  font-size: 12px;
  color: var(--bento-sub, #6b7280);
}

.wf-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  max-width: 100%;
  padding: 7px 14px;
  border: 1px solid #cfe3df;
  border-radius: 999px;
  background: #f4fbf9;
  color: #0f7a6b;
  font-family: inherit;
  font-size: 12.5px;
  cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease;
}

.wf-chip:hover {
  border-color: #0f9d8a;
  background: #ecf8f5;
}

.wf-chip b {
  font-weight: 600;
  white-space: nowrap;
}

.wf-chip-desc {
  color: #6b8f89;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 420px;
}

@media (max-width: 760px) {
  .wf-chip-desc {
    display: none;
  }
}

.wf-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.wf-item {
  padding: 10px 14px;
  border: 1px solid var(--bento-border, #e4e7ee);
  border-radius: 10px;
  background: #fbfcfe;
}

.wf-item-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.wf-name {
  font-size: 13.5px;
  font-weight: 600;
}

.wf-err {
  font-size: 12px;
  color: #c2604f;
  overflow: hidden;
  max-width: 420px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-item-sub {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12px;
  color: var(--bento-sub, #6b7280);
}

.wf-reject {
  color: #c2604f;
}

.wf-ok {
  color: #0f9d8a;
}

.trust-bar {
  margin-bottom: 0;
  font-weight: 600;
}

.live-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 0;
  font-size: 13.5px;
  color: #5f6672;
  background: #fff;
  border: 1px solid #eef0f5;
  border-radius: 14px;
  padding: 8px 14px;
}

/* 参考站卡片三件套：白卡 + 左上角淡紫图标块 + 右上角 ↗ */
.qh-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  border-radius: 12px;
  background: var(--bento-accent-soft);
  color: var(--bento-accent);
}

.bento-icon svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.qh-arrow {
  font-size: 14px;
  line-height: 1;
  color: #1951c3;
  opacity: 0;
  transform: translate(-2px, 2px);
  transition:
    opacity 180ms var(--bento-ease),
    transform 180ms var(--bento-ease);
}

.quick-item:hover .qh-arrow {
  opacity: 1;
  transform: translate(0, 0);
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.quick-item {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  grid-template-areas:
    'icon name arrow'
    'icon desc arrow';
  align-items: center;
  gap: 3px 12px;
  min-height: 88px;
  padding: 14px 16px;
  border: 1px solid var(--bento-border);
  border-radius: 16px;
  background: #ffffff;
  box-shadow:
    0 1px 2px rgba(16, 24, 40, 0.04),
    0 8px 20px rgba(16, 24, 40, 0.04);
  text-decoration: none;
  transition:
    transform 220ms var(--bento-ease),
    box-shadow 220ms var(--bento-ease),
    border-color 220ms var(--bento-ease);
}

.quick-item:hover {
  transform: translateY(-2px);
  border-color: #baccf0;
  box-shadow:
    0 2px 6px rgba(25, 81, 195, 0.1),
    0 12px 28px rgba(16, 24, 40, 0.07);
}

.quick-item .qh-icon { grid-area: icon; }
.quick-item .qh-arrow { grid-area: arrow; }

.quick-name {
  grid-area: name;
  min-width: 0;
  font-size: 15px;
  font-weight: 650;
  color: var(--bento-text);
}

.quick-desc {
  grid-area: desc;
  min-width: 0;
  font-size: 14px;
  line-height: 1.45;
  color: var(--bento-mute);
}

.guide-card,
.info-card,
.rec-card {
  margin-bottom: 0;
}

/* 生涯规划与右侧信息/摘要在同一行自动对齐：不跨两行，避免右侧只有一行卡片
   时留下结构性空白；内容按自身高度收拢，页脚区块不参与撑高。 */
.guide-card :deep(.el-card__body) {
  display: block;
}

.profile-recommendations,
.profile-descriptions {
  margin-bottom: 0;
}

/* 桌面（4 列栅格）：生涯规划占左列两行，本人信息与岗位摘要占右列两行，
   左右两列高度与信息量同步填充，不留结构性空白。 */
.guide-card {
  grid-row: 1 / span 2;
}

.info-card {
  grid-column: 3 / span 2;
  grid-row: 1;
}

.profile-recommendations {
  grid-column: 3 / span 2;
  grid-row: 2;
}

/* 2 列（平板及小桌面）：左侧生涯规划收窄为单列并占两行，右侧信息与摘要
   各收窄一列，由自动布局依次填充第二列，右列同样不留空槽。 */
@media (max-width: 1180px) and (min-width: 701px) {
  .guide-card {
    grid-column: span 1;
    grid-row: 1 / span 2;
  }

  .info-card,
  .profile-recommendations {
    grid-column: span 1;
  }
}

/* 单列（手机）：三张卡各占一行，顺序为规划 → 本人信息 → 岗位摘要 */
@media (max-width: 700px) {
  .guide-card,
  .info-card,
  .profile-recommendations {
    grid-column: auto;
    grid-row: auto;
  }
}

.profile-rec-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
  flex-wrap: wrap;
}

.profile-rec-sub {
  display: block;
  margin-top: 3px;
  color: var(--qh-text-sub, #5f6672);
  font-size: 12.5px;
}

.profile-rec-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.profile-job {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 8px 12px;
  width: 100%;
  padding: 12px 13px;
  border: 1px solid var(--qh-border, #e4e7ee);
  border-radius: var(--qh-radius-lg, 8px);
  background: #fff;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    transform 180ms var(--bento-ease, ease),
    border-color 180ms var(--bento-ease, ease),
    box-shadow 180ms var(--bento-ease, ease);
}

.profile-job:hover {
  transform: translateY(-2px);
  border-color: #baccf0;
  box-shadow: 0 8px 22px rgba(16, 24, 40, 0.08);
}

.profile-job-main {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr);
  align-items: start;
  gap: 8px;
  min-width: 0;
}

.profile-job-label {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 20px;
  border-radius: 6px;
  background: var(--qh-primary-soft, #e9efff);
  color: var(--qh-primary, #1951c3);
  font-size: 11.5px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.profile-job-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.profile-job-title {
  overflow: hidden;
  color: var(--qh-text, #16181d);
  font-size: 14.5px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-job-meta {
  overflow: hidden;
  color: var(--qh-text-sub, #5f6672);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-job-gap {
  color: #b45309;
  font-size: 12.5px;
  line-height: 1.5;
}

.profile-job-hit {
  color: #59677c;
  font-size: 12.5px;
  line-height: 1.5;
}

.profile-job-score {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  min-width: 56px;
  color: var(--qh-text-muted, #6b7280);
  font-size: 12px;
  white-space: nowrap;
}

.profile-job-score b {
  color: var(--qh-primary, #1951c3);
  font-size: 16px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.profile-job-arrow {
  margin-top: 4px;
  opacity: 0.55;
}

.guide-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.guide-headline {
  font-size: 16px;
  font-weight: 600;
  margin: 4px 0 8px;
}

.guide-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 14px;
  color: #4e5969;
  margin-bottom: 10px;
}

.intent-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 12px;
}

/* 新生引导：大一且未选方向时展示，取代原来那句纯文字提示 */
.onboard {
  padding: 2px 0;
}

.onboard-head {
  margin-bottom: 14px;
}

.onboard-badge {
  display: inline-block;
  margin-bottom: 8px;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--qh-primary-soft, #e9efff);
  color: var(--qh-primary, #1951c3);
  font-size: 13px;
  font-weight: 600;
}

.onboard-title {
  margin: 0 0 6px;
  font-size: 17px;
  font-weight: 650;
  line-height: 1.45;
  color: var(--qh-text, #16181d);
}

.onboard-sub {
  margin: 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--qh-text-sub, #5f6672);
}

.onboard-pick {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.pick-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid var(--qh-border, #e4e7ee);
  border-radius: 12px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 180ms var(--qh-ease, ease),
    box-shadow 180ms ease,
    transform 180ms ease;
}

.pick-card:hover {
  border-color: #baccf0;
  transform: translateY(-1px);
}

.pick-card.is-on {
  border-color: var(--qh-primary, #1951c3);
  background: var(--qh-primary-soft, #e9efff);
  box-shadow: 0 6px 16px rgba(25, 81, 195, 0.14);
}

.pick-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--qh-text, #16181d);
}

.pick-desc {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--qh-text-sub, #5f6672);
}

.onboard-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 16px;
}

.onboard-hint {
  font-size: 13.5px;
  color: var(--qh-text-mute, #9aa1ad);
}

@media (max-width: 560px) {
  .onboard-pick {
    grid-template-columns: 1fr;
  }

  .quick-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .quick-item {
    grid-template-columns: 32px minmax(0, 1fr) auto;
    gap: 3px 8px;
    min-height: 82px;
    padding: 12px 10px;
  }

  .quick-item .bento-icon {
    width: 32px;
    height: 32px;
  }

  .quick-name { font-size: 14px; }
  .quick-desc { font-size: 12.5px; }
}

/* 本周行动：卡片底部占位，内容直接取规划第一步，缺数据则整块不渲染 */
.week-box {
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px dashed var(--bento-border-strong);
}

.week-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}

.week-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--bento-text);
}

.week-sub {
  font-size: 13px;
  color: var(--bento-mute);
}

.week-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 4px 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--bento-sub);
  cursor: pointer;
}

.week-check {
  flex: 0 0 auto;
  width: 15px;
  height: 15px;
  margin: 4px 0 0;
  accent-color: var(--bento-accent);
  cursor: pointer;
}

.week-text {
  min-width: 0;
}

/* 选课联动块：引擎事实直引，智能体规划入口在选课页 */
.elective-link-box {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px dashed var(--bento-border, #dcdfe6);
  border-radius: 12px;
  background: var(--el-fill-color-light);
}

.elective-link-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.elective-link-title {
  font-weight: 700;
}

.elective-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.elective-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 12px;
  font-weight: 600;
}

.elective-idx {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.elective-gened {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.elective-gened-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.elective-credits {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}

.elective-link-cta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.elective-entry-link {
  font-size: 12px;
  color: var(--el-color-primary);
  text-decoration: none;
}

.elective-note {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* 卡片底部两个落地 CTA */
.guide-cta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.guide-cta-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border: 1px solid var(--bento-border);
  border-radius: 999px;
  background: #ffffff;
  color: var(--bento-sub);
  font-size: 14px;
  text-decoration: none;
  transition:
    transform 200ms var(--bento-ease),
    background-color 200ms var(--bento-ease),
    color 200ms var(--bento-ease),
    border-color 200ms var(--bento-ease);
}

.guide-cta-btn:hover {
  transform: translateY(-1px);
  border-color: #baccf0;
  background: var(--bento-accent-soft);
  color: var(--bento-accent);
}

.guide-cta .cta-arrow {
  opacity: 0.6;
}

.muted {
  color: #5f6672;
  font-size: 13.5px;
}

.reason-title {
  margin-top: 12px;
}

.reason-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.risk-score {
  font-size: 18px;
  font-weight: 600;
  color: var(--qh-red);
}

.missing {
  color: #5f6672;
}

.engine-line {
  margin-top: 10px;
  font-size: 13.5px;
  color: #5f6672;
}

.err {
  color: var(--qh-red);
  margin-left: 10px;
}

.rec-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 推荐小格子：改用 flex 等宽铺满——5 张卡在 4 列网格里会在第二行剩 3 个空槽 */
.rec-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.rec-cell {
  flex: 1 1 240px;
  border: 1px solid var(--qh-border);
  border-radius: var(--qh-radius-lg);
  padding: 10px 12px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  animation: cell-in 220ms ease-out both;
  transition: transform 150ms ease, box-shadow 150ms ease;
}

.rec-cell:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(14, 58, 61, 0.08);
}

@keyframes cell-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.cell-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cell-index {
  width: 20px;
  height: 20px;
  line-height: 20px;
  text-align: center;
  border-radius: 8px;
  background: var(--qh-red);
  color: #fff;
  font-size: 12.5px;
}

.cell-score {
  font-size: 14px;
  font-weight: 600;
  color: var(--qh-red);
  font-variant-numeric: tabular-nums;
}

.cell-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--qh-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-meta {
  font-size: 13.5px;
  color: var(--qh-text-sub);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-salary {
  font-size: 14px;
  color: var(--qh-orange);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.cell-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-height: 20px;
}

.mini-tag {
  font-size: 12.5px;
  line-height: 18px;
  padding: 0 6px;
  border-radius: 8px;
  border: 1px solid var(--qh-border);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.mini-tag.hit {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
}

.mini-tag.gap {
  background: #fffbeb;
  border-color: #fde68a;
  color: #b45309;
}

.mini-tag.more {
  background: #eef0f5;
  color: var(--qh-text-sub);
  cursor: help;
}

.cell-peer {
  font-size: 12.5px;
  color: var(--el-color-success);
  margin-top: 2px;
}
.reason-block { font-size: 14px; line-height: 1.7; }
.reason-row { display: flex; gap: 8px; margin: 4px 0; }
.reason-row .rk {
  flex: none; width: 64px; color: var(--el-text-color-secondary); font-size: 13.5px;
}
.cell-advice {
  font-size: 13.5px;
  color: var(--qh-text-sub);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ---------- 竞赛通知铃铛 ---------- */
.bell-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--qh-border, #e4e7ee);
  border-radius: 8px;
  background: #ffffff;
  color: var(--qh-text-sub, #5f6672);
  font-size: 13.5px;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.bell-btn:hover {
  background: #e9efff;
  color: #14419c;
}

.bell-btn.has-new {
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}

.bell-icon {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.bell-badge {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--qh-red, #dc2626);
  color: #ffffff;
  font-size: 12px;
  line-height: 16px;
  text-align: center;
}

/* ---------- 详情 / 通知抽屉 ---------- */
.detail-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f7f8fa;
}

.detail-head {
  flex: 0 0 auto;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  background: #ffffff;
  border-bottom: 1px solid var(--qh-border, #e4e7ee);
}

.detail-head-text {
  min-width: 0;
}

.detail-title {
  font-size: 14px;
  font-weight: 600;
  color: #16181d;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.detail-sub {
  font-size: 13.5px;
  color: #6b7280;
}

.icon-btn {
  width: 30px;
  height: 30px;
  margin-left: auto;
  border: 1px solid var(--qh-border, #e4e7ee);
  border-radius: 8px;
  background: #ffffff;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 150ms ease;
}

.icon-btn:hover {
  background: #eef0f5;
}

.ico {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: #5f6672;
  stroke-width: 1.8;
  stroke-linecap: round;
}

.detail-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 14px 16px 20px;
}

.detail-kpis {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.kpi {
  background: #ffffff;
  border: 1px solid var(--qh-border, #e4e7ee);
  border-radius: 8px;
  padding: 8px 10px;
}

.kpi-label {
  font-size: 13.5px;
  color: #6b7280;
}

.kpi-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--qh-red, #dc2626);
  font-variant-numeric: tabular-nums;
}

.kpi-value.small {
  font-size: 14px;
  color: #16181d;
}

.sec-title {
  display: flex;
  align-items: center;
  gap: 10px;
  /* 岗位卡内最多 7 个区块，拉开距离并加分隔线，避免挤成一团看不出分组 */
  margin: 22px 0 10px;
  padding-top: 14px;
  border-top: 1px solid var(--qh-border, #e4e7ee);
  font-size: 15px;
  font-weight: 600;
  color: #16181d;
}

.track-switch {
  margin-left: auto;
}

.dim-list {
  background: #ffffff;
  border: 1px solid var(--qh-border, #e4e7ee);
  border-radius: 8px;
  padding: 14px;
}

.dim-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13.5px;
}

.dim-row + .dim-row {
  margin-top: 8px;
}

.dim-name {
  flex: 0 0 72px;
  color: #5f6672;
}

.dim-bar {
  flex: 1 1 auto;
  height: 6px;
  border-radius: 8px;
  background: #eef0f5;
  overflow: hidden;
}

.dim-bar i {
  display: block;
  height: 100%;
  background: #1951c3;
  border-radius: 8px;
}

.dim-value {
  flex: 0 0 56px;
  text-align: right;
  color: #16181d;
  font-variant-numeric: tabular-nums;
}

.ul-hit,
.ul-gap {
  margin: 0;
  padding-left: 18px;
  font-size: 13.5px;
  line-height: 1.9;
  color: #5f6672;
}

.ul-gap {
  color: #b45309;
}

.ol-action {
  margin: 0;
  padding-left: 20px;
  font-size: 14px;
  line-height: 2;
  color: #16181d;
}

.comp-loading {
  font-size: 13.5px;
  color: #6b7280;
}

.comp-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.comp-cell {
  background: #ffffff;
  border: 1px solid var(--qh-border, #e4e7ee);
  border-radius: 8px;
  padding: 10px 12px;
}

.comp-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.comp-cat {
  flex: 0 0 auto;
  padding: 0 6px;
  border-radius: 8px;
  background: #e9efff;
  border: 1px solid #baccf0;
  color: #14419c;
  font-size: 12.5px;
  line-height: 18px;
}

.comp-name {
  font-size: 14px;
  font-weight: 600;
  color: #16181d;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.comp-org {
  margin-top: 2px;
  font-size: 13.5px;
  color: #6b7280;
}

.comp-why {
  margin-top: 4px;
  font-size: 13.5px;
  color: #5f6672;
}

.comp-reward {
  margin-top: 4px;
  font-size: 12.5px;
  color: #6b7280;
}

.comp-link {
  display: inline-block;
  margin-top: 6px;
  font-size: 13.5px;
  color: #1951c3;
  text-decoration: none;
}

.comp-link:hover {
  text-decoration: underline;
}

.notice-cell {
  background: #ffffff;
  border: 1px solid var(--qh-border, #e4e7ee);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
}

.notice-date {
  font-size: 12.5px;
  color: #6b7280;
}

.notice-title {
  margin-top: 4px;
  font-size: 14px;
  line-height: 1.6;
  color: #16181d;
}

.twin-panel {
  position: relative;
  display: grid;
  grid-template-columns: minmax(300px, 0.86fr) minmax(0, 1.74fr);
  align-items: stretch;
  gap: 0;
  overflow: hidden;
  padding: 8px;
  border: 1px solid #dce3ee;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 12px 34px rgba(24, 43, 76, 0.07);
}

.twin-visual {
  position: relative;
  display: flex;
  min-height: 286px;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  overflow: hidden;
  isolation: isolate;
  padding: 18px 20px 17px;
  border-radius: 13px;
  background:
    radial-gradient(ellipse at 50% 48%, rgba(56, 109, 209, 0.29), transparent 49%),
    linear-gradient(145deg, #101a31 0%, #192b4a 56%, #12343a 100%);
}

.twin-visual::before {
  position: absolute;
  z-index: -1;
  inset: 0;
  background-image:
    linear-gradient(rgba(154, 191, 255, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(154, 191, 255, 0.05) 1px, transparent 1px);
  background-size: 28px 28px;
  content: '';
  mask-image: linear-gradient(transparent, #000 18%, #000 82%, transparent);
}

.twin-visual-top,
.twin-visual-bottom {
  position: relative;
  z-index: 1;
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
}

.twin-visual-top {
  color: #c3d4ef;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.twin-visual-top i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #63dfbd;
  box-shadow: 0 0 12px rgba(99, 223, 189, 0.85);
}

.twin-stage {
  position: relative;
  z-index: 1;
  width: min(100%, 276px);
  margin: -5px 0;
  filter: drop-shadow(0 0 16px rgba(87, 201, 238, 0.22));
}

.twin-sphere { display: block; width: 100%; }
.twin-visual-bottom { align-items: flex-end; color: #d3def1; }
.twin-visual-bottom strong { font-size: 11px; letter-spacing: 0.1em; }
.twin-visual-bottom span { color: #bac9df; font-size: 12px; }

.twin-content {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
  padding: 26px 28px 24px 32px;
  background: #fff;
}

.twin-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.twin-eyebrow {
  margin: 0 0 5px;
  color: #5475a9;
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.08em;
}

.twin-heading h2 {
  margin: 0;
  color: #172a4d;
  font-size: 25px;
  line-height: 1.3;
  letter-spacing: -0.025em;
}

.twin-intro {
  margin: 7px 0 0;
  color: #53627b;
  font-size: 14px;
  line-height: 1.65;
}

.twin-live {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 7px;
  padding: 7px 10px;
  border: 1px solid #cfe8dd;
  border-radius: 999px;
  background: #f2faf6;
  color: #216b56;
  font-size: 12px;
  line-height: 1.35;
}

.twin-live i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #15936f;
  box-shadow: 0 0 0 3px rgba(21, 147, 111, 0.12);
}

.twin-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 22px;
}

.twin-fact {
  min-width: 0;
  min-height: 104px;
  padding: 13px 14px 12px;
  border: 1px solid #e5e9f0;
  border-radius: 11px;
  background: #f9fafc;
  transition: border-color 180ms ease, background-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}

.twin-fact > span,
.twin-fact small {
  display: block;
  color: #59677c;
  font-size: 12px;
  line-height: 1.45;
}

.twin-fact strong {
  display: block;
  overflow: hidden;
  margin: 7px 0 5px;
  color: #1e3156;
  font-size: 20px;
  font-weight: 700;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.twin-fact em { font-size: 12px; font-style: normal; font-weight: 500; }
.twin-fact small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.twin-fact:hover {
  transform: translateY(-2px);
  border-color: #c7d5eb;
  background: #fff;
  box-shadow: 0 8px 18px rgba(37, 71, 132, 0.08);
}

.twin-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #edf0f5;
  color: #59677c;
  font-size: 12px;
}

.twin-ask {
  min-height: 42px;
  border-color: #c7d5eb;
  color: #315db1;
  font-weight: 650;
}

.twin-ask:hover,
.twin-ask:focus-visible {
  border-color: #315db1;
  background: #f4f7ff;
  color: #244b98;
}

.twin-ask:focus-visible { outline: 2px solid #315db1; outline-offset: 2px; }

@media (max-width: 900px) {
  .twin-panel { grid-template-columns: 224px minmax(0, 1fr); }
  .twin-visual { min-height: 254px; padding-right: 14px; padding-left: 14px; }
  .twin-stage { width: min(100%, 220px); }
  .twin-content { padding: 22px 20px 18px; }
  .twin-heading { gap: 10px; }
  .twin-heading h2 { font-size: 23px; }
  .twin-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 17px; }
  .twin-fact { min-height: 96px; }
}

@media (max-width: 560px) {
  .twin-panel { grid-template-columns: minmax(0, 1fr); padding: 6px; }
  .twin-visual { min-height: 202px; padding: 14px 17px 13px; }
  .twin-stage { width: 184px; }
  .twin-content { padding: 20px 13px 12px; }
  .twin-heading { align-items: flex-start; gap: 8px; }
  .twin-heading h2 { font-size: 21px; }
  .twin-intro { font-size: 13px; }
  .twin-live { padding: 5px 8px; font-size: 11px; }
  .twin-facts { gap: 7px; margin-top: 15px; }
  .twin-fact { min-height: 94px; padding: 10px; }
  .twin-fact strong { font-size: 18px; }
  .twin-foot { align-items: stretch; flex-direction: column; margin-top: 13px; }
  .twin-ask { width: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  .twin-fact { transition: none; }
}

@media (prefers-reduced-motion: reduce) {
  .rec-cell {
    animation: none;
    transition: none;
  }

  .bell-btn,
  .icon-btn {
    transition: none;
  }
}

/* 窄屏 Hero：三块指标压进 358px 卡片内，不再把页面撑出横向滚动 */
@media (max-width: 700px) {
  /* 实时条在 390px 下把「30 秒自动刷新」「竞赛通知」挤成竖排单字，
     换成可换行布局并让标签保持整词。 */
  .live-bar {
    flex-wrap: wrap;
    gap: 8px 12px;
  }

  .live-bar > span:first-child,
  .bell-btn {
    white-space: nowrap;
  }

  .live-bar :deep(.el-switch__label) {
    white-space: nowrap;
  }

  /* 两个操作按钮在窄屏取等分宽度：flex 自适应会让「立即刷新」「竞赛通知」
     宽度随字数变化，视觉上像两个不同层级的控件 */
  .live-bar :deep(.el-button),
  .live-bar .bell-btn {
    flex: 1 1 calc(50% - 4px);
    min-width: 0;
    justify-content: center;
  }
}

/* 推荐卡头：标题 + 数量 + 刷新按钮在 360px 下把按钮文字挤掉，
   窄屏让标题独占一行、按钮保持整词 */
@media (max-width: 560px) {
  .rec-head {
    flex-wrap: wrap;
    gap: 8px;
  }

  .rec-head .card-title {
    flex: 1 1 100%;
  }

  .rec-head :deep(.el-button) {
    flex: 1 1 auto;
    white-space: nowrap;
  }

  .rec-head :deep(.el-input-number) {
    width: 118px;
  }
}

/* ---------- 入场动效（仅 transform/opacity/filter，不改布局尺寸） ---------- */
/* 页头改为浅色说明面板后，扫光带（.qh-hero::after）在浅底上是一条脏白痕，
   连同指标浮入动画一起去掉——页面内容的入场已由 .qh-reveal 统一负责。 */

/* ---------- 数字孪生：动态全息核心 ---------- */
/* 双层编排：SVG 元素用 CSS 关键帧（旋转/脉冲/扫描），
   轨道粒子与数据标签用 SMIL animateMotion 沿椭圆路径运行。 */

.twin-sphere {
  animation: twin-breathe 7s ease-in-out infinite;
}

@keyframes twin-breathe {
  0%, 100% { opacity: 0.88; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.02); }
}

/* 光晕呼吸 */
.twin-glow {
  animation: twin-glow 5s ease-in-out infinite;
}

@keyframes twin-glow {
  0%, 100% { opacity: 0.62; }
  50% { opacity: 1; }
}

/* 外圈虚线光环 + 双陀螺环 */
.twin-halo,
.twin-ring {
  transform-origin: 120px 96px;
}

.twin-halo { animation: twin-spin 30s linear infinite; }
.ring-a { animation: twin-spin 16s linear infinite; }
.ring-b { animation: twin-spin-rev 22s linear infinite; }

@keyframes twin-spin { to { transform: rotate(360deg); } }
@keyframes twin-spin-rev { to { transform: rotate(-360deg); } }

/* 能量核心 */
.twin-core-dot {
  transform-box: fill-box;
  transform-origin: center;
  animation: twin-core 3.2s ease-in-out infinite;
}

@keyframes twin-core {
  0%, 100% { transform: scale(1); opacity: 0.85; }
  50% { transform: scale(1.22); opacity: 1; }
}

/* 扩散脉冲：两相位交替 */
.twin-pulse {
  transform-box: fill-box;
  transform-origin: center;
  opacity: 0;
  animation: twin-pulse 3.2s ease-out infinite;
}

.p2 { animation-delay: 1.6s; }

@keyframes twin-pulse {
  0% { transform: scale(0.55); opacity: 0.75; }
  70% { opacity: 0; }
  100% { transform: scale(2.3); opacity: 0; }
}

/* 准轴虚线流动 */
.twin-axis { stroke-dasharray: 4 5; animation: twin-dash 24s linear infinite; }

@keyframes twin-dash { to { stroke-dashoffset: -216; } }

/* 雷达扇面：9 秒一圈 */
.twin-radar {
  transform-origin: 120px 96px;
  animation: twin-spin 9s linear infinite;
}

/* 星尘闪烁：三组相位错开 */
.twin-dust circle {
  fill: #bdf1ff;
  animation: twin-twinkle 4.2s ease-in-out infinite;
}

.d2 circle { animation-delay: 1.4s; }
.d3 circle { animation-delay: 2.8s; }

@keyframes twin-twinkle {
  0%, 100% { opacity: 0.15; }
  50% { opacity: 0.85; }
}

/* 核心外圈光环轻微收放 */
.twin-core-halo {
  transform-box: fill-box;
  transform-origin: center;
  animation: twin-core-halo 3.2s ease-in-out infinite;
}

@keyframes twin-core-halo {
  0%, 100% { transform: scale(1); opacity: 0.55; }
  50% { transform: scale(1.13); opacity: 0.95; }
}

/* 数据标签随轨道漂移时轻微增亮 */
.twin-chip text {
  font-family: inherit;
  font-weight: 650;
  letter-spacing: 0.05em;
}

@media (prefers-reduced-motion: reduce) {
  .twin-sphere,
  .twin-glow,
  .twin-halo,
  .twin-ring,
  .twin-core-dot,
  .twin-pulse,
  .twin-axis,
  .twin-radar,
  .twin-dust circle,
  .twin-core-halo {
    animation: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .twin-sphere {
    animation: none;
  }

  .quick-item,
  .pick-card,
  .guide-cta-btn,
  .twin-fact {
    transition: none;
  }

  .quick-item:hover,
  .pick-card:hover,
  .guide-cta-btn:hover,
  .twin-fact:hover,
  .rec-cell:hover {
    transform: none;
  }
}

/* 触屏设备关闭 hover 位移，避免点按后卡片卡在浮起态 */
@media (pointer: coarse) {
  .quick-item:hover,
  .pick-card:hover,
  .guide-cta-btn:hover,
  .twin-fact:hover,
  .rec-cell:hover {
    transform: none;
  }
}
</style>
