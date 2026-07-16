# XEMA — catàleg de variables mesurades (dades "mesurades")

Font: API oficial de Meteocat, `GET /xema/v1/variables/mesurades/metadades`
(fetch 2026-07-16; payload arxivat a `data/raw/xema/2026/07/16/`).
90 variables al catàleg, codis dins el rang documentat [1–100] (més els
codis de prova 100–102).

Les dades **mesurades** són els registres de les estacions, amb el codi de
validació corresponent (`estat`), sense cap càlcul posterior; cada lectura
arriba amb `data` (UTC), `valor`, `estat` i `baseHoraria` (p. ex. `SH`
semi-horària). El recurs *Últimes dades* (finestra de les 4 hores prèvies)
serveix per obtenir només el darrer valor d'una variable a una EMA.

Ús al projecte: `xema_ingest.py` només persisteix els codis
**32 · 33 · 35 · 38** (marcats ✅) — la resta queda a l'arxiu cru i es pot
recuperar ampliant `VARIABLES` + `rebuild_db.py` (vegeu
`docs/data-report.md` §3.9). ❄ marca les variables amb interès potencial
per al nowcast/verificació de neu.

## Pressió atmosfèrica

| Codi | Nom | Unitat | Acrònim | |
|---|---|---|---|---|
| 1 | Pressió atmosfèrica màxima | hPa | Px | |
| 2 | Pressió atmosfèrica mínima | hPa | Pn | |
| 34 | Pressió atmosfèrica | hPa | P | ❄ diagnòstic d'inversions |

## Temperatura de l'aire

| Codi | Nom | Unitat | Acrònim | |
|---|---|---|---|---|
| 32 | Temperatura | °C | T | ✅ ingerida (`obs.temperatura`) |
| 40 | Temperatura màxima | °C | Tx | |
| 42 | Temperatura mínima | °C | Tn | |

## Humitat

| Codi | Nom | Unitat | Acrònim | |
|---|---|---|---|---|
| 3 | Humitat relativa màxima | % | HRx | |
| 33 | Humitat relativa | % | HR | ✅ ingerida (`obs.humitat`) |
| 44 | Humitat relativa mínima | % | HRn | |

## Precipitació

| Codi | Nom | Unitat | Acrònim | |
|---|---|---|---|---|
| 35 | Precipitació | mm | PPT | ✅ ingerida (`obs.precipitacio`) |
| 70 | Precipitació acumulada | mm | PPTacu | |
| 72 | Precipitació màxima en 1 minut | mm | PPTx1min | ❄ intensitat |
| 15 / 100 | Precipitació prova | mm | PPT2 | (canal de prova) |
| 16 / 101 | Precipitació màxima en 1 minut prova | mm | PPTx1min2 | (prova) |
| 17 / 102 | Precipitació acumulada prova | mm | PPTac2 | (prova) |

## Vent (tres altures: 10 m / 6 m / 2 m)

| Codi | Nom | Unitat | Acrònim | |
|---|---|---|---|---|
| 30 | Velocitat del vent a 10 m (esc.) | m/s | VV10 | ❄ correcció d'infracaptació del pluviòmetre; transport de neu |
| 31 | Direcció de vent 10 m (m. 1) | ° | DV10 | ❄ |
| 20 | Velocitat del vent a 10 m (vec.) | m/s | VV10vec | |
| 21 | Direcció del vent a 10 m (m. u) | ° | DV10u | |
| 22 | Desviació est. de la direcció del vent a 10 m | ° | DVdest10 | |
| 50 | Ratxa màxima del vent a 10 m | m/s | VVx10 | ❄ |
| 51 | Direcció de la ratxa màxima del vent a 10 m | ° | DVVx10 | |
| 48 | Velocitat del vent a 6 m (esc.) | m/s | VV6 | |
| 49 | Direcció del vent a 6 m (m. 1) | ° | DV6 | |
| 23 | Velocitat del vent a 6 m (vec.) | m/s | VV6vec | |
| 24 | Direcció del vent a 6 m (m. u) | ° | DV6u | |
| 25 | Desviació est. de la direcció de vent a 6 m | ° | DVdest6 | |
| 53 | Ratxa màxima del vent a 6 m | m/s | VVx6 | |
| 54 | Direcció de la ratxa màxima del vent a 6 m | ° | DVVx6 | |
| 46 | Velocitat del vent a 2 m (esc.) | m/s | VV2 | |
| 47 | Direcció del vent a 2 m (m. 1) | ° | DV2 | |
| 26 | Velocitat del vent a 2 m (vec.) | m/s | VV2vec | |
| 27 | Direcció del vent a 2 m (m. u) | ° | DV2u | |
| 28 | Desviació est. de la direcció del vent a 2 m | ° | DVdest2 | |
| 56 | Ratxa màxima del vent a 2 m | m/s | VVx2 | |
| 57 | Direcció de la ratxa màxima del vent a 2 m | ° | DVVx2 | |

## Neu ❄

| Codi | Nom | Unitat | Acrònim | |
|---|---|---|---|---|
| 38 | Gruix de neu a terra | cm | GNEU | ✅ ingerida (`obs.gruix_neu`) |
| 80–87 | Temperatura de la neu 1…8 | °C | TNEU1…TNEU8 | perfil tèrmic del mantell (estacions nivològiques) |

## Radiació

| Codi | Nom | Unitat | Acrònim | |
|---|---|---|---|---|
| 36 | Irradiància solar global | W/m² | RS | ❄ proxy de fusió (backlog) |
| 37 | Desviació est. de la irradiància solar global | W/m² | RSdest | |
| 59 | Irradiància neta | W/m² | RN | |
| 8 | Desviació estàndard de la irradiància neta | W/m² | RNdest | |
| 9 | Irradiància reflectida | W/m² | Ir | ❄ albedo → neu fresca vs vella |
| 10 | Irradiància fotosintèticament activa (PAR) | W/m² | PAR | |
| 39 | Radiació UV | MED/h | RUV | |

## Superfície i subsol

| Codi | Nom | Unitat | Acrònim | |
|---|---|---|---|---|
| 11 | Temperatura de superfície | °C | TSUP | |
| 12 | Temperatura màxima de superfície | °C | TSUPx | |
| 13 | Temperatura mínima de superfície | °C | TSUPn | |
| 60 | Temperatura de subsol a 5 cm | °C | TSUB5 | |
| 4 | Temperatura màxima de subsol a 5 cm | °C | TSUBx5 | |
| 5 | Temperatura mínima de subsol a 5 cm | °C | TSUBn5 | |
| 14 | Temperatura de subsol a 40 cm | °C | TSUB40 | |
| 61 | Temperatura de subsol a 50 cm | °C | TSUB50 | |
| 62 | TDR a 10 cm | %(1) | TDR10 | (humitat del sòl) |
| 63 | TDR a 35 cm | %(1) | TDR35 | |
| 6 | TDR màxima a 10 cm | %(1) | TDRx10 | |
| 7 | TDR mínima a 10 cm | %(1) | TDRn10 | |

## Humectació i combustible forestal (agro/incendis)

| Codi | Nom | Unitat | Acrònim |
|---|---|---|---|
| 64 | Humectació moll | %(1) | HMOLL |
| 65 | Humectació sec | %(1) | HSEC |
| 66 | Humectació res | Ohms | HRES |
| 67 | Humectació moll 2 | %(1) | HMOLL2 |
| 68 | Humectació sec 2 | %(1) | HSEC2 |
| 69 | Humectació res 2 | Ohms | HRES2 |
| 74 | Humitat del combustible forestal 1 | mV | HCF1 |
| 75 | Temperatura del combustible forestal 1 | mV | TCF1 |
| 76 | Humitat del combustible forestal 2 | mV | HCF2 |
| 77 | Temperatura del combustible forestal 2 | mV | TCF2 |
| 78 | Humitat del combustible forestal 3 | % | HCF3 |
| 79 | Temperatura del combustible forestal 3 | °C | TCF3 |

## Marines (boies / litoral — irrellevants per al projecte)

| Codi | Nom | Unitat | Acrònim |
|---|---|---|---|
| 90 | Altura màxima | cm | ALTx |
| 91 | Període màxima | s | PERx |
| 92 | Altura significant | cm | ALTsig |
| 93 | Període significant | s | PERsig |
| 94 | Altura mitjana | cm | ALTm |
| 95 | Període mitjà | s | PERm |
| 96 | Direcció del pic | ° | DPIC |
| 97 | Temperatura superficial del mar | °C | TMAR |

## Manteniment de l'estació (housekeeping)

| Codi | Nom | Unitat | Acrònim |
|---|---|---|---|
| 71 | Bateria | V | BAT |
| 88 | Quality number | %(1) | QN |
| 89 | Temperatura del datalogger | °C | TDLOG |

## Notes

- Cap estació mesura totes les variables: el subconjunt per estació surt de
  `GET /xema/v1/estacions/{codi}/variables/mesurades/metadades` (ja
  consultat per `xema_recon.py` per a les sis estacions del projecte).
  Recordatori: la Tosa d'Alp [ZD] no té pluviòmetre ni sensor de neu.
- La unitat `%(1)` és la notació del catàleg per a fraccions/percentatges
  d'escala pròpia (TDR, humectació, quality number).
- Els codis 100–102 dupliquen els canals "prova" 15–17 — ignorar-los.
- Cost API: aquest catàleg és metadata estable (1 crida del pla XEMA,
  cachejada 7 dies via `httpcache`); tornar-lo a consultar no afecta el
  pressupost de 750 crides/mes de forma apreciable.
- Els candidats ❄ d'incorporació immediata a `xema_ingest.VARIABLES`
  (cost API zero — el payload station-day ja els porta) són, per aquest
  ordre: 30/31 (vent 10 m, infracaptació), 50 (ratxa), 34 (pressió),
  36/9 (radiació/albedo, fase posterior). Vegeu `docs/data-report.md` §3.9.
