"""Merge CBS buurten into D66 afdelingen for the map.

Mapping: data/afdelingen.csv (gemeente -> afdeling) and data/amsterdam_stadsdelen.csv
(Amsterdam has a deelafdeling per stadsdeel; the stadsdeel is the letter after
BU0363 in the buurtcode). Writes data/processed/afdelingen.js; re-run after editing.
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
AMSTERDAM = "GM0363"


def main():
    mapping = pd.read_csv(ROOT / "data" / "afdelingen.csv")
    stadsdelen = pd.read_csv(ROOT / "data" / "amsterdam_stadsdelen.csv").set_index("letter")
    buurten = gpd.read_file(RAW / "cbs/buurten_2025_nh.geojson")
    buurten = buurten[buurten.water == "NEE"].to_crs("EPSG:28992")
    missing = set(buurten.gemeentecode) - set(mapping.gemeentecode)
    if missing:
        sys.exit(f"Gemeenten zonder afdeling in data/afdelingen.csv: {sorted(missing)}")

    merged = buurten.merge(mapping[["gemeentecode", "afdeling"]], on="gemeentecode")
    ams = merged.gemeentecode == AMSTERDAM
    letters = merged.loc[ams, "buurtcode"].str[6]
    unknown = set(letters) - set(stadsdelen.index)
    if unknown:
        sys.exit(f"Onbekende stadsdeelletters in Amsterdamse buurtcodes: {sorted(unknown)}")
    merged.loc[ams, "afdeling"] = letters.map(stadsdelen.afdeling)

    # Small buffer closes slivers between buurten before dissolving.
    afd = merged.assign(geometry=merged.buffer(1)).dissolve("afdeling").buffer(-1).simplify(20)
    afd = gpd.GeoDataFrame(geometry=afd, crs="EPSG:28992").to_crs("EPSG:4326").reset_index()
    gj = json.loads(afd.to_json(drop_id=True))
    for f in gj["features"]:
        f["geometry"] = shapely.geometry.mapping(
            shapely.set_precision(shapely.geometry.shape(f["geometry"]), 0.00001))

    gemeenten = {r.gemeentecode: {"afdeling": r.afdeling, "regio": r.regio} for r in mapping.itertuples()}
    # Buurten whose afdeling differs from their gemeente's (the Amsterdam stadsdelen).
    buurt_afd = dict(zip(merged.loc[ams, "buurtcode"], merged.loc[ams, "afdeling"]))
    (OUT / "afdelingen.js").write_text("window.AFDELINGEN = " + json.dumps(
        {"gemeenten": gemeenten, "buurten": buurt_afd, "geo": gj}, separators=(",", ":"), ensure_ascii=False) + ";")
    print(f"{merged.afdeling.nunique()} afdelingen; afdelingen.js "
          f"{(OUT / 'afdelingen.js').stat().st_size / 1e3:.0f} kB", file=sys.stderr)


if __name__ == "__main__":
    main()
