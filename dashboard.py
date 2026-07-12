"""Static dashboard generator (ADR-0003): SQLite consensus -> plain HTML.

Renders an index with the three resort cards plus one page per resort,
showing for today and tomorrow the consensus new snow (cm, with the SWE mm
it derives from), the snow line, the confidence label and the per-leg
values behind the blend — honesty about disagreement is the product.
UTC-only storage; Europe/Madrid appears only here (project convention).
The mandatory attributions (Open-Meteo CC-BY, AEMET, Meteocat) are on
every page.

Usage: python dashboard.py [--out DIR]   (default: data/site)
"""
import argparse
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import db
from config import DATA_DIR, ISO_UTC, RESORTS
from normalize import OPENMETEO_SNOW_CM_PER_SWE_MM

LOCAL_TZ = ZoneInfo("Europe/Madrid")
CONFIDENCE_LABELS = {2.0: "Alta", 1.0: "Mitjana", 0.0: "Baixa"}
REGIME_LABELS = {0.0: "flux del nord", 1.0: "flux del sud/est", 2.0: "mixt"}
RESORT_NAMES = {"baqueira": "Baqueira Beret", "boi_taull": "Boí Taüll",
                "la_molina": "La Molina"}
LEG_NAMES = {"openmeteo": "AROME (Open-Meteo)", "aemet": "AEMET",
             "meteocat": "Meteocat"}

STYLE = """
body{font-family:system-ui,sans-serif;margin:0;background:#f4f7fa;color:#123}
main{max-width:60rem;margin:0 auto;padding:1rem}
h1{font-size:1.4rem} h2{font-size:1.15rem;margin:.2rem 0}
.card{background:#fff;border-radius:10px;padding:1rem;margin:1rem 0;
      box-shadow:0 1px 3px rgba(0,0,0,.12)}
.blocks{display:flex;gap:1rem;flex-wrap:wrap}
.block{flex:1;min-width:14rem;border:1px solid #dde5ec;border-radius:8px;
       padding:.7rem}
.snow{font-size:1.6rem;font-weight:700}
.badge{display:inline-block;padding:.15rem .6rem;border-radius:99px;
       font-size:.8rem;font-weight:600;color:#fff}
.alta{background:#1a7f37}.mitjana{background:#b58105}.baixa{background:#a40e26}
table{border-collapse:collapse;font-size:.85rem;margin-top:.5rem;width:100%}
td,th{border-bottom:1px solid #e4eaf0;padding:.25rem .4rem;text-align:left}
footer{font-size:.75rem;color:#456;padding:1rem;line-height:1.5}
a{color:#0757a5}.muted{color:#678;font-size:.85rem}
"""

ATTRIBUTION = (
    '<footer><p>Predicció no oficial, sense garanties — consulteu les fonts '
    'oficials abans de sortir a la muntanya.</p>'
    '<p>Dades: <a href="https://open-meteo.com/">Open-Meteo</a> '
    '(<a href="https://creativecommons.org/licenses/by/4.0/">CC-BY 4.0</a>) · '
    '<a href="https://www.aemet.es/">AEMET</a> (© AEMET, ús autoritzat '
    'citant-ne l\'autoria) · '
    '<a href="https://www.meteo.cat/">Servei Meteorològic de Catalunya '
    '(Meteocat)</a>. Projecte no comercial.</p></footer>')


def _load_latest(conn) -> Dict:
    run = conn.execute("SELECT MAX(run_time_utc) FROM forecast_values "
                       "WHERE source='consensus'").fetchone()[0]
    data: Dict = {"run": run, "resorts": {}}
    if run is None:
        return data
    for station, day, variable, value in conn.execute(
            """SELECT station, valid_time_utc, variable, value
               FROM forecast_values WHERE source='consensus'
                 AND run_time_utc=?""", (run,)):
        data["resorts"].setdefault(station, {}).setdefault(day, {})[variable] \
            = value
    return data


def _fmt_snow(swe_mm: Optional[float]) -> str:
    if swe_mm is None:
        return "sense dades"
    cm = swe_mm * OPENMETEO_SNOW_CM_PER_SWE_MM
    if swe_mm < 0.5:
        return "0 cm"
    return f"{cm:.0f}&thinsp;cm <span class='muted'>({swe_mm:.0f} mm eq.)</span>"


def _block_html(day: str, values: Dict[str, float]) -> str:
    snow = values.get("snow_swe_mm")
    conf = CONFIDENCE_LABELS.get(values.get("confidence"), "Baixa")
    regime = REGIME_LABELS.get(values.get("regime"), "mixt")
    cota = values.get("cota_m")
    cota_html = (f"cota de neu ~{cota:.0f}&thinsp;m" if cota is not None
                 and (snow or 0) >= 0.5 else "sense neu prevista")
    legs = []
    for leg, name in LEG_NAMES.items():
        s = values.get(f"leg.{leg}.snow_swe_mm")
        c = values.get(f"leg.{leg}.cota_m")
        legs.append(f"<tr><td>{name}</td>"
                    f"<td>{'—' if s is None else f'{s:.1f} mm'}</td>"
                    f"<td>{'—' if c is None else f'{c:.0f} m'}</td></tr>")
    return f"""<div class="block">
  <h3>{html.escape(day)}</h3>
  <div class="snow">{_fmt_snow(snow)}</div>
  <div>{cota_html}</div>
  <p>Confiança: <span class="badge {conf.lower()}">{conf}</span>
     <span class="muted">· règim: {regime}</span></p>
  <table><tr><th>Font</th><th>Neu nova (SWE)</th><th>Cota</th></tr>
  {''.join(legs)}</table>
</div>"""


def _page(title: str, body: str, generated_at: Optional[str]) -> str:
    stamp = ""
    if generated_at:
        local = datetime.strptime(generated_at, ISO_UTC).replace(
            tzinfo=timezone.utc).astimezone(LOCAL_TZ)
        stamp = (f"<p class='muted'>Actualitzat "
                 f"{local.strftime('%d/%m/%Y %H:%M')} (hora local)</p>")
    return f"""<!doctype html><html lang="ca"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{STYLE}</style></head><body>
<main><h1>{html.escape(title)}</h1>{stamp}{body}</main>
{ATTRIBUTION}</body></html>"""


def _resort_card(station: str, days: Dict[str, Dict], link: bool) -> str:
    name = RESORT_NAMES.get(station, station)
    title = (f'<a href="{station}.html">{html.escape(name)}</a>'
             if link else html.escape(name))
    blocks = "".join(_block_html(d, days[d]) for d in sorted(days))
    return (f'<div class="card"><h2>{title}</h2>'
            f'<div class="blocks">{blocks}</div></div>')


def generate(out_dir: Path, conn=None) -> Path:
    conn = conn or db.connect()
    data = _load_latest(conn)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not data["resorts"]:
        body = "<p>Encara no hi ha consens calculat.</p>"
        (out_dir / "index.html").write_text(
            _page("Previsió de neu al Pirineu català", body, None),
            encoding="utf-8")
        return out_dir

    cards = [_resort_card(r["station"], data["resorts"][r["station"]], True)
             for r in RESORTS if r["station"] in data["resorts"]]
    (out_dir / "index.html").write_text(
        _page("Previsió de neu al Pirineu català (48 h)", "".join(cards),
              data["run"]), encoding="utf-8")

    for r in RESORTS:
        station = r["station"]
        if station not in data["resorts"]:
            continue
        card = _resort_card(station, data["resorts"][station], False)
        back = '<p><a href="index.html">&larr; Totes les estacions</a></p>'
        (out_dir / f"{station}.html").write_text(
            _page(f"Previsió de neu — {RESORT_NAMES.get(station, station)}",
                  card + back, data["run"]), encoding="utf-8")
    return out_dir


if __name__ == "__main__":
    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument("--out", default=DATA_DIR / "site", type=Path)
    args = argp.parse_args()
    path = generate(args.out)
    print(f"dashboard: wrote {sorted(p.name for p in path.glob('*.html'))} "
          f"to {path}")
