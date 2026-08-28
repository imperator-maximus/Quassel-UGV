"""Splitterdreiecke aus binaeren STL-Dateien entfernen.

Warum das noetig ist: Fusion trianguliert grosse ebene Flaechen mit Loechern -
etwa den Wannenboden mit seinen drei Entwaesserungsschlitzen - mit einigen
extrem schmalen Dreiecken. Beim Wannenboden sind das Kanten bis 92 mm Laenge
bei 0,0002 mm Hoehe. Geometrisch liegen sie flach in ihrer Ebene und aendern
nichts an der Form, im Slicer erscheinen sie aber als Faecher von Spitzen
quer durch das Bauteil.

An den Exporteinstellungen laesst sich das nicht abstellen: eine Begrenzung
der Kantenlaenge laesst Fusion bei diesen Flaechen unbeeindruckt, und eine
Begrenzung des Seitenverhaeltnisses zwingt eine gleichmaessige Feinvernetzung
des ganzen Teils - aus 25.000 Dreiecken werden dann 2,4 Millionen.

Deshalb hier nachtraeglich ein Kantenkollaps: Bei jedem Splitter werden seine
zwei naechstliegenden Eckpunkte im ganzen Netz zu einem verschmolzen. Das
Dreieck faellt damit in sich zusammen und wird entfernt, alle Nachbarn
bleiben verbunden - das Netz bleibt geschlossen. Die Punkte liegen dabei
Bruchteile eines Mikrometers auseinander, die Form aendert sich also nicht
messbar.

Aufruf:  python cad/clean_stl.py cad/asa_*.stl
"""

import math
import struct
import sys

WELD = 1.0e-4          # mm, Punkte darunter gelten als derselbe
MIN_HEIGHT = 0.005     # mm, flacher gilt als Splitter


def read_stl(path):
    with open(path, "rb") as f:
        header = f.read(80)
        count = struct.unpack("<I", f.read(4))[0]
        tris = [struct.unpack("<12fH", f.read(50)) for _ in range(count)]
    return header, tris


def write_stl(path, header, faces, verts):
    with open(path, "wb") as f:
        f.write(header)
        f.write(struct.pack("<I", len(faces)))
        for n, tri in faces:
            vals = list(n)
            for i in tri:
                vals.extend(verts[i])
            f.write(struct.pack("<12fH", *vals, 0))


def build(tris):
    """Netz auf Indexbasis bringen, dabei doppelte Punkte verschweissen."""
    index = {}
    verts = []
    faces = []
    for rec in tris:
        tri = []
        for v in (rec[3:6], rec[6:9], rec[9:12]):
            key = tuple(round(c / WELD) for c in v)
            if key not in index:
                index[key] = len(verts)
                verts.append(tuple(v))
            tri.append(index[key])
        faces.append((rec[0:3], tri))
    return faces, verts


def height(verts, tri):
    a, b, c = (verts[i] for i in tri)
    edges = [(math.dist(a, b), 0, 1), (math.dist(b, c), 1, 2),
             (math.dist(c, a), 2, 0)]
    longest = max(e[0] for e in edges)
    if longest == 0.0:
        return 0.0, edges
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    cr = [u[1] * v[2] - u[2] * v[1],
          u[2] * v[0] - u[0] * v[2],
          u[0] * v[1] - u[1] * v[0]]
    area = 0.5 * math.sqrt(sum(x * x for x in cr))
    return 2.0 * area / longest, edges


def clean(path):
    header, tris = read_stl(path)
    faces, verts = build(tris)

    merge = list(range(len(verts)))

    def find(i):
        while merge[i] != i:
            merge[i] = merge[merge[i]]
            i = merge[i]
        return i

    collapsed = 0
    for _, tri in faces:
        t = [find(i) for i in tri]
        if len(set(t)) < 3:
            continue
        h, edges = height(verts, t)
        if h >= MIN_HEIGHT:
            continue
        # kuerzeste Kante des Splitters zusammenziehen
        _, i, j = min(edges, key=lambda e: e[0])
        a, b = find(t[i]), find(t[j])
        if a != b:
            merge[b] = a
            collapsed += 1

    out = []
    for n, tri in faces:
        t = [find(i) for i in tri]
        if len(set(t)) == 3:
            out.append((n, t))

    write_stl(path, header, out, verts)
    return len(tris), len(tris) - len(out), collapsed


if __name__ == "__main__":
    for path in sys.argv[1:]:
        total, removed, collapsed = clean(path)
        print("%-46s %6d Dreiecke, %3d Kanten kollabiert, %3d entfernt"
              % (path, total, collapsed, removed))
