// web/src/api/innovation.js
// 职责：创新全景看板唯一取数入口。身份由后端 JWT 注入，前端不传学号/教师编号，
// 也不在这里计算、补齐或修正任何数值；缺失值由后端以 available=false / null 返回。

import http from './http'

// GET /innovation/overview —— 学生取本人、教师取任教范围内的聚合事实。
export function getInnovationOverview() {
  return http.get('/innovation/overview', { timeout: 60000 })
}
