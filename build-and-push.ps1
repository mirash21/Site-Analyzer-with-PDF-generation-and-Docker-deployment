# ==========================================
# BUILD AND PUSH DOCKER IMAGES (PowerShell)
# ==========================================
# Script builds and pushes backend and frontend images to Docker Hub
# ==========================================
# Run: .\build-and-push.ps1
# ==========================================

# ============================
# CONFIGURATION
# ============================
$DOCKER_USERNAME = "mirash2008"
$BACKEND_TAG = "${DOCKER_USERNAME}/backend:latest"
$FRONTEND_TAG = "${DOCKER_USERNAME}/frontend:latest"

# Dockerfile paths
$BACKEND_DOCKERFILE = "Backend-Dockerfile"
$FRONTEND_DOCKERFILE = "frontend/Dockerfile"

# ============================
# FUNCTIONS
# ============================

function Print-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host "  $Message" -ForegroundColor Cyan
    Write-Host "=========================================" -ForegroundColor Cyan
}

function Print-Error {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Print-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Print-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Yellow
}

function Test-DockerLogin {
    Print-Step "CHECKING DOCKER HUB AUTH"
    
    $dockerInfo = docker info 2>&1
    if ($dockerInfo -match "Username:\s*$DOCKER_USERNAME") {
        Print-Success "Already logged in as $DOCKER_USERNAME"
        return $true
    } else {
        Print-Info "Docker Hub authorization required"
        docker login
        return $?
    }
}

function Build-BackendImage {
    Print-Step "BUILDING BACKEND IMAGE"
    
    Print-Info "Dockerfile: $BACKEND_DOCKERFILE"
    Print-Info "Tag: $BACKEND_TAG"
    
    if (!(Test-Path $BACKEND_DOCKERFILE)) {
        Print-Error "Dockerfile not found: $BACKEND_DOCKERFILE"
        return $false
    }
    
    docker build --progress=plain `
        -t $BACKEND_TAG `
        -f $BACKEND_DOCKERFILE `
        .
    
    if ($LASTEXITCODE -eq 0) {
        Print-Success "Backend image built successfully"
        return $true
    } else {
        Print-Error "Failed to build backend image"
        return $false
    }
}

function Push-BackendImage {
    Print-Step "PUSHING BACKEND IMAGE TO DOCKER HUB"
    
    Print-Info "Pushing: $BACKEND_TAG"
    
    docker push $BACKEND_TAG
    
    if ($LASTEXITCODE -eq 0) {
        Print-Success "Backend image pushed"
        return $true
    } else {
        Print-Error "Failed to push backend image"
        return $false
    }
}

function Build-FrontendImage {
    Print-Step "BUILDING FRONTEND IMAGE"
    
    Print-Info "Directory: frontend/"
    Print-Info "Dockerfile: $FRONTEND_DOCKERFILE"
    Print-Info "Tag: $FRONTEND_TAG"
    
    if (!(Test-Path $FRONTEND_DOCKERFILE)) {
        Print-Error "Dockerfile not found: $FRONTEND_DOCKERFILE"
        return $false
    }
    
    docker build --progress=plain `
        -t $FRONTEND_TAG `
        -f $FRONTEND_DOCKERFILE `
        frontend/
    
    if ($LASTEXITCODE -eq 0) {
        Print-Success "Frontend image built successfully"
        return $true
    } else {
        Print-Error "Failed to build frontend image"
        return $false
    }
}

function Push-FrontendImage {
    Print-Step "PUSHING FRONTEND IMAGE TO DOCKER HUB"
    
    Print-Info "Pushing: $FRONTEND_TAG"
    
    docker push $FRONTEND_TAG
    
    if ($LASTEXITCODE -eq 0) {
        Print-Success "Frontend image pushed"
        return $true
    } else {
        Print-Error "Failed to push frontend image"
        return $false
    }
}

function Test-Images {
    Print-Step "TESTING IMAGES"
    
    Print-Info "Image sizes:"
    docker images $BACKEND_TAG $FRONTEND_TAG --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
    
    $test = Read-Host "Test containers locally? (y/n)"
    if ($test -eq "y" -or $test -eq "Y") {
        Print-Info "Starting test containers..."
        
        $backendJob = Start-Job -ScriptBlock {
            docker run --rm -p 8001:8000 $using:BACKEND_TAG
        }
        
        Start-Sleep -Seconds 5
        
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:8001/health" -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                Print-Success "Backend container is running"
            }
        } catch {
            Print-Info "Backend container not responding (may be normal)"
        }
        
        Stop-Job $backendJob
        Remove-Job $backendJob
        
        Print-Info "Testing completed"
    } else {
        Print-Info "Testing skipped"
    }
}

function Cleanup-OldImages {
    Print-Step "CLEANING OLD IMAGES"
    
    $cleanup = Read-Host "Remove old images and dangling layers? (y/n)"
    if ($cleanup -eq "y" -or $cleanup -eq "Y") {
        Print-Info "Removing dangling images..."
        docker image prune -f
        
        Print-Info "Removing old images without tags..."
        docker image prune -a -f
        
        Print-Success "Cleanup completed"
    } else {
        Print-Info "Cleanup skipped"
    }
}

function Print-ImageInfo {
    Print-Step "IMAGE INFORMATION"
    
    docker images $BACKEND_TAG $FRONTEND_TAG --format "table {{.Repository}}\t{{.Tag}}\t{{.CreatedAt}}\t{{.Size}}"
}

# ============================
# MAIN BLOCK
# ============================

Print-Step "STARTING BUILD AND PUSH"

# Check authorization
if (-not (Test-DockerLogin)) {
    exit 1
}

# Build and push Backend
if (-not (Build-BackendImage)) { exit 1 }
if (-not (Push-BackendImage)) { exit 1 }

# Build and push Frontend
if (-not (Build-FrontendImage)) { exit 1 }
if (-not (Push-FrontendImage)) { exit 1 }

# Print info
Print-ImageInfo

# Test (optional)
Test-Images

# Cleanup (optional)
Cleanup-OldImages

Print-Step "BUILD AND PUSH COMPLETED"
Print-Success "Images ready for deployment"
Print-Info "Run: .\deploy.ps1 to deploy"
