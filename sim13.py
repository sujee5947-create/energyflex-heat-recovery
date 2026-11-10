"""v1.3 hourly simulation with physical component models (physics.py).

Same services in every case: same AI jobs every hour, all server heat removed, same heat delivered.
Separates two kinds of improvement:
  equipment effect  : different installed equipment (air -> liquid + efficient UPS, + heat pump)
  operation effect  : same equipment, different hourly operation (coolant supply setpoint, heat pump on/off)
Operation choice = hourly minimum primary energy (no electricity price anywhere).
"""
import numpy as np
import pandas as pd
import config as C
import physics as ph
import sim

P = C.V13


def size_dry_cooler(base):
    """Size the (shared) dry cooler for the hottest design hour of the worst case (air-cooled S0).
    Design outdoor temp = 0.4 % exceedance of the simulated year (ASHRAE design-condition practice)."""
    t_des = float(np.quantile(base.t_out, 1 - P["dc_design_exceed"]))
    q_des = P["design_heat_kw"]
    cop = ph.chiller_cop(P["air_chw_supply"], t_des)
    q_rej = q_des * (1 + 1 / cop)
    P["dc_design_kw"] = q_rej * P["dc_design_dT"] / P["cond_approach"]     # full fan at cond_approach ΔT
    P["dc_fan_rated_kw"] = P["dc_fan_kw_per_kw"] * P["dc_design_kw"]
    P["t_design_c"] = t_des
    return t_des


def allowed_supply():
    tmax = P["coolant_class_max"][P["coolant_class"]]
    return tuple(t for t in P["liquid_supply_options"] if t <= tmax)


def simulate13(base, cooling, ups_eff, heat_pump, t_sup, t_heat_supply, hp_level=1.0, cop_mult=1.0, cool_mult=1.0):
    """cop_mult (scalar or per-row array): 'true' heat pump COP relative to the model.
    cool_mult: 'true' cooling-equipment electricity relative to the model, interpreted PHYSICALLY (v1.5.2):
      chiller COP_true = COP_model / cool_mult  -> chiller work, condenser heat, dry-cooler duty, condensing
      temperature and feasibility are all recomputed; fan and pump power scale by cool_mult (pump work ends up
      as heat in the water loop and is rejected by the dry cooler; fan heat leaves with the air).
    Both errors therefore act through the energy balances, not as a post-hoc multiplier on electricity."""
    if P["dc_design_kw"] is None:
        size_dry_cooler(base)
    df = base.copy(); n = len(df)
    t_out = df.t_out.values
    t_sup = np.broadcast_to(np.asarray(t_sup, float), (n,)).copy()
    hp_level = np.broadcast_to(np.asarray(hp_level, float), (n,)) * bool(heat_pump)
    if cooling == "liquid":
        dT = P["liquid_dT"]
        leak = 1 + P["leak_per_K"] * np.maximum(t_sup - P["leak_ref_c"], 0)
    else:
        dT = P["air_dT"]; leak = np.ones(n)
    it = df.it_kw.values * leak                          # same jobs; warmer chips draw slightly more power
    conv = it * (1 / ups_eff - 1); misc = it * C.MISC_FRACTION
    q_cool = it + conv + misc
    t_ret = t_sup + dT

    # heat pump (source = coolant return water); hp_level = share of the heat demand it is asked to cover
    keep = 1 - C.PIPE_LOSS_FRAC
    demand = df.heat_demand_kw.values
    q_target = np.minimum(hp_level * demand / keep, C.HP_MAX_HEAT_KW)
    m_cp = q_cool / dT                                   # kW/K, whole loop passes the HP evaporator
    t_src_out = t_ret.copy()
    for _ in range(4):                                   # COP depends on how much the source water is cooled
        cop, cop_full, plf = ph.hp_cop(t_ret, t_heat_supply, q_target / C.HP_MAX_HEAT_KW, t_src_out=t_src_out)
        cop = np.maximum(cop * cop_mult, 1.05)
        q_hp = np.minimum(q_target, q_cool / (1 - 1 / cop))
        q_evap_i = q_hp * (1 - 1 / cop)
        t_src_out = t_ret - q_evap_i / m_cp
    w_hp = np.where(q_hp > 0, q_hp / cop, 0.0)
    q_hp_evap = q_hp - w_hp
    q_useful = q_hp * keep; q_pipe = q_hp - q_useful
    q_boiler = demand - q_useful; fuel = q_boiler / C.BOILER_EFF

    # v1.3.1: the heat pump cools the return water first -> the dry cooler sees colder water
    t_ret_dc = t_ret - q_hp_evap / m_cp
    q_rem = q_cool - q_hp_evap                           # = m_cp * (t_ret_dc - t_sup)
    Qd, dTd = P["dc_design_kw"] * P["dc_derate"], P["dc_design_dT"]
    span = np.maximum(t_ret_dc - t_sup, 1e-9)
    free_frac = np.clip((t_ret_dc - (t_out + P["dc_approach"])) / span, 0, 1)
    cap_free = Qd * np.maximum(t_ret_dc - t_out, 0) / dTd            # full-fan capacity at this water temp
    q_free_want = q_rem * free_frac
    q_free = np.minimum(q_free_want, cap_free)
    free_cap_limited = q_free_want > cap_free + 1e-9
    q_ch = q_rem - q_free

    # chiller: if the dry cooler cannot reject the heat at the normal condensing temperature,
    # the condensing temperature rises until it can (lower COP) -- never "free" capacity
    w_pump, phi = ph.pump_power_kw(q_cool, dT)
    w_pump = w_pump * cool_mult
    q_pump_heat = w_pump                                   # pump work dissipates into the coolant
    t_cond_min = np.maximum(t_out, P["cond_min"]) + P["cond_approach"]
    t_cond = t_cond_min.copy()
    for _ in range(4):
        cop_ch = ph.chiller_cop(t_sup, t_out, t_cond) / cool_mult
        w_ch = q_ch / cop_ch
        q_rej = q_free + q_ch + w_ch + q_pump_heat
        t_cond = np.where(q_ch > 0, np.maximum(t_cond_min, t_out + q_rej * dTd / Qd), t_cond_min)
    t_cond_need = t_cond
    infeasible = (q_ch > 0) & (t_cond_need > P["chiller_t_cond_max"] + 1e-6)   # chiller outside its envelope
    t_cond = np.minimum(t_cond, P["chiller_t_cond_max"])
    cop_ch = ph.chiller_cop(t_sup, t_out, t_cond) / cool_mult
    w_ch = q_ch / cop_ch
    q_rej = q_free + q_ch + w_ch + q_pump_heat
    cond_raised = (q_ch > 0) & (t_cond > t_cond_min + 1e-6)
    cap_at_max = Qd * np.maximum(t_cond - t_out, 0) / dTd
    q_unmet = np.where(infeasible, np.maximum(q_rej - cap_at_max, 0), 0.0)     # heat that could NOT be rejected
    t_water_in = np.where(q_ch > 0, np.maximum(t_ret_dc, t_cond), t_ret_dc)
    w_fan_dc, dc_need = ph.dry_cooler_fan_kw(q_rej - q_unmet, t_water_in, t_out)
    w_fan_dc = w_fan_dc * cool_mult
    w_fan_crah = ph.crah_fan_kw(q_cool / P["design_heat_kw"]) if cooling == "air" else np.zeros(n)
    w_fan_crah = w_fan_crah * cool_mult
    w_cool = w_ch + w_fan_dc + w_pump + w_fan_crah
    dc_elec = it + conv + misc + w_cool
    site = dc_elec + w_hp
    primary = C.PEF_ELEC * site + C.PEF_GAS * fuel
    return df.assign(t_sup=t_sup, t_ret=t_ret, t_ret_dc=t_ret_dc, it_elec=it, conv_loss=conv, misc=misc, q_cool=q_cool,
                     hp_level=hp_level, hp_on=q_hp > 0, cop_hp=np.where(q_hp > 0, cop, np.nan), plf=plf, q_hp=q_hp,
                     w_hp=w_hp, q_hp_evap=q_hp_evap, q_useful=q_useful, q_pipe_loss=q_pipe, q_boiler=q_boiler, fuel=fuel,
                     q_free=q_free, q_chiller=q_ch, cop_ch=cop_ch, t_cond=t_cond, cond_raised=cond_raised,
                     free_cap_limited=free_cap_limited, infeasible=infeasible, q_unmet=q_unmet, q_reject=q_rej, q_pump_heat=q_pump_heat, t_src_out=t_src_out,
                     w_chiller=w_ch, w_fan_dc=w_fan_dc,
                     dc_fan_need=dc_need, w_pump=w_pump, flow_frac=phi, w_fan_crah=w_fan_crah, w_cooling=w_cool,
                     dc_elec=dc_elec, site_load=site, primary=primary)


def candidates(base, cooling, ups_eff, heat_pump, t_heat_supply):
    """All operating candidates (coolant setpoint within the coolant class x heat pump level).
    Returns (list of hourly results, meta [(t_sup, level)], primary-energy matrix with inf where infeasible)."""
    cands, meta = [], []
    for ts in (allowed_supply() if cooling == "liquid" else (P["air_chw_supply"],)):
        for lvl in (P["hp_levels"] if heat_pump else (0.0,)):
            cands.append(simulate13(base, cooling, ups_eff, heat_pump, ts, t_heat_supply, lvl))
            meta.append((ts, lvl))
    pe = np.vstack([np.where(c.infeasible.values, np.inf, c.primary.values) for c in cands])
    return cands, meta, pe


def assemble(cands, choice):
    out = cands[0].copy()
    idx = np.arange(len(out))
    for col in out.columns:
        stack = np.vstack([c[col].to_numpy() for c in cands])
        out[col] = stack[choice, idx]
    return out


def optimise(base, cooling, ups_eff, heat_pump, t_heat_supply, cand=None):
    """IDEAL operation: hourly independent pick with perfect knowledge (upper bound of the operation effect).
    Infeasible candidates are never chosen. Also records what separates the 1st and 2nd best candidate."""
    cands, meta, pe = cand or candidates(base, cooling, ups_eff, heat_pump, t_heat_supply)
    order = np.argsort(pe, axis=0, kind="stable")
    best, second = order[0], order[1] if len(cands) > 1 else order[0]
    out = assemble(cands, best)
    idx = np.arange(len(out))
    if len(cands) > 1:
        out["gap_1st_2nd_pct"] = (pe[second, idx] - pe[best, idx]) / pe[best, idx] * 100
        lvl = np.array([m[1] for m in meta]); ts = np.array([m[0] for m in meta])
        ch_on = np.vstack([(c.q_chiller.values > 1.0) for c in cands])
        kind = np.where(lvl[best] != lvl[second], "히트펌프 운전량",
                        np.where(ch_on[best, idx] != ch_on[second, idx], "냉각 방식(외기냉방↔냉동기)", "냉각수 온도만"))
        out["second_kind"] = kind
        out["second_t_sup"] = ts[second]
    else:
        out["gap_1st_2nd_pct"] = np.nan; out["second_kind"] = ""
    out["choice"] = best
    return out


def dp_path(pe, meta, start, ramp_K=None, hold_h=None):
    """REALISTIC operation: one plan for the whole year by dynamic programming.
    Constraints: coolant setpoint may change by at most ramp_K per hour; after any change the new
    setting must be held for hold_h hours. Minimises total primary energy of the given cost matrix."""
    ramp_K = P["ramp_K"] if ramp_K is None else ramp_K
    H = int(P["hold_h"] if hold_h is None else hold_h)
    J, T = pe.shape
    ts = np.array([m[0] for m in meta])
    allowed = np.abs(ts[:, None] - ts[None, :]) <= ramp_K + 1e-9          # allowed[j, k]: j -> k
    np.fill_diagonal(allowed, False)
    big = 1e18
    cost = np.where(np.isfinite(pe), pe, big)
    V = np.full((J, H + 1), big); V[start, H] = 0.0                       # age H = free to change
    bp_j = np.zeros((T, J, H + 1), dtype=np.int16); bp_a = np.zeros((T, J, H + 1), dtype=np.int16)
    trans_from = np.where(allowed, V[:, H][:, None], big)
    for t in range(T):
        Vn = np.full((J, H + 1), big)
        # stay: age a -> min(a+1, H)
        for a in range(1, H + 1):
            na = min(a + 1, H)
            better = V[:, a] < Vn[:, na]
            Vn[better, na] = V[better, a]; bp_j[t, better, na] = np.arange(J)[better]; bp_a[t, better, na] = a
        # change j -> k (only from age H), new age 1
        trans_from = np.where(allowed, V[:, H][:, None], big)             # [j, k]
        jbest = trans_from.argmin(axis=0); vbest = trans_from.min(axis=0)
        better = vbest < Vn[:, 1]
        Vn[better, 1] = vbest[better]; bp_j[t, better, 1] = jbest[better]; bp_a[t, better, 1] = H
        V = Vn + cost[:, t][:, None]
    j, a = np.unravel_index(V.argmin(), V.shape)
    path = np.zeros(T, dtype=int)
    for t in range(T - 1, -1, -1):
        path[t] = j
        j, a = bp_j[t, j, a], bp_a[t, j, a]
    return path


def forecast_base(base, seed=11):
    """Day-ahead view of the year: outdoor temperature with AR(1) forecast error; heat demand follows it.
    IT load is treated as known (scheduled AI jobs)."""
    rng = np.random.default_rng(seed)
    rho, sd = P["forecast_rho"], P["forecast_sd"]
    e = np.zeros(len(base)); e[0] = rng.normal(0, sd)
    for t in range(1, len(base)):
        e[t] = rho * e[t - 1] + rng.normal(0, sd * np.sqrt(1 - rho ** 2))
    f = base.copy(); f["t_out"] = base.t_out + e
    dhw = base.heat_demand_kw - C.HEAT_UA_KW_PER_K * np.clip(C.HEAT_BALANCE_T - base.t_out, 0, None)
    f["heat_demand_kw"] = C.HEAT_UA_KW_PER_K * np.clip(C.HEAT_BALANCE_T - f.t_out, 0, None) + dhw
    return f


def realistic(base, ups_eff, t_heat_supply, cand=None, use_forecast=True, ramp_K=None, hold_h=None):
    """Plan with constraints (and day-ahead forecast), then run the plan in the real weather.
    If the planned setting turns out infeasible in reality, fall back to the best feasible one (counted)."""
    cands, meta, pe = cand or candidates(base, "liquid", ups_eff, True, t_heat_supply)
    start = [i for i, m in enumerate(meta) if m == (P["liquid_supply_design"], 1.0)][0]
    if use_forecast:
        fb = forecast_base(base)
        _, _, pe_plan = candidates(fb, "liquid", ups_eff, True, t_heat_supply)
    else:
        pe_plan = pe
    path = dp_path(pe_plan, meta, start, ramp_K, hold_h)
    idx = np.arange(pe.shape[1])
    bad = ~np.isfinite(pe[path, idx])
    path = np.where(bad, pe.argmin(axis=0), path)
    out = assemble(cands, path)
    out["choice"] = path; out["fallback"] = bad
    ts = np.array([m[0] for m in meta])
    out.attrs["changes"] = int((np.diff(ts[path]) != 0).sum())
    return out


def stress_base(base, heatwave_K=0.0, it_full=False):
    b = base.copy()
    if heatwave_K:
        m = pd.date_range("2025-01-01", periods=len(b), freq="h").month
        summer = np.isin(m, [6, 7, 8, 9])
        b.loc[summer, "t_out"] = b.t_out[summer] + heatwave_K
        dhw = base.heat_demand_kw - C.HEAT_UA_KW_PER_K * np.clip(C.HEAT_BALANCE_T - base.t_out, 0, None)
        b["heat_demand_kw"] = C.HEAT_UA_KW_PER_K * np.clip(C.HEAT_BALANCE_T - b.t_out, 0, None) + dhw
    if it_full:
        b["it_kw"] = C.IT_CAPACITY_KW; b["util"] = 1.0; b["jobs"] = C.JOBS_PER_UTIL_HOUR
    return b


STRESS = [
    ("기준", dict()),
    ("폭염 +3°C (6–9월)", dict(heatwave_K=3.0)),
    ("폭염 +5°C (6–9월)", dict(heatwave_K=5.0)),
    ("IT 100% 연속", dict(it_full=True)),
    ("건식냉각기 성능 −20%", dict(derate=0.8)),
    ("서버 등급 W32", dict(cls="W32")),
    ("복합: 폭염+5°C · IT 100% · 냉각기 −20%", dict(heatwave_K=5.0, it_full=True, derate=0.8)),
]


def stress_test(t_heat_supply=65.0):
    """Equipment is sized once for the normal year; then the year is made harder. Counts hours the
    equipment cannot do the job (chiller outside its envelope -> heat not rejected)."""
    base = sim.climate_and_load(); size_dry_cooler(base)
    rows = []
    for name, kw in STRESS:
        b = stress_base(base, kw.get("heatwave_K", 0.0), kw.get("it_full", False))
        old_d, old_c = P["dc_derate"], P["coolant_class"]
        P["dc_derate"] = kw.get("derate", 1.0); P["coolant_class"] = kw.get("cls", old_c)
        cases = {"S0 공랭": simulate13(b, "air", P["ups_legacy"], False, P["air_chw_supply"], t_heat_supply),
                 "S2 규칙운전": simulate13(b, "liquid", P["ups_efficient"], True, P["liquid_supply_design"], t_heat_supply, 1.0),
                 "S2 최적운전": optimise(b, "liquid", P["ups_efficient"], True, t_heat_supply)}
        for cname, o in cases.items():
            rows.append(dict(stress=name, case=cname, infeasible_h=int(o.infeasible.sum()), unmet_mwh=o.q_unmet.sum() / 1e3,
                             cond_raised_h=int(o.cond_raised.sum()), max_t_cond=float(o.t_cond.where(o.q_chiller > 0).max()),
                             max_fan_need=float(o.dc_fan_need.max()), pue=o.dc_elec.sum() / o.it_elec.sum(),
                             primary_mwh=o.primary.sum() / 1e3, max_t_out=float(b.t_out.max())))
        P["dc_derate"], P["coolant_class"] = old_d, old_c
    return pd.DataFrame(rows)


def checks13(o):
    return dict(
        cooling_balance=float(np.abs(o.q_cool - (o.q_free + o.q_chiller + o.q_hp_evap)).max()),
        heat_balance=float(np.abs(o.heat_demand_kw - (o.q_useful + o.q_boiler)).max()),
        hp_balance=float(np.abs(o.q_hp - (o.q_hp_evap + o.w_hp)).max()),
        pipe_balance=float(np.abs(o.q_hp - (o.q_useful + o.q_pipe_loss)).max()),
        nonneg=float(min(o.q_free.min(), o.q_chiller.min(), o.q_boiler.min(), o.q_hp_evap.min(), 0.0)),
        unmet_cooling=float(o.q_unmet.max()),
        rejection_balance=float(np.abs(o.q_reject - (o.q_free + o.q_chiller + o.w_chiller + o.q_pump_heat)).max()),
        dc_over_capacity=float(max(o.dc_fan_need.max() - 1.0, 0.0)))   # must be 0: no heat rejected beyond full fan


def ess13(load, soc_min=None, soc_max=None, iters=40):
    """Peak shaving on a v1.3 site-load profile: lowest threshold the ESS can hold all year."""
    soc_min = C.ESS_SOC_MIN if soc_min is None else soc_min
    soc_max = C.ESS_SOC_MAX if soc_max is None else soc_max
    lo, hi = load.max() - C.ESS_KW, load.max()
    for _ in range(iters):
        mid = (lo + hi) / 2
        grid = sim.run_ess(load, mid, soc_min, soc_max)[0]
        if grid.max() <= mid + 1e-6: hi = mid
        else: lo = mid
    return hi


def summary(o):
    site, fuel = o.site_load.sum(), o.fuel.sum()
    return dict(final_mwh=(site + fuel) / 1e3, primary_mwh=o.primary.sum() / 1e3, elec_mwh=site / 1e3,
                it_mwh=o.it_elec.sum() / 1e3, conv_mwh=o.conv_loss.sum() / 1e3, misc_mwh=o.misc.sum() / 1e3,
                chiller_mwh=o.w_chiller.sum() / 1e3, dc_fan_mwh=o.w_fan_dc.sum() / 1e3,
                crah_fan_mwh=o.w_fan_crah.sum() / 1e3, pump_mwh=o.w_pump.sum() / 1e3,
                hp_mwh=o.w_hp.sum() / 1e3, boiler_fuel_mwh=fuel / 1e3, heat_useful_mwh=o.q_useful.sum() / 1e3,
                hp_seasonal_cop=o.q_hp.sum() / o.w_hp.sum() if o.w_hp.sum() > 0 else np.nan,
                pue=o.dc_elec.sum() / o.it_elec.sum(), peak_kw=o.site_load.max(),
                mean_t_sup=o.t_sup.mean(), free_share=o.q_free.sum() / o.q_cool.sum(),
                jobs=o.jobs.sum(), dc_fan_saturated_pct=(o.dc_fan_need > 1).mean() * 100,
                cond_raised_h=int(o.cond_raised.sum()), free_cap_limited_h=int(o.free_cap_limited.sum()),
                infeasible_h=int(o.infeasible.sum()), unmet_mwh=o.q_unmet.sum() / 1e3,
                max_t_cond=float(o.t_cond.where(o.q_chiller > 0).max()) if (o.q_chiller > 0).any() else np.nan,
                dc_fan_need_max=float(o.dc_fan_need.max()), max_t_sup=float(o.t_sup.max()),
                hp_level_mean=float(o.hp_level[o.heat_demand_kw > 0].mean()),
                near_tie_pct=(o.gap_1st_2nd_pct < 1).mean() * 100 if "gap_1st_2nd_pct" in o else np.nan,
                near_tie_setpoint_pct=((o.gap_1st_2nd_pct < 1) & (o.second_kind == "냉각수 온도만")).mean() * 100 if "second_kind" in o else np.nan,
                near_tie_mode_pct=((o.gap_1st_2nd_pct < 1) & (o.second_kind != "냉각수 온도만")).mean() * 100 if "second_kind" in o else np.nan)


def run13():
    base = sim.climate_and_load()
    size_dry_cooler(base)
    td = P["liquid_supply_design"]
    assert td <= P["coolant_class_max"][P["coolant_class"]], "rule setpoint above coolant class limit"
    rows, outs, chk = {}, {}, {}
    for ths in P["heat_supply_c"]:
        cases = {
            "S0 기존(공랭)": simulate13(base, "air", P["ups_legacy"], False, P["air_chw_supply"], ths),
            "S1 규칙운전": simulate13(base, "liquid", P["ups_efficient"], False, td, ths),
            "S1 최적운전": optimise(base, "liquid", P["ups_efficient"], False, ths),
            "S2 규칙운전": simulate13(base, "liquid", P["ups_efficient"], True, td, ths, 1.0),
            "S2 최적운전": optimise(base, "liquid", P["ups_efficient"], True, ths),
        }
        for k, o in cases.items():
            key = f"{ths:.0f}°C | {k}"
            outs[key], rows[key], chk[key] = o, summary(o), checks13(o)
            rows[key]["ess_peak_kw"] = ess13(o.site_load.values) if k == "S2 최적운전" else np.nan
    res = pd.DataFrame(rows).T
    # same service: jobs and heat delivered identical in every case
    ref = next(iter(outs.values()))
    svc = {k: dict(jobs_diff=float(np.abs(o.jobs - ref.jobs).max()),
                   heat_delivered_diff=float(np.abs(o.q_useful + o.q_boiler - ref.heat_demand_kw).max()))
           for k, o in outs.items()}
    # decomposition: equipment vs operation (primary energy, MWh)
    dec = {}
    for ths in P["heat_supply_c"]:
        g = lambda k: res.loc[f"{ths:.0f}°C | {k}", "primary_mwh"]
        dec[f"{ths:.0f}°C"] = {
            "설비①: 공랭→수랭+고효율UPS": g("S0 기존(공랭)") - g("S1 규칙운전"),
            "운전①: 냉각수 온도 시간별 최적화": g("S1 규칙운전") - g("S1 최적운전"),
            "설비②: 히트펌프 열회수 추가": g("S1 규칙운전") - g("S2 규칙운전"),
            "운전②: 냉각수 온도·히트펌프 운전량 최적화": g("S2 규칙운전") - g("S2 최적운전"),
        }
    return base, outs, res, chk, svc, pd.DataFrame(dec)


if __name__ == "__main__":
    import warnings; warnings.simplefilter("error")
    base, outs, res, chk, svc, dec = run13()
    pd.set_option("display.width", 250)
    print("design T_out", round(P["t_design_c"], 2), "dry cooler kW", round(P["dc_design_kw"]), "fan kW", round(P["dc_fan_rated_kw"], 1))
    print(res[["final_mwh", "primary_mwh", "it_mwh", "pue", "cond_raised_h", "free_cap_limited_h", "max_t_cond",
               "dc_fan_need_max", "max_t_sup", "hp_level_mean", "near_tie_pct", "near_tie_setpoint_pct",
               "near_tie_mode_pct", "peak_kw", "ess_peak_kw"]].round(2).to_string())
    print("max balance:", max(v for d in chk.values() for v in map(abs, d.values())))
    print("same service worst:", max(v for d in svc.values() for v in d.values()))
    print(dec.round(1))
    for k in ["65°C | S2 최적운전", "45°C | S2 최적운전"]:
        o = outs[k]
        print(k, o.t_sup.value_counts().to_dict(), "levels", o.hp_level.value_counts().to_dict(),
              "kinds(<1%)", o.second_kind[o.gap_1st_2nd_pct < 1].value_counts().to_dict())
