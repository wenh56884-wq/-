// 抓取文本常见 HTML 实体的展示层解码（{{ }} 插值不解析 HTML，无 XSS 面）
export function decodeEntities(s) {
  return String(s ?? '')
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)))
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
}

// 在「中文句 → 英文整句」的分界处切一刀。要求尾巴以足够长的英文串开头，
// 避免「用 Excel 做报表」这种句中夹英文被误切；找不到就整段保留
function cutZhEn(c) {
  const re = /[\u4e00-\u9fa5][。！？]?\s*(?=[A-Za-z])/g
  let m
  while ((m = re.exec(c))) {
    const idx = m.index + m[0].length
    const head = c.slice(0, idx).trim()
    const tail = c.slice(idx).trim()
    if (!head || !tail) continue
    if (/^[A-Za-z][A-Za-z0-9 ,.'()\/&+-]{10,}/.test(tail)) return [head, tail]
  }
  return [c]
}

// 一条职责里常见「中文；English;」成对。先按分号切，再逐段找中英分界；
// 整段无中文且有英文的判为英文辅助行（保留原文字句，只拆分不改写）
function splitBilingual(text) {
  const out = []
  for (const raw of String(text).split(/(?<=[；;])/)) {
    const c = raw.replace(/[；;]\s*$/, '').trim()
    if (!c) continue
    out.push(...cutZhEn(c))
  }
  return out.filter(Boolean).map((t) => ({
    text: t,
    en: !/[\u4e00-\u9fa5]/.test(t) && /[A-Za-z]{3}/.test(t)
  }))
}

// 把抓来的职位介绍解析成 [{ heading, items: [{ no, parts }] }]
// 只做结构性切分，不改写原文任何字句；解析不出来就退化成单段纯文本
export function parseJd(raw) {
  let s = decodeEntities(raw).replace(/\r\n?/g, '\n').trim()
  if (!s) return []

  // 统一在前面补空白，保证行首的「1.」也能被切出来
  s = ' ' + s
  s = s.replace(/\s+(\d{1,2})[.、]\s+/g, '\n$1. ')
  s = s.replace(/\s*([A-Z][A-Z &/]{4,})[:：]\s*/g, '\n## $1\n')
  // 段首的中文小标签（隐私提示/备注之类）单独成段，不跟职责正文黏在一起
  s = s.replace(/\s+((?:隐私[^：:\s]{0,8}|备注|其他说明|温馨提示|特别说明))[：:]\s*/g, '\n## $1\n')

  const sections = []
  let cur = { heading: '', items: [] }

  for (const rawLine of s.split('\n')) {
    const line = rawLine.trim()
    if (!line) continue

    if (line.startsWith('## ')) {
      if (cur.heading || cur.items.length) sections.push(cur)
      cur = { heading: line.slice(3).trim(), items: [] }
      continue
    }

    const m = line.match(/^(\d{1,2})[.、]\s*(.+)$/s)
    if (m) {
      cur.items.push({ no: m[1], parts: splitBilingual(m[2]) })
    } else {
      cur.items.push({ no: '', parts: splitBilingual(line) })
    }
  }

  if (cur.heading || cur.items.length) sections.push(cur)
  return sections
}
