"""Compare a buurt-level spreadsheet (e.g. from the party) with our own estimates.

Usage: python scripts/compare_xlsx.py "D66-buurten NH (conceptversie).xlsx"
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

COLS = {
    "Gemeente": "gemeente", "Wijk": "wijk", "Buurt": "buurt", "Buurtcode": "buurtcode",
    "Inwoners": "inwoners", "Opkomst PS2023": "opk_ps23", "D66 % PS2023": "d66_ps23",
    "Opkomst TK2023": "opk_tk23", "D66 % TK2023": "d66_tk23", "Opkomst TK2025": "opk_tk25",
    "D66 % TK2025": "d66_tk25", "D66-stemmen TK2025": "d66_stemmen_tk25", "Buurtscore (0-100)": "score",
}


def official_d66_per_gemeente():
    """Actual TK2025 / PS2023 D66 share per gemeente, summed from stembureau results."""
    out = {}
    for key, path, keep in [("tk25", "2025tk.geo.json", None), ("ps23", "2023ps.geo.json", "PS2023_NoordHolland")]:
        rows = []
        for f in json.loads((RAW / "openstate" / path).read_text())["features"]:
            p = f["properties"]
            if keep and p["election"] != keep:
                continue
            rows.append((p["gmcode"], int(str(p["D66"]).strip() or 0), int(str(p["Geldige stemmen"]).strip() or 0)))
        df = pd.DataFrame(rows, columns=["gmcode", "d66", "geldig"]).groupby("gmcode").sum()
        out[f"d66_stemmen_{key}"] = df.d66
        out[f"d66_aandeel_{key}"] = df.d66 / df.geldig
    return pd.DataFrame(out)


def main(path):
    x = pd.read_excel(path)
    x.columns = [c.strip() for c in x.columns]
    x = x.rename(columns=COLS)
    ours = pd.read_csv(OUT / "buurten_schattingen.csv")
    lines = []
    say = lines.append

    # 1. Internal checks --------------------------------------------------
    say(f"## Interne controles ({len(x)} rijen)")
    dup = x[x.buurtcode.duplicated(keep=False)]
    say(f"- Dubbele buurtcodes: {dup.buurtcode.nunique()}" + (f" ({', '.join(dup.buurtcode.unique()[:10])})" if len(dup) else ""))
    for c in ["inwoners", "opk_ps23", "d66_ps23", "opk_tk23", "d66_tk23", "opk_tk25", "d66_tk25", "d66_stemmen_tk25", "score"]:
        n = x[c].isna().sum()
        if n:
            say(f"- Lege waarden in {c}: {n}")
    for c in ["opk_ps23", "d66_ps23", "opk_tk23", "d66_tk23", "opk_tk25", "d66_tk25"]:
        bad = x[(x[c] < 0) | (x[c] > 1)]
        if len(bad):
            say(f"- {c} buiten 0-100%: {len(bad)} rijen, bv. {bad[['buurtcode', 'buurt', c]].head(3).to_dict('records')}")
    # Precision fingerprint: hints at values pasted from different sources.
    dec = x.d66_tk25.dropna().map(lambda v: len(repr(float(v)).split(".")[-1]))
    say(f"- Aantal decimalen in 'D66 % TK2025': {dec.clip(upper=6).value_counts().sort_index().to_dict()} (6 = 6 of meer)")
    implied = x.inwoners * x.opk_tk25 * x.d66_tk25
    say(f"- 'D66-stemmen TK2025' ≈ inwoners × opkomst × D66%: mediaan verhouding "
        f"{(x.d66_stemmen_tk25 / implied).median():.3f}")

    codes = set(ours.buurtcode)
    missing_in_ours = x[~x.buurtcode.isin(codes)]
    missing_in_x = ours[~ours.buurtcode.isin(set(x.buurtcode))]
    say(f"- Buurtcodes die niet in CBS-indeling 2025 (NH) staan: {len(missing_in_ours)}"
        + (f", bv. {missing_in_ours[['gemeente', 'buurt', 'buurtcode']].head(5).to_dict('records')}" if len(missing_in_ours) else ""))
    say(f"- CBS-buurten 2025 die in de spreadsheet ontbreken: {len(missing_in_x)} "
        f"({int(missing_in_x.inwoners.sum()):,} inwoners); per gemeente: "
        f"{missing_in_x.groupby('gemeentenaam').size().sort_values(ascending=False).head(8).to_dict()}")

    # 2. Gemeente totals vs official results --------------------------------
    m = x.merge(ours[["buurtcode", "gemeentecode"]], on="buurtcode", how="left")
    off = official_d66_per_gemeente()
    g = m.groupby("gemeentecode").agg(gemeente=("gemeente", "first"), stemmen=("d66_stemmen_tk25", "sum"),
                                       inw=("inwoners", "sum"))
    g = g.join(off)
    g["afwijking"] = g.stemmen / g.d66_stemmen_tk25 - 1
    say("\n## D66-stemmen TK2025 per gemeente: spreadsheet vs officiële uitslag")
    say(f"- Totaal NH: spreadsheet {int(g.stemmen.sum()):,} vs officieel {int(g.d66_stemmen_tk25.sum()):,} "
        f"({g.stemmen.sum() / g.d66_stemmen_tk25.sum() - 1:+.1%})")
    say("- Grootste afwijkingen:")
    for gm, r in g.reindex(g.afwijking.abs().sort_values(ascending=False).index).head(10).iterrows():
        say(f"  - {r.gemeente}: {int(r.stemmen):,} vs {int(r.d66_stemmen_tk25):,} ({r.afwijking:+.0%})")

    # 3. Buurt-level comparison with our estimates -----------------------
    j = x.merge(ours, on="buurtcode", how="inner", suffixes=("", "_cbs"))
    say(f"\n## Vergelijking per buurt met onze schatting ({len(j)} gekoppelde buurten)")
    rel = (j.inwoners_cbs >= 50)
    pairs = [("inwoners", "inwoners_cbs", "Inwoners (CBS 2025)"),
             ("d66_tk25", "d66_aandeel_tk25", "D66 % TK2025"),
             ("d66_ps23", "d66_aandeel_ps23", "D66 % PS2023"),
             ("d66_stemmen_tk25", "d66_kiezers_tk25", "D66-stemmen TK2025")]
    for a, b, label in pairs:
        s = j[rel & j[a].notna() & j[b].notna()]
        diff = s[a] - s[b]
        if a.startswith("d66_") and a != "d66_stemmen_tk25":
            say(f"- {label}: correlatie {s[a].corr(s[b]):.2f}, mediane afwijking {diff.abs().median() * 100:.1f} pp, "
                f"spreadsheet gemiddeld {diff.mean() * 100:+.1f} pp; >5 pp verschil: {(diff.abs() > .05).sum()} buurten")
        else:
            say(f"- {label}: correlatie {s[a].corr(s[b]):.2f}, mediane relatieve afwijking "
                f"{(diff.abs() / s[b].replace(0, np.nan)).median():.0%}; >25% verschil: "
                f"{((diff.abs() / s[b].replace(0, np.nan)) > .25).sum()} buurten")
    s = j[rel]
    say(f"- Buurtscore vs onze canvas-prioriteit: rangcorrelatie {s.score.rank().corr(s.canvas_score.rank()):.2f}; "
        f"vs D66 % TK2025: {s.score.rank().corr(s.d66_tk25.rank()):.2f}; vs inwoners: "
        f"{s.score.rank().corr(s.inwoners.rank()):.2f}; vs D66-stemmen: {s.score.rank().corr(s.d66_stemmen_tk25.rank()):.2f}")
    say("- Opkomst is niet vergeleken: onze opkomst per buurt is alleen indicatief.")

    j["verschil_d66_tk25_pp"] = (j.d66_tk25 - j.d66_aandeel_tk25) * 100
    j["verschil_d66_ps23_pp"] = (j.d66_ps23 - j.d66_aandeel_ps23) * 100
    j["verschil_inwoners"] = j.inwoners - j.inwoners_cbs
    say("\n### Grootste verschillen D66 % TK2025 (spreadsheet − onze schatting)")
    for _, r in j[rel].reindex(j[rel].verschil_d66_tk25_pp.abs().sort_values(ascending=False).index).head(12).iterrows():
        say(f"- {r.gemeente} / {r.buurt} ({r.buurtcode}): {r.d66_tk25:.1%} vs {r.d66_aandeel_tk25:.1%}")
    cols = ["gemeente", "wijk", "buurt", "buurtcode", "inwoners", "inwoners_cbs", "verschil_inwoners", "d66_tk25",
            "d66_aandeel_tk25", "verschil_d66_tk25_pp", "d66_ps23", "d66_aandeel_ps23", "verschil_d66_ps23_pp",
            "d66_stemmen_tk25", "d66_kiezers_tk25", "score", "canvas_score"]
    j[cols].to_csv(OUT / "vergelijking_spreadsheet.csv", index=False, float_format="%.4f")
    g.to_csv(OUT / "vergelijking_spreadsheet_gemeenten.csv", float_format="%.4f")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1])
