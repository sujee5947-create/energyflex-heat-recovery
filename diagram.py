"""System-boundary schematic (00_system_boundary.png)."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.family"] = "Noto Sans CJK KR"
OUT = Path(__file__).parent / "results"
BLUE, ORANGE, GREEN, GRAY, PURPLE = "#2f6fb0", "#d9822b", "#3b8f5a", "#5f6368", "#8e5bb5"
fig, ax = plt.subplots(figsize=(11, 6.2)); ax.set_xlim(0, 110); ax.set_ylim(0, 62); ax.axis("off")

def box(x, y, w, h, txt, fc, ec="#333", fs=9.5, ls="-", lw=1.2, tc="#111", r=1.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, ls=ls, lw=lw))
    if txt: ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center", fontsize=fs, color=tc)

def arrow(x1, y1, x2, y2, col, txt=None, tx=0, ty=1.2, lw=2.2):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14, color=col, lw=lw))
    if txt: ax.text((x1 + x2) / 2 + tx, (y1 + y2) / 2 + ty, txt, ha="center", fontsize=8.5, color=col)

def line(pts, col, lw=2.2):
    xs, ys = zip(*pts); ax.plot(xs, ys, color=col, lw=lw, solid_capstyle="round")

# boundaries
box(17, 3, 74, 55, "", "none", ec=GRAY, ls="--", lw=1.3)
ax.text(18.5, 55.6, "사이트 경계 — 최종에너지·1차에너지는 이 선을 넘는 에너지로 센다", fontsize=9.5, color=GRAY)
box(21, 24, 40, 23, "", "#f3f6fa", ec=BLUE, ls="--", lw=1.3)
ax.text(22.5, 25.2, "데이터센터 경계 — PUE는 여기 안만 본다", fontsize=9, color=BLUE)
box(23, 32, 9, 8, "전력변환\n(UPS)", "white"); box(34, 32, 11, 8, "IT 서버\n+조명 등", "white")
box(48, 29, 11.5, 12, "냉각\n건식냉각기 팬\n냉동기·펌프", "white", fs=9)
box(66, 26, 14, 10, "히트펌프\n(서버 열 → 65°C)", "#eef6f0", ec=GREEN)
box(66, 4, 14, 8, "보일러\n(가스)", "#f4f4f4", ec=GRAY)
box(1, 32, 12, 8, "전력망\n(전기)", "#fff7ee", ec=ORANGE); box(1, 5, 12, 6, "가스", "#f4f4f4", ec=GRAY)
box(95, 47, 14, 8, "AI 작업량\n(모든 경우 동일)", "#eef3fb", ec=BLUE, fs=8.8)
box(95, 37, 14, 7, "외기로 버린 열", "#f4f4f4", ec=GRAY, fs=8.8)
box(95, 20, 14, 10, "이웃 건물\n난방·온수\n(모든 경우 동일)", "#eef6f0", ec=GREEN, fs=8.8)
arrow(13, 36, 23, 36, ORANGE)
line([(7, 32), (7, 20), (73, 20)], ORANGE); arrow(73, 20, 73, 26, ORANGE)
ax.text(40, 20.8, "히트펌프용 전기", fontsize=8.5, color=ORANGE)
arrow(13, 8, 66, 8, GRAY)
line([(39.5, 40), (39.5, 51)], BLUE); arrow(39.5, 51, 95, 51, BLUE)
arrow(59.5, 32, 66, 31, GREEN); ax.text(62.8, 33.2, "서버 열", fontsize=8.5, color=GREEN, ha="center")
arrow(59.5, 38, 95, 40.5, GRAY); ax.text(78, 40.6, "남는 열", fontsize=8.5, color=GRAY)
arrow(80, 30, 95, 26, GREEN); ax.text(85.2, 30.6, "유효열\n(배관손실 5% 뺀 값)", fontsize=7.6, color=GREEN, ha="center")
arrow(80, 8, 95, 21.5, GRAY); ax.text(87, 7.5, "부족분", fontsize=8.5, color=GRAY)
ax.text(1, 0.6, "같은 서비스(오른쪽 파랑·초록)를 내는 데 왼쪽에서 들어간 전기·가스가 얼마나 줄었는지를 비교한다. 전기요금은 어떤 결정에도 쓰지 않는다.",
        fontsize=9, color="#333")
fig.tight_layout(); fig.savefig(OUT / "00_system_boundary.png", dpi=170); plt.close(fig)
