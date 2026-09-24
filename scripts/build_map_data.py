"""Build the province map data embedded in tools/covid-nl.html.

Inputs (download once into data/raw/, which git ignores):
  provincies-2024.json               PDOK CBS gebiedsindelingen, provincie_gegeneraliseerd, jaarcode 2024, EPSG:28992
      https://api.pdok.nl/cbs/gebiedsindelingen/ogc/v1/collections/provincie_gegeneraliseerd/items?f=json&jaarcode=2024&limit=50&crs=http://www.opengis.net/def/crs/EPSG/0/28992
  provincies-labelpoint-2024.json    PDOK, same API, collection provincie_labelpoint (label positions)
      https://api.pdok.nl/cbs/gebiedsindelingen/ogc/v1/collections/provincie_labelpoint/items?f=json&jaarcode=2024&limit=50&crs=http://www.opengis.net/def/crs/EPSG/0/28992
  rsa-rwzi.json                      PDOK/Rijkswaterstaat Richtlijn Stedelijk Afvalwater, RWZI locations (uwwcode NL01008 = RIVM code 1008)
      https://service.pdok.nl/rws/richtlijn-stedelijk-afvalwater/wfs/v2_0?request=GetFeature&service=WFS&version=2.0.0&typeNames=richtlijnstedelijkafvalwater:rsa_rwzi&outputFormat=application/json&srsName=EPSG:28992
  cbs-inwoners-per-rwzi-2024.xlsx  CBS, inwoners per rioolwaterzuiveringsinstallatie 1-1-2024 (Tabel 1)
      https://www.cbs.nl/nl-nl/maatwerk/2025/04/inwoners-per-rioolwaterzuiveringsinstallatie-1-1-2024
  cbs-gebieden-2024.json             CBS StatLine 85755NED "Gebieden in Nederland 2024" (gemeente -> provincie)
      https://opendata.cbs.nl/ODataApi/odata/85755NED/TypedDataSet?$format=json

  pc4-2024.json                      CBS 4-digit postcode areas 2024, fetched by scripts/fetch_pc4.py

Run from the repo root:  uv run --with openpyxl --with shapely python scripts/build_map_data.py
It rewrites the block between the GEO markers in tools/covid-nl.html and writes tools/covid-nl-catchments.js.

Catchment areas are approximate: no national map of them is published, so each postcode area goes to the
station that serves most of its residents (CBS Tabel 2) and the postcode areas are merged per station.
"""
import json, math, pathlib, re, collections
import openpyxl
from shapely.geometry import shape
from shapely.ops import unary_union

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
        # 99998/99999 are CBS's "niet ingedeeld" / "buiten RWZI herkomstgebied" rows: residents no plant serves
        if not r or r[6] != "GM" or r[7] not in gm2pv or str(r[1]) in ("99998", "99999"):
            continue
        plants[str(r[1])][index[gm2pv[r[7]]]] += r[5] * float(r[9])
    plants = {code: [[pv, round(pop)] for pv, pop in sorted(v.items()) if round(pop) > 0] for code, v in plants.items()}

    # station locations, keyed by the numeric code RIVM uses
    stations = {}
    for f in json.load(open(RAW / "rsa-rwzi.json"))["features"]:
        code = f["properties"]["uwwcode"]
        if not (code.startswith("NL") and code[2:].isdigit()):
            continue
        x, y = f["geometry"]["coordinates"][0] if f["geometry"]["type"] == "MultiPoint" else f["geometry"]["coordinates"]
        stations[str(int(code[2:]))] = [round((x - x0) / UNIT), round((y1 - y) / UNIT)]

    # catchment areas: postcode areas merged per station that serves most of their residents
    by_pc4 = collections.defaultdict(lambda: collections.defaultdict(float))
    for r in list(wb["Tabel 2"].iter_rows(values_only=True))[4:]:
        if not r or r[6] != "PC4" or str(r[1]) in ("99998", "99999"):
            continue
        by_pc4[int(r[7])][str(r[1])] += r[5] * float(r[8])   # station residents x share living in this postcode
    main_station = {pc: max(d.items(), key=lambda kv: kv[1])[0] for pc, d in by_pc4.items()}
    groups = collections.defaultdict(list)
    for f in json.load(open(RAW / "pc4-2024.json"))["features"]:
        pc = f["properties"]["postcode"]
        if pc in main_station:
            groups[main_station[pc]].append(shape(f["geometry"]))

    def to_path(geom):
        polys = [geom] if geom.geom_type == "Polygon" else [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]
        out = []
        for p in polys:
            if p.area < 2e5:
                continue
            for ring in [p.exterior, *p.interiors]:
                q = [(round((x - x0) / UNIT), round((y1 - y) / UNIT)) for x, y in list(ring.coords)[:-1]]
                q = [pt for i, pt in enumerate(q) if i == 0 or pt != q[i - 1]]
                if len(q) >= 3:
                    out.append("M%d %d" % q[0] + "".join("l%d %d" % (b[0] - a[0], b[1] - a[1]) for a, b in zip(q, q[1:])) + "z")
        return "".join(out)

    catchments = {code: to_path(unary_union(geoms).simplify(300, preserve_topology=True)) for code, geoms in sorted(groups.items())}
    catchments = {k: v for k, v in catchments.items() if v}
    js = ("// generated by scripts/build_map_data.py: approximate sewage station catchment areas (CBS postcode areas 2024)\n"
          "window.COVID_CATCHMENTS = " + json.dumps(catchments, separators=(",", ":")) + ";\n")
    (ROOT / "tools" / "covid-nl-catchments.js").write_text(js)
    print(f"{len(catchments)} catchment areas, {len(js) / 1024:.0f} KB in tools/covid-nl-catchments.js")

    data = {"w": width, "h": height, "provinces": provinces, "plants": plants, "stations": stations}
    block = "const GEO = " + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";"
    html = PAGE.read_text()
    new, n = re.subn(r"(/\* GEO:BEGIN[^\n]*\n).*?(\n\s*/\* GEO:END \*/)", lambda m: m.group(1) + "  " + block + m.group(2), html, flags=re.S)
    if n != 1:
        raise SystemExit("GEO markers not found in " + str(PAGE))
    PAGE.write_text(new)
    print(f"{len(provinces)} provinces, {len(plants)} plants, {len(stations)} station locations, {len(block) / 1024:.0f} KB embedded")


if __name__ == "__main__":
    main()
