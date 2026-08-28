# Fusion360-Skript: Snap-Schienen an "Halterung Batterie v4" nachruesten.
# Wird ueber den Fusion-MCP-Server ausgefuehrt (featureType=script).
#
# ACHTUNG - Ausnahme vom sonst geltenden Workflow: dieses Skript baut NICHT in
# ein frisches Dokument, sondern aendert das AKTIVE. Es muss "Halterung Batterie
# v4" aktiv und editierbar sein. Rueckgaengig: Fusion-Undo, das Dokument wird
# vom Skript nicht gespeichert.
#
# Was es tut, an jedem der drei 30x30x3-Stege:
#   1. loescht die bisherige 2-mm-Rippe (Koerper2 / Koerper5 / Koerper10)
#   2. setzt Anschlagsockel (30 x 4 x 5, Z 3..8) auf den Flansch
#   3. setzt die Schwalbenschwanz-Schiene darauf (Z 8..30, Wurzel 11 -> Spitze 16)
#   4. schneidet Einfuehrfase oben und Rastnut hinein
# Geometrie identisch zu cad/fusion_snap_interface.py - beide Dateien muessen
# bei Aenderungen zusammen angefasst werden.
#
# Die Rippen werden ueber ihre Bounding-Box gefunden, nicht ueber den Namen:
# robuster, und dient zugleich als Sicherung. Passt etwas nicht, bricht das
# Skript ab, bevor es irgendetwas aendert.
#
# Hinweis: die drei Rippen haengen ueber Spiegeln1 und die Kopier-Operation
# zusammen - das Loeschen der ersten entfernt die beiden anderen gleich mit.
# Deshalb ist "war schon entfernt" hier kein Fehler.
#
# Die Flansche haben KEINE Schraubloecher. Die zwei Ø4-Kreise pro Lasche sind
# R2-Eckverrundungen (liegen 2 mm von beiden Aussenkanten). Befestigt wird die
# Halterung ueber zwei Ø8,2 in der Grundplatte bei Y = +/-90.
#
# DRUCKREGEL: Halterung flach aufs Bett -> Schiebeachse senkrecht. Schiene und
# Sockel sind Prismen in Z, null Ueberhang, keine Stuetzen.
#
# Masse in mm (Fusion-API rechnet intern in cm -> mm()-Helper).

import adsk.core
import adsk.fusion

# Praefix statt vollem Namen: Fusion zaehlt beim Speichern die Version hoch.
DOC_PREFIX = "Halterung Batterie"

# --- Schiene, identisch zu fusion_snap_interface.py ---
WALL_W = 30.0
RAIL_W_ROOT = 11.0
RAIL_W_TIP = 16.0
RAIL_H = 4.0
RAIL_Z0 = 8.0
RAIL_Z1 = 30.0
STOP_Z0 = 3.0
STOP_Z1 = 8.0
DET_Z0 = 22.2
DET_Z1 = 26.8
DET_DEPTH = 1.2
DET_W = 7.0

# --- Stationen: (Name, Rippen-BBox, Schnittebene, Offset, Abbildung (u,v)->(x,y)) ---
# u = seitlich ab Stegmitte, v = nach aussen ab Steg-Aussenflaeche
STATIONS = [
    ("rail_y_plus", (-26.37, -24.37, 99.50, 109.50, 0.0, 30.0),
     "yz", -25.82, lambda u, v: (-25.82 + u, 100.5 + v)),
    ("rail_y_minus", (-26.37, -24.37, -109.50, -99.50, 0.0, 30.0),
     "yz", -25.82, lambda u, v: (-25.82 + u, -100.5 - v)),
    ("rail_x_plus", (9.18, 19.18, -0.96, 1.04, 0.0, 30.0),
     "xz", 0.5, lambda u, v: (10.18 + v, 0.5 + u)),
]

EXPORT_DIR = r"C:\Users\mausz\Documents\PlatformIO\Projects\quassel-ugv\cad"


def mm(v):
    return v / 10.0


def bbox_mm(body):
    bb = body.boundingBox
    return (bb.minPoint.x * 10, bb.maxPoint.x * 10,
            bb.minPoint.y * 10, bb.maxPoint.y * 10,
            bb.minPoint.z * 10, bb.maxPoint.z * 10)


def find_by_bbox(root, box, tol=0.05):
    hits = []
    for b in root.bRepBodies:
        if all(abs(a - c) < tol for a, c in zip(bbox_mm(b), box)):
            hits.append(b)
    return hits


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


def extrude(root, prof, dist, op, participants=None, symmetric=False):
    """dist bei symmetric=True ist die GESAMTlaenge (isFullLength)."""
    exts = root.features.extrudeFeatures
    inp = exts.createInput(prof, op)
    if symmetric:
        inp.setSymmetricExtent(adsk.core.ValueInput.createByReal(mm(dist)), True)
    else:
        inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm(dist)))
    if participants:
        inp.participantBodies = participants
    return exts.add(inp)


def run(_context):
    app = adsk.core.Application.get()
    doc = app.activeDocument
    if not doc.name.startswith(DOC_PREFIX):
        raise RuntimeError("Aktives Dokument ist '%s', erwartet '%s*'. Abbruch."
                           % (doc.name, DOC_PREFIX))
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    design.timeline.moveToEnd()

    # --- Sicherungen, bevor irgendetwas geaendert wird ---
    for b in root.bRepBodies:
        if b.name.startswith("rail_"):
            raise RuntimeError("Koerper '%s' existiert schon - Skript lief bereits. "
                               "Abbruch." % b.name)
    for name, box, _, _, _ in STATIONS:
        hits = find_by_bbox(root, box)
        if len(hits) > 1:
            raise RuntimeError("Fuer %s passen %d Koerper auf die Rippen-Bounding-Box, "
                               "erwartet hoechstens 1. Abbruch." % (name, len(hits)))
    print("Sicherungen ok.")

    # Jede Rippe direkt vor dem Loeschen frisch suchen: deleteMe() macht die
    # Referenzen auf alle anderen Koerper ungueltig.
    for name, box, _, _, _ in STATIONS:
        hits = find_by_bbox(root, box)
        if not hits:
            print("Rippe fuer %s war schon entfernt" % name)
            continue
        rname = hits[0].name
        if not hits[0].deleteMe():
            raise RuntimeError("Rippe '%s' liess sich nicht loeschen. Abbruch." % rname)
        print("geloescht:", rname)

    xy = root.xYConstructionPlane
    yz = root.yZConstructionPlane
    xz = root.xZConstructionPlane
    new_body = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    join = adsk.fusion.FeatureOperations.JoinFeatureOperation
    cut = adsk.fusion.FeatureOperations.CutFeatureOperation

    hw = WALL_W / 2.0
    rr, rt = RAIL_W_ROOT / 2.0, RAIL_W_TIP / 2.0
    pl_stop = offset_plane(root, xy, STOP_Z0, "z")
    pl_rail = offset_plane(root, xy, RAIL_Z0, "z")

    for name, _, base_name, base_off, m in STATIONS:
        # Anschlagsockel
        sk = root.sketches.add(pl_stop)
        sk.name = name + "_sockel"
        poly(sk, [m(-hw, 0.0) + (STOP_Z0,), m(hw, 0.0) + (STOP_Z0,),
                  m(hw, RAIL_H) + (STOP_Z0,), m(-hw, RAIL_H) + (STOP_Z0,)])
        body = extrude(root, sk.profiles.item(0), STOP_Z1 - STOP_Z0, new_body).bodies.item(0)
        body.name = name
        parts = [body]

        # Schwalbenschwanz
        sk = root.sketches.add(pl_rail)
        sk.name = name + "_schiene"
        poly(sk, [m(-rr, 0.0) + (RAIL_Z0,), m(rr, 0.0) + (RAIL_Z0,),
                  m(rt, RAIL_H) + (RAIL_Z0,), m(-rt, RAIL_H) + (RAIL_Z0,)])
        extrude(root, sk.profiles.item(0), RAIL_Z1 - RAIL_Z0, join, parts)

        # Schnittebene fuer Fase und Rastnut (enthaelt v und z)
        base = yz if base_name == "yz" else xz
        comp = "x" if base_name == "yz" else "y"
        pl_cut = offset_plane(root, base, base_off, comp)

        # Einfuehrfase oben, 45 Grad
        sk = root.sketches.add(pl_cut)
        sk.name = name + "_fase"
        poly(sk, [m(0.0, 1.5) + (RAIL_Z1 + 1.0,), m(0.0, 5.0) + (RAIL_Z1 + 1.0,),
                  m(0.0, 5.0) + (RAIL_Z1 - 2.5,)])
        extrude(root, sk.profiles.item(0), 2 * RAIL_W_TIP, cut, parts, symmetric=True)

        # Rastnut, beide Flanken 45 Grad
        y_in = RAIL_H - DET_DEPTH
        over = 5.0 - RAIL_H
        sk = root.sketches.add(pl_cut)
        sk.name = name + "_rastnut"
        poly(sk, [m(0.0, 5.0) + (DET_Z0 - over,), m(0.0, y_in) + (DET_Z0 + DET_DEPTH,),
                  m(0.0, y_in) + (DET_Z1 - DET_DEPTH,), m(0.0, 5.0) + (DET_Z1 + over,)])
        extrude(root, sk.profiles.item(0), DET_W, cut, parts, symmetric=True)

        print("%-14s vol=%6.2f cm3  x %7.2f..%7.2f  y %8.2f..%8.2f  z %5.2f..%5.2f"
              % ((body.name, body.volume) + bbox_mm(body)))

    # --- Kontrolle: sitzt an jeder Station Material da, wo die Schiene hin soll? ---
    def solid_any(x, y, z):
        p = adsk.core.Point3D.create(x / 10.0, y / 10.0, z / 10.0)
        for b in root.bRepBodies:
            if b.pointContainment(p) == adsk.fusion.PointContainment.PointInsidePointContainment:
                return True
        return False

    bad = 0
    for name, _, _, _, m in STATIONS:
        for label, u, v, z, expect in [
            ("Schiene massiv", 0.0, 2.0, 15.0, True),
            ("Rastnut frei", 0.0, 3.4, 24.5, False),
            ("Sockel massiv", 0.0, 2.0, 5.0, True),
            ("neben Schiene frei", 13.0, 2.0, 15.0, False),
            ("Hinterschnitt frei", 7.0, 1.0, 15.0, False),
            ("Spitze breit", 7.0, 3.5, 15.0, True),
            ("Flansch traegt Sockel", 0.0, 2.0, 1.5, True),
            ("Rippe entfernt", 0.0, 7.0, 15.0, False),
        ]:
            x, y = m(u, v)
            got = solid_any(x, y, z)
            ok = (got == expect)
            bad += 0 if ok else 1
            if not ok:
                print("%s / %-18s soll=%-5s ist=%-5s <<< ABWEICHUNG"
                      % (name, label, expect, got))
    print("Kontrollpunkte: %d Abweichungen" % bad)
    print("Koerper jetzt:", root.bRepBodies.count)

    export_mgr = design.exportManager
    stl_path = EXPORT_DIR + r"\asa_halterung_batterie_snap.stl"
    opts = export_mgr.createSTLExportOptions(root, stl_path)
    opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
    export_mgr.execute(opts)
    print("exported: " + stl_path)
    step_path = EXPORT_DIR + r"\halterung_batterie_snap.step"
    export_mgr.execute(export_mgr.createSTEPExportOptions(step_path, root))
    print("exported: " + step_path)
    print("Dokument NICHT gespeichert - pruefen, dann selbst speichern.")
