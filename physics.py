"""v1.3 component models. Each function is a small, replaceable physical model.

- Heat pump COP depends on the source water (server coolant return) and heating supply temperature,
  and on part-load ratio. Outdoor temperature affects it only indirectly (via free cooling / coolant temp).
- Pump power = hydraulic power with static head + friction head + minimum flow + efficiency curve.
  It is NOT the pure affinity (flow^3) law; a measured performance curve can replace the formula.
- Fan power (dry cooler, CRAH) is computed per device from the needed air-flow fraction.
"""
import numpy as np
import pandas as pd
import config as C

K, G, CP = 273.15, 9.81, 4.186     # K offset, m/s2, kJ/kg-K (water)
P = C.V13


def _lm(t_a, t_b):
    """Log-mean temperature (K) between two water temperatures in °C."""
    a, b = np.asarray(t_a, float) + K, np.asarray(t_b, float) + K
    d = a - b
    small = np.abs(d) < 1e-6
    with np.errstate(divide="ignore", invalid="ignore"):
        lm = d / np.log(np.where(small, 2.0, a / b))
    return np.where(small, a, lm)


def hp_cop(t_src_in, t_heat_supply, plr, t_src_out=None, t_sink_in=None, method=None):
    """Heat pump COP. Outdoor air never enters directly.
    inlet  (v1.3): T_evap = source inlet - 5, T_cond = supply + 5, Carnot fraction
    outlet (v1.4): T_evap = source OUTLET - pinch, T_cond = sink OUTLET + pinch, Carnot fraction
                   (single-stage cycle: evaporator must be colder than the coldest source water)
    lorenz (v1.4): Lorenz COP from log-mean source/sink temperatures x Lorenz efficiency (comparison only)"""
    method = method or P["hp_cop_method"]
    t_src_in = np.asarray(t_src_in, float)
    t_src_out = t_src_in if t_src_out is None else np.asarray(t_src_out, float)
    if method == "inlet":
        t_evap = t_src_in - P["hp_evap_approach"]; t_cond = np.asarray(t_heat_supply, float) + P["hp_cond_approach"]
        cop_full = P["hp_carnot"] * (t_cond + K) / np.maximum(t_cond - t_evap, 1.0)
    elif method == "outlet":
        t_evap = t_src_out - P["hp_pinch"]; t_cond = np.asarray(t_heat_supply, float) + P["hp_pinch"]
        cop_full = P["hp_carnot"] * (t_cond + K) / np.maximum(t_cond - t_evap, 1.0)
    elif method == "lorenz":
        t_sink_in = P["heat_return_c"].get(float(t_heat_supply), t_heat_supply - 25.0) if t_sink_in is None else t_sink_in
        th, tc = _lm(t_heat_supply, t_sink_in), _lm(t_src_in, t_src_out)
        cop_full = P["lorenz_eff"] * th / np.maximum(th - tc, 1.0)
    else:
        raise ValueError(method)
    cop_full = np.minimum(cop_full, P["hp_cop_max"])
    plr = np.clip(np.asarray(plr, float), 0, 1)
    plf = np.where(plr >= P["hp_plr_mod_min"], 1.0, 1 - P["hp_cd"] * (1 - plr / P["hp_plr_mod_min"]))
    return cop_full * plf, cop_full, plf


def chiller_cop(t_supply, t_out, t_cond=None):
    t_evap = np.asarray(t_supply, float) - P["chiller_evap_approach"]
    if t_cond is None:
        t_cond = np.maximum(t_out, P["cond_min"]) + P["cond_approach"]
    lift = np.maximum(t_cond - t_evap, 5.0)
    return np.minimum(P["chiller_carnot"] * (t_evap + K) / lift, P["chiller_cop_max"])


_curve = None
def _pump_curve():
    global _curve
    if P["pump_curve_csv"] and _curve is None:
        _curve = pd.read_csv(P["pump_curve_csv"]).sort_values("flow_frac")
    return _curve


def pump_head_eff(phi):
    """Head (m) and pump efficiency at flow fraction phi (of design)."""
    cur = _pump_curve()
    if cur is not None:
        return (np.interp(phi, cur.flow_frac, cur.head_m), np.interp(phi, cur.flow_frac, cur.eff))
    H = P["pump_H_static_m"] + (P["pump_H_design_m"] - P["pump_H_static_m"]) * phi ** 2
    b = P["pump_bep_flow"]
    eff = P["pump_eta_max"] * np.clip(1 - ((phi - b) / b) ** 2, P["pump_eta_floor"], 1)
    return H, eff


def pump_power_kw(q_kw, dT, design_kw=None):
    """Loop pump electricity for moving q_kw of heat at temperature difference dT (constant-dT control)."""
    design_kw = design_kw or P["design_heat_kw"]
    m_design = design_kw / (CP * dT)                         # kg/s
    phi = np.maximum(np.asarray(q_kw, float) / design_kw, P["pump_min_flow"])
    H, eff = pump_head_eff(phi)
    return m_design * phi * G * H / (eff * P["drive_eta"]) / 1000.0, phi


def pump_power_cube_law(q_kw, dT, design_kw=None):
    """Reference only: the pure affinity law (what the model deliberately does NOT use)."""
    design_kw = design_kw or P["design_heat_kw"]
    p_design, _ = pump_power_kw(design_kw, dT, design_kw)
    return p_design * (np.asarray(q_kw, float) / design_kw) ** 3


def fan_power_kw(speed, rated_kw):
    s = np.clip(speed, P["fan_min_speed"], 1.0)
    return rated_kw * s ** P["fan_exp"]


def crah_fan_kw(flow_frac):
    """Indoor air-handler fans: ASHRAE 90.1 Appendix G VAV part-load curve (static-pressure controlled)."""
    a, b, c, d = P["crah_curve"]
    x = np.clip(np.asarray(flow_frac, float), P["fan_min_speed"], 1.0)
    return P["crah_fan_rated_kw"] * (a + b * x + c * x ** 2 + d * x ** 3)


def dry_cooler_fan_kw(q_reject_kw, t_water_in, t_out):
    """Fan speed needed to reject q at the available water-air temperature difference."""
    dT = np.maximum(np.asarray(t_water_in, float) - t_out, 1.0)
    cap_full = P["dc_design_kw"] * P["dc_derate"] * dT / P["dc_design_dT"]
    need = np.asarray(q_reject_kw, float) / cap_full
    return fan_power_kw(need, P["dc_fan_rated_kw"]), need
