# Fusion360-Skript: Shunt-Halter fuer den Junce/Junctek 100-A-Sampler
# Erstes Anbauteil an der Snap-Schnittstelle der Batteriehalterung.
# Wird ueber den Fusion-MCP-Server ausgefuehrt (featureType=script).
#
# Ein Stueck: Snap-Adapter (identisch zu fusion_snap_interface.py) + Traegerplatte.
# Shunt steht senkrecht, 75 mm waagerecht, symmetrisch +/-37,5 mm um die Stegmitte.
#
# Shunt-Daten aus dem Datenblatt: Platine 75 x 30 mm, Aufbauhoehe 24,5 mm,
# 2x Ø4,4 im Abstand 64 mm. ANNAHME: Loecher symmetrisch auf der Laengsmittellinie
# (5,5 mm von den Enden) - so zeigt es die Masszeichnung.
#
# Stand nach dem ersten Druck: die Pads stiessen an den grossen Kabelklemm-
# Muttern auf der Platinenrueckseite an. Die 8 mm Abstand stimmten, nur die
# Innenkante der Pads (zur Platinenmitte hin) musste versetzt werden.
# Historie von PAD_X_IN: 24.0 (1. Druck, stiess an) -> 26.0 -> 23.7 (falsche
# Richtung) -> 28.2. Gemessen wird der Abstand Pad-Innenkante bis Rand des
# Ø5,6-Sitzes: bei 26.0 waren das 3,2 mm, bei 23.7 dann 5,5 mm, Ziel ist 1 mm.
# Beim ersten Druck standen 5,2 mm Pad ueber den Sitz hinaus nach innen - genau
# dort sitzt die Mutter, das war die Kollision.
#
# Der Shunt sitzt auf zwei 8 mm hohen Pads, nicht flach auf der Platte:
#  - Luft zum Kuehlen (0,75 mOhm -> 7,5 W bei 100 A, ASA erweicht ab ~95 C)
#  - Freigang fuer Ueberstaende auf der Platinenrueckseite
#  - Zugangskanal von oben zur Zuglasche des Schnappers
# Zwei Pads + zwei M4 sind vollstaendig bestimmt: die Pads nehmen das Kippmoment
# um die Schraubenachse, die zwei Schrauben die Drehung in der Plattenebene.
#
# DRUCKREGEL wie bei der Schnittstelle: Schiebeachse = Modell-Z senkrecht aufs
# Bett. Alle Ueberhaenge 45 Grad, keine Stuetzen. ASA.
#
# Masse in mm (Fusion-API rechnet intern in cm -> mm()-Helper).

import adsk.core
import adsk.fusion

# --- Snap-Adapter (identisch zu fusion_snap_interface.py) ---
RAIL_W_ROOT = 11.0
RAIL_W_TIP = 16.0
RAIL_H = 4.0
RAIL_Z0 = 8.0

CL = 0.25
AD_W = 26.0
AD_Y0 = 0.25
AD_WALL_Y = 7.5
AD_Z1 = 30.0

TONGUE_W = 8.0
TONGUE_T = 1.6
TAPER_Z0 = 9.0
TAPER_Z1 = 14.0
SLIT_W = 1.5
SLIT_Z0 = 10.0
NOSE_W = 6.0
NOSE_TIP_Y = 3.1
NOSE_Z0 = 22.45
NOSE_Z1 = 26.55
TAB_Y = 10.5
TAB_Z0 = 29.0
TAB_Z1 = 34.5

# --- Shunt (Datenblatt) ---
SHUNT_L = 75.0
SHUNT_W = 30.0
SHUNT_HOLE_SPACING = 64.0
BOARD_Z0 = 12.0        # Unterkante Platine

# --- Traegerplatte ---
PLATE_X = 41.0         # +/-41 -> 2,5 mm Rand neben der 75-mm-Platine
PLATE_Y0 = 7.5         # bindet direkt an die Adapter-Rueckwand an
PLATE_Y1 = 12.0
PLATE_Z0 = 8.0
PLATE_Z1 = BOARD_Z0 + SHUNT_W          # 42, buendig mit der Platinenoberkante
NOTCH_X = 9.0          # Freigang Zuglasche, oben offen
NOTCH_Z0 = 28.0

# --- Abstandspads ---
# Grosse Auflageflaeche wie beim ersten Druck, nur die INNENKANTE (zur Mitte
# der Platine hin) 2 mm weiter nach aussen: dort sassen die grossen Kabel-
# klemm-Muttern auf der Platinenrueckseite und haben angestossen. Aussenkante,
# Hoehe und 45-Grad-Anlauf bleiben unveraendert - die 8 mm Abstand zur Platte
# haben fuer die Mutternhoehe gereicht.
# PAD_X_IN ist die Zahl zum Nachstellen, falls es weiter anstoesst.
# Maszgeblich ist der Abstand von der Pad-INNENKANTE zum Rand des Ø5,6-Sitzes.
# Der Sitzrand liegt bei X = HOLE_XC - INSERT_M4_D/2 = 29.2; davon 1 mm Pad
# nach innen stehen lassen -> 28.2. Weiter innen sitzt die Kabelklemm-Mutter.
PAD_X_IN = 28.2
PAD_X_OUT = 40.0
PAD_Y1 = 20.0          # 8 mm Abstand zur Platte = Auflageebene der Platine
PAD_Z1 = 38.0
PAD_RAMP = 8.0         # 45-Grad-Anlauf unten statt Ueberhang
HOLE_XC = SHUNT_HOLE_SPACING / 2.0     # 32, Lochmitte
HOLE_Z = BOARD_Z0 + SHUNT_W / 2.0      # 27, Laengsmittellinie der Platine

INSERT_M4_D = 5.6      # M4-Einschmelzgewinde: Ø5,6 x 9 als Sitz ...
INSERT_M4_DEPTH = 9.0
M4_CLEAR_D = 4.5       # ... dahinter Ø4,5 durch bis zur Plattenrueckseite.
                       # Durchgehend, damit eine zu lange Schraube nicht aufsetzt
                       # und wahlweise eine Durchgangsschraube mit Mutter geht.

EXPORT_DIR = r"C:\Users\mausz\Documents\PlatformIO\Projects\UGV ESP32CAN\cad"


def mm(v):
    return v / 10.0


def offset_plane(root, base, dist, comp):
    planes = root.constructionPlanes
    inp = planes.createInput()
    inp.setByOffset(base, adsk.core.ValueInput.createByReal(mm(dist)))
    pl = planes.add(inp)
    sk = root.sketches.add(pl)
    pt = sk.sketchPoints.add(adsk.core.Point3D.create(0, 0, 0))
    got = getattr(pt.worldGeometry, comp)
    sk.deleteMe()
    if abs(got - mm(dist)) > 1e-6:
        pl.deleteMe()
        inp = planes.createInput()
        inp.setByOffset(base, adsk.core.ValueInput.createByReal(-mm(dist)))
        pl = planes.add(inp)
    return pl


def poly(sk, pts):
    lines = sk.sketchCurves.sketchLines
    sp = [sk.modelToSketchSpace(adsk.core.Point3D.create(mm(p[0]), mm(p[1]), mm(p[2])))
          for p in pts]
    for i in range(len(sp)):
        lines.addByTwoPoints(sp[i], sp[(i + 1) % len(sp)])


def all_profiles(sk):
    col = adsk.core.ObjectCollection.create()
    for i in range(sk.profiles.count):
        col.add(sk.profiles.item(i))
    return col


def extrude(root, profs, dist, op, participants=None, symmetric=False):
    """dist bei symmetric=True ist die GESAMTlaenge (isFullLength)."""
    exts = root.features.extrudeFeatures
    inp = exts.createInput(profs, op)
    if symmetric:
        inp.setSymmetricExtent(adsk.core.ValueInput.createByReal(mm(dist)), True)
    else:
        inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(dist)))
    if participants:
        inp.participantBodies = participants
    return exts.add(inp)


def build(comp, body_name="shunt_halter"):
    """Baut den Halter in lokalen Koordinaten. Rueckgabe: der Koerper.

    Wird auch von cad/fusion_montage_halterung_shunt.py benutzt - dort in
    den Fahrzeug-Koordinaten des Hauptdokuments. Einzige Quelle der
    Geometrie, damit Einzelteil und Baugruppe nicht auseinanderlaufen."""
    xy = comp.xYConstructionPlane
    yz = comp.yZConstructionPlane
    xz = comp.xZConstructionPlane
    new_body = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    join = adsk.fusion.FeatureOperations.JoinFeatureOperation
    cut = adsk.fusion.FeatureOperations.CutFeatureOperation

    ahw = AD_W / 2.0
    rr, rt = RAIL_W_ROOT / 2.0, RAIL_W_TIP / 2.0
    fr, ft, fu = rr + CL, rt + CL, RAIL_H + CL
    slope = (ft - fr) / fu

    pl_z8 = offset_plane(comp, xy, RAIL_Z0, "z")

    # --- Adapterblock ---
    sk = comp.sketches.add(pl_z8)
    sk.name = "adapter_block"
    poly(sk, [(-ahw, AD_Y0, RAIL_Z0), (ahw, AD_Y0, RAIL_Z0),
              (ahw, AD_WALL_Y, RAIL_Z0), (-ahw, AD_WALL_Y, RAIL_Z0)])
    part = extrude(comp, sk.profiles.item(0), AD_Z1 - RAIL_Z0, new_body).bodies.item(0)
    part.name = body_name
    parts = [part]

    # --- Schwalbenschwanznut ---
    sk = comp.sketches.add(pl_z8)
    sk.name = "adapter_nut"
    poly(sk, [(-(fr - slope), -1.0, RAIL_Z0), (fr - slope, -1.0, RAIL_Z0),
              (ft, fu, RAIL_Z0), (-ft, fu, RAIL_Z0)])
    extrude(comp, sk.profiles.item(0), AD_Z1 - RAIL_Z0, cut, parts)

    # --- Freischnitt der Federzunge ---
    thw, sr = TONGUE_W / 2.0, SLIT_W / 2.0
    y_mid = (AD_WALL_Y + RAIL_H) / 2.0
    pl_y = offset_plane(comp, xz, y_mid, "y")
    sk = comp.sketches.add(pl_y)
    sk.name = "adapter_freischnitt"
    for sx in (-1.0, 1.0):
        x0, x1 = sx * thw, sx * (thw + SLIT_W)
        poly(sk, [(min(x0, x1), y_mid, SLIT_Z0), (max(x0, x1), y_mid, SLIT_Z0),
                  (max(x0, x1), y_mid, AD_Z1 + 0.5), (min(x0, x1), y_mid, AD_Z1 + 0.5)])
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            sk.modelToSketchSpace(adsk.core.Point3D.create(
                mm(sx * (thw + sr)), mm(y_mid), mm(SLIT_Z0))), mm(sr))
    extrude(comp, all_profiles(sk), (AD_WALL_Y - RAIL_H) + 1.0, cut, parts, symmetric=True)

    # --- Zunge ausduennen (vor der Platte, sonst kerbt der Schnitt die Platte an) ---
    ty = fu + TONGUE_T
    sk = comp.sketches.add(yz)
    sk.name = "adapter_zunge_duenn"
    poly(sk, [(0, AD_WALL_Y + 0.5, TAPER_Z0), (0, ty, TAPER_Z1),
              (0, ty, AD_Z1 + 1.0), (0, AD_WALL_Y + 0.5, AD_Z1 + 1.0)])
    extrude(comp, sk.profiles.item(0), TONGUE_W, cut, parts, symmetric=True)

    # --- Rastnase ---
    nose_base = fu + 0.5
    ramp = nose_base - NOSE_TIP_Y
    sk = comp.sketches.add(yz)
    sk.name = "adapter_rastnase"
    poly(sk, [(0, nose_base, NOSE_Z0 - 0.5), (0, NOSE_TIP_Y, NOSE_Z0 - 0.5 + ramp),
              (0, NOSE_TIP_Y, NOSE_Z1 + 0.5 - ramp), (0, nose_base, NOSE_Z1 + 0.5)])
    extrude(comp, sk.profiles.item(0), NOSE_W, join, parts, symmetric=True)

    # --- Traegerplatte ---
    pl_p = offset_plane(comp, xy, PLATE_Z0, "z")
    sk = comp.sketches.add(pl_p)
    sk.name = "traegerplatte"
    poly(sk, [(-PLATE_X, PLATE_Y0, PLATE_Z0), (PLATE_X, PLATE_Y0, PLATE_Z0),
              (PLATE_X, PLATE_Y1, PLATE_Z0), (-PLATE_X, PLATE_Y1, PLATE_Z0)])
    extrude(comp, sk.profiles.item(0), PLATE_Z1 - PLATE_Z0, join, parts)

    # --- Freigang Zuglasche (oben offen, damit man von oben rankommt) ---
    sk = comp.sketches.add(yz)
    sk.name = "zuglaschen_freigang"
    poly(sk, [(0, PLATE_Y0 - 0.05, NOTCH_Z0), (0, PLATE_Y1 + 0.5, NOTCH_Z0),
              (0, PLATE_Y1 + 0.5, PLATE_Z1 + 1.0), (0, PLATE_Y0 - 0.05, PLATE_Z1 + 1.0)])
    extrude(comp, sk.profiles.item(0), 2 * NOTCH_X, cut, parts, symmetric=True)

    # --- Zuglasche (nach dem Freigang, sonst wird sie weggeschnitten) ---
    sk = comp.sketches.add(yz)
    sk.name = "adapter_zuglasche"
    poly(sk, [(0, fu, TAB_Z0), (0, AD_WALL_Y, TAB_Z0),
              (0, TAB_Y, TAB_Z0 + (TAB_Y - AD_WALL_Y)),
              (0, TAB_Y, TAB_Z1), (0, fu, TAB_Z1)])
    extrude(comp, sk.profiles.item(0), TONGUE_W, join, parts, symmetric=True)

    # --- Abstandspads mit 45-Grad-Anlauf ---
    pad_c = (PAD_X_IN + PAD_X_OUT) / 2.0
    pad_w = PAD_X_OUT - PAD_X_IN
    for sx in (-pad_c, pad_c):
        pl_pad = offset_plane(comp, yz, sx, "x")
        sk = comp.sketches.add(pl_pad)
        sk.name = "pad_%+d" % int(sx)
        poly(sk, [(sx, PLATE_Y1, PLATE_Z0), (sx, PAD_Y1, PLATE_Z0 + PAD_RAMP),
                  (sx, PAD_Y1, PAD_Z1), (sx, PLATE_Y1, PAD_Z1)])
        extrude(comp, sk.profiles.item(0), pad_w, join, parts, symmetric=True)

    # --- 2x M4-Einschmelzgewinde ---
    y_i = PAD_Y1 - INSERT_M4_DEPTH / 2.0
    pl_i = offset_plane(comp, xz, y_i, "y")
    sk = comp.sketches.add(pl_i)
    sk.name = "m4_inserts"
    for sx in (-HOLE_XC, HOLE_XC):
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            sk.modelToSketchSpace(adsk.core.Point3D.create(mm(sx), mm(y_i), mm(HOLE_Z))),
            mm(INSERT_M4_D) / 2.0)
    extrude(comp, all_profiles(sk), INSERT_M4_DEPTH, cut, parts, symmetric=True)

    # --- Durchgangsbohrung bis hinten durch ---
    y_lo, y_hi = PLATE_Y0 - 0.5, PAD_Y1 + 0.5
    y_c = (y_lo + y_hi) / 2.0
    pl_c = offset_plane(comp, xz, y_c, "y")
    sk = comp.sketches.add(pl_c)
    sk.name = "m4_durchgang"
    for sx in (-HOLE_XC, HOLE_XC):
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            sk.modelToSketchSpace(adsk.core.Point3D.create(mm(sx), mm(y_c), mm(HOLE_Z))),
            mm(M4_CLEAR_D) / 2.0)
    extrude(comp, all_profiles(sk), y_hi - y_lo, cut, parts, symmetric=True)

    # --- Kontrolle ---
    return part


def run(_context):
    app = adsk.core.Application.get()
    app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent

    part = build(root)

    bb = part.boundingBox
    print("%-16s vol=%7.2f cm3  x %6.2f..%6.2f  y %6.2f..%6.2f  z %6.2f..%6.2f" % (
        part.name, part.volume,
        bb.minPoint.x * 10, bb.maxPoint.x * 10,
        bb.minPoint.y * 10, bb.maxPoint.y * 10,
        bb.minPoint.z * 10, bb.maxPoint.z * 10))

    def solid(x, y, z):
        p = adsk.core.Point3D.create(x / 10.0, y / 10.0, z / 10.0)
        return part.pointContainment(p) == adsk.fusion.PointContainment.PointInsidePointContainment

    checks = [
        ('Nut leer          (0, 2.0, 20)', 0.0, 2.0, 20.0, False),
        ('Zunge 1,6 mm      (0, 5.0, 20)', 0.0, 5.0, 20.0, True),
        ('hinter der Zunge  (0, 6.8, 20)', 0.0, 6.8, 20.0, False),
        ('Platte hinter Zunge (0, 9.0, 20)', 0.0, 9.0, 20.0, True),
        ('Schlitz offen     (4.75, 5.0, 20)', 4.75, 5.0, 20.0, False),
        ('Rastnase          (0, 3.3, 24.5)', 0.0, 3.3, 24.5, True),
        ('Zuglasche         (0, 9.5, 32)', 0.0, 9.5, 32.0, True),
        ('Freigang neben Lasche (7, 9.5, 32)', 7.0, 9.5, 32.0, False),
        ('Pad massiv        (32, 16.0, 20)', 32.0, 16.0, 20.0, True),
        ('Pad Innenkante    (28.7, 16.0, 27)', 28.7, 16.0, 27.0, True),
        ('vor Innenkante frei (27.7, 16.0, 27)', 27.7, 16.0, 27.0, False),
        ('1 mm Steg zum Sitz (29.0, 16.0, 27)', 29.0, 16.0, 27.0, True),
        ('Sitzrand bei 29,2  (29.4, 16.0, 27)', 29.4, 16.0, 27.0, False),
        ('Pad Aussenkante   (39.5, 16.0, 27)', 39.5, 16.0, 27.0, True),
        ('hinter Aussenkante (40.5, 16.0, 27)', 40.5, 16.0, 27.0, False),
        ('Pad-Anlauf frei   (32, 18.0, 10)', 32.0, 18.0, 10.0, False),
        ('Insertsitz weit   (32, 15.0, 29.5)', 32.0, 15.0, 29.5, False),
        ('Platte am Rand    (40, 10.0, 30)', 40.0, 10.0, 30.0, True),
        ('Luft unter Platine (0, 16.0, 27)', 0.0, 16.0, 27.0, False),
        ('Durchgang offen   (32,  9.0, 27)', 32.0, 9.0, 27.0, False),
        ('Durchgang eng     (32,  9.0, 29.5)', 32.0, 9.0, 29.5, True),
        ('Platte neben Loch (32, 9.0, 20)', 32.0, 9.0, 20.0, True),
    ]
    bad = 0
    for name, x, y, z, expect in checks:
        got = solid(x, y, z)
        ok = (got == expect)
        bad += 0 if ok else 1
        print('%-38s soll=%-5s ist=%-5s %s' % (name, expect, got, 'OK' if ok else '<<< ABWEICHUNG'))
    print('Abweichungen:', bad)

    export_mgr = design.exportManager
    stl_path = EXPORT_DIR + r"\asa_shunt_halter.stl"
    opts = export_mgr.createSTLExportOptions(part, stl_path)
    opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
    export_mgr.execute(opts)
    print("exported: " + stl_path)
    step_path = EXPORT_DIR + r"\shunt_halter.step"
    export_mgr.execute(export_mgr.createSTEPExportOptions(step_path, root))
    print("exported: " + step_path)
