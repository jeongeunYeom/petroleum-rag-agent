$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$statePath = Join-Path $projectRoot 'workspace\lan-test\processes.json'

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host '실행 중인 LAN 테스트 기록이 없습니다.'
    return
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$allStopped = $true
foreach ($server in @('frontend', 'backend')) {
    $entry = $state.$server
    if (-not $entry) { continue }
    $process = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    if ($process.StartTime.ToUniversalTime().ToString('o') -ne ([DateTime]$entry.startedAt).ToUniversalTime().ToString('o')) {
        Write-Warning "$server PID가 다른 프로세스에 재사용되어 종료하지 않았습니다."
        $allStopped = $false
        continue
    }
    $command = (Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.id)").CommandLine
    $expected = if ($server -eq 'backend') { 'uvicorn app.main:app' } else { 'node_modules/next/dist/bin/next start' }
    if ($command -notlike "*$expected*") {
        Write-Warning "$server 명령이 기록과 달라 종료하지 않았습니다."
        $allStopped = $false
        continue
    }
    & taskkill.exe /PID $entry.id /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "$server 프로세스 트리를 종료하지 못했습니다: PID $($entry.id)"
        $allStopped = $false
    }
    else { Write-Host "$server 종료: PID $($entry.id)" }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
foreach ($ruleName in @($state.createdFirewallRules)) {
    if (-not $ruleName) { continue }
    if ($isAdmin) {
        Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        Write-Host "방화벽 규칙 제거: $ruleName"
    } else {
        Write-Warning "관리자 권한이 없어 방화벽 규칙을 제거하지 못했습니다: $ruleName"
        Write-Host "관리자 PowerShell: Remove-NetFirewallRule -Name '$ruleName'"
    }
}

if (-not $allStopped) { throw "일부 프로세스를 종료하지 못했습니다. 실행 기록을 유지합니다: $statePath" }
Remove-Item -LiteralPath $statePath
Write-Host 'LAN 테스트 서버 종료 완료'
