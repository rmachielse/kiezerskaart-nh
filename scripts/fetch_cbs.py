"""Download CBS wijken & buurten 2025 (PDOK OGC API) for all Noord-Holland gemeenten."""
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "cbs"
BASE = "https://api.pdok.nl/cbs/wijken-en-buurten-2025/ogc/v1/collections"


def nh_gemeentecodes():
    ps = json.loads((ROOT / "data/raw/openstate/2023ps.geo.json").read_text())
    return sorted({f["properties"]["gmcode"] for f in ps["features"]
                   if f["properties"]["election"] == "PS2023_NoordHolland"})


def fetch(collection, gmcode):
    url = f"{BASE}/{collection}/items"
    params = {"f": "json", "limit": 1000, "gemeentecode": gmcode}
    features = []
    while url:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        d = r.json()
        features += d["features"]
        url = next((l["href"] for l in d.get("links", []) if l["rel"] == "next"), None)
        params = None
    return features


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    codes = nh_gemeentecodes()
    print(f"{len(codes)} gemeenten", file=sys.stderr)
    for collection in ("gemeenten", "buurten"):
        features = []
        for gm in codes:
            features += fetch(collection, gm)
        (OUT / f"{collection}_2025_nh.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": features}))
        print(f"{collection}: {len(features)}", file=sys.stderr)


if __name__ == "__main__":
    main()
