param(
    [string]$HostName = "raspberrycan",
    [string]$User = "nicolay",
    # Steht das Fahrzeug nicht im LAN, laeuft der Zugang ueber die Portfreigabe
    # des Routers - dort liegt SSH nicht auf 22.
    [int]$Port = 22,
    # Ein Ausrollvorgang laedt hoch und startet neu, sonst nichts. Tests sind
    # ausdruecklich anzufordern - sie gehoeren in den Arbeitsablauf davor und
    # nicht in jeden einzelnen Ausrollvorgang.
    #
    # -Tests laesst beide Suiten hier auf dem Entwicklungsrechner laufen
    # (unter einer Minute).
    [switch]$Tests,
    # -RemoteTests laesst dieselbe Suite zusaetzlich auf dem Pi laufen. Das
    # dauert dort rund zehn Minuten und ist der ausgesprochene Sonderfall:
    # sinnvoll, wenn sich an Abhaengigkeiten oder Python-Version auf dem
    # Geraet etwas geaendert hat. Schlaegt sie fehl, bleibt die laufende
    # Installation unberuehrt.
    [switch]$RemoteTests,
    # Sprungrechner, falls das Fahrzeug nicht direkt erreichbar ist. Am
    # Mobilfunkrouter ist es das immer: Die SIM haengt hinter CGNAT, es gibt
    # keine eingehende Verbindung. Der Weg fuehrt dann ueber den
    # Rueckwaertstunnel - der bindet auf 127.0.0.1 des Zielrechners, also
    # muss von dort gesprungen werden.
    #
    #   -Jump ugvtunnel@schloss.fdog.de:2224 -HostName 127.0.0.1 -Port 12222
    #
    # Steht das Fahrzeug im LAN, bleibt der Schalter weg.
    [string]$Jump = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$remote = "$User@$HostName"
$sshPort = @("-p", "$Port")
$scpPort = @("-P", "$Port")
$jumpArgs = if ($Jump) { @("-J", "$Jump") } else { @() }
$remoteTmp = "/tmp/ugv_deploy_motor_controller"
$remoteStaticTmp = "/tmp/ugv_deploy_static"
$remoteApp = "/home/$User/motor_controller"
$remoteTemplates = "/home/$User/templates"
$remoteStatic = "/home/$User/static"
$remoteMotorServiceTmp = "/tmp/ugv-motor-controller-v2.service"
$remoteODriveWatchdogTmp = "/tmp/configure_odrive_watchdog.py"
$remoteODriveUndervoltageTmp = "/tmp/configure_odrive_undervoltage.py"
$remoteODriveDcLimitTmp = "/tmp/configure_odrive_dc_current_limit.py"
$remotePackageTar = "/tmp/ugv_deploy_motor_controller.tar.gz"
$remoteStaticTar = "/tmp/ugv_deploy_static.tar.gz"
$localPackageTar = Join-Path ([System.IO.Path]::GetTempPath()) "ugv_deploy_motor_controller.tar.gz"
$localStaticTar = Join-Path ([System.IO.Path]::GetTempPath()) "ugv_deploy_static.tar.gz"

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

if ($Tests) {
    Invoke-Step "Install local dev dependencies" {
        python -m pip install -r requirements-dev.txt
    }
    Invoke-Step "Run motor-controller tests" {
        python -m unittest discover -s raspberry_pi/motor_controller/tests -v
    }
}

Invoke-Step "Prepare remote staging directory" {
    ssh -4 @jumpArgs @sshPort $remote "rm -rf $remoteTmp $remoteStaticTmp && mkdir -p $remoteTmp $remoteStaticTmp"
}

# Verzeichnisse gehen gepackt ueber die Leitung, nicht Datei fuer Datei. Am
# Mobilfunkrouter ist das der Unterschied zwischen Sekunden und einer
# Viertelstunde: Das Paket wiegt roh 6,1 MB, wovon 3 MB kompilierter
# Bytecode sind, den der Pi ohnehin neu erzeugt, und rund 1 MB eine
# eingefrorene Planaufzeichnung fuer die Tests. Gepackt und ohne
# __pycache__ bleiben davon knapp 500 KB.
#
# Die Tests bleiben bewusst drin - sonst laeuft `-RemoteTests` ins Leere,
# wenn es doch einmal gebraucht wird.
Invoke-Step "Upload motor-controller package, template, and static assets" {
    tar -czf $localPackageTar --exclude=__pycache__ -C "raspberry_pi/motor_controller" .
    if ($LASTEXITCODE -ne 0) { throw "Packing the motor-controller package failed" }
    tar -czf $localStaticTar -C "raspberry_pi/static" .
    if ($LASTEXITCODE -ne 0) { throw "Packing the static assets failed" }

    scp -4 @jumpArgs @scpPort "$localPackageTar" "${remote}:$remotePackageTar"
    if ($LASTEXITCODE -ne 0) { throw "Motor-controller upload failed" }
    scp -4 @jumpArgs @scpPort "$localStaticTar" "${remote}:$remoteStaticTar"
    if ($LASTEXITCODE -ne 0) { throw "Static asset upload failed" }
    ssh -4 @jumpArgs @sshPort $remote "tar -xzf $remotePackageTar -C $remoteTmp && tar -xzf $remoteStaticTar -C $remoteStaticTmp && rm -f $remotePackageTar $remoteStaticTar"
    if ($LASTEXITCODE -ne 0) { throw "Unpacking on the remote failed" }

    scp -4 @jumpArgs @scpPort "raspberry_pi/templates/index.html" "${remote}:$remoteTmp/index.html"
    if ($LASTEXITCODE -ne 0) { throw "Template upload failed" }
    scp -4 @jumpArgs @scpPort "raspberry_pi/motor-controller-v2.service" "${remote}:$remoteMotorServiceTmp"
    if ($LASTEXITCODE -ne 0) { throw "Motor service upload failed" }
    scp -4 @jumpArgs @scpPort "scripts/configure_odrive_watchdog.py" "${remote}:$remoteODriveWatchdogTmp"
    if ($LASTEXITCODE -ne 0) { throw "ODrive watchdog script upload failed" }
    scp -4 @jumpArgs @scpPort "scripts/configure_odrive_undervoltage.py" "${remote}:$remoteODriveUndervoltageTmp"
    if ($LASTEXITCODE -ne 0) { throw "ODrive undervoltage script upload failed" }
    scp -4 @jumpArgs @scpPort "scripts/configure_odrive_dc_current_limit.py" "${remote}:$remoteODriveDcLimitTmp"
}

# Der Testblock wird vor dem Here-String zusammengesetzt, damit der Schalter
# nur ueber diese eine Stelle entscheidet.
if (-not $RemoteTests) {
    $remoteTestBlock = "echo 'Kein Testlauf auf dem Pi (-RemoteTests nicht gesetzt).'"
} else {
    $remoteTestBlock = @'
if ! PYTHONPATH="$staging_test_root:/home/USERPLATZHALTER/.venvs/odrive056/lib/python3.11/site-packages" python3 -m unittest discover -s motor_controller/tests -v; then
  echo 'Remote staging tests failed; running installation was not changed.' >&2
  exit 1
fi
'@
    $remoteTestBlock = $remoteTestBlock -replace 'USERPLATZHALTER', $User
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
$remoteTestBlock
ts=`$(date +%Y%m%d_%H%M%S)
backup=/home/$User/backup/motor_controller_`$ts
mkdir -p /home/$User/backup
sudo cp -a $remoteApp "`$backup"
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
sudo install -m 644 $remoteMotorServiceTmp /etc/systemd/system/motor-controller-v2.service
# Der Bus ist ausgebaut. Die Einheiten dazu bleiben sonst als aktivierte
# Leichen auf dem Geraet stehen und ziehen bei jedem Boot einen Fehlversuch.
sudo systemctl disable --now dronecan-esc.service 2>/dev/null || true
sudo systemctl disable --now can-interface.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/can-interface.service
sudo systemctl daemon-reload
sudo systemctl enable motor-controller-v2.service
sudo systemctl start motor-controller-v2.service
systemctl is-active motor-controller-v2.service
# Zwei native ODrive/Fibre-Suchlaeufe brauchen beim Start mehrere Sekunden,
# der Webserver lauscht erst danach. Ein fester sleep hat genau an dieser
# Grenze gestanden und die Pruefung unten in ein "connection refused"
# laufen lassen, obwohl der Dienst sauber hochkam. Also warten, bis der
# Port antwortet - und nur aufgeben, wenn er es innerhalb einer Minute
# nicht tut.
for versuch in `$(seq 1 60); do
  if curl -s -o /dev/null --max-time 2 http://localhost/; then
    echo "Webserver antwortet nach `${versuch}s"
    break
  fi
  if [ "`$versuch" = 60 ]; then
    echo 'FEHLER: Webserver antwortet nach 60s nicht' >&2
    exit 1
  fi
  sleep 1
done
! systemctl is-active --quiet can-interface.service
grep -A6 '^pose:' $remoteApp/config.yaml
# Die Oberflaeche verlangt eine Anmeldung. Die Zugangsdaten stehen in der
# EnvironmentFile des Dienstes und bleiben damit auf dem Geraet - sie duerfen
# weder in diesem Skript noch in der Prozessliste auftauchen.
# Die Datei gehoert root und hat Modus 600 - der Deploy-Benutzer kommt nur
# ueber sudo heran. Ohne sudo blieben die Variablen leer und die Pruefung
# liefe unangemeldet in ein 401.
web_user=`$(sudo sed -n 's/^UGV_WEB_USERNAME=//p' /etc/ugv-web.env 2>/dev/null | tail -1)
web_pass=`$(sudo sed -n 's/^UGV_WEB_PASSWORD=//p' /etc/ugv-web.env 2>/dev/null | tail -1)
if [ -n "`$web_pass" ]; then
  curl -fsS -u "`$web_user:`$web_pass" -o /dev/null -w 'root=%{http_code}\n' http://localhost/
  curl -fsS -u "`$web_user:`$web_pass" -o /dev/null -w 'status=%{http_code}\n' http://localhost/api/status
  unauth=`$(curl -s -o /dev/null -w '%{http_code}' http://localhost/api/status)
  echo "ohne Anmeldung=`$unauth (401 erwartet)"
  [ "`$unauth" = 401 ] || { echo 'FEHLER: Oberflaeche antwortet ohne Anmeldung' >&2; exit 1; }
else
  echo 'WARNUNG: /etc/ugv-web.env fehlt oder ist leer - Weboberflaeche antwortet mit 503' >&2
  curl -fsS -o /dev/null -w 'root=%{http_code}\n' http://localhost/
  curl -fsS -o /dev/null -w 'status=%{http_code}\n' http://localhost/api/status
fi
echo backup=`$backup
"@

# Das Here-String uebernimmt die Zeilenenden dieser Datei. Liegt sie mit CRLF
# im Arbeitsverzeichnis (Windows-Editor oder core.autocrlf), scheitert bash auf
# dem Pi schon an "set: -\r: Ungueltige Option".
$deployCommand = $deployCommand -replace "`r`n", "`n"
$remoteScript = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($deployCommand))
Invoke-Step "Install, verify, and restart on remote" {
    ssh -4 @jumpArgs @sshPort $remote "echo $remoteScript | base64 -d | bash"
}

Invoke-Step "Check recent service errors" {
    ssh -4 @jumpArgs @sshPort $remote "journalctl -u motor-controller-v2.service --since '2 minutes ago' --no-pager -p err..alert || true"
}

Remove-Item -Force -ErrorAction SilentlyContinue $localPackageTar, $localStaticTar

Write-Host ""
Write-Host "Deploy complete." -ForegroundColor Green
