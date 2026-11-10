"""Validate the data-centre cooling part of S1/S2 against ESIF measured data (NLR, CC BY 4.0).

Scope (stated explicitly)
- Validated: data-centre non-IT power (cooling + HVAC + pumps + lights/plugs) and PUE as a function of
  measured IT power and outdoor temperature, for a warm-water liquid-cooled HPC data centre.
- NOT validated here: power-conversion (UPS) loss — ESIF's PUE boundary excludes it (checked: reported
  PUE == (IT + cooling + hvac + pump + plug) / IT); heat-pump COP; the S0 air-cooled baseline; ESS.

Method
1. Input: hourly means from prep_esif.py.
2. Cleaning rules (documented, applied in order): IT >= 100 kW; >= 30 samples in the hour;
   no component < -0.5 kW; reported PUE in [1.0, 1.5]; period 2016-06..2023-12 (2024 shows a
   configuration change: HVAC median ~9 kW -> ~167 kW).
3. Model (same structure as sim.py liquid cooling, with ESIF boundary):
     non_IT = base_kW + aux_frac * IT + chiller_power(IT, T_out, approach)
   Chiller power appears only when the dry cooler cannot reach the 30 °C supply temperature.
4. Before-calibration check with the v1 default assumptions, then calibration on 2016–2019 and an
   out-of-sample test on 2020–2023 (chronological split).
5. Error: MAPE and Bland–Altman (bias, 95 % LoA) of predicted vs measured non-IT power and PUE.
6. Measured heat reuse: reused_kW = (PUE - ERE) * IT, by year.

Usage: python validate_esif.py <esif_hourly.csv>
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import config as C
import sim

OUT = Path(__file__).parent / "results" / "validation"
COMP = ["cooling_kw", "hvac_kw", "pump_kw", "plug_and_light_kw"]


def clean(df):
    log = []
    m = pd.Series(True, index=df.index)
    for name, cond in [("IT >= 100 kW", df.it_power_kw >= 100),
                       ("coverage >= 30 samples/h", df.n_power_samples >= 30),
                       ("no component < -0.5 kW", (df[COMP] >= -0.5).all(axis=1)),
                       ("reported PUE in [1.0, 1.5]", df.pue.between(1.0, 1.5)),
                       ("period 2016-06..2023-12 (config change in 2024)", df.index < "2024-01-01")]:
        before = int(m.sum()); m &= cond; log.append((name, before - int(m.sum())))
    return df[m].copy(), log, len(df)


def model_non_it(it, t, base, aux, approach):
    p = C.LIQUID
    free = np.clip((p["return_c"] - (t + approach)) / (p["return_c"] - p["supply_c"]), 0, 1)
    cop = sim.chiller_cop(p["t_evap"], t, p["cond_approach"], p["cond_min"])
    return base + aux * it + it * (1 - free) / cop


def ba(pred, meas):
    d = pred - meas; sd = d.std(ddof=1)
    return dict(n=len(d), bias=d.mean(), loa_low=d.mean() - 1.96 * sd, loa_high=d.mean() + 1.96 * sd,
                mape_pct=float(np.mean(np.abs(d) / np.abs(meas)) * 100))


def evaluate(part, base, aux, appr):
    pred = model_non_it(part.it_power_kw.values, part.t_out_c.values, base, aux, appr)
    meas = part.non_it.values
    pue_p = 1 + pred / part.it_power_kw.values
    pue_m = 1 + meas / part.it_power_kw.values
    return ba(pred, meas), ba(pue_p, pue_m), pred


def main(path):
    OUT.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(path, index_col=0, parse_dates=True)
    raw["non_it"] = raw[COMP].sum(axis=1)
    pue_calc = (raw.it_power_kw + raw.non_it) / raw.it_power_kw
    df, log, n0 = clean(raw)
    boundary_p95 = float((df.pue - (1 + df.non_it / df.it_power_kw)).abs().quantile(0.95))

    train, test = df[df.index < "2020-01-01"], df[df.index >= "2020-01-01"]

    # v1 defaults (before calibration), mapped to the ESIF boundary: misc 2 % of IT as base, aux 3 % of heat
    v1 = dict(base=0.0, aux=C.MISC_FRACTION + C.LIQUID["aux_frac"] * (1 + C.MISC_FRACTION), appr=C.LIQUID["dry_cooler_approach"])
    best = None
    for base in np.arange(0, 60.1, 2.0):
        for aux in np.arange(0.0, 0.06, 0.001):
            for appr in np.arange(0.0, 15.1, 1.0):
                pred = model_non_it(train.it_power_kw.values, train.t_out_c.values, base, aux, appr)
                err = np.mean(np.abs(pred - train.non_it.values))
                if best is None or err < best[0]:
                    best = (err, base, aux, appr)
    _, base, aux, appr = best
    edge = base in (0.0, 60.0) or aux in (0.0, 0.059) or appr in (0.0, 15.0)

    # v1.1 structure: fan/pump power rises with outdoor temperature above T_FAN (dry/evap cooler works harder)
    # non_IT = base + aux*IT + k*IT*max(0, T - T_FAN) + chiller(approach); linear part by least squares
    T_FAN = 10.0
    def design(part):
        it, t = part.it_power_kw.values, part.t_out_c.values
        return np.column_stack([np.ones_like(it), it, it * np.clip(t - T_FAN, 0, None)])
    # ESIF has no compressor chiller (evaporative towers), so v1.1 drops the chiller term for this
    # validation: the model's chiller part is NOT validated by ESIF.
    coef2, *_ = np.linalg.lstsq(design(train), train.non_it.values, rcond=None)
    appr2 = None

    def predict_v11(part):
        return design(part) @ coef2

    v11_rows = {}
    for lbl, part in [("v1.1 · 2016–19 (보정 구간)", train), ("v1.1 · 2020–23 (검증 구간)", test)]:
        p_ = predict_v11(part); m_ = part.non_it.values; it_ = part.it_power_kw.values
        v11_rows[f"비IT 전력 kW · {lbl}"] = ba(p_, m_)
        v11_rows[f"PUE · {lbl}"] = ba(1 + p_ / it_, 1 + m_ / it_)

    rows = {}
    for lbl, part, prm in [("v1 기본 가정 · 2020–23", test, v1),
                           ("보정 · 2016–19 (보정 구간)", train, dict(base=base, aux=aux, appr=appr)),
                           ("보정 · 2020–23 (검증 구간)", test, dict(base=base, aux=aux, appr=appr))]:
        nit, pue, _ = evaluate(part, prm["base"], prm["aux"], prm["appr"])
        rows[f"비IT 전력 kW · {lbl}"] = nit
        rows[f"PUE · {lbl}"] = pue
    rows.update(v11_rows)
    res = pd.DataFrame(rows).T
    res.to_csv(OUT / "validation_summary.csv", encoding="utf-8-sig")

    df["reuse_kw"] = (df.pue - df.ere).clip(lower=0) * df.it_power_kw
    by_year = df.groupby(df.index.year).agg(hours=("it_power_kw", "size"), it_kw=("it_power_kw", "mean"),
                                            pue=("pue", "mean"), ere=("ere", "mean"), reuse_kw=("reuse_kw", "mean"))
    by_year["reuse_share_of_it_heat"] = by_year.reuse_kw / by_year.it_kw
    by_year.to_csv(OUT / "esif_heat_reuse_by_year.csv", encoding="utf-8-sig")

    _, _, pred_test = evaluate(test, base, aux, appr)
    test = test.assign(pred_v1=pred_test, pred_v11=predict_v11(test))
    tb = test.groupby(pd.cut(test.t_out_c, [-30, -10, 0, 10, 20, 25, 30, 40]), observed=True).agg(
        hours=("non_it", "size"), measured_kw=("non_it", "mean"), v1_kw=("pred_v1", "mean"), v11_kw=("pred_v11", "mean"))
    # Error breakdown (v1.1, test period): MAE, WAPE, Bias overall and by season / outdoor temp / IT load
    def err(g):
        e = g.pred_v11 - g.non_it
        return pd.Series(dict(hours=len(g), measured_kw=g.non_it.mean(), mae_kw=e.abs().mean(),
                              wape_pct=e.abs().sum() / g.non_it.abs().sum() * 100, bias_kw=e.mean(),
                              bias_pct=e.sum() / g.non_it.sum() * 100))
    season = test.index.month.map({12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
                                   6: "여름", 7: "여름", 8: "여름", 9: "가을", 10: "가을", 11: "가을"})
    tbin = pd.cut(test.t_out_c, [-30, 0, 10, 20, 30, 40], labels=["<0°C", "0–10°C", "10–20°C", "20–30°C", "≥30°C"])
    lbin = pd.qcut(test.it_power_kw, 4, labels=["IT 하위 25%", "25–50%", "50–75%", "IT 상위 25%"])
    parts = [pd.DataFrame({"전체": err(test)}).T.assign(group="전체")]
    for gname, key in [("계절", season), ("외기온도", tbin), ("IT 부하", lbin)]:
        g = test.groupby(key, observed=True).apply(err, include_groups=False).assign(group=gname)
        if gname == "계절": g = g.reindex(["봄", "여름", "가을", "겨울"]).assign(group=gname)
        parts.append(g)
    eb = pd.concat(parts); eb.index.name = "bin"
    eb.to_csv(OUT / "error_breakdown.csv", encoding="utf-8-sig")
    print(eb.round(2).to_string())

    test[["it_power_kw", "t_out_c", "non_it", "pred_v1", "pred_v11"]].to_csv(OUT / "test_hourly.csv", encoding="utf-8-sig")
    tb.to_csv(OUT / "test_by_outdoor_temp.csv", encoding="utf-8-sig")

    info = dict(rows_hourly=n0, rows_kept=len(df), cleaning=log, boundary_check_p95=boundary_p95,
                train_hours=len(train), test_hours=len(test),
                calibrated=dict(base_kw=base, aux_frac=aux, dry_cooler_approach_c=appr), calibration_at_edge=edge,
                v11=dict(base_kw=round(coef2[0], 3), aux_frac=round(coef2[1], 5),
                         fan_slope_per_C_above_10=round(coef2[2], 6), chiller="excluded (ESIF has none)"),
                v1_defaults=v1)
    pd.Series({k: str(v) for k, v in info.items()}).to_csv(OUT / "validation_info.csv", encoding="utf-8-sig", header=["value"])
    for k, v in info.items(): print(f"{k}: {v}")
    print(res.round(4).to_string()); print(by_year.round(3).to_string()); print(tb.round(2).to_string())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
