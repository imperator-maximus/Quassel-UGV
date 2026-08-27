"""Die Oberflaeche ist ein einziger Skriptblock - ein Tippfehler kostet alles.

Am 27.08.2026 geriet beim Einfuegen ein echter Zeilenumbruch in einen
einfach gequoteten JavaScript-String. Die Seite lud weiter, der Server
antwortete mit 200, und die Tests blieben gruen - aber der Browser brach das
Skript an dieser Stelle ab, und damit war der Joystick weg. Aufgefallen ist es
erst dem User am Fahrzeug.

Dieser Test liest deshalb dasselbe, was der Browser bekommt, und laesst es von
node auf Syntax pruefen. Ohne node wird uebersprungen: Auf dem Pi ist es nicht
installiert, und dort laeuft dieselbe Suite.
"""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[2] / 'templates' / 'index.html'

# Nur die eingebetteten Bloecke. Fremde Bibliotheken kommen ueber `src` und
# gehoeren nicht zu dem, was hier geprueft werden kann.
INLINE_SCRIPT = re.compile(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.S)


@unittest.skipUnless(TEMPLATE.exists(), 'Oberflaeche liegt nicht im Pruefpfad')
@unittest.skipUnless(shutil.which('node'), 'node nicht verfuegbar')
class TheInterfaceScriptMustParseTests(unittest.TestCase):
    def test_the_embedded_script_is_valid_javascript(self):
        blocks = INLINE_SCRIPT.findall(TEMPLATE.read_text(encoding='utf-8'))
        self.assertTrue(blocks, 'Kein eingebetteter Skriptblock gefunden')

        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'oberflaeche.js'
            script.write_text('\n'.join(blocks), encoding='utf-8')
            result = subprocess.run(
                ['node', '--check', str(script)],
                capture_output=True,
                text=True,
                timeout=60,
            )

        self.assertEqual(
            result.returncode,
            0,
            f'JavaScript der Oberflaeche ist fehlerhaft:\n{result.stderr}',
        )


if __name__ == '__main__':
    unittest.main()
