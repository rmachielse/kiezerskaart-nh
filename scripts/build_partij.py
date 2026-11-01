"""Convert the party spreadsheet to JSON and join it to CBS buurt geometries.

Usage: python scripts/build_partij.py "D66-buurten NH (conceptversie).xlsx"
Writes data/processed/partij_buurten.json (plain records) and partij_data.js (map data).
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

COLS = {
    "Gemeente": "gemeente", "Wijk": "wijk", "Buurt": "buurt", "Buurtcode": "buurtcode",
    "Inwoners": "inwoners", "Opkomst PS2023": "opkomst_ps23", "D66 % PS2023": "d66_ps23",
    "Opkomst TK2023": "opkomst_tk23", "D66 % TK2023": "d66_tk23", "Opkomst TK2025": "opkomst_tk25",
    "D66 % TK2025": "d66_tk25", "D66-stemmen TK2025": "d66_stemmen_tk25", "Buurtscore (0-100)": "buurtscore",
}


def main(path):
    x = pd.read_excel(path)
    x.columns = [c.strip() for c in x.columns]
    missing = set(COLS) - set(x.columns)
    if missing:
        sys.exit(f"Kolommen ontbreken in spreadsheet: {sorted(missing)}")
    x = x.rename(columns=COLS)[list(COLS.values())]
    floats = x.select_dtypes("float").columns
    x[floats] = x[floats].round(6)  # strip Excel float noise (0.6629999999999999)
    x = x.astype(object).where(x.notna(), None)
    records = x.to_dict("records")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "partij_buurten.json").write_text(json.dumps(
        {"bron": Path(path).name, "buurten": records}, ensure_ascii=False, indent=1))

    # The map takes buurt geometries from data.js (build.py); this file only carries the figures.
    (OUT / "partij_data.js").write_text("window.PARTIJ = " + json.dumps(
        {"bron": Path(path).name, "buurten": records}, separators=(",", ":"), ensure_ascii=False) + ";")
    buurten = gpd.read_file(RAW / "cbs/buurten_2025_nh.geojson")
    codes = set(buurten[buurten.water == "NEE"].buurtcode)
    print(f"{len(records)} rijen; {len(set(x.buurtcode) & codes)} van {len(codes)} CBS-buurten gekoppeld; "
          f"niet gekoppeld uit spreadsheet: {len(set(x.buurtcode) - codes)}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
