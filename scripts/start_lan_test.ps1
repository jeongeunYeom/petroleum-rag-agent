param([string]$ServerIp = '10.11.51.110')

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$frontendDir = Join-Path $projectRoot 'frontend'
$backendDir = Join-Path $projectRoot 'backend'
$stateDir = Join-Path $projectRoot 'workspace\lan-test'
$statePath = Join-Path $stateDir 'processes.json'
$origin = "http://${ServerIp}:3000"
$apiBase = "http://${ServerIp}:8000/api"

function Test-Http([string]$url) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    } catch { return $false }
}

function Wait-Http([string]$url, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Http $url) { return }
        Start-Sleep -Seconds 2
    }
    throw "서버 응답 시간 초과: $url"
}

function Get-LocalProjectServerId([int]$port, [string]$kind, [string]$dataDir) {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if (-not $listeners) { return }
    if (@($listeners | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') }).Count -gt 0) {
        throw "TCP $port 에 이미 LAN 서버가 있습니다. scripts/stop_lan_test.ps1 또는 해당 서버를 확인하세요."
    }
    $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -ne 1) { throw "TCP $port 사용 프로세스를 안전하게 식별할 수 없습니다." }
    $ownerId = $owners[0]
    $command = (Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId").CommandLine
    if ($kind -eq 'backend') {
        if ($command -notmatch 'uvicorn\s+app\.main:app' -or $command -match '\-\-reload') {
            throw "TCP $port 의 기존 backend가 이 프로젝트의 단일 프로세스인지 확인할 수 없습니다."
        }
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 4
        if ($health.app -ne 'Petroleum Engineering AI Agent' -or
            [IO.Path]::GetFullPath($health.data_dir) -ne [IO.Path]::GetFullPath($dataDir)) {
            throw "TCP $port 의 기존 backend가 현재 데이터 디렉터리를 사용하지 않습니다."
        }
    } else {
        if ($command -notmatch 'node_modules[/\\]next[/\\]dist[/\\]bin[/\\]next\s+start') {
            throw "TCP $port 의 기존 frontend를 안전하게 식별할 수 없습니다."
        }
        $page = Invoke-WebRequest -Uri 'http://127.0.0.1:3000/' -UseBasicParsing -TimeoutSec 4
        if ($page.Content -notmatch '<title>Petroleum Engineering AI Agent</title>') {
            throw "TCP $port 의 기존 frontend가 이 프로젝트인지 확인할 수 없습니다."
        }
    }
    return $ownerId
}

$ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
    Where-Object { $_.IPAddress -eq $ServerIp -and $_.AddressState -eq 'Preferred' } |
    Select-Object -First 1
if (-not $ip) { throw "이 PC에서 IPv4 $ServerIp 를 찾지 못했습니다. 서버 주소를 확인하세요." }
$network = Get-NetConnectionProfile -InterfaceIndex $ip.InterfaceIndex -ErrorAction SilentlyContinue

$ollamaListeners = @(Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue)
if (@($ollamaListeners | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') }).Count -gt 0) {
    throw 'Ollama 11434가 외부 인터페이스에 열려 있습니다. LAN 테스트를 시작하지 않습니다.'
}
$ollamaHealthy = Test-Http 'http://127.0.0.1:11434/api/tags'
$backendHealthy = Test-Http 'http://127.0.0.1:8000/api/health'
$frontendHealthy = Test-Http 'http://127.0.0.1:3000/'
Write-Host "사전 상태 | IP: $ServerIp ($($ip.InterfaceAlias), $($network.NetworkCategory))"
Write-Host "Ollama localhost:11434: $ollamaHealthy | Backend localhost:8000: $backendHealthy | Frontend localhost:3000: $frontendHealthy"
if (-not $ollamaHealthy) { throw 'Ollama localhost:11434가 응답하지 않습니다. 기존 Ollama 서비스를 먼저 실행하세요.' }

$python = Join-Path $backendDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}
$nextCli = Join-Path $frontendDir 'node_modules\next\dist\bin\next'
if (-not (Test-Path -LiteralPath $nextCli)) { throw 'frontend 의존성이 없습니다. README의 최초 설치 절차를 완료하세요.' }
$node = (Get-Command node -ErrorAction Stop).Source
$null = Get-Command pnpm -ErrorAction Stop

Push-Location $backendDir
try {
    $paths = @(& $python -c 'from app.core.config import get_settings; s=get_settings(); print(s.data_dir); print(s.vector_db_dir)')
    if ($LASTEXITCODE -ne 0 -or $paths.Count -lt 2) { throw 'backend 설정을 읽지 못했습니다.' }
} finally { Pop-Location }
$dataDir = $paths[-2]
$dbDir = $paths[-1]
if (-not (Test-Path -LiteralPath (Join-Path $dbDir 'chroma.sqlite3'))) {
    throw "기존 ChromaDB를 찾지 못했습니다: $dbDir (새 DB를 만들지 않습니다)"
}
Write-Host "기존 DATA_DIR: $dataDir"

if (Test-Path -LiteralPath $statePath) { & (Join-Path $PSScriptRoot 'stop_lan_test.ps1') }
$oldFrontendId = Get-LocalProjectServerId 3000 'frontend' $dataDir
$oldBackendId = Get-LocalProjectServerId 8000 'backend' $dataDir
foreach ($oldServer in @(@{ port = 3000; id = $oldFrontendId; kind = 'frontend' },
                          @{ port = 8000; id = $oldBackendId; kind = 'backend' })) {
    if (-not $oldServer.id) { continue }
    Write-Host "기존 localhost $($oldServer.kind) 교체: PID $($oldServer.id)"
    Stop-Process -Id $oldServer.id -Force
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (-not (Get-NetTCPConnection -LocalPort $oldServer.port -State Listen -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 500
    }
    if (Get-NetTCPConnection -LocalPort $oldServer.port -State Listen -ErrorAction SilentlyContinue) {
        throw "TCP $($oldServer.port) 포트가 해제되지 않았습니다."
    }
}
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

$priorApi = [Environment]::GetEnvironmentVariable('NEXT_PUBLIC_API_BASE', 'Process')
$priorCors = [Environment]::GetEnvironmentVariable('PETROLEUM_LAN_TEST_ORIGIN', 'Process')
$priorOllama = [Environment]::GetEnvironmentVariable('OLLAMA_BASE_URL', 'Process')
$backendProcess = $null
$frontendProcess = $null
try {
    $env:NEXT_PUBLIC_API_BASE = $apiBase
    $env:PETROLEUM_LAN_TEST_ORIGIN = $origin
    $env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'

    Push-Location $frontendDir
    try {
        Write-Host "Frontend 빌드 중 (API: $apiBase)..."
        & pnpm build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend 빌드에 실패했습니다.' }
    } finally { Pop-Location }

    $backendProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000') `
        -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $stateDir 'backend.out.log') -RedirectStandardError (Join-Path $stateDir 'backend.err.log')
    Wait-Http 'http://127.0.0.1:8000/api/health' 90
    Wait-Http "http://${ServerIp}:8000/api/health" 15

    $frontendProcess = Start-Process -FilePath $node -ArgumentList @('node_modules/next/dist/bin/next', 'start', '-H', '0.0.0.0', '-p', '3000') `
        -WorkingDirectory $frontendDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $stateDir 'frontend.out.log') -RedirectStandardError (Join-Path $stateDir 'frontend.err.log')
    Wait-Http 'http://127.0.0.1:3000/' 90
    Wait-Http "http://${ServerIp}:3000/" 15

    $preflight = Invoke-WebRequest -Method Options -Uri 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 4 `
        -Headers @{ Origin = $origin; 'Access-Control-Request-Method' = 'GET' }
    if ($preflight.Headers['Access-Control-Allow-Origin'] -ne $origin) { throw 'LAN CORS 허용 검증에 실패했습니다.' }

    $state = [ordered]@{
        serverIp = $ServerIp
        backend = @{ id = $backendProcess.Id; startedAt = $backendProcess.StartTime.ToUniversalTime().ToString('o') }
        frontend = @{ id = $frontendProcess.Id; startedAt = $frontendProcess.StartTime.ToUniversalTime().ToString('o') }
        createdFirewallRules = @()
    }
    $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding UTF8

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
    foreach ($port in @(3000, 8000)) {
        $ruleName = "PetroleumAgent-LAN-Test-$port"
        $existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Host "기존 방화벽 규칙 유지: $ruleName (범위 확인 필요)"
        } elseif ($isAdmin) {
            try {
                New-NetFirewallRule -Name $ruleName -DisplayName "Petroleum Agent LAN Test TCP $port" `
                    -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -LocalAddress $ServerIp `
                    -RemoteAddress LocalSubnet -Profile Private,Domain | Out-Null
                $state.createdFirewallRules += $ruleName
                $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding UTF8
                Write-Host "방화벽 규칙 생성: TCP $port / Private,Domain / LocalSubnet"
            } catch { Write-Warning "TCP $port 방화벽 규칙 생성 실패: $_" }
        } else {
            Write-Warning "관리자 권한이 없어 TCP $port 방화벽 규칙을 만들지 못했습니다."
            Write-Host "관리자 PowerShell: New-NetFirewallRule -Name '$ruleName' -DisplayName 'Petroleum Agent LAN Test TCP $port' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -LocalAddress $ServerIp -RemoteAddress LocalSubnet -Profile Private,Domain"
        }
    }

    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host 'LAN 테스트 서버 실행 완료' -ForegroundColor Green
    Write-Host "다른 PC에서 접속: http://${ServerIp}:3000" -ForegroundColor Green
    Write-Host "Backend health: http://${ServerIp}:8000/api/health" -ForegroundColor Green
    Write-Host '상태: Frontend OK | Backend OK | Ollama OK' -ForegroundColor Green
    Write-Host 'Ollama: localhost:11434 (LAN 비노출)' -ForegroundColor Green
    Write-Host "종료: .\scripts\stop_lan_test.ps1"
    Write-Host "========================================`n" -ForegroundColor Green
    if ($network.NetworkCategory -notin @('Private', 'DomainAuthenticated')) {
        Write-Warning "현재 네트워크 프로필은 $($network.NetworkCategory) 입니다. Private/Domain 전용 규칙은 이 프로필에서 적용되지 않아 다른 PC 접속이 차단될 수 있습니다. 프로필은 자동 변경하지 않습니다."
    }
    Write-Warning '현재 API에는 별도 로그인 기능이 없습니다. 신뢰하는 LAN에서만 사용하세요.'
} catch {
    foreach ($started in @($frontendProcess, $backendProcess)) {
        if ($started -and -not $started.HasExited) { & taskkill.exe /PID $started.Id /T /F | Out-Null }
    }
    Write-Warning "시작 실패. 로그: $stateDir"
    throw
} finally {
    [Environment]::SetEnvironmentVariable('NEXT_PUBLIC_API_BASE', $priorApi, 'Process')
    [Environment]::SetEnvironmentVariable('PETROLEUM_LAN_TEST_ORIGIN', $priorCors, 'Process')
    [Environment]::SetEnvironmentVariable('OLLAMA_BASE_URL', $priorOllama, 'Process')
}
