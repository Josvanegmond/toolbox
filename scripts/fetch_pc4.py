"""Download CBS 4-digit postcode areas (PDOK, jaarcode 2024, EPSG:28992) once into data/raw/pc4-2024.json.

Keeps only the postcode and geometry. Used by build_map_data.py to draw sewage station catchment areas.
Run from the repo root:  python scripts/fetch_pc4.py
"""
import json, pathlib, time, urllib.request

OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw" / "pc4-2024.json"
url = ("https://api.pdok.nl/cbs/postcode4/ogc/v1/collections/postcode4/items?f=json&limit=1000&jaarcode=2024"
       "&crs=http://www.opengis.net/def/crs/EPSG/0/28992")
features = []
while url:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    page = json.load(urllib.request.urlopen(req, timeout=300))
    features += [{"type": "Feature", "properties": {"postcode": f["properties"]["postcode"]}, "geometry": f["geometry"]}
                 for f in page["features"]]
    url = next((l["href"] for l in page["links"] if l["rel"] == "next"), None)
    print(len(features), "postcode areas")
    time.sleep(1)
OUT.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
print("wrote", OUT, OUT.stat().st_size // 1024, "KB")
