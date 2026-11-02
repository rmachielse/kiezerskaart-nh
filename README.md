# Kiezerskaart Noord-Holland

Interactieve kaart (`kaart.html`) met geschatte verkiezingsuitslagen per CBS-buurt in Noord-Holland
(PS2023, TK2025, GR2026) en D66-campagnescores voor de Provinciale Statenverkiezingen.

## Openen

```bash
open kaart.html
```

De kaart laadt `data/processed/data.js` en haalt MapLibre en de PDOK-achtergrondkaart online op.

## Opnieuw bouwen

```bash
mise exec uv@0.13.5 -- uv run python scripts/fetch_cbs.py   # CBS buurten 2025 via PDOK
mise exec uv@0.13.5 -- uv run python scripts/build.py       # schattingen + data.js
```

Ruwe bronnen in `data/raw/`:

- `openstate/2025tk.geo.json`, `openstate/2023ps.geo.json`: uitslag per stembureau met coördinaten
  ([Open State](https://data.openstate.eu/id/group/verkiezingen) / de Volkskrant).
- `kiesraad/GR2026_eml/`: Kiesraad EML-tellingen GR2026
  ([data.overheid.nl](https://data.overheid.nl/dataset/verkiezingsuitslagen-gemeenteraad-2026)). Stembureaus zijn
  gelokaliseerd door ze op postcode te koppelen aan TK2025/PS2023, met PDOK Locatieserver als terugval.
- `cbs/`: CBS Wijken en Buurten 2025 (PDOK OGC API).

## Methode (kort)

1. Per gemeente: Voronoi-gebieden rond de stembureaulocaties, bijgesneden tot de gemeentegrens.
2. De stemmen van elk gebied worden over de overlappende buurten verdeeld naar rato van het aantal inwoners.
3. Absolute D66-kiezers = aandeel in de buurt × volwassen inwoners × opkomst in de gemeente. Zo vertekenen
   stembureaus op stations en in centra (stempas) de aantallen niet.
4. Mobiliseerbaar = D66-kiezers TK2025 × (1 − PS/TK-stemverhouding per wijk, getrokken richting het gemeentegemiddelde).
5. Canvas-prioriteit = √(mobiliseerbaar × mobiliseerbaar per 100 huishoudens).

Alles is een schatting op buurtniveau. Er staan geen gegevens over individuele kiezers in.

## Partijdata

De kaart heeft een bronkeuze: publieke data of de spreadsheet van de partij. Die laatste zet je zo om:

```bash
mise exec uv@0.13.5 -- uv run python scripts/build_partij.py "D66-buurten NH (conceptversie).xlsx"
```

Dit maakt `data/processed/partij_buurten.json` (de spreadsheet als JSON) en `partij_data.js` (wordt door de kaart geladen;
ontbreekt het bestand, dan staat alleen publieke data aan). Met `scripts/compare_xlsx.py` vergelijk je de spreadsheet met
onze eigen schattingen.

## Gebruik

**Per afdeling** (startscherm): de D66-afdelingen gerangschikt op wat er te winnen valt voor de gekozen actie, bijvoorbeeld
het aantal thuisblijvende D66-kiezers voor deur-aan-deur. Klik op een afdeling om naar de buurten te gaan.

**Per buurt**: kies een afdeling en een actie (deur-aan-deur, flyeren & events, achterban). Per selectie is de top 10% van
de buurten prioriteit 1 en de volgende 20% prioriteit 2. Aangrenzende buurten met prioriteit 1 worden samengevoegd tot
werkgebieden. Onder "Verkennen" staan alle losse kaartlagen.

De indeling van gemeenten in afdelingen staat in `data/afdelingen.csv`, overgenomen uit het
[D66NH-overzicht van regio's en afdelingen (2023)](https://d66.nl/noordholland/wp-content/uploads/sites/340/2023/09/D66NH-regioverdeling-2023-def.pdf).
Na een wijziging:

```bash
mise exec uv@0.13.5 -- uv run python scripts/build_afdelingen.py
```
