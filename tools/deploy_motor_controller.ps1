param(
    [string]$HostName = "raspberrycan",
    [string]$User = "nicolay",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$remote = "$User@$HostName"
$remoteTmp = "/tmp/ugv_deploy_motor_controller"
$remoteStaticTmp = "/tmp/ugv_deploy_static"
$remoteApp = "/home/$User/motor_controller"
$remoteTemplates = "/home/$User/templates"
$remoteStatic = "/home/$User/static"
$remoteCanServiceTmp = "/tmp/ugv-can-interface.service"
$remoteMotorServiceTmp = "/tmp/ugv-motor-controller-v2.service"

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
    ssh $remote "rm -rf $remoteTmp $remoteStaticTmp && mkdir -p $remoteTmp $remoteStaticTmp"
}

Invoke-Step "Upload motor-controller package, template, and static assets" {
    scp -r "raspberry_pi/motor_controller/." "${remote}:$remoteTmp/"
    scp "raspberry_pi/templates/index.html" "${remote}:$remoteTmp/index.html"
    scp -r "raspberry_pi/static/." "${remote}:$remoteStaticTmp/"
    scp "raspberry_pi/can-interface.service" "${remote}:$remoteCanServiceTmp"
    scp "raspberry_pi/motor-controller-v2.service" "${remote}:$remoteMotorServiceTmp"
}

$deployCommand = @"
set -e
ts=`$(date +%Y%m%d_%H%M%S)
backup=/home/$User/backup/motor_controller_`$ts
mkdir -p /home/$User/backup
sudo cp -a $remoteApp "`$backup"
sudo cp -a /etc/systemd/system/can-interface.service "/home/$User/backup/can-interface_`$ts.service" 2>/dev/null || true
sudo cp -a /etc/systemd/system/motor-controller-v2.service "/home/$User/backup/motor-controller-v2_`$ts.service" 2>/dev/null || true
sudo systemctl stop motor-controller-v2.service || true
sudo find $remoteApp -mindepth 1 -maxdepth 1 ! -name config.yaml -exec rm -rf {} +
sudo cp -a $remoteTmp/. $remoteApp/
sudo rm -f $remoteApp/index.html
mkdir -p $remoteTemplates $remoteApp/web/templates
cp $remoteTmp/index.html $remoteTemplates/index.html
cp $remoteTmp/index.html $remoteApp/web/templates/index.html
mkdir -p $remoteStatic
cp -a $remoteStaticTmp/. $remoteStatic/
sudo chown -R ${User}:${User} $remoteApp $remoteTemplates/index.html $remoteStatic
sudo sed -i -E '/^can:/,/^[^[:space:]]/ s/^([[:space:]]+bitrate:).*/\1 250000/' $remoteApp/config.yaml
sudo install -m 644 $remoteCanServiceTmp /etc/systemd/system/can-interface.service
sudo install -m 644 $remoteMotorServiceTmp /etc/systemd/system/motor-controller-v2.service
sudo systemctl disable --now dronecan-esc.service 2>/dev/null || true
sudo systemctl stop can-interface.service || true
sudo systemctl daemon-reload
sudo systemctl enable can-interface.service motor-controller-v2.service
sudo systemctl start can-interface.service
cd /home/$User
python3 -m unittest discover -s motor_controller/tests -v
sudo systemctl start motor-controller-v2.service
sleep 5
systemctl is-active can-interface.service
systemctl is-active motor-controller-v2.service
ip -details link show can0
grep -A2 '^can:' $remoteApp/config.yaml
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
