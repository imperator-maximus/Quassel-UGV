param(
    [string]$HostName = "raspberrycan",
    [string]$User = "nicolay",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$remote = "$User@$HostName"
$remoteTmp = "/tmp/ugv_deploy_motor_controller"
$remoteApp = "/home/$User/motor_controller"
$remoteTemplates = "/home/$User/templates"

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Command
}

Set-Location $repoRoot

if (-not $SkipTests) {
    Invoke-Step "Install local dev dependencies" {
        python -m pip install -r requirements-dev.txt
    }
    Invoke-Step "Run motor-controller tests" {
        python -m unittest discover -s raspberry_pi/motor_controller/tests -v
    }
    Invoke-Step "Run sensor-hub tests" {
        python -m unittest discover -s sensor_hub/tests -v
    }
}

Invoke-Step "Prepare remote staging directory" {
    ssh $remote "rm -rf $remoteTmp && mkdir -p $remoteTmp"
}

Invoke-Step "Upload motor-controller package and template" {
    scp -r "raspberry_pi/motor_controller/." "${remote}:$remoteTmp/"
    scp "raspberry_pi/templates/index.html" "${remote}:$remoteTmp/index.html"
}

$deployCommand = @"
set -e
ts=`$(date +%Y%m%d_%H%M%S)
backup=/home/$User/backup/motor_controller_`$ts
mkdir -p /home/$User/backup
sudo cp -a $remoteApp "`$backup"
sudo find $remoteApp -mindepth 1 -maxdepth 1 ! -name config.yaml -exec rm -rf {} +
sudo cp -a $remoteTmp/. $remoteApp/
sudo rm -f $remoteApp/index.html
mkdir -p $remoteTemplates $remoteApp/web/templates
cp $remoteTmp/index.html $remoteTemplates/index.html
cp $remoteTmp/index.html $remoteApp/web/templates/index.html
sudo chown -R ${User}:${User} $remoteApp $remoteTemplates/index.html
cd /home/$User
python3 -m unittest discover -s motor_controller/tests -v
sudo systemctl restart motor-controller-v2.service
sleep 5
systemctl is-active motor-controller-v2.service
curl -s -o /dev/null -w 'root=%{http_code}\n' http://localhost/
curl -s -o /dev/null -w 'status=%{http_code}\n' http://localhost/api/status
echo backup=`$backup
"@

$remoteScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($deployCommand))
Invoke-Step "Install, verify, and restart on remote" {
    ssh $remote "echo $remoteScript | base64 -d | bash"
}

Invoke-Step "Check recent service errors" {
    ssh $remote "journalctl -u motor-controller-v2.service --since '2 minutes ago' --no-pager -p err..alert || true"
}

Write-Host ""
Write-Host "Deploy complete." -ForegroundColor Green
