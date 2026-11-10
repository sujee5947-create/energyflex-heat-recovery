"""One-at-a-time sensitivity of the v1.3 results to the assumptions (low / high from the cited ranges).

Outputs results/v13/sensitivity.csv and 18_sensitivity.png (tornado).
Metrics (65 °C heating supply): total primary-energy saving S0 -> S2 optimal (%), operation effect (MWh/yr).
"""
from pathlib import Path
import copy
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import config as C
import sim13

plt.rcParams["font.family"] = "Noto Sans CJK KR"; plt.rcParams["axes.unicode_minus"] = False
OUT = Path(__file__).parent / "results" / "v13"
BLUE, ORANGE, GRAY = "#2f6fb0", "#d9822b", "#5f6368"
pipe = lambda L: round(0.17 * (C.ANNUAL_HEAT_MWH / L) ** -0.5, 3)

# (label, kind, key, low, high, basis)   kind: v13 dict key or module attribute
CASES = [
    ("1차에너지 계수(전기)", "C", "PEF_ELEC", 1.9, 2.75, "EU 에너지효율지침 2023 기본값 1.9 ↔ 국내 2.75"),
    ("칩 누설전력 (%/°C)", "V", "leak_per_K", 0.0003, 0.0022, "Kadhim 2019 유휴 ≈0.03 ↔ 부하 ≈0.22"),
    ("히트펌프 카르노 비율", "V", "hp_carnot", 0.45, 0.55, "실사용 45–55% (OpenEnergyMonitor)"),
    ("히트펌프 COP 상한", "V", "hp_cop_max", 7.0, 11.0, "가정 범위 (실증 COP≈9 기준 ±2)"),
    ("냉동기 카르노 비율", "V", "chiller_carnot", 0.41, 0.50, "ASHRAE 90.1 최소(COP 2.96) ↔ 고효율"),
    ("건식냉각기 접근온도 (K)", "V", "dc_approach", 8.5, 11.8, "제조사 IQR (Wenzel 2023)"),
    ("배관 길이 → 손실", "C", "PIPE_LOSS_FRAC", pipe(100), pipe(800), "IEA 상관식, 100 m ↔ 800 m"),
    ("구형 UPS 효율", "V", "ups_legacy", 0.92, 0.95, "ENERGY STAR 일반 고효율 92–95%"),
    ("보일러 효율", "C", "BOILER_EFF", 0.81, 0.91, "국내 등급 4등급 하한 ↔ 1등급"),
    ("공조기(CRAH) 팬 정격 (kW)", "V", "crah_fan_rated_kw", 20.0, 60.0, "가정 범위 ±50%"),
    ("펌프 정압 비율", "V", "pump_H_static_m", 0.0, 11.5, "가정: 0 ↔ 설계 양정의 1/2"),
    ("펌프 최소유량", "V", "pump_min_flow", 0.20, 0.40, "가정 범위"),
    ("히트펌프 최소 변조율", "V", "hp_plr_mod_min", 0.20, 0.40, "가정 범위"),
    ("히트펌프 핀치 온도차 (K)", "V", "hp_pinch", 1.0, 5.0, "Jensen 2018 검토 범위 0–10 K 중 일반 범위"),
    ("IT 유휴전력 비율", "C", "IT_IDLE_FRACTION", 0.18, 0.26, "H100 실측 18% ↔ CPU 서버 2024년 25.7%"),
]


def metrics():
    _, _, res, _, _, dec = sim13.run13()
    s0 = res.loc["65°C | S0 기존(공랭)", "primary_mwh"]; s2 = res.loc["65°C | S2 최적운전", "primary_mwh"]
    return (1 - s2 / s0) * 100, dec.loc["운전②: 냉각수 온도·히트펌프 운전량 최적화", "65°C"]


def run():
    base_saving, base_op = metrics()
    rows = []
    v13_orig = copy.deepcopy(C.V13)
    for lbl, kind, key, lo, hi, basis in CASES:
        out = {}
        for tag, val in [("low", lo), ("high", hi)]:
            keys = key if isinstance(key, tuple) else (key,)
            saved = {k: (C.V13[k] if kind == "V" else getattr(C, k)) for k in keys}
            for k in keys:
                if kind == "V": C.V13[k] = val
                else: setattr(C, k, val)
            out[tag] = metrics()
            for k, v in saved.items():
                if kind == "V": C.V13[k] = v
                else: setattr(C, k, v)
        rows.append(dict(assumption=lbl, low=lo, high=hi, basis=basis,
                         saving_low=out["low"][0], saving_high=out["high"][0],
                         op_low=out["low"][1], op_high=out["high"][1]))
    assert C.V13 == v13_orig
    df = pd.DataFrame(rows)
    df["saving_span"] = (df.saving_high - df.saving_low).abs()
    df = df.sort_values("saving_span")
    df.to_csv(OUT / "sensitivity.csv", index=False, encoding="utf-8-sig")
    pd.Series(dict(base_saving_pct=base_saving, base_op_mwh=base_op)).to_csv(OUT / "sensitivity_base.csv", encoding="utf-8-sig")

    fig, axs = plt.subplots(1, 2, figsize=(11.5, 5.6), sharey=True)
    y = np.arange(len(df))
    for a, (lo_c, hi_c, base, ttl, fmt) in zip(axs, [
            ("saving_low", "saving_high", base_saving, f"총 1차에너지 절감률 (기준 {base_saving:.1f}%)", "{:.1f}"),
            ("op_low", "op_high", base_op, f"운전 최적화 효과 (기준 {base_op:,.0f} MWh/년)", "{:,.0f}")]):
        for yi, l, h in zip(y, df[lo_c], df[hi_c]):
            a.barh(yi, l - base, left=base, color=GRAY, height=0.6)
            a.barh(yi, h - base, left=base, color=BLUE, height=0.6)
            tol = abs(base) * 1e-4
            for v in {round(l, 6), round(h, 6)}:
                if abs(v - base) <= tol:
                    continue
                a.text(v, yi, " " + fmt.format(v) + " ", va="center", fontsize=7.5,
                       ha="left" if v > base else "right")
            if abs(l - base) <= tol and abs(h - base) <= tol:
                a.text(base, yi, "  영향 없음", va="center", fontsize=7, color="#777")
        a.axvline(base, color="#222", lw=0.8)
        a.set_title(ttl, loc="left", fontsize=10.5); a.spines[["top", "right"]].set_visible(False)
        span = max(abs(df[lo_c] - base).max(), abs(df[hi_c] - base).max()) * 1.45 + 1e-9
        a.set_xlim(base - span, base + span)
    axs[0].set_yticks(y); axs[0].set_yticklabels(df.assumption, fontsize=8.5)
    fig.suptitle("가정값을 근거 범위 안에서 바꾸면 결과가 얼마나 흔들리나 (65°C 난방, 회색 = 낮은 값, 파랑 = 높은 값)",
                 fontsize=11, x=0.01, ha="left")
    fig.tight_layout(); fig.savefig(OUT / "18_sensitivity.png", dpi=160); plt.close(fig)
    return df, base_saving, base_op


if __name__ == "__main__":
    import warnings; warnings.simplefilter("error")
    df, b, o = run()
    print("base", round(b, 2), round(o, 1))
    print(df[["assumption", "saving_low", "saving_high", "op_low", "op_high"]].round(2).to_string(index=False))
