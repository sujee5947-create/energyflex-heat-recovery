"""Run all scenarios and write results/ (CSV + charts)."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import config as C
import sim

plt.rcParams["font.family"] = "Noto Sans CJK KR"
plt.rcParams["axes.unicode_minus"] = False
OUT = Path(__file__).parent / "results"
OUT.mkdir(exist_ok=True)
NAMES = {"S0_Baseline": "S0 기존", "S1_EffCooling": "S1 효율냉각",
         "S2_HeatRecovery": "S2 +폐열회수", "S3_HR_ESS": "S3 +ESS"}
GRAY, BLUE, GREEN, ORANGE = "#9aa0a6", "#2f6fb0", "#3b8f5a", "#d9822b"

base, outs, res, chk, ess_cmp, thr = sim.run_all()
res.T.to_csv(OUT / "summary_metrics.csv", encoding="utf-8-sig")
pd.DataFrame(chk).T.to_csv(OUT / "energy_balance_checks.csv", encoding="utf-8-sig")
pd.DataFrame(ess_cmp).T.to_csv(OUT / "ess_window_comparison.csv", encoding="utf-8-sig")
for n, o in outs.items():
    o.to_csv(OUT / f"hourly_{n}.csv", index=False, encoding="utf-8-sig")

r = res.T
x = [NAMES[n] for n in r.index]
MWh = 1e-3

# 1) final energy breakdown (electricity components + boiler fuel)
fig, ax = plt.subplots(figsize=(8, 4.6))
parts = [("IT 장비", r.it_kwh, "#c8ccd2"), ("전력변환 손실", r.conversion_loss_kwh, ORANGE),
         ("냉각", r.cooling_kwh, BLUE), ("히트펌프", r.heat_pump_kwh, GREEN),
         ("ESS 손실", r.ess_loss_kwh, "#8e5bb5"), ("보일러 연료(가스)", r.boiler_fuel_kwh, GRAY)]
misc = r.facility_elec_kwh - r.it_kwh - r.conversion_loss_kwh - r.cooling_kwh - r.heat_pump_kwh - r.ess_loss_kwh
parts.insert(1, ("기타(조명 등)", misc, "#e3e5e8"))
bottom = 0
for lbl, v, col in parts:
    ax.bar(x, v * MWh, bottom=bottom, label=lbl, color=col, edgecolor="white", linewidth=0.5)
    bottom = bottom + v * MWh
for i, t in enumerate(r.total_final_energy_kwh * MWh):
    ax.text(i, t + 120, f"{t:,.0f}", ha="center", fontsize=10, fontweight="bold")
ax.set_ylabel("연간 최종에너지 (MWh)")
ax.set_title("같은 AI 작업량·같은 난방 수요를 처리하는 데 든 총 에너지", fontsize=12, loc="left")
ax.legend(ncol=4, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.1), frameon=False)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "01_final_energy_breakdown.png", dpi=160); plt.close(fig)

# 2) three accounting bases: final, primary, exergy (relative to S0)
fig, ax = plt.subplots(figsize=(8, 4))
w = 0.26
for k, (col_name, lbl, colr) in enumerate([("total_final_energy_kwh", "최종에너지", BLUE),
                                           ("primary_energy_kwh", "1차에너지", ORANGE),
                                           ("exergy_input_kwh", "엑서지 투입", GREEN)]):
    rel = r[col_name] / r[col_name].iloc[0] * 100
    xs = [i + (k - 1) * w for i in range(len(x))]
    ax.bar(xs, rel, w, label=lbl, color=colr)
    for xi, v in zip(xs, rel):
        ax.text(xi, v + 1, f"{v:.0f}", ha="center", fontsize=8)
ax.set_xticks(range(len(x))); ax.set_xticklabels(x)
ax.set_ylabel("S0 대비 (%)"); ax.set_ylim(0, 115)
ax.set_title("평가 기준에 따라 개선 폭이 다르다 (S0 = 100)", fontsize=12, loc="left")
ax.legend(frameon=False, fontsize=9); ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "02_accounting_bases.png", dpi=160); plt.close(fig)

# 3) monthly heat: useful heat delivered vs heat still rejected outdoors (S2)
o2 = outs["S2_HeatRecovery"].copy()
o2["month"] = pd.date_range("2025-01-01", periods=len(o2), freq="h").month
m = o2.groupby("month").agg(demand=("heat_demand_kw", "sum"), useful=("q_useful", "sum"),
                            rejected=("q_free", "sum"), chiller=("q_chiller", "sum"))
fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(m.index - 0.2, m.useful * MWh, 0.38, color=GREEN, label="회수해서 실제로 쓴 열(유효열)")
ax.bar(m.index + 0.2, (m.rejected + m.chiller) * MWh, 0.38, color=GRAY, label="그래도 외기로 버린 열")
ax.set_xticks(range(1, 13)); ax.set_xlabel("월"); ax.set_ylabel("MWh")
ax.set_title("여름에는 열수요가 작아 회수할 곳이 부족하다 (S2)", fontsize=12, loc="left")
ax.legend(frameon=False, fontsize=9); ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "03_monthly_heat.png", dpi=160); plt.close(fig)

# 4) ESS window trade-off
e = pd.DataFrame(ess_cmp).T
fig, axs = plt.subplots(1, 3, figsize=(9, 3.3))
for a, (col, lbl, fmt) in zip(axs, [("peak_cut_kw", "피크 저감 (kW)", "{:.0f}"),
                                    ("ess_loss_kwh", "충방전 손실 (MWh/년)", "{:.1f}"),
                                    ("total_fade", "용량 감소 (%/년)", "{:.1f}")]):
    vals = e[col] * (1e-3 if "loss" in col else 100 if "fade" in col else 1)
    a.bar(["열화 고려\nSOC 20–90%", "공격적\nSOC 5–100%"], vals, color=[GREEN, ORANGE])
    for i, v in enumerate(vals):
        a.text(i, v, fmt.format(v), ha="center", va="bottom", fontsize=9)
    a.set_title(lbl, fontsize=10); a.spines[["top", "right"]].set_visible(False)
fig.suptitle("ESS 운전 범위: 피크를 조금 더 깎는 대가로 배터리를 더 쓴다", fontsize=12, x=0.02, ha="left")
fig.tight_layout(); fig.savefig(OUT / "04_ess_tradeoff.png", dpi=160); plt.close(fig)

# 8) heat funnel (S2): generated -> recoverable -> recovered -> heat pump output -> useful
s2 = r.loc["S2_HeatRecovery"]
steps = [("① 서버가 만든 열\n(발생열)", s2.heat_generated_kwh, GRAY),
         ("② 회수 가능한 열\n(히트펌프 용량 한도)", s2.heat_recoverable_kwh, "#7aa6d6"),
         ("③ 실제로 뽑아낸 열\n(회수열, 수요 한도)", s2.heat_extracted_kwh, BLUE),
         ("④ 히트펌프 출력\n(③ + 히트펌프 전기)", s2.heat_recovered_kwh, "#5b9b74"),
         ("⑤ 이웃 건물이 쓴 열\n(유효열, 배관손실 후)", s2.heat_useful_kwh, GREEN)]
fig, ax = plt.subplots(figsize=(8.4, 4.4))
for i, (lbl, v, col) in enumerate(steps):
    ax.barh(i, v * MWh, color=col, height=0.62)
    ax.text(v * MWh + 80, i, f"{v*MWh:,.0f} MWh  ({v/s2.heat_generated_kwh*100:.0f}%)", va="center", fontsize=9)
ax.set_yticks(range(len(steps))); ax.set_yticklabels([x[0] for x in steps], fontsize=9); ax.invert_yaxis()
ax.text(0.99, 0.04, f"히트펌프 전기 +{s2.heat_pump_kwh*MWh:,.0f} MWh 투입 · 배관손실 −{s2.pipe_loss_kwh*MWh:,.0f} MWh",
        transform=ax.transAxes, ha="right", fontsize=8.5, color="#444")
ax.set_xlim(0, s2.heat_generated_kwh * MWh * 1.32); ax.set_xlabel("연간 열량 (MWh)")
ax.set_title("서버 열 중 실제로 쓰인 열은 얼마인가 (S2, 1년)", loc="left", fontsize=12)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "08_heat_funnel.png", dpi=160); plt.close(fig)

# 9) same-service check: annual totals per scenario are identical
svc, worst = sim.same_service(outs)
fig, axs = plt.subplots(1, 3, figsize=(10, 3.2))
for a, (lbl, vals, unit) in zip(axs, [
        ("AI 작업량", [o.jobs.sum() / 1e6 for o in outs.values()], "백만 작업"),
        ("서버 발열(IT) — 전부 냉각됨", [o.it_kw.sum() * MWh for o in outs.values()], "MWh"),
        ("이웃 건물에 공급한 열", [(o.q_useful + o.q_boiler).sum() * MWh for o in outs.values()], "MWh")]):
    a.bar(x, vals, color=[GRAY, BLUE, GREEN, "#8e5bb5"], width=0.6)
    for i, v in enumerate(vals):
        a.text(i, v * 1.01, f"{v:,.2f}" if unit == "백만 작업" else f"{v:,.0f}", ha="center", fontsize=8)
    a.set_title(f"{lbl} ({unit})", fontsize=10, loc="left"); a.set_ylim(0, max(vals) * 1.15)
    a.tick_params(axis="x", labelsize=8); a.spines[["top", "right"]].set_visible(False)
fig.suptitle(f"모든 경우가 같은 서비스를 제공한다 (시간별 최대 차이 {worst:.0e})",
             fontsize=10.5, x=0.01, ha="left")
fig.tight_layout(); fig.savefig(OUT / "09_same_service.png", dpi=160); plt.close(fig)
pd.DataFrame(svc).T.to_csv(OUT / "same_service_check.csv", encoding="utf-8-sig")

print("written:", sorted(p.name for p in OUT.iterdir()))
print("max balance residual:", max(abs(v) for d in chk.values() for v in d.values()))
