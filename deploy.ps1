# ==========================================
# DEPLOYMENT SCRIPT (PowerShell)
# ==========================================
# Script for complete server setup via SSH
# ==========================================
# Run: .\deploy.ps1
# ==========================================

# ============================
# CONFIGURATION
# ============================
$SERVER_USER = "root"
$SERVER_IP = "185.117.155.237"
$SERVER_PATH = "/home/$SERVER_USER/Final_project_curs"
$LOCAL_PROJECT_PATH = Get-Location

# Files to upload to server
$FILES_TO_UPLOAD = @(
    "docker-compose.production.yml",
    "update-containers.sh",
    "setup-cron.sh"
)

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

function Test-SSHConnection {
    Print-Step "CHECKING SSH CONNECTION"
    
    $result = ssh -o ConnectTimeout=5 ${SERVER_USER}@${SERVER_IP} "echo 'SSH connection established'" 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Print-Success "SSH connection to server $SERVER_IP established"
        return $true
    } else {
        Print-Error "Failed to establish SSH connection to $SERVER_IP"
        return $false
    }
}

function Create-Directories {
    Print-Step "CREATING DIRECTORIES ON SERVER"
    
    ssh ${SERVER_USER}@${SERVER_IP} "mkdir -p ${SERVER_PATH}/data ${SERVER_PATH}/logs ${SERVER_PATH}/logs/backend ${SERVER_PATH}/logs/frontend"
    
    if ($LASTEXITCODE -eq 0) {
        Print-Success "Directories created: ${SERVER_PATH}/data, ${SERVER_PATH}/logs"
        return $true
    } else {
        Print-Error "Failed to create directories"
        return $false
    }
}

function Upload-Files {
    Print-Step "UPLOADING FILES TO SERVER"
    
    foreach ($file in $FILES_TO_UPLOAD) {
        $fullPath = Join-Path $LOCAL_PROJECT_PATH $file
        if (Test-Path $fullPath) {
            Print-Info "Uploading: $file"
            scp $fullPath "${SERVER_USER}@${SERVER_IP}:${SERVER_PATH}/"
            
            if ($LASTEXITCODE -eq 0) {
                Print-Success "File $file uploaded"
            } else {
                Print-Error "Failed to upload $file"
                return $false
            }
        } else {
            Print-Error "File not found: $file"
        }
    }
    
    return $true
}

function Create-EnvFile {
    Print-Step "CREATING .env FILE"
    
    $timestamp = [int][double]::Parse((Get-Date -UFormat %s))
    $envContent = @"
# Backend configuration
DATABASE_URL=sqlite:///./data/app.db
SECRET_KEY=prod-secret-key-change-this-$timestamp
ENVIRONMENT=production

# API configuration (change to real values)
# OPENAI_API_KEY=your-openai-key-here

# CORS configuration
CORS_ORIGINS=http://185.117.155.237
"@
    
    $tempPath = Join-Path $env:TEMP "server.env"
    $envContent | Out-File -FilePath $tempPath -Encoding UTF8
    
    scp $tempPath "${SERVER_USER}@${SERVER_IP}:${SERVER_PATH}/.env"
    Remove-Item $tempPath
    
    if ($LASTEXITCODE -eq 0) {
        Print-Success ".env file created"
        Print-Info "Note: Change SECRET_KEY and add OPENAI_API_KEY if needed"
        return $true
    } else {
        Print-Error "Failed to create .env file"
        return $false
    }
}

function Upload-FrontendNginx {
    Print-Step "UPLOADING NGINX CONFIGURATION"
    
    $nginxPath = Join-Path $LOCAL_PROJECT_PATH "frontend\nginx.conf"
    
    if (Test-Path $nginxPath) {
        scp $nginxPath "${SERVER_USER}@${SERVER_IP}:${SERVER_PATH}/"
        
        if ($LASTEXITCODE -eq 0) {
            Print-Success "nginx.conf uploaded"
            return $true
        } else {
            Print-Error "Failed to upload nginx.conf"
            return $false
        }
    } else {
        Print-Info "frontend/nginx.conf not found, skipping"
        return $true
    }
}

function Start-Containers {
    Print-Step "STARTING CONTAINERS"
    
    Print-Info "Pulling images from Docker Hub..."
    ssh ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && docker-compose -f docker-compose.production.yml pull"
    
    if ($LASTEXITCODE -eq 0) {
        Print-Success "Images pulled"
    } else {
        Print-Error "Failed to pull images"
        return $false
    }
    
    Print-Info "Starting containers..."
    ssh ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && docker-compose -f docker-compose.production.yml up -d"
    
    if ($LASTEXITCODE -eq 0) {
        Print-Success "Containers started"
        return $true
    } else {
        Print-Error "Failed to start containers"
        return $false
    }
}

function Check-Status {
    Print-Step "CHECKING CONTAINER STATUS"
    
    ssh ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && docker-compose -f docker-compose.production.yml ps"
    
    return $LASTEXITCODE -eq 0
}

function Setup-Permissions {
    Print-Step "SETTING UP PERMISSIONS"
    
    ssh ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && chmod +x update-containers.sh setup-cron.sh"
    
    if ($LASTEXITCODE -eq 0) {
        Print-Success "Permissions set"
        return $true
    } else {
        Print-Error "Failed to set permissions"
        return $false
    }
}

function Setup-Cron {
    Print-Step "SETTING UP CRON FOR AUTO-UPDATE"
    
    $setupCron = Read-Host "Setup cron job for automatic updates? (y/n)"
    
    if ($setupCron -eq "y" -or $setupCron -eq "Y") {
        ssh ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && sudo bash setup-cron.sh"
        
        if ($LASTEXITCODE -eq 0) {
            Print-Success "Cron job setup"
            return $true
        } else {
            Print-Error "Failed to setup cron job"
            return $false
        }
    } else {
        Print-Info "Cron setup skipped"
    }
    
    return $true
}

function Setup-Firewall {
    Print-Step "SETTING UP FIREWALL"
    
    $setupFW = Read-Host "Open ports 80 and 443 in firewall? (y/n)"
    
    if ($setupFW -eq "y" -or $setupFW -eq "Y") {
        ssh ${SERVER_USER}@${SERVER_IP} "sudo ufw allow 80 && sudo ufw allow 443"
        
        if ($LASTEXITCODE -eq 0) {
            Print-Success "Ports 80 and 443 opened"
            return $true
        } else {
            Print-Error "Failed to open ports"
            return $false
        }
    } else {
        Print-Info "Firewall setup skipped"
    }
    
    return $true
}

function Print-Summary {
    Print-Step "DEPLOYMENT COMPLETED"
    
    Write-Host ""
    Write-Host "Application available at:" -ForegroundColor Green
    Write-Host "   Frontend: http://$SERVER_IP" -ForegroundColor White
    Write-Host "   Backend:  http://$SERVER_IP/api/" -ForegroundColor White
    Write-Host ""
    Write-Host "Useful commands:" -ForegroundColor Green
    Write-Host "   Status:     ssh $SERVER_USER@$SERVER_IP 'cd $SERVER_PATH && docker-compose -f docker-compose.production.yml ps'" -ForegroundColor White
    Write-Host "   Logs:       ssh $SERVER_USER@$SERVER_IP 'cd $SERVER_PATH && docker-compose -f docker-compose.production.yml logs -f'" -ForegroundColor White
    Write-Host "   Update:     ssh $SERVER_USER@$SERVER_IP 'cd $SERVER_PATH && ./update-containers.sh'" -ForegroundColor White
    Write-Host "   Stop:       ssh $SERVER_USER@$SERVER_IP 'cd $SERVER_PATH && docker-compose -f docker-compose.production.yml down'" -ForegroundColor White
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Green
    Write-Host "   1. Verify images are published on Docker Hub" -ForegroundColor White
    Write-Host "   2. Check .env file on server and configure SECRET_KEY" -ForegroundColor White
    Write-Host "   3. Test commands:" -ForegroundColor White
    Write-Host "      - Check container status" -ForegroundColor White
    Write-Host "      - Open http://$SERVER_IP in browser" -ForegroundColor White
    Write-Host ""
    Print-Success "Deployment completed successfully!"
}

# ============================
# MAIN BLOCK
# ============================

Print-Step "STARTING DEPLOYMENT TO SERVER $SERVER_IP"

# Check required files
foreach ($file in $FILES_TO_UPLOAD) {
    $fullPath = Join-Path $LOCAL_PROJECT_PATH $file
    if (!(Test-Path $fullPath)) {
        Print-Error "File not found: $file"
        Print-Info "Make sure you are in the project root"
        exit 1
    }
}

# Sequential execution
if (-not (Test-SSHConnection)) { exit 1 }
if (-not (Create-Directories)) { exit 1 }
if (-not (Upload-Files)) { exit 1 }
if (-not (Create-EnvFile)) { exit 1 }
if (-not (Upload-FrontendNginx)) { exit 1 }
if (-not (Setup-Permissions)) { exit 1 }
if (-not (Start-Containers)) { exit 1 }
if (-not (Check-Status)) { exit 1 }
if (-not (Setup-Cron)) { exit 1 }
if (-not (Setup-Firewall)) { exit 1 }

Print-Summary

exit 0
