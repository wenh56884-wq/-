<#
  init_qihang.ps1  --  Create the folder skeleton for project QIHANG.
  Idempotent: safe to run many times.

  Usage (recommended):
      powershell -NoProfile -ExecutionPolicy Bypass -File init_qihang.ps1 -Root D:\qihang
  Or just double-click init_qihang.bat

  Options:
      -Root <path>   project root, default D:\qihang
      -SkipGit       do not run "git init"
#>
[CmdletBinding()]
param(
    [string]$Root = "D:\qihang",
    [switch]$SkipGit
)

$ErrorActionPreference = "Stop"
function Say($tag, $msg) { Write-Host ("{0,-8}{1}" -f $tag, $msg) }

# ---------------------------------------------------------------- 1. folders
# Order matters only for readability; New-Item -Force creates parents anyway.
$dirs = @(
    "app",               # FastAPI gateway
    "app\routers",       # teacher / student endpoints
    "app\static",        # static assets for demo page
    "agents",            # LangGraph multi-agent layer
    "engine",            # deterministic engines (warning / profile / recommend)
    "db",                # SQL schemas (mysql + duckdb)
    "etl",               # ingest / clean / mask
    "scripts",           # init_db / seed_mock / smoke_test / reports
    "tests",             # pytest
    "data",              # duckdb file + generated csv (git-ignored)
    "docs",              # VERIFY.md / demo script / deck outline
    "logs"               # critic logs + runtime logs (git-ignored)
)

Say "ROOT" $Root
if (-not (Test-Path $Root)) {
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    Say "mkdir" $Root
} else {
    Say "exist" $Root
}

foreach ($d in $dirs) {
    $p = Join-Path $Root $d
    if (-not (Test-Path $p)) {
        New-Item -ItemType Directory -Path $p -Force | Out-Null
        Say "mkdir" $p
    } else {
        Say "exist" $p
    }
}

# keep empty folders in git
foreach ($d in $dirs) {
    $p = Join-Path $Root $d
    $k = Join-Path $p ".gitkeep"
    if (-not (Test-Path $k)) { New-Item -ItemType File -Path $k -Force | Out-Null }
}

# ---------------------------------------------------------------- 2. dotfiles
$utf8 = New-Object System.Text.UTF8Encoding($false)

$gitignore = @'
# --- python ---
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.ruff_cache/
.venv/
venv/

# --- secrets / local ---
.env
.env.local

# --- data & runtime ---
data/*.duckdb
data/*.duckdb.wal
data/*.csv
logs/
*.log

# --- ide / os ---
.vscode/
.idea/
.DS_Store
Thumbs.db
'@

$envExample = @'
# ===== DeepSeek (model provider) =====
DEEPSEEK_API_KEY=sk-REPLACE_ME
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# ===== MySQL 8.0.21 (already running on this machine) =====
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=REPLACE_ME
MYSQL_DB=qihang

# ===== DuckDB (analytics layer, MVP stand-in for ClickHouse) =====
DUCKDB_PATH=D:/qihang/data/analytics.duckdb

# ===== app =====
APP_PORT=8000
JWT_SECRET=REPLACE_WITH_32_RANDOM_CHARS
JWT_EXPIRE_MINUTES=120
'@

$pairs = @(
    @{ Path = (Join-Path $Root ".gitignore");       Body = $gitignore },
    @{ Path = (Join-Path $Root ".env.example");    Body = $envExample }
)

foreach ($f in $pairs) {
    if (-not (Test-Path $f.Path)) {
        [System.IO.File]::WriteAllText($f.Path, $f.Body, $utf8)
        Say "file" $f.Path
    } else {
        Say "exist" $f.Path
    }
}

# ---------------------------------------------------------------- 3. git init
if (-not $SkipGit) {
    $hasGit = Test-Path (Join-Path $Root ".git")
    if (-not $hasGit) {
        $g = Get-Command git -ErrorAction SilentlyContinue
        if ($g) {
            Push-Location $Root
            git init | Out-Null
            Pop-Location
            Say "git" "initialized repository at $Root"
        } else {
            Say "warn" "git not found in PATH, skipped"
        }
    } else {
        Say "exist" (Join-Path $Root ".git")
    }
}

# ---------------------------------------------------------------- 4. summary
Write-Host ""
Write-Host "----- folder tree -----"
Get-ChildItem -Path $Root -Directory -Recurse |
    Where-Object { $_.FullName -notmatch '\\\.git\\' -and $_.Name -ne '.git' } |
    ForEach-Object { $_.FullName.Replace($Root, '.') } |
    Sort-Object |
    ForEach-Object { Write-Host $_ }

$nDir  = (Get-ChildItem -Path $Root -Directory -Recurse | Where-Object { $_.Name -ne '.git' }).Count
$nKeep = (Get-ChildItem -Path $Root -Filter ".gitkeep" -Recurse -Force).Count
Write-Host ""
Write-Host ("done: {0} folders, {1} .gitkeep placeholders" -f $nDir, $nKeep)
Write-Host ""
Write-Host "next steps:"
Write-Host "  1) cd $Root"
Write-Host "  2) & 'D:\data\python.exe' -m venv .venv"
Write-Host "  3) .\.venv\Scripts\Activate.ps1"
Write-Host "  4) copy .env.example .env   -> then fill DEEPSEEK_API_KEY / MYSQL_PASSWORD / JWT_SECRET"
Write-Host "  5) open $Root in CodeBuddy (Agent mode) and send prompt P0"
