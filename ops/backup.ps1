# 个人 AI 知识助手备份脚本（Windows PowerShell）
#
# 备份内容：
#   1. PostgreSQL 数据库（pg_dump 自定义格式，可用 pg_restore 恢复）
#   2. 文件存储（docker-compose 卷 personal_ai_storage，含上传文件与本地对象存储）
#
# 用法（在项目根目录执行）：
#   powershell -ExecutionPolicy Bypass -File ops\backup.ps1
#   powershell -ExecutionPolicy Bypass -File ops\backup.ps1 -OutputDir D:\backups -KeepDays 14
#
# 恢复方法见 README.md「备份与恢复」一节。

param(
    [string]$OutputDir = ".\backups",
    [int]$KeepDays = 30
)

$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$dbFile = Join-Path $OutputDir "personal_ai_db_$Stamp.dump"
Write-Host "备份数据库到 $dbFile ..."
# PowerShell 管道会破坏二进制流，必须经 cmd 重定向。
cmd /c "docker compose exec -T db pg_dump -U postgres -d personal_ai -Fc > `"$dbFile`""
if ($LASTEXITCODE -ne 0) { throw "pg_dump 失败" }

$storageFile = Join-Path $OutputDir "personal_ai_storage_$Stamp.tar.gz"
Write-Host "备份文件存储到 $storageFile ..."
docker run --rm `
    -v personal_ai_storage:/data:ro `
    -v (Resolve-Path $OutputDir).Path`:/backup `
    alpine tar czf /backup/personal_ai_storage_$Stamp.tar.gz -C /data .
if ($LASTEXITCODE -ne 0) { throw "存储备份失败" }

$sizeDb = "{0:N1} MB" -f ((Get-Item $dbFile).Length / 1MB)
$sizeStorage = "{0:N1} MB" -f ((Get-Item $storageFile).Length / 1MB)
Write-Host "完成：数据库 $sizeDb，存储 $sizeStorage"

if ($KeepDays -gt 0) {
    $cutoff = (Get-Date).AddDays(-$KeepDays)
    Get-ChildItem $OutputDir -File |
        Where-Object { $_.Name -like "personal_ai_*" -and $_.LastWriteTime -lt $cutoff } |
        ForEach-Object { Write-Host "清理过期备份：$($_.Name)"; Remove-Item $_ }
}
