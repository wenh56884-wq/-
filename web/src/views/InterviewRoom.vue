<template>
  <div class="page bento-page">
    <!-- 本场说明：原来是一块蓝紫渐变营销横幅（大字 + 光圈装饰），
         放在后台工作区里像落地页插进控制台，和下面的白卡片是两套语言。
         现在改成与卡片同族的说明面板：标题说明“这是什么”，右侧三颗状态点说明“能不能开练”。 -->
    <section class="iv-hero">
      <div class="hero-copy">
        <h1>让智能体陪你练到会</h1>
        <p>面试智能体读取你的简历与目标岗位，动态出题、追问薄弱点；每轮点评可核验，最终评分由确定性引擎完成。</p>
      </div>
      <div class="hero-status" aria-label="练习准备情况">
        <span class="status-chip" :class="{ on: resume }">
          <i class="status-dot" :class="resume ? 'ready' : 'pending'"></i>
          {{ resume ? '简历已就绪' : '待录入简历' }}
        </span>
        <span class="status-chip on"><i class="status-dot ready"></i>智能体动态追问</span>
        <span class="status-chip on"><i class="status-dot ready"></i>评分可追溯</span>
      </div>
    </section>

    <p class="practice-disclaimer" role="note">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v5M12 8h.01" />
      </svg>
      简历诊断、AI 润色与面试建议仅供参考，不构成录用承诺；请结合真实经历与岗位要求自行判断。
    </p>

    <el-tabs v-model="tab" class="iv-tabs">
      <!-- ============ 简历 ============ -->
      <el-tab-pane label="我的简历" name="resume">
        <div class="bento-grid">
        <el-card shadow="never" class="block-card bento-span-2">
          <template #header><span class="card-title">录入简历</span></template>
          <el-radio-group v-model="entryMode">
            <el-radio-button value="paste">粘贴文本</el-radio-button>
            <el-radio-button value="upload">上传 docx / txt</el-radio-button>
            <el-radio-button value="form">问卷自填</el-radio-button>
            <el-radio-button value="template">简历模板</el-radio-button>
          </el-radio-group>

          <template v-if="entryMode === 'paste'">
            <el-input v-model="pasteText" type="textarea" :rows="10" class="mt8"
              placeholder="粘贴简历全文（含 教育经历 / 技能证书 / 实践经历 各小节效果最佳）" />
            <el-button type="primary" class="mt8" :loading="parsing" :disabled="!pasteText.trim()"
              @click="parseText">解析</el-button>
          </template>

          <template v-else-if="entryMode === 'upload'">
            <input type="file" accept=".docx,.txt" class="mt8" @change="onFile" />
            <div class="muted mt8">其他格式（pdf 等）请复制内容后用「粘贴文本」</div>
          </template>

          <template v-else-if="entryMode === 'template'">
            <el-form label-width="90px" class="mt8">
              <el-form-item label="选择模板">
                <el-select v-model="templateKind" class="job-select" aria-label="选择简历模板">
                  <el-option v-for="item in resumeTemplates" :key="item.id" :value="item.id" :label="item.name" />
                </el-select>
              </el-form-item>
              <el-form-item label="目标岗位"><el-input v-model="rewriteTarget" placeholder="如：Java 后端开发工程师" /></el-form-item>
              <el-form-item label="简历内容">
                <el-input v-model="pasteText" type="textarea" :rows="9" placeholder="将你的真实经历填入模板；没有的信息请留空，不要编造。" />
              </el-form-item>
            </el-form>
            <div class="template-preview"><b>{{ activeTemplate.name }}</b><p>{{ activeTemplate.description }}</p><pre>{{ activeTemplate.content }}</pre></div>
            <div class="resume-actions">
              <el-button @click="useResumeTemplate">填入此模板</el-button>
              <el-button type="primary" :loading="rewriteLoading" :disabled="pasteText.trim().length < 30" @click="rewriteResume">AI 润色草稿</el-button>
            </div>
            <div v-if="rewrittenText" class="rewrite-result">
              <div class="rewrite-result-head"><b>AI 润色结果 · 数字校验通过</b><el-button link type="primary" @click="pasteText = rewrittenText">用结果替换编辑区</el-button></div>
              <pre>{{ rewrittenText }}</pre>
              <p>结果尚未保存；请检查姓名、经历及岗位表达后，再解析并确认保存。</p>
            </div>
          </template>

          <template v-else>
            <el-form label-width="90px" class="mt8">
              <el-form-item label="自我评价"><el-input v-model="form.self" /></el-form-item>
              <el-form-item label="意向方向"><el-input v-model="form.intent" placeholder="如 数据分析" /></el-form-item>
              <el-form-item label="教育经历">
                <el-input v-model="form.edu" placeholder="学校｜专业｜2023.09-2027.06" />
              </el-form-item>
              <el-form-item label="技能/证书">
                <el-input v-model="form.skills" placeholder="Python、MySQL、CET-6 568（顿号分隔）" />
              </el-form-item>
              <el-form-item label="实践经历">
                <el-input v-model="form.exp" type="textarea" :rows="3"
                  placeholder="项目名｜负责后端开发，完成12个接口，服务500名学生" />
              </el-form-item>
            </el-form>
            <el-button type="primary" @click="saveForm">保存简历</el-button>
          </template>
        </el-card>

        <el-card v-if="parsed" shadow="never" class="block-card bento-span-2">
          <template #header>
            <div class="head-row"><span class="card-title">解析结果（确认后保存）</span>
              <el-button type="primary" size="small" :loading="saving" @click="saveParsed">保存为当前简历</el-button>
            </div>
          </template>
          <div class="kv"><span class="k">教育</span>{{ parsed.educations.map(e => e.school + '｜' + (e.major || '')).join('；') || '（无）' }}</div>
          <div class="kv"><span class="k">技能</span>{{ parsed.skills.join('、') || '（无）' }}</div>
          <div class="kv"><span class="k">证书</span>{{ parsed.certs.map(c => c.name).join('、') || '（无）' }}</div>
          <div class="kv"><span class="k">经历</span>
            <div v-for="(e, i) in parsed.experiences" :key="i" class="exp-item">{{ e.name }}</div>
            <span v-if="!parsed.experiences.length">（无）</span>
          </div>
        </el-card>

        <el-card v-if="resume" shadow="never" class="block-card bento-span-2 cap-body">
          <template #header>
            <div class="head-row"><span class="card-title">当前简历（v{{ resume['版本号'] }}，{{ resume['来源'] === 'upload' ? '上传' : '自填' }}）</span>
              <el-button size="small" :loading="diagLoading" @click="runDiagnosis">简历诊断</el-button>
            </div>
          </template>
          <div class="kv"><span class="k">教育</span>{{ (resume.educations || []).map(e => e.school + '｜' + (e.major || '')).join('；') || '（无）' }}</div>
          <div class="kv"><span class="k">技能</span>{{ (resume.skills || []).join('、') || '（无）' }}</div>
          <div class="kv"><span class="k">证书</span>{{ (resume.certs || []).map(c => c.name + (c.level ? ' ' + c.level : '')).join('、') || '（无）' }}</div>
          <div class="kv"><span class="k">经历</span>
            <div class="exp-list">
              <div v-for="(e, i) in resume.experiences || []" :key="i" class="exp-item">{{ e.name }}</div>
            </div>
            <span v-if="!(resume.experiences || []).length">（无）</span>
          </div>
        </el-card>

        <el-card v-if="diagnosis" shadow="never" class="block-card bento-span-2 cap-body">
          <template #header><span class="card-title">简历诊断（{{ diagnosis.issues.length }} 个问题）</span></template>
          <div v-for="(iss, i) in diagnosis.issues" :key="i" class="diag-item">
            <el-tag size="small" type="warning">{{ issueLabel(iss.kind) }}</el-tag>
            <b>{{ iss.where }}</b>：{{ iss.problem }}
            <div class="rewrite">{{ iss.rewrite }}</div>
          </div>
          <div v-if="!diagnosis.issues.length" class="muted">未发现明显问题</div>
        </el-card>

        <!-- 没跑诊断时占满整行，避免右半留白；有诊断时与它并排 -->
        <el-card shadow="never" class="block-card" :class="diagnosis ? 'bento-span-2' : 'bento-span-4'">
          <template #header><span class="card-title">怎么练</span></template>
          <ol class="howto">
            <li><b>录入简历</b>：粘贴 / 上传 / 问卷任选，解析后确认保存。</li>
            <li><b>选择岗位</b>：到「面试演练」选目标岗位开局。</li>
            <li><b>深度模拟面试</b>：逐题作答、逐题点评（引文逐字校验），答浅了会被追问。</li>
            <li><b>看评估报告</b>：维度分 + 核心问题 + 三步改进计划，照着练下一场就涨分。</li>
          </ol>
        </el-card>
        </div>
      </el-tab-pane>

      <!-- ============ 面试 ============ -->
      <el-tab-pane label="面试演练" name="interview">
        <div class="bento-grid">
        <el-card v-if="!session && !report" shadow="never" class="block-card bento-span-2">
          <template #header>
            <div class="setup-card-head">
              <div>
                <span class="card-title">和面试智能体开始训练</span>
                <p>先选一个目标岗位，智能体会按岗位要求组织本场问题。</p>
              </div>
              <el-tag size="small" type="info" effect="plain">
                全国岗位池 {{ jobTotal || '…' }} 条
              </el-tag>
            </div>
          </template>
          <div class="flow-steps" aria-label="开始面试的步骤">
            <div class="flow-step" :class="resume ? 'done' : 'active'"><span>01</span><b>准备简历</b></div>
            <div class="flow-line"></div>
            <div class="flow-step" :class="resume ? 'active' : ''"><span>02</span><b>选择岗位</b></div>
            <div class="flow-line"></div>
            <div class="flow-step"><span>03</span><b>开始练习</b></div>
          </div>
          <div v-if="!resume" class="resume-needed">
            <div><b>先让智能体认识你</b><span>录入简历后，问题才能结合你的经历进行追问。</span></div>
            <el-button type="primary" plain @click="tab = 'resume'">去准备简历</el-button>
          </div>
          <div class="job-filters">
            <el-input v-model="jobKeyword" placeholder="搜索岗位 / 技能 / 企业" clearable
              class="job-kw" @keyup.enter="loadJobs" @clear="loadJobs" />
            <el-select v-model="jobIndustry" placeholder="行业" clearable filterable
              class="job-filter" @change="loadJobs">
              <el-option v-for="i in facets.industries" :key="i.name" :value="i.name"
                :label="`${i.name} (${i.count})`" />
            </el-select>
            <el-select v-model="jobCity" placeholder="城市" clearable filterable
              class="job-filter" @change="loadJobs">
              <el-option v-for="c in facets.cities" :key="c.name" :value="c.name"
                :label="`${c.name} (${c.count})`" />
            </el-select>
            <el-button :loading="jobLoading" @click="loadJobs">搜索</el-button>
          </div>
          <label class="field-label" for="interview-job-select">目标岗位</label>
          <el-select id="interview-job-select" v-model="jobId" filterable placeholder="选择岗位（可先按条件过滤）"
            class="job-select" :loading="jobLoading">
            <el-option v-for="j in jobs" :key="j.id" :value="j.id"
              :label="`${j.title} · ${j.company || ''} · ${j.city || ''}`" />
          </el-select>

          <!-- 模式三档：选中的 mode 随 start 请求一起发给后端，出题节奏由后端决定 -->
          <div class="mode-field" role="radiogroup" aria-label="面试模式">
            <div class="mode-field-head">
              <span class="field-label">面试模式</span>
              <span class="mode-field-note">影响出题节奏与点评语气，不影响评分口径</span>
            </div>
            <div class="mode-grid">
              <button
                v-for="mode in MODES" :key="mode.value" type="button"
                class="mode-card" :class="{ active: interviewMode === mode.value }"
                role="radio" :aria-checked="interviewMode === mode.value"
                :disabled="starting" @click="interviewMode = mode.value"
              >
                <span class="mode-card-top">
                  <b>{{ mode.label }}</b>
                  <i class="mode-check" aria-hidden="true"></i>
                </span>
                <span class="mode-card-desc">{{ mode.desc }}</span>
                <span class="mode-card-tags">
                  <span v-for="tag in mode.tags" :key="tag">{{ tag }}</span>
                </span>
              </button>
            </div>
          </div>

          <el-button type="primary" class="start-button" :loading="starting" :disabled="!jobId || !resume"
            @click="startInterview">开始模拟面试</el-button>
          <div v-if="!resume" class="muted mt8">还没有简历：请先在「我的简历」页录入</div>
          <div class="agent-flow mt8">
            <div class="agent-flow-title"><span class="agent-pulse"></span>本场由面试智能体驱动</div>
            <div class="agent-flow-steps">
              <span>读取简历证据</span><i>→</i><span>匹配岗位能力</span><i>→</i><span>动态追问</span><i>→</i><span>生成可核验复盘</span>
            </div>
          </div>
        </el-card>

        <!-- 去掉跨两行：行高被右侧点评/历史卡拉爆会留出大片空白，见「我的简历」同款修法 -->
        <el-card v-if="session && !report" shadow="never" class="block-card bento-span-2">
          <template #header>
            <div class="head-row">
              <span class="card-title">
                第 {{ session.round }} / {{ session.total }} 题 · {{ session.label }}
                <el-tag v-if="session.isProbe" size="small" type="warning" effect="dark"
                  class="probe-tag">追问</el-tag>
              </span>
              <el-tag size="small">{{ jobTitle }}</el-tag>
              <!-- 本场模式徽标：只认接口返回的 mode_label，缺失就不显示，不用前端选项名冒充 -->
              <el-tag v-if="session.modeLabel" size="small" effect="plain" class="mode-badge"
                :type="session.mode === 'stress' ? 'danger' : session.mode === 'easy' ? 'success' : 'info'">
                本场：{{ session.modeLabel }}
              </el-tag>
              <el-button size="small" class="end-button" :loading="abandoning" :disabled="abandoning || answering"
                @click="confirmAbandon">结束本场</el-button>
            </div>
          </template>
          <div class="progress-heading">
            <span>练习进度</span><b>第 {{ session.round }} / {{ session.total }} 题</b>
            <span v-if="currentClock" class="question-clock" aria-label="本题已用时">
              <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="13" r="8" /><path d="M12 9v4l2.5 1.5M9 2h6" /></svg>
              本题已用 {{ currentClock }}
            </span>
            <!-- 压力模式单题倒计时：仅前端提示，归零不自动提交、不自动跳题 -->
            <span v-if="countdownVisible" class="countdown" :class="{ 'is-low': countdownLeft <= COUNTDOWN_LOW, 'is-up': countdownUp }"
              role="timer" aria-live="off"
              :aria-label="countdownUp ? '时间到，仍可继续作答' : `本题建议用时剩余 ${countdownLeft} 秒`">
              <svg class="countdown-ring" viewBox="0 0 36 36" aria-hidden="true">
                <circle class="ring-track" cx="18" cy="18" r="15.9" />
                <circle class="ring-value" cx="18" cy="18" r="15.9"
                  :stroke-dasharray="`${countdownArc} ${COUNTDOWN_CIRC}`" />
              </svg>
              <span class="countdown-text">{{ countdownUp ? '时间到，仍可继续作答' : `剩余 ${countdownLeft} 秒` }}</span>
            </span>
          </div>
          <el-progress :percentage="Math.round(((session.round - 1) / session.total) * 100)"
            :stroke-width="8" :show-text="false" class="iv-progress" />
          <div class="agent-live-strip">
            <span class="agent-live-mark">AI</span>
            <span><b>面试智能体</b> 正在进行{{ session.isProbe ? '针对性追问' : '岗位适配提问' }}，根据你的回答调整下一步问题。</span>
            <el-tag size="small" type="success" effect="plain">动态面试中</el-tag>
          </div>
          <div class="question-label">{{ session.label || labelOf(session.type) }}<span>请结合具体经历作答</span></div>
          <div v-if="session.personalized" class="personalized-strip">
            <el-tag v-if="session.personalized.avoided_recent" size="small" type="info" effect="plain">已避开你近 3 场做过的题</el-tag>
            <el-tag v-if="session.personalized.weak" size="small" type="warning" effect="plain">
              重点考察{{ session.personalized.weak_label }}（上次 {{ session.personalized.weak.score }} 分）
            </el-tag>
          </div>
          <div class="question">{{ session.question }}</div>
          <div v-if="session.source" class="q-source">
            <template v-if="session.source.kind === 'bank'">
              <el-tag size="small" type="success" effect="plain">题库命中</el-tag>
              <span class="src-txt">
                本题出自
                <a :href="session.source.url" target="_blank" rel="noopener">{{ session.source.name }}</a>
                · {{ session.source.family_label || session.source.family }}
                <template v-if="session.source.matched_by && session.source.matched_by.length">
                  · 命中 {{ session.source.matched_by.join('、') }}
                </template>
              </span>
            </template>
            <template v-else>
              <el-tag size="small" type="info" effect="plain">模板出题</el-tag>
              <span class="src-txt">该行业暂无题库覆盖，按简历证据套用通用问法</span>
            </template>
          </div>
          <label class="field-label" for="interview-answer">你的回答</label>
          <el-input id="interview-answer" v-model="answerText" type="textarea" :rows="6" :maxlength="VOICE_MAX_CHARS"
            show-word-limit resize="vertical" aria-describedby="answer-hint"
            :disabled="answering || voice.listening"
            placeholder="试着按 STAR 结构组织：背景是什么、目标是什么、你采取了哪些行动、结果如何？" />
          <!-- 语音作答：识别文本实时追加到上面的输入框，已打字的内容原样保留 -->
          <div class="voice-bar">
            <button type="button" class="voice-btn" :class="{ 'is-recording': voice.listening }"
              :disabled="!voiceSupported || answering" @click="toggleVoice"
              :aria-pressed="voice.listening">
              <span class="voice-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
              </span>
              <span class="voice-label">{{ voice.listening ? '停止录音' : '开始录音' }}</span>
              <span v-if="voice.listening" class="voice-wave" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
            </button>
            <span v-if="voice.listening" class="voice-status" role="status" aria-live="polite">
              正在听你说，识别到的内容会接在已写内容后面
            </span>
            <span v-else-if="!voiceSupported" class="voice-status is-muted">{{ voiceUnsupportedHint }}</span>
            <span v-else class="voice-status is-muted">可以边说边打字，识别内容会追加在后面</span>
          </div>
          <div id="answer-hint" class="input-hint">尽量写清你亲自采取的行动和可验证的结果。暂时没有思路时，也可以跳过——卡住约 45 秒，小航会在旁边递一句提示。</div>
          <div class="mt8 head-row">
            <el-button type="primary" :loading="answering" :disabled="answering || !answerText.trim()"
              @click="submitAnswer(true)">提交回答</el-button>
            <el-button :loading="answering" :disabled="answering" @click="submitAnswer(false)">跳过本题</el-button>
          </div>
        </el-card>

        <!-- 点评卡：始终在场，形成「答 → 看点评 → 下一题」的节奏。
             提交后进入等待态（骨架屏），点评渲染完「下一题」才出现并贴在卡片底部，
             不会和「提交回答」同时可点。 -->
        <el-card v-if="session && !report" shadow="never" class="block-card bento-span-2 cap-body comment-card"
          :class="{ 'is-waiting': commentPending }">
          <template #header>
            <div class="head-row">
              <span class="card-title">上一题点评</span>
              <template v-if="lastComment && !commentPending">
                <el-tag size="small" :type="lastComment.version === 'comment-fallback-v1' ? 'info' : 'success'">
                  {{ lastComment.version === 'comment-fallback-v1' ? '模板点评' : 'AI 点评·引文已校验' }}
                </el-tag>
                <el-tag v-if="lastComment.score != null" size="small" type="warning">{{ lastComment.score }} 分</el-tag>
                <el-tag v-if="lastComment.elapsed" size="small" type="info" effect="plain">用时 {{ lastComment.elapsed }}</el-tag>
              </template>
            </div>
          </template>

          <!-- 等待态：点评请求进行中 -->
          <div v-if="commentPending" class="comment-waiting" role="status" aria-live="polite">
            <div class="skeleton-block" aria-hidden="true"></div>
            <div class="skeleton-block is-short" aria-hidden="true"></div>
            <p class="waiting-text">
              <span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>
              面试官正在看你的回答…
            </p>
          </div>

          <!-- 错误态：不把后端原文案丢给学生，给一句人话 + 可执行的动作 -->
          <div v-else-if="commentError" class="comment-error" role="alert">
            <p>{{ commentError.text }}</p>
            <div class="comment-error-actions">
              <el-button v-if="commentError.action === 'reload'" size="small" type="primary" @click="reloadPage">刷新页面</el-button>
              <el-button v-else size="small" type="primary" @click="retryLastAction">重试</el-button>
            </div>
          </div>

          <!-- 空态：本题还没提交 -->
          <div v-else-if="!lastComment" class="comment-empty">提交回答后，面试官会在这里给出点评。</div>

          <!-- 点评正文 + 底部「下一题」 -->
          <template v-else>
            <div class="comment">{{ lastComment.text }}</div>
            <div class="comment-footer">
              <span class="comment-footer-hint">看完点评再继续</span>
              <el-button type="primary" @click="goNextQuestion">下一题</el-button>
            </div>
          </template>
        </el-card>

        <el-card v-if="report" shadow="never" class="block-card bento-span-4 report-card">
          <template #header>
            <div class="head-row"><span class="card-title">面试评估报告</span>
              <el-tag size="small" type="info" effect="plain">引擎 {{ evaluation.engine_version || 'interview-v2' }} · 全部为确定性实算</el-tag>
              <el-button size="small" @click="resetInterview">再来一场</el-button>
            </div>
          </template>

          <!-- 顶部：总分 + 概况 + 维度分 -->
          <div class="report-hero">
            <div class="score-ring" :class="scoreClass">
              <svg viewBox="0 0 120 120">
                <circle cx="60" cy="60" r="52" class="ring-bg" />
                <circle cx="60" cy="60" r="52" class="ring-fg"
                  :stroke-dasharray="`${(evaluation.total || 0) / 100 * 326.7} 326.7`" />
              </svg>
              <div class="ring-text">
                <b>{{ evaluation.total ?? '—' }}</b><span>总分</span>
              </div>
            </div>
            <div class="hero-facts">
              <div class="fact-row">
                <span class="fact">已答 <b>{{ evaluation.answered }}</b> 题</span>
                <span class="fact warn" v-if="evaluation.skipped">跳过 <b>{{ evaluation.skipped }}</b> 题</span>
                <span class="fact" v-if="evaluation.probes">追问 <b>{{ evaluation.probes }}</b> 道</span>
                <span class="fact" v-if="jobTitle">{{ jobTitle }}</span>
              </div>
              <div class="dim-bars">
                <div v-for="d in evaluation.dimensions" :key="d.type" class="dim-row">
                  <span class="dim-label">{{ d.label }}</span>
                  <div class="dim-track">
                    <div class="dim-fill" :class="dimClass(d.avg)"
                      :style="{ width: (d.avg || 0) + '%' }"></div>
                  </div>
                  <span class="dim-val">{{ d.avg ?? '未答' }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 核心问题 -->
          <div v-if="evaluation.core_problems && evaluation.core_problems.length" class="report-sec">
            <div class="sec-title">核心问题 <span class="muted">（按严重度排序，全部由评分明细机械归因）</span></div>
            <div v-for="(p, i) in evaluation.core_problems" :key="i" class="problem-item">
              <el-tag size="small" :type="p.severity === 'high' ? 'danger' : p.severity === 'medium' ? 'warning' : 'info'"
                effect="dark">{{ p.severity === 'high' ? '高' : p.severity === 'medium' ? '中' : '低' }}</el-tag>
              <span class="problem-dim">{{ p.dimension }}</span>
              <span class="problem-txt">{{ p.problem }}</span>
              <div class="problem-action">→ {{ p.action }}</div>
            </div>
          </div>

          <!-- 改进计划 -->
          <div v-if="evaluation.improvement_plan && evaluation.improvement_plan.length" class="report-sec">
            <div class="sec-title">改进计划</div>
            <div class="plan-row">
              <div v-for="(s, i) in evaluation.improvement_plan" :key="i" class="plan-card">
                <div class="plan-when">{{ s.when }}</div>
                <div class="plan-focus">{{ s.focus }}</div>
                <div class="plan-action">{{ s.action }}</div>
              </div>
            </div>
          </div>

          <!-- 逐题复盘 -->
          <div class="report-sec">
            <div class="sec-title">逐题复盘 <span class="muted">（点评引文已逐字校验；追问以 ⚡ 标记）</span></div>
            <div v-for="q in evaluation.per_question" :key="q.round" class="qreview"
              :class="{ probe: q.is_probe, skipped: !q.answered }">
              <div class="qreview-head">
                <span class="qreview-round">第 {{ q.round }} 题 <template v-if="q.is_probe">⚡追问</template></span>
                <el-tag size="small" effect="plain">{{ q.label }}</el-tag>
                <el-tag size="small" :type="scoreTagType(q.score)">
                  {{ q.score != null ? q.score + ' 分' : '未作答' }}
                </el-tag>
              </div>
              <div class="qreview-question">{{ q.question }}</div>
              <div v-if="q.comment" class="qreview-comment">{{ q.comment }}</div>
              <div v-if="q.keyword_missed && q.keyword_missed.length" class="qreview-tags">
                <span class="tag-muted">漏掉考点：</span>
                <el-tag v-for="k in q.keyword_missed" :key="k" size="small" type="warning" effect="plain">{{ k }}</el-tag>
              </div>
              <div v-if="q.keyword_hits && q.keyword_hits.length" class="qreview-tags">
                <span class="tag-muted">命中：</span>
                <el-tag v-for="k in q.keyword_hits" :key="k" size="small" type="success" effect="plain">{{ k }}</el-tag>
              </div>
            </div>
          </div>

          <!-- 强项与原文 -->
          <el-collapse class="mt8">
            <el-collapse-item title="报告原文（可复制）" name="raw">
              <pre class="report">{{ report.report }}</pre>
            </el-collapse-item>
          </el-collapse>

          <div v-if="reportSources.length" class="mt8">
            <div class="muted">本场题目出处（每道题都能回到来源页面核对）</div>
            <el-table :data="reportSources" size="small" class="mt8">
              <el-table-column prop="round" label="轮次" width="70" />
              <el-table-column label="题型" width="120">
                <template #default="{ row }">
                  {{ row.label }}
                  <el-tag v-if="row.is_probe" size="small" type="warning" effect="plain">追问</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="来源" width="140" />
              <el-table-column prop="question" label="题目" min-width="240" show-overflow-tooltip />
              <el-table-column label="链接" width="90">
                <template #default="{ row }">
                  <a v-if="row.url" :href="row.url" target="_blank" rel="noopener">查看</a>
                  <span v-else class="muted">模板</span>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <p class="report-disclaimer">
            本报告由确定性引擎评分 + AI 组织表达，仅供参考，不构成录用承诺。
          </p>
        </el-card>

        <!-- 动态跨列补空位：无答题卡时与「选择目标岗位开局」并排（历史场次始终同屏可见）。
             有答题卡时它和常驻的点评卡各占半宽，历史卡落到下一行占满整行 -->
        <el-card shadow="never" class="block-card"
          :class="session ? 'bento-span-4' : 'bento-span-2'">
          <template #header><span class="card-title">历史场次</span></template>
          <!-- 这张表在半宽卡片里，7 列必然横向溢出（操作列被裁）。
               合并成 4 列：场次 / 岗位 / 结果（状态 + 分数 + 进度）/ 操作。
               完整时间等信息在点开的报告里看，列表只承担「找到那一场」的职责。 -->
          <el-table :data="history" size="small" class="hist-table" @row-click="openHistory">
            <el-table-column prop="编号" label="场次" width="56" />
            <el-table-column prop="岗位名称" label="岗位" min-width="110" show-overflow-tooltip>
              <template #default="{ row }">{{ row['岗位名称'] || '未选岗位' }}</template>
            </el-table-column>
            <el-table-column label="结果" width="104">
              <template #default="{ row }">
                <span class="hist-result" :class="row['状态']">
                  <b v-if="row['总分'] != null">{{ row['总分'] }}</b>
                  <b v-else>{{ statusText(row['状态']) }}</b>
                  <i v-if="row['总分'] != null">{{ statusText(row['状态']) }}</i>
                  <i v-else>{{ row['当前轮次'] }}/{{ row['最大轮次'] }}</i>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="82">
              <template #default="{ row }">
                <el-button link type="primary" :loading="openingSession === row['编号']"
                  @click.stop="openHistory(row)">
                  {{ row['状态'] === 'ongoing' ? '继续' : '报告' }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs'
import http from '../api/http'
import { useIdleHint } from '../composables/useIdleHint'

const tab = ref('interview')
const entryMode = ref('paste')
const pasteText = ref('')
const templateKind = ref('campus')
const rewriteTarget = ref('')
const rewriteLoading = ref(false)
const rewrittenText = ref('')
const parsed = ref(null)
const saving = ref(false)
const parsing = ref(false)
const resume = ref(null)
const diagnosis = ref(null)
const diagLoading = ref(false)
const form = ref({ self: '', intent: '', edu: '', skills: '', exp: '' })

const jobs = ref([])
const jobId = ref(null)
const jobPool = ref('national')
const jobTotal = ref(0)
const jobKeyword = ref('')
const jobCity = ref('')
const jobIndustry = ref('')
const jobLoading = ref(false)
const facets = ref({ industries: [], cities: [] })
const session = ref(null)
const jobTitle = ref('')
const answerText = ref('')
const answering = ref(false)
const starting = ref(false)

// ---- 面试模式：三档，选中的 mode 随 start 请求发给后端，出题节奏由后端决定 ----
// tags 是给学生看的说明；真正的抗压题 / 追问 / 点评语气都由后端按 mode 处理，前端只负责选择与展示。
const MODES = [
  { value: 'easy', label: '轻松', desc: '先适应流程，不怕答不好',
    tags: ['去掉抗压题', '追问少', '点评多鼓励'] },
  { value: 'standard', label: '标准', desc: '贴近常见面试的节奏',
    tags: ['常规抗压题', '常规追问', '点评均衡'] },
  { value: 'stress', label: '压力', desc: '模拟高压面，练临场反应',
    tags: ['抗压题提前', '追问紧', '点评直接'] },
]
const interviewMode = ref('standard')

// ---- 压力模式单题倒计时：仅前端提示用 ----
// 90 秒只是给学生的节奏提示：到点不会自动提交，也不会自动跳题，学生仍可继续作答。
// 这个数字不发给后端、不参与评分，后端也没有「答题限时」的口径，所以写死在前端。
const STRESS_COUNTDOWN_SEC = 90
const COUNTDOWN_LOW = 15                        // 剩余不足 15 秒转为警示色
const COUNTDOWN_CIRC = 2 * Math.PI * 15.9155    // 环形进度条周长（r=15.9155，与模板里的 r 对应）
const countdownLeft = ref(0)
const countdownUp = ref(false)                  // 归零：显示「时间到，仍可继续作答」，倒计时停止
const countdownVisible = computed(() => (
  session.value?.mode === 'stress' && !report.value && !answering.value
))
const countdownArc = computed(() => (COUNTDOWN_CIRC * countdownLeft.value) / STRESS_COUNTDOWN_SEC)
const lastComment = ref(null)
const report = ref(null)
const evaluation = ref({})
const history = ref([])
const openingSession = ref(null)

// ---- 面试节奏：答 → 看点评 → 下一题 ----
// 提交接口一次性返回「点评 + 下一题」。为了不让学生看到点评时题目已经跳走，
// 下一题先暂存到 pendingNext，点「下一题」才真正换题并开始计时。
const router = useRouter()
const commentPending = ref(false)     // 点评请求进行中（骨架屏）
const commentError = ref(null)        // { text, action: 'retry' | 'reload' } | null
const pendingNext = ref(null)         // 已取回但尚未展示的下一题
const questionStartedAt = ref(null)   // 当前题开始作答的时间戳（毫秒）
const questionClock = ref(0)           // 当前题已用秒数，仅驱动界面上的走时显示
const abandoning = ref(false)
let clockTimer = null
const resumeTemplates = [
  { id: 'campus', name: '应届生校招', description: '适合在校生 / 应届生，强调课程项目、实习和校园实践。',
    content: '【基本信息】姓名｜电话｜邮箱｜求职意向\n【教育经历】学校｜专业｜学历｜起止时间\n主修课程：\n【项目 / 实习经历】项目名称｜角色｜时间\n背景与目标：\n个人行动：\n结果与证据（只填真实数据）：\n【技能与证书】\n【自我评价】' },
  { id: 'technical', name: '技术 / 项目型', description: '适合研发、数据与工程岗位，突出技术栈、个人贡献和项目结果。',
    content: '【基本信息】姓名｜电话｜邮箱｜求职意向\n【技术概要】编程语言｜框架｜数据库｜工具\n【教育经历】学校｜专业｜学历｜起止时间\n【项目经历】项目名称｜技术栈｜个人角色\n项目背景与目标：\n负责的具体模块与技术决策：\n难点、解决过程与真实结果：\n【实习 / 开源 / 竞赛】\n【证书与其他】' },
  { id: 'general', name: '通用实习简历', description: '适合寻找第一段实习经历，突出学习背景、实践与可迁移能力。',
    content: '【基本信息】姓名｜电话｜邮箱｜求职意向\n【教育经历】学校｜专业｜学历｜起止时间\n【实践经历】组织 / 项目｜角色｜时间\n任务背景：\n我的行动：\n结果与复盘：\n【校园经历 / 志愿活动】\n【技能与证书】\n【个人总结】' },
]
const activeTemplate = computed(() => resumeTemplates.find((item) => item.id === templateKind.value) || resumeTemplates[0])

// 报告配色：分数段语义色（复用评分口径：<60 待提升 / 60-75 合格 / >=75 强项）
const scoreClass = computed(() => {
  const t = evaluation.value.total
  return t == null ? '' : t >= 75 ? 'good' : t >= 60 ? 'mid' : 'low'
})
const dimClass = (v) => (v == null ? '' : v >= 75 ? 'good' : v >= 60 ? 'mid' : 'low')
const scoreTagType = (s) => (s == null ? 'info' : s >= 75 ? 'success' : s >= 60 ? 'warning' : 'danger')

const ISSUE_LABELS = {
  quantify: '缺量化', verb: '动词开头', length: '过长', missing: '缺失',
  alignment: '岗位对齐'
}
const issueLabel = (k) => ISSUE_LABELS[k] || k

const TYPE_LABELS = {
  motivation: '动机匹配', major: '专业基础', project: '项目深挖',
  scenario: '情景模拟', stress: '抗压应对', counter: '反问环节'
}
const labelOf = (t) => TYPE_LABELS[t] || t

// ---- 冷场提示：45 秒没动笔，小航递一句结构化抓手（不给答案） ----
// 确定性模板、不发模型请求；每道题最多 2 条；学生打字/提交会重新计时。
const IDLE_HINTS = {
  motivation: [
    '可以从「为什么是这个岗位、为什么是现在」两句话开场，再落到一个具体细节。',
    '想想投递那天最打动你的一件事，把它讲成你选择这份工作的理由。'
  ],
  major: [
    '先把核心概念用一句话说清，再接一个课程里做过的例子。',
    '找一门你考得最好的课，说说它和这道题的关联。'
  ],
  project: [
    '套 STAR：当时的目标、你亲自做的动作、可验证的结果，最后补一句复盘。',
    '想想项目里最难跨过去的一步，你当时是怎么解决的。'
  ],
  scenario: [
    '先给一句原则表态，再给两步具体做法，最后收一句「什么情况下不这么做」。'
  ],
  stress: [
    '先接住情绪不辩解：承认事实，再讲你会做的改进，最后一句教训收尾。'
  ],
  counter: [
    '可以问岗位最常踩的坑，或新人前 90 天怎么算合格，先别问薪资福利。'
  ],
  general: [
    '先给结论，再给两条理由，最后收一句可执行的建议。',
    '想想这道题在考察什么能力，用一段真实经历去对上它。'
  ]
}
const idleHint = useIdleHint({
  timeoutMs: 45000,
  maxHints: 2,
  pick: (n) => {
    if (!session.value || answering.value) return null
    const pool = IDLE_HINTS[session.value.type] || IDLE_HINTS.general
    return pool[n % pool.length]
  }
})

watch(session, (s) => {
  if (s && s.question) idleHint.restart()
  else idleHint.stop()
})

watch(answerText, (text) => {
  if (String(text).trim()) idleHint.poke()
})

// 历史场次的状态由引擎返回英文枚举，界面统一译成中文
const STATUS_LABELS = { ongoing: '进行中', finished: '已完成', aborted: '已中止', pending: '待开始' }
const statusText = (status) => STATUS_LABELS[status] || status || '—'

// ---- 单题计时：题目出现即开始，提交时停表。纯前端展示，不参与任何评分 ----
function formatClock(totalSeconds) {
  const safe = Math.max(0, Math.floor(Number(totalSeconds) || 0))
  const mm = String(Math.floor(safe / 60)).padStart(2, '0')
  const ss = String(safe % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

// 开表：走时与压力模式倒计时共用同一个定时器，避免两个 interval 各走各的产生漂移
function startQuestionClock() {
  stopQuestionClock()
  questionStartedAt.value = Date.now()
  questionClock.value = 0
  // 倒计时只在压力模式走；其余模式归零、不启动
  countdownUp.value = false
  countdownLeft.value = session.value?.mode === 'stress' ? STRESS_COUNTDOWN_SEC : 0
  clockTimer = setInterval(() => {
    if (questionStartedAt.value) {
      questionClock.value = Math.floor((Date.now() - questionStartedAt.value) / 1000)
      tickCountdown()
    }
  }, 1000)
}

// 倒计时走一步。归零后置 countdownUp 并停止递减：此后只是提示，绝不自动提交、不自动跳题。
function tickCountdown() {
  if (countdownUp.value || countdownLeft.value <= 0) return
  const next = countdownLeft.value - 1
  if (next <= 0) {
    countdownLeft.value = 0
    countdownUp.value = true
    ElMessage.info('时间到，仍可继续作答')
  } else {
    countdownLeft.value = next
  }
}

// 停表并返回本题用时（mm:ss）；从没开过表就返回 null，不显示假 00:00
function stopQuestionClock() {
  if (clockTimer) {
    clearInterval(clockTimer)
    clockTimer = null
  }
  const started = questionStartedAt.value
  questionStartedAt.value = null
  if (!started) return null
  return formatClock((Date.now() - started) / 1000)
}

// 当前题走时：没开表返回空串，界面上不显示
const currentClock = computed(() => (questionStartedAt.value ? formatClock(questionClock.value) : ''))

// ---- 错误文案映射：把后端的错误码 / 文案翻译成学生看得懂的话 ----
// 每条给出「发生了什么」和「接下来能做什么」；action 决定点评卡里出现哪个按钮。
// 未命中任何规则的错误一律落到网络提示，绝不把后端原文案直接丢到页面上。
const ERROR_MESSAGES = [
  { test: (e) => e?.response?.status === 401,
    text: '登录已过期，请重新登录后再继续。', action: 'reload' },
  { test: (e) => /轮次已变化|round.*(changed|mismatch)/i.test(e?.response?.data?.detail || ''),
    text: '页面数据已更新，请刷新后继续。', action: 'reload' },
  { test: (e) => e?.response?.status === 409 && /已结束|finished/i.test(e?.response?.data?.detail || ''),
    text: '这场面试已经结束，正在为你加载评估报告。', action: 'reload' },
  { test: (e) => e?.response?.status === 409 && /最后一题|last/i.test(e?.response?.data?.detail || ''),
    text: '这已经是最后一题了，刷新后即可查看评估报告。', action: 'reload' },
  { test: (e) => e?.response?.status === 409,
    text: '页面数据已更新，请刷新后继续。', action: 'reload' },
  { test: (e) => e?.response?.status === 403,
    text: '你没有访问这场面试的权限，请回到面试列表重新进入。', action: 'reload' },
  { test: (e) => e?.response?.status === 404,
    text: '没有找到这场面试，可能已被清理，请回到面试列表重新开始。', action: 'reload' },
  { test: (e) => e?.code === 'ECONNABORTED' || /timeout/i.test(e?.message || ''),
    text: '面试官这次想得有点久，你的回答还在，可以再提交一次。', action: 'retry' },
  { test: (e) => !e?.response,
    text: '网络似乎不稳定，请重试', action: 'retry' },
]
const FALLBACK_ERROR = { text: '网络似乎不稳定，请重试', action: 'retry' }

function friendlyError(err) {
  const hit = ERROR_MESSAGES.find((rule) => {
    try { return rule.test(err) } catch { return false }
  })
  return hit ? { text: hit.text, action: hit.action } : { ...FALLBACK_ERROR }
}

// ---- 语音作答：浏览器原生 Web Speech API，不引入任何依赖 ----
// 与 ExpressionLab 的区别：那边录音结束用识别结果「替换」整段文本；
// 这里要「追加」——学生已经打的字原样保留，识别内容接在后面。
// 做法：开始录音时记下 base = 当前答案，之后每次回调都把输入框设为 base + 本次识别文本。
// interim 结果会反复刷新，用「重设整段」而不是「往后拼」才不会重复追加。
const SpeechCtor = typeof window === 'undefined'
  ? null
  : (window.SpeechRecognition || window.webkitSpeechRecognition)
// 与项目里 useVoice.js 同一口径：语音识别要求「有接口 + 安全上下文（HTTPS 或 localhost）」。
// 非安全上下文下浏览器虽然暴露了构造函数，但 start() 必然报 not-allowed，提前判掉更诚实。
const voiceSecure = typeof window === 'undefined' ? true : window.isSecureContext !== false
const voiceSupported = Boolean(SpeechCtor) && voiceSecure
// 答案字数上限：与输入框 maxlength 共用同一个常量，语音追加时同样不越过这条线
const VOICE_MAX_CHARS = 2000
const voiceUnsupportedHint = !SpeechCtor
  ? '当前浏览器不支持语音，请打字作答'
  : (!voiceSecure ? '语音作答需要 HTTPS 环境，当前请打字作答' : '')

const voice = ref({ listening: false })
let voiceRec = null          // 当前识别实例
let voiceBase = ''           // 开始录音时的答案文本
let voiceFinal = ''          // 本次录音已确定的识别文本
let voiceInterim = ''        // 本次录音临时的识别文本
let voiceStopRequested = false   // 学生主动点了停止（用于区分自动 onend 的续录）

// 把「base + 本次识别」写回输入框。超过字数上限时不再追加，避免把已有内容挤掉。
function applyVoiceText() {
  const recognized = voiceFinal + voiceInterim
  const needsGap = voiceBase && !/\s$/.test(voiceBase) && recognized
  const next = voiceBase + (needsGap ? ' ' : '') + recognized
  answerText.value = next.slice(0, VOICE_MAX_CHARS)
}

function handleVoiceResult(event) {
  voiceInterim = ''
  for (let i = event.resultIndex; i < event.results.length; i += 1) {
    const result = event.results[i]
    const piece = String(result?.[0]?.transcript || '')
    if (!piece) continue
    if (result.isFinal) voiceFinal += piece
    else voiceInterim += piece
  }
  applyVoiceText()
}

function handleVoiceError(event) {
  const code = event?.error || ''
  if (code === 'not-allowed' || code === 'service-not-allowed') {
    ElMessage.warning('麦克风权限被拒绝：请在地址栏的权限设置里允许麦克风后重试，或直接打字作答')
  } else if (code === 'audio-capture') {
    ElMessage.warning('没有找到可用的麦克风，请直接打字作答')
  } else if (code === 'network') {
    ElMessage.warning('语音识别服务网络异常，已说的内容已保留，可以打字继续')
  } else if (code === 'aborted') {
    // 主动停止会触发 aborted，属正常流程，不提示
  } else if (code === 'no-speech') {
    ElMessage.info('没有听到声音，可以再试一次或直接打字')
  }
  // 其余错误码不逐个解释：识别已中断，已有文本保留，提示一句即可
}

function releaseVoiceRec() {
  const current = voiceRec
  voiceRec = null
  if (!current) return
  current.onresult = null
  current.onerror = null
  current.onend = null
}

function handleVoiceEnd() {
  // 学生没有主动停止、且页面仍在录音状态：Chrome 单段识别约 60 秒会自动结束，这里续录
  if (!voiceStopRequested && voice.value.listening && voiceRec) {
    try {
      voiceRec.start()
      return
    } catch {
      /* 已在运行时 start 会抛错，落到下面按结束处理 */
    }
  }
  // 结束：最终文本已通过 applyVoiceText 写入输入框，原样保留，不做清空
  releaseVoiceRec()
  voice.value.listening = false
  voiceFinal = ''
  voiceInterim = ''
  voiceBase = ''
}

function startVoice() {
  if (!voiceSupported || voice.value.listening) return
  let instance
  try {
    instance = new SpeechCtor()
  } catch {
    ElMessage.error('当前浏览器无法启动语音识别，请打字作答')
    return
  }
  instance.lang = 'zh-CN'
  instance.continuous = true
  instance.interimResults = true
  instance.onresult = handleVoiceResult
  instance.onerror = handleVoiceError
  instance.onend = handleVoiceEnd

  voiceBase = answerText.value
  voiceFinal = ''
  voiceInterim = ''
  voiceStopRequested = false
  voiceRec = instance
  try {
    instance.start()
  } catch {
    releaseVoiceRec()
    ElMessage.error('麦克风启动失败，请检查浏览器权限后重试，或直接打字作答')
    return
  }
  voice.value.listening = true
}

function stopVoice() {
  if (!voice.value.listening) return
  voiceStopRequested = true
  const current = voiceRec
  if (!current) {
    handleVoiceEnd()
    return
  }
  try {
    current.stop()
  } catch {
    handleVoiceEnd()
  }
}

function toggleVoice() {
  if (voice.value.listening) stopVoice()
  else startVoice()
}

// 报告页的题目出处表：题库题给链接，模板题明确标注，不含糊
const reportSources = computed(() => (report.value && report.value.sources) || [])

async function loadResume() {
  const { data } = await http.get('/interview/resume/me')
  resume.value = data.resume
}

async function parseText() {
  parsing.value = true
  try {
    const { data } = await http.post('/interview/resume/parse', { text: pasteText.value })
    parsed.value = data.parsed
  } finally {
    parsing.value = false
  }
}

function useResumeTemplate() {
  pasteText.value = activeTemplate.value.content
  ElMessage.success('模板已填入，请用真实经历替换方括号提示后再润色')
}

async function rewriteResume() {
  rewriteLoading.value = true
  try {
    const { data } = await http.post('/interview/resume/rewrite', {
      text: pasteText.value, target_job: rewriteTarget.value || null,
    })
    rewrittenText.value = data.rewritten_text
    ElMessage.success('AI 润色完成，原文数字已校验；请检查后再保存')
  } finally {
    rewriteLoading.value = false
  }
}

async function onFile(ev) {
  const file = ev.target.files[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  parsing.value = true
  try {
    const { data } = await http.post('/interview/resume/upload', fd,
      { headers: { 'Content-Type': 'multipart/form-data' } })
    parsed.value = data.parsed
    ElMessage.success('解析成功，请确认后保存')
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    parsing.value = false
  }
}

async function saveParsed() {
  saving.value = true
  try {
    const p = parsed.value
    const skills = (p.skills || []).map((s) => ({ type: 'skill', name: s }))
    const certs = (p.certs || []).map((c) => ({ type: 'cert', name: c.name, level: c.level }))
    const exps = (p.experiences || []).map((e) => ({
      type: e.type || 'project', name: e.name, desc: e.desc || e.name, dates: e.dates
    }))
    const edus = (p.educations || []).map((e) => ({
      school: e.school, major: e.major, dates: e.dates
    }))
    await http.post('/interview/resume', {
      self_eval: p.self, educations: edus, skills: [...skills, ...certs], experiences: exps,
      raw_text: pasteText.value || null
    })
    ElMessage.success('简历已保存')
    parsed.value = null
    await loadResume()
  } finally {
    saving.value = false
  }
}

async function saveForm() {
  saving.value = true
  try {
    const f = form.value
    const exp = f.exp ? f.exp.split('\n').filter(Boolean).map((line) => ({
      type: /实习/.test(line) ? 'intern' : /竞赛|比赛/.test(line) ? 'contest' : 'project',
      name: line.split('｜')[0], desc: line
    })) : []
    const skills = f.skills.split('、').map((s) => s.trim()).filter(Boolean)
      .map((s) => (/CET|证|等级/.test(s) ? { type: 'cert', name: s } : { type: 'skill', name: s }))
    const edu = f.edu ? f.edu.split('｜') : []
    await http.post('/interview/resume', {
      self_eval: f.self || null, intent: f.intent || null,
      educations: edu.length ? [{ school: edu[0], major: edu[1] || null, dates: edu[2] || null }] : [],
      skills, experiences: exp
    })
    ElMessage.success('简历已保存')
    await loadResume()
  } finally {
    saving.value = false
  }
}

async function runDiagnosis() {
  diagLoading.value = true
  try {
    const q = jobId.value ? `?job_id=${jobId.value}` : ''
    const { data } = await http.get(`/interview/resume/diagnosis${q}`)
    diagnosis.value = data
  } finally {
    diagLoading.value = false
  }
}

async function loadJobs() {
  jobLoading.value = true
  try {
    const { data } = await http.get('/interview/jobs', {
      params: { pool: jobPool.value, limit: 50, keyword: jobKeyword.value,
        city: jobCity.value, industry: jobIndustry.value }
    })
    jobs.value = data.items
    jobTotal.value = data.total
  } finally {
    jobLoading.value = false
  }
}

async function loadFacets() {
  const { data } = await http.get('/interview/jobs/facets')
  facets.value = data
  jobTotal.value = jobTotal.value || data.total
}

async function loadHistory() {
  const { data } = await http.get('/interview/history/me')
  history.value = data.items
}

async function startInterview() {
  starting.value = true
  try {
    const { data } = await http.post('/interview/start', {
      job_id: jobId.value, job_pool: jobPool.value, mode: interviewMode.value
    })
    const job = jobs.value.find((j) => j.id === jobId.value)
    jobTitle.value = job ? job.title : ''
    // mode 以接口回传为准；mode_label 缺失时为 null，徽标不显示（不用前端选项名冒充）
    session.value = { round: data.round, total: data.total_rounds, question: data.question,
      type: data.question_type, label: data.question_label, id: data.session_id,
      source: data.source || null, isProbe: false,
      personalized: data.personalized || null,
      mode: data.mode || interviewMode.value, modeLabel: data.mode_label || null }
    report.value = null
    evaluation.value = {}
    lastComment.value = null
    pendingNext.value = null
    commentError.value = null
    answerText.value = ''
    diagnosis.value = null
    startQuestionClock()   // 题目出现即开始计时
  } finally {
    starting.value = false
  }
}

// 提交/跳过共用入口：expected_round 取当前展示题号（1-based），服务端据此拒绝双击或
// 旧页面的过期请求（409）。answering 同时承担按钮 loading 与函数级防重入，先于任何 await 置位。
// 流程：停表 → 请求（期间点评区是骨架屏）→ 只展示点评，下一题暂存，等学生点「下一题」。
// retryElapsed：出错重试时传入首次提交停表得到的用时（那时表已停，重试不能再停一次）
async function submitAnswer(real, retryElapsed = null) {
  if (answering.value || commentPending.value || pendingNext.value) return
  const sid = session.value?.id
  const expectedRound = session.value?.round
  if (!sid || !expectedRound) return
  // 录音中点提交：先停录音。输入框里已是「已打字 + 已识别」的全部内容，按所见提交。
  if (voice.value.listening) stopVoice()
  const submittedText = real ? answerText.value : null
  const elapsed = retryElapsed || stopQuestionClock()   // 提交即停表
  answering.value = true
  commentPending.value = true
  commentError.value = null
  try {
    const { data } = await http.post(`/interview/${sid}/answer`,
      { text: submittedText, expected_round: expectedRound })
    if (data.finished) {
      commentPending.value = false
      report.value = data
      evaluation.value = data.evaluation || {}
      session.value = null
      lastComment.value = null
      pendingNext.value = null
      await loadHistory()
      return
    }
    // 接口若回传用时则优先用它的，否则用前端停表结果
    lastComment.value = { text: data.comment, score: data.score, version: data.comment_version,
      elapsed: data.elapsed_time || data.elapsed || elapsed }
    pendingNext.value = { ...session.value, round: data.next.round, question: data.next.question,
      type: data.next.question_type, source: data.next.source || null,
      total: data.total_rounds || session.value.total,
      isProbe: !!data.next.is_probe, probeOf: data.next.probe_of || null }
    if (data.probed) ElMessage.info('这道题答得比较浅，面试官追加了一道追问')
    answerText.value = ''
  } catch (e) {
    // 冲突：服务端已不在我们以为的那一轮，按 GET 的真实状态恢复，不让用户猜是否提交成功
    if (e?.response?.status === 409) {
      commentPending.value = false
      await recoverFromConflict(sid, expectedRound)
      return
    }
    // 其它错误：点评区显示人话 + 重试按钮；未提交的答案原样保留
    commentPending.value = false
    commentError.value = {
      ...friendlyError(e),
      retry: () => submitAnswer(real, elapsed || null),
    }
    answerText.value = real ? (answerText.value || submittedText || '') : answerText.value
  } finally {
    answering.value = false
  }
}

function retryLastAction() {
  const retry = commentError.value?.retry
  commentError.value = null
  if (retry) retry()
}

function reloadPage() {
  window.location.reload()
}

// 「下一题」：把暂存的下一题真正换上来，并开始新一题的计时
function goNextQuestion() {
  const next = pendingNext.value
  if (!next) return
  if (voice.value.listening) stopVoice()   // 换题前收尾录音，避免旧识别回调把内容写进新题
  session.value = next
  pendingNext.value = null
  commentError.value = null
  answerText.value = ''
  startQuestionClock()
}

// 409 恢复：以 GET /interview/{sid} 为准。服务器确实推进了才清掉过期答案；
// 仍停在本题（重复请求被拒但尚未推进）则保留学生已写的内容，避免丢答案。
async function recoverFromConflict(sid, expectedRound) {
  try {
    const { data } = await http.get(`/interview/${sid}`)
    const completed = Number(data.session?.['当前轮次']) || 0
    const serverRound = completed + 1
    if (data.session?.['状态'] === 'ongoing') {
      const next = data.outline?.[completed]
      if (!next) {
        commentError.value = { text: '页面数据已更新，请刷新后继续。', action: 'reload' }
        ElMessage.warning('冲突已确认，但暂时无法恢复本题，请刷新页面后重试（答案已保留）')
        return
      }
      const previous = data.qa?.at(-1)
      session.value = {
        id: sid, round: serverRound,
        total: data.session['最大轮次'] || data.outline.length,
        question: next.question, type: next.type, label: labelOf(next.type),
        source: next.source || null, isProbe: !!next.probe_of, probeOf: next.probe_of || null,
        mode: data.mode || 'standard', modeLabel: data.mode_label || null,
      }
      // 从服务器恢复：前端没有这道题的开始时间，用时如实留空（elapsed 不给）
      lastComment.value = previous?.点评
        ? { text: previous['点评'], score: previous['评分'], version: previous['点评版本'], elapsed: null }
        : null
      pendingNext.value = null
      commentError.value = null
      startQuestionClock()   // 恢复出来的题从此刻重新计时
      if (serverRound > expectedRound) {
        answerText.value = ''
        ElMessage.success(`刚才的回答已提交，已同步到第 ${serverRound} 题，请作答新题`)
      } else {
        ElMessage.info('本次提交未生效，已按服务器状态复位到本题，答案已保留可重新提交')
      }
      return
    }

    // 已收卷：加载结构化评估 + 报告，避免学生猜测刚才那次是否提交成功
    let eva = {}
    try {
      const { data: ed } = await http.get(`/interview/${sid}/evaluation`)
      eva = ed.evaluation || {}
    } catch {
      ElMessage.warning('结构化复盘暂时不可用，仍可查看报告原文')
    }
    report.value = { total: data.session['总分'], report: data.session['报告'] || '(报告为空)', gaps: [],
      sources: (data.outline || []).map((o) => ({
        round: o.round, type: o.type, label: labelOf(o.type),
        question: o.question, kind: (o.source || {}).kind || 'template',
        name: (o.source || {}).name || '模板出题', url: (o.source || {}).url, bank_id: (o.source || {}).id,
        is_probe: !!o.probe_of,
      })) }
    evaluation.value = eva
    session.value = null
    lastComment.value = null
    pendingNext.value = null
    commentError.value = null
    stopQuestionClock()
    answerText.value = ''
    jobTitle.value = data.session['岗位名称'] || jobTitle.value
    ElMessage.success('本场面试已结束，已为你加载评估报告，可在逐题复盘中核对刚才的回答是否已计入')
    await loadHistory()
  } catch {
    // 恢复本身失败（网络等）：保留当前题与未提交答案，点评区给出可执行的下一步
    stopQuestionClock()
    commentError.value = { text: '页面数据已更新，请刷新后继续。', action: 'reload' }
    ElMessage.warning('冲突状态恢复失败，未提交答案已保留，请刷新页面后重试')
  }
}

async function openHistory(row) {
  if (session.value) {
    ElMessage.info('请先完成当前进行中的面试，再切换历史场次')
    return
  }
  openingSession.value = row['编号']
  try {
    const { data } = await http.get(`/interview/${row['编号']}`)
    jobTitle.value = data.session['岗位名称'] || ''
    tab.value = 'interview'
    if (data.session['状态'] === 'ongoing') {
      const completed = Number(data.session['当前轮次']) || 0
      const next = data.outline?.[completed]
      if (!next) {
        ElMessage.warning('这场面试暂时无法恢复，请刷新历史记录后重试')
        return
      }
      const previous = data.qa?.at(-1)
      session.value = {
        id: data.session['编号'], round: completed + 1,
        total: data.session['最大轮次'] || data.outline.length,
        question: next.question, type: next.type, label: labelOf(next.type),
        source: next.source || null, isProbe: !!next.probe_of, probeOf: next.probe_of || null,
        mode: data.mode || 'standard', modeLabel: data.mode_label || null,
      }
      // 从服务器恢复：这道题的开始时间前端没有，用时如实留空
      lastComment.value = previous?.点评
        ? { text: previous['点评'], score: previous['评分'], version: previous['点评版本'], elapsed: null }
        : null
      pendingNext.value = null
      commentError.value = null
      answerText.value = ''
      report.value = null
      evaluation.value = {}
      startQuestionClock()   // 恢复出来的题从此刻重新计时
      ElMessage.success(`已恢复到第 ${completed + 1} 题，可以继续作答`)
      return
    }

    // 结构化评估与收卷同一引擎重算，结果与当时一致
    let eva = {}
    try {
      const { data: ed } = await http.get(`/interview/${row['编号']}/evaluation`)
      eva = ed.evaluation || {}
    } catch {
      ElMessage.warning('结构化复盘暂时不可用，仍可查看报告原文')
    }
    report.value = { total: data.session['总分'], report: data.session['报告'] || '(报告为空)', gaps: [],
      sources: (data.outline || []).map((o) => ({
        round: o.round, type: o.type, label: labelOf(o.type),
        question: o.question, kind: (o.source || {}).kind || 'template',
        name: (o.source || {}).name || '模板出题', url: (o.source || {}).url, bank_id: (o.source || {}).id,
        is_probe: !!o.probe_of,
      })) }
    evaluation.value = eva
    session.value = null
    lastComment.value = null
    pendingNext.value = null
    commentError.value = null
  } finally {
    openingSession.value = null
  }
}

function resetInterview() {
  report.value = null
  evaluation.value = {}
  session.value = null
  lastComment.value = null
  pendingNext.value = null
  commentError.value = null
  jobId.value = null
  jobTitle.value = ''
  if (voice.value.listening) stopVoice()
  stopQuestionClock()
}

// ---- 结束本场：确认后调用 abandon；接口未上线（404）时如实提示并保持可重试 ----
async function confirmAbandon() {
  const sid = session.value?.id
  if (!sid || abandoning.value) return
  try {
    await ElMessageBox.confirm(
      '结束本场后，这道题的作答不会计入，已答题目仍可在历史场次里查看。确定现在结束吗？',
      '结束本场面试',
      { confirmButtonText: '确定结束', cancelButtonText: '继续作答', type: 'warning',
        confirmButtonClass: 'el-button--primary' }
    )
  } catch {
    return   // 点了「继续作答」或关掉弹窗：什么都不做
  }
  abandoning.value = true
  try {
    await http.post(`/interview/${sid}/abandon`)
    ElMessage.success('本场面试已结束')
    router.push('/student/interview')
  } catch (e) {
    if (e?.response?.status === 404) {
      // 接口尚未上线：不离开页面、不改会话状态，学生可以继续作答或稍后再试
      ElMessageBox.alert('该功能即将上线', '暂时无法结束本场', {
        confirmButtonText: '知道了',
        callback: () => {},
      }).catch(() => {})
      return
    }
    if (e?.response?.status === 401) return   // 拦截器已处理登录失效
    commentError.value = { ...friendlyError(e), action: 'reload' }
  } finally {
    abandoning.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadResume(), loadJobs(), loadFacets(), loadHistory()])
})

onBeforeUnmount(() => {
  stopQuestionClock()
  // 离开页面时直接释放识别实例：不续录、不走正常收尾，并真正中止会话，放开麦克风
  voiceStopRequested = true
  voice.value.listening = false
  const current = voiceRec
  releaseVoiceRec()
  try {
    current?.abort()
  } catch {
    /* 已结束的实例 abort 会抛错，忽略 */
  }
})
</script>

<style scoped>
.page { display: block; }
/* 说明面板：白底 + 细边，与全站卡片同一容器语言；只保留一层极淡的
   左上角靛蓝提亮，避免整块纯白显得空。 */
.iv-hero {
  display: flex; align-items: center; justify-content: space-between; gap: 28px;
  padding: 22px 26px; margin-bottom: 16px; border-radius: 14px;
  border: 1px solid #e7eaf1;
  background: linear-gradient(180deg, #fbfcff 0%, #ffffff 68%);
  box-shadow: 0 1px 2px rgba(16, 24, 40, .04);
}
.hero-copy { min-width: 0; }
.hero-copy h1 { margin: 0 0 6px; font-size: 21px; font-weight: 680; letter-spacing: -.02em; color: var(--qh-text); }
.hero-copy p { margin: 0; max-width: 660px; color: var(--qh-text-sub); font-size: 13.5px; line-height: 1.7; }
.hero-status { display: flex; flex-direction: column; align-items: stretch; gap: 6px; min-width: 176px; }
.status-chip { display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px;
  border: 1px solid #e7eaf1; border-radius: 999px; background: #fff;
  color: var(--qh-text-sub); font-size: 12.5px; font-weight: 500; white-space: nowrap; }
.status-chip.on { border-color: #dfe7f7; background: #f6f9ff; color: #1f4fa8; }
.status-dot { width: 7px; height: 7px; flex: none; border-radius: 50%; background: #e2b04a; }
.status-dot.ready { background: #14a06f; }
.setup-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.setup-card-head p { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.5; }
.status-dot { width: 7px; height: 7px; flex: none; border-radius: 50%; background: #e2b04a; }
.status-dot.ready { background: #14a06f; }
.card-title { font-weight: 600; }
.mt8 { margin-top: 8px; }
.muted { color: var(--el-text-color-secondary); font-size: 13.5px; }
.kv { display: flex; gap: 8px; margin: 6px 0; font-size: 14px; align-items: baseline; }
.kv .k { color: var(--el-text-color-secondary); flex: none; width: 34px; }
/* 经历列表必须是块级整体：直接把 v-for 项当 .kv 的 flex 子项会互相挤压成
   一条条竖排单字列（把卡片撑到天高），包一层拿走剩余宽度即回归正常流 */
.exp-list { flex: 1; min-width: 0; }
.exp-item { margin: 2px 0; }
/* 长内容卡（当前简历 / 简历诊断）体高封顶内部滚动：
   不再把同行卡片拉伸出大片空白（bento 网格行高 = 行内最高者） */
.cap-body :deep(.el-card__body) {
  max-height: 540px;
  overflow-y: auto;
}
.head-row { display: flex; align-items: center; gap: 8px; }
.hist-table { --el-table-text-color: #374151; font-size: 13px; }
/* 「结果」列：分数为主、状态为辅，两行不换行不撑宽 */
.hist-result { display: inline-flex; align-items: baseline; gap: 5px; white-space: nowrap; }
.hist-result b { font-weight: 650; color: #111827; font-variant-numeric: tabular-nums; }
.hist-result i { font-style: normal; font-size: 12px; color: #6b7280; }
.hist-result.ongoing b { color: #1f4fa8; }
.hist-table :deep(.el-table__cell) { padding: 8px 0; }
.question-label { display: flex; align-items: center; gap: 10px; margin: 18px 0 6px; color: #245da6; font-size: 13px; font-weight: 700; }
.personalized-strip { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 10px; }
.question-label span { color: var(--el-text-color-secondary); font-weight: 400; }
.question { font-size: 18px; font-weight: 650; margin-bottom: 16px; line-height: 1.75; color: var(--el-text-color-primary); }
.q-source { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin: -2px 0 12px; font-size: 13.5px; color: #6b7280; }
.q-source .src-txt a { color: #1951c3; text-decoration: none; }
.q-source .src-txt a:hover { text-decoration: underline; }
.comment { line-height: 1.7; font-size: 14px; }

/* ===== 点评卡：等待态 / 错误态 / 空态 / 底部「下一题」 ===== */
.end-button { margin-left: auto; }
.question-clock { display: inline-flex; align-items: center; gap: 4px; color: #245da6;
  font-variant-numeric: tabular-nums; }
.question-clock svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.8;
  stroke-linecap: round; stroke-linejoin: round; }
.comment-card.is-waiting :deep(.el-card__body) { min-height: 196px; }
.comment-waiting { padding: 4px 0 8px; }
/* 骨架屏：与正文同宽的两行灰块，浅靛蓝呼吸，不抢眼 */
.skeleton-block { height: 16px; margin: 12px 0; border-radius: 6px;
  background: linear-gradient(90deg, #eef2f8 25%, #e3eaf6 37%, #eef2f8 63%);
  background-size: 400% 100%; animation: skeleton-shimmer 1.4s ease infinite; }
.skeleton-block.is-short { width: 62%; }
@keyframes skeleton-shimmer { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }
.waiting-text { display: flex; align-items: center; gap: 8px; margin: 16px 0 0;
  color: var(--el-text-color-secondary); font-size: 13.5px; }
/* 三个点的「正在思考」动画 */
.thinking-dots { display: inline-flex; gap: 3px; }
.thinking-dots i { width: 5px; height: 5px; border-radius: 50%; background: #245da6;
  animation: thinking-bounce 1.2s ease-in-out infinite; }
.thinking-dots i:nth-child(2) { animation-delay: .15s; }
.thinking-dots i:nth-child(3) { animation-delay: .3s; }
@keyframes thinking-bounce { 0%, 60%, 100% { transform: translateY(0); opacity: .45; }
  30% { transform: translateY(-3px); opacity: 1; } }
.comment-empty { padding: 14px 0 4px; color: var(--el-text-color-secondary); font-size: 13.5px; }
/* 错误态：浅琥珀底 + 一句人话 + 一个动作，不出现后端原文 */
.comment-error { margin: 8px 0; padding: 14px 16px; border: 1px solid #f4d7a1; border-radius: 12px;
  background: #fffaf0; }
.comment-error p { margin: 0; color: #8a5a13; font-size: 14px; line-height: 1.6; }
.comment-error-actions { display: flex; gap: 8px; margin-top: 10px; }
/* 底部「下一题」：点评渲染完才出现，靠右贴边，与上方正文用细线分隔 */
.comment-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  margin-top: 18px; padding-top: 14px; border-top: 1px dashed #e5eaf3; }
.comment-footer-hint { color: var(--el-text-color-secondary); font-size: 13px; }
.comment-footer :deep(.el-button) { min-height: 38px; padding-inline: 22px; }

/* ===== 面试模式：三档卡片（单选） ===== */
.mode-field { margin: 4px 0 16px; }
.mode-field-head { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; }
.mode-field-head .field-label { margin-bottom: 8px; }
.mode-field-note { color: var(--el-text-color-secondary); font-size: 12.5px; }
.mode-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.mode-card {
  display: flex; flex-direction: column; gap: 6px; padding: 12px 14px; text-align: left;
  font: inherit; color: var(--el-text-color-regular); cursor: pointer;
  border: 1.5px solid #e7eaf1; border-radius: 12px; background: #fff;
  transition: border-color .18s ease, background-color .18s ease, box-shadow .18s ease;
}
.mode-card:hover:not(:disabled) { border-color: #b9cdf0; }
.mode-card:focus-visible { outline: 2px solid #1951c3; outline-offset: 2px; }
.mode-card:disabled { cursor: not-allowed; opacity: .6; }
.mode-card.active { border-color: #1951c3; background: #f3f7ff; box-shadow: 0 0 0 3px rgba(25, 81, 195, .08); }
.mode-card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.mode-card-top b { font-size: 15px; color: var(--el-text-color-primary); }
.mode-card.active .mode-card-top b { color: #1951c3; }
/* 选中标记：空心圆 → 实心带勾，状态不只靠颜色表达 */
.mode-check { width: 16px; height: 16px; flex: none; border-radius: 50%;
  border: 1.5px solid #c4cad6; background: #fff; transition: border-color .18s ease, background-color .18s ease; }
.mode-card.active .mode-check { border-color: #1951c3; background: #1951c3;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M4 8.3l2.6 2.6L12 5.4' fill='none' stroke='%23fff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: center; }
.mode-card-desc { font-size: 13px; line-height: 1.5; color: var(--el-text-color-secondary); }
.mode-card-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 2px; }
.mode-card-tags span { padding: 1px 7px; border-radius: 999px; background: #f1f4f9;
  color: #536680; font-size: 11.5px; line-height: 1.7; white-space: nowrap; }
.mode-card.active .mode-card-tags span { background: #e6eefb; color: #245da6; }
.mode-badge { margin-left: 2px; }

/* ===== 压力模式单题倒计时：环形进度 + 剩余秒数 ===== */
.countdown { display: inline-flex; align-items: center; gap: 6px; margin-left: auto;
  padding: 2px 10px 2px 4px; border: 1px solid #f4d7a1; border-radius: 999px; background: #fffaf0;
  color: #8a5a13; font-size: 12.5px; font-weight: 600; font-variant-numeric: tabular-nums; }
.countdown-ring { width: 22px; height: 22px; flex: none; transform: rotate(-90deg); }
.countdown-ring circle { fill: none; stroke-width: 3.4; }
.countdown-ring .ring-track { stroke: #f1dcb4; }
.countdown-ring .ring-value { stroke: #c98900; stroke-linecap: round; transition: stroke-dasharray .9s linear, stroke .3s ease; }
.countdown.is-low { border-color: #f1b9b3; background: #fdf3f2; color: #a12d22; }
.countdown.is-low .ring-value { stroke: #d83b32; }
.countdown.is-up { border-color: #f1b9b3; background: #fdf3f2; color: #a12d22; }
.countdown.is-up .ring-value { stroke: transparent; }

/* ===== 语音作答 ===== */
.voice-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; margin-top: 8px; }
.voice-btn {
  display: inline-flex; align-items: center; gap: 7px; min-height: 34px; padding: 0 14px;
  font: inherit; font-size: 13px; font-weight: 500; cursor: pointer;
  color: #245da6; border: 1px solid #cddcf3; border-radius: 999px; background: #f7faff;
  transition: background-color .18s ease, border-color .18s ease, color .18s ease;
}
.voice-btn:hover:not(:disabled) { border-color: #245da6; background: #eef4ff; }
.voice-btn:focus-visible { outline: 2px solid #1951c3; outline-offset: 2px; }
.voice-btn:disabled { cursor: not-allowed; color: #a3acb9; border-color: #e7eaf1; background: #f7f8fa; }
.voice-icon { display: grid; place-items: center; width: 18px; height: 18px; }
.voice-icon svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.8;
  stroke-linecap: round; stroke-linejoin: round; }
/* 录音中：主色实底 + 四根跳动波形；同时有「停止录音」文字，状态不只靠动效表达 */
.voice-btn.is-recording { color: #fff; border-color: #1951c3; background: #1951c3; }
.voice-btn.is-recording:hover { background: #123a8f; border-color: #123a8f; }
.voice-wave { display: inline-flex; align-items: center; gap: 2px; height: 14px; }
.voice-wave i { width: 3px; height: 6px; border-radius: 2px; background: #fff;
  animation: voice-bounce 1s ease-in-out infinite; }
.voice-wave i:nth-child(2) { animation-delay: .12s; }
.voice-wave i:nth-child(3) { animation-delay: .24s; }
.voice-wave i:nth-child(4) { animation-delay: .36s; }
@keyframes voice-bounce { 0%, 100% { height: 5px; opacity: .65; } 50% { height: 14px; opacity: 1; } }
.voice-status { color: #245da6; font-size: 12.5px; }
.voice-status.is-muted { color: var(--el-text-color-secondary); }
.report { white-space: pre-wrap; font-family: inherit; font-size: 14px; line-height: 1.8; margin: 0; }
.diag-item { margin: 10px 0; font-size: 14px; line-height: 1.6; }
.rewrite { color: var(--el-color-success); margin-top: 4px; }
.howto { margin: 0; padding-left: 18px; font-size: 14px; line-height: 1.8; color: var(--el-text-color-regular); }
.howto b { color: var(--el-text-color-primary); }
.field-label { display: block; margin: 12px 0 6px; color: var(--el-text-color-primary); font-size: 14px; font-weight: 600; }
.flow-steps { display: flex; align-items: center; gap: 10px; margin: 0 0 20px; }
.flow-step { display: flex; align-items: center; gap: 8px; color: var(--el-text-color-secondary); white-space: nowrap; font-size: 13px; }
.flow-step span { width: 26px; height: 26px; display: grid; place-items: center; border-radius: 50%; background: #eef2f7; font-size: 12px; font-weight: 700; }
.flow-step.done span, .flow-step.active span { color: #fff; background: #2465b7; }
.flow-step.done b, .flow-step.active b { color: var(--el-text-color-primary); }
.flow-line { height: 1px; flex: 1; min-width: 12px; background: var(--el-border-color-lighter); }
.resume-needed { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin: 0 0 16px; padding: 13px 14px; border: 1px solid #f4d7a1; border-radius: 12px; background: #fffaf0; }
.resume-needed div { display: grid; gap: 3px; }
.resume-needed b { color: #8a5a13; font-size: 14px; }
.resume-needed span { color: #9a7a42; font-size: 13px; }
.start-button { margin-top: 12px; min-height: 42px; padding-inline: 22px; }
.agent-flow { padding: 13px 14px; border: 1px solid #dbe7fb; border-radius: 12px; background: linear-gradient(135deg, #f4f8ff, #fbfdff); }
.agent-flow-title { display: flex; align-items: center; gap: 7px; color: #245da6; font-size: 13.5px; font-weight: 700; }
.agent-pulse { width: 8px; height: 8px; border-radius: 50%; background: #2d72db; box-shadow: 0 0 0 4px rgba(45,114,219,.14); }
.agent-flow-steps { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 9px; color: #536680; font-size: 13px; }
.agent-flow-steps i { color: #9bb4d8; font-style: normal; }
.template-preview { margin-top: 12px; padding: 12px 14px; border: 1px solid #e5eaf3; border-radius: 12px; background: #f8faff; }
.template-preview b { color: #245da6; }
.template-preview p { margin: 4px 0 8px; color: var(--el-text-color-secondary); font-size: 13px; }
.template-preview pre, .rewrite-result pre { max-height: 220px; margin: 0; overflow: auto; white-space: pre-wrap; font: 13px/1.65 inherit; color: var(--el-text-color-regular); }
.resume-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.rewrite-result { margin-top: 14px; padding: 14px; border: 1px solid #cdebdc; border-radius: 12px; background: #f5fcf8; }
.rewrite-result-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #267653; }
.rewrite-result p { margin: 8px 0 0; color: #5e7c6d; font-size: 13px; }
.progress-heading { display: flex; justify-content: space-between; gap: 12px; margin: 6px 0 8px; color: var(--el-text-color-secondary); font-size: 13px; }
.progress-heading b { color: #245da6; font-size: 14px; }
.job-select { width: 360px; }
.job-filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.job-kw { width: 260px; }
.job-filter { width: 160px; }
.probe-tag { margin-left: 8px; vertical-align: 1px; }
.iv-progress { margin-bottom: 12px; }
.agent-live-strip { display: flex; align-items: center; gap: 9px; margin: 0 0 14px; padding: 9px 11px; border: 1px solid #dce8fa; border-radius: 10px; background: #f7faff; color: #536680; font-size: 13px; line-height: 1.5; }
.agent-live-strip > span:nth-child(2) { flex: 1; }
.agent-live-strip b { color: #245da6; }
.agent-live-mark { display: grid; place-items: center; width: 26px; height: 26px; flex: none; border-radius: 8px; background: #245da6; color: #fff; font-size: 11px; font-weight: 700; }
.practice-disclaimer {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin: 0 0 18px;
  padding: 9px 12px;
  border: 1px solid #dce8f5;
  border-radius: 10px;
  background: #f7faff;
  color: #4a5b76;
  font-size: 13px;
  line-height: 1.6;
}

.practice-disclaimer svg {
  width: 15px;
  height: 15px;
  flex: 0 0 15px;
  margin-top: 2px;
  fill: none;
  stroke: #315db1;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.report-disclaimer {
  margin: 14px 0 0;
  padding-top: 10px;
  border-top: 1px dashed #e5eaf3;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.iv-tabs :deep(.el-tabs__header) { margin-bottom: 20px; }

/* ===== 面试评估报告 ===== */
.report-hero { display: flex; gap: 28px; align-items: center; flex-wrap: wrap; }
.score-ring { position: relative; width: 128px; height: 128px; flex: none; }
.score-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.ring-bg { fill: none; stroke: #e5e7eb; stroke-width: 10; }
.ring-fg { fill: none; stroke-width: 10; stroke-linecap: round; transition: stroke-dasharray .6s; }
.score-ring.good .ring-fg { stroke: #10b981; }
.score-ring.mid .ring-fg { stroke: #f59e0b; }
.score-ring.low .ring-fg { stroke: #ef4444; }
.ring-text { position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; }
.ring-text b { font-size: 30px; line-height: 1.1; }
.ring-text span { font-size: 13.5px; color: #6b7280; }
.hero-facts { flex: 1; min-width: 260px; display: flex; flex-direction: column; gap: 12px; }
.fact-row { display: flex; gap: 14px; flex-wrap: wrap; font-size: 14px; color: #374151; }
.fact b { color: #111827; }
.fact.warn { color: #b45309; }
.dim-bars { display: flex; flex-direction: column; gap: 6px; }
.dim-row { display: flex; align-items: center; gap: 10px; font-size: 13.5px; }
.dim-label { flex: none; width: 64px; color: #6b7280; }
.dim-track { flex: 1; height: 8px; border-radius: 4px; background: #f1f5f9; overflow: hidden; }
.dim-fill { height: 100%; border-radius: 4px; }
.dim-fill.good { background: #10b981; }
.dim-fill.mid { background: #f59e0b; }
.dim-fill.low { background: #ef4444; }
.dim-val { flex: none; width: 44px; text-align: right; color: #374151; }

.report-sec { margin-top: 22px; }
.sec-title { font-weight: 600; font-size: 14px; margin-bottom: 10px; }
.problem-item { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
  padding: 8px 0; border-bottom: 1px dashed #f1f5f9; font-size: 14px; }
.problem-dim { font-weight: 600; }
.problem-txt { color: #374151; }
.problem-action { width: 100%; color: #059669; font-size: 13.5px; padding-left: 42px; }

.plan-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.plan-card { border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px 14px;
  background: #f8fafc; }
.plan-when { font-size: 13.5px; color: #1951c3; font-weight: 600; }
.plan-focus { font-weight: 600; margin: 4px 0; }
.plan-action { font-size: 13.5px; color: #4b5563; line-height: 1.6; }

.qreview { border: 1px solid #eef2f7; border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; }
.qreview.probe { border-color: #fde68a; background: #fffbeb; }
.qreview.skipped { opacity: 0.72; }
.qreview-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.qreview-round { font-weight: 600; font-size: 14px; }
.qreview-question { margin: 8px 0; font-size: 14px; color: #111827; font-weight: 500; }
.qreview-comment { font-size: 14px; line-height: 1.8; color: #374151;
  border-left: 1px solid #93c5fd; padding-left: 10px; margin: 6px 0; }
.qreview-tags { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
.tag-muted { font-size: 13.5px; color: #6b7280; }

/* 窄屏：模式卡片折成单列，三档说明竖排更好读；倒计时独占一行不挤进度 */
@media (max-width: 640px) {
  .mode-grid { grid-template-columns: minmax(0, 1fr); }
  .countdown { margin-left: 0; }
}

@media (max-width: 768px) {
  .iv-hero { align-items: flex-start; flex-direction: column; gap: 16px; padding: 18px 16px; border-radius: 14px; }
  .hero-status { width: 100%; min-width: 0; flex-direction: row; flex-wrap: wrap; }
  .status-chip { flex: 1 1 auto; justify-content: center; }
  .flow-steps { gap: 6px; }
  .flow-step { gap: 5px; font-size: 12px; }
  .flow-step span { width: 24px; height: 24px; }
  .setup-card-head { flex-direction: column; }
  .resume-needed { align-items: flex-start; flex-direction: column; }
  .agent-flow-steps { line-height: 1.8; }
  .agent-live-strip { align-items: flex-start; flex-wrap: wrap; }
  .agent-live-strip > :deep(.el-tag) { margin-left: 35px; }
  .job-filters { display: grid; grid-template-columns: 1fr 1fr; }
  .job-kw { width: auto; grid-column: 1 / -1; }
  .job-filter { width: 100%; }
  .job-select { width: 100%; }
  .question { font-size: 17px; }
  .head-row { flex-wrap: wrap; }
  .head-row :deep(.el-button) { min-height: 42px; }
  .progress-heading { flex-wrap: wrap; }
  .comment-footer { flex-direction: column-reverse; align-items: stretch; }
  .comment-footer-hint { text-align: center; }
  .input-hint { margin-top: 6px; }
}

@media (max-width: 480px) {
  .hero-copy p { font-size: 15px; }
  .flow-step { flex-direction: column; align-items: center; text-align: center; white-space: normal; }
  .flow-line { align-self: center; margin-bottom: 18px; }
  .job-filters { grid-template-columns: 1fr; }
  .job-kw { grid-column: auto; }
  .question { font-size: 16px; }
  .iv-tabs :deep(.el-tabs__item) { font-size: 15px; }
}

@media (prefers-reduced-motion: reduce) {
  .iv-hero *, .score-ring *, .block-card { scroll-behavior: auto !important; transition-duration: .01ms !important; }
  /* 等待态的两段循环动画在「减少动态效果」下停掉，保留静态的骨架与三个点 */
  .skeleton-block, .thinking-dots i { animation: none !important; }
  .skeleton-block { background: #eef2f8; }
  .thinking-dots i { opacity: .8; }
  /* 录音波形同理停掉：按钮仍是主色实底并写着「停止录音」，状态不靠动效也能看出来 */
  .voice-wave i { animation: none !important; height: 9px; opacity: 1; }
  .countdown-ring .ring-value { transition: none !important; }
}
</style>
