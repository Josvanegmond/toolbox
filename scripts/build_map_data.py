"""Build the province map data embedded in tools/covid-nl.html.

Inputs (download once into data/raw/, which git ignores):
  provincies-2024.json               PDOK CBS gebiedsindelingen, provincie_gegeneraliseerd, jaarcode 2024, EPSG:28992
      https://api.pdok.nl/cbs/gebiedsindelingen/ogc/v1/collections/provincie_gegeneraliseerd/items?f=json&jaarcode=2024&limit=50&crs=http://www.opengis.net/def/crs/EPSG/0/28992
  provincies-labelpoint-2024.json    PDOK, same API, collection provincie_labelpoint (label positions)
      https://api.pdok.nl/cbs/gebiedsindelingen/ogc/v1/collections/provincie_labelpoint/items?f=json&jaarcode=2024&limit=50&crs=http://www.opengis.net/def/crs/EPSG/0/28992
  cbs-inwoners-per-rwzi-2024.xlsx   CBS, inwoners per rioolwaterzuiveringsinstallatie 1-1-2024 (Tabel 1)
      https://www.cbs.nl/nl-nl/maatwerk/2025/04/inwoners-per-rioolwaterzuiveringsinstallatie-1-1-2024
  cbs-gebieden-2024.json             CBS StatLine 85755NED "Gebieden in Nederland 2024" (gemeente -> provincie)
      https://opendata.cbs.nl/ODataApi/odata/85755NED/TypedDataSet?$format=json

Run from the repo root:  uv run --with openpyxl python scripts/build_map_data.py
It rewrites the block between the GEO markers in tools/covid-nl.html.
"""
import json, math, pathlib, re, collections
import openpyxl

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PAGE = ROOT / "tools" / "covid-nl.html"
UNIT = 100        # output coordinates in units of 100 m
TOL = 250         # Douglas-Peucker tolerance in metres
MIN_AREA = 2e6    # drop rings smaller than 2 km² (tiny islets)


def dp(pts, tol):
    """Douglas-Peucker simplification of an open polyline."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-9
        best, idx = -1, None
        for i in range(a + 1, b):
            x0, y0 = pts[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def ring_area(r):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]))) / 2


def main():
    geo = json.load(open(RAW / "provincies-2024.json"))
    xs = [x for f in geo["features"] for poly in f["geometry"]["coordinates"] for ring in poly for x, _ in ring]
    ys = [y for f in geo["features"] for poly in f["geometry"]["coordinates"] for ring in poly for _, y in ring]
    x0, y1 = min(xs), max(ys)
    width, height = math.ceil((max(xs) - x0) / UNIT), math.ceil((y1 - min(ys)) / UNIT)

    labels = {f["properties"]["statcode"]: f["geometry"]["coordinates"]
              for f in json.load(open(RAW / "provincies-labelpoint-2024.json"))["features"]}
    provinces = []
    for f in sorted(geo["features"], key=lambda f: f["properties"]["statnaam"]):
        parts = []
        for poly in f["geometry"]["coordinates"]:
            for ring in poly:
                ring = [tuple(p) for p in ring[:-1]]
                if ring_area(ring) < MIN_AREA:
                    continue
                # simplify as two halves so the closing point stays fixed
                mid = len(ring) // 2
                simp = dp(ring[: mid + 1], TOL)[:-1] + dp(ring[mid:] + ring[:1], TOL)[:-1]
                q = [(round((x - x0) / UNIT), round((y1 - y) / UNIT)) for x, y in simp]
                q = [p for i, p in enumerate(q) if i == 0 or p != q[i - 1]]
                if len(q) < 3:
                    continue
                d = "M%d %d" % q[0] + "".join("l%d %d" % (b[0] - a[0], b[1] - a[1]) for a, b in zip(q, q[1:])) + "z"
                parts.append(d)
        lx, ly = labels[f["properties"]["statcode"]]
        provinces.append({"code": f["properties"]["statcode"], "name": f["properties"]["statnaam"], "d": "".join(parts),
                          "lx": round((lx - x0) / UNIT), "ly": round((y1 - ly) / UNIT)})

    # plant -> residents per province, via municipality shares (CBS Tabel 1, rows of type GM)
    gm2pv = {r["Code_1"].strip(): r["Code_28"].strip() for r in json.load(open(RAW / "cbs-gebieden-2024.json"))["value"]}
    index = {p["code"]: i for i, p in enumerate(provinces)}
    plants = collections.defaultdict(lambda: collections.defaultdict(float))
    wb = openpyxl.load_workbook(RAW / "cbs-inwoners-per-rwzi-2024.xlsx", read_only=True)
    for r in list(wb["Tabel 1"].iter_rows(values_only=True))[4:]:
        if not r or r[6] != "GM" or r[7] not in gm2pv:
            continue
        plants[str(r[1])][index[gm2pv[r[7]]]] += r[5] * float(r[9])
    plants = {code: [[pv, round(pop)] for pv, pop in sorted(v.items()) if round(pop) > 0] for code, v in plants.items()}

    data = {"w": width, "h": height, "provinces": provinces, "plants": plants}
    block = "const GEO = " + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";"
    html = PAGE.read_text()
    new, n = re.subn(r"(/\* GEO:BEGIN[^\n]*\n).*?(\n\s*/\* GEO:END \*/)", lambda m: m.group(1) + "  " + block + m.group(2), html, flags=re.S)
    if n != 1:
        raise SystemExit("GEO markers not found in " + str(PAGE))
    PAGE.write_text(new)
    print(f"{len(provinces)} provinces, {len(plants)} plants, {len(block) / 1024:.0f} KB embedded")


if __name__ == "__main__":
    main()
