# Fusion360-Skript: Anbauteile in das Hauptdokument "Halterung Batterie"
# einsetzen, jeweils aufgesteckt auf eine der drei Snap-Schienen.
# Wird ueber den Fusion-MCP-Server ausgefuehrt (featureType=script).
#
# ACHTUNG - aendert das AKTIVE Dokument. Voraussetzung: "Halterung Batterie"
# ist aktiv, editierbar, und cad/fusion_snap_rail_halterung.py lief bereits
# (die drei Koerper rail_* muessen da sein). Rueckgaengig: Fusion-Undo.
#
# Die Geometrie kommt aus den Teiledateien selbst: das Skript fuehrt sie aus
# und ruft deren build(comp, body_name) auf. Damit gibt es genau EINE Quelle
# pro Teil, Einzelteil und Baugruppe koennen nicht auseinanderlaufen.
#
# Jedes Teil wird in seinen lokalen Koordinaten am Ursprung gebaut und danach
# per Move-Feature an die Station gesetzt. Lokales System: X = seitlich ab
# Stegmitte, Y = nach aussen ab Steg-Aussenflaeche, Z = Hoehe. Rechtshaendig,
# deshalb reicht eine Drehung um Z und es entsteht keine Spiegelung.
#
# Kein Unterbauteil: "Halterung Batterie" ist ein Bauteil-Dokument und darf nur
# eine Komponente enthalten. Die Anbauteile kommen daher als eigene Koerper
# neben die zehn vorhandenen - zum Drucken einzeln als STL exportieren.
#
# Das Skript ist wiederholbar: es raeumt einen frueheren Lauf selbst weg. Alle
# Skizzen bekommen dafuer das Praefix des Teils (sh_, jt_), unabhaengig davon
# wie die Teiledatei sie benennt.
#
# Masse in mm (Fusion-API rechnet intern in cm -> mm()-Helper).

import io
import math
import os
import adsk.core
import adsk.fusion

# Praefix statt vollem Namen: Fusion zaehlt beim Speichern die Version hoch
# (v4 -> v5 -> ...), ein fester Name wuerde jedes Mal fehlschlagen.
DOC_PREFIX = "Halterung Batterie"

CAD_DIR = r"C:\Users\mausz\Documents\PlatformIO\Projects\quassel-ugv\cad"

# (Praefix, Koerpername, Teiledatei, Station)
PARTS = [
    ("sh", "shunt_halter",   "fusion_shunt_halter.py",   "rail_x_plus"),
    ("jt", "junctek_halter", "fusion_junctek_halter.py", "rail_y_plus"),
]

# Station -> (Drehung um Z in Grad, Verschiebung x, Verschiebung y)
# Die Verschiebung zeigt auf die Mitte der Steg-Aussenflaeche.
STATION_PLACEMENT = {
    "rail_y_plus":  (0.0,   -25.82,  100.5),
    "rail_y_minus": (180.0, -25.82, -100.5),
    "rail_x_plus":  (-90.0,  10.18,    0.5),
}

PROTECTED = ("rail_", "Skizze1")


def mm(v):
    return v / 10.0


def load_part(filename):
    """Teiledatei ausfuehren und ihr build() zurueckgeben. run() wird NICHT
    aufgerufen - das wuerde ein neues Dokument anlegen."""
    path = os.path.join(CAD_DIR, filename)
    with io.open(path, encoding="utf-8") as f:
        src = f.read()
    g = {"__name__": "part_" + filename.replace(".py", "")}
    exec(compile(src, path, "exec"), g)
    if "build" not in g:
        raise RuntimeError("%s hat keine build()-Funktion." % filename)
    return g["build"]


def cleanup(design, prefixes):
    """Alles ab dem ersten Eintrag mit Teile-Praefix loeschen. Die zugehoerige
    Ebene steht davor, die muss mit weg."""
    tl = design.timeline
    first = -1
    for i in range(tl.count):
        if any(tl.item(i).name.startswith(p + "_") for p in prefixes):
            first = i
            break
    if first < 0:
        return 0
    start = first - 1 if tl.item(first - 1).name.startswith("Ebene") else first
    doomed = set()
    for i in range(start, tl.count):
        n = tl.item(i).name
        for guard in PROTECTED:
            if n.startswith(guard):
                raise RuntimeError("Aufraeumbereich enthaelt '%s'. Abbruch." % n)
        doomed.add(n)

    removed, tries = 0, 0
    while tries < 500:
        tries += 1
        idx = -1
        for i in range(tl.count - 1, -1, -1):
            if tl.item(i).name in doomed:
                idx = i
                break
        if idx < 0:
            break
        nm = tl.item(idx).name
        ent = tl.item(idx).entity
        if ent and ent.deleteMe():
            removed += 1
        else:
            doomed.discard(nm)          # nicht loeschbar, nicht endlos versuchen
    return removed


def place(root, prefix, body_name, build_fn, station):
    """Teil am Ursprung bauen, Skizzen praefixen, an die Station schieben."""
    n0 = root.sketches.count
    part = build_fn(root, body_name)
    for i in range(n0, root.sketches.count):
        sk = root.sketches.item(i)
        if not sk.name.startswith(prefix + "_"):
            sk.name = "%s_%s" % (prefix, sk.name)

    deg, tx, ty = STATION_PLACEMENT[station]
    m = adsk.core.Matrix3D.create()
    m.setToRotation(math.radians(deg), adsk.core.Vector3D.create(0, 0, 1),
                    adsk.core.Point3D.create(0, 0, 0))
    m.translation = adsk.core.Vector3D.create(mm(tx), mm(ty), 0.0)

    coll = adsk.core.ObjectCollection.create()
    coll.add(part)
    moves = root.features.moveFeatures
    if hasattr(moves, "createInput2"):
        mv_in = moves.createInput2(coll)
        mv_in.defineAsFreeMove(m)
    else:
        mv_in = moves.createInput(coll, m)
    moves.add(mv_in)
    return part


def run(_context):
    app = adsk.core.Application.get()
    doc = app.activeDocument
    if not doc.name.startswith(DOC_PREFIX):
        raise RuntimeError("Aktives Dokument ist '%s', erwartet '%s...'. Abbruch."
                           % (doc.name, DOC_PREFIX))
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    design.timeline.moveToEnd()

    rails = [b.name for b in root.bRepBodies if b.name.startswith("rail_")]
    for _, _, _, station in PARTS:
        if station not in STATION_PLACEMENT:
            raise RuntimeError("Unbekannte Station '%s'." % station)
        if station not in rails:
            raise RuntimeError("Schiene '%s' fehlt (vorhanden: %s)."
                               % (station, rails or "keine"))
    used = [p[3] for p in PARTS]
    if len(set(used)) != len(used):
        raise RuntimeError("Zwei Teile auf derselben Station: %s" % used)
    print("Schienen: %s | Stationen belegt: %s" % (", ".join(rails), ", ".join(used)))

    n = cleanup(design, [p[0] for p in PARTS])
    print("aufgeraeumt: %d Chronikeintraege" % n)

    placed = []
    for prefix, body_name, filename, station in PARTS:
        build_fn = load_part(filename)
        part = place(root, prefix, body_name, build_fn, station)
        placed.append(part)
        bb = part.boundingBox
        print("%-15s %-13s vol=%6.2f cm3  x %7.2f..%7.2f  y %8.2f..%8.2f  z %6.2f..%6.2f"
              % (body_name, station, part.volume,
                 bb.minPoint.x * 10, bb.maxPoint.x * 10,
                 bb.minPoint.y * 10, bb.maxPoint.y * 10,
                 bb.minPoint.z * 10, bb.maxPoint.z * 10))

    # --- Kontrolle: sitzen die Anbauteile beruehrungsfrei? ---
    names = set(p.name for p in placed)
    bl = list(root.bRepBodies)
    hits = 0
    for i in range(len(bl)):
        for j in range(i + 1, len(bl)):
            if not (bl[i].name in names or bl[j].name in names):
                continue                # Ueberlappungen des Originals ignorieren
            col = adsk.core.ObjectCollection.create()
            col.add(bl[i])
            col.add(bl[j])
            ipt = design.createInterferenceInput(col)
            ipt.areCoincidentFacesIncluded = False
            res = design.analyzeInterference(ipt)
            for k in range(res.count):
                hits += 1
                print("  VERSCHNEIDUNG %s <-> %s: %.4f mm3"
                      % (bl[i].name, bl[j].name,
                         res.item(k).interferenceBody.volume * 1000))
    print("Verschneidungen mit Anbauteilen:", hits)
    print("Koerper:", root.bRepBodies.count, "| Chronik:", design.timeline.count)

    step_path = os.path.join(CAD_DIR, "halterung_baugruppe.step")
    design.exportManager.execute(
        design.exportManager.createSTEPExportOptions(step_path, root))
    print("exported: " + step_path)
    print("Dokument NICHT gespeichert - pruefen, dann selbst speichern.")
