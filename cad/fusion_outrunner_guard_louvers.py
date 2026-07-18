# Fusion360-Skript: ASA-Schutzhaube fuer ODrive D5065 Outrunner (Maehdeck)
# Wird ueber den Fusion-MCP-Server ausgefuehrt (featureType=script).
#
# Design:
#  - Geschlossener Deckel oben (Hauptschmutzpfad)
#  - 8 umlaufende Lamellen (45 Grad, nach unten/aussen) statt gerader Fenster:
#    kein direkter Sichtkontakt zur drehenden Glocke, Regen/Schleudergut prallt ab
#  - 6 vertikale Rippen verbinden die Lamellenringe mit Ober-/Unterteil
#  - Flansch unten mit 4x M5-Durchgangsloch auf Lochkreis 108 mm,
#    offene Senktaschen (Ø11) fuer die Schraubenkoepfe
#  - 45-Grad-Kegel vom Flansch zur Wand: kopfueber (Deckel aufs Druckbett)
#    ohne Stuetzen druckbar
#
# Masse in mm (Fusion-API rechnet intern in cm -> mm()-Helper).

import math
import adsk.core
import adsk.fusion

# --- Parameter (mm) ---
R_IN = 45.0            # Innenradius Haube (Motor Ø50 + 20 Luft)
R_OUT = 48.0           # Aussenradius Wand (3 mm Wandstaerke)
FLANGE_R = 61.0        # Flanschradius
FLANGE_T = 5.0         # Flanschdicke
CONE_TOP_Z = 18.0      # 45-Grad-Kegel (FLANGE_R,5) -> (R_OUT,18)
LOW_WALL_TOP = 20.0    # Oberkante unterer Wandring (innen)
UPPER_Z0 = 68.0        # Oberkante Lamellenband = Unterkante Deckel
CAP_Z0 = 68.0          # Unterkante Deckel (sitzt direkt auf dem Lamellenband)
HEIGHT = 71.0          # Gesamthoehe ueber Flanschunterkante

LOUVER_N = 8           # Lamellenanzahl
LOUVER_PITCH = 7.0     # vertikaler Abstand
LOUVER_Z0 = 13.5       # Aussen-Unterkante erste Lamelle
LOUVER_T = 2.0         # Lamellendicke (vertikal)
LOUVER_DROP = 6.5      # Hoehenversatz innen->aussen (45 Grad)
LOUVER_R_IN = 44.0
LOUVER_R_OUT = 50.5    # Tropfkante 2.5 mm ueber Wand

RIB_N = 6
RIB_W = 6.0            # tangential; 45-Grad-Lamellen schneiden die Rippe an,
RIB_R_IN = 41.5        # daher breiter/tiefer: schwaechste Stelle bleibt >=4x4
RIB_Z0, RIB_Z1 = 5.0, 69.0  # 1 mm in den Deckel, damit Combine sauber verschmilzt

BOLT_N = 4
BOLT_DIA = 5.5         # M5 Durchgang
BOLT_R = 54.0          # Lochkreis 108 mm
POCKET_DIA = 11.0      # Senktasche fuer M5-Zylinderkopf

# Kabeldurchlass unten, buendig mit Auflageflaeche (Kabel liegt plan auf).
# Position 0 Grad = mittig zwischen zwei Schraubtaschen (bei +/-45 Grad).
SLOT_W = 13.0          # Breite (tangential)
SLOT_H = 8.0           # Hoehe ab Unterkante
SLOT_X0, SLOT_X1 = 40.0, 66.0  # radial durch Wand und Flansch

EXPORT_DIR = r"C:\Users\mausz\Documents\PlatformIO\Projects\UGV ESP32CAN\cad"


def mm(v):
    return v / 10.0


def run(_context):
    app = adsk.core.Application.get()
    # Immer in einem frischen Dokument bauen, nie in ein bestehendes hinein.
    app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent

    # --- Rotationsprofil (XZ-Ebene) ---
    sk = root.sketches.add(root.xZConstructionPlane)
    sk.name = "guard_profile"
    lines = sk.sketchCurves.sketchLines

    def poly(pts):
        for i in range(len(pts)):
            x0, z0 = pts[i]
            x1, z1 = pts[(i + 1) % len(pts)]
            lines.addByTwoPoints(
                adsk.core.Point3D.create(mm(x0), mm(z0), 0),
                adsk.core.Point3D.create(mm(x1), mm(z1), 0),
            )

    # Flansch + Kegel + unterer Wandring
    poly([(R_IN, 0), (FLANGE_R, 0), (FLANGE_R, FLANGE_T),
          (R_OUT, CONE_TOP_Z), (R_OUT, LOW_WALL_TOP), (R_IN, LOW_WALL_TOP)])
    # Oberer Wandring + Deckel
    poly([(R_IN, UPPER_Z0), (R_OUT, UPPER_Z0), (R_OUT, HEIGHT),
          (0, HEIGHT), (0, CAP_Z0), (R_IN, CAP_Z0)])
    # Lamellen (Parallelogramme, 45 Grad nach unten/aussen)
    for i in range(LOUVER_N):
        z0 = LOUVER_Z0 + LOUVER_PITCH * i
        poly([(LOUVER_R_OUT, z0), (LOUVER_R_OUT, z0 + LOUVER_T),
              (LOUVER_R_IN, z0 + LOUVER_DROP + LOUVER_T),
              (LOUVER_R_IN, z0 + LOUVER_DROP)])

    profs = adsk.core.ObjectCollection.create()
    for i in range(sk.profiles.count):
        profs.add(sk.profiles.item(i))
    print(f"profiles: {sk.profiles.count}")

    revolves = root.features.revolveFeatures
    rev_in = revolves.createInput(
        profs, root.zConstructionAxis,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    rev_in.setAngleExtent(False, adsk.core.ValueInput.createByReal(2 * math.pi))
    rev = revolves.add(rev_in)
    print(f"revolve bodies: {rev.bodies.count}")

    # --- Rippe (verbindet Lamellen), dann 6x rund ---
    sk2 = root.sketches.add(root.xZConstructionPlane)
    sk2.name = "rib_profile"
    lines2 = sk2.sketchCurves.sketchLines

    def poly2(pts):
        for i in range(len(pts)):
            x0, z0 = pts[i]
            x1, z1 = pts[(i + 1) % len(pts)]
            lines2.addByTwoPoints(
                adsk.core.Point3D.create(mm(x0), mm(z0), 0),
                adsk.core.Point3D.create(mm(x1), mm(z1), 0),
            )

    poly2([(RIB_R_IN, RIB_Z0), (R_OUT, RIB_Z0),
           (R_OUT, RIB_Z1), (RIB_R_IN, RIB_Z1)])

    extrudes = root.features.extrudeFeatures
    ext_in = extrudes.createInput(
        sk2.profiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_in.setSymmetricExtent(adsk.core.ValueInput.createByReal(mm(RIB_W)), True)
    rib = extrudes.add(ext_in)
    rib_body = rib.bodies.item(0)

    circ = root.features.circularPatternFeatures
    ents = adsk.core.ObjectCollection.create()
    ents.add(rib_body)
    circ_in = circ.createInput(ents, root.zConstructionAxis)
    circ_in.quantity = adsk.core.ValueInput.createByReal(RIB_N)
    circ_in.totalAngle = adsk.core.ValueInput.createByString("360 deg")
    circ_in.isSymmetric = False
    circ.add(circ_in)

    # --- Alles zu einem Koerper vereinen ---
    bodies = root.bRepBodies
    target = bodies.item(0)
    for i in range(bodies.count):
        if bodies.item(i).volume > target.volume:
            target = bodies.item(i)
    tools = adsk.core.ObjectCollection.create()
    for i in range(bodies.count):
        if bodies.item(i) != target:
            tools.add(bodies.item(i))
    comb_in = root.features.combineFeatures.createInput(target, tools)
    comb_in.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    comb_in.isKeepToolBodies = False
    root.features.combineFeatures.add(comb_in)
    print(f"bodies after combine: {root.bRepBodies.count}")

    body = root.bRepBodies.item(0)
    bb = body.boundingBox
    s = 1.0 if abs(bb.maxPoint.z) >= abs(bb.minPoint.z) else -1.0

    centers = [(BOLT_R * math.cos(math.pi / 4 + k * math.pi / 2),
                BOLT_R * math.sin(math.pi / 4 + k * math.pi / 2))
               for k in range(BOLT_N)]

    # --- M5-Durchgangsloecher ---
    sk3 = root.sketches.add(root.xYConstructionPlane)
    sk3.name = "bolt_holes"
    for cx, cy in centers:
        sk3.sketchCurves.sketchCircles.addByCenterRadius(
            adsk.core.Point3D.create(mm(cx), mm(cy), 0), mm(BOLT_DIA) / 2)
    profs3 = adsk.core.ObjectCollection.create()
    for i in range(sk3.profiles.count):
        profs3.add(sk3.profiles.item(i))
    cut_in = extrudes.createInput(
        profs3, adsk.fusion.FeatureOperations.CutFeatureOperation)
    cut_in.setSymmetricExtent(adsk.core.ValueInput.createByReal(8.0), True)
    extrudes.add(cut_in)

    # --- Senktaschen (offen nach oben durch den Kegel) ---
    plane_in = root.constructionPlanes.createInput()
    plane_in.setByOffset(root.xYConstructionPlane,
                         adsk.core.ValueInput.createByReal(s * mm(10.5)))
    pocket_plane = root.constructionPlanes.add(plane_in)
    sk4 = root.sketches.add(pocket_plane)
    sk4.name = "bolt_pockets"
    for cx, cy in centers:
        pt = sk4.modelToSketchSpace(
            adsk.core.Point3D.create(mm(cx), mm(cy), s * mm(10.5)))
        sk4.sketchCurves.sketchCircles.addByCenterRadius(pt, mm(POCKET_DIA) / 2)
    profs4 = adsk.core.ObjectCollection.create()
    for i in range(sk4.profiles.count):
        profs4.add(sk4.profiles.item(i))
    cut_in2 = extrudes.createInput(
        profs4, adsk.fusion.FeatureOperations.CutFeatureOperation)
    cut_in2.setSymmetricExtent(adsk.core.ValueInput.createByReal(mm(11.0)), True)
    extrudes.add(cut_in2)

    # --- Kabeldurchlass unten ---
    sk5 = root.sketches.add(root.xZConstructionPlane)
    sk5.name = "cable_slot"
    lines5 = sk5.sketchCurves.sketchLines
    slot_pts = [(SLOT_X0, 0.0), (SLOT_X1, 0.0),
                (SLOT_X1, SLOT_H), (SLOT_X0, SLOT_H)]
    for i in range(len(slot_pts)):
        x0, z0 = slot_pts[i]
        x1, z1 = slot_pts[(i + 1) % len(slot_pts)]
        lines5.addByTwoPoints(
            adsk.core.Point3D.create(mm(x0), mm(z0), 0),
            adsk.core.Point3D.create(mm(x1), mm(z1), 0))
    slot_in = extrudes.createInput(
        sk5.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
    slot_in.setSymmetricExtent(adsk.core.ValueInput.createByReal(mm(SLOT_W)), True)
    extrudes.add(slot_in)

    body = root.bRepBodies.item(0)
    body.name = "guard_d5065_louvers"
    bb = body.boundingBox
    print(f"volume_cm3: {body.volume:.1f}")
    print(f"bbox_mm: x {bb.minPoint.x*10:.1f}..{bb.maxPoint.x*10:.1f}, "
          f"y {bb.minPoint.y*10:.1f}..{bb.maxPoint.y*10:.1f}, "
          f"z {bb.minPoint.z*10:.1f}..{bb.maxPoint.z*10:.1f}")

    # --- Export ---
    export_mgr = design.exportManager
    stl_path = EXPORT_DIR + r"\asa_outrunner_guard_d5065_louvers.stl"
    stl_opts = export_mgr.createSTLExportOptions(root, stl_path)
    stl_opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
    export_mgr.execute(stl_opts)
    step_path = EXPORT_DIR + r"\asa_outrunner_guard_d5065_louvers.step"
    step_opts = export_mgr.createSTEPExportOptions(step_path, root)
    export_mgr.execute(step_opts)
    print(f"exported: {stl_path}")
    print(f"exported: {step_path}")
