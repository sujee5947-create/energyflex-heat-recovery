"""v1.4 results: stress test (P0), heat pump COP method (P1), ideal vs realistic operation (P2). -> results/v14/"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import config as C
import sim
import sim13

plt.rcParams["font.family"] = "Noto Sans CJK KR"; plt.rcParams["axes.unicode_minus"] = False
OUT = Path(__file__).parent / "results" / "v14"; OUT.mkdir(parents=True, exist_ok=True)
BLUE, ORANGE, GREEN, PURPLE, GRAY = "#2f6fb0", "#d9822b", "#3b8f5a", "#8e5bb5", "#9aa0a6"
P = C.V13
base = sim.climate_and_load(); sim13.size_dry_cooler(base)
UPS = P["ups_efficient"]

# ---------------- P0 stress test + margin search
st = sim13.stress_test()
st.to_csv(OUT / "stress_test.csv", index=False, encoding="utf-8-sig")
margin = []
for case in ["S0 공랭", "S2 규칙운전"]:
    found = None
    for k in np.arange(5, 31, 1.0):
        b = sim13.stress_base(base, k, True); P["dc_derate"] = 0.8
        o = (sim13.simulate13(b, "air", P["ups_legacy"], False, P["air_chw_supply"], 65.0) if case == "S0 공랭"
             else sim13.simulate13(b, "liquid", UPS, True, P["liquid_supply_design"], 65.0, 1.0))
        P["dc_derate"] = 1.0
        if o.infeasible.any():
            found = dict(case=case, heatwave_K=k, max_t_out=float(b.t_out.max()), infeasible_h=int(o.infeasible.sum())); break
    margin.append(found or dict(case=case, heatwave_K=np.nan, max_t_out=np.nan, infeasible_h=0))
margin = pd.DataFrame(margin); margin.to_csv(OUT / "stress_margin.csv", index=False, encoding="utf-8-sig")

names = [n for n, _ in sim13.STRESS]
fig, ax = plt.subplots(figsize=(10, 4.6))
y = np.arange(len(names))
for k, (case, col, mk) in enumerate([("S0 공랭", GRAY, "o"), ("S2 규칙운전", BLUE, "s"), ("S2 최적운전", ORANGE, "D")]):
    d = st[st.case == case].set_index("stress").loc[names]
    ax.scatter(d.max_t_cond, y + (k - 1) * 0.22, color=col, marker=mk, s=40, label=case, zorder=3)
    for yi, v, h in zip(y + (k - 1) * 0.22, d.max_t_cond, d.cond_raised_h):
        if h > 0: ax.text(v + 0.3, yi, f"응축온도 상승 {h:,}시간", fontsize=7.5, va="center")
ax.axvline(P["chiller_t_cond_max"], color="#c0392b", lw=1.5)
ax.text(P["chiller_t_cond_max"] - 0.3, -0.55, f"냉동기 운전 한계 {P['chiller_t_cond_max']:.0f}°C", color="#c0392b", ha="right", fontsize=9)
ax.set_yticks(y); ax.set_yticklabels(names, fontsize=9); ax.set_ylim(len(names) - 0.4, -0.9)
ax.set_xlabel("연중 최고 냉동기 응축온도 (°C)"); ax.set_xlim(38, 62)
ax.legend(frameon=False, fontsize=8.5, loc="center right")
ax.set_title("가혹 조건에서도 냉동기 운전 한계 안에 머문다 (불가능 운전 0시간)", loc="left", fontsize=11)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "20_stress_test.png", dpi=160); plt.close(fig)

# ---------------- P1 heat pump COP method
rows = []
orig = P["hp_cop_method"]
for m, lab in [("inlet", "v1.3: 열원 입구 −5 K"), ("outlet", "v1.4: 열원 출구 − 핀치 (기본)"), ("lorenz", "로렌츠 (비교용)")]:
    P["hp_cop_method"] = m
    for ths in P["heat_supply_c"]:
        o = sim13.simulate13(base, "liquid", UPS, True, P["liquid_supply_design"], ths, 1.0)
        rows.append(dict(method=m, label=lab, heat_supply=ths, seasonal_cop=o.q_hp.sum() / o.w_hp.sum(),
                         primary_mwh=o.primary.sum() / 1e3, cap_hours=int((o.cop_hp >= P["hp_cop_max"] - 1e-9).sum()),
                         mean_src_out=float(o.t_src_out[o.q_hp > 0].mean())))
P["hp_cop_method"] = orig
cm = pd.DataFrame(rows); cm.to_csv(OUT / "hp_cop_methods.csv", index=False, encoding="utf-8-sig")
fig, ax = plt.subplots(figsize=(8.5, 3.8)); w = 0.26
for k, (m, col) in enumerate([("inlet", GRAY), ("outlet", BLUE), ("lorenz", PURPLE)]):
    d = cm[cm.method == m]
    ax.bar(np.arange(2) + (k - 1) * w, d.seasonal_cop, w, color=col, label=d.label.iloc[0])
    for i, v in enumerate(d.seasonal_cop): ax.text(i + (k - 1) * w, v + 0.1, f"{v:.2f}", ha="center", fontsize=8.5)
ax.axhline(P["hp_cop_max"], color=GRAY, ls="--", lw=0.8); ax.text(1.45, P["hp_cop_max"] + 0.1, f"상한 {P['hp_cop_max']:.0f}", fontsize=8, ha="right")
ax.set_xticks(range(2)); ax.set_xticklabels([f"난방 공급 {t:.0f}°C" for t in P["heat_supply_c"]])
ax.set_ylabel("계절 COP (규칙 운전)"); ax.set_ylim(0, P["hp_cop_max"] + 1.3); ax.legend(frameon=False, fontsize=8.5, loc="upper left")
ax.set_title("열원 출구온도로 계산하면 COP가 조금 낮아지고, 로렌츠 상수 효율은 과대평가한다", loc="left", fontsize=11)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "21_hp_cop_methods.png", dpi=160); plt.close(fig)

# ---------------- P2 ideal vs realistic operation
rows, examples = [], {}
for ths in P["heat_supply_c"]:
    cand = sim13.candidates(base, "liquid", UPS, True, ths)
    rule = sim13.simulate13(base, "liquid", UPS, True, P["liquid_supply_design"], ths, 1.0)
    ideal = sim13.optimise(base, "liquid", UPS, True, ths, cand)
    dpp = sim13.realistic(base, UPS, ths, cand, use_forecast=False)
    dpf = sim13.realistic(base, UPS, ths, cand, use_forecast=True)
    r = rule.primary.sum() / 1e3
    for name, o, ch in [("이상적 (매시간 자유, 미래 앎)", ideal, int((np.diff(ideal.t_sup) != 0).sum())),
                        ("제약 운전 (완벽한 정보)", dpp, dpp.attrs["changes"]),
                        ("제약 운전 + 기온 예보", dpf, dpf.attrs["changes"])]:
        rows.append(dict(heat_supply=f"{ths:.0f}°C", mode=name, op_effect_mwh=r - o.primary.sum() / 1e3,
                         setpoint_changes=ch, fallback_h=int(o.get("fallback", pd.Series([False])).sum()),
                         infeasible_h=int(o.infeasible.sum())))
    examples[ths] = (ideal, dpf)
op = pd.DataFrame(rows); op.to_csv(OUT / "ideal_vs_realistic.csv", index=False, encoding="utf-8-sig")
# hold-time sensitivity (65 °C, perfect info + forecast)
cand65 = sim13.candidates(base, "liquid", UPS, True, 65.0)
rule65 = sim13.simulate13(base, "liquid", UPS, True, P["liquid_supply_design"], 65.0, 1.0).primary.sum() / 1e3
hs = []
for h in [1, 4, 12, 24, 72, 168]:
    o = sim13.realistic(base, UPS, 65.0, cand65, use_forecast=True, hold_h=h)
    hs.append(dict(hold_h=h, op_effect_mwh=rule65 - o.primary.sum() / 1e3, changes=o.attrs["changes"]))
hs = pd.DataFrame(hs); hs.to_csv(OUT / "hold_time_sensitivity.csv", index=False, encoding="utf-8-sig")

fig, axs = plt.subplots(1, 2, figsize=(11.5, 4.0), gridspec_kw=dict(width_ratios=[1.3, 1]))
modes = op["mode"].unique(); w = 0.26
for k, (m, col) in enumerate(zip(modes, [GRAY, BLUE, ORANGE])):
    d = op[op["mode"] == m]
    axs[0].bar(np.arange(2) + (k - 1) * w, d.op_effect_mwh, w, color=col, label=m)
    for i, (v, c) in enumerate(zip(d.op_effect_mwh, d.setpoint_changes)):
        axs[0].text(i + (k - 1) * w, v + 4, f"{v:,.0f}\n({c}회)", ha="center", fontsize=7.5)
axs[0].set_xticks(range(2)); axs[0].set_xticklabels([f"난방 공급 {t:.0f}°C" for t in P["heat_supply_c"]])
axs[0].set_ylabel("운전 최적화 효과 (MWh/년, 1차)"); axs[0].set_ylim(0, op.op_effect_mwh.max() * 1.3)
axs[0].legend(frameon=False, fontsize=8, loc="upper right")
axs[0].set_title("이상적 → 실현 가능 운전 (괄호: 연간 설정 변경 횟수)", loc="left", fontsize=10)
axs[1].plot(hs.hold_h, hs.op_effect_mwh, color=BLUE, marker="o", lw=2)
for x_, v, c in zip(hs.hold_h, hs.op_effect_mwh, hs.changes): axs[1].text(x_, v + 4, f"{v:,.0f}", ha="center", fontsize=8)
axs[1].set_xscale("log"); axs[1].set_xticks(hs.hold_h); axs[1].set_xticklabels([f"{h}h" for h in hs.hold_h])
axs[1].set_ylim(0, op.op_effect_mwh.max() * 1.3); axs[1].set_xlabel("설정 변경 후 최소 유지시간")
axs[1].set_title("설정을 오래 고정할수록 효과가 줄어든다 (65°C, 예보 기반)", loc="left", fontsize=10)
for a in axs: a.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "22_ideal_vs_realistic.png", dpi=160); plt.close(fig)

# example weeks
ideal, dpf = examples[65.0]
fig, axs = plt.subplots(1, 2, figsize=(11.5, 3.4), sharey=True)
for a, (start, ttl) in zip(axs, [(24 * 14, "1월 셋째 주"), (24 * 196, "7월 셋째 주")]):
    sl = slice(start, start + 24 * 7); hh = np.arange(24 * 7) / 24
    a.step(hh, ideal.t_sup.values[sl], where="post", color=GRAY, lw=1.2, label="이상적")
    a.step(hh, dpf.t_sup.values[sl], where="post", color=ORANGE, lw=2, label="제약 + 예보")
    a.set_title(ttl, loc="left", fontsize=10); a.set_xlabel("일"); a.spines[["top", "right"]].set_visible(False)
axs[0].set_ylabel("냉각수 공급온도 (°C)"); axs[0].set_yticks([25, 30, 35, 40]); axs[1].legend(frameon=False, fontsize=9)
fig.suptitle("이상적 운전은 수시로 바꾸지만, 제약 운전은 몇 시간씩 유지한다 (65°C 난방)", fontsize=11, x=0.01, ha="left")
fig.tight_layout(); fig.savefig(OUT / "23_week_example.png", dpi=160); plt.close(fig)

# DP constraint check: every change respects hold time and ramp
ts = dpf.t_sup.values; chg = np.flatnonzero(np.diff(ts) != 0) + 1
gaps = np.diff(chg) if len(chg) > 1 else np.array([P["hold_h"]])
pd.Series(dict(min_hours_between_changes=int(gaps.min()), max_step_K=float(np.abs(np.diff(ts)).max()),
               hold_h=P["hold_h"], ramp_K=P["ramp_K"])).to_csv(OUT / "dp_constraint_check.csv", encoding="utf-8-sig")
print(st[st.stress.str.startswith("복합")].round(2).to_string(index=False))
print(margin.to_string(index=False)); print(cm.round(2).to_string(index=False)); print(op.round(1).to_string(index=False))
print(hs.round(1).to_string(index=False)); print("dp check: min gap", gaps.min(), "max step", np.abs(np.diff(ts)).max())
