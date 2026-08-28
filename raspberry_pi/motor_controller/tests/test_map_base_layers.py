"""Tests fuer die Umschaltung des Kartenhintergrunds.

Die Luftbildumschaltung gab es schon, sie steckte aber in der Gruppe
``map-edit-control``, die der Plan-Modus komplett ausblendet. Damit war das
Satellitenbild ausgerechnet dort weg, wo man es braucht: beim Vergleich der
geplanten Bahnen mit der echten Flaeche. Diese Tests halten das fest.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TEMPLATE = REPO / 'raspberry_pi' / 'templates' / 'index.html'
EDITOR_JS = REPO / 'raspberry_pi' / 'static' / 'js' / 'mapping_editor.js'


class MapBaseLayerMarkupTests(unittest.TestCase):
    def setUp(self):
        self.html = TEMPLATE.read_text(encoding='utf-8')

    def test_beide_hintergruende_haben_einen_knopf(self):
        for element_id in ('osmLayerBtn', 'bingLayerBtn'):
            self.assertIn(f'id="{element_id}"', self.html)

    def test_esri_ist_wieder_entfallen(self):
        """Sein Bild endet hier bei Zoom 19 und war beim Planen nur Brei."""
        self.assertNotIn('esriLayerBtn', self.html)

    def test_umschaltung_wird_im_planmodus_nicht_ausgeblendet(self):
        """Der Kern der Sache: die Zeile darf nicht in der versteckten Gruppe stehen."""
        zeile = None
        for kandidat in self.html.split('\n'):
            if 'osmLayerBtn' in kandidat:
                zeile = kandidat
                break
        self.assertIsNotNone(zeile, 'Layer-Knopf nicht gefunden')
        # Der umgebende Container ist die Zeile davor.
        index = self.html.index('id="osmLayerBtn"')
        container = self.html.rfind('<div', 0, index)
        container_tag = self.html[container:self.html.index('>', container) + 1]
        self.assertNotIn(
            'map-edit-control', container_tag,
            'Die Layer-Umschaltung darf nicht in der Gruppe stehen, die '
            'enterPlanUiMode() ausblendet - sonst fehlt das Luftbild genau '
            'beim Pruefen der Bahnen.',
        )


class MapBaseLayerScriptTests(unittest.TestCase):
    def setUp(self):
        self.js = EDITOR_JS.read_text(encoding='utf-8')

    def test_esri_ist_vollstaendig_entfernt(self):
        # Auf die Kachel-Adresse pruefen, nicht auf den Namen: der Kommentar
        # im Quelltext haelt fest, warum die Quelle wieder rausflog, und soll
        # stehenbleiben duerfen.
        self.assertNotIn('mapLayers.esri', self.js)
        self.assertNotIn('arcgisonline.com', self.js)

    def test_native_zoomgrenze_ist_gesetzt(self):
        """Ohne maxNativeZoom liefert der Dienst oberhalb nur Platzhalter.

        Am Standplatz nachgemessen: Bing hat echte Bilddaten bis Zoom 20.
        Darueber antwortet er mit HTTP 200, aber fuer jede Kachel mit
        demselben Bild.
        """
        bing = re.search(r'mapLayers\.bing = new BingLayer\(.*?\}\)', self.js, re.S)
        self.assertIsNotNone(bing)
        self.assertIn('maxNativeZoom: 20', bing.group(0))

    def test_auswahl_wird_gemerkt(self):
        self.assertIn('BASE_LAYER_STORAGE_KEY', self.js)
        self.assertIn('loadPreferredBaseLayer', self.js)

    def test_gespeicherte_auswahl_wird_gegen_die_bekannten_layer_geprueft(self):
        """Ein fremder Wert im Speicher darf die Karte nicht leer lassen."""
        self.assertIn('BASE_LAYER_BUTTONS[gespeichert]', self.js)

    def test_alte_esri_auswahl_landet_auf_dem_luftbild(self):
        """Wer Esri gewaehlt hatte, wollte kein Strassennetz sehen."""
        self.assertIn("gespeichert === 'esri'", self.js)

    def test_zugriff_auf_den_speicher_ist_abgesichert(self):
        """In privaten Fenstern wirft localStorage - die Karte muss trotzdem kommen."""
        laden = self.js[self.js.index('function loadPreferredBaseLayer'):]
        laden = laden[:laden.index('function setMapBaseLayer')]
        self.assertIn('try {', laden)
        self.assertIn('catch', laden)

    def test_hintergrund_bleibt_unter_den_anderen_ebenen(self):
        self.assertIn('bringToBack', self.js)


if __name__ == '__main__':
    unittest.main()
