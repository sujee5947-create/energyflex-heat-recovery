"""Charts for the ESIF validation (reads results/validation/*.csv written by validate_esif.py)."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import matplotlib.dates as mdates

plt.rcParams["font.family"] = "Noto Sans CJK KR"; plt.rcParams["axes.unicode_minus"] = False
V = Path(__file__).parent / "results" / "validation"
BLUE, ORANGE, GRAY, GREEN = "#2f6fb0", "#d9822b", "#5f6368", "#3b8f5a"

t = pd.read_csv(V / "test_hourly.csv", index_col=0, parse_dates=True)
d = t.resample("1D").mean().dropna()
pue_m = 1 + d.non_it / d.it_power_kw
pue_p = 1 + d.pred_v11 / d.it_power_kw
mean, diff = (pue_m + pue_p) / 2, pue_p - pue_m
bias, sd = diff.mean(), diff.std(ddof=1)

fig, axs = plt.subplots(1, 2, figsize=(10, 4))
a = axs[0]
a.plot(d.index, pue_m, color=GRAY, lw=0.8, label="실측 PUE (ESIF)")
a.plot(d.index, pue_p, color=BLUE, lw=0.8, label="모델 예측 PUE (2016–19로 보정)")
a.set_title("검증 구간 2020–2023 일평균 PUE", loc="left", fontsize=11)
a.legend(frameon=False, fontsize=8); a.spines[["top", "right"]].set_visible(False)
a.xaxis.set_major_locator(mdates.YearLocator()); a.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
a = axs[1]
a.scatter(mean, diff, s=6, color=BLUE, alpha=0.5)
for y, ls, lbl in [(bias, "-", f"편향 {bias:+.4f}"), (bias + 1.96 * sd, "--", f"+1.96SD {bias + 1.96*sd:+.4f}"),
                   (bias - 1.96 * sd, "--", f"−1.96SD {bias - 1.96*sd:+.4f}")]:
    a.axhline(y, color=ORANGE, ls=ls, lw=1); a.text(0.98, y, lbl, transform=a.get_yaxis_transform(), ha="right", va="bottom", fontsize=8, color=ORANGE)
a.axhline(0, color=GRAY, lw=0.6)
a.set_xlabel("평균 PUE (실측+예측)/2"); a.set_ylabel("예측 − 실측")
a.set_title("Bland–Altman (일평균, 검증 구간)", loc="left", fontsize=11)
a.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(V / "05_esif_validation.png", dpi=160); plt.close(fig)

y = pd.read_csv(V / "esif_heat_reuse_by_year.csv", index_col=0)
fig, ax1 = plt.subplots(figsize=(8, 3.6))
ax1.bar(y.index, y.reuse_share_of_it_heat * 100, color=GREEN)
for xx, v, it in zip(y.index, y.reuse_share_of_it_heat * 100, y.it_kw):
    ax1.text(xx, v + 0.3, f"{v:.1f}%", ha="center", fontsize=8.5)
    ax1.text(xx, -1.6, f"IT {it:,.0f}kW", ha="center", fontsize=7, color=GRAY)
ax1.set_ylim(-2.4, max(y.reuse_share_of_it_heat * 100) * 1.18)
ax1.set_ylabel("재사용한 열 / IT 발열 (%)"); ax1.axhline(0, color=GRAY, lw=0.6)
ax1.set_title("ESIF: IT 부하는 늘었지만 재사용한 열의 비율은 13% → 1%로 감소", loc="left", fontsize=11)
ax1.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(V / "06_esif_heat_reuse.png", dpi=160); plt.close(fig)

# 10) error breakdown: where is the model wrong? (v1.1, test period 2020-23, non-IT power)
eb = pd.read_csv(V / "error_breakdown.csv", index_col=0)
groups = ["계절", "외기온도", "IT 부하"]
fig, axs = plt.subplots(1, 3, figsize=(11, 3.8), sharey=True)
overall = eb.loc["전체"]
for a, g in zip(axs, groups):
    part = eb[eb.group == g]
    xs = np.arange(len(part)); w = 0.38
    a.bar(xs - w / 2, part.wape_pct, w, color=BLUE, label="WAPE (오차 크기)")
    a.bar(xs + w / 2, part.bias_pct, w, color=ORANGE, label="Bias (치우침, −=과소예측)")
    for xi, v1, v2 in zip(xs, part.wape_pct, part.bias_pct):
        a.text(xi - w / 2, v1 + 1, f"{v1:.0f}", ha="center", fontsize=7.5)
        a.text(xi + w / 2, v2 - 3.5, f"{v2:.0f}", ha="center", fontsize=7.5)
    a.axhline(0, color=GRAY, lw=0.6)
    a.set_xticks(xs); a.set_xticklabels(part.index, fontsize=8)
    a.set_title(g, loc="left", fontsize=10); a.spines[["top", "right"]].set_visible(False)
axs[0].set_ylabel("%")
fig.legend(*axs[0].get_legend_handles_labels(), frameon=False, fontsize=9, ncol=2, loc="lower center")
fig.suptitle(f"모델 오차는 여름·고온·고부하에서 커진다 (전체 WAPE {overall.wape_pct:.0f}%, Bias {overall.bias_pct:.0f}%, 비IT 전력 기준)",
             fontsize=11, x=0.01, ha="left")
fig.tight_layout(rect=(0, 0.07, 1, 1)); fig.savefig(V / "10_error_breakdown.png", dpi=160); plt.close(fig)
print("daily BA:", round(bias, 4), round(bias - 1.96 * sd, 4), round(bias + 1.96 * sd, 4))
