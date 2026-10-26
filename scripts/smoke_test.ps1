#Requires -Version 5.1
<#
 scripts\smoke_test.ps1 —— 端到端冒烟（10 项）
 用法：powershell -ExecutionPolicy Bypass -File scripts\smoke_test.ps1 [-BaseUrl http://127.0.0.1:8000]
 返回：每项 PASS / FAIL / SKIP + 耗时；存在 FAIL 时 exit 1
 说明：服务未启动时会自动尝试用本仓库 .venv 拉起 uvicorn（app.main:app）
#>
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Term = "2025-2026-2",
    [int]$Port = 8000
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"

$script:Results = @()

function Write-Result {
    param([string]$Index, [string]$Name, [string]$Status, [string]$Detail, [double]$Ms)
    $script:Results += [pscustomobject]@{
        Index = $Index
        Item  = $Name
        Status = $Status
        Detail = $Detail
        Ms = [math]::Round($Ms, 1)
    }
    $color = switch ($Status) { "PASS" { "Green" } "FAIL" { "Red" } default { "Yellow" } }
    $ms = [math]::Round($Ms, 1)
    Write-Host ("[{0,-4}] {1,-28} {2,-5} {3,8} ms  {4}" -f $Index, $Name, $Status, $ms, $Detail) -ForegroundColor $color
}

function Invoke-Api {
    param([string]$Method, [string]$Path, [hashtable]$Headers = @{}, [object]$Body = $null, [hashtable]$Query = @{})
    $uri = "$BaseUrl$Path"
    if ($Query.Count -gt 0) {
        $pairs = @()
        foreach ($k in $Query.Keys) {
            $pairs += "$k=" + [System.Uri]::EscapeDataString([string]$Query[$k])
        }
        $uri = $uri + "?" + ($pairs -join "&")
    }
    $params = @{ Uri = $uri; Method = $Method; Headers = $Headers; UseBasicParsing = $true }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = ([System.Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Compress)))
    }
    # 不用 Invoke-RestMethod：它按 GBK 解 JSON，中文要点会变乱码；这里取字节按 UTF-8 解码
    $res = Invoke-WebRequest @params
    $text = [System.Text.Encoding]::UTF8.GetString($res.RawContentStream.ToArray())
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    return ($text | ConvertFrom-Json)
}

function Invoke-Check {
    param([string]$Index, [string]$Name, [scriptblock]$Action)
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $outcome = & $Action
        $watch.Stop()
        Write-Result $Index $Name $outcome.Status $outcome.Detail $watch.Elapsed.TotalMilliseconds
    } catch {
        $watch.Stop()
        $status = 0
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $status = [int]$_.Exception.Response.StatusCode
        }
        $detail = $_.Exception.Message
        if ($status -gt 0) { $detail = "HTTP $status：" + $detail }
        Write-Result $Index $Name "FAIL" $detail $watch.Elapsed.TotalMilliseconds
    }
}

Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host " 启航系统 · 端到端冒烟（11 项）" -ForegroundColor Cyan
Write-Host " BaseUrl=$BaseUrl   Term=$Term" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan

# ---- 0. 准备：服务拉起 + 演示教师 + 取样班级/学号 ----
try {
    $null = Invoke-Api -Method GET -Path "/health"
} catch {
    Write-Host "服务未就绪，尝试启动 uvicorn..." -ForegroundColor Yellow
    if (Test-Path $py) {
        Start-Process -FilePath $py -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "$Port" -WindowStyle Hidden
        Start-Sleep -Seconds 8
    }
}

$ensureTeacher = @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from pymysql import connect
from app.auth import hash_password
from app.config import get_settings
s = get_settings()
c = connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
            password=s.mysql_password, database=s.mysql_db, charset="utf8mb4")
cur = c.cursor()
cur.execute("SELECT id FROM teacher WHERE employee_no = %s", ("T001",))
if cur.fetchone() is None:
    cur.execute("INSERT INTO teacher (tenant_id, name, employee_no, role, password_hash) "
                "VALUES (%s,%s,%s,'teacher',%s)",
                (1, "演示教师", "T001", hash_password("teacher@123")))
c.commit()
c.close()
print("teacher ready")
'@
$null = $ensureTeacher | & $py -

$metaCmd = @'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from pymysql import connect
from pymysql.cursors import DictCursor
from app.config import get_settings
term = sys.argv[1]
s = get_settings()
c = connect(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user,
            password=s.mysql_password, database=s.mysql_db,
            charset="utf8mb4", cursorclass=DictCursor)
cur = c.cursor()
cur.execute("SELECT s.class_name AS class_name, COUNT(DISTINCT s.id) AS n "
            "FROM student s JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
            "WHERE s.tenant_id = 1 GROUP BY s.class_name ORDER BY n DESC LIMIT 1", (term,))
row = cur.fetchone() or {}
klass = row.get("class_name") or ""
cur.execute("SELECT s.student_no AS student_no FROM student s "
            "JOIN score sc ON sc.student_id = s.id AND sc.term = %s "
            "WHERE s.tenant_id = 1 AND s.class_name = %s "
            "ORDER BY s.student_no LIMIT 1", (term, klass))
self_no = (cur.fetchone() or {}).get("student_no") or ""
cur.execute("SELECT s.student_no AS student_no FROM student s "
            "WHERE s.tenant_id = 1 AND s.student_no <> %s "
            "ORDER BY s.student_no LIMIT 1", (self_no,))
other = (cur.fetchone() or {}).get("student_no") or ""
c.close()
print(json.dumps({"class_name": klass, "student_no": self_no,
                  "other_student_no": other}, ensure_ascii=False))
'@
$metaRaw = $metaCmd | & $py - $Term
$meta = $metaRaw | ConvertFrom-Json
$Class = $meta.class_name
$StudentNo = $meta.student_no
$OtherNo = $meta.other_student_no
Write-Host ("样品数据：班级={0}  本人={1}  他人={2}" -f $Class, $StudentNo, $OtherNo) -ForegroundColor DarkGray

# ---- 1. /health ----
Invoke-Check -Index "1" -Name "/health 全绿" -Action {
    $h = Invoke-Api -Method GET -Path "/health"
    $ok = ($h.status -eq "ok") -and ($h.db -eq "ok") -and ($h.duckdb -eq "ok")
    $detail = "status=$($h.status) db=$($h.db) duckdb=$($h.duckdb) llm=$($h.llm)"
    return @{ Status = $(if ($ok) { "PASS" } else { "FAIL" }); Detail = $detail }
}

# ---- 2. 教师登录 ----
$script:TeacherToken = ""
Invoke-Check -Index "2" -Name "教师登录拿 token" -Action {
    $login = Invoke-Api -Method POST -Path "/auth/login" -Body @{
        role = "teacher"; account = "T001"; password = "teacher@123"
    }
    $script:TeacherToken = $login.access_token
    $ok = [bool]$script:TeacherToken
    return @{ Status = $(if ($ok) { "PASS" } else { "FAIL" }); Detail = "role=$($login.role) tenant=$($login.tenant_id) expires=$($login.expires_in)s" }
}
$tHeaders = @{ Authorization = "Bearer $script:TeacherToken" }

# ---- 3. 班级概览 ----
Invoke-Check -Index "3" -Name "教师查班级概览" -Action {
    $ov = Invoke-Api -Method GET -Path "/teacher/class-overview" -Headers $tHeaders -Query @{ class_name = $Class; term = $Term }
    $ok = ($null -ne $ov.headcount) -and ($null -ne $ov.warning_distribution)
    $detail = "headcount=$($ov.headcount) avg_gpa=$($ov.avg_gpa) fail_rate=$($ov.fail_rate)"
    return @{ Status = $(if ($ok) { "PASS" } else { "FAIL" }); Detail = $detail }
}

# ---- 4. 预警名单 ----
Invoke-Check -Index "4" -Name "教师查预警名单" -Action {
    $wl = Invoke-Api -Method GET -Path "/teacher/warnings" -Headers $tHeaders -Query @{ class_name = $Class; term = $Term }
    $d = $wl.distribution
    $detail = "count=$($wl.count) red=$($d.red) orange=$($d.orange) yellow=$($d.yellow) none=$($d.none) unknown=$($d.unknown)"
    return @{ Status = "PASS"; Detail = $detail }
}

# ---- 5. 学生画像 ----
Invoke-Check -Index "5" -Name "教师查学生画像" -Action {
    $sp = Invoke-Api -Method GET -Path "/teacher/student/$StudentNo" -Headers $tHeaders -Query @{ term = $Term }
    $dims = @($sp.dimensions.PSObject.Properties).Count
    $tags = @($sp.tags)
    $ok = ($dims -eq 4) -and ($tags.Count -ge 3)
    $detail = "维度=$dims 标签=$($tags.Count) [$(($tags) -join '/')]"
    return @{ Status = $(if ($ok) { "PASS" } else { "FAIL" }); Detail = $detail }
}

# ---- 6. 职业差距 ----
Invoke-Check -Index "6" -Name "教师查职业差距" -Action {
    $cg = Invoke-Api -Method GET -Path "/teacher/career-gap" -Headers $tHeaders -Query @{ class_name = $Class; term = $Term }
    $ok = ($null -ne $cg.class_ability) -and ($null -ne $cg.gaps)
    $detail = "target=$($cg.target_direction) sample=$($cg.class_ability.sample) gaps=$(@($cg.gaps).Count)"
    return @{ Status = $(if ($ok) { "PASS" } else { "FAIL" }); Detail = $detail }
}

# ---- 7. 学生登录 ----
$script:StudentToken = ""
Invoke-Check -Index "7" -Name "学生登录拿 token" -Action {
    $sl = Invoke-Api -Method POST -Path "/auth/login" -Body @{
        role = "student"; account = $StudentNo; password = $StudentNo
    }
    $script:StudentToken = $sl.access_token
    $ok = [bool]$script:StudentToken
    return @{ Status = $(if ($ok) { "PASS" } else { "FAIL" }); Detail = "学号 $StudentNo（初始口令=学号）" }
}
$sHeaders = @{ Authorization = "Bearer $script:StudentToken" }

# ---- 8. 学生查本人预警 ----
Invoke-Check -Index "8" -Name "学生查本人预警" -Action {
    $mw = Invoke-Api -Method GET -Path "/student/warning" -Headers $sHeaders -Query @{ term = $Term }
    $row = $null
    try {
        $wl2 = Invoke-Api -Method GET -Path "/teacher/warnings" -Headers $tHeaders -Query @{ class_name = $Class; term = $Term }
        $row = @($wl2.items | Where-Object { $_.student_no -eq $StudentNo })[0]
    } catch {
        $row = $null
    }
    $consistent = ($null -eq $row) -or ($row.risk_score -eq $mw.risk_score)
    $detail = "risk=$($mw.risk_score) level=$($mw.level) coverage=$($mw.coverage) 两端一致=$consistent"
    return @{ Status = $(if ($consistent) { "PASS" } else { "FAIL" }); Detail = $detail }
}

# ---- 9. 学生查他人 → 403 ----
Invoke-Check -Index "9" -Name "学生查他人被拒 403" -Action {
    if ([string]::IsNullOrWhiteSpace($OtherNo)) {
        return @{ Status = "SKIP"; Detail = "该班只有 1 名学生，无法构造「他人」场景" }
    }
    $status = 0
    try {
        $null = Invoke-Api -Method GET -Path "/teacher/student/$OtherNo" -Headers $sHeaders -Query @{ term = $Term }
    } catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $status = [int]$_.Exception.Response.StatusCode
        }
    }
    if ($status -eq 403) {
        return @{ Status = "PASS"; Detail = "HTTP 403 已拦截（目标 $OtherNo）" }
    }
    return @{ Status = "FAIL"; Detail = "期望 403，实际 HTTP $status" }
}

# ---- 10. 学生推荐接口 ----
Invoke-Check -Index "10" -Name "学生推荐接口" -Action {
    $rec = Invoke-Api -Method GET -Path "/student/recommendations" -Headers $sHeaders -Query @{ term = $Term; top_n = 5 }
    if ($rec.recommend_version -eq "pending") {
        return @{ Status = "SKIP"; Detail = "待 P9 实现，当前返回占位结构（字段已留全）" }
    }
    return @{ Status = "PASS"; Detail = "count=$(@($rec.items).Count) version=$($rec.recommend_version)" }
}

# ---- 11. 前端静态托管（P10-3）：有构建产物才检查，没构建就 SKIP ----
Invoke-Check -Index "11" -Name "前端静态托管" -Action {
    $distIndex = Join-Path $root "web\dist\index.html"
    if (-not (Test-Path $distIndex)) {
        return @{ Status = "SKIP"; Detail = "未构建前端产物（先跑 scripts\build_web.ps1）" }
    }
    $rootPage = Invoke-WebRequest -Uri "$BaseUrl/" -UseBasicParsing
    $spa = Invoke-WebRequest -Uri "$BaseUrl/teacher" -UseBasicParsing
    if ($rootPage.StatusCode -eq 200 -and $spa.StatusCode -eq 200 -and $spa.Content -match 'id="app"') {
        return @{ Status = "PASS"; Detail = "/ 与 /teacher 均回落 index.html（$($rootPage.Content.Length) B）" }
    }
    return @{ Status = "FAIL"; Detail = "首页 HTTP $($rootPage.StatusCode) /teacher HTTP $($spa.StatusCode)" }
}

# ---- 汇总 ----
Write-Host ""
Write-Host "==================== 汇总 ====================" -ForegroundColor Cyan
$pass = @($script:Results | Where-Object { $_.Status -eq "PASS" }).Count
$fail = @($script:Results | Where-Object { $_.Status -eq "FAIL" }).Count
$skip = @($script:Results | Where-Object { $_.Status -eq "SKIP" }).Count
$total = [math]::Round(($script:Results | Measure-Object -Property Ms -Sum).Sum, 1)
Write-Host ("PASS {0}  FAIL {1}  SKIP {2}   总耗时 {3} ms" -f $pass, $fail, $skip, $total)
if ($fail -gt 0) {
    Write-Host "存在 FAIL 项，冒烟未通过。" -ForegroundColor Red
    exit 1
}
Write-Host "冒烟通过（SKIP 项已说明原因）。" -ForegroundColor Green
exit 0
