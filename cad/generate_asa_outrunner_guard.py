import math
from pathlib import Path


OUT = Path(__file__).with_name("asa_outrunner_guard_d5065_test.stl")


MOTOR_DIA = 50.0
RADIAL_CLEARANCE = 20.0
WALL = 3.0
MOTOR_BODY_HEIGHT = 65.0
TOP_CLEARANCE = 18.0
TOP_THICKNESS = 3.0
FLANGE_THICKNESS = 5.0
FLANGE_OVERHANG = 10.0
LOWER_SOLID_RING = 12.0
UPPER_SOLID_RING = 22.0
VENT_COUNT = 12
VENT_WIDTH = 13.0
BOLT_COUNT = 4
BOLT_HOLE_DIA = 5.2
BOLT_CIRCLE_DIA = MOTOR_DIA + 2 * RADIAL_CLEARANCE + 12.0

INNER_R = (MOTOR_DIA + 2 * RADIAL_CLEARANCE) / 2
OUTER_R = INNER_R + WALL
FLANGE_R = OUTER_R + FLANGE_OVERHANG
HEIGHT = MOTOR_BODY_HEIGHT + TOP_CLEARANCE + TOP_THICKNESS
VENT_Z0 = LOWER_SOLID_RING
VENT_Z1 = HEIGHT - TOP_THICKNESS - UPPER_SOLID_RING
VENT_HALF_ANGLE = (VENT_WIDTH / OUTER_R) / 2
BOLT_R = BOLT_HOLE_DIA / 2
BOLT_CIRCLE_R = BOLT_CIRCLE_DIA / 2
BOLT_CENTERS = [
    (
        BOLT_CIRCLE_R * math.cos(2 * math.pi * i / BOLT_COUNT + math.pi / 4),
        BOLT_CIRCLE_R * math.sin(2 * math.pi * i / BOLT_COUNT + math.pi / 4),
    )
    for i in range(BOLT_COUNT)
]

ANG_STEPS = 240
Z_STEPS = 96


def v(radius, theta, z):
    return (
        radius * math.cos(theta),
        radius * math.sin(theta),
        z,
    )


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def norm(n):
    length = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
    if length == 0:
        return (0.0, 0.0, 0.0)
    return (n[0] / length, n[1] / length, n[2] / length)


def tri(faces, a, b, c):
    faces.append((a, b, c))


def quad(faces, a, b, c, d):
    tri(faces, a, b, c)
    tri(faces, a, c, d)


def in_vent(theta, z):
    if not (VENT_Z0 <= z <= VENT_Z1):
        return False
    wrapped = theta % (2 * math.pi)
    for i in range(VENT_COUNT):
        center = 2 * math.pi * i / VENT_COUNT
        diff = abs((wrapped - center + math.pi) % (2 * math.pi) - math.pi)
        if diff <= VENT_HALF_ANGLE:
            return True
    return False


def add_cylinder_with_windows(faces, radius, z0, z1, outward=True):
    dz = (z1 - z0) / Z_STEPS
    for iz in range(Z_STEPS):
        za = z0 + iz * dz
        zb = za + dz
        zc = (za + zb) / 2
        for ia in range(ANG_STEPS):
            ta = 2 * math.pi * ia / ANG_STEPS
            tb = 2 * math.pi * (ia + 1) / ANG_STEPS
            tc = (ta + tb) / 2
            if in_vent(tc, zc):
                continue
            a, b, c, d = v(radius, ta, za), v(radius, tb, za), v(radius, tb, zb), v(radius, ta, zb)
            if outward:
                quad(faces, a, b, c, d)
            else:
                quad(faces, d, c, b, a)


def add_cylinder(faces, radius, z0, z1, outward=True, steps=ANG_STEPS):
    for ia in range(steps):
        ta = 2 * math.pi * ia / steps
        tb = 2 * math.pi * (ia + 1) / steps
        a, b, c, d = v(radius, ta, z0), v(radius, tb, z0), v(radius, tb, z1), v(radius, ta, z1)
        if outward:
            quad(faces, a, b, c, d)
        else:
            quad(faces, d, c, b, a)


def add_annulus(faces, inner_r, outer_r, z, up=True, steps=ANG_STEPS):
    for ia in range(steps):
        ta = 2 * math.pi * ia / steps
        tb = 2 * math.pi * (ia + 1) / steps
        a, b = v(inner_r, ta, z), v(inner_r, tb, z)
        c, d = v(outer_r, tb, z), v(outer_r, ta, z)
        if up:
            quad(faces, a, b, c, d)
        else:
            quad(faces, d, c, b, a)


def in_bolt_hole(x, y):
    for cx, cy in BOLT_CENTERS:
        if (x - cx) ** 2 + (y - cy) ** 2 <= BOLT_R ** 2:
            return True
    return False


def in_flange_face(x, y, inner_r, outer_r):
    r2 = x * x + y * y
    return inner_r * inner_r <= r2 <= outer_r * outer_r and not in_bolt_hole(x, y)


def add_flange_face_grid(faces, inner_r, outer_r, z, up=True, step=1.0):
    # Simple grid triangulation makes the M5 holes real openings in the STL.
    start = -outer_r
    count = int(math.ceil(2 * outer_r / step))
    for ix in range(count):
        x0 = start + ix * step
        x1 = x0 + step
        for iy in range(count):
            y0 = start + iy * step
            y1 = y0 + step
            cx = (x0 + x1) / 2
            cy = (y0 + y1) / 2
            if not in_flange_face(cx, cy, inner_r, outer_r):
                continue
            a, b, c, d = (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)
            if up:
                quad(faces, a, b, c, d)
            else:
                quad(faces, d, c, b, a)


def add_bolt_hole_walls(faces, z0, z1, steps=36):
    for cx, cy in BOLT_CENTERS:
        for i in range(steps):
            ta = 2 * math.pi * i / steps
            tb = 2 * math.pi * (i + 1) / steps
            a = (cx + BOLT_R * math.cos(ta), cy + BOLT_R * math.sin(ta), z0)
            b = (cx + BOLT_R * math.cos(tb), cy + BOLT_R * math.sin(tb), z0)
            c = (cx + BOLT_R * math.cos(tb), cy + BOLT_R * math.sin(tb), z1)
            d = (cx + BOLT_R * math.cos(ta), cy + BOLT_R * math.sin(ta), z1)
            quad(faces, d, c, b, a)


def add_disk(faces, radius, z, up=True, steps=ANG_STEPS):
    center = (0.0, 0.0, z)
    for ia in range(steps):
        ta = 2 * math.pi * ia / steps
        tb = 2 * math.pi * (ia + 1) / steps
        if up:
            tri(faces, center, v(radius, ta, z), v(radius, tb, z))
        else:
            tri(faces, center, v(radius, tb, z), v(radius, ta, z))


def add_window_edges(faces):
    for i in range(VENT_COUNT):
        center = 2 * math.pi * i / VENT_COUNT
        ta = center - VENT_HALF_ANGLE
        tb = center + VENT_HALF_ANGLE
        for theta in (ta, tb):
            # Vertical radial walls at each side of the window.
            quad(
                faces,
                v(INNER_R, theta, VENT_Z0),
                v(OUTER_R, theta, VENT_Z0),
                v(OUTER_R, theta, VENT_Z1),
                v(INNER_R, theta, VENT_Z1),
            )
        steps = max(4, int((tb - ta) / (2 * math.pi) * ANG_STEPS))
        for j in range(steps):
            t0 = ta + (tb - ta) * j / steps
            t1 = ta + (tb - ta) * (j + 1) / steps
            # Horizontal window sill and lintel faces through wall thickness.
            quad(faces, v(INNER_R, t0, VENT_Z0), v(INNER_R, t1, VENT_Z0), v(OUTER_R, t1, VENT_Z0), v(OUTER_R, t0, VENT_Z0))
            quad(faces, v(OUTER_R, t0, VENT_Z1), v(OUTER_R, t1, VENT_Z1), v(INNER_R, t1, VENT_Z1), v(INNER_R, t0, VENT_Z1))


def write_ascii_stl(path, faces):
    with path.open("w", encoding="ascii") as f:
        f.write("solid asa_outrunner_guard_d5065_test\n")
        for a, b, c in faces:
            n = norm(cross(sub(b, a), sub(c, a)))
            f.write(f"  facet normal {n[0]:.6g} {n[1]:.6g} {n[2]:.6g}\n")
            f.write("    outer loop\n")
            for pnt in (a, b, c):
                f.write(f"      vertex {pnt[0]:.6g} {pnt[1]:.6g} {pnt[2]:.6g}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write("endsolid asa_outrunner_guard_d5065_test\n")


def main():
    faces = []
    add_cylinder_with_windows(faces, OUTER_R, 0, HEIGHT, outward=True)
    add_cylinder_with_windows(faces, INNER_R, 0, HEIGHT - TOP_THICKNESS, outward=False)
    add_window_edges(faces)
    add_disk(faces, OUTER_R, HEIGHT, up=True)
    add_disk(faces, INNER_R, HEIGHT - TOP_THICKNESS, up=False)
    add_cylinder(faces, FLANGE_R, -FLANGE_THICKNESS, 0, outward=True)
    add_cylinder(faces, INNER_R, -FLANGE_THICKNESS, 0, outward=False)
    add_bolt_hole_walls(faces, -FLANGE_THICKNESS, 0)
    add_flange_face_grid(faces, OUTER_R, FLANGE_R, 0, up=True)
    add_flange_face_grid(faces, INNER_R, FLANGE_R, -FLANGE_THICKNESS, up=False)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_ascii_stl(OUT, faces)
    print(OUT)
    print(f"inner_diameter_mm={INNER_R * 2:.1f}")
    print(f"outer_diameter_mm={OUTER_R * 2:.1f}")
    print(f"flange_diameter_mm={FLANGE_R * 2:.1f}")
    print(f"bolt_holes={BOLT_COUNT}x {BOLT_HOLE_DIA:.1f}mm on {BOLT_CIRCLE_DIA:.1f}mm BCD")
    print(f"height_mm={HEIGHT:.1f}")
    print(f"vent_z_mm={VENT_Z0:.1f}-{VENT_Z1:.1f}")
    print(f"triangles={len(faces)}")


if __name__ == "__main__":
    main()
