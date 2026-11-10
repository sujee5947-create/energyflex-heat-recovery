"""v1.3 physics results: CSVs + charts in results/v13/."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import config as C
import physics as ph
import sim13

plt.rcParams["font.family"] = "Noto Sans CJK KR"; plt.rcParams["axes.unicode_minus"] = False
OUT = Path(__file__).parent / "results" / "v13"; OUT.mkdir(parents=True, exist_ok=True)
BLUE, ORANGE, GREEN, PURPLE, GRAY = "#2f6fb0", "#d9822b", "#3b8f5a", "#8e5bb5", "#9aa0a6"
P = C.V13

base, outs, res, chk, svc, dec = sim13.run13()
res.to_csv(OUT / "v13_summary.csv", encoding="utf-8-sig")
pd.DataFrame(chk).T.to_csv(OUT / "v13_balance_checks.csv", encoding="utf-8-sig")
pd.DataFrame(svc).T.to_csv(OUT / "v13_same_service.csv", encoding="utf-8-sig")
dec.to_csv(OUT / "v13_equipment_vs_operation.csv", encoding="utf-8-sig")
v12 = pd.read_csv(Path(__file__).parent / "results" / "summary_metrics.csv", index_col=0)

# 11) heat pump COP: water temperatures + part load
fig, axs = plt.subplots(1, 2, figsize=(10, 3.8))
tr = np.linspace(30, 50, 81)
for ths, col in [(65, ORANGE), (45, BLUE)]:
    cop = ph.hp_cop(tr, ths, 1.0)[0]
    axs[0].plot(tr, cop, color=col, lw=2)
    xt, yt = (31, P['hp_cop_max'] - 0.6) if ths == 45 else (44, 4.2)
    axs[0].text(xt, yt, f"난방 공급 {ths}°C", color=col, fontsize=9.5, fontweight="bold")
axs[0].axhline(P["hp_cop_max"], color=GRAY, ls="--", lw=0.8)
axs[0].text(49.5, P["hp_cop_max"] - 0.25, f"COP 상한 {P['hp_cop_max']:.0f} (Gasser 2017 저리프트 실증값)", fontsize=8, color="#555", ha="right")
axs[0].axvline(40, color=GRAY, ls=":", lw=1); axs[0].text(40.2, 2.2, "설계 환수 40°C", fontsize=8, color="#555")
axs[0].set_xlim(30, 50); axs[0].set_ylim(2, P['hp_cop_max'] + 0.8)
axs[0].set_xlabel("서버 냉각수 환수 온도 (°C) = 히트펌프 열원"); axs[0].set_ylabel("COP (전기 1 → 열 몇)")
axs[0].set_title("COP는 '물 온도 차이'가 결정한다", loc="left", fontsize=11)
plr = np.linspace(0.02, 1, 99)
axs[1].plot(plr * 100, ph.hp_cop(40, 65, plr)[2], color=PURPLE, lw=2)
axs[1].axvline(P["hp_plr_mod_min"] * 100, color=GRAY, ls=":", lw=1)
axs[1].text(P["hp_plr_mod_min"] * 100 + 2, 0.78, "이 아래는 켜졌다 꺼졌다(사이클링)", fontsize=8, color="#555")
axs[1].set_xlabel("부분부하율 PLR (%)"); axs[1].set_ylabel("효율 보정계수 PLF"); axs[1].set_ylim(0.7, 1.03)
axs[1].set_title("너무 적게 돌리면 효율이 떨어진다", loc="left", fontsize=11)
for a in axs: a.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "11_hp_cop_model.png", dpi=160); plt.close(fig)

# 12) pump model vs pure cube law
q = np.linspace(0.05, 1, 96) * P["design_heat_kw"]
pm, phi = ph.pump_power_kw(q, P["liquid_dT"]); pc = ph.pump_power_cube_law(q, P["liquid_dT"])
fig, ax = plt.subplots(figsize=(8, 3.8))
ax.plot(q / P["design_heat_kw"] * 100, pm, color=BLUE, lw=2)
ax.plot(q / P["design_heat_kw"] * 100, pc, color=ORANGE, lw=2, ls="--")
ax.text(33, 6.2, "v1.3 모델(파랑 실선):\n정압 + 마찰 + 최소유량 + 효율곡선", color=BLUE, fontsize=9)
ax.text(66, 1.0, "단순 세제곱 법칙(주황 점선):\n사용하지 않음", color=ORANGE, fontsize=9)
ax.axvline(P["pump_min_flow"] * 100, color=GRAY, ls=":", lw=1)
ax.text(P["pump_min_flow"] * 100 + 1, pm.max() * 0.9, "최소 유량 30%", fontsize=8, color="#555")
ax.set_xlabel("냉각 부하 (설계 대비 %)"); ax.set_ylabel("펌프 전력 (kW)")
ax.set_title("부분 부하에서 펌프 전력은 세제곱 법칙보다 훨씬 덜 줄어든다", loc="left", fontsize=11)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "12_pump_model.png", dpi=160); plt.close(fig)

# 13) v1.3 energy breakdown by device (65 °C)
keys = ["S0 기존(공랭)", "S1 규칙운전", "S1 최적운전", "S2 규칙운전", "S2 최적운전"]
r65 = res.loc[[f"65°C | {k}" for k in keys]]
parts = [("IT 장비", "it_mwh", "#c8ccd2"), ("기타", "misc_mwh", "#e3e5e8"), ("전력변환 손실", "conv_mwh", ORANGE),
         ("냉동기", "chiller_mwh", "#1f4e80"), ("건식냉각기 팬", "dc_fan_mwh", BLUE), ("실내 공조기 팬", "crah_fan_mwh", "#7aa6d6"),
         ("펌프", "pump_mwh", PURPLE), ("히트펌프", "hp_mwh", GREEN), ("보일러 연료", "boiler_fuel_mwh", GRAY)]
fig, ax = plt.subplots(figsize=(9, 4.8)); bottom = np.zeros(len(keys))
for lbl, c, col in parts:
    ax.bar(keys, r65[c], bottom=bottom, color=col, label=lbl, edgecolor="white", linewidth=0.6); bottom += r65[c].values
for i, t in enumerate(r65.final_mwh): ax.text(i, t + 120, f"{t:,.0f}", ha="center", fontsize=9.5, fontweight="bold")
ax.set_ylabel("연간 최종에너지 (MWh)"); ax.tick_params(axis="x", labelsize=9)
ax.set_title("v1.3: 팬·펌프·냉동기를 장비별로 나눠 본 에너지 (난방 공급 65°C)", loc="left", fontsize=11)
ax.legend(ncol=5, fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.09))
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "13_v13_breakdown.png", dpi=160); plt.close(fig)

# 14) equipment vs operation (waterfall, primary energy) for 65 and 45 °C
fig, axs = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
for a, ths in zip(axs, P["heat_supply_c"]):
    g = lambda k: res.loc[f"{ths:.0f}°C | {k}", "primary_mwh"]
    steps = [("S0 기존", g("S0 기존(공랭)"), "total"), ("설비①\n수랭+UPS", g("S1 규칙운전") - g("S0 기존(공랭)"), "eq"),
             ("설비②\n히트펌프", g("S2 규칙운전") - g("S1 규칙운전"), "eq"),
             ("운전\n최적화", g("S2 최적운전") - g("S2 규칙운전"), "op"), ("S2 최적", g("S2 최적운전"), "total")]
    run = 0
    for i, (lbl, v, kind) in enumerate(steps):
        if kind == "total":
            a.bar(i, v, color=GRAY, width=0.6); a.text(i, v + 300, f"{v:,.0f}", ha="center", fontsize=9); run = v
        else:
            a.bar(i, -v, bottom=run + v, color=BLUE if kind == "eq" else ORANGE, width=0.6)
            a.text(i, run + 300, f"−{-v:,.0f}\n({-v/steps[0][1]*100:.1f}%)", ha="center", fontsize=8.5); run += v
    a.set_xticks(range(5)); a.set_xticklabels([s[0] for s in steps], fontsize=8.5)
    a.set_ylim(15000, 29500); a.set_title(f"난방 공급 {ths:.0f}°C", loc="left", fontsize=10.5)
    a.spines[["top", "right"]].set_visible(False)
axs[0].set_ylabel("연간 1차에너지 (MWh)")
fig.suptitle("절감의 대부분은 '설비'(파랑)에서, '운전 최적화'(주황)는 작지만 공급온도가 높을수록 커진다", fontsize=11, x=0.01, ha="left")
fig.tight_layout(); fig.savefig(OUT / "14_equipment_vs_operation.png", dpi=160); plt.close(fig)

# 15) what the optimiser chose + how close the 1st and 2nd choice were
fig, axs = plt.subplots(1, 2, figsize=(11, 3.9))
cols = {25.0: "#c6dbef", 30.0: "#7aa6d6", 35.0: BLUE, 40.0: "#1f4e80", 45.0: "#0b2a4a"}
MONTH = pd.date_range("2025-01-01", periods=C.HOURS, freq="h").month   # real calendar months
for a, ths in zip(axs, P["heat_supply_c"]):
    o = outs[f"{ths:.0f}°C | S2 최적운전"].copy(); o["month"] = MONTH
    sh = pd.crosstab(o.month, o.t_sup, normalize="index") * 100; bottom = np.zeros(12)
    for t in sorted(sh.columns):
        a.bar(sh.index, sh[t], bottom=bottom, color=cols[t], label=f"{t:.0f}°C", edgecolor="white", linewidth=0.5); bottom += sh[t].values
    a.set_xticks(range(1, 13)); a.set_xlabel("월"); a.set_ylim(0, 100)
    a.set_title(f"난방 공급 {ths:.0f}°C: 시간별로 고른 냉각수 공급온도", loc="left", fontsize=10)
    a.spines[["top", "right"]].set_visible(False)
axs[0].set_ylabel("시간 비율 (%)"); axs[1].legend(title="공급온도", fontsize=8, title_fontsize=8, frameon=False, bbox_to_anchor=(1.0, 1.0), loc="upper left")
fig.tight_layout(); fig.savefig(OUT / "15_operation_choice.png", dpi=160); plt.close(fig)

# 16) how close were the 1st and 2nd choice, and what separated them
bins = np.array([0, 0.25, 0.5, 1, 2, 5, 100])
labels = ["<0.25%", "0.25–0.5%", "0.5–1%", "1–2%", "2–5%", "≥5%"]
kinds = [("냉각수 온도만", "#c6dbef"), ("냉각 방식(외기냉방↔냉동기)", BLUE), ("히트펌프 운전량", ORANGE)]
fig, axs = plt.subplots(1, 2, figsize=(11, 3.9), sharey=True)
for a, ths in zip(axs, P["heat_supply_c"]):
    o = outs[f"{ths:.0f}°C | S2 최적운전"]
    bottom = np.zeros(6)
    for kname, col in kinds:
        g = o.gap_1st_2nd_pct[o.second_kind == kname]
        h = np.histogram(g, bins)[0] / len(o) * 100
        a.bar(range(6), h, bottom=bottom, color=col, label=kname, edgecolor="white", linewidth=0.5); bottom += h
    for i, v in enumerate(bottom):
        a.text(i, v + 1, f"{v:.0f}", ha="center", fontsize=8)
    a.set_xticks(range(6)); a.set_xticklabels(labels, fontsize=8); a.set_xlabel("1위와 2위 후보의 1차에너지 차이")
    a.set_title(f"난방 공급 {ths:.0f}°C", loc="left", fontsize=10); a.spines[["top", "right"]].set_visible(False)
axs[0].set_ylabel("시간 비율 (%)")
axs[1].legend(title="1·2위를 가른 것", fontsize=8, title_fontsize=8, frameon=False, loc="upper right")
fig.suptitle("1·2위 차이가 1% 미만인 시간의 대부분은 '냉각수 온도만' 다른 경우다 — 운전 방식이 갈리는 시간은 일부", fontsize=11, x=0.01, ha="left")
fig.tight_layout(); fig.savefig(OUT / "16_decision_gap.png", dpi=160); plt.close(fig)

# 17) v1.2 vs v1.3 (rule-based, 65 °C) final energy
pairs = [("S0 기존", "S0_Baseline", "65°C | S0 기존(공랭)"), ("S1 효율냉각", "S1_EffCooling", "65°C | S1 규칙운전"),
         ("S2 +열회수", "S2_HeatRecovery", "65°C | S2 규칙운전")]
fig, ax = plt.subplots(figsize=(8, 3.8)); w = 0.36
for k, (lab, col) in enumerate([("v1.2 (보조전력 = 비율 가정)", GRAY), ("v1.3 (팬·펌프·COP 물리 모델)", BLUE)]):
    vals = [v12.loc[a, "total_final_energy_kwh"] / 1e3 if k == 0 else res.loc[b, "final_mwh"] for _, a, b in pairs]
    ax.bar(np.arange(3) + (k - 0.5) * w, vals, w, color=col, label=lab)
    for i, v in enumerate(vals): ax.text(i + (k - 0.5) * w, v + 100, f"{v:,.0f}", ha="center", fontsize=8.5)
ax.set_xticks(range(3)); ax.set_xticklabels([p[0] for p in pairs]); ax.set_ylabel("연간 최종에너지 (MWh)")
ax.legend(frameon=False, fontsize=9, loc="upper right"); ax.spines[["top", "right"]].set_visible(False)
ax.set_title("모델을 정교화하면 숫자가 얼마나 바뀌나 (규칙 운전, 65°C)", loc="left", fontsize=11)
fig.tight_layout(); fig.savefig(OUT / "17_v12_vs_v13.png", dpi=160); plt.close(fig)

# 19) coolant class (ASHRAE W-class) -> allowed supply temperature -> results
cls_rows = []
orig = P["coolant_class"]
for cl in ["W32", "W40", "W45"]:
    P["coolant_class"] = cl
    _, o_c, r_c, _, _, d_c = sim13.run13()
    for ths in P["heat_supply_c"]:
        k = f"{ths:.0f}°C"
        cls_rows.append(dict(coolant_class=cl, heat_supply=k, max_supply_c=P["coolant_class_max"][cl],
                             op_effect_mwh=d_c.loc["운전②: 냉각수 온도·히트펌프 운전량 최적화", k],
                             saving_pct=(1 - r_c.loc[f"{k} | S2 최적운전", "primary_mwh"] / r_c.loc[f"{k} | S0 기존(공랭)", "primary_mwh"]) * 100,
                             it_mwh=r_c.loc[f"{k} | S2 최적운전", "it_mwh"]))
P["coolant_class"] = orig
cls = pd.DataFrame(cls_rows); cls.to_csv(OUT / "v13_coolant_class.csv", index=False, encoding="utf-8-sig")
fig, ax = plt.subplots(figsize=(8, 3.6)); w = 0.36
for k, (ths, col) in enumerate([("65°C", ORANGE), ("45°C", BLUE)]):
    d = cls[cls.heat_supply == ths]
    ax.bar(np.arange(3) + (k - 0.5) * w, d.op_effect_mwh, w, color=col, label=f"난방 공급 {ths}")
    for i, v in enumerate(d.op_effect_mwh): ax.text(i + (k - 0.5) * w, v + 5, f"{v:,.0f}", ha="center", fontsize=8.5)
ax.set_xticks(range(3)); ax.set_xticklabels([f"{c}\n(공급 ≤{P['coolant_class_max'][c]:.0f}°C)" for c in ["W32", "W40", "W45"]])
ax.set_ylabel("운전 최적화 효과 (MWh/년, 1차)"); ax.legend(frameon=False, fontsize=9)
ax.set_title("서버가 허용하는 냉각수 온도(ASHRAE 등급)가 운전 최적화의 크기를 정한다", loc="left", fontsize=11)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "19_coolant_class.png", dpi=160); plt.close(fig)
_, outs, res, chk, svc, dec = sim13.run13()   # back to the default class for the rest

# feasibility table
feas = res[["cond_raised_h", "free_cap_limited_h", "dc_fan_need_max", "max_t_cond", "max_t_sup", "hp_level_mean", "ess_peak_kw", "peak_kw"]]
feas.to_csv(OUT / "v13_feasibility.csv", encoding="utf-8-sig")
pd.Series(dict(t_design_c=P["t_design_c"], dc_design_kw=P["dc_design_kw"], dc_fan_rated_kw=P["dc_fan_rated_kw"],
               coolant_class=P["coolant_class"],
               breakeven_cop=C.PEF_ELEC * C.BOILER_EFF / C.PEF_GAS)).to_csv(OUT / "v13_design.csv", encoding="utf-8-sig")
res.to_csv(OUT / "v13_summary.csv", encoding="utf-8-sig")
dec.to_csv(OUT / "v13_equipment_vs_operation.csv", encoding="utf-8-sig")
pd.DataFrame(chk).T.to_csv(OUT / "v13_balance_checks.csv", encoding="utf-8-sig")
print(cls.round(1).to_string(index=False))
print("max balance:", max(abs(v) for d in chk.values() for v in d.values()))
print("same-service worst:", max(v for d in svc.values() for v in d.values()))
for ths in P["heat_supply_c"]:
    g = outs[f"{ths:.0f}°C | S2 최적운전"].gap_1st_2nd_pct
    print(ths, "gap<1%:", round((g < 1).mean() * 100, 1), "median gap", round(g.median(), 3))
print(sorted(p.name for p in OUT.iterdir()))
