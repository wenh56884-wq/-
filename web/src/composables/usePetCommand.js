// 宠物指令表 + 目标解析 + 路由直达。
// 用户说一句人话 → 匹配到一条指令 → 直接打开对应页面（或拉起 AI 抽屉）→ 宠物说一句话。
// 匹配靠关键词而不是 NLU：宠物要的是「说到就到」的确定性，猜错比不猜更烦人。
// 路由直达：seg 声明各角色下的路由段（与 web/src/router/index.js 保持一致），
// 没写 seg 的角色代表该端没有此页面（如教师端没有模拟面试/报考分析）。

// 角色 → 路由前缀；与学生/教师两棵路由树一一对应
const ROLE_PREFIX = { student: '/student', teacher: '/teacher' }

export const PET_COMMANDS = [
  { key: 'grades', label: '成绩单', words: ['成绩', '分数', '绩点', '成绩单'], line: '成绩单给你点开了，先看最近一次考试。', seg: { student: 'grades', teacher: 'grades' } },
  { key: 'jobs', label: '岗位库', words: ['岗位', '招聘', '找工作', '职位'], line: '岗位库打开了，看到合适的我可以帮你记下来。', seg: { student: 'jobs', teacher: 'jobs' } },
  { key: 'exams', label: '招考信息', words: ['招考', '考试', '公告', '报名'], line: '招考信息在这儿，报名别卡最后一天。', seg: { student: 'exams', teacher: 'exams' } },
  { key: 'interview', label: '模拟面试', words: ['面试', '模拟'], line: '面试间准备好了，深呼一口气再开口。', seg: { student: 'interview' } },
  { key: 'kg', label: '知识图谱', words: ['图谱', '知识点', '关系'], line: '知识图谱开好了，顺着连线看会更清楚。', seg: { student: 'kg', teacher: 'kg' } },
  { key: 'forecast', label: '学业预测', words: ['预测', '趋势', '学业'], line: '学业预测调出来了，趋势比单次分数有用。', seg: { student: 'forecast' } },
  { key: 'assessment', label: '职业测评', words: ['测评', '职业', '性格'], line: '测评入口在这儿，答完就有报告。', seg: { student: 'assessment' } },
  { key: 'career', label: '报考分析', words: ['报考', '分析', '院校'], line: '报考分析给你摊开了，先看冲稳保三档。', seg: { student: 'career' } },
  { key: 'profile', label: '我的画像', words: ['画像', '我的', '首页'], line: '回你的画像页，这里是你的全部进度。', seg: { student: '' } },
  { key: 'students', label: '学生档案', words: ['学生', '档案', '名单'], line: '学生档案在这儿，找谁都能翻到。', seg: { teacher: 'students' } },
  { key: 'approvals', label: '工作流审批', words: ['审批', '工作流', '待办'], line: '审批队列打开了，先处理快到期的。', seg: { teacher: 'approvals' } },
  { key: 'assistant', label: '问 AI', words: ['助手', '问', 'ai', '聊天'], action: 'ask', line: '我把对话拉起来，你直接问。' }
]

// 当前登录角色：登录态写死在 localStorage（与路由守卫同一来源）
export function currentRole() {
  return localStorage.getItem('qh_role') === 'teacher' ? 'teacher' : 'student'
}

// 用户输入 → 指令；空命中返回 null
export function matchCommand(text) {
  const q = String(text || '').trim().toLowerCase()
  if (!q) return null
  let best = null
  let bestScore = 0
  PET_COMMANDS.forEach((cmd) => {
    cmd.words.forEach((w) => {
      const word = w.toLowerCase()
      if (q.includes(word) && word.length > bestScore) {
        best = cmd
        bestScore = word.length
      }
    })
  })
  return best
}

// 当前角色可见的指令：有 seg 且该角色配了路由段的，或纯 ask 动作
export function visibleCommands(role = currentRole()) {
  return PET_COMMANDS.filter((cmd) => cmd.action === 'ask' || Boolean(cmd.seg?.[role]))
}

// 指令 → 目标路由；该角色没有此页面或纯 ask 动作时返回 null
export function resolveCommandPath(cmd, role = currentRole()) {
  const seg = cmd?.seg?.[role]
  if (seg === undefined) return null
  return seg ? `${ROLE_PREFIX[role]}/${seg}` : ROLE_PREFIX[role]
}
