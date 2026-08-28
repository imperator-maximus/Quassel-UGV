# Fusion360-Skript: Snap-Schnittstelle fuer "Halterung Batterie" (Prueflehre)
# Wird ueber den Fusion-MCP-Server ausgefuehrt (featureType=script).
#
# Zweck: An den drei 30x30x3-Stegen der Batteriehalterung soll man Anbauteile
# (<0,5 kg) wechseln koennen, ohne die 195-mm-Grundplatte neu zu drucken.
# Schnittstelle = Schwalbenschwanz-Schiene auf der Steg-Aussenseite + Rastnase.
#
# Dieses Skript baut die zwei Testkoerper (montiert dargestellt):
#   1) snap_rail_pruefklotz - 30x30-Wandstueck mit Flansch, Anschlagsockel
#      und Schiene. Bildet exakt die Steg-Aussenseite der Halterung nach.
#   2) snap_adapter - Gegenstueck mit Schwalbenschwanznut, Federzunge,
#      Rastnase, Zuglasche und 4x M3-Einschmelzgewinde als Montagepad.
#
# Kinematik: Adapter von oben aufschieben, faellt am Anschlagsockel (Z=8) auf
# Anschlag, Rastnase schnappt in die Nut der Schiene. Loesen = Zuglasche oben
# nach aussen ziehen, dann abziehen.
#
# DRUCKREGEL (gilt fuer Halterung UND jedes Anbauteil):
# Schiebeachse = Modell-Z steht immer senkrecht auf dem Druckbett.
# Vorgabe kommt von der Halterung selbst - die 195x48x3-Platte mit ihren drei
# Stegen laesst sich nur flach drucken, damit liegt die Schiebeachse fest.
# In dieser Lage sind Schwalbenschwanz und Nut reine Prismen in Z -> null
# Ueberhang, glatte Flanken, das Spiel von CL stimmt exakt. Alle uebrigen
# Ueberhaenge sind 45 Grad. ASA, keine Stuetzen.
#
# Kehrseite: die Federzunge biegt damit QUER zur Schichtrichtung. Deshalb ist
# sie auf ~0,9 % Randfaserdehnung ausgelegt (duenn + langer Hebel), nicht auf
# die ~1,5 %, die in Schichtebene noch vertretbar waeren.
#
# Masse in mm (Fusion-API rechnet intern in cm -> mm()-Helper).

import adsk.core
import adsk.fusion

# --- Steg der Halterung (aus "Halterung Batterie v4" ausgemessen) ---
WALL_W = 30.0          # Stegbreite
WALL_T = 3.0           # Stegdicke
WALL_H = 30.0          # Steghoehe
FLANGE_OUT = 9.0       # Flansch ragt 9 mm ueber die Steg-Aussenflaeche
FLANGE_IN = 1.0        # ... und 1 mm dahinter
FLANGE_T = 3.0
# ACHTUNG: diese zwei Loecher gibt es am echten Teil NICHT. Am Original sind die
# zwei Ø4-Kreise pro Lasche R2-Eckverrundungen. Faellt beim Pruefklotz nicht ins
# Gewicht (beruehrt die Passung nicht), aber nicht weiterverwenden.
FLANGE_HOLE_R = 2.0
FLANGE_HOLE_X = 13.0   # +/-13 von Stegmitte
FLANGE_HOLE_Y = 7.0    # 7 mm vor der Steg-Aussenflaeche

# --- Schiene (maennlich, ersetzt die bisherige 2-mm-Rippe) ---
RAIL_W_ROOT = 11.0     # Breite an der Wand
RAIL_W_TIP = 16.0      # Breite aussen -> Hinterschnitt, 58 Grad Flanke
RAIL_H = 4.0           # Vorsprung vor der Wand
RAIL_Z0 = 8.0          # Oberkante Anschlagsockel
RAIL_Z1 = 30.0         # buendig mit Stegoberkante

STOP_Z0 = 3.0          # Anschlagsockel steht auf dem Flansch
STOP_Z1 = 8.0          # 5 mm hoch -> Adapter raeumt die Flanschschrauben frei

DET_Z0 = 22.2          # Rastnut in der Schienen-Stirnflaeche
DET_Z1 = 26.8
DET_DEPTH = 1.2
DET_W = 7.0

# --- Adapter ---
CL = 0.25              # Flankenspiel Schwalbenschwanz (ASA, Schiebesitz)
AD_W = 26.0            # Adapterbreite
AD_Y0 = 0.25           # Innenflaeche, 0,25 mm Luft zur Wand
AD_WALL_Y = 7.5        # Rueckwand aussen (mittig, traegt die Federzunge)
AD_COL_Y = 12.0        # Saeulen aussen = Montageflaeche
AD_COL_X = 6.5         # Saeulen ab +/-6,5
AD_Z1 = 30.0

TONGUE_W = 8.0         # Federzunge
TONGUE_T = 1.6         # ausgeduennt: 3,25 mm Rueckwand waere viel zu steif
TAPER_Z0 = 9.0         # Fuss laeuft von 3,25 auf 2,0 mm aus (keine Kerbe)
TAPER_Z1 = 14.0
SLIT_W = 1.5           # Freischnitt links/rechts
SLIT_Z0 = 10.0
NOSE_W = 6.0
NOSE_TIP_Y = 3.1       # Rastnase greift 0,9 mm in die Schiene
NOSE_Z0 = 22.45        # weiter oben = laengerer Hebel = weniger Dehnung
NOSE_Z1 = 26.55
TAB_Y = 10.5           # Zuglasche
TAB_Z0 = 29.0          # 1 mm Ueberlappung mit der Zunge -> sauberer Join
TAB_Z1 = 34.5

INSERT_D = 4.0         # M3-Einschmelzgewinde: Ø4,0 x 6,5
INSERT_DEPTH = 6.5
INSERT_X = 9.5
INSERT_Z = (13.0, 25.0)

EXPORT_DIR = r"C:\Users\mausz\Documents\PlatformIO\Projects\quassel-ugv\cad"


def mm(v):
    return v / 10.0


def offset_plane(root, base, dist, comp):
    """Konstruktionsebene mit Offset. Vorzeichen zur Laufzeit pruefen, weil
    die XZ-Ebene ihre Normale entgegen Modell-Y hat."""
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
    """pts = [(x, y, z), ...] in Modellkoordinaten, muessen auf der Ebene liegen."""
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


def run(_context):
    app = adsk.core.Application.get()
    app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent

    xy = root.xYConstructionPlane
    yz = root.yZConstructionPlane
    xz = root.xZConstructionPlane
    new_body = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    join = adsk.fusion.FeatureOperations.JoinFeatureOperation
    cut = adsk.fusion.FeatureOperations.CutFeatureOperation

    hw = WALL_W / 2.0
    rr, rt = RAIL_W_ROOT / 2.0, RAIL_W_TIP / 2.0

    # ================= 1) Pruefklotz =================
    # Wand (bildet die Steg-Aussenflaeche bei Y=0 nach)
    sk = root.sketches.add(xy)
    sk.name = "wand"
    poly(sk, [(-hw, -WALL_T, 0), (hw, -WALL_T, 0), (hw, 0, 0), (-hw, 0, 0)])
    extrude(root, sk.profiles.item(0), WALL_H, new_body)

    # Flansch
    sk = root.sketches.add(xy)
    sk.name = "flansch"
    poly(sk, [(-hw, -FLANGE_IN, 0), (hw, -FLANGE_IN, 0),
              (hw, FLANGE_OUT, 0), (-hw, FLANGE_OUT, 0)])
    extrude(root, sk.profiles.item(0), FLANGE_T, new_body)

    # Anschlagsockel: volle Stegbreite, der Adapter setzt darauf auf
    pl_stop = offset_plane(root, xy, STOP_Z0, "z")
    sk = root.sketches.add(pl_stop)
    sk.name = "anschlagsockel"
    poly(sk, [(-hw, 0, STOP_Z0), (hw, 0, STOP_Z0),
              (hw, RAIL_H, STOP_Z0), (-hw, RAIL_H, STOP_Z0)])
    extrude(root, sk.profiles.item(0), STOP_Z1 - STOP_Z0, new_body)

    # Schwalbenschwanz-Schiene
    pl_z8 = offset_plane(root, xy, RAIL_Z0, "z")
    sk = root.sketches.add(pl_z8)
    sk.name = "schiene"
    poly(sk, [(-rr, 0, RAIL_Z0), (rr, 0, RAIL_Z0),
              (rt, RAIL_H, RAIL_Z0), (-rt, RAIL_H, RAIL_Z0)])
    extrude(root, sk.profiles.item(0), RAIL_Z1 - RAIL_Z0, new_body)

    # zu einem Koerper vereinen
    bodies = root.bRepBodies
    target = bodies.item(0)
    tools = adsk.core.ObjectCollection.create()
    for i in range(1, bodies.count):
        tools.add(bodies.item(i))
    comb = root.features.combineFeatures.createInput(target, tools)
    comb.operation = join
    comb.isKeepToolBodies = False
    root.features.combineFeatures.add(comb)
    klotz = root.bRepBodies.item(0)
    klotz.name = "snap_rail_pruefklotz"
    parts_klotz = [klotz]

    # Flanschloecher (wie am Original: Ø4 bei +/-13 / Y=7)
    sk = root.sketches.add(xy)
    sk.name = "flanschloecher"
    for sx in (-FLANGE_HOLE_X, FLANGE_HOLE_X):
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            adsk.core.Point3D.create(mm(sx), mm(FLANGE_HOLE_Y), 0), mm(FLANGE_HOLE_R))
    extrude(root, all_profiles(sk), FLANGE_T, cut, parts_klotz)

    # Einfuehrfase oben an der Schiene (45 Grad, nach oben offen)
    sk = root.sketches.add(yz)
    sk.name = "schiene_fase"
    poly(sk, [(0, 1.5, RAIL_Z1 + 1.0), (0, 5.0, RAIL_Z1 + 1.0), (0, 5.0, RAIL_Z1 - 2.5)])
    extrude(root, sk.profiles.item(0), 2 * RAIL_W_TIP, cut, parts_klotz, symmetric=True)

    # Rastnut in der Schienen-Stirnflaeche, beide Flanken 45 Grad
    y_in = RAIL_H - DET_DEPTH
    over = 5.0 - RAIL_H
    sk = root.sketches.add(yz)
    sk.name = "rastnut"
    poly(sk, [(0, 5.0, DET_Z0 - over), (0, y_in, DET_Z0 + DET_DEPTH),
              (0, y_in, DET_Z1 - DET_DEPTH), (0, 5.0, DET_Z1 + over)])
    extrude(root, sk.profiles.item(0), DET_W, cut, parts_klotz, symmetric=True)

    # ================= 2) Adapter =================
    ahw = AD_W / 2.0
    sk = root.sketches.add(pl_z8)
    sk.name = "adapter_block"
    poly(sk, [(-ahw, AD_Y0, RAIL_Z0), (ahw, AD_Y0, RAIL_Z0),
              (ahw, AD_WALL_Y, RAIL_Z0), (-ahw, AD_WALL_Y, RAIL_Z0)])
    ad_ext = extrude(root, sk.profiles.item(0), AD_Z1 - RAIL_Z0, new_body)
    adapter = ad_ext.bodies.item(0)
    adapter.name = "snap_adapter"
    parts_ad = [adapter]

    # Montagesaeulen links/rechts (Aussenflaeche = Anschraubflaeche)
    sk = root.sketches.add(pl_z8)
    sk.name = "adapter_saeulen"
    for x0, x1 in ((AD_COL_X, ahw), (-ahw, -AD_COL_X)):
        poly(sk, [(x0, AD_WALL_Y, RAIL_Z0), (x1, AD_WALL_Y, RAIL_Z0),
                  (x1, AD_COL_Y, RAIL_Z0), (x0, AD_COL_Y, RAIL_Z0)])
    extrude(root, all_profiles(sk), AD_Z1 - RAIL_Z0, join, parts_ad)

    # Schwalbenschwanznut (Negativ der Schiene + Spiel), oben offen
    fr, ft, fu = rr + CL, rt + CL, RAIL_H + CL
    slope = (ft - fr) / fu
    sk = root.sketches.add(pl_z8)
    sk.name = "adapter_nut"
    poly(sk, [(-(fr - slope), -1.0, RAIL_Z0), (fr - slope, -1.0, RAIL_Z0),
              (ft, fu, RAIL_Z0), (-ft, fu, RAIL_Z0)])
    extrude(root, sk.profiles.item(0), AD_Z1 - RAIL_Z0, cut, parts_ad)

    # Freischnitt der Federzunge (zwei Schlitze mit rundem Auslauf)
    thw, sr = TONGUE_W / 2.0, SLIT_W / 2.0
    y_mid = (AD_WALL_Y + RAIL_H) / 2.0
    pl_y = offset_plane(root, xz, y_mid, "y")
    sk = root.sketches.add(pl_y)
    sk.name = "adapter_freischnitt"
    for sx in (-1.0, 1.0):
        x0, x1 = sx * thw, sx * (thw + SLIT_W)
        poly(sk, [(min(x0, x1), y_mid, SLIT_Z0), (max(x0, x1), y_mid, SLIT_Z0),
                  (max(x0, x1), y_mid, AD_Z1 + 0.5), (min(x0, x1), y_mid, AD_Z1 + 0.5)])
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            sk.modelToSketchSpace(adsk.core.Point3D.create(
                mm(sx * (thw + sr)), mm(y_mid), mm(SLIT_Z0))), mm(sr))
    extrude(root, all_profiles(sk), (AD_WALL_Y - RAIL_H) + 1.0, cut,
            parts_ad, symmetric=True)

    # Zunge auf TONGUE_T ausduennen. Fuss angeschraegt statt abgesetzt, sonst
    # sitzt die Kerbe genau in der hoechstbelasteten Stelle. Oben offen -> kein
    # Ueberhang. Muss vor der Zuglasche laufen, damit die satt anbindet.
    ty = fu + TONGUE_T
    sk = root.sketches.add(yz)
    sk.name = "adapter_zunge_duenn"
    poly(sk, [(0, AD_WALL_Y + 0.5, TAPER_Z0), (0, ty, TAPER_Z1),
              (0, ty, AD_Z1 + 1.0), (0, AD_WALL_Y + 0.5, AD_Z1 + 1.0)])
    extrude(root, sk.profiles.item(0), TONGUE_W, cut, parts_ad, symmetric=True)

    # Rastnase auf der Zungeninnenseite, Einlauframpe unten / Haltefase oben 45 Grad
    nose_base = fu + 0.5           # 0,5 mm in die Zunge hinein -> sauberer Join
    ramp = nose_base - NOSE_TIP_Y
    sk = root.sketches.add(yz)
    sk.name = "adapter_rastnase"
    poly(sk, [(0, nose_base, NOSE_Z0 - 0.5), (0, NOSE_TIP_Y, NOSE_Z0 - 0.5 + ramp),
              (0, NOSE_TIP_Y, NOSE_Z1 + 0.5 - ramp), (0, nose_base, NOSE_Z1 + 0.5)])
    extrude(root, sk.profiles.item(0), NOSE_W, join, parts_ad, symmetric=True)

    # Zuglasche oben (ueber dem Montagepad, bleibt auch bei Anbau erreichbar)
    sk = root.sketches.add(yz)
    sk.name = "adapter_zuglasche"
    poly(sk, [(0, fu, TAB_Z0), (0, AD_WALL_Y, TAB_Z0),
              (0, TAB_Y, TAB_Z0 + (TAB_Y - AD_WALL_Y)),
              (0, TAB_Y, TAB_Z1), (0, fu, TAB_Z1)])
    extrude(root, sk.profiles.item(0), TONGUE_W, join, parts_ad, symmetric=True)

    # 4x M3-Einschmelzgewinde in die Saeulen
    y_i = AD_COL_Y - INSERT_DEPTH / 2.0
    pl_i = offset_plane(root, xz, y_i, "y")
    sk = root.sketches.add(pl_i)
    sk.name = "adapter_inserts"
    for sx in (-INSERT_X, INSERT_X):
        for sz in INSERT_Z:
            sk.sketchCurves.sketchCircles.addByCenterRadius(
                sk.modelToSketchSpace(adsk.core.Point3D.create(mm(sx), mm(y_i), mm(sz))),
                mm(INSERT_D) / 2.0)
    extrude(root, all_profiles(sk), INSERT_DEPTH, cut, parts_ad, symmetric=True)

    # ================= Kontrolle + Export =================
    for b in root.bRepBodies:
        bb = b.boundingBox
        print("%-22s vol=%7.2f cm3  x %6.2f..%6.2f  y %6.2f..%6.2f  z %6.2f..%6.2f" % (
            b.name, b.volume,
            bb.minPoint.x * 10, bb.maxPoint.x * 10,
            bb.minPoint.y * 10, bb.maxPoint.y * 10,
            bb.minPoint.z * 10, bb.maxPoint.z * 10))

    export_mgr = design.exportManager
    for b in root.bRepBodies:
        path = EXPORT_DIR + "\\asa_" + b.name + ".stl"
        opts = export_mgr.createSTLExportOptions(b, path)
        opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
        export_mgr.execute(opts)
        print("exported: " + path)
    step_path = EXPORT_DIR + r"\snap_interface.step"
    export_mgr.execute(export_mgr.createSTEPExportOptions(step_path, root))
    print("exported: " + step_path)
