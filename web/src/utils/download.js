// 文件下载工具：带 JWT 请求二进制流 → 触发浏览器保存
// 为什么不用 window.open：下载接口要鉴权，新窗口不会带 Authorization 头，
// 只能由 axios 代发请求拿到 blob 再交给 <a download>。
import http from '../api/http'

/** 从 Content-Disposition 里解析真实文件名（优先 RFC 5987 的 UTF-8 实名） */
export function filenameFromDisposition(disposition, fallback = '导出文件') {
  if (!disposition) return fallback
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      /* 编码异常就退回 fallback */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1] : fallback
}

/**
 * 下载一个受鉴权保护的导出文件。
 * @param {string} url    接口路径，如 /export/students
 * @param {object} params 查询参数（class_name / term / fmt ...）
 * @param {string} fallback 服务端没给文件名时的兜底名
 * @returns {Promise<string>} 实际保存的文件名
 */
export async function downloadFile(url, params = {}, fallback = '导出文件') {
  const resp = await http.get(url, { params, responseType: 'blob' })
  const name = filenameFromDisposition(
    resp.headers?.['content-disposition'],
    fallback
  )
  const blob = new Blob([resp.data], {
    type: resp.headers?.['content-type'] || 'application/octet-stream'
  })
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  // 立刻 revoke 在部分浏览器会让下载中断，推迟一拍释放
  setTimeout(() => URL.revokeObjectURL(href), 1500)
  return name
}
