"""Chart for the 16 combinations (reads results/combos/combinations_16.csv)."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.family"] = "Noto Sans CJK KR"; plt.rcParams["axes.unicode_minus"] = False
D = Path(__file__).parent / "results" / "combos"
BLUE, ORANGE, GREEN, GRAY = "#2f6fb0", "#d9822b", "#3b8f5a", "#9aa0a6"
df = pd.read_csv(D / "combinations_16.csv").sort_values("final_cut_pct", ascending=True)
y = np.arange(len(df)); h = 0.38
fig, (a, b) = plt.subplots(1, 2, figsize=(11, 6.2), gridspec_kw=dict(width_ratios=[2.2, 1]), sharey=True)
a.barh(y + h / 2, df.final_cut_pct, h, color=BLUE, label="최종에너지 감소 (%)")
a.barh(y - h / 2, df.primary_cut_pct, h, color=ORANGE, label="1차에너지 감소 (%)")
for yi, v1, v2 in zip(y, df.final_cut_pct, df.primary_cut_pct):
    a.text(max(v1, 0) + 0.3, yi + h / 2, f"{v1:.1f}", va="center", fontsize=7.5)
    a.text(max(v2, 0) + 0.3, yi - h / 2, f"{v2:.1f}", va="center", fontsize=7.5)
a.axvline(0, color="#5f6368", lw=0.6)
a.set_yticks(y); a.set_yticklabels(df.combo)
a.set_title("기술 조합별 에너지 감소율 (아무것도 안 했을 때 대비)", loc="left", fontsize=11)
a.legend(frameon=False, fontsize=8.5, loc="lower right"); a.spines[["top", "right"]].set_visible(False)
col = [GREEN if d else GRAY for d in df.D]
b.hlines(y, 0, df.peak_kw, color=col, lw=1.2, alpha=0.6)
b.scatter(df.peak_kw, y, color=col, s=36, zorder=3)
for yi, v in zip(y, df.peak_kw): b.text(v + 25, yi, f"{v:,.0f}", va="center", fontsize=7.5)
b.set_xlim(0, df.peak_kw.max() * 1.18)
b.set_title("전력 피크 (kW) · 초록 = ESS 포함", loc="left", fontsize=11); b.spines[["top", "right"]].set_visible(False)
fig.text(0.01, 0.01, "A 효율냉각(수랭+외기냉방) · B 고효율 전력변환 · C 히트펌프 폐열회수 · D ESS 피크저감", fontsize=8.5, color="#5f6368")
fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(D / "07_combinations.png", dpi=160); plt.close(fig)
