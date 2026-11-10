"""v1.5 operating-mode maps (P3) and uncertainty maps (P4).  -> results/v15/

Map A : for every (outdoor temperature, heat demand) point, the operating choice with the lowest primary
        energy (no prediction error). Choice = heat pump level {0, 0.5, 1} x coolant supply setpoint
        (within the server coolant class). Reported as four strategies:
            열회수 (HP 100 %), 혼합 (HP 50 %), 외기냉방 (HP off, mostly free cooling), 냉동기 (HP off, mostly chiller)
Map B : choice stability under an ASSUMED error model (Monte Carlo ratio, not an observed probability).
        Cooling-electricity error = ESIF non-IT model error distribution used as a PROXY uncertainty (different
        system and model); heat pump COP error = assumed +/-15 % (sensitivity analysis). Errors are applied inside
        sim13.simulate13, so heat extracted from servers, residual cooling load, boiler use and feasibility are
        all recomputed (v1.5.1).
Annual: how often the hourly choice flips and what it costs (regret), as a function of the error correlation
        between candidates (rho = 1: common error ... rho = 0: independent per candidate, a stress scenario).
No electricity price is used anywhere.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import config as C
import sim
import sim13

plt.rcParams["font.family"] = "Noto Sans CJK KR"; plt.rcParams["axes.unicode_minus"] = False
ROOT = Path(__file__).parent
OUT = ROOT / "results" / "v15"; OUT.mkdir(parents=True, exist_ok=True)
P = C.V13
UPS = P["ups_efficient"]
N_DRAW = 300
N_ANNUAL = 40
COP_ERR = 0.15                     # assumed +/- range (uniform) -> sensitivity analysis
NEAR_TIE = 1.0                     # % gap between 1st and 2nd
T_GRID = np.arange(-15, 36, 1.0)
D_GRID = np.arange(0, 801, 25.0)
IT_KW = C.IT_CAPACITY_KW * (C.IT_IDLE_FRACTION + (1 - C.IT_IDLE_FRACTION) * C.UTIL_MEAN)   # average IT load

CH_THR = 0.10                      # chiller share above which the cooling mode counts as 'chiller-assisted'
STRATS = ["열회수+외기냉방", "열회수+냉동기 보조", "혼합(부분 회수)", "외기냉방만", "냉동기 사용"]
SCOL = {"열회수+외기냉방": "#3b8f5a", "열회수+냉동기 보조": "#a3c96b", "혼합(부분 회수)": "#d9822b",
        "외기냉방만": "#7aa6d6", "냉동기 사용": "#1f4e80"}
TCOL = {25.0: "#e3eef8", 30.0: "#a9c8e8", 35.0: "#5b8fc9", 40.0: "#2f6fb0", 45.0: "#123c6b"}


def grid_base():
    T, D = np.meshgrid(T_GRID, D_GRID)
    n = T.size
    return pd.DataFrame(dict(hour=np.arange(n), t_out=T.ravel(), util=C.UTIL_MEAN, it_kw=IT_KW,
                             jobs=C.UTIL_MEAN * C.JOBS_PER_UTIL_HOUR, heat_demand_kw=D.ravel())), T.shape


def strategy_of(o):
    """Heat pump level (recovery / partial / none) x cooling mode (free cooling only / chiller-assisted)."""
    on = (o.q_hp.values > 1e-9) & (o.hp_level.values >= 0.99)
    part = (o.q_hp.values > 1e-9) & (o.hp_level.values < 0.99)
    ch = (o.q_chiller / np.maximum(o.q_cool, 1e-9)).values > CH_THR
    return np.where(on, np.where(ch, "열회수+냉동기 보조", "열회수+외기냉방"),
                    np.where(part, "혼합(부분 회수)", np.where(ch, "냉동기 사용", "외기냉방만")))


def esif_errors():
    d = pd.read_csv(ROOT / "results" / "validation" / "test_hourly.csv")
    e = (d.non_it - d.pred_v11) / d.pred_v11
    bins = [-60, 0, 10, 20, 30, 60]
    lab = pd.cut(d.t_out_c, bins, labels=False)
    pools = {b: e[lab == b].values for b in range(len(bins) - 1)}
    return bins, pools


from scipy.stats import norm as _norm

RHOS = [1.0, 0.9, 0.75, 0.5, 0.25, 0.0]


def draw_errors(rng, tbin, pools_sorted, n_cand, rho, cop_per_row=True):
    """Correlated errors via a Gaussian copula: z_k = sqrt(rho) z_common + sqrt(1-rho) z_k,indep.
    Cooling error eps_k: mapped to the empirical ESIF error quantiles of the row's temperature bin.
    COP error delta_k: mapped to Uniform(-COP_ERR, +COP_ERR) (per row, or one value per year)."""
    n = len(tbin)
    zc = rng.standard_normal(n); zi = rng.standard_normal((n_cand, n))
    u = _norm.cdf(np.sqrt(rho) * zc + np.sqrt(1 - rho) * zi)
    eps = np.empty((n_cand, n))
    for b, pool in pools_sorted.items():
        m = tbin == b
        if m.any():
            eps[:, m] = pool[np.minimum((u[:, m] * len(pool)).astype(int), len(pool) - 1)]
    if cop_per_row:
        wc = rng.standard_normal(n); wi = rng.standard_normal((n_cand, n))
    else:
        wc = np.full(n, rng.standard_normal()); wi = np.repeat(rng.standard_normal((n_cand, 1)), n, axis=1)
    delta = (2 * _norm.cdf(np.sqrt(rho) * wc + np.sqrt(1 - rho) * wi) - 1) * COP_ERR
    return eps, delta


def true_pe(base, meta, ths, eps, delta):
    """'Simulation truth': rerun every candidate with its errors applied inside the physics."""
    out = []
    for k, (ts, lvl) in enumerate(meta):
        o = sim13.simulate13(base, "liquid", UPS, True, ts, ths, lvl, cop_mult=1 + delta[k], cool_mult=1 + eps[k])
        out.append(np.where(o.infeasible.values, np.inf, o.primary.values))
    return np.vstack(out)


def main():
    rng = np.random.default_rng(2026)
    base = sim.climate_and_load(); sim13.size_dry_cooler(base)        # equipment sized on the normal year
    g, shape = grid_base()
    bins, pools = esif_errors()
    pools = {b: np.sort(v) for b, v in pools.items()}
    tbin = np.clip(np.digitize(g.t_out.values, bins) - 1, 0, len(bins) - 2)
    summary_rows, cell_rows = [], []
    for ths in P["heat_supply_c"]:
        cands, meta, pe = sim13.candidates(g, "liquid", UPS, True, ths)
        order = np.argsort(pe, axis=0, kind="stable"); best = order[0]; second = order[1]
        A = sim13.assemble(cands, best)
        strat_A = strategy_of(A); tsup_A = A.t_sup.values
        idx = np.arange(len(g))
        gap = (pe[second, idx] - pe[best, idx]) / pe[best, idx] * 100
        # ---- Map B: Monte Carlo
        same_choice = np.zeros(len(g)); same_strat = np.zeros(len(g)); same_tsup = np.zeros(len(g))
        votes = np.zeros((len(cands), len(g)))
        regret = np.zeros(len(g))
        strat_of_cand = np.vstack([strategy_of(c) for c in cands])
        tsup_of_cand = np.array([m[0] for m in meta])
        for _ in range(N_DRAW):
            eps, delta = draw_errors(rng, tbin, pools, len(cands), rho=1.0)      # map: common error per cell
            pe_true = true_pe(g, meta, ths, eps, delta)
            b_true = pe_true.argmin(axis=0)
            votes[b_true, idx] += 1
            same_choice += b_true == best
            same_strat += strat_of_cand[b_true, idx] == strat_A
            same_tsup += tsup_of_cand[b_true] == tsup_A
            regret += (pe_true[best, idx] - pe_true[b_true, idx]) / pe_true[b_true, idx] * 100
        stab = same_choice / N_DRAW; stab_s = same_strat / N_DRAW; stab_t = same_tsup / N_DRAW
        modal = votes.argmax(axis=0)
        strat_B = strat_of_cand[modal, idx]; tsup_B = tsup_of_cand[modal]
        cell = pd.DataFrame(dict(heat_supply=ths, t_out=g.t_out, demand=g.heat_demand_kw, strat_A=strat_A, tsup_A=tsup_A,
                                 gap_pct=gap, strat_B=strat_B, tsup_B=tsup_B, stability=stab, stability_strategy=stab_s,
                                 stability_setpoint=stab_t, mean_regret_pct=regret / N_DRAW))
        cell_rows.append(cell)
        summary_rows.append(dict(heat_supply=ths, cells=len(g),
                                 share_recovery=np.isin(strat_A, ["열회수+외기냉방", "열회수+냉동기 보조", "혼합(부분 회수)"]).mean() * 100,
                                 near_tie_cells_pct=(gap < NEAR_TIE).mean() * 100,
                                 strategy_stable_ge90_pct=(stab_s >= 0.9).mean() * 100,
                                 setpoint_stable_ge90_pct=(stab_t >= 0.9).mean() * 100,
                                 choice_differs_A_B_pct=((tsup_A != tsup_B) | (strat_A != strat_B)).mean() * 100,
                                 strategy_differs_A_B_pct=(strat_A != strat_B).mean() * 100,
                                 mean_regret_pct=(regret / N_DRAW).mean(), max_regret_pct=(regret / N_DRAW).max()))
    cells = pd.concat(cell_rows); cells.to_csv(OUT / "map_cells.csv", index=False, encoding="utf-8-sig")
    summ = pd.DataFrame(summary_rows); summ.to_csv(OUT / "map_summary.csv", index=False, encoding="utf-8-sig")

    # ---- coolant temperature as a fixed condition (mode map per coolant setpoint)
    mode_rows = []
    for ths in P["heat_supply_c"]:
        for ts in [30.0, 35.0, 40.0]:
            cs = [sim13.simulate13(g, "liquid", UPS, True, ts, ths, lvl) for lvl in P["hp_levels"]]
            pe = np.vstack([np.where(c.infeasible.values, np.inf, c.primary.values) for c in cs])
            A = sim13.assemble(cs, pe.argmin(axis=0))
            srt = np.sort(pe, axis=0)
            mode_rows.append(pd.DataFrame(dict(heat_supply=ths, coolant=ts, t_out=g.t_out, demand=g.heat_demand_kw,
                                               strat=strategy_of(A), gap_pct=(srt[1] - srt[0]) / srt[0] * 100,
                                               free_share=A.q_free / (A.q_cool - A.q_hp_evap + 1e-9))))
    modes = pd.concat(mode_rows); modes.to_csv(OUT / "map_modes_by_coolant.csv", index=False, encoding="utf-8-sig")

    # ---- annual: flips and regret as a function of the error correlation between candidates
    ann = []
    tb_year = np.clip(np.digitize(base.t_out.values, bins) - 1, 0, len(bins) - 2)
    for ths in P["heat_supply_c"]:
        cands, meta, pe = sim13.candidates(base, "liquid", UPS, True, ths)
        best = pe.argmin(axis=0); idx = np.arange(len(base))
        strat_c = np.vstack([strategy_of(c) for c in cands])
        for rho in RHOS:
            flips, sflips, reg = [], [], []
            for _ in range(N_ANNUAL):
                eps, delta = draw_errors(rng, tb_year, pools, len(cands), rho, cop_per_row=False)  # COP error persists all year
                pt = true_pe(base, meta, ths, eps, delta); bt = pt.argmin(axis=0)
                flips.append((bt != best).mean() * 100)
                sflips.append((strat_c[bt, idx] != strat_c[best, idx]).mean() * 100)
                reg.append((pt[best, idx] - pt[bt, idx]).sum() / 1e3)
            ann.append(dict(heat_supply=f"{ths:.0f}°C", rho=rho,
                            error="공통 오차 (ρ=1)" if rho == 1 else ("후보별 독립 오차 (ρ=0, 스트레스 시나리오)" if rho == 0 else f"상관 ρ={rho}"),
                            flip_any_pct=np.mean(flips), flip_strategy_pct=np.mean(sflips),
                            regret_mwh_mean=np.mean(reg), regret_mwh_p95=np.percentile(reg, 95)))
    ann = pd.DataFrame(ann); ann.to_csv(OUT / "annual_flip_regret.csv", index=False, encoding="utf-8-sig")
    return cells, summ, modes, ann


# ------------------------------------------------------------------ figures
def _img(ax, cells, col, cmap, norm, title):
    T = cells.t_out.unique(); D = cells.demand.unique()
    Z = cells.pivot(index="demand", columns="t_out", values=col).loc[D, T].values
    ax.pcolormesh(T, D, Z, cmap=cmap, norm=norm, shading="nearest")
    ax.set_title(title, loc="left", fontsize=10)
    ax.set_xlabel("외기온도 (°C)"); ax.set_ylabel("난방 수요 (kW)")


def _hatch(ax, cells, mask_col, thr, label):
    T = cells.t_out.unique(); D = cells.demand.unique()
    M = cells.pivot(index="demand", columns="t_out", values=mask_col).loc[D, T].values < thr
    ax.contourf(T, D, M.astype(float), levels=[0.5, 1.5], colors="none", hatches=["////"])
    ax.contour(T, D, M.astype(float), levels=[0.5], colors="#222", linewidths=0.6)


def figures(cells, summ, modes, ann):
    scode = {s: i for i, s in enumerate(STRATS)}
    s_cmap = ListedColormap([SCOL[s] for s in STRATS]); s_norm = BoundaryNorm(np.arange(-0.5, len(STRATS) + 0.5), len(STRATS))
    tvals = sorted(TCOL); t_cmap = ListedColormap([TCOL[t] for t in tvals])
    t_norm = BoundaryNorm(np.array(tvals + [tvals[-1] + 5]) - 2.5, len(tvals))
    for ths in P["heat_supply_c"]:
        c = cells[cells.heat_supply == ths].copy()
        c["sA"] = c.strat_A.map(scode); c["sB"] = c.strat_B.map(scode)
        # Map A
        fig, axs = plt.subplots(1, 2, figsize=(11.5, 4.4))
        _img(axs[0], c, "sA", s_cmap, s_norm, "① 최적 운전 전략")
        _img(axs[1], c, "tsup_A", t_cmap, t_norm, "② 최적 냉각수 공급온도")
        for a in axs: _hatch(a, c, "gap_pct", NEAR_TIE, "1·2위 차이 < 1%")
        axs[0].legend(handles=[Patch(color=SCOL[s], label=s) for s in STRATS if s in set(c.strat_A)] +
                      [Patch(facecolor="white", edgecolor="#222", hatch="////", label="1·2위 차이 < 1%")],
                      fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3)
        axs[1].legend(handles=[Patch(color=TCOL[t], label=f"{t:.0f}°C") for t in tvals if t <= P["coolant_class_max"][P["coolant_class"]]],
                      fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=5, title="냉각수 공급온도 (빗금: 1·2위 차이 < 1%)", title_fontsize=8)
        fig.suptitle(f"지도 A (예측 오차 없음) — 난방 공급 {ths:.0f}°C, IT 평균 부하 {IT_KW:.0f} kW, 서버 등급 {P['coolant_class']}",
                     fontsize=11, x=0.01, ha="left")
        fig.set_size_inches(11.5, 5.2); fig.tight_layout(); fig.savefig(OUT / f"24_map_A_{ths:.0f}.png", dpi=160); plt.close(fig)
        # Map B
        fig, axs = plt.subplots(1, 2, figsize=(11.5, 4.4))
        st_cmap = plt.get_cmap("Blues")
        T = c.t_out.unique(); D = c.demand.unique()
        Z = c.pivot(index="demand", columns="t_out", values="stability_setpoint").loc[D, T].values * 100
        im = axs[0].pcolormesh(T, D, Z, cmap=st_cmap, vmin=0, vmax=100, shading="nearest")
        cb = fig.colorbar(im, ax=axs[0], fraction=0.046, pad=0.02); cb.set_label("지도 A의 냉각수 온도가 그대로 최선인 비율 (%, 300회 모의)", fontsize=8)
        axs[0].set_title("③ 선택 안정성 (가정한 오차 모델 하에서)", loc="left", fontsize=10)
        axs[0].set_xlabel("외기온도 (°C)"); axs[0].set_ylabel("난방 수요 (kW)")
        diff = ((c.tsup_A != c.tsup_B) | (c.strat_A != c.strat_B)).astype(float)
        c["diff"] = diff
        _img(axs[1], c, "tsup_B", t_cmap, t_norm, "④ 오차를 고려한 최선 (가장 자주 1위) — 테두리: 지도 A와 다른 곳")
        M = c.pivot(index="demand", columns="t_out", values="diff").loc[D, T].values
        axs[1].contour(T, D, M, levels=[0.5], colors="#d9822b", linewidths=1.8)
        fig.suptitle(f"지도 B (민감도 분석) — 냉각 전력: ESIF 비IT 모델 오차를 대리 불확실성으로, 히트펌프 COP: ±{COP_ERR:.0%} 가정",
                     fontsize=11, x=0.01, ha="left")
        fig.tight_layout(); fig.savefig(OUT / f"26_map_B_{ths:.0f}.png", dpi=160); plt.close(fig)
    # modes by coolant temperature (coolant as a fixed condition)
    fig, axs = plt.subplots(2, 3, figsize=(12, 7), sharex=True, sharey=True)
    for r, ths in enumerate(P["heat_supply_c"]):
        for k, ts in enumerate([30.0, 35.0, 40.0]):
            m = modes[(modes.heat_supply == ths) & (modes.coolant == ts)].copy(); m["s"] = m.strat.map(scode)
            _img(axs[r, k], m, "s", s_cmap, s_norm, f"난방 {ths:.0f}°C · 냉각수 {ts:.0f}°C")
            _hatch(axs[r, k], m, "gap_pct", NEAR_TIE, "")
            if r == 0: axs[r, k].set_xlabel("")
            if k > 0: axs[r, k].set_ylabel("")
    fig.legend(handles=[Patch(color=SCOL[s], label=s) for s in STRATS if s in set(modes.strat)] +
               [Patch(facecolor="white", edgecolor="#222", hatch="////", label="1·2위 차이 < 1%")], fontsize=9, loc="lower center", ncol=5, frameon=False)
    fig.suptitle("냉각수 온도를 고정 조건으로 본 운전 전략 지도 — 냉각수가 따뜻할수록 외기냉방 영역이 더운 쪽으로 넓어진다",
                 fontsize=11, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.05, 1, 1)); fig.savefig(OUT / "25_map_by_coolant.png", dpi=150); plt.close(fig)
    # annual flips vs error correlation
    fig, axs = plt.subplots(1, 2, figsize=(11.5, 3.9))
    for ths, col, mk in [("65°C", "#d9822b", "o"), ("45°C", "#2f6fb0", "s")]:
        d = ann[ann.heat_supply == ths].sort_values("rho")
        axs[0].plot(d.rho, d.flip_any_pct, color=col, marker=mk, lw=2, label=f"난방 {ths}")
        axs[1].plot(d.rho, d.regret_mwh_mean, color=col, marker=mk, lw=2, label=f"난방 {ths}")
        axs[1].fill_between(d.rho, d.regret_mwh_mean, d.regret_mwh_p95, color=col, alpha=0.12, lw=0)
        off, va = (1.0, "bottom") if ths == "65°C" else (-1.0, "top")
        for x_, y_ in zip(d.rho, d.flip_any_pct): axs[0].text(x_, y_ + off, f"{y_:.1f}", ha="center", va=va, fontsize=7.5)
        for x_, y_ in zip(d.rho, d.regret_mwh_mean):
            if x_ in (0.0, 0.5, 1.0): axs[1].text(x_ + 0.02, y_ + 2.5 * off, f"{y_:.0f}", ha="left", va=va, fontsize=7.5)
    axs[0].set_ylabel("판단이 바뀐 시간 (% / 년)"); axs[1].set_ylabel("손실 (MWh/년, 1차) · 음영: 95% 분위")
    for a in axs:
        a.set_xlabel("후보 간 오차 상관계수 ρ  (0 = 후보별 독립, 1 = 공통)"); a.set_xticks(RHOS)
        a.spines[["top", "right"]].set_visible(False); a.legend(frameon=False, fontsize=8.5)
        a.set_ylim(bottom=0)
    axs[0].set_title("오차의 상관이 약할수록 판단이 자주 바뀐다", loc="left", fontsize=10)
    axs[1].set_title("손실도 상관계수에 따라 급격히 커진다", loc="left", fontsize=10)
    fig.suptitle("예측 오차가 후보들 사이에서 얼마나 '같이' 움직이느냐에 따른 연간 판단 변경과 손실", fontsize=11, x=0.01, ha="left")
    fig.tight_layout(); fig.savefig(OUT / "27_annual_flip.png", dpi=160); plt.close(fig)

if __name__ == "__main__":
    import warnings; warnings.simplefilter("ignore", category=RuntimeWarning)
    cells, summ, modes, ann = main()
    figures(cells, summ, modes, ann)
    pd.set_option("display.width", 220)
    print(summ.round(2).to_string(index=False)); print(ann.round(2).to_string(index=False))
    print(cells.groupby(["heat_supply", "strat_A"]).size())
