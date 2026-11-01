"""Combine stembureau-uitslagen (PS2023, TK2025, GR2026) for Noord-Holland and
estimate results per CBS-buurt.

Method: per gemeente the stembureau locations are turned into Voronoi cells
(clipped to the gemeente). Each cell's votes are distributed over the buurten it
overlaps, weighted by the estimated population in the overlap (buurt population
x overlapping area share). The result is an *estimate*: with a stempas people
can vote anywhere in their gemeente.
"""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
RD = "EPSG:28992"

META = {
    "omschrijving", "id", "Stembureau", "Adres", "Locatie", "description", "Geldige stemmen",
    "Opgeroepen", "Ongeldig", "Blanco", "Geldige stempassen", "Geldige volmachtbewijzen",
    "Geldige kiezerspassen", "Toegelaten kiezers", "Meer getelde stembiljetten",
    "Minder getelde stembiljetten", "Meegenomen stembiljetten", "Te weinig uitgereikte stembiljetten",
    "Te veel uitgereikte stembiljetten", "Geen verklaring", "Andere verklaring",
    "Te veel briefstembiljetten", "Geen briefstembiljetten", "gmcode", "election", "electionName",
    "Opkomst", "Opkomstpercentage",
}

# Canonical party keys, in display order.
PARTIES = ["D66", "GL-PvdA", "VVD", "PVV", "CDA", "JA21", "FvD", "BBB", "SP", "PvdD", "Volt",
           "CU", "SGP", "DENK", "NSC", "50PLUS", "BIJ1", "D66-combi", "Lokaal", "Overig"]

CANON = {
    "D66": "D66",
    "GROENLINKS / Partij van de Arbeid (PvdA)": "GL-PvdA",
    "GROENLINKS": "GL-PvdA",
    "Partij van de Arbeid (P.v.d.A.)": "GL-PvdA",
    "Partij van de Arbeid (PvdA)": "GL-PvdA",
    "VVD": "VVD",
    "PVV (Partij voor de Vrijheid)": "PVV",
    "CDA": "CDA",
    "JA21": "JA21",
    "Forum voor Democratie": "FvD",
    "BBB": "BBB",
    "SP (Socialistische Partij)": "SP",
    "Partij voor de Dieren": "PvdD",
    "Volt": "Volt",
    "ChristenUnie": "CU",
    "Staatkundig Gereformeerde Partij (SGP)": "SGP",
    "DENK": "DENK",
    "Nieuw Sociaal Contract (NSC)": "NSC",
    "50PLUS": "50PLUS",
    "BIJ1": "BIJ1",
    "D66 - GROENLINKS": "D66-combi",
    "D66 - GROENLINKS / Partij van de Arbeid (PvdA)": "D66-combi",
    "Lokale partij": "Lokaal",
}


def canon(name):
    return CANON.get(name.strip(), "Overig")


def to_int(v):
    if v is None:
        return 0
    s = str(v).strip()
    return int(float(s)) if s else 0


# ---------------------------------------------------------------- stations

def load_openstate(path, keep):
    rows = []
    for f in json.loads(Path(path).read_text())["features"]:
        p = f["properties"]
        if not keep(p) or not f.get("geometry"):
            continue
        votes = defaultdict(int)
        for k, v in p.items():
            if k not in META:
                votes[canon(k)] += to_int(v)
        lon, lat = f["geometry"]["coordinates"][:2]
        rows.append({
            "gmcode": p["gmcode"],
            "naam": re.sub(r"^Stembureau\s+", "", p.get("description") or ""),
            "postcode": (p.get("Adres") or "").replace(" ", ""),
            "lon": lon, "lat": lat,
            "geldig": to_int(p.get("Geldige stemmen")),
            **votes,
        })
    return pd.DataFrame(rows)


def load_gr2026(nh_codes, ref):
    """Parse Kiesraad EML Telling files; geocode via postcode match or PDOK."""
    classif = {r["Partijnaam"]: r["Classificatie"] for r in csv.DictReader(
        open(RAW / "kiesraad/PartijKlassificatie_GR2026.csv", encoding="utf-8-sig"), delimiter=";")}
    ns = {"e": "urn:oasis:names:tc:evs:schema:eml"}
    from lxml import etree

    pc_lookup = {(r.gmcode, r.postcode): (r.lon, r.lat) for r in ref.itertuples() if r.postcode}
    rows, lists = [], defaultdict(set)
    for path in sorted((RAW / "kiesraad/GR2026_eml/08_Noord-Holland").glob("Telling_*.xml")):
        tree = etree.parse(str(path))
        gm = "GM" + tree.find(".//e:ManagingAuthority/e:AuthorityIdentifier", ns).get("Id")
        if gm not in nh_codes:
            continue
        for ru in tree.iterfind(".//e:ReportingUnitVotes", ns):
            ident = ru.find("e:ReportingUnitIdentifier", ns)
            name = ident.text or ""
            votes = defaultdict(int)
            for sel in ru.iterfind("e:Selection", ns):
                aff = sel.find("e:AffiliationIdentifier/e:RegisteredName", ns)
                if aff is None:
                    continue
                lijst = aff.text or ""
                key = canon(classif.get(lijst, lijst))
                votes[key] += int(sel.find("e:ValidVotes", ns).text)
                lists[gm].add(key)
            m = re.search(r"postcode:\s*(\d{4})\s*([A-Z]{2})", name)
            rows.append({
                "gmcode": gm,
                "naam": re.sub(r"^(Stembureau\s+)+", "", re.sub(r"\s*\(postcode:.*\)", "", name)),
                "postcode": m.group(1) + m.group(2) if m else "",
                "geldig": sum(votes.values()),
                **votes,
            })
    df = pd.DataFrame(rows)
    lon, lat, src = [], [], []
    for r in df.itertuples():
        hit = pc_lookup.get((r.gmcode, r.postcode))
        if hit is None and r.postcode:
            hit = geocode_postcode(r.postcode)
            src.append("pdok" if hit else "none")
        else:
            src.append("match" if hit else "none")
        lon.append(hit[0] if hit else None)
        lat.append(hit[1] if hit else None)
    df["lon"], df["lat"], df["geo"] = lon, lat, src
    print("GR2026 geocoding:", df["geo"].value_counts().to_dict(), file=sys.stderr)
    return df[df["lon"].notna()].drop(columns="geo"), {k: sorted(v) for k, v in lists.items()}


def geocode_postcode(pc):
    r = requests.get("https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
                     params={"q": f"postcode:{pc}", "fq": "type:postcode", "rows": 1}, timeout=30)
    docs = r.json()["response"]["docs"]
    if not docs:
        return None
    lon, lat = map(float, re.findall(r"[-\d.]+", docs[0]["centroide_ll"]))
    return lon, lat


# ---------------------------------------------------------------- allocation

def allocate(stations, buurten):
    """Return DataFrame indexed by buurtcode with estimated votes per party."""
    st = gpd.GeoDataFrame(stations, geometry=gpd.points_from_xy(stations.lon, stations.lat),
                          crs="EPSG:4326").to_crs(RD)
    cols = [p for p in PARTIES if p in st.columns] + ["geldig"]
    st[cols] = st[cols].fillna(0)
    # Merge stembureaus that share a building (same location within 5 m).
    st["kx"] = (st.geometry.x / 5).round()
    st["ky"] = (st.geometry.y / 5).round()
    loc = st.groupby(["gmcode", "kx", "ky"], as_index=False).agg(
        {**{c: "sum" for c in cols}, "geometry": "first"})
    loc = gpd.GeoDataFrame(loc, geometry="geometry", crs=RD)

    result = []
    for gm, pts in loc.groupby("gmcode"):
        bu = buurten[buurten.gemeentecode == gm]
        if bu.empty:
            continue
        region = shapely.union_all(bu.geometry.values)
        if len(pts) == 1:
            cells = [region]
        else:
            vor = shapely.voronoi_polygons(shapely.MultiPoint(list(pts.geometry)),
                                           extend_to=region.envelope.buffer(1000), ordered=True)
            cells = [shapely.intersection(c, region) for c in vor.geoms]
        cell_df = gpd.GeoDataFrame(pts[cols].reset_index(drop=True), geometry=cells, crs=RD)
        cell_df["cell"] = range(len(cell_df))
        ov = gpd.overlay(cell_df[["cell", "geometry"]],
                         bu[["buurtcode", "inwoners", "area", "geometry"]], how="intersection",
                         keep_geom_type=True)
        ov["a"] = ov.geometry.area
        ov["w"] = ov.inwoners * ov.a / ov.area
        tot = ov.groupby("cell")["w"].transform("sum")
        area_tot = ov.groupby("cell")["a"].transform("sum")
        ov["frac"] = np.where(tot > 0, ov.w / tot.replace(0, np.nan), ov.a / area_tot)
        ov = ov.merge(cell_df[["cell"] + cols], on="cell")
        for c in cols:
            ov[c] = ov[c] * ov.frac
        result.append(ov.groupby("buurtcode")[cols].sum())
    return pd.concat(result)


# ---------------------------------------------------------------- main

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    buurten = gpd.read_file(RAW / "cbs/buurten_2025_nh.geojson").to_crs(RD)
    buurten = buurten[buurten.water == "NEE"].copy()
    nh_codes = set(buurten.gemeentecode)
    buurten["inwoners"] = buurten.aantal_inwoners.clip(lower=0).fillna(0)
    buurten["huishoudens"] = buurten.aantal_huishoudens.clip(lower=0).fillna(0)
    p0 = buurten.percentage_personen_0_tot_15_jaar.where(lambda s: s >= 0)
    p15 = buurten.percentage_personen_15_tot_25_jaar.where(lambda s: s >= 0)
    # 18+ approximation: drop 0-14 and ~3/10 of 15-24; fall back to NL average (~80%).
    frac18 = (1 - p0 / 100 - 0.3 * p15 / 100).fillna(0.8)
    buurten["volwassenen"] = (buurten.inwoners * frac18).round()
    buurten["area"] = buurten.geometry.area

    ps = load_openstate(RAW / "openstate/2023ps.geo.json",
                        lambda p: p["election"] == "PS2023_NoordHolland")
    tk = load_openstate(RAW / "openstate/2025tk.geo.json", lambda p: p["gmcode"] in nh_codes)
    gr, gr_lists = load_gr2026(nh_codes, pd.concat([tk, ps]))
    elections = {"tk25": tk, "ps23": ps, "gr26": gr}

    table = buurten[["buurtcode", "buurtnaam", "wijkcode", "gemeentecode", "gemeentenaam",
                     "inwoners", "huishoudens", "volwassenen", "area"]].set_index("buurtcode")
    stations_out = {}
    for key, df in elections.items():
        est = allocate(df, buurten).add_prefix(f"{key}_")
        table = table.join(est)
        print(f"{key}: {len(df)} stembureaus, {int(df.geldig.sum())} geldige stemmen, "
              f"toegewezen {int(est[f'{key}_geldig'].sum())}", file=sys.stderr)
        cols = ["gmcode", "naam", "lon", "lat", "geldig"] + [p for p in PARTIES if p in df.columns]
        stations_out[key] = df[cols].fillna(0).round(5).to_dict("records")

    for key in elections:
        for p in PARTIES:
            table[f"{key}_{p}"] = table.get(f"{key}_{p}", 0)
        table[f"{key}_geldig"] = table[f"{key}_geldig"].fillna(0)
    table[[c for c in table.columns if c.split("_")[0] in elections]] = table[[c for c in table.columns if c.split("_")[0] in elections]].fillna(0)

    # D66 campaign metrics ------------------------------------------------
    # Allocated vote totals per buurt are distorted by where stembureaus happen to be
    # (stempas voters flock to central locations), so absolute estimates use the
    # buurt's party share x adults x gemeente turnout, and the TK->PS drop-off is
    # measured per wijk, shrunk towards the gemeente value.
    tkv, psv = table.tk25_geldig, table.ps23_geldig
    gem = table.groupby("gemeentecode")[["tk25_geldig", "ps23_geldig", "volwassenen"]].transform("sum")
    wijk = table.groupby("wijkcode")[["tk25_geldig", "ps23_geldig"]].transform("sum")
    table["opkomst_gem_tk25"] = (gem.tk25_geldig / gem.volwassenen).clip(upper=1)
    table["opkomst_gem_ps23"] = (gem.ps23_geldig / gem.volwassenen).clip(upper=1)
    r_gem = gem.ps23_geldig / gem.tk25_geldig.replace(0, np.nan)
    m = 2000  # pseudo-votes: weight of the gemeente prior
    table["ps_tk_ratio"] = ((wijk.ps23_geldig + m * r_gem) / (wijk.tk25_geldig + m)).clip(0, 1)
    reliable = (table.inwoners >= 50) & (tkv >= 20)
    for key in elections:
        table[f"opkomst_{key}"] = (table[f"{key}_geldig"] / table.volwassenen.replace(0, np.nan)).clip(upper=1)
    table["d66_aandeel_tk25"] = (table.tk25_D66 / tkv.replace(0, np.nan)).where(reliable)
    table["d66_aandeel_ps23"] = (table.ps23_D66 / psv.replace(0, np.nan)).where(reliable)
    table["d66_aandeel_gr26"] = (table.gr26_D66 / table.gr26_geldig.replace(0, np.nan)).where(
        reliable & table.gemeentecode.map(lambda gm: "D66" in gr_lists.get(gm, [])))
    table["d66_groei"] = table.d66_aandeel_tk25 - table.d66_aandeel_ps23
    table["d66_kiezers_tk25"] = table.d66_aandeel_tk25 * table.volwassenen * table.opkomst_gem_tk25
    table["d66_kiezers_ps23"] = table.d66_aandeel_ps23 * table.volwassenen * table.opkomst_gem_ps23
    table["d66_mobiliseerbaar"] = table.d66_kiezers_tk25 * (1 - table.ps_tk_ratio)
    hh = table.huishoudens.where(table.huishoudens >= 50)
    table["d66_mob_per_100hh"] = 100 * table.d66_mobiliseerbaar / hh
    table["canvas_score"] = np.sqrt(table.d66_mobiliseerbaar * table.d66_mob_per_100hh)
    table["gr26_d66_lijst"] = table.gemeentecode.map(
        lambda gm: "D66" if "D66" in gr_lists.get(gm, []) else
        ("D66-combi" if "D66-combi" in gr_lists.get(gm, []) else
         ("geen GR2026" if gm not in gr_lists else "geen")))

    table.to_csv(OUT / "buurten_schattingen.csv", float_format="%.4f")

    # Map data ----------------------------------------------------------
    geo = buurten.set_index("buurtcode")[["geometry"]].join(table, how="inner")
    geo["geometry"] = geo.geometry.simplify(4)
    geo = geo.to_crs("EPSG:4326").reset_index()
    geo["km2"] = geo.pop("area") / 1e6
    num = geo.select_dtypes("number").columns
    geo[num] = geo[num].round(4)
    for c in [c for c in geo.columns if c.split("_")[0] in elections]:
        geo[c] = geo[c].round(1)
    gj = json.loads(geo.to_json(drop_id=True))
    for f in gj["features"]:
        f["geometry"] = shapely.geometry.mapping(
            shapely.set_precision(shapely.geometry.shape(f["geometry"]), 0.00001))
    # Neighbouring buurten (touching within 2 m), used to merge priority buurten into werkgebieden.
    b = buurten[["buurtcode", "geometry"]]
    pairs = gpd.sjoin(b, b.assign(geometry=b.buffer(2)), predicate="intersects")
    pairs = pairs[pairs.buurtcode_left != pairs.buurtcode_right]
    neighbours = pairs.groupby("buurtcode_left").buurtcode_right.apply(sorted).to_dict()
    data = {"buurten": gj, "stations": stations_out, "parties": PARTIES, "grLists": gr_lists,
            "buren": neighbours}
    (OUT / "data.js").write_text("window.DATA = " + json.dumps(data, separators=(",", ":"),
                                                               default=str) + ";")
    print(f"buurten: {len(geo)}; data.js {(OUT / 'data.js').stat().st_size / 1e6:.1f} MB",
          file=sys.stderr)


if __name__ == "__main__":
    main()
