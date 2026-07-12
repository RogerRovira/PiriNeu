# Open points

Everything genuinely unresolved as of 2026-07-12, in one place. PLAN.md
tracks milestones; this is the working list of what still needs an answer,
who/what can answer it, and where the hook is in the code. Remove entries
as they close.

## Blocked until the first winter payloads (nothing to do until it snows)

1. **La Molina zone assignment (LOW confidence).** The Meteocat zonal
   endpoint has no geometry; `config.METEOCAT_ZONE_FOR_STATION` maps
   la_molina→6 "Vessant sud Prepirineu oriental", but zones 4 ("Pirineu
   oriental") and 8 ("Vessant sud Pirineu oriental") are plausible.
   - Data path: run `python verify_meteocat_zones.py` after a few snow
     episodes — it ranks zones by how well their `zonal.cota` tracks the
     La Tosa d'Alp isozero (needs ≥8 samples/zone).
   - Shortcut: open https://www.meteo.cat/prediccio/pirineu in a browser
     (blocked for non-browser agents) and read the zone off the map.
   - All zones are stored (`zona_<id>` pseudo-stations), so fixing this is
     a one-line config change — no re-ingestion.

2. **Units of Meteocat `acumulacioNeu` / `cota` valors.** Summer payloads
   omit the `valor`; presumed cm of snow and metres respectively.
   Confirm on the first snowfall, then implement
   `normalize.meteocat_bucket_to_swe_mm` (it currently raises, which makes
   the consensus Meteocat AMOUNT leg abstain — Alta confidence is
   unreachable until this closes because only 2 amount legs exist).

3. **AEMET fields 207 and 228.** Their `CAMPO` tags are mislabeled
   upstream ("press" for both). Ranges suggest 207 = snow (0.001–0.2,
   likely m) and 228 = gust (0–140, likely km/h). Confirm on a winter
   run by comparing `grid.f207` against snowfall events, then replace the
   provisional consensus snow gate (precip where pixel temp ≤ +1 °C,
   `consensus.AEMET_SNOW_MAX_TEMP_C`) with the real snow field.

4. **Derived isozero vs Meteocat isozero bias.** Expect ~100–200 m
   systematic difference on storm days; the consensus stores
   `leg.openmeteo.cota_m` and `leg.meteocat.cota_m` side by side every
   run, so the comparison accumulates by itself. Absorb the bias into
   `consensus.ISOZERO_TO_COTA_M` (currently a flat 300 m for both legs).

## Needs a decision or work (not weather-blocked)

5. **XEMA nowcast correction — the last v1 feature.** Blocked on choices:
   which XEMA stations represent each resort (codes, altitudes, variables),
   how to handle gauge undercatch (20–50 % in windy snowfall), and the
   API quota budget (polling multiplies calls; the ingest cache is
   committed to the datastore branch, so caching works across runs).
   Suggested timing: autumn, with a couple of months of collected data.

6. **Consensus priors are unverified.** Regime weights and confidence
   thresholds in `consensus.py` are hand-tuned. Before any calibration,
   fix the verification metrics (PLAN.md): MAE on 24 h accumulation,
   hit/false-alarm on snow days, cota error in metres. All inputs are
   already stored per run (`leg.*` variables + XEMA once it lands).

7. **Staleness / degraded-mode policy.** Current rule: a leg is excluded
   when its newest run is older than 30 h (`consensus.MAX_RUN_AGE_HOURS`),
   and confidence caps by leg count. Decide whether 2-of-3 should also be
   surfaced on the dashboard ("font X caiguda") rather than only in the
   per-leg table.

8. **Datastore branch growth.** ~10–12 MB/day in season (≈2 GB per
   winter), dominated by the 4 daily AEMET crops. Fine for season one;
   revisit (tighter `CROP_BOUNDS`, shallow history, squash, or object
   storage) before it gets unwieldy — new ADR when it happens.

9. **Elevation semantics (base/mid/top per resort).**
   `normalize.RESORT_ELEVATIONS_M` holds provisional public figures;
   `config.RESORTS` holds the canonical peak coordinates (DEM elevations
   2458/2710/2526 m). Decide the canonical per-band mapping across
   sources — affects how the dashboard eventually reports "neu a cota
   mitjana".

10. **License.** README TODO: pick one compatible with the non-commercial
    posture and the CC-BY/attribution constraints before publicising.

## Deployment watch items (no action unless they bite)

11. **Meteocat quota headroom.** The 13 UTC + 14 UTC double slot spends
    ~5 extra calls only when the committed HTTP cache misses; verify real
    consumption after a week (`/quotes` endpoint exists if needed).
12. **GitHub schedule suspension.** Schedules pause after 60 days without
    repo activity; datastore commits count as activity, but check the
    Actions tab if ingestion ever seems to stop.
13. **Cap de Vaquèira sits on the Aran/Pallars divide.** Its zone (1,
    north slope) is right for Baqueira's main sectors; if Bonaigua-side
    forecasts ever look off, that's why.
