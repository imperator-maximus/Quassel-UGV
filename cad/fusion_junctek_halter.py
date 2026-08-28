# Fusion360-Skript: Halter fuer das Junctek Mess-/Anzeigemodul
# Zweites Anbauteil an der Snap-Schnittstelle der Batteriehalterung.
# Wird ueber den Fusion-MCP-Server ausgefuehrt (featureType=script).
#
# Ein Stueck: Snap-Adapter (identisch zu fusion_snap_interface.py) + Traeger.
# Modul steht senkrecht, 107,35 mm waagerecht, symmetrisch um die Stegmitte.
#
# Moduldaten aus dem Datenblatt: 107,35 x 60,36 x 26,75 mm, 2x Ø4 im Abstand
# 100 mm. ANNAHME: Loecher symmetrisch auf der Laengsmittellinie, also je
# 3,7 mm von den Schmalseiten und mittig in der 60,36-mm-Richtung.
#
# Unterschied zum Shunt-Halter: die Modulrueckseite ist voellig flach, es gibt
# keine ueberstehenden Muttern. Die Auflage darf deshalb bis dicht an die
# Schrauben heran, keine zurueckgesetzte Innenkante noetig.
#
# Der Abstand von 12 mm bleibt trotzdem, aber aus einem anderen Grund: das
# Modul deckt mit 107 x 60 mm die Zuglasche des Schnappers komplett zu. Der
# Spalt zwischen Traegerplatte und Modulrueckseite ist nach unten offen und ist
# der Zugang zur Lasche - sie sitzt 21 mm ueber der Plattenunterkante.
#
# DRUCKREGEL: Schiebeachse = Modell-Z senkrecht aufs Druckbett. Alle Ueber-
# haenge 45 Grad, auch die Fensterdaecher - keine Stuetzen. ASA.
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

# --- Junctek-Modul (Datenblatt) ---
JT_L = 107.35
JT_W = 60.36           # in Z, wenn das Modul senkrecht steht
JT_H = 26.75           # ragt nach aussen
JT_HOLE_SPACING = 100.0
MODULE_Z0 = 8.0        # Unterkante Modul, buendig mit der Halterunterkante

HOLE_XC = JT_HOLE_SPACING / 2.0        # 50
HOLE_Z = MODULE_Z0 + JT_W / 2.0        # 38,18

# --- Traegerplatte ---
PLATE_X = 55.0
PLATE_Y0 = 7.5
PLATE_Y1 = 12.0
PLATE_Z0 = 8.0
PLATE_Z1 = 50.0        # reicht bis 11,8 mm ueber die Lochmitte, darueber
                       # kragt das Modul frei aus - es haengt an den Schrauben

# Zuglaschen-Freigang: Fenster mit 45-Grad-Dach statt Bruecke
NOTCH_X = 8.0
NOTCH_Z0 = 27.0
NOTCH_Z1 = 35.0        # ab hier das Dach bis NOTCH_Z1 + NOTCH_X

# Erleichterungsfenster zwischen Adapter und Pad, ebenfalls mit 45-Grad-Dach.
# Laesst oben und unten je 6 mm Gurt stehen - wirkt als I-Traeger.
WIN_X0 = 17.0
WIN_X1 = 37.0
WIN_Z0 = 14.0
WIN_Z1 = 34.0          # ab hier das Dach bis WIN_Z1 + (WIN_X1-WIN_X0)/2

# --- Abstandspads ---
PAD_X_IN = 40.0
PAD_X_OUT = PLATE_X
PAD_Y1 = 24.0          # 12 mm Abstand zur Platte = Auflageebene des Moduls
PAD_Z1 = PLATE_Z1
PAD_RAMP = 12.0        # 45-Grad-Anlauf unten statt Ueberhang

INSERT_M4_D = 5.6      # M4-Einschmelzgewinde: Ø5,6 x 9 als Sitz ...
INSERT_M4_DEPTH = 9.0
M4_CLEAR_D = 4.5       # ... dahinter Ø4,5 durch bis zur Plattenrueckseite

EXPORT_DIR = r"C:\Users\mausz\Documents\PlatformIO\Projects\quassel-ugv\cad"


def mm(v):
    return v / 10.0


def offset_plane(comp, base, dist, axis):
    planes = comp.constructionPlanes
    inp = planes.createInput()
    inp.setByOffset(base, adsk.core.ValueInput.createByReal(mm(dist)))
    pl = planes.add(inp)
    sk = comp.sketches.add(pl)
    p = sk.sketchToModelSpace(adsk.core.Point3D.create(0, 0, 0))
    got = getattr(p, axis)
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


def extrude(comp, profs, dist, op, participants=None, symmetric=False):
    """dist bei symmetric=True ist die GESAMTlaenge (isFullLength)."""
    exts = comp.features.extrudeFeatures
    inp = exts.createInput(profs, op)
    if symmetric:
        inp.setSymmetricExtent(adsk.core.ValueInput.createByReal(mm(dist)), True)
    else:
        inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(dist)))
    if participants:
        inp.participantBodies = participants
    return exts.add(inp)


def build(comp, body_name="junctek_halter"):
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
    sk.name = "jt_adapter_block"
    poly(sk, [(-ahw, AD_Y0, RAIL_Z0), (ahw, AD_Y0, RAIL_Z0),
              (ahw, AD_WALL_Y, RAIL_Z0), (-ahw, AD_WALL_Y, RAIL_Z0)])
    part = extrude(comp, sk.profiles.item(0), AD_Z1 - RAIL_Z0, new_body).bodies.item(0)
    part.name = body_name
    parts = [part]

    # --- Schwalbenschwanznut ---
    sk = comp.sketches.add(pl_z8)
    sk.name = "jt_adapter_nut"
    poly(sk, [(-(fr - slope), -1.0, RAIL_Z0), (fr - slope, -1.0, RAIL_Z0),
              (ft, fu, RAIL_Z0), (-ft, fu, RAIL_Z0)])
    extrude(comp, sk.profiles.item(0), AD_Z1 - RAIL_Z0, cut, parts)

    # --- Freischnitt der Federzunge ---
    thw, sr = TONGUE_W / 2.0, SLIT_W / 2.0
    y_mid = (AD_WALL_Y + RAIL_H) / 2.0
    pl_y = offset_plane(comp, xz, y_mid, "y")
    sk = comp.sketches.add(pl_y)
    sk.name = "jt_adapter_freischnitt"
    for sx in (-1.0, 1.0):
        x0, x1 = sx * thw, sx * (thw + SLIT_W)
        poly(sk, [(min(x0, x1), y_mid, SLIT_Z0), (max(x0, x1), y_mid, SLIT_Z0),
                  (max(x0, x1), y_mid, AD_Z1 + 0.5), (min(x0, x1), y_mid, AD_Z1 + 0.5)])
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            sk.modelToSketchSpace(adsk.core.Point3D.create(
                mm(sx * (thw + sr)), mm(y_mid), mm(SLIT_Z0))), mm(sr))
    extrude(comp, all_profiles(sk), (AD_WALL_Y - RAIL_H) + 1.0, cut, parts, symmetric=True)

    # --- Zunge ausduennen ---
    ty = fu + TONGUE_T
    sk = comp.sketches.add(yz)
    sk.name = "jt_adapter_zunge_duenn"
    poly(sk, [(0, AD_WALL_Y + 0.5, TAPER_Z0), (0, ty, TAPER_Z1),
              (0, ty, AD_Z1 + 1.0), (0, AD_WALL_Y + 0.5, AD_Z1 + 1.0)])
    extrude(comp, sk.profiles.item(0), TONGUE_W, cut, parts, symmetric=True)

    # --- Rastnase ---
    nose_base = fu + 0.5
    ramp = nose_base - NOSE_TIP_Y
    sk = comp.sketches.add(yz)
    sk.name = "jt_adapter_rastnase"
    poly(sk, [(0, nose_base, NOSE_Z0 - 0.5), (0, NOSE_TIP_Y, NOSE_Z0 - 0.5 + ramp),
              (0, NOSE_TIP_Y, NOSE_Z1 + 0.5 - ramp), (0, nose_base, NOSE_Z1 + 0.5)])
    extrude(comp, sk.profiles.item(0), NOSE_W, join, parts, symmetric=True)

    # --- Traegerplatte ---
    pl_p = offset_plane(comp, xy, PLATE_Z0, "z")
    sk = comp.sketches.add(pl_p)
    sk.name = "jt_traegerplatte"
    poly(sk, [(-PLATE_X, PLATE_Y0, PLATE_Z0), (PLATE_X, PLATE_Y0, PLATE_Z0),
              (PLATE_X, PLATE_Y1, PLATE_Z0), (-PLATE_X, PLATE_Y1, PLATE_Z0)])
    extrude(comp, sk.profiles.item(0), PLATE_Z1 - PLATE_Z0, join, parts)

    # --- Zuglaschen-Freigang, Dach 45 Grad ---
    pl_win = offset_plane(comp, xz, (PLATE_Y0 + PLATE_Y1) / 2.0, "y")
    y_w = (PLATE_Y0 + PLATE_Y1) / 2.0
    sk = comp.sketches.add(pl_win)
    sk.name = "jt_zuglaschen_freigang"
    poly(sk, [(-NOTCH_X, y_w, NOTCH_Z0), (NOTCH_X, y_w, NOTCH_Z0),
              (NOTCH_X, y_w, NOTCH_Z1), (0.0, y_w, NOTCH_Z1 + NOTCH_X),
              (-NOTCH_X, y_w, NOTCH_Z1)])
    extrude(comp, sk.profiles.item(0), (PLATE_Y1 - PLATE_Y0) + 1.0, cut,
            parts, symmetric=True)

    # --- Zuglasche (nach dem Freigang, sonst wird sie weggeschnitten) ---
    sk = comp.sketches.add(yz)
    sk.name = "jt_adapter_zuglasche"
    poly(sk, [(0, fu, TAB_Z0), (0, AD_WALL_Y, TAB_Z0),
              (0, TAB_Y, TAB_Z0 + (TAB_Y - AD_WALL_Y)),
              (0, TAB_Y, TAB_Z1), (0, fu, TAB_Z1)])
    extrude(comp, sk.profiles.item(0), TONGUE_W, join, parts, symmetric=True)

    # --- Erleichterungsfenster, Dach 45 Grad ---
    win_peak = WIN_Z1 + (WIN_X1 - WIN_X0) / 2.0
    win_mid = (WIN_X0 + WIN_X1) / 2.0
    sk = comp.sketches.add(pl_win)
    sk.name = "jt_fenster"
    for s in (-1.0, 1.0):
        a, b = s * WIN_X0, s * WIN_X1
        poly(sk, [(min(a, b), y_w, WIN_Z0), (max(a, b), y_w, WIN_Z0),
                  (max(a, b), y_w, WIN_Z1), (s * win_mid, y_w, win_peak),
                  (min(a, b), y_w, WIN_Z1)])
    extrude(comp, all_profiles(sk), (PLATE_Y1 - PLATE_Y0) + 1.0, cut,
            parts, symmetric=True)

    # --- Abstandspads mit 45-Grad-Anlauf ---
    pad_c = (PAD_X_IN + PAD_X_OUT) / 2.0
    pad_w = PAD_X_OUT - PAD_X_IN
    for sx in (-pad_c, pad_c):
        pl_pad = offset_plane(comp, yz, sx, "x")
        sk = comp.sketches.add(pl_pad)
        sk.name = "jt_pad_%+d" % int(sx)
        poly(sk, [(sx, PLATE_Y1, PLATE_Z0), (sx, PAD_Y1, PLATE_Z0 + PAD_RAMP),
                  (sx, PAD_Y1, PAD_Z1), (sx, PLATE_Y1, PAD_Z1)])
        extrude(comp, sk.profiles.item(0), pad_w, join, parts, symmetric=True)

    # --- 2x M4-Einschmelzgewinde ---
    y_i = PAD_Y1 - INSERT_M4_DEPTH / 2.0
    pl_i = offset_plane(comp, xz, y_i, "y")
    sk = comp.sketches.add(pl_i)
    sk.name = "jt_m4_inserts"
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
    sk.name = "jt_m4_durchgang"
    for sx in (-HOLE_XC, HOLE_XC):
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            sk.modelToSketchSpace(adsk.core.Point3D.create(mm(sx), mm(y_c), mm(HOLE_Z))),
            mm(M4_CLEAR_D) / 2.0)
    extrude(comp, all_profiles(sk), y_hi - y_lo, cut, parts, symmetric=True)

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
    print("Lochmitten: x +/-%.1f, z %.2f" % (HOLE_XC, HOLE_Z))

    def solid(x, y, z):
        p = adsk.core.Point3D.create(x / 10.0, y / 10.0, z / 10.0)
        return part.pointContainment(p) == adsk.fusion.PointContainment.PointInsidePointContainment

    checks = [
        ('Nut leer            (0, 2.0, 20)', 0.0, 2.0, 20.0, False),
        ('Zunge 1,6 mm        (0, 5.0, 20)', 0.0, 5.0, 20.0, True),
        ('hinter der Zunge    (0, 6.8, 20)', 0.0, 6.8, 20.0, False),
        ('Platte hinter Zunge (0, 9.0, 20)', 0.0, 9.0, 20.0, True),
        ('Schlitz offen     (4.75, 5.0, 20)', 4.75, 5.0, 20.0, False),
        ('Rastnase            (0, 3.3, 24.5)', 0.0, 3.3, 24.5, True),
        ('Zuglasche           (0, 9.5, 32)', 0.0, 9.5, 32.0, True),
        ('Freigang neben Lasche (6, 9.5, 32)', 6.0, 9.5, 32.0, False),
        ('Freigang-Dach traegt (0, 9.5, 44)', 0.0, 9.5, 44.0, True),
        ('Fenster offen      (27, 9.5, 25)', 27.0, 9.5, 25.0, False),
        ('Fenster-Dach traegt (27, 9.5, 45)', 27.0, 9.5, 45.0, True),
        ('Untergurt steht    (27, 9.5, 11)', 27.0, 9.5, 11.0, True),
        ('Steg neben Fenster (40, 9.5, 25)', 40.0, 9.5, 25.0, True),
        ('Pad massiv        (50, 20.0, 30)', 50.0, 20.0, 30.0, True),
        ('Pad Innenkante    (40.5, 20.0, 30)', 40.5, 20.0, 30.0, True),
        ('vor Pad frei      (39.5, 20.0, 30)', 39.5, 20.0, 30.0, False),
        ('Pad-Anlauf frei   (50, 22.0, 12)', 50.0, 22.0, 12.0, False),
        ('Pad-Anlauf traegt (50, 22.0, 21)', 50.0, 22.0, 21.0, True),
        ('Insertsitz weit   (50, 19.0, 40.6)', 50.0, 19.0, 40.6, False),
        ('Durchgang eng     (50, 9.0, 40.6)', 50.0, 9.0, 40.6, True),
        ('Durchgang offen   (50, 9.0, 38.18)', 50.0, 9.0, 38.18, False),
        ('Spalt fuer Zugang (0, 18.0, 30)', 0.0, 18.0, 30.0, False),
    ]
    bad = 0
    for name, x, y, z, expect in checks:
        got = solid(x, y, z)
        ok = (got == expect)
        bad += 0 if ok else 1
        print('%-38s soll=%-5s ist=%-5s %s' % (name, expect, got,
                                               'OK' if ok else '<<< ABWEICHUNG'))
    print('Abweichungen:', bad)

    export_mgr = design.exportManager
    stl_path = EXPORT_DIR + r"\asa_junctek_halter.stl"
    opts = export_mgr.createSTLExportOptions(part, stl_path)
    opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
    export_mgr.execute(opts)
    print("exported: " + stl_path)
    step_path = EXPORT_DIR + r"\junctek_halter.step"
    export_mgr.execute(export_mgr.createSTEPExportOptions(step_path, root))
    print("exported: " + step_path)
