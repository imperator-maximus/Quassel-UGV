# Fusion360-Skript: ASA-Gehaeuse fuer ODrive v3.5 (Wanne + Lamellendeckel)
# Wird ueber den Fusion-MCP-Server ausgefuehrt (featureType=script).
#
# Basis: PCB_v3.5.step aus dem ODriveHardware-Repo vermessen:
#   Board 140.5 x 50.0 x 1.7 mm
#   4 mittlere M3-Montageloecher (O3.4) bei x=55/93.5, y=5.5/29.1 (Board-Koord.)
#   Bauteile: 10.5 mm auf der dicken Seite (Elkos/Klemmen), 4.2 mm andere Seite
#
# Design:
#  - Wanne: Bodenplatte 3 mm, Waende 3 mm, innen 10 mm Luft um die Platine
#  - 4 Standoffs O8 x 12 mm mit Loechern O4.0 x 6.5 fuer M3-Einschmelzgewinde
#    (12 mm statt "ca. 1 cm", weil die Unterseiten-Bauteile 10.5 mm hoch sind)
#  - 4 Ecksaeulen O10 mit Loechern O5.6 x 9 fuer M4-Einschmelzgewinde
#  - Je Stirnseite 2 Loecher O16.5 (M16-Kabelverschraubung, innen verschraubt)
#  - Deckel: Platte 3 mm mit 17 Lueftungsschlitzen, darueber 45-Grad-Lamellen
#    (gleiche Bauart wie die Outrunner-Haube, vertikal blickdicht,
#    Tropfkante landet auf massivem Steg) - kopfueber ohne Stuetzen druckbar
#  - Deckelbefestigung: 4x M4 an den Ecken

import math
import adsk.core
import adsk.fusion

# --- Board (gemessen aus PCB_v3.5.step) ---
BOARD_L = 140.5
BOARD_W = 50.0
# Montageloecher relativ zur Board-Ecke: 4 in einer Reihe (vom User am
# realen Board bestaetigt); die Reihe y=5.5 liegt unter den Terminal-Blocks.
BOARD_HOLES = [(12.5, 29.1), (55.0, 29.1), (93.5, 29.1), (133.5, 29.1)]

# --- Gehaeuse ---
CLEAR = 20.0            # Luft um die Platine, je Seite (Kabelverschraubungen
                        # ragen ~15 mm ins Gehaeuse und brauchen den Platz)
WALL = 3.0
BASE_T = 3.0
INNER_L = BOARD_L + 2 * CLEAR   # 160.5
INNER_W = BOARD_W + 2 * CLEAR   # 70.0
OUTER_L = INNER_L + 2 * WALL    # 166.5
OUTER_W = INNER_W + 2 * WALL    # 76.0
WALL_TOP = 50.0         # Oberkante Wand (= Auflage Deckel)

STANDOFF_D = 8.0
STANDOFF_H = 12.0       # Freiraum unter der Platine
M3_INSERT_D = 4.0       # Ruthex/Standard M3-Einschmelzgewinde
M3_INSERT_DEPTH = 6.5

# Eckstuetzen unter den Platinenecken (ohne Loch, gegen Wippen der Platine)
CORNER_PAD = 3.0

POST_D = 10.0
M4_INSERT_D = 5.6       # Standard M4-Einschmelzgewinde
M4_INSERT_DEPTH = 9.0
POST_OFF_X = OUTER_L / 2 - WALL - POST_D / 2   # 75.25
POST_OFF_Y = OUTER_W / 2 - WALL - POST_D / 2   # 30.0

GLAND_D = 16.5          # M16-Kabelverschraubung
GLAND_Y = 19.0          # Lochmitten +/-19 von der Mitte
GLAND_Z = 36.5          # Lochmitte: Oberkante Loch ~5 mm unter dem Wannenrand

# --- Deckel ---
LID_T = 3.0
LID_HOLE_D = 4.4        # M4 Durchgang
VENT_N = 21             # Schlitze
VENT_PITCH = 7.0
VENT_W = 4.0            # Schlitzbreite (3 mm Steg dazwischen)
VENT_SPAN = 38.0        # Schlitze y -38..38, mittlerer Steg y -3..3
VENT_SPINE = 3.0
LOUVER_T = 2.0          # Lamellendicke (vertikal)
LOUVER_RISE = 6.0       # 45 Grad: 6 mm Anstieg ueber 6 mm Lauf
LOUVER_SINK = 2.0       # Eintauchtiefe in Platte/Rahmen (echte Verschmelzung)
VENT_X0 = -(VENT_N * VENT_PITCH) / 2   # -59.5

FILLET_R = 5.0          # Radius der senkrechten Aussenkanten (Wanne + Deckel)

# Montageflansche an beiden Stirnseiten (verlaengerte Bodenplatte)
FLANGE_LEN = 14.0       # Auskragung ueber die Wand hinaus
FLANGE_T = 4.0          # Dicke
FLANGE_HOLE_D = 5.5     # M5 Durchgang
FLANGE_HOLE_Y = [-34.0, 0.0, 34.0]
FLANGE_HOLE_X_OFF = 8.0  # Lochmitte hinter der Wandaussenflaeche

EXPORT_DIR = r"C:\Users\mausz\Documents\PlatformIO\Projects\UGV ESP32CAN\cad"


def mm(v):
    return v / 10.0


def run(_context):
    app = adsk.core.Application.get()
    # Immer in einem frischen Dokument bauen.
    app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    sketches = root.sketches
    extrudes = root.features.extrudeFeatures
    planes = root.constructionPlanes

    def rect(sk, x0, y0, x1, y1):
        sk.sketchCurves.sketchLines.addTwoPointRectangle(
            adsk.core.Point3D.create(mm(x0), mm(y0), 0),
            adsk.core.Point3D.create(mm(x1), mm(y1), 0))

    def circle(sk, cx, cy, cz, d):
        pt = sk.modelToSketchSpace(adsk.core.Point3D.create(mm(cx), mm(cy), mm(cz)))
        sk.sketchCurves.sketchCircles.addByCenterRadius(pt, mm(d) / 2)

    def all_profiles(sk):
        oc = adsk.core.ObjectCollection.create()
        for i in range(sk.profiles.count):
            oc.add(sk.profiles.item(i))
        return oc

    def offset_plane(z=None, x=None):
        pin = planes.createInput()
        if z is not None:
            pin.setByOffset(root.xYConstructionPlane,
                            adsk.core.ValueInput.createByReal(mm(z)))
        else:
            pin.setByOffset(root.yZConstructionPlane,
                            adsk.core.ValueInput.createByReal(mm(x)))
        return planes.add(pin)

    NEW = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    JOIN = adsk.fusion.FeatureOperations.JoinFeatureOperation
    CUT = adsk.fusion.FeatureOperations.CutFeatureOperation

    # ================= WANNE =================
    sk = sketches.add(root.xYConstructionPlane)
    sk.name = "base_plate"
    rect(sk, -OUTER_L / 2, -OUTER_W / 2, OUTER_L / 2, OUTER_W / 2)
    ext = extrudes.createInput(sk.profiles.item(0), NEW)
    ext.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(BASE_T)))
    base = extrudes.add(ext).bodies.item(0)

    # Waende (Ring) + Ecksaeulen
    sk = sketches.add(root.xYConstructionPlane)
    sk.name = "walls_posts"
    rect(sk, -OUTER_L / 2, -OUTER_W / 2, OUTER_L / 2, OUTER_W / 2)
    rect(sk, -INNER_L / 2, -INNER_W / 2, INNER_L / 2, INNER_W / 2)
    for sx in (-1, 1):
        for sy in (-1, 1):
            circle(sk, sx * POST_OFF_X, sy * POST_OFF_Y, 0, POST_D)
    profs = adsk.core.ObjectCollection.create()
    for i in range(sk.profiles.count):
        p = sk.profiles.item(i)
        if p.profileLoops.count == 2:      # Wandring (hat Innen- und Aussenloop)
            profs.add(p)
        else:
            bb = p.boundingBox
            if (bb.maxPoint.x - bb.minPoint.x) * 10 < POST_D + 1:  # Saeulen
                profs.add(p)
    ext = extrudes.createInput(profs, JOIN)
    ext.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(WALL_TOP)))
    extrudes.add(ext)

    # Standoffs (Boardmitte = Gehaeusemitte)
    off_x, off_y = -BOARD_L / 2, -BOARD_W / 2
    standoffs = [(bx + off_x, by + off_y) for bx, by in BOARD_HOLES]
    sk = sketches.add(root.xYConstructionPlane)
    sk.name = "standoffs"
    for cx, cy in standoffs:
        circle(sk, cx, cy, 0, STANDOFF_D)
    ext = extrudes.createInput(all_profiles(sk), JOIN)
    ext.setDistanceExtent(
        False, adsk.core.ValueInput.createByReal(mm(BASE_T + STANDOFF_H)))
    extrudes.add(ext)

    # Eckstuetzen: 3x3 mm, gleiche Hoehe wie Standoffs, ganz unter der Platine
    sk = sketches.add(root.xYConstructionPlane)
    sk.name = "corner_pads"
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = sx * BOARD_L / 2, sy * BOARD_W / 2
            rect(sk, cx - (CORNER_PAD if sx > 0 else 0),
                 cy - (CORNER_PAD if sy > 0 else 0),
                 cx + (0 if sx > 0 else CORNER_PAD),
                 cy + (0 if sy > 0 else CORNER_PAD))
    ext = extrudes.createInput(all_profiles(sk), JOIN)
    ext.setDistanceExtent(
        False, adsk.core.ValueInput.createByReal(mm(BASE_T + STANDOFF_H)))
    extrudes.add(ext)

    # M3-Insert-Loecher (von oben in die Standoffs)
    pl = offset_plane(z=BASE_T + STANDOFF_H)
    sk = sketches.add(pl)
    sk.name = "m3_holes"
    for cx, cy in standoffs:
        circle(sk, cx, cy, BASE_T + STANDOFF_H, M3_INSERT_D)
    ext = extrudes.createInput(all_profiles(sk), CUT)
    ext.setDistanceExtent(
        False, adsk.core.ValueInput.createByReal(-mm(M3_INSERT_DEPTH)))
    extrudes.add(ext)

    # M4-Insert-Loecher (von oben in die Ecksaeulen)
    pl = offset_plane(z=WALL_TOP)
    sk = sketches.add(pl)
    sk.name = "m4_holes"
    for sx in (-1, 1):
        for sy in (-1, 1):
            circle(sk, sx * POST_OFF_X, sy * POST_OFF_Y, WALL_TOP, M4_INSERT_D)
    ext = extrudes.createInput(all_profiles(sk), CUT)
    ext.setDistanceExtent(
        False, adsk.core.ValueInput.createByReal(-mm(M4_INSERT_DEPTH)))
    extrudes.add(ext)

    # Kabelverschraubungs-Loecher, beide Stirnseiten
    for side in (-1, 1):
        pl = offset_plane(x=side * (OUTER_L / 2 - 4.0))
        sk = sketches.add(pl)
        sk.name = f"glands_{'left' if side < 0 else 'right'}"
        for sy in (-1, 1):
            circle(sk, side * (OUTER_L / 2 - 4.0), sy * GLAND_Y, GLAND_Z, GLAND_D)
        ext = extrudes.createInput(all_profiles(sk), CUT)
        ext.setSymmetricExtent(adsk.core.ValueInput.createByReal(mm(14.0)), True)
        extrudes.add(ext)

    # Montageflansche: Bodenplatte an den Stirnseiten verlaengert
    # (beginnt 6 mm innerhalb der Wand, damit an den gerundeten Ecken
    # kein Spalt zwischen Flansch und Wand entsteht)
    sk = sketches.add(root.xYConstructionPlane)
    sk.name = "flanges"
    for side in (-1, 1):
        x_in = side * (OUTER_L / 2 - 6.0)
        x_out = side * (OUTER_L / 2 + FLANGE_LEN)
        rect(sk, min(x_in, x_out), -OUTER_W / 2, max(x_in, x_out), OUTER_W / 2)
    ext = extrudes.createInput(all_profiles(sk), JOIN)
    ext.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(FLANGE_T)))
    ext.participantBodies = [base]
    extrudes.add(ext)

    sk = sketches.add(root.xYConstructionPlane)
    sk.name = "flange_holes"
    for side in (-1, 1):
        hx = side * (OUTER_L / 2 + FLANGE_HOLE_X_OFF)
        for hy in FLANGE_HOLE_Y:
            circle(sk, hx, hy, 0, FLANGE_HOLE_D)
    ext = extrudes.createInput(all_profiles(sk), CUT)
    ext.setSymmetricExtent(adsk.core.ValueInput.createByReal(10.0), True)
    ext.participantBodies = [base]
    extrudes.add(ext)

    base.name = "odrive35_box_base"

    # ================= DECKEL =================
    pl = offset_plane(z=WALL_TOP)
    sk = sketches.add(pl)
    sk.name = "lid_plate"
    p0 = sk.modelToSketchSpace(
        adsk.core.Point3D.create(mm(-OUTER_L / 2), mm(-OUTER_W / 2), mm(WALL_TOP)))
    p1 = sk.modelToSketchSpace(
        adsk.core.Point3D.create(mm(OUTER_L / 2), mm(OUTER_W / 2), mm(WALL_TOP)))
    sk.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
    ext = extrudes.createInput(sk.profiles.item(0), NEW)
    ext.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(LID_T)))
    lid = extrudes.add(ext).bodies.item(0)

    # Lueftungsschlitze (2 Felder, mittlerer Steg bleibt stehen)
    sk = sketches.add(root.xYConstructionPlane)
    sk.name = "vent_slots"
    for i in range(VENT_N):
        x0 = VENT_X0 + VENT_PITCH * i
        rect(sk, x0, -VENT_SPAN, x0 + VENT_W, -VENT_SPINE)
        rect(sk, x0, VENT_SPINE, x0 + VENT_W, VENT_SPAN)
    ext = extrudes.createInput(all_profiles(sk), CUT)
    ext.setSymmetricExtent(adsk.core.ValueInput.createByReal(20.0), True)
    ext.participantBodies = [lid]
    extrudes.add(ext)

    # Lamellen: 45 Grad, Tropfkante landet 1 mm hinter dem Schlitz auf dem Steg
    # (XZ-Skizze: Skizzen-Y laeuft entgegen Modell-Z -> Vorzeichen dynamisch)
    sk_probe = sketches.add(root.xZConstructionPlane)
    probe = sk_probe.sketchPoints.add(adsk.core.Point3D.create(0, 1.0, 0))
    zsign = 1.0 if probe.worldGeometry.z > 0 else -1.0
    sk_probe.deleteMe()

    sk = sketches.add(root.xZConstructionPlane)
    sk.name = "louvers"
    lines = sk.sketchCurves.sketchLines
    z_top = WALL_TOP + LID_T

    def louver_poly(pts):
        for i in range(len(pts)):
            x0, z0 = pts[i]
            x1, z1 = pts[(i + 1) % len(pts)]
            lines.addByTwoPoints(
                adsk.core.Point3D.create(mm(x0), zsign * mm(z0), 0),
                adsk.core.Point3D.create(mm(x1), zsign * mm(z1), 0))

    for i in range(VENT_N):
        x0 = VENT_X0 + VENT_PITCH * i
        tip = x0 + VENT_W + 1.0
        zb = z_top - LOUVER_SINK  # Fusspunkt in der Platte versenkt
        louver_poly([(tip, zb), (tip, zb + LOUVER_T),
                     (tip - LOUVER_RISE, zb + LOUVER_T + LOUVER_RISE),
                     (tip - LOUVER_RISE, zb + LOUVER_RISE)])
    ext = extrudes.createInput(all_profiles(sk), JOIN)
    ext.setSymmetricExtent(
        adsk.core.ValueInput.createByReal(mm(2 * (VENT_SPAN + LOUVER_SINK))), True)
    ext.participantBodies = [lid]
    extrudes.add(ext)

    # M4-Durchgangsloecher an den Ecken
    sk = sketches.add(root.xYConstructionPlane)
    sk.name = "lid_holes"
    for sx in (-1, 1):
        for sy in (-1, 1):
            circle(sk, sx * POST_OFF_X, sy * POST_OFF_Y, 0, LID_HOLE_D)
    ext = extrudes.createInput(all_profiles(sk), CUT)
    ext.setSymmetricExtent(adsk.core.ValueInput.createByReal(20.0), True)
    ext.participantBodies = [lid]
    extrudes.add(ext)

    lid.name = "odrive35_box_lid"

    # Senkrechte Aussenkanten abrunden (Wanne + Deckel gleich)
    for body in (base, lid):
        edges = adsk.core.ObjectCollection.create()
        for i in range(body.edges.count):
            e = body.edges.item(i)
            p0, p1 = e.startVertex.geometry, e.endVertex.geometry
            if (abs(p0.x - p1.x) < 1e-6 and abs(p0.y - p1.y) < 1e-6
                    and (abs(abs(p0.x) * 10 - OUTER_L / 2) < 0.01
                         or abs(abs(p0.x) * 10 - (OUTER_L / 2 + FLANGE_LEN)) < 0.01)
                    and abs(abs(p0.y) * 10 - OUTER_W / 2) < 0.01):
                edges.add(e)
        fin = root.features.filletFeatures.createInput()
        fin.addConstantRadiusEdgeSet(
            edges, adsk.core.ValueInput.createByReal(mm(FILLET_R)), True)
        root.features.filletFeatures.add(fin)

    # ================= KONTROLLE + EXPORT =================
    print(f"bodies: {root.bRepBodies.count}")
    for i in range(root.bRepBodies.count):
        b = root.bRepBodies.item(i)
        bb = b.boundingBox
        print(f"  {b.name}: vol {b.volume:.1f} cm3, "
              f"z {bb.minPoint.z*10:.1f}..{bb.maxPoint.z*10:.1f}")

    export_mgr = design.exportManager
    for b, fname in ((base, "asa_odrive35_box_base.stl"),
                     (lid, "asa_odrive35_box_lid.stl")):
        path = EXPORT_DIR + "\\" + fname
        opts = export_mgr.createSTLExportOptions(b, path)
        opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
        export_mgr.execute(opts)
        print(f"exported: {path}")
    step_path = EXPORT_DIR + r"\odrive35_box.step"
    export_mgr.execute(export_mgr.createSTEPExportOptions(step_path, root))
    print(f"exported: {step_path}")
