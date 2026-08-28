# Fusion360-Skript: Halterung fuer Huawei LTE Cube E5180 an der Heckstrebe
# Wird ueber den Fusion-MCP-Server ausgefuehrt (featureType=script).
#
# Zweck: Der LTE-Router (110 x 70 x 70 mm, 250 g) sitzt mittig an der hinteren
# Vierkantstrebe des Hauptgehaeuses - der Strebe, auf der der Deckel aufliegt.
# Profil steht HOCHKANT: 50 mm hoch, 24 mm tief (nachgemessen). Der Deckel
# schliesst buendig mit der hinteren Flaeche ab. Die Strebe steht leicht
# schraeg - laut User unkritisch, der Halter kippt mit.
#
# Vier Teile:
#   1) schelle_oben  - Zunge auf der 24er-Flaeche (liegt unter dem Deckel),
#      Rueckplatte, Bosse fuer den Buegel, zwei Aufhaengebolzen + Sicherung.
#   2) schelle_strap - Buegel unter der Strebe, vorn mit Hakenlippe, hinten
#      mit zwei M3 nach oben in die Bosse verschraubt.
#   3) wanne         - Schale mit hoher Rueckwand, Wuerfel von oben eingelegt.
#   4) dach          - Platte mit Tropfkante, vier M4 auf die Wanne.
#
# LAGE DES WUERFELS: STEHEND (Entscheidung des Users am 20.08.2026). Der
# Empfangstest war in allen Lagen gleich gut, also entscheidet die Mechanik -
# und stehend gewinnt aus drei Gruenden: schmaler (83 statt 123 mm Breite),
# das Stromkabel geht unten nach innen zum Gehaeuse weg, und vor allem liegt
# die WPS-Taste dann OBEN. Liegend zeigte sie zur Seite, wo die Wand sie beim
# Fahren ausgeloest hat. Stehend liegen an allen vier Seitenflaechen nur
# tastenfreie Flaechen an, und nach oben stehen 5 mm Luft zum Dach. Die Anschlussseite (Netzteil, RJ45, RJ11 - alle auf der
# Rueckseite des Geraets) zeigt nach VORN zum Fahrzeug, davor 14 mm
# Steckerbucht. Das Kabel faellt durch die Bodenschlitze nach unten ab.
# ACHTUNG: In die 14 mm passt nur ein WINKELSTECKER.
#
# WARUM SCHLUESSELLOCH statt Schwalbenschwanz (Umbau 20.08.2026):
# Der erste Entwurf hatte die Schwalbenschwanznut in der Wand der Wiege. Beim
# Druck stellte sich heraus: die Nut und die zwei Taschen sind SACKLOECHER, die
# auf dem Bett anfangen und sich 4,5 mm hoeher wieder schliessen - drei Decken,
# die gestuetzt werden muessen. Stuetzmaterial in einer Schwalbenschwanznut
# bekommt man nicht sauber heraus, damit war die Passung hin. Ersatz ist eine
# Schluessellochaufhaengung: zwei Bolzen stehen von der Schelle ab, die Wanne
# wird aufgesetzt und nach unten gedrueckt, die Koepfe hintergreifen die Wand.
# Das Schluesselloch ist ein DURCHGANGSLOCH - es hat in keiner Druckrichtung
# eine Decke. Eine dritte M4 unten sichert gegen Hochrutschen.
#
# WARUM ZWEITEILIG VERSCHRAUBT (Schelle): Vierkantrohre sind nicht massgenau,
# und ein federndes ASA-Teil ist draussen das erste, was nach UV und Frost
# bricht. Der Buegel wird angezogen, der Spalt darf sein was er will. Zwischen
# Buegel und Strebe kommt ein 2 mm EPDM-Streifen - der nimmt die Rohrtoleranz
# auf und greift, ohne den Lack zu beschaedigen.
#
# VERDREHSICHERUNG: Die Zunge liegt unter dem Deckel und wird von ihm
# niedergehalten. 250 g auf Hebel sind bei 10 g Stoss rund 1,7 Nm - das haelt
# keine Reibschelle allein, mit der Zunge muss sie es auch nicht.
#
# GEWINDELOCHMASSE: Alle Verbindungen sind M4, damit nur eine Schraubensorte
# noetig ist. Der Buegel war zwischenzeitlich M3, weil die Rueckplatte damals
# nur 8 mm dick war und ein 5,6er Loch dort zu wenig Wand uebrig liess. Seit
# die Platte 12 mm dick ist, passt M4 mit gut 3 mm Wand ringsum.
#
# Zwei Lochmasse fuer M4: 5,6 mm, wenn die Bohrung in Aufbaurichtung steht,
# und 5,8 mm, wenn sie quer dazu liegt. Liegende Bohrungen fallen im Druck
# etwas zu eng aus - der User bekam die Gewinde sonst kaum hinein.
#
# DRUCKRICHTUNGEN - alle vier Teile stuetzenfrei:
#   schelle_oben  auf der RUECKPLATTE stehend, also der Flaeche, an der die
#                 Wanne anliegt. Aufbaurichtung ist Modell-Y. Kopfueber ginge
#                 nicht mehr: seit die Platte nach oben durchlaeuft, wuerde
#                 der Bau oben beginnen, und die Zunge taeuchte spaeter
#                 als 24x84-Insel in der Luft auf. Auf der Rueckplatte
#                 stehend wird der Querschnitt dagegen nur kleiner, nie
#                 groesser - null Ueberhang.
#   schelle_strap flach.
#   wanne         auf dem Boden stehend, Waende wachsen nach oben. Die
#                 Schlitze sind Loecher in den ersten Lagen, die
#                 Schluesselloecher Durchgangsloecher in einer senkrechten
#                 Wand. Bauhoehe 80 mm, aber nirgends eine Decke.
#   dach          Platte flach auf dem Bett, 5 mm hoch.
#
# EINBAUVORAUSSETZUNG, am Fahrzeug zu pruefen: Die Hakenlippe des Buegels
# braucht 6 mm Luft VOR der Strebe, ab 40 mm unterhalb der Oberkante abwaerts,
# also im untersten Drittel der 50-mm-Flanke.
#
# NACH JEDEM EXPORT:  python cad/clean_stl.py cad/asa_router_e5180_*.stl
# Fusion legt beim Triangulieren grosser ebener Flaechen mit Loechern - vor
# allem beim Wannenboden mit seinen Schlitzen - ein paar extrem schmale
# Dreiecke ab (Kante bis 92 mm, Hoehe 0,0002 mm). Sie liegen flach in ihrer
# Ebene und aendern nichts an der Form, der Slicer zeichnet sie aber als
# Faecher von Spitzen quer durchs Bauteil. An den Exportoptionen laesst sich
# das nicht abstellen. clean_stl.py zieht sie per Kantenkollaps zusammen.
#
# Koordinaten (mm): X laengs der Strebe, 0 = Mitte.
#                   Y vorn/hinten, 0 = hintere Flaeche der Strebe, +Y = nach
#                     hinten aus dem Fahrzeug heraus.
#                   Z senkrecht, 0 = Oberseite der Strebe, +Z = oben.
# Masse in mm (Fusion-API rechnet intern in cm -> mm()-Helper).

import adsk.core
import adsk.fusion
import math

import os

# --- Strebe (vom User nachgemessen, Rohr nicht massgenau) ---
RAIL_D = 24.0
RAIL_H = 50.0

# --- Schelle ---
CLAMP_W = 84.0
TONGUE_T = 2.5         # Zunge unter dem Deckel - User: 2-3 mm merkt man nicht
TONGUE_CHAMFER = 1.5   # Enden anfasen, damit der Deckel auflaeuft
BACK_T = 12.0          # Rueckplatte, muss die M4-Aufhaengung aufnehmen

# --- Einschmelzgewinde nach den Druckregeln des Users ---
# 4,3 statt der 4,0 aus den bisherigen Druckregeln: bei 4,0 liessen sich die
# Gewinde nur schwer einschmelzen. Dazu kommt, dass dieses Loch in der
# gewaehlten Druckrichtung LIEGEND gedruckt wird - liegende Bohrungen fallen
# ohnehin etwas zu eng aus.
INS_M3_D = 4.3
INS_M3_DEPTH = 6.5
CLEAR_M3 = 3.4
INS_M4_D = 5.6         # stehend gebohrt, also in Aufbaurichtung
INS_M4_D_FLAT = 5.8    # liegend gebohrt - faellt im Druck etwas zu eng aus
INS_M4_DEPTH = 9.0
CLEAR_M4 = 4.5

# --- Buegel unter der Strebe (M4) ---
STRAP_T = 5.0
STRAP_Z_TOP = -52.2    # 0,2 mm Luft zum Boss, damit die Schraube ziehen kann
STRAP_Y_FRONT = -RAIL_D - 6.5
STRAP_Y_BACK = 11.0    # bleibt 1 mm vor der Anlageflaeche der Wanne
STRAP_EAR_X0 = 18.5
LIP_Z_TOP = -40.0      # Hakenlippe greift die unteren 12 mm der Vorderseite
SBOLT_X = 26.0
SBOLT_Y = 6.0
BOSS_X0 = 20.0
BOSS_X1 = 32.0
BOSS_Z_BOT = -52.0     # 2 mm unter der Rohrunterkante -> Platz fuer EPDM
BOSS_Z_TOP = -38.0

# --- Verschraubung Wanne/Schelle ---
# Vier M4. Die Einschmelzgewinde sitzen in der WANNE, die Schrauben kommen
# von vorn durch die Schelle und ihre Koepfe verschwinden in einer Senkung in
# der Schellen-Vorderflaeche. Damit steht weder im Innenraum der Wanne noch
# zwischen Schelle und Strebe irgendetwas vor. Folge fuer die Montage: Wanne
# und Schelle werden zuerst miteinander verschraubt, danach kommt die
# Baugruppe als Ganzes an die Strebe - an die Koepfe kommt man spaeter nicht
# mehr heran, weil davor die Strebe steht.
# Alle vier sitzen in der oberen Haelfte: unten ist der Bereich fuer den
# Netzstecker, da darf nichts im Weg sein.
# Die Rueckplatte laeuft hinter der Deckelkante durch bis nach oben und fasst
# die Wanne an ihrer Oberkante. Frueher waren das zwei einzelne Arme - das sah
# wie ein Anbau aus und war unnoetig schmal. Ein durchgehendes Blatt ist ein
# Teil statt drei, steifer, und in der Y-Aufbaurichtung kostet es keinen
# einzigen Ueberhang mehr als vorher. Damit haengt der Router von oben
# statt in halber Hoehe geklemmt zu sein, und die ganze Rueckseite darunter
# bleibt frei fuer Stecker und Kabel. Moeglich ist das, weil der Deckel
# buendig mit der HINTEREN Strebenflaeche abschliesst - dahinter ist oberhalb
# der Strebe nichts mehr.
# Oberkante buendig mit der Wanne, darunter zwei Beine statt vollem Blatt:
# unten in der Mitte bleibt eine Oeffnung. Getragen wird dort nichts - die
# Wanne stuetzt sich mit ihren Eckstuetzen an den Aussenkanten ab, und die
# Beine fuehren die Bosse fuer den Buegel nach unten.
# Oberkante der Rueckplatte = Oberkante der Zunge. Die Platte hoert also mit
# der Strebe auf, sie ragt nicht mehr darueber hinaus.
ARM_Z1 = TONGUE_T
PLATE_Z0 = -26.0       # bis hierher volle Breite, beide Schraubenreihen liegen darin
LEG_X0 = 20.0
LEG_X1 = 42.0
SCREW_X = 22.0
CBORE_D = 8.0          # Senkung fuer den Zylinderkopf
CBORE_DEPTH = 5.0
# Obere Schraubenreihe so hoch wie moeglich. Die Grenze setzt nicht die
# Senkung in der Wanne, sondern das Einschmelzgewinde in der Schelle: ueber
# dem 5,6er Loch muessen 3,5 mm Material stehen bleiben, sonst reisst es beim
# Einschmelzen zur Plattenoberkante hin auf.
SCREW_TOP_WALL = 3.5
SCREW_Z = (TONGUE_T - INS_M4_D / 2.0 - SCREW_TOP_WALL,
           TONGUE_T - INS_M4_D / 2.0 - SCREW_TOP_WALL - 16.0)

# --- Wanne ---
WA_WALL = 6.0
# Die Rueckwand ist dicker als die uebrigen: sie muss die Senkung fuer die
# Schraubenkoepfe aufnehmen und trotzdem tragen.
BACK_WALL_T = 12.0
# Wuerfel steht: 70 x 70 im Grundriss, 110 hoch. Die WPS-Taste ist die
# komplette obere 70x70-Flaeche - nichts darf sie beruehren.
CUBE_L = 70.0          # laengs der Strebe (X)
CUBE_W = 70.0          # Einbautiefe (Y)
CUBE_H = 110.0         # Hoehe (Z)
CUBE_FIT = 0.0         # spielfrei, ausdruecklich so gewuenscht
# Keine Steckerbucht: Der Wuerfel steht direkt an der Rueckwand. Der Stecker
# braucht dort keinen Platz, weil die Rueckwand nur oben als Band vorhanden
# ist - unterhalb davon, also genau dort wo die Buchsen sitzen, ist die
# Rueckseite ohnehin offen.
BAY = 0.0
CUBE_HX = (CUBE_L + CUBE_FIT) / 2.0
WA_HX = CUBE_HX + WA_WALL
WA_Y0 = BACK_T                     # Anlageflaeche an der Schelle
WA_BACK_Y1 = WA_Y0 + BACK_WALL_T
CUBE_Y0 = WA_BACK_Y1 + BAY
CUBE_Y1 = CUBE_Y0 + CUBE_W + CUBE_FIT
# Vorderwand dicker als die Seiten: sie muss die Gewinde fuers Dach aufnehmen.
FRONT_WALL_T = 12.0
WA_FRONT_Y1 = CUBE_Y1 + FRONT_WALL_T
# Die Hoehenkette laeuft jetzt von OBEN nach unten: die Oberkante der Wanne
# liegt buendig mit der Oberkante der Schelle, damit die Schelle am oberen
# Ende des Routers sitzt und nicht auf halber Hoehe. Alles andere ergibt sich
# daraus nach unten - der Router haengt also unter der Strebe.
WA_TOP_Z = ARM_Z1
CUBE_Z1 = WA_TOP_Z - 5.0           # 5 mm Luft ueber der WPS-Taste
CUBE_Z0 = CUBE_Z1 - CUBE_H - CUBE_FIT
WA_FLOOR_Z0 = CUBE_Z0 - WA_WALL
# Seiten- und Vorderwand duerfen ruhig hoch sein: stehend liegen dort ueberall
# die glatten 70x110-Flaechen an, keine Taste.
WA_SIDE_Z1 = CUBE_Z0 + 40.0

# Pfosten und Bosse, in die das Dach geschraubt wird
# Die Dachpfosten sitzen weiter aussen als die Schrauben zur Schelle, sonst
# wuerde das Einschmelzgewinde fuers Dach in die Senkung darunter einbrechen.
# Keine Pfosten mehr. Sie standen frueher in der Steckerbucht; seit die weg
# ist, ragten sie in den Wuerfelraum und der Wuerfel passte nicht mehr hinein.
# Die vier Dachgewinde sitzen jetzt senkrecht in der Rueckwand und in der
# Vorderwand - beide sind 12 mm dick, das reicht fuer ein M4-Gewinde, und sie
# liegen ausserhalb der Tasche.
DFIX_X = 34.0
DFIX_Y_BACK = WA_Y0 + BACK_WALL_T / 2.0
DFIX_Y_FRONT = CUBE_Y1 + FRONT_WALL_T / 2.0
# Die Rueckseite ist nur im oberen Bereich geschlossen: das Band mit den vier
# Schrauben sitzt oben und laeuft bis unters Dach durch, darunter ist die
# ganze Rueckseite offen. Dort kommen Stecker und Kabel heraus. Getragen wird
# das Band von zwei Eckstuetzen - den Seitenwaenden, die im hinteren Bereich
# ueber die volle Hoehe hochgezogen sind. Weiter vorn bleiben die Seiten
# niedrig, damit Luft durchzieht.
BAND_Z0 = min(SCREW_Z) - CBORE_D / 2.0 - 4.0
# Die Eckstuetzen reichen jetzt bis an die Anlageflaeche heran: sie liegen
# unten an der Rueckplatte der Schelle an und fangen das Kippmoment ab, statt
# es allein den Schrauben zu ueberlassen. Die Mitte bleibt frei.
SILL_H = 5.0           # Schwelle ueber dem Boden am hinteren Ausschnitt
# Zwei Anschlaege an den Seitenwaenden, gegen die die Anschlussseite des
# Wuerfels stoesst. Ohne sie koennte er die 14 mm der Steckerbucht nach
# hinten rutschen und dabei am Stecker ziehen. Sie sitzen aussen, damit in
# der Mitte der Platz fuer den Stecker frei bleibt.
STOP_W = 4.0           # wie weit der Anschlag nach innen ragt
STOP_T = 4.0           # Dicke in Einschubrichtung
# Das Rueckwandband hat unter sich die offene Rueckseite. Ohne Abstuetzung
# muesste der Drucker dort ueber die volle Breite zwischen den Eckstuetzen
# bruecken - 70 mm, das haengt durch. Zwei 45-Grad-Schraegen an den oberen
# Ecken der Oeffnung verkuerzen die freie Spannweite auf 30 mm und sind
# selbst stuetzenfrei.
GUSSET_Y0 = WA_Y0
BRACE_X = 15.0         # bis hierher reicht die Schraege nach innen
BRACE_DROP = 20.0      # und so weit nach unten
GUSSET_Y1 = CUBE_Y0 + 8.0
DACH_Y0 = WA_Y0

# Bodenschlitze: Entwaesserung, Kabelabgang, Luft. Sie laufen bis unter die
# Vorderwand durch, damit im Boden nirgends eine Decke entsteht.
SLOT_XC = (-22.0, 0.0, 22.0)
SLOT_W = 14.0
# Die Schlitze fangen schon unter der Steckerbucht an, damit das 12-V-Kabel
# direkt hinter dem Stecker nach unten und nach innen zum Gehaeuse abgeht.
# Die Schlitze reichen 2 mm HINTER die Wuerfeltasche. Damit zerfaellt die
# Bodenoberflaeche in vier getrennte Rechtecke statt eines zusammenhaengenden
# Kamms mit drei Einschnitten. Fusion hat diesen Kamm falsch trianguliert und
# zwei riesige Dreiecke quer ueber die Schlitze gelegt - eine Membran mit
# Volumen null, sichtbar in Fusion, in der STL und im Slicer, aber unsichtbar
# fuer jede Volumenpruefung.
SLOT_Y0 = WA_BACK_Y1 - 2.0

# --- Dach ---
DACH_T = 5.0
DACH_OVER = 5.0
DACH_Z0 = WA_TOP_Z
DACH_Z1 = DACH_Z0 + DACH_T

ROUND_R = 1.2          # alle Aussenkanten brechen

EXPORT_DIR = r"C:\Users\mausz\Documents\PlatformIO\Projects\quassel-ugv\cad"


def mm(v):
    """Fusion rechnet intern in cm."""
    return v / 10.0


def _plane_at(root, z):
    """Konstruktionsebene parallel zu XY auf Hoehe z."""
    planes = root.constructionPlanes
    pin = planes.createInput()
    pin.setByOffset(root.xYConstructionPlane,
                    adsk.core.ValueInput.createByReal(mm(z)))
    return planes.add(pin)


def _rect_sketch(root, z, x0, x1, y0, y1):
    """Rechteck auf einer Ebene in Hoehe z. Skizzen-X/Y = Modell-X/Y, keine
    Vorzeichenfalle wie bei XZ-Skizzen."""
    sk = root.sketches.add(_plane_at(root, z))
    sk.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(mm(x0), mm(y0), 0),
        adsk.core.Point3D.create(mm(x1), mm(y1), 0))
    return sk


def box(root, x0, x1, y0, y1, z0, z1, name=None):
    """Quader als eigener Body, von z0 nach z1 extrudiert."""
    sk = _rect_sketch(root, z0, x0, x1, y0, y1)
    ext_in = root.features.extrudeFeatures.createInput(
        sk.profiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_in.setDistanceExtent(False,
                             adsk.core.ValueInput.createByReal(mm(z1 - z0)))
    body = root.features.extrudeFeatures.add(ext_in).bodies.item(0)
    if name:
        body.name = name
    return body


def join(root, target, tools_list):
    tools = adsk.core.ObjectCollection.create()
    for b in tools_list:
        tools.add(b)
    ci = root.features.combineFeatures.createInput(target, tools)
    ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    root.features.combineFeatures.add(ci)


def cut_cylinder(root, x, y, z0, z1, dia, only=None):
    """Senkrechte Bohrung als Schnitt-Extrusion.

    only: Body, auf den der Schnitt beschraenkt wird. Ohne das schneidet eine
    Extrusion JEDEN Body, den sie trifft."""
    sk = root.sketches.add(_plane_at(root, z0))
    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(mm(x), mm(y), 0), mm(dia / 2.0))
    ext_in = root.features.extrudeFeatures.createInput(
        sk.profiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation)
    ext_in.setDistanceExtent(False,
                             adsk.core.ValueInput.createByReal(mm(z1 - z0)))
    if only is not None:
        ext_in.participantBodies = [only]
    root.features.extrudeFeatures.add(ext_in)


def cut_box(root, x0, x1, y0, y1, z0, z1, only=None):
    sk = _rect_sketch(root, z0, x0, x1, y0, y1)
    ext_in = root.features.extrudeFeatures.createInput(
        sk.profiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation)
    ext_in.setDistanceExtent(False,
                             adsk.core.ValueInput.createByReal(mm(z1 - z0)))
    if only is not None:
        ext_in.participantBodies = [only]
    root.features.extrudeFeatures.add(ext_in)


def _xz_signs(sk):
    """Auf der XZ-Ebene laeuft die Skizzen-Y-Achse gegen Modell-Z. Die
    Vorzeichen werden zur Laufzeit mit einem Probepunkt ermittelt, statt sie
    anzunehmen - sie haengen von der Fusion-Version ab."""
    p = sk.sketchPoints.add(adsk.core.Point3D.create(mm(10.0), mm(20.0), 0))
    w = p.worldGeometry
    return (1.0 if w.x > 0 else -1.0), (1.0 if w.z > 0 else -1.0)


def cut_along_y(root, shapes, only):
    """Schneidet quer durch das Teil in Y-Richtung. Die Extrusion ist
    symmetrisch um Y=0 und weit ueberdimensioniert - welche Bodies getroffen
    werden, regelt participantBodies, nicht die Laenge."""
    for shape in shapes:
        # Bewusst eine Skizze pro Form: Kreis und Schlitz eines
        # Schluessellochs ueberlappen sich, in einer gemeinsamen Skizze wuerde
        # Fusion daraus mehrere Teilprofile machen und die Zuordnung waere
        # nicht mehr vorhersagbar.
        sk = root.sketches.add(root.xZConstructionPlane)
        sx, sz = _xz_signs(sk)
        if shape[0] == "circle":
            _, x, z, dia = shape
            sk.sketchCurves.sketchCircles.addByCenterRadius(
                adsk.core.Point3D.create(mm(sx * x), mm(sz * z), 0),
                mm(dia / 2.0))
        else:
            _, x0, x1, z0, z1 = shape
            sk.sketchCurves.sketchLines.addTwoPointRectangle(
                adsk.core.Point3D.create(mm(sx * x0), mm(sz * z0), 0),
                adsk.core.Point3D.create(mm(sx * x1), mm(sz * z1), 0))
        ext_in = root.features.extrudeFeatures.createInput(
            sk.profiles.item(0),
            adsk.fusion.FeatureOperations.CutFeatureOperation)
        ext_in.setDistanceExtent(True, adsk.core.ValueInput.createByReal(
            mm(200.0)))
        ext_in.participantBodies = [only]
        root.features.extrudeFeatures.add(ext_in)


def _y_plane(root, y):
    """Konstruktionsebene parallel zur XZ-Ebene bei Modell-Y = y.

    In welche Richtung ein positiver Offset laeuft, haengt von der
    Fusion-Version ab - deshalb wird es einmal mit einem Probepunkt
    gemessen statt angenommen."""
    planes = root.constructionPlanes
    pin = planes.createInput()
    pin.setByOffset(root.xZConstructionPlane,
                    adsk.core.ValueInput.createByReal(mm(10.0)))
    probe_plane = planes.add(pin)
    probe_sk = root.sketches.add(probe_plane)
    pt = probe_sk.sketchPoints.add(adsk.core.Point3D.create(0, 0, 0))
    ys = 1.0 if pt.worldGeometry.y > 0 else -1.0
    probe_sk.deleteMe()
    probe_plane.deleteMe()

    pin2 = planes.createInput()
    pin2.setByOffset(root.xZConstructionPlane,
                     adsk.core.ValueInput.createByReal(mm(y * ys)))
    return planes.add(pin2), ys


def cut_y_range(root, shape, y0, y1, only):
    """Schnitt in Y-Richtung mit definiertem Anfang und Ende - fuer die
    Senkungen, die nur 4,5 mm tief sein duerfen."""
    plane, ys = _y_plane(root, y0)
    sk = root.sketches.add(plane)
    sx, sz = _xz_signs(sk)
    _, x, z, dia = shape
    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(mm(sx * x), mm(sz * z), 0), mm(dia / 2.0))
    ext_in = root.features.extrudeFeatures.createInput(
        sk.profiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation)
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(
        mm((y1 - y0) * ys)))
    ext_in.participantBodies = [only]
    root.features.extrudeFeatures.add(ext_in)


def wedge_y(root, pts_xz, y0, y1):
    """Prisma mit dreieckigem Querschnitt in der XZ-Ebene, in Y extrudiert.
    Wird fuer die 45-Grad-Schraegen unter dem Rueckwandband gebraucht."""
    plane, ys = _y_plane(root, y0)
    sk = root.sketches.add(plane)
    sx, sz = _xz_signs(sk)
    lines = sk.sketchCurves.sketchLines
    p3 = [adsk.core.Point3D.create(mm(sx * x), mm(sz * z), 0)
          for x, z in pts_xz]
    for i in range(len(p3)):
        lines.addByTwoPoints(p3[i], p3[(i + 1) % len(p3)])
    ext_in = root.features.extrudeFeatures.createInput(
        sk.profiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(
        mm((y1 - y0) * ys)))
    return root.features.extrudeFeatures.add(ext_in).bodies.item(0)


def _planar_edges(body, radius, min_len):
    """Kanten zwischen zwei ebenen Flaechen. Bohrungen, Senkungen und
    Schlitzrundungen bleiben damit unangetastet."""
    plane_type = adsk.core.Plane.classType()
    out = []
    for e in body.edges:
        faces = e.faces
        if faces.count != 2:
            continue
        if faces.item(0).geometry.objectType != plane_type:
            continue
        if faces.item(1).geometry.objectType != plane_type:
            continue
        if e.length * 10.0 < max(min_len, radius * 3.0):
            continue
        out.append(e)
    return out


def _fillet(root, edges, radius):
    coll = adsk.core.ObjectCollection.create()
    for e in edges:
        coll.add(e)
    fi = root.features.filletFeatures.createInput()
    fi.isRollingBallCorner = True
    fi.edgeSetInputs.addConstantRadiusEdgeSet(
        coll, adsk.core.ValueInput.createByReal(mm(radius)), True)
    root.features.filletFeatures.add(fi)


def round_edges(root, body, radius):
    """Alle Aussenkanten brechen.

    Zuerst der Versuch, alle Kanten in EINEM Fillet-Feature zu verrunden -
    nur so rechnet Fusion die Ecken sauber aus. Scheitert das (etwa dort, wo
    die Verrundung auf die Zungenfase trifft, Fehler ASM_BL_NO_VTX_GEOM),
    wird der Radius verkleinert und kurze Kanten werden ausgelassen. Erst
    ganz zuletzt geht es kantenweise weiter - das laesst zwar Ecken scharf,
    ist aber besser als gar keine Verrundung.
    """
    for r, min_len in ((radius, 0.0), (radius, 6.0), (radius * 0.6, 6.0)):
        edges = _planar_edges(body, r, min_len)
        if not edges:
            continue
        try:
            _fillet(root, edges, r)
            return len(edges), len(edges), r
        except:
            pass

    # Zweiter Anlauf in Laengenbaendern: erst die grosse Aussenkontur, dann
    # die kurzen Kanten. Bei der Wanne scheitert das Rundum-Feature an den
    # Bodenschlitzen, in zwei Gruppen laeuft es durch.
    all_edges = _planar_edges(body, radius, 0.0)
    bands = [[e for e in all_edges if e.length * 10.0 >= 20.0],
             [e for e in all_edges if e.length * 10.0 < 20.0]]
    done = 0
    for band in bands:
        if not band:
            continue
        try:
            _fillet(root, band, radius)
            done += len(band)
        except:
            pass
    if done:
        return done, len(all_edges), radius

    edges = _planar_edges(body, radius, 0.0)
    total = len(edges)
    edges.sort(key=lambda e: -e.length)
    done = 0
    for e in edges:
        if not e.isValid:
            continue
        try:
            _fillet(root, [e], radius)
            done += 1
        except:
            pass
    return done, total, radius


def chamfer_tongue_ends(root, body):
    """Die beiden Stirnkanten der Zunge brechen. Kanten werden ueber ihre Lage
    gesucht, nicht ueber Indizes - die verschieben sich, sobald am Skript
    etwas geaendert wird."""
    edges = adsk.core.ObjectCollection.create()
    for e in body.edges:
        if e.geometry.objectType != adsk.core.Line3D.classType():
            continue
        bb = e.boundingBox
        x0, x1 = bb.minPoint.x * 10.0, bb.maxPoint.x * 10.0
        y0, y1 = bb.minPoint.y * 10.0, bb.maxPoint.y * 10.0
        z0, z1 = bb.minPoint.z * 10.0, bb.maxPoint.z * 10.0
        if abs(z0 - TONGUE_T) > 0.01 or abs(z1 - TONGUE_T) > 0.01:
            continue
        if abs(x1 - x0) > 0.01 or abs(abs(x0) - CLAMP_W / 2.0) > 0.01:
            continue
        if abs(y0 + RAIL_D) > 0.01 or y1 < -0.01:
            continue
        edges.add(e)
    if edges.count == 0:
        raise RuntimeError("Zungen-Stirnkanten nicht gefunden")
    ch_in = root.features.chamferFeatures.createInput2()
    ch_in.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
        edges, adsk.core.ValueInput.createByReal(mm(TONGUE_CHAMFER)), True)
    root.features.chamferFeatures.add(ch_in)


def build_shell(root):
    """schelle_oben: Zunge + Rueckplatte + Buegelbosse + Aufhaengeklotze."""
    hw = CLAMP_W / 2.0
    parts = []
    shell = box(root, -hw, hw, -RAIL_D, 0.0, 0.0, TONGUE_T, "schelle_oben")
    parts.append(box(root, -hw, hw, 0.0, BACK_T, -RAIL_H, TONGUE_T))
    for sgn in (-1.0, 1.0):
        x0, x1 = sorted((sgn * BOSS_X0, sgn * BOSS_X1))
        parts.append(box(root, x0, x1, 0.0, BACK_T, BOSS_Z_BOT, BOSS_Z_TOP))
    # Abstandsklotze: sie stellen den Spalt zwischen Schraubenkopf und Platte
    # ein, damit man die Schrauben fest anziehen kann und die Wanne trotzdem
    # einhaengbar bleibt. Quadratisch statt rund, damit sie im Schlitz nicht
    # verdrehen und beim Druck kein Rundueberhang entsteht.
    join(root, shell, parts)

    # Buegelgewinde von unten, M3
    for sgn in (-1.0, 1.0):
        cut_cylinder(root, sgn * SBOLT_X, SBOLT_Y,
                     BOSS_Z_BOT, BOSS_Z_BOT + INS_M4_DEPTH, INS_M4_D_FLAT,
                     only=shell)

    # Aufhaengegewinde und Sicherungsgewinde, M4, quer durch die Platte
    holes = []
    for sgn in (-1.0, 1.0):
        for z in SCREW_Z:
            holes.append(("circle", sgn * SCREW_X, z, CLEAR_M4))
    cut_along_y(root, holes, shell)
    for sgn in (-1.0, 1.0):
        for z in SCREW_Z:
            cut_y_range(root, ("circle", sgn * SCREW_X, z, CBORE_D),
                        -1.0, CBORE_DEPTH, shell)

    chamfer_tongue_ends(root, shell)
    shell.name = "schelle_oben"
    return shell


def build_strap(root):
    """schelle_strap: Buegel unter der Strebe mit Hakenlippe vorn."""
    hw = CLAMP_W / 2.0
    z0 = STRAP_Z_TOP - STRAP_T
    z1 = STRAP_Z_TOP
    strap = box(root, -hw, hw, STRAP_Y_FRONT, 0.0, z0, z1, "schelle_strap")
    parts = []
    for sgn in (-1.0, 1.0):
        x0, x1 = sorted((sgn * STRAP_EAR_X0, sgn * hw))
        parts.append(box(root, x0, x1, 0.0, STRAP_Y_BACK, z0, z1))
    parts.append(box(root, -hw, hw, STRAP_Y_FRONT, STRAP_Y_FRONT + 6.0,
                     z0, LIP_Z_TOP))
    join(root, strap, parts)

    for sgn in (-1.0, 1.0):
        cut_cylinder(root, sgn * SBOLT_X, SBOLT_Y, z0 - 1.0, z1 + 1.0,
                     CLEAR_M4, only=strap)

    strap.name = "schelle_strap"
    return strap


def build_wanne(root):
    """wanne: flache Schale. Boden mit Schlitzen, niedrige Seiten- und
    Vorderwand, hohe Rueckwand mit den Schluessell\u00f6chern, vier Pfosten
    fuer das Dach."""
    wanne = box(root, -WA_HX, WA_HX, WA_Y0, WA_FRONT_Y1,
                WA_FLOOR_Z0, CUBE_Z0, "wanne")
    parts = []
    # hohe Rueckwand
    parts.append(box(root, -WA_HX, WA_HX, WA_Y0, WA_BACK_Y1,
                     WA_FLOOR_Z0, WA_TOP_Z))
    # niedrige Vorderwand
    parts.append(box(root, -WA_HX, WA_HX, CUBE_Y1, WA_FRONT_Y1,
                     WA_FLOOR_Z0, WA_SIDE_Z1))
    # niedrige Seitenwaende
    for sgn in (-1.0, 1.0):
        x0, x1 = sorted((sgn * CUBE_HX, sgn * WA_HX))
        parts.append(box(root, x0, x1, WA_BACK_Y1, WA_FRONT_Y1,
                         WA_FLOOR_Z0, WA_SIDE_Z1))
    # Anschlaege nur, wenn es ueberhaupt eine Bucht gibt, in die der Wuerfel
    # zurueckrutschen koennte. Ohne Bucht steht er direkt an der Rueckwand.
    if BAY > 0.1:
        for sgn in (-1.0, 1.0):
            x0, x1 = sorted((sgn * (CUBE_HX - STOP_W), sgn * CUBE_HX))
            parts.append(box(root, x0, x1, CUBE_Y0 - STOP_T, CUBE_Y0,
                             WA_FLOOR_Z0, WA_SIDE_Z1))

    # Bodenschlitze
    for xc in SLOT_XC:
        cut_box(root, xc - SLOT_W / 2.0, xc + SLOT_W / 2.0,
                SLOT_Y0, CUBE_Y1, WA_FLOOR_Z0 - 1.0, CUBE_Z0 + 1.0,
                only=wanne)

    # Schluessell\u00f6cher und Sicherungsloch, quer durch die Rueckwand
    # Sacklochgewinde in der Anlageflaeche, kein Durchbruch. Ein durchgehender
    # Schnitt in Y hat hier vorher auch die Vorderwand durchbohrt - vier
    # Loecher ohne jede Funktion.
    for sgn in (-1.0, 1.0):
        for z in SCREW_Z:
            cut_y_range(root, ("circle", sgn * SCREW_X, z, INS_M4_D_FLAT),
                        WA_Y0 - 0.5, WA_Y0 + INS_M4_DEPTH, wanne)

    # Gewinde fuer das Dach, von oben in die vier Pfosten
    for sgn in (-1.0, 1.0):
        cut_cylinder(root, sgn * DFIX_X, DFIX_Y_BACK,
                     WA_TOP_Z, WA_TOP_Z - INS_M4_DEPTH, INS_M4_D, only=wanne)
        cut_cylinder(root, sgn * DFIX_X, DFIX_Y_FRONT,
                     WA_TOP_Z, WA_TOP_Z - INS_M4_DEPTH, INS_M4_D, only=wanne)

    wanne.name = "wanne"
    return wanne


def build_dach(root):
    """dach: Platte mit Tropfkante ringsum, vier Durchgangsloecher."""
    hx = WA_HX + DACH_OVER
    dach = box(root, -hx, hx, DACH_Y0, WA_FRONT_Y1 + DACH_OVER,
               DACH_Z0, DACH_Z1, "dach")
    for sgn in (-1.0, 1.0):
        cut_cylinder(root, sgn * DFIX_X, DFIX_Y_BACK,
                     DACH_Z0 - 1.0, DACH_Z1 + 1.0, CLEAR_M4, only=dach)
        cut_cylinder(root, sgn * DFIX_X, DFIX_Y_FRONT,
                     DACH_Z0 - 1.0, DACH_Z1 + 1.0, CLEAR_M4, only=dach)
    dach.name = "dach"
    return dach


def export_all(design, root):
    em = design.exportManager
    if not os.path.isdir(EXPORT_DIR):
        return
    for body in root.bRepBodies:
        path = os.path.join(EXPORT_DIR, "asa_router_e5180_%s.stl" % body.name)
        opt = em.createSTLExportOptions(body, path)
        # Nicht MeshRefinementHigh: die Voreinstellung laesst beliebig lange
        # Dreiecke zu und erzeugt an den Verrundungen Nadeln - bis 92 mm lang
        # bei 0,0003 mm Hoehe. Im Slicer sieht das aus wie ein zerrissener
        # Boden. Mit begrenzter Kantenlaenge und Seitenverhaeltnis ist das weg.
        opt.meshRefinement =             adsk.fusion.MeshRefinementSettings.MeshRefinementCustom
        opt.surfaceDeviation = mm(0.02)
        opt.normalDeviation = math.radians(10.0)
        opt.maxEdgeLength = mm(4.0)
        opt.aspectRatio = 8.0
        em.execute(opt)
    step = os.path.join(EXPORT_DIR, "router_e5180_halter.step")
    em.execute(em.createSTEPExportOptions(step, root))


def run(_context):
    # Kein try/except: eine geschluckte Exception verschleiert nur, an welcher
    # Stelle das Skript ausgestiegen ist.
    app = adsk.core.Application.get()
    app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    root = design.rootComponent

    bodies = [build_shell(root), build_strap(root),
              build_wanne(root), build_dach(root)]
    for b in bodies:
        done, total, r = round_edges(root, b, ROUND_R)
        print("%s: %d von %d Kanten verrundet, r=%.1f" % (
            b.name, done, total, r))
    export_all(design, root)

    app.activeViewport.fit()
    for body in root.bRepBodies:
        bb = body.boundingBox
        print("%s: %.1f x %.1f x %.1f mm" % (
            body.name,
            (bb.maxPoint.x - bb.minPoint.x) * 10.0,
            (bb.maxPoint.y - bb.minPoint.y) * 10.0,
            (bb.maxPoint.z - bb.minPoint.z) * 10.0))
