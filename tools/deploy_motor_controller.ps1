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
$remoteODriveWatchdogTmp = "/tmp/configure_odrive_watchdog.py"
$remoteODriveUndervoltageTmp = "/tmp/configure_odrive_undervoltage.py"
$remoteODriveDcLimitTmp = "/tmp/configure_odrive_dc_current_limit.py"

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Step '$Name' failed with exit code $LASTEXITCODE"
    }
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
    ssh -4 $remote "rm -rf $remoteTmp $remoteStaticTmp && mkdir -p $remoteTmp $remoteStaticTmp"
}

Invoke-Step "Upload motor-controller package, template, and static assets" {
    scp -4 -r "raspberry_pi/motor_controller/." "${remote}:$remoteTmp/"
    if ($LASTEXITCODE -ne 0) { throw "Motor-controller upload failed" }
    scp -4 "raspberry_pi/templates/index.html" "${remote}:$remoteTmp/index.html"
    if ($LASTEXITCODE -ne 0) { throw "Template upload failed" }
    scp -4 -r "raspberry_pi/static/." "${remote}:$remoteStaticTmp/"
    if ($LASTEXITCODE -ne 0) { throw "Static asset upload failed" }
    scp -4 "raspberry_pi/can-interface.service" "${remote}:$remoteCanServiceTmp"
    if ($LASTEXITCODE -ne 0) { throw "CAN service upload failed" }
    scp -4 "raspberry_pi/motor-controller-v2.service" "${remote}:$remoteMotorServiceTmp"
    if ($LASTEXITCODE -ne 0) { throw "Motor service upload failed" }
    scp -4 "scripts/configure_odrive_watchdog.py" "${remote}:$remoteODriveWatchdogTmp"
    if ($LASTEXITCODE -ne 0) { throw "ODrive watchdog script upload failed" }
    scp -4 "scripts/configure_odrive_undervoltage.py" "${remote}:$remoteODriveUndervoltageTmp"
    if ($LASTEXITCODE -ne 0) { throw "ODrive undervoltage script upload failed" }
    scp -4 "scripts/configure_odrive_dc_current_limit.py" "${remote}:$remoteODriveDcLimitTmp"
}

$deployCommand = @"
set -e
staging_test_root=/tmp/ugv_deploy_test_root
rm -rf "`$staging_test_root"
mkdir -p "`$staging_test_root"
ln -s $remoteTmp "`$staging_test_root/motor_controller"
mkdir -p /tmp/templates
cp $remoteTmp/index.html /tmp/templates/index.html
mkdir -p /tmp/static
cp -a $remoteStaticTmp/. /tmp/static/
cd "`$staging_test_root"
if ! PYTHONPATH="`$staging_test_root:/home/$User/.venvs/odrive056/lib/python3.11/site-packages" python3 -m unittest discover -s motor_controller/tests -v; then
  echo 'Remote staging tests failed; running installation was not changed.' >&2
  exit 1
fi
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
install -m 755 $remoteODriveWatchdogTmp /home/$User/configure_odrive_watchdog.py
chown ${User}:${User} /home/$User/configure_odrive_watchdog.py
install -m 755 $remoteODriveUndervoltageTmp /home/$User/configure_odrive_undervoltage.py
chown ${User}:${User} /home/$User/configure_odrive_undervoltage.py
install -m 755 $remoteODriveDcLimitTmp /home/$User/configure_odrive_dc_current_limit.py
chown ${User}:${User} /home/$User/configure_odrive_dc_current_limit.py
sudo sed -i -E '/^can:/,/^[^[:space:]]/ s/^([[:space:]]+bitrate:).*/\1 250000/' $remoteApp/config.yaml
sudo install -m 644 $remoteCanServiceTmp /etc/systemd/system/can-interface.service
sudo install -m 644 $remoteMotorServiceTmp /etc/systemd/system/motor-controller-v2.service
sudo systemctl disable --now dronecan-esc.service 2>/dev/null || true
sudo systemctl stop can-interface.service || true
sudo systemctl daemon-reload
sudo systemctl enable motor-controller-v2.service
can_enabled=`$(python3 -c 'import yaml; print(str(bool(yaml.safe_load(open("/home/$User/motor_controller/config.yaml")).get("can", {}).get("enabled", True))).lower())')
if [ "`$can_enabled" = true ]; then
  sudo systemctl enable can-interface.service
  sudo systemctl start can-interface.service
else
  sudo systemctl disable can-interface.service 2>/dev/null || true
fi
sudo systemctl start motor-controller-v2.service
# Two native ODrive/Fibre discoveries take several seconds during startup.
sleep 15
systemctl is-active motor-controller-v2.service
if [ "`$can_enabled" = true ]; then
  systemctl is-active can-interface.service
  ip -details link show can0
else
  ! systemctl is-active --quiet can-interface.service
fi
grep -A3 '^can:' $remoteApp/config.yaml
curl -fsS -o /dev/null -w 'root=%{http_code}\n' http://localhost/
curl -fsS -o /dev/null -w 'status=%{http_code}\n' http://localhost/api/status
echo backup=`$backup
"@

# Das Here-String uebernimmt die Zeilenenden dieser Datei. Liegt sie mit CRLF
# im Arbeitsverzeichnis (Windows-Editor oder core.autocrlf), scheitert bash auf
# dem Pi schon an "set: -\r: Ungueltige Option".
$deployCommand = $deployCommand -replace "`r`n", "`n"
$remoteScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($deployCommand))
Invoke-Step "Install, verify, and restart on remote" {
    ssh -4 $remote "echo $remoteScript | base64 -d | bash"
}

Invoke-Step "Check recent service errors" {
    ssh -4 $remote "journalctl -u motor-controller-v2.service --since '2 minutes ago' --no-pager -p err..alert || true"
}

Write-Host ""
Write-Host "Deploy complete." -ForegroundColor Green
