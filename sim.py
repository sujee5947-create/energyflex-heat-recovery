"""Hourly energy simulation: same AI workload, different cooling / heat-recovery / ESS configurations.

Principle: compare scenarios at identical workload; minimise consumed and discarded energy.
No electricity price enters any decision. ESS shifts timing only and its losses are counted.
"""
import numpy as np
import pandas as pd
import config as C

K = 273.15


def climate_and_load(seed=7):
    rng = np.random.default_rng(seed)
    h = np.arange(C.HOURS)
    day = h / 24.0
    hod = h % 24
    t_out = (C.T_MEAN - C.T_SEASON_AMP * np.cos(2 * np.pi * (day - 15) / 365)
             + C.T_DAY_AMP * np.sin(2 * np.pi * (hod - 9) / 24)
             + rng.normal(0, C.T_NOISE_SD, C.HOURS))
    util = np.clip(C.UTIL_MEAN + C.UTIL_DAY_AMP * np.sin(2 * np.pi * (hod - 8) / 24)
                   + rng.normal(0, 0.03, C.HOURS), 0.3, 1.0)
    it_kw = C.IT_CAPACITY_KW * (C.IT_IDLE_FRACTION + (1 - C.IT_IDLE_FRACTION) * util)
    jobs = util * C.JOBS_PER_UTIL_HOUR
    dhw = np.where((hod >= 6) & (hod < 22), C.DHW_KW_DAY, C.DHW_KW_NIGHT)
    heat_demand = C.HEAT_UA_KW_PER_K * np.clip(C.HEAT_BALANCE_T - t_out, 0, None) + dhw
    return pd.DataFrame(dict(hour=h, t_out=t_out, util=util, it_kw=it_kw, jobs=jobs,
                             heat_demand_kw=heat_demand))


def chiller_cop(t_evap, t_out, approach, cond_min):
    t_cond = np.maximum(t_out, cond_min) + approach
    return C.CARNOT_FRACTION_CHILLER * (t_evap + K) / (t_cond - t_evap)


def hp_cop(evap_c=None):
    evap_c = C.HP_SOURCE_EVAP_C if evap_c is None else evap_c
    return C.CARNOT_FRACTION_HP * (C.HP_SINK_COND_C + K) / (C.HP_SINK_COND_C - evap_c)


def hp_source(cooling):
    """(evaporator °C, source water °C): warm-water liquid loop vs air-cooled room return water."""
    if cooling == "liquid":
        return C.HP_SOURCE_EVAP_C, C.LIQUID["return_c"]
    return C.AIR_HP_SOURCE_EVAP_C, C.AIR_HP_SOURCE_RETURN_C


def run_ess(load_kw, threshold, soc_min, soc_max):
    """Peak shaving only: discharge above threshold, recharge below it. Returns grid draw and ESS log."""
    cap = C.ESS_KWH
    e = cap * soc_max
    grid = load_kw.copy()
    ch = np.zeros_like(load_kw); dis = np.zeros_like(load_kw); soc = np.zeros_like(load_kw)
    for i, L in enumerate(load_kw):
        if L > threshold:
            d = min(C.ESS_KW, L - threshold, (e - cap * soc_min) * C.ESS_ETA_DIS)
            dis[i] = d; e -= d / C.ESS_ETA_DIS
        elif e < cap * soc_max:
            c = min(C.ESS_KW, threshold - L, (cap * soc_max - e) / C.ESS_ETA_CH)
            ch[i] = c; e += c * C.ESS_ETA_CH
        soc[i] = e / cap
        grid[i] = L - dis[i] + ch[i]
    return grid, ch, dis, soc


def degradation(soc, dis):
    """Simple fade estimate: per-day equivalent full cycles weighted by DoD stress + calendar fade."""
    days = len(soc) // 24
    s = soc[:days * 24].reshape(days, 24)
    d = dis[:days * 24].reshape(days, 24).sum(axis=1)
    efc = d / C.ESS_ETA_DIS / C.ESS_KWH
    dod = s.max(axis=1) - s.min(axis=1)
    cycle_fade = np.sum(efc * C.FADE_PER_EFC_AT_80DOD * (np.clip(dod, 0, 1) / 0.8) ** C.DOD_STRESS_EXP)
    return dict(efc=efc.sum(), mean_daily_dod=dod[efc > 0].mean() if (efc > 0).any() else 0.0,
                cycle_fade=cycle_fade, calendar_fade=C.CALENDAR_FADE_PER_YEAR,
                total_fade=cycle_fade + C.CALENDAR_FADE_PER_YEAR)


def simulate(base, sc, peak_threshold=None, ess_window=None):
    df = base.copy()
    it = df.it_kw.values
    conv_loss = it * (1 / sc["ups_eff"] - 1)
    misc = it * C.MISC_FRACTION
    q_cool = it + conv_loss + misc                      # all electrical power in the room becomes heat
    t_out = df.t_out.values

    # Heat-recovery stages: generated (q_cool) -> recoverable (capacity/source limit) -> recovered
    # (heat pump evaporator) -> useful (delivered to users after pipe loss, never above demand)
    q_hp_evap = np.zeros(C.HOURS); q_hp = np.zeros(C.HOURS); w_hp = np.zeros(C.HOURS)
    q_recoverable = np.zeros(C.HOURS); q_useful = np.zeros(C.HOURS); q_pipe_loss = np.zeros(C.HOURS)
    if sc["heat_pump"]:
        cop_hp = hp_cop(hp_source(sc["cooling"])[0])
        keep = 1 - C.PIPE_LOSS_FRAC
        q_recoverable = np.minimum(q_cool, C.HP_MAX_HEAT_KW * (1 - 1 / cop_hp))   # evaporator-side potential
        q_hp = np.minimum.reduce([df.heat_demand_kw.values / keep, np.full(C.HOURS, C.HP_MAX_HEAT_KW),
                                  q_cool / (1 - 1 / cop_hp)])                     # heat pump output
        w_hp = q_hp / cop_hp
        q_hp_evap = q_hp - w_hp                          # heat taken out of the cooling loop
        q_useful = q_hp * keep
        q_pipe_loss = q_hp - q_useful
    q_reject = q_cool - q_hp_evap

    if sc["cooling"] == "air":
        p = C.AIR
        free_frac = (t_out < p["free_cool_below"]).astype(float)
        cop = chiller_cop(p["t_evap"], t_out, p["cond_approach"], p["cond_min"])
    else:
        p = C.LIQUID
        t_reach = t_out + p["dry_cooler_approach"]        # temperature the dry cooler can reach
        free_frac = np.clip((p["return_c"] - t_reach) / (p["return_c"] - p["supply_c"]), 0, 1)
        cop = chiller_cop(p["t_evap"], t_out, p["cond_approach"], p["cond_min"])
    q_free = q_reject * free_frac
    q_chiller = q_reject - q_free
    w_chiller = q_chiller / cop
    w_aux = p["aux_frac"] * q_cool
    w_cooling = w_chiller + w_aux

    q_boiler = df.heat_demand_kw.values - q_useful
    fuel = q_boiler / C.BOILER_EFF

    dc_elec = it + conv_loss + misc + w_cooling          # data-centre electricity (excl. heat pump)
    site_load = dc_elec + w_hp

    out = df.assign(conv_loss=conv_loss, misc=misc, q_cool=q_cool, q_free=q_free, q_chiller=q_chiller,
                    q_hp_evap=q_hp_evap, q_hp=q_hp, w_hp=w_hp, q_recoverable=q_recoverable,
                    q_useful=q_useful, q_pipe_loss=q_pipe_loss, w_chiller=w_chiller, w_aux=w_aux,
                    w_cooling=w_cooling, q_boiler=q_boiler, fuel=fuel, dc_elec=dc_elec,
                    site_load=site_load, ess_ch=0.0, ess_dis=0.0, soc=np.nan, grid=site_load)
    ess_info = None
    out.attrs["soc_start"] = None
    out.attrs["hp_src_c"] = hp_source(sc["cooling"])[1]
    if sc["ess"]:
        lo, hi = ess_window or (C.ESS_SOC_MIN, C.ESS_SOC_MAX)
        out.attrs["soc_start"] = hi
        grid, ch, dis, soc = run_ess(site_load, peak_threshold, lo, hi)
        out["ess_ch"], out["ess_dis"], out["soc"], out["grid"] = ch, dis, soc, grid
        ess_info = degradation(soc, dis)
    return out, ess_info


def checks(o, sc):
    """Energy-balance checks (kW, per hour). Returns max absolute residual for each balance."""
    r = {}
    r["cooling_balance"] = np.abs(o.q_cool - (o.q_free + o.q_chiller + o.q_hp_evap)).max()
    r["heat_balance"] = np.abs(o.heat_demand_kw - (o.q_useful + o.q_boiler)).max()
    r["pipe_balance"] = np.abs(o.q_hp - (o.q_useful + o.q_pipe_loss)).max()
    r["useful_le_demand"] = float(max(0.0, (o.q_useful - o.heat_demand_kw).max()))
    r["hp_balance"] = np.abs(o.q_hp - (o.q_hp_evap + o.w_hp)).max()
    r["grid_balance"] = np.abs(o.grid - (o.site_load - o.ess_dis + o.ess_ch)).max()
    r["nonneg"] = float(min(o.q_free.min(), o.q_chiller.min(), o.q_boiler.min(), o.q_hp_evap.min()))
    if sc["ess"]:
        e = o.soc.values * C.ESS_KWH
        start = C.ESS_KWH * o.attrs["soc_start"]
        de = np.diff(np.concatenate([[start], e]))
        r["ess_balance"] = np.abs(de - (o.ess_ch * C.ESS_ETA_CH - o.ess_dis / C.ESS_ETA_DIS)).max()
    return r


def same_service(outs):
    """Every case must deliver the same services hour by hour: AI jobs, server heat removed, heat delivered."""
    names = list(outs); ref = outs[names[0]]
    res = {}
    for n in names:
        o = outs[n]
        res[n] = dict(
            jobs_diff=float(np.abs(o.jobs - ref.jobs).max()),
            it_heat_diff=float(np.abs(o.it_kw - ref.it_kw).max()),
            server_heat_removed_gap=float(np.abs(o.q_cool - (o.q_free + o.q_chiller + o.q_hp_evap)).max()),
            heat_delivered_diff=float(np.abs((o.q_useful + o.q_boiler) - ref.heat_demand_kw).max()))
    worst = max(v for d in res.values() for v in d.values())
    return res, worst


def metrics(o, ess_info):
    T0 = o.t_out + K
    T_hw = C.HOT_WATER_SUPPLY_C + K
    ex_heat_delivered = (o.heat_demand_kw * (1 - T0 / T_hw)).sum()   # same heat service in every case
    T_src = o.attrs.get("hp_src_c", C.LIQUID["return_c"]) + K
    ex_waste_used = (o.q_hp_evap * np.clip(1 - T0 / T_src, 0, None)).sum()
    ex_for_heating = o.fuel.sum() + o.w_hp.sum() + ex_waste_used
    ess_loss = (o.ess_ch.sum() - o.ess_dis.sum()
                - ((o.soc.iloc[-1] - o.attrs["soc_start"]) * C.ESS_KWH if o.attrs.get("soc_start") else 0.0))
    grid_elec = o.grid.sum()
    fuel = o.fuel.sum()
    m = {
        "jobs": o.jobs.sum(),
        "it_kwh": o.it_kw.sum(),
        "dc_kwh_per_job": o.dc_elec.sum() / o.jobs.sum(),
        "facility_elec_kwh": grid_elec,
        "cooling_kwh": o.w_cooling.sum(),
        "conversion_loss_kwh": o.conv_loss.sum(),
        "ess_loss_kwh": ess_loss,
        "heat_pump_kwh": o.w_hp.sum(),
        "heat_recovered_kwh": o.q_hp.sum(),
        "heat_generated_kwh": o.q_cool.sum(),
        "heat_recoverable_kwh": o.q_recoverable.sum(),
        "heat_extracted_kwh": o.q_hp_evap.sum(),
        "heat_useful_kwh": o.q_useful.sum(),
        "pipe_loss_kwh": o.q_pipe_loss.sum(),
        "dc_elec_kwh": o.dc_elec.sum(),
        "pue_incl_hp": (o.dc_elec.sum() + o.w_hp.sum()) / o.it_kw.sum(),
        "boiler_fuel_kwh": fuel,
        "boiler_fuel_displaced_kwh": None,   # filled vs baseline later
        "peak_kw": o.grid.max(),
        "pue": o.dc_elec.sum() / o.it_kw.sum(),
        "erf": o.q_useful.sum() / o.dc_elec.sum(),
        "total_final_energy_kwh": grid_elec + fuel,
        "primary_energy_kwh": C.PEF_ELEC * grid_elec + C.PEF_GAS * fuel,
        "exergy_input_kwh": grid_elec + fuel,          # electricity and gas ≈ pure exergy (approx.)
        "heat_exergy_delivered_kwh": ex_heat_delivered,
        "heating_exergy_efficiency": ex_heat_delivered / ex_for_heating,
    }
    if ess_info:
        m.update({f"ess_{k}": v for k, v in ess_info.items()})
    return m


def min_feasible_peak(base, win, iters=40):
    """Lowest grid peak (kW) this ESS window can hold all year (binary search)."""
    s2, _ = simulate(base, C.SCENARIOS["S2_HeatRecovery"])
    lo, hi = s2.site_load.max() - C.ESS_KW, s2.site_load.max()
    for _ in range(iters):
        mid = (lo + hi) / 2
        o, _ = simulate(base, C.SCENARIOS["S3_HR_ESS"], peak_threshold=mid, ess_window=win)
        if o.grid.max() <= mid + 1e-6: hi = mid
        else: lo = mid
    return hi


def run_all():
    base = climate_and_load()
    results, outs, chk = {}, {}, {}
    # threshold from S2 (the configuration ESS is added to)
    thr = min_feasible_peak(base, (C.ESS_SOC_MIN, C.ESS_SOC_MAX))
    for name, sc in C.SCENARIOS.items():
        o, info = simulate(base, sc, peak_threshold=thr)
        outs[name], results[name], chk[name] = o, metrics(o, info), checks(o, sc)
    b = results["S0_Baseline"]["boiler_fuel_kwh"]
    for r in results.values():
        r["boiler_fuel_displaced_kwh"] = b - r["boiler_fuel_kwh"]
    # ESS window comparison: degradation-aware vs aggressive
    ess_cmp = {}
    for lbl, win in {"열화 고려 (SOC 20–90%)": (0.20, 0.90), "공격적 (SOC 5–100%)": (0.05, 1.00)}.items():
        t = min_feasible_peak(base, win)
        o, info = simulate(base, C.SCENARIOS["S3_HR_ESS"], peak_threshold=t, ess_window=win)
        m = metrics(o, info)
        ess_cmp[lbl] = dict(peak_kw=m["peak_kw"], peak_cut_kw=simulate(base, C.SCENARIOS["S2_HeatRecovery"])[0].site_load.max() - m["peak_kw"], ess_loss_kwh=m["ess_loss_kwh"], efc=info["efc"],
                            mean_daily_dod=info["mean_daily_dod"], cycle_fade=info["cycle_fade"],
                            total_fade=info["total_fade"])
    return base, outs, pd.DataFrame(results), chk, ess_cmp, thr


if __name__ == "__main__":
    base, outs, res, chk, ess_cmp, thr = run_all()
    pd.set_option("display.width", 200, "display.float_format", "{:,.3f}".format)
    print(res)
    print("checks:", chk)
    print("peak threshold kW:", thr)
    print(pd.DataFrame(ess_cmp))
