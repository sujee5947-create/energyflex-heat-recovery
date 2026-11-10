"""Full factorial of the four measures (2^4 = 16 combinations), same workload and heat demand.

A = efficient cooling (warm-water liquid + dry-cooler free cooling) instead of air + chiller
B = high-efficiency power conversion (97 % instead of 94 %)
C = heat-pump waste-heat recovery to the neighbouring heat demand (source temp depends on A)
D = ESS peak shaving (degradation-aware SOC 20–90 %), threshold = lowest peak it can hold all year
"""
from itertools import product
from pathlib import Path
import numpy as np
import pandas as pd
import config as C
import sim

OUT = Path(__file__).parent / "results" / "combos"


def min_peak(base, sc, iters=30):
    o, _ = sim.simulate(base, dict(sc, ess=False))
    lo, hi = o.site_load.max() - C.ESS_KW, o.site_load.max()
    for _ in range(iters):
        mid = (lo + hi) / 2
        g, *_ = sim.run_ess(o.site_load.values, mid, C.ESS_SOC_MIN, C.ESS_SOC_MAX)
        lo, hi = (lo, mid) if g.max() <= mid + 1e-6 else (mid, hi)
    return hi


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    base = sim.climate_and_load()
    rows, checks = [], {}
    for a, b, c, d in product([0, 1], repeat=4):
        code = "".join(l for l, on in zip("ABCD", (a, b, c, d)) if on) or "없음(S0)"
        sc = dict(cooling="liquid" if a else "air", ups_eff=0.97 if b else 0.94, heat_pump=bool(c), ess=bool(d))
        thr = min_peak(base, sc) if d else None
        o, info = sim.simulate(base, sc, peak_threshold=thr)
        m = sim.metrics(o, info)
        chk = sim.checks(o, sc); checks[code] = max(abs(v) for v in chk.values())
        rows.append(dict(combo=code, A=a, B=b, C=c, D=d,
                         dc_kwh_per_job=m["dc_kwh_per_job"], facility_elec_mwh=m["facility_elec_kwh"] / 1e3,
                         cooling_mwh=m["cooling_kwh"] / 1e3, conversion_loss_mwh=m["conversion_loss_kwh"] / 1e3,
                         heat_pump_mwh=m["heat_pump_kwh"] / 1e3, boiler_fuel_mwh=m["boiler_fuel_kwh"] / 1e3,
                         ess_loss_mwh=m["ess_loss_kwh"] / 1e3, final_mwh=m["total_final_energy_kwh"] / 1e3,
                         primary_mwh=m["primary_energy_kwh"] / 1e3, peak_kw=m["peak_kw"], pue=m["pue"],
                         hp_cop=sim.hp_cop(sim.hp_source(sc["cooling"])[0]) if c else np.nan,
                         ess_fade_pct=(info["total_fade"] * 100) if info else np.nan))
    df = pd.DataFrame(rows)
    s0 = df[df.combo == "없음(S0)"].iloc[0]
    for col, key in [("final_mwh", "final"), ("primary_mwh", "primary"), ("facility_elec_mwh", "elec"),
                     ("dc_kwh_per_job", "job")]:
        df[f"{key}_cut_pct"] = (1 - df[col] / s0[col]) * 100          # reduction vs no measures
        df[f"{key}_eff_gain_pct"] = (s0[col] / df[col] - 1) * 100      # same output per energy: efficiency gain
    df["peak_cut_kw"] = s0.peak_kw - df.peak_kw
    df.to_csv(OUT / "combinations_16.csv", index=False, encoding="utf-8-sig")

    # Single-measure effects vs on-top-of-others, and interactions (final energy, MWh saved)
    eff = {}
    get = lambda **k: df[(df[list(k)] == pd.Series(k)).all(axis=1)].final_mwh.mean()
    for m in "ABCD":
        others = [x for x in "ABCD" if x != m]
        alone = s0.final_mwh - get(**{m: 1, **{o: 0 for o in others}})
        on_top = get(**{m: 0, **{o: 1 for o in others}}) - get(**{m: 1, **{o: 1 for o in others}})
        avg = (df[df[m] == 0].final_mwh.mean() - df[df[m] == 1].final_mwh.mean())
        eff[m] = dict(alone_mwh=alone, on_top_of_others_mwh=on_top, average_effect_mwh=avg)
    eff = pd.DataFrame(eff).T
    eff.to_csv(OUT / "measure_effects.csv", encoding="utf-8-sig")
    inter_ac = (get(A=0, B=0, C=0, D=0) - get(A=1, B=0, C=1, D=0)) - \
               ((get(A=0, B=0, C=0, D=0) - get(A=1, B=0, C=0, D=0)) + (get(A=0, B=0, C=0, D=0) - get(A=0, B=0, C=1, D=0)))
    return df, eff, inter_ac, checks


if __name__ == "__main__":
    import warnings; warnings.simplefilter("error")
    df, eff, inter_ac, checks = run()
    pd.set_option("display.width", 250)
    cols = ["combo", "dc_kwh_per_job", "facility_elec_mwh", "final_mwh", "primary_mwh", "peak_kw", "hp_cop",
            "final_cut_pct", "final_eff_gain_pct", "primary_cut_pct", "primary_eff_gain_pct", "elec_cut_pct", "job_eff_gain_pct", "ess_loss_mwh"]
    print(df.sort_values("final_mwh")[cols].round(3).to_string(index=False))
    print(eff.round(1)); print("A×C interaction (MWh, + = synergy):", round(inter_ac, 1))
    print("max balance residual:", max(checks.values()))
