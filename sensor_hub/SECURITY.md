# 🔒 Sicherheit - Quassel UGV Sensor Hub

## ⚠️ Wichtige Sicherheitsrichtlinien

### 1. NIEMALS Credentials in Code speichern!

❌ **FALSCH:**
```python
# config.py
NTRIP_USERNAME = 'odmv-3569452'
NTRIP_PASSWORD = 'hSahH6jy9e'
```

✅ **RICHTIG:**
```python
# config.py
NTRIP_USERNAME = os.getenv('NTRIP_USERNAME', '')
NTRIP_PASSWORD = os.getenv('NTRIP_PASSWORD', '')
```

### 2. Environment Variables (.env Datei)

Die `.env` Datei enthält sensitive Daten:
- NTRIP Benutzername und Passwort
- Zugangsdaten des Webservers (`WEB_AUTH_USERNAME`, `WEB_AUTH_PASSWORD`)
- API-Keys
- Datenbank-Credentials
- Andere sensitive Konfiguration

**Diese Datei wird NICHT in Git committed!**

### 2a. Zugangsschutz des Webservers

Der SensorHub ist über eine Portfreigabe aus dem Internet erreichbar und
liefert die metergenaue Position des Fahrzeugs. Er verlangt deshalb eine
Anmeldung per HTTP-Basic-Auth:

```
WEB_AUTH_ENABLED=1
WEB_AUTH_USERNAME=ugv
WEB_AUTH_PASSWORD=hier-ein-langes-passwort
```

`WEB_AUTH_PASSWORD` akzeptiert Klartext oder einen Werkzeug-Hash:

```bash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash(input('Passwort: ')))"
```

Ohne gesetztes Passwort antwortet der Server auf jede Anfrage mit 503 - eine
aktivierte, aber unvollständige Konfiguration führt nie zu freiem Zugang.

**Achtung:** Der Raspberry-Hauptrechner ruft die Telemetrie über dieselben
Routen ab. Er braucht dieselben Zugangsdaten in
`SENSOR_HUB_TELEMETRY_PASSWORD`, sonst bleibt die Pose aus und der Fahrantrieb
pausiert. Einzelheiten in `raspberry_pi/WEB_ZUGANGSSCHUTZ.md`.

**Reihenfolge:** Der SensorHub wird als **zweites** ausgerollt, nach dem
Raspberry. Ein SensorHub, der schon Anmeldung verlangt, während der Raspberry
noch alten Code fährt, weist dessen Telemetrieabruf mit 401 ab und legt den
Fahrantrieb still. Umgekehrt ist es unkritisch.

Basic-Auth ohne TLS überträgt das Passwort mitlesbar. Es hält Portscanner und
Gelegenheitsfunde ab, nicht jemanden, der den Datenverkehr beobachtet.

### 3. Setup auf neuem System

```bash
# 1. Repository klonen
git clone <repo>
cd sensor_hub

# 2. .env Datei erstellen (aus Template)
cp .env.example .env

# 3. .env mit deinen Credentials füllen
nano .env

# 4. Dependencies installieren
pip3 install python-dotenv

# 5. Anwendung starten
python3 sensor_hub_app.py
```

### 4. .gitignore Konfiguration

Die `.gitignore` Datei verhindert, dass sensitive Dateien committed werden:

```
.env              # Hauptkonfiguration mit Credentials
.env.local        # Lokale Overrides
__pycache__/      # Python Cache
*.log             # Log-Dateien
```

### 5. Credentials Rotation

Falls Credentials kompromittiert sind:

1. **Sofort ändern** auf dem NTRIP-Server
2. **Neue Credentials** in `.env` eintragen
3. **Anwendung neustarten**
4. **Logs überprüfen** auf verdächtige Aktivitäten

### 6. Sichere Entwicklung

**Vor dem Commit überprüfen:**
```bash
# Zeige alle Dateien die committed werden
git status

# Überprüfe ob .env in .gitignore ist
cat .gitignore | grep "^\.env"

# Überprüfe ob Credentials in Code sind
grep -r "NTRIP_PASSWORD\|NTRIP_USERNAME" --include="*.py" | grep -v "os.getenv"
```

### 7. Production Deployment

Für Production-Systeme:

1. **Separate .env Datei** pro System
2. **Restricted File Permissions:**
   ```bash
   chmod 600 .env
   ```
3. **Secrets Management** verwenden (z.B. HashiCorp Vault)
4. **Audit Logging** aktivieren
5. **Regelmäßige Credential Rotation**

### 8. Notfall-Checkliste

Falls Credentials exposed sind:

- [ ] Credentials sofort auf Server ändern
- [ ] Neue Credentials in `.env` eintragen
- [ ] Anwendung neustarten
- [ ] Logs auf verdächtige Aktivitäten überprüfen
- [ ] Git History überprüfen (falls versehentlich committed)
- [ ] Falls in Git: `git filter-branch` verwenden um zu entfernen

### 9. Weitere Ressourcen

- [OWASP: Secrets Management](https://owasp.org/www-community/Sensitive_Data_Exposure)
- [12 Factor App: Config](https://12factor.net/config)
- [Python-dotenv Dokumentation](https://github.com/theskumar/python-dotenv)

---

**Sicherheit ist keine Einmalaufgabe - es ist ein kontinuierlicher Prozess!**

