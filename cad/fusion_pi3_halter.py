# Fusion360-Skript: Halterung fuer Raspberry Pi 3 Model B
# Drittes Anbauteil an der Snap-Schnittstelle der Batteriehalterung.
# Wird ueber den Fusion-MCP-Server ausgefuehrt (featureType=script).
#
# Ein Stueck: Snap-Adapter (identisch zu fusion_snap_interface.py) + Leiterrahmen
# als Auflagedeck. Kein Gehaeuse - der Pi sitzt bereits im Top-Gehaeuse, hier
# geht es nur ums Halten.
#
# Pi-Daten (mechanische Spezifikation Pi 3 Model B): Platine 85 x 56 mm,
# 4x Ø2,75 im Raster 58 x 49 mm, jeweils 3,5 mm von den Plattenkanten.
# ACHTUNG: das Lochbild sitzt NICHT mittig auf der Platine - in Laengsrichtung
# bleiben 3,5 mm auf der microSD-Seite und 23,5 mm auf der USB/LAN-Seite stehen.
# Hier ist das LOCHBILD auf X=0 zentriert, nicht die Platine. Damit haengt die
# Last symmetrisch am Adapter, und die USB-Seite kragt 17,5 mm ueber den Rahmen
# hinaus - so wie bei jedem handelsueblichen Pi-Traeger.
#
# Ausrichtung (Vorgabe User): die Strom/HDMI-Laengsseite zeigt zur Schiene.
# Der Adapterklotz steht bis Z=30 vor genau dieser Kante, die Zuglasche bis
# Z=34,5. Freigang schafft allein der Versatz: BOARD_Y0 = 35,5 mm ab der
# Steg-Aussenflaeche, also 28 mm vor der Adapterrueckwand. Soviel Platz
# brauchen Stecker und Kabelbogen fuer Strom, HDMI und Klinke, und soviel
# braucht die Hand an der Zuglasche. BOARD_Y0 ist die Zahl zum Nachstellen,
# aber nach unten ist bei ~25 mm Schluss, sonst stoesst der Stecker an.
#
# Abstandshalter (User): Messing, 10 mm Bauhoehe, unten M3 AUSSENgewinde,
# 5-6 mm lang. Entscheidend fuer die Befestigung: die Halter sind bereits am
# Pi festgeschraubt und lassen sich nicht mehr drehen, ohne dass sie sich dort
# loesen. Damit scheidet JEDES feste Gewinde im Druckteil aus - kein Insert,
# kein Kunststoffgewinde. Das drehende Teil muss die Mutter sein.
#
# Lochprofil im Boss, von oben:
#   Z=16..14  Skin 2,0 mm mit Ø3,4 - hier kommt nur das Gewinde durch
#   Z=14..8   Ø10 Mutternkammer, 6 mm tief, nach unten offen
# 2,0 mm Skin + 2,4 mm Mutternhoehe = 4,4 mm, passt also auch in ein knappes
# 5-mm-Gewinde. Die Kammer ist bewusst rund und ohne Sechskant: der Halter
# darf nicht gegengehalten werden, die Mutter wird mit der Nuss angezogen.
# Deshalb steht der Abstandshalter auch direkt auf der Deckflaeche - keine
# Aufnahmetasche, die braucht der Messingkoerper nicht.
# Der Boss ist dafuer von 12 auf 16 mm verbreitert, sonst blieben neben der
# Ø10-Kammer nur 1 mm Wand stehen.
#
# DRUCKREGEL wie bei allen Anbauteilen: Schiebeachse = Modell-Z senkrecht aufs
# Bett. Der Rahmen ist deshalb kein liegendes Blech, sondern ein Gitter aus
# stehenden Waenden, das vom Bett (Z=8) auf die Auflageebene (Z=16) hochwaechst
# - null Ueberhang, keine Stuetzen. Die einzigen Schraegen sind die zwei
# 45-Grad-Konsolen an der Adapterwand. ASA.
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

# --- Raspberry Pi 3 Model B (mechanische Spezifikation) ---
PI_L = 85.0            # Laengsseite, liegt in X
PI_W = 56.0            # Querseite, liegt in Y
PI_HOLE_DX = 58.0
PI_HOLE_DY = 49.0
PI_EDGE = 3.5          # Lochmitte zur Plattenkante

# --- Lage des Pi ---
BOARD_Y0 = 35.5        # Strom/HDMI-Kante der Platine, ab Steg-Aussenflaeche
STANDOFF_H = 10.0      # Messing-Abstandshalter, nur fuer die Kontrollausgabe

HOLE_X = PI_HOLE_DX / 2.0            # 29.0, Lochbild auf X=0 zentriert
HOLE_Y1 = BOARD_Y0 + PI_EDGE         # 39.0, Lochreihe schienenseitig
HOLE_Y2 = HOLE_Y1 + PI_HOLE_DY       # 88.0, Lochreihe aussen

# --- Leiterrahmen ---
DECK_Z0 = 8.0          # Bettebene, buendig mit der Adapterunterkante
DECK_Z1 = 16.0         # Auflageebene der Abstandshalter (8 mm Deck)
WALL_T = 6.0           # Wandstaerke Holme und Rungen
BOSS = 16.0            # Kantenlaenge der Bosse -> 3 mm Wand neben der Kammer
ROOT_Y0 = AD_WALL_Y    # Wurzelrunge bindet an die Adapterrueckwand an
ROOT_Y1 = ROOT_Y0 + WALL_T
RAIL_Y1 = HOLE_Y2 + BOSS / 2.0       # 96.0, hinteres Ende der Holme
RUNG_X = HOLE_X + WALL_T / 2.0       # 32.0, Rungen bis Holm-Aussenkante
FRAME_X = HOLE_X + BOSS / 2.0        # 37.0, Aussenkante der Bosse

# Adaptermitte auf der Vorderkante. 0 waere mittig; auf Wunsch ans +x-Ende
# gerueckt, der Pi haengt damit komplett auf der -x-Seite neben der Schiene.
# Der Adapter ist AD_W=26 breit, bei +24 reicht er also von +11 bis +37 und
# schliesst aussen buendig mit dem Rahmen ab. Deshalb laeuft die Wurzelrunge
# jetzt ueber die volle Breite (+/-FRAME_X statt +/-RUNG_X): sonst stuende die
# aeussere Konsole ueber x 32..37 in der Luft und Fusion wuerde sie beim
# Join verwerfen.
ADAPTER_X = 24.0

# --- Konsolen an der Adapterwand ---
GUSSET_X0 = 8.0        # neben Zunge (+/-4) und Freischnitt (bis +/-5,5)
GUSSET_X1 = 13.0
GUSSET_Y1 = ROOT_Y1    # sitzt vollstaendig auf der Wurzelrunge auf
GUSSET_Z1 = AD_Z1      # 30, Oberkante an der Adapterwand

SKIN_T = 2.0           # tragende Decke ueber der Mutternkammer
NUT_BORE_D = 10.0      # Mutternkammer, nach unten offen
M3_CLEAR_D = 3.4       # Gewindedurchgang durch die Decke

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


def rect_xy(sk, x0, x1, y0, y1, z):
    poly(sk, [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)])


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


def build(comp, body_name="pi3_halter"):
    """Baut den Halter in lokalen Koordinaten. Rueckgabe: der Koerper.

    Gleiche Signatur wie build() in fusion_shunt_halter.py, damit ein
    Montageskript ihn in Fahrzeugkoordinaten einsetzen kann."""
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
    pl_ax = yz if abs(ADAPTER_X) < 1e-9 else offset_plane(comp, yz, ADAPTER_X, "x")

    # --- Adapterblock ---
    sk = comp.sketches.add(pl_z8)
    sk.name = "adapter_block"
    rect_xy(sk, ADAPTER_X - ahw, ADAPTER_X + ahw, AD_Y0, AD_WALL_Y, RAIL_Z0)
    part = extrude(comp, sk.profiles.item(0), AD_Z1 - RAIL_Z0, new_body).bodies.item(0)
    part.name = body_name
    parts = [part]

    # --- Schwalbenschwanznut ---
    sk = comp.sketches.add(pl_z8)
    sk.name = "adapter_nut"
    ax = ADAPTER_X
    poly(sk, [(ax - (fr - slope), -1.0, RAIL_Z0), (ax + (fr - slope), -1.0, RAIL_Z0),
              (ax + ft, fu, RAIL_Z0), (ax - ft, fu, RAIL_Z0)])
    extrude(comp, sk.profiles.item(0), AD_Z1 - RAIL_Z0, cut, parts)

    # --- Freischnitt der Federzunge ---
    thw, sr = TONGUE_W / 2.0, SLIT_W / 2.0
    y_mid = (AD_WALL_Y + RAIL_H) / 2.0
    pl_y = offset_plane(comp, xz, y_mid, "y")
    sk = comp.sketches.add(pl_y)
    sk.name = "adapter_freischnitt"
    for sx in (-1.0, 1.0):
        x0, x1 = ADAPTER_X + sx * thw, ADAPTER_X + sx * (thw + SLIT_W)
        poly(sk, [(min(x0, x1), y_mid, SLIT_Z0), (max(x0, x1), y_mid, SLIT_Z0),
                  (max(x0, x1), y_mid, AD_Z1 + 0.5), (min(x0, x1), y_mid, AD_Z1 + 0.5)])
        sk.sketchCurves.sketchCircles.addByCenterRadius(
            sk.modelToSketchSpace(adsk.core.Point3D.create(
                mm(ADAPTER_X + sx * (thw + sr)), mm(y_mid), mm(SLIT_Z0))), mm(sr))
    extrude(comp, all_profiles(sk), (AD_WALL_Y - RAIL_H) + 1.0, cut, parts, symmetric=True)

    # --- Zunge ausduennen (vor dem Rahmen, sonst kerbt der Schnitt die Rungen an) ---
    ty = fu + TONGUE_T
    sk = comp.sketches.add(pl_ax)
    sk.name = "adapter_zunge_duenn"
    poly(sk, [(ax, AD_WALL_Y + 0.5, TAPER_Z0), (ax, ty, TAPER_Z1),
              (ax, ty, AD_Z1 + 1.0), (ax, AD_WALL_Y + 0.5, AD_Z1 + 1.0)])
    extrude(comp, sk.profiles.item(0), TONGUE_W, cut, parts, symmetric=True)

    # --- Rastnase ---
    nose_base = fu + 0.5
    ramp = nose_base - NOSE_TIP_Y
    sk = comp.sketches.add(pl_ax)
    sk.name = "adapter_rastnase"
    poly(sk, [(ax, nose_base, NOSE_Z0 - 0.5), (ax, NOSE_TIP_Y, NOSE_Z0 - 0.5 + ramp),
              (ax, NOSE_TIP_Y, NOSE_Z1 + 0.5 - ramp), (ax, nose_base, NOSE_Z1 + 0.5)])
    extrude(comp, sk.profiles.item(0), NOSE_W, join, parts, symmetric=True)

    # --- Zuglasche (liegt ab Z=29 komplett ueber dem Deck, kein Freigang noetig) ---
    sk = comp.sketches.add(pl_ax)
    sk.name = "adapter_zuglasche"
    poly(sk, [(ax, fu, TAB_Z0), (ax, AD_WALL_Y, TAB_Z0),
              (ax, TAB_Y, TAB_Z0 + (TAB_Y - AD_WALL_Y)),
              (ax, TAB_Y, TAB_Z1), (ax, fu, TAB_Z1)])
    extrude(comp, sk.profiles.item(0), TONGUE_W, join, parts, symmetric=True)

    # --- Leiterrahmen: zwei Holme in Y, drei Rungen in X, vier Bosse ---
    # Jede Strebe bekommt ein EIGENES Sketch. Alle in ein Sketch zu legen und
    # mit all_profiles() zu extrudieren fuellt den Rahmen massiv aus: Fusion
    # zaehlt die Fenster ZWISCHEN den Streben ebenfalls als geschlossene
    # Profile. Kostete beim ersten Lauf 69 statt 32 cm3.
    # REIHENFOLGE ist wesentlich: ein Join-Extrude, das beim Anlegen nichts
    # beruehrt, wird von Fusion kommentarlos verworfen. Also erst die
    # Wurzelrunge (haengt an der Adapterrueckwand), dann die Holme (haengen an
    # der Wurzelrunge), dann die restlichen Rungen und zuletzt die Bosse.
    hw, bh = WALL_T / 2.0, BOSS / 2.0
    members = [("runge_wurzel", -FRAME_X, FRAME_X, ROOT_Y0, ROOT_Y1)]
    for sx in (-HOLE_X, HOLE_X):
        members.append(("holm_%+d" % int(sx), sx - hw, sx + hw, ROOT_Y0, RAIL_Y1))
    for i, yc in enumerate((HOLE_Y1, HOLE_Y2)):
        members.append(("runge_%d" % i, -RUNG_X, RUNG_X, yc - hw, yc + hw))
    for sx in (-HOLE_X, HOLE_X):
        for sy in (HOLE_Y1, HOLE_Y2):
            members.append(("boss_%+d_%d" % (int(sx), int(sy)),
                            sx - bh, sx + bh, sy - bh, sy + bh))
    for name, x0, x1, y0, y1 in members:
        sk = comp.sketches.add(pl_z8)
        sk.name = name
        rect_xy(sk, x0, x1, y0, y1, DECK_Z0)
        extrude(comp, sk.profiles.item(0), DECK_Z1 - DECK_Z0, join, parts)

    # --- 45-Grad-Konsolen von der Adapterwand auf die Wurzelrunge ---
    g_c = (GUSSET_X0 + GUSSET_X1) / 2.0
    for sx in (ADAPTER_X - g_c, ADAPTER_X + g_c):
        pl_g = offset_plane(comp, yz, sx, "x")
        sk = comp.sketches.add(pl_g)
        sk.name = "konsole_%+d" % int(sx)
        drop = GUSSET_Y1 - AD_WALL_Y
        poly(sk, [(sx, AD_WALL_Y, DECK_Z1), (sx, AD_WALL_Y, GUSSET_Z1),
                  (sx, GUSSET_Y1, GUSSET_Z1 - drop), (sx, GUSSET_Y1, DECK_Z1)])
        extrude(comp, sk.profiles.item(0), GUSSET_X1 - GUSSET_X0, join, parts,
                symmetric=True)

    # --- 4x Mutternkammer Ø10, von unten offen ---
    z_lo, z_hi = DECK_Z0 - 0.5, DECK_Z1 - SKIN_T
    z_c = (z_lo + z_hi) / 2.0
    pl_k = offset_plane(comp, xy, z_c, "z")
    sk = comp.sketches.add(pl_k)
    sk.name = "mutternkammern"
    for sx in (-HOLE_X, HOLE_X):
        for sy in (HOLE_Y1, HOLE_Y2):
            sk.sketchCurves.sketchCircles.addByCenterRadius(
                sk.modelToSketchSpace(adsk.core.Point3D.create(mm(sx), mm(sy), mm(z_c))),
                mm(NUT_BORE_D) / 2.0)
    extrude(comp, all_profiles(sk), z_hi - z_lo, cut, parts, symmetric=True)

    # --- 4x Ø3,4 durch die Decke ---
    z_d = DECK_Z1 - SKIN_T / 2.0
    pl_d = offset_plane(comp, xy, z_d, "z")
    sk = comp.sketches.add(pl_d)
    sk.name = "m3_durchgang"
    for sx in (-HOLE_X, HOLE_X):
        for sy in (HOLE_Y1, HOLE_Y2):
            sk.sketchCurves.sketchCircles.addByCenterRadius(
                sk.modelToSketchSpace(adsk.core.Point3D.create(mm(sx), mm(sy), mm(z_d))),
                mm(M3_CLEAR_D) / 2.0)
    extrude(comp, all_profiles(sk), SKIN_T + 1.0, cut, parts, symmetric=True)

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
    print("Auflageebene Z=%.1f, Platinenunterkante Z=%.1f (Abstandshalter %.1f mm), "
          "Adapteroberkante Z=%.1f" % (DECK_Z1, DECK_Z1 + STANDOFF_H, STANDOFF_H, AD_Z1))
    print("Platine belegt x %.1f..%.1f, y %.1f..%.1f" % (
        -HOLE_X - PI_EDGE, -HOLE_X - PI_EDGE + PI_L, BOARD_Y0, BOARD_Y0 + PI_W))

    def solid(x, y, z):
        p = adsk.core.Point3D.create(x / 10.0, y / 10.0, z / 10.0)
        return part.pointContainment(p) == adsk.fusion.PointContainment.PointInsidePointContainment

    checks = [
        ('Nut leer            (24, 2.0, 20)', 24.0, 2.0, 20.0, False),
        ('Zunge 1,6 mm        (24, 5.0, 20)', 24.0, 5.0, 20.0, True),
        ('hinter der Zunge    (24, 6.8, 20)', 24.0, 6.8, 20.0, False),
        ('Schlitz offen       (19.25, 5.0, 20)', 19.25, 5.0, 20.0, False),
        ('Adapterwand seitl.  (14, 6.0, 20)', 14.0, 6.0, 20.0, True),
        ('Adapter-Aussenkante (36, 6.0, 20)', 36.0, 6.0, 20.0, True),
        ('neben dem Adapter   (10, 6.0, 20)', 10.0, 6.0, 20.0, False),
        ('Rastnase            (24, 3.3, 24.5)', 24.0, 3.3, 24.5, True),
        ('Zuglasche           (24, 9.5, 32)', 24.0, 9.5, 32.0, True),
        ('Wurzelrunge         (0, 10.5, 14)', 0.0, 10.5, 14.0, True),
        ('Wurzelrunge aussen  (34, 10.5, 14)', 34.0, 10.5, 14.0, True),
        ('Rahmen offen        (0, 25, 14)', 0.0, 25.0, 14.0, False),
        ('Seitenholm          (29, 25, 14)', 29.0, 25.0, 14.0, True),
        ('neben dem Holm frei (15, 25, 14)', 15.0, 25.0, 14.0, False),
        ('Runge mittig        (0, 88, 14)', 0.0, 88.0, 14.0, True),
        ('Mutternkammer offen (31, 39, 12)', 31.0, 39.0, 12.0, False),
        ('Kammer unten offen  (29, 39, 9)', 29.0, 39.0, 9.0, False),
        ('Kammerwand steht    (35, 39, 12)', 35.0, 39.0, 12.0, True),
        ('ausserhalb Boss     (38, 39, 12)', 38.0, 39.0, 12.0, False),
        ('Decke ueber Kammer  (31, 39, 15)', 31.0, 39.0, 15.0, True),
        ('Gewindeloch offen   (29, 39, 15)', 29.0, 39.0, 15.0, False),
        ('Kammer bis 14       (29, 39, 13)', 29.0, 39.0, 13.0, False),
        ('Decke am 2. Boss    (31, 88, 15)', 31.0, 88.0, 15.0, True),
        ('ueber dem Deck frei (31, 88, 17)', 31.0, 88.0, 17.0, False),
        ('Konsolenfuss        (14, 10, 17)', 14.0, 10.0, 17.0, True),
        ('Konsole innen       (14, 10, 26)', 14.0, 10.0, 26.0, True),
        ('Konsole aussen      (34, 10, 26)', 34.0, 10.0, 26.0, True),
        ('ueber Konsole frei  (14, 10, 28)', 14.0, 10.0, 28.0, False),
        ('neben Konsole frei  (20, 10, 26)', 20.0, 10.0, 26.0, False),
        ('Platinenebene frei  (29, 60, 30)', 29.0, 60.0, 30.0, False),
        ('Hinterkante Rahmen  (29, 95, 14)', 29.0, 95.0, 14.0, True),
        ('hinter dem Rahmen   (29, 97, 14)', 29.0, 97.0, 14.0, False),
    ]
    bad = 0
    for name, x, y, z, expect in checks:
        got = solid(x, y, z)
        ok = (got == expect)
        bad += 0 if ok else 1
        print('%-38s soll=%-5s ist=%-5s %s' % (name, expect, got, 'OK' if ok else '<<< ABWEICHUNG'))
    print('Abweichungen:', bad)

    export_mgr = design.exportManager
    stl_path = EXPORT_DIR + r"\asa_pi3_halter.stl"
    opts = export_mgr.createSTLExportOptions(part, stl_path)
    opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
    export_mgr.execute(opts)
    print("exported: " + stl_path)
    step_path = EXPORT_DIR + r"\pi3_halter.step"
    export_mgr.execute(export_mgr.createSTEPExportOptions(step_path, root))
    print("exported: " + step_path)
