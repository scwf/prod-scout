# run_crawler.ps1 - One-click RSS crawler script
# Functions: Check environment, start dependencies, run crawler

# ==================== Configuration ====================
$VENV_DIR = ".venv"               # Virtual environment directory (created by uv)
$RSSHUB_CONTAINER = "rsshub"      # RSSHub container name
$RSSHUB_IMAGE = "diygod/rsshub:chromium-bundled"
$RSSHUB_PORT = 1200
$SCRIPT_DIR = $PSScriptRoot
# =======================================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Prod Scout - Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Read config.ini to decide whether RSSHub is required.
$configPath = Join-Path $SCRIPT_DIR "config.ini"
$xScraperEnabled = $false
if (Test-Path $configPath) {
    $inXScraperSection = $false
    foreach ($line in Get-Content $configPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or $trimmed.StartsWith(";")) {
            continue
        }
        if ($trimmed -match "^\[(.+)\]$") {
            $inXScraperSection = ($Matches[1].Trim().ToLower() -eq "x_scraper")
            continue
        }
        if ($inXScraperSection -and $trimmed -match "^enabled\s*=\s*(.+)$") {
            $enabledValue = $Matches[1].Trim().ToLower()
            $xScraperEnabled = @("1", "true", "yes", "on").Contains($enabledValue)
            break
        }
    }
}

if (-not $xScraperEnabled) {
    # 1. Check if Docker is running
    Write-Host "[1/3] Checking Docker service..." -ForegroundColor Yellow
    $dockerRunning = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Docker is not running. Please start Docker Desktop first." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Docker service OK" -ForegroundColor Green

    # 2. Check RSSHub container
    Write-Host "[2/3] Checking RSSHub container..." -ForegroundColor Yellow
    $containerStatus = docker ps -a --filter "name=$RSSHUB_CONTAINER" --format "{{.Status}}"

    if (-not $containerStatus) {
        # Container does not exist, create and start
        Write-Host "  RSSHub container not found, creating..." -ForegroundColor Yellow
        $envFile = Join-Path $SCRIPT_DIR "rsshub-docker.env"
        if (Test-Path $envFile) {
            docker run -d --name $RSSHUB_CONTAINER -p ${RSSHUB_PORT}:1200 --env-file $envFile $RSSHUB_IMAGE
        } else {
            Write-Host "  WARNING: rsshub-docker.env not found, starting without env file" -ForegroundColor Yellow
            docker run -d --name $RSSHUB_CONTAINER -p ${RSSHUB_PORT}:1200 $RSSHUB_IMAGE
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: Failed to create RSSHub container" -ForegroundColor Red
            exit 1
        }
        Write-Host "  RSSHub container created and started" -ForegroundColor Green
        # Wait for service ready
        Write-Host "  Waiting for RSSHub service (10s)..." -ForegroundColor Yellow
        Start-Sleep -Seconds 10
    } elseif ($containerStatus -like "Up*") {
        Write-Host "  RSSHub container is running" -ForegroundColor Green
    } else {
        # Container exists but stopped, start it
        Write-Host "  RSSHub container stopped, starting..." -ForegroundColor Yellow
        docker start $RSSHUB_CONTAINER
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: Failed to start RSSHub container" -ForegroundColor Red
            exit 1
        }
        Write-Host "  RSSHub container started" -ForegroundColor Green
        # Wait for service ready
        Write-Host "  Waiting for RSSHub service (5s)..." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
    }
} else {
    Write-Host "[1/2] x_scraper.enabled=true, skipping Docker/RSSHub checks" -ForegroundColor Green
}

# 3. Activate virtual environment and run crawler
if ($xScraperEnabled) {
    Write-Host "[2/2] Running crawler script..." -ForegroundColor Yellow
} else {
    Write-Host "[3/3] Running crawler script..." -ForegroundColor Yellow
}

$venvPath = Join-Path $SCRIPT_DIR $VENV_DIR
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"

if (-not (Test-Path $activateScript)) {
    Write-Host "  ERROR: Virtual environment not found at $venvPath" -ForegroundColor Red
    Write-Host "  Please create it first: uv venv" -ForegroundColor Yellow
    exit 1
}

Write-Host "  Activating virtual environment..." -ForegroundColor Yellow
& $activateScript
Write-Host "  Virtual environment activated" -ForegroundColor Green
Write-Host ""

# Run crawler
python -m native_scout.pipeline

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Crawler finished successfully!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  Crawler failed. Check output above." -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    exit 1
}
