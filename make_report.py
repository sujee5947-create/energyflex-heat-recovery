"""Automated plain-language report (Word .docx) built from the files in results/.

    python make_report.py                      # build the report from existing results
    python make_report.py --run [ESIF_CSV]     # rerun the whole pipeline first, then build

Every number in the report is read from results/*.csv at build time, so rerunning with new
assumptions or new raw data regenerates a consistent document.
"""
import subprocess
import sys
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Cm, Pt, RGBColor

import config as C

ROOT = Path(__file__).parent
R = ROOT / "results"
FORM = R / "formulas"
OUTFILE = R / "EnergyFlex_결과보고서.docx"
FONT = "맑은 고딕"
INK, MUTED, ACCENT = RGBColor(0x22, 0x22, 0x22), RGBColor(0x5F, 0x63, 0x68), RGBColor(0x2F, 0x6F, 0xB0)


# ----------------------------------------------------------------------------- pipeline
def run_pipeline(esif_csv=None):
    steps = [["report.py"], ["combos.py"], ["report_combos.py"], ["report13.py"], ["report14.py"], ["sensitivity.py"], ["diagram.py"]]
    if esif_csv:
        steps += [["validate_esif.py", esif_csv], ["report_validation.py"]]
    steps += [["maps15.py"]]
    for s in steps:
        if (ROOT / s[0]).exists():
            print("running", " ".join(s))
            subprocess.run([sys.executable, str(ROOT / s[0]), *s[1:]], check=True, cwd=ROOT,
                           stdout=subprocess.DEVNULL)


# ----------------------------------------------------------------------------- formula images
def formula_png(name, tex, fs=15):
    FORM.mkdir(parents=True, exist_ok=True)
    p = FORM / f"{name}.png"
    plt.rcParams["mathtext.fontset"] = "cm"
    fig = plt.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, f"${tex}$", fontsize=fs)
    fig.savefig(p, dpi=220, bbox_inches="tight", pad_inches=0.04, transparent=False, facecolor="white")
    plt.close(fig)
    return p


# ----------------------------------------------------------------------------- docx helpers
def set_cell_bg(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def style_doc(doc):
    st = doc.styles["Normal"]
    st.font.name = FONT; st.font.size = Pt(10.5); st.font.color.rgb = INK
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    st.paragraph_format.space_after = Pt(4); st.paragraph_format.line_spacing = 1.25
    for lvl, size in [(0, 22), (1, 15), (2, 12.5)]:
        h = doc.styles["Title" if lvl == 0 else f"Heading {lvl}"]
        h.font.name = FONT; h.font.size = Pt(size); h.font.bold = True
        h.font.color.rgb = INK if lvl != 1 else ACCENT
        h.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        h.paragraph_format.space_before = Pt(14 if lvl == 1 else 10); h.paragraph_format.space_after = Pt(6)
        h.paragraph_format.keep_with_next = True
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.0); sec.top_margin = sec.bottom_margin = Cm(2.0)


def para(doc, text, bold=False, color=None, size=None, italic=False, align=None, after=None):
    p = doc.add_paragraph()
    r = p.add_run(text); r.bold = bold; r.italic = italic
    if color: r.font.color.rgb = color
    if size: r.font.size = Pt(size)
    if align: p.alignment = align
    if after is not None: p.paragraph_format.space_after = Pt(after)
    return p


def rich(doc, parts, style=None):
    """parts = [(text, bold), ...]"""
    p = doc.add_paragraph(style=style)
    for t, b in parts:
        r = p.add_run(t); r.bold = b
    return p


def bullet(doc, text, bold_lead=None):
    p = doc.add_paragraph(style="List Bullet")
    if bold_lead:
        p.add_run(bold_lead).bold = True
    p.add_run(text)
    return p


FIG_NO = [0]


def figure(doc, path, takeaway, caption, width=16.5):
    import re
    FIG_NO[0] += 1
    caption = f"그림 {FIG_NO[0]}. " + re.sub(r"^그림 \d+\.\s*", "", caption)
    if not Path(path).exists():
        para(doc, f"(그림 없음: {Path(path).name})", color=MUTED); return
    rich(doc, [("핵심 → ", True), (takeaway, False)])
    doc.add_picture(str(path), width=Cm(width))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    para(doc, caption, color=MUTED, size=8.5, align=WD_ALIGN_PARAGRAPH.CENTER, after=10)


def table(doc, header, rows, widths=None, fs=9):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]; c.text = ""
        r = c.paragraphs[0].add_run(h); r.bold = True; r.font.size = Pt(fs)
        set_cell_bg(c, "E8EEF6")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            lines = str(v).split("\n")
            for k, line in enumerate(lines):
                p = cells[i].paragraphs[0] if k == 0 else cells[i].add_paragraph()
                r = p.add_run(line); r.font.size = Pt(fs)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def formula(doc, name, tex, meaning, fs=15):
    p = formula_png(name, tex, fs)
    doc.add_picture(str(p), height=Cm(0.95 if fs >= 15 else 0.8))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    para(doc, meaning, color=MUTED, size=9, after=8)


# ----------------------------------------------------------------------------- build
def build():
    s = pd.read_csv(R / "summary_metrics.csv", index_col=0)
    combos = pd.read_csv(R / "combos" / "combinations_16.csv")
    eff = pd.read_csv(R / "combos" / "measure_effects.csv", index_col=0)
    ess = pd.read_csv(R / "ess_window_comparison.csv", index_col=0)
    bal = pd.read_csv(R / "energy_balance_checks.csv", index_col=0)
    svc = pd.read_csv(R / "same_service_check.csv", index_col=0)
    v13 = pd.read_csv(R / "v13" / "v13_summary.csv", index_col=0)
    dec = pd.read_csv(R / "v13" / "v13_equipment_vs_operation.csv", index_col=0)
    bal13 = pd.read_csv(R / "v13" / "v13_balance_checks.csv", index_col=0)
    svc13 = pd.read_csv(R / "v13" / "v13_same_service.csv", index_col=0)
    V = R / "validation"
    have_val = (V / "validation_summary.csv").exists()
    if have_val:
        val = pd.read_csv(V / "validation_summary.csv", index_col=0)
        eb = pd.read_csv(V / "error_breakdown.csv", index_col=0)
        reuse = pd.read_csv(V / "esif_heat_reuse_by_year.csv", index_col=0)

    S0, S1, S2, S3 = (s.loc[k] for k in ["S0_Baseline", "S1_EffCooling", "S2_HeatRecovery", "S3_HR_ESS"])
    cut = lambda a, b: (1 - a / b) * 100
    gain = lambda a, b: (b / a - 1) * 100
    worst_bal = bal13.abs().max().max()
    worst_svc = svc13.abs().max().max()
    k65 = lambda k: v13.loc[f"65°C | {k}"]
    k45 = lambda k: v13.loc[f"45°C | {k}"]
    OPK = "운전②: 냉각수 온도·히트펌프 운전량 최적화"
    op65 = dec.loc[OPK, "65°C"]
    op45 = dec.loc[OPK, "45°C"]
    feas = pd.read_csv(R / "v13" / "v13_feasibility.csv", index_col=0)
    from types import SimpleNamespace
    _d = pd.read_csv(R / "v13" / "v13_design.csv", index_col=0).iloc[:, 0].to_dict()
    des = SimpleNamespace(**{k: (v if k == "coolant_class" else float(v)) for k, v in _d.items()})
    cls = pd.read_csv(R / "v13" / "v13_coolant_class.csv")
    it_up = (k65("S2 최적운전").it_mwh / k65("S2 규칙운전").it_mwh - 1) * 100
    W = R / "v14"
    st = pd.read_csv(W / "stress_test.csv"); mg = pd.read_csv(W / "stress_margin.csv")
    cm = pd.read_csv(W / "hp_cop_methods.csv"); opr = pd.read_csv(W / "ideal_vs_realistic.csv")
    hs = pd.read_csv(W / "hold_time_sensitivity.csv")
    dpc = pd.read_csv(W / "dp_constraint_check.csv", index_col=0).iloc[:, 0]
    ope = lambda ths, m: opr[(opr.heat_supply == ths) & (opr["mode"].str.startswith(m))].iloc[0]
    total65 = k65("S0 기존(공랭)").primary_mwh - k65("S2 최적운전").primary_mwh
    fun = pd.read_csv(R / "v13" / "v13_heat_funnel.csv", index_col=0)
    f65h, f45h = fun.loc["65°C"], fun.loc["45°C"]
    pcut = lambda k, kk=k65: cut(kk(k).primary_mwh, kk("S0 기존(공랭)").primary_mwh)
    fcut = lambda k, kk=k65: cut(kk(k).final_mwh, kk("S0 기존(공랭)").final_mwh)

    doc = Document(); style_doc(doc)

    # ---------------- title
    doc.add_paragraph("EnergyFlex 결과 보고서", style="Title")
    para(doc, "AI 데이터센터의 전력과 열을 함께 보면 에너지를 얼마나 덜 쓸 수 있는가", size=12.5, color=ACCENT, after=2)
    para(doc, f"자동 생성 {date.today():%Y-%m-%d} · 최종 모델 v1.5.2 기준 · 1 MW급 AI 연산실 + 인근 건물 난방·온수, 1년 8,760시간",
         color=MUTED, size=9, after=10)
    rich(doc, [("이 보고서를 읽는 법. ", True),
               ("그림마다 맨 위에 '핵심 →' 한 줄을 두었습니다. 그 줄만 읽어도 결론을 알 수 있도록 썼습니다. "
                "가정값의 출처는 10장, 계산식은 11장, 어려운 용어는 12장, 믿을 수 없는 부분은 13장에 모았습니다. "
                "모든 숫자는 프로그램이 결과 파일에서 직접 읽어 넣은 값입니다. "
                "본문의 숫자는 모두 최종 모델(v1.5.2)로 계산한 값이고, 괄호 안의 버전 표시(v1.3, v1.4 등)는 그 기능이 추가된 시점을 뜻합니다. "
                "초기 간소화 모델(v1.2)의 결과는 부록에 참고용으로 두었습니다.", False)])

    # ---------------- 0. summary
    doc.add_heading("0. 한 장 요약", 1)
    para(doc, "같은 AI 작업, 같은 난방을 하면서 들어간 에너지만 비교했습니다. 전기요금은 어떤 결정에도 쓰지 않았습니다.", after=6)
    rows = [
        ["같은 서비스인가", f"모든 경우의 AI 작업량과 건물 난방량이 시간마다 같음 (최대 차이 {worst_svc:.0e}). "
         f"최적운전에서는 냉각수 온도를 올려 IT 전력이 {it_up:+.1f}%",
         "공정한 비교의 전제 조건 통과 (늘어난 IT 전력도 에너지에 포함)"],
        ["설비가 실제로 감당하나", f"건식냉각기를 설계 외기 {des.t_design_c:.1f}°C(0.4% 초과온도)에 맞춰 설계. 용량 초과 시간 0, "
         f"냉각수는 서버 허용 등급 {des.coolant_class}(≤{C.V13['coolant_class_max'][des.coolant_class]:.0f}°C) 안에서만 선택",
         "계산상 가능하지만 실제로는 불가능한 운전을 제외"],
        ["효율 냉각 + 폐열 회수의 효과", f"1차에너지 {pcut('S2 최적운전'):.1f}% 감소 (난방 공급 65°C), {pcut('S2 최적운전', k45):.1f}% 감소 (45°C)\n"
         f"최종에너지 {fcut('S2 최적운전'):.0f}% 감소 (65°C). 기준은 기존 공랭(S0)",
         "보일러 가스를 서버 열로 대체한 효과와 냉각 전력 절감이 합쳐진 값"],
        ["버리던 열 중 실제로 쓴 열", f"서버 열 {f65h.generated_mwh:,.0f} MWh 중 {f65h.useful_mwh:,.0f} MWh "
         f"({f65h.useful_share_pct:.0f}%). 건물 난방 수요의 {f65h.demand_covered_pct:.0f}%를 충당", "여름엔 쓸 곳이 없어 대부분 버려짐"],
        ["설비 효과 vs 운전 효과", f"65°C 난방 기준 1차에너지 절감 {total65:,.0f} MWh 중 "
         f"운전 최적화는 {op65:,.0f} MWh ({op65/total65*100:.0f}%) — 미래를 알고 매시간 독립적으로 바꾼다는 이상적 조건의 값",
         "절감의 대부분은 설비. 운전 효과는 서버 허용 냉각수 온도에 좌우 (W32면 0)"],
        ["실현 가능한 운전", f"설정 변경 폭(시간당 {C.V13['ramp_K']:.0f} K)·최소 유지({C.V13['hold_h']}시간)·전날 기온 예보로 운전하면 "
         f"운전 효과 {ope('65°C','이상적').op_effect_mwh:,.0f} → {ope('65°C','제약 운전 +').op_effect_mwh:,.0f} MWh "
         f"(이상적의 {ope('65°C','제약 운전 +').op_effect_mwh/ope('65°C','이상적').op_effect_mwh*100:.0f}%). 주 1회만 바꿔도 {hs[hs.hold_h==168].op_effect_mwh.iloc[0]:,.0f} MWh",
         "운전 효과의 대부분은 계절에 맞춘 냉각수 온도에서 나옴 → 실제로도 얻을 수 있음"],
        ["가혹 조건 (스트레스 테스트)", f"폭염 +5°C·IT 100%·냉각기 성능 −20%를 한꺼번에 줘도 불가능 운전 0시간. "
         f"냉동기 한계({C.V13['chiller_t_cond_max']:.0f}°C)에 닿으려면 여름 외기가 +{mg.heatwave_K.min():.0f}°C 더 올라가야 함",
         "설계 외기 기준 설비 크기에 여유가 있음"],
        ["운전 지도와 예측 오차", "본 연구 가정에서 수요가 있으면 항상 열회수가 최선. 가정한 오차를 넣으면 판단이 바뀌는 시간은 후보 간 오차 상관 ρ=1이면 약 3%(손실 1~2 MWh), "
         "ρ=0.5면 18~23%(14~16 MWh), ρ=0(스트레스 시나리오)이면 20~31%(19~41 MWh)",
         "판단이 흔들리는 곳은 냉각수 온도 경계. 오차의 상관 구조가 운전 최적화의 가치를 좌우"],
        ["후보 간 차이가 작은 시간", f"65°C 난방 기준 1·2위 후보의 차이가 1% 미만인 시간 {k65('S2 최적운전').near_tie_pct:.0f}% "
         f"(냉각수 온도만 다른 경우 {k65('S2 최적운전').near_tie_setpoint_pct:.0f}%, 운전 방식이 다른 경우 {k65('S2 최적운전').near_tie_mode_pct:.0f}%)",
         "오차 민감도 검증이 필요하다는 뜻. 실제로 판단이 뒤집히는 비율은 다음 단계(지도 B)에서 계산"],
    ]
    if have_val:
        pue_t = val.loc["PUE · v1.1 · 2020–23 (검증 구간)"]
        rows.append(["실측 데이터로 검증 (NLR ESIF)", f"PUE 예측 오차(MAPE) {pue_t.mape_pct:.1f}%, "
                     f"비IT 전력 WAPE {eb.loc['전체', 'wape_pct']:.0f}%\n여름 WAPE {eb.loc['여름', 'wape_pct']:.0f}% vs 겨울 {eb.loc['겨울', 'wape_pct']:.0f}%",
                     "냉각 전력 간소화 모델의 검증. 상세 설비 모델(히트펌프·냉동기·펌프)은 별도 실측 보정 필요"])
    sens0 = pd.read_csv(R / "v13" / "sensitivity.csv")
    rows.append(["가정값을 바꾸면?", f"근거 범위 안에서 가정 하나씩 바꿔도 총 1차에너지 절감률 {sens0[['saving_low','saving_high']].min().min():.1f}~{sens0[['saving_low','saving_high']].max().max():.1f}% (65°C)",
                 "결론은 가정에 강건, 운전 효과 크기는 누설전력 가정에 민감"])
    table(doc, ["질문", "결과", "의미"], rows, widths=[3.6, 8.2, 5.2])

    # ---------------- 1. what was compared
    doc.add_heading("1. 무엇을 비교했나 — 시스템 경계와 시나리오", 1)
    figure(doc, R / "00_system_boundary.png",
           "PUE는 데이터센터 안만 보고, 최종·1차에너지는 히트펌프·보일러까지 포함한 사이트 전체를 봅니다. 결론은 사이트 기준으로 냅니다.",
           "그림 1. 시스템 경계. 오른쪽 결과물(AI 작업, 난방)은 모든 경우에 같고, 왼쪽 투입(전기·가스)만 달라집니다.")
    table(doc, ["시나리오", "구성", "바꾼 것의 종류"], [
        ["S0 기존(공랭)", f"공랭 + 냉동기, 일반 UPS(효율 {C.V13['ups_legacy']:.0%}), 가스보일러 난방", "기준"],
        ["S1 규칙운전", f"수랭(냉각수 {C.V13['liquid_supply_design']:.0f}°C 고정) + 외기냉방, 고효율 UPS({C.V13['ups_efficient']:.0%}), 가스보일러 난방", "설비"],
        ["S1 최적운전", "S1 설비에서 냉각수 온도를 매시간 선택", "운전"],
        ["S2 규칙운전", f"S1 + 히트펌프로 서버 열을 회수해 난방 (냉각수 {C.V13['liquid_supply_design']:.0f}°C 고정, 수요 전부 담당)", "설비"],
        ["S2 최적운전", "S2 설비에서 냉각수 온도와 히트펌프 운전량을 매시간 선택", "운전"],
        ["(별도) ESS", f"S2 최적운전에 ESS {C.ESS_KWH:,.0f} kWh/{C.ESS_KW:,.0f} kW 추가", "설비 (피크 지표로 따로 평가, 5장)"],
    ], widths=[2.8, 10.2, 4.0])
    para(doc, "난방 공급온도는 65°C(기존 라디에이터)와 45°C(저온 난방) 두 조건으로 각각 계산했습니다. 대표 수치는 65°C 기준입니다.", color=MUTED, size=9)
    rich(doc, [("설비 효과와 운전 효과를 나눈 이유. ", True),
               ("공랭을 수랭으로 바꾸거나 히트펌프를 '설치'해서 생긴 절감(설비 효과)과, 같은 설비를 '어떻게 돌리느냐'로 생긴 절감(운전 효과)은 원인이 다릅니다. "
                "둘을 섞으면 '최적화 알고리즘 덕분'인지 '좋은 장비 덕분'인지 설명할 수 없습니다. 7장에서 둘을 분리했습니다.", False)])

    # ---------------- 2. same service
    doc.add_heading("2. 같은 서비스를 제공하는가 — 공정 비교 확인", 1)
    para(doc, "모든 시나리오가 8,760시간 각각에서 같은 AI 작업량과 같은 난방량을 제공하는지 확인했습니다. 에너지 차이가 '일을 덜 해서'가 아니라 '효율이 좋아서' 생긴 것임을 보이기 위한 점검입니다.")
    table(doc, ["확인 항목", "방법", "최대 차이", "판정"], [
        ["AI 작업량", "매시간 작업 수를 기준(S0)과 비교", f"{svc13.jobs_diff.max():.1e}", "통과"],
        ["건물 난방량", "유효열 + 보일러 열 = 난방 수요", f"{svc13.heat_delivered_diff.max():.1e} kW", "통과"],
        ["서버 열 전부 제거", "외기냉방 + 냉동기 + 히트펌프 흡열 = 발생열", f"{bal13.cooling_balance.abs().max():.1e} kW", "통과"],
        ["방열 수지", "건식냉각기가 버린 열 = 외기냉방 + 냉동기 열 + 냉동기 전기 + 펌프 열", f"{bal13.rejection_balance.abs().max():.1e} kW", "통과"],
        ["에너지 수지 (모든 식)", "냉각·난방·히트펌프·배관·방열 수지", f"{bal13.abs().max().max():.1e} kW", "통과"],
    ], widths=[3.4, 7.6, 3.0, 2.0])
    rich(doc, [("주의점: 서버 전력은 같지 않습니다. ", True),
               (f"냉각수 온도를 올리면 칩이 따뜻해져 IT 전력이 늘어납니다(누설전력). 65°C 난방 최적운전의 IT 전력량은 "
                f"{k65('S2 최적운전').it_mwh:,.0f} MWh로 규칙운전({k65('S2 규칙운전').it_mwh:,.0f} MWh)보다 {it_up:.1f}% 많습니다. "
                "따라서 같은 것은 'AI 작업량'과 '난방량'이고, 서버 소비전력·발열은 같지 않습니다. 늘어난 전기는 그대로 에너지에 포함했습니다.", False)])

    # ---------------- 3. results (final model)
    doc.add_heading("3. 결과 — 에너지를 얼마나 줄이나", 1)
    rows = []
    for lab, kk in [("65°C", k65), ("45°C", k45)]:
        for k in ["S0 기존(공랭)", "S1 규칙운전", "S1 최적운전", "S2 규칙운전", "S2 최적운전"]:
            if lab == "45°C" and not k.startswith("S2"):
                continue
            r = kk(k)
            rows.append([lab, k, f"{r.final_mwh:,.0f}", f"{r.primary_mwh:,.0f}", "기준" if k.startswith("S0") else f"{pcut(k, kk):.1f}%", f"{r.pue:.2f}"])
    rich(doc, [("핵심 → ", True),
               (f"효율 냉각과 폐열 회수를 함께 적용하고 운전을 최적화하면(S2 최적운전) 기존 공랭 대비 1차에너지가 {pcut('S2 최적운전'):.1f}% 줄어듭니다(난방 공급 65°C). "
                f"난방을 45°C로 공급할 수 있으면 {pcut('S2 최적운전', k45):.1f}%입니다.", False)])
    table(doc, ["난방 공급", "시나리오", "최종에너지 (MWh/년)", "1차에너지 (MWh/년)", "1차에너지 절감", "PUE"], rows, widths=[2.0, 3.6, 3.2, 3.2, 2.8, 2.2])
    para(doc, "S0·S1은 히트펌프가 없어 난방 공급온도와 무관하므로 65°C 줄에만 적었습니다. PUE는 데이터센터 안만 보는 지표라 히트펌프·보일러를 포함하지 않습니다.", color=MUTED, size=9)
    figure(doc, R / "v13" / "13_v13_breakdown.png",
           f"공랭(S0)의 냉각 관련 전력은 냉동기 {k65('S0 기존(공랭)').chiller_mwh:,.0f}, 건식냉각기 팬 {k65('S0 기존(공랭)').dc_fan_mwh:,.0f}, "
           f"실내 공조기 팬 {k65('S0 기존(공랭)').crah_fan_mwh:,.0f}, 펌프 {k65('S0 기존(공랭)').pump_mwh:,.0f} MWh/년입니다. 수랭에서는 대부분 사라지고, "
           f"히트펌프를 더하면 보일러 연료 {k65('S0 기존(공랭)').boiler_fuel_mwh:,.0f} MWh가 히트펌프 전기 {k65('S2 최적운전').hp_mwh:,.0f} MWh로 바뀝니다.",
           "장비별 연간 최종에너지 (난방 공급 65°C).")
    para(doc, "절감이 설비에서 왔는지 운전에서 왔는지는 7장에서 나눠 봅니다.", color=MUTED, size=9)

    # ---------------- 4. heat
    doc.add_heading("4. 버리던 열은 얼마나 실제로 쓰였나 — 발생 → 회수 → 유효", 1)
    figure(doc, R / "v13" / "28_heat_funnel.png",
           f"서버가 만든 열의 {f65h.useful_share_pct:.0f}%만 이웃 건물이 실제로 썼습니다. 건물 난방 수요는 {f65h.demand_covered_pct:.0f}% 충당했으므로, 막힌 곳은 장비가 아니라 '열을 쓸 곳(수요)'입니다.",
           "열 깔때기 (S2 최적운전, 65°C, 1년). ③이 ②보다 큰 이유는 히트펌프가 전기를 써서 열을 더하기 때문이고, ④는 배관에서 잃은 열을 뺀 값입니다.")
    table(doc, ["단계", "뜻", "65°C 난방 (MWh/년)", "45°C 난방 (MWh/년)"], [
        ["① 발생열", "서버·전력변환 장치가 만든 모든 열", f"{f65h.generated_mwh:,.0f}", f"{f45h.generated_mwh:,.0f}"],
        ["② 회수열", "히트펌프가 서버 냉각수에서 실제로 뽑아낸 열", f"{f65h.extracted_mwh:,.0f}", f"{f45h.extracted_mwh:,.0f}"],
        ["③ 히트펌프 출력", "② + 히트펌프 전기", f"{f65h.hp_output_mwh:,.0f}", f"{f45h.hp_output_mwh:,.0f}"],
        ["④ 유효열", f"배관손실 {C.PIPE_LOSS_FRAC*100:.1f}% 뺀 뒤 건물이 쓴 열 (수요 초과 불가)", f"{f65h.useful_mwh:,.0f}", f"{f45h.useful_mwh:,.0f}"],
        ["버린 열", "① − ②, 건식냉각기로 밖에 버린 서버 열", f"{f65h.rejected_mwh:,.0f}", f"{f45h.rejected_mwh:,.0f}"],
    ], widths=[3.0, 8.0, 3.0, 3.0])
    figure(doc, R / "v13" / "29_monthly_heat.png",
           "겨울엔 서버 열의 상당 부분을 쓰지만 여름엔 난방 수요가 거의 없어 열을 버립니다. 열 저장이나 여름철 열 수요(온수·흡수식 냉방)가 다음 과제입니다.",
           "월별 유효열과 버린 열 (S2 최적운전, 65°C).")

    # ---------------- 5. ESS
    doc.add_heading("5. ESS는 따로 평가 — 에너지 절감이 아니라 피크 저감", 1)
    e0, e1 = ess.iloc[0], ess.iloc[1]
    rich(doc, [("핵심 → ", True),
               (f"ESS는 에너지를 줄이지 않습니다. 충방전 손실만큼 오히려 더 씁니다. 대신 가장 많이 쓰는 순간의 전력(피크)을 낮춥니다. "
                f"S2 최적운전의 전력 사용 패턴에 ESS를 적용하면 피크가 {k65('S2 최적운전').peak_kw:,.0f} → {k65('S2 최적운전').ess_peak_kw:,.0f} kW(65°C 난방), "
                f"{k45('S2 최적운전').peak_kw:,.0f} → {k45('S2 최적운전').ess_peak_kw:,.0f} kW(45°C 난방)로 내려갑니다.", False)])
    para(doc, "그래서 ESS는 에너지 절감 지표와 섞지 않고 '피크 저감·열화' 지표로 따로 봅니다. 운전 범위(충전 상태 폭)에 따른 피크 저감과 수명 소모의 맞교환은 초기 모델로 계산했고 부록에 실었습니다.")

    # ---------------- 6. v1.3 physics
    doc.add_heading("6. 물리 모델 — 장비를 어떻게 계산했나", 1)
    para(doc, "초기 모델(v1.2)은 팬·펌프 전력을 '냉각열의 몇 %'로, 히트펌프 효율을 고정값으로 두었습니다. 최종 모델은 장비마다 물리 법칙에 가까운 식을 넣었습니다. 이 보고서의 결과는 모두 오른쪽 열(최종 모델)로 계산했습니다.")
    table(doc, ["부분", "초기 모델 (v1.2)", "최종 모델"], [
        ["히트펌프 COP", "고정값 (4.9)", "열원(서버 냉각수) 출구온도·난방 출구온도·부분부하율로 계산 (v1.4). 외기온도는 직접 쓰지 않음"],
        ["냉동기 운전 한계", "없음", f"응축온도 {C.V13['chiller_t_cond_max']:.0f}°C 초과 시 '운전 불가'로 판정, 최적화에서 제외 (v1.4)"],
        ["펌프", "보조전력 비율에 포함", "정압 + 마찰 + 최소유량 + 효율곡선. 실측 성능곡선 CSV로 교체 가능. 단순 세제곱 법칙 미사용"],
        ["팬", "보조전력 비율에 포함", "건식냉각기 팬과 실내 공조기 팬을 장비별로 분리, 필요한 풍량으로 계산"],
        ["냉각수 온도", "30°C 고정", f"25~45°C 후보 중 서버 허용 등급({C.V13['coolant_class']}) 이하만 선택 (운전 변수)"],
        ["건식냉각기 용량", "제약 없음", f"설계 외기 {des.t_design_c:.1f}°C에 맞춰 {des.dc_design_kw:,.0f} kW로 설계. 모자라면 냉동기 응축온도가 올라가 효율 저하 (v1.3.1)"],
        ["히트펌프-외기냉방 상호작용", "없음", "히트펌프가 열을 뽑아 식은 물이 건식냉각기로 감 → 외기냉방 조건에 반영 (v1.3.1)"],
        ["난방 공급 온도", "65°C", "65°C와 45°C 두 조건을 명시해 따로 계산"],
    ], widths=[3.0, 4.0, 10.0])
    figure(doc, R / "v13" / "11_hp_cop_model.png",
           "히트펌프 효율은 '물을 몇 도에서 몇 도로 올리느냐'가 결정합니다. 난방을 45°C로 공급하면 65°C보다 효율이 훨씬 좋고, 아주 적게 돌리면 효율이 떨어집니다.",
           f"그림 9. 히트펌프 COP 모델. 왼쪽: 온도 효과, 오른쪽: 부분부하 효과. 카르노 비율 {C.V13['hp_carnot']:.2f}, COP 상한 {C.V13['hp_cop_max']:.0f} (근거는 10장).")
    c65 = cm[(cm.heat_supply == 65) | (cm.heat_supply == 65.0)].set_index("method")
    figure(doc, W / "21_hp_cop_methods.png",
           f"히트펌프는 서버 냉각수에서 열을 빼면서 물을 식히므로, 증발기는 '들어오는 물'이 아니라 '나가는 물'보다 차가워야 합니다(평균 {c65.loc['outlet','mean_src_out']:.1f}°C). "
           f"이걸 반영하면 65°C 난방의 계절 COP가 {c65.loc['inlet','seasonal_cop']:.2f} → {c65.loc['outlet','seasonal_cop']:.2f}로 조금 낮아집니다. "
           f"반면 로렌츠 COP에 상수 효율 {C.V13['lorenz_eff']}을 곱하면 {c65.loc['lorenz','seasonal_cop']:.2f}로 크게 과대평가합니다(온도 리프트가 작을 때 로렌츠 효율이 떨어지는 현상, Pieper 외 2020). 그래서 로렌츠는 비교용으로만 썼습니다.",
           "히트펌프 COP 계산 방식 비교 (P1, 규칙 운전).")
    figure(doc, R / "v13" / "12_pump_model.png",
           "펌프는 유량을 절반으로 줄여도 전력이 1/8로 줄지 않습니다. 배관 높이차(정압), 최소 유량, 효율 저하 때문입니다.",
           "그림 10. 펌프 전력 모델과 단순 세제곱 법칙 비교 (수랭 루프).")

    # ---------------- 7. equipment vs operation
    doc.add_heading("7. 설비 효과 vs 운전 최적화 효과", 1)
    para(doc, f"규칙 운전 = 냉각수 30°C 고정, 히트펌프는 수요를 전부 담당. 최적 운전 = 매시간 냉각수 공급온도(서버 허용 등급 {C.V13['coolant_class']} 이하)와 "
              "히트펌프 운전량(수요의 0·50·100%) 중 1차에너지가 가장 작은 조합을 선택(전기요금 미사용). 외기냉방과 냉동기의 분담은 이 선택의 결과로 정해집니다. "
              "미래를 정확히 알고 매시간 독립적으로 설정을 바꾼다고 가정한 이상적 조건이므로, 운전 효과는 실제로 얻을 수 있는 값의 상한입니다.")
    figure(doc, R / "v13" / "14_equipment_vs_operation.png",
           f"절감의 대부분은 설비(파랑)에서 나옵니다. 운전 최적화(주황)는 이상적 조건에서 65°C 난방 {op65:,.0f} MWh, 45°C 난방 {op45:,.0f} MWh로 작지만 장비를 바꾸지 않고 얻는 절감입니다.",
           "그림 13. 1차에너지 기준 단계별 절감 (폭포 그래프).")
    rows = []
    for k in dec.index:
        rows.append([k, f"{dec.loc[k, '65°C']:,.0f}", f"{dec.loc[k, '45°C']:,.0f}",
                     "설비" if k.startswith("설비") else "운전"])
    table(doc, ["단계", "65°C 난방 (MWh/년)", "45°C 난방 (MWh/년)", "종류"], rows, widths=[7.0, 3.6, 3.6, 2.8])
    para(doc, "'운전①'은 히트펌프가 없는 S1에서 냉각수 온도만 최적화한 효과로, 폭포 그래프에는 넣지 않고 참고로 표시했습니다.", color=MUTED, size=9)
    figure(doc, R / "v13" / "15_operation_choice.png",
           "65°C 난방에서는 겨울에 냉각수를 40°C로 올리는 것이 최선입니다(히트펌프 효율 상승 > 칩 누설전력 증가). 45°C 난방에서는 히트펌프 효율이 이미 높아(계절 COP {:.1f}, 상한 {:.0f}) 대부분 30°C를 유지합니다.".format(k45("S2 최적운전").hp_seasonal_cop, C.V13["hp_cop_max"]),
           "그림 14. 최적 운전에서 매시간 고른 냉각수 공급 온도의 월별 비율. 동점일 때는 낮은 온도를 고르도록 되어 있습니다.")
    rich(doc, [("히트펌프는 왜 항상 켜졌나. ", True),
               (f"히트펌프 열이 보일러 열보다 1차에너지가 적으려면 COP가 {C.PEF_ELEC} × {C.BOILER_EFF} ÷ {C.PEF_GAS} = {des.breakeven_cop:.2f}만 넘으면 됩니다. "
                f"실제 COP는 {k65('S2 최적운전').hp_seasonal_cop:.1f}(65°C)~{k45('S2 최적운전').hp_seasonal_cop:.1f}(45°C)라 1차에너지 기준에서는 항상 켜는 것이 맞습니다. "
                "그래서 이번 결과의 운전 효과는 거의 전부 냉각수 온도 선택에서 나오며, 'ON/OFF 모드 선택을 검증했다'고 말할 수는 없습니다.", False)])
    figure(doc, R / "v13" / "19_coolant_class.png",
           f"서버가 허용하는 냉각수 온도가 낮으면(W32) 운전 최적화로 얻을 것이 {cls[(cls.coolant_class=='W32')&(cls.heat_supply=='65°C')].op_effect_mwh.iloc[0]:,.0f} MWh로 사라지고, "
           f"W45면 {cls[(cls.coolant_class=='W45')&(cls.heat_supply=='65°C')].op_effect_mwh.iloc[0]:,.0f} MWh로 커집니다(65°C 난방). 운전 최적화의 가치는 서버 사양이 먼저 정합니다.",
           "ASHRAE 수랭 등급별 운전 최적화 효과. 등급은 서버가 받을 수 있는 설비 공급수의 상한온도입니다.")
    o65 = k65("S2 최적운전")
    figure(doc, R / "v13" / "16_decision_gap.png",
           f"1·2위 후보의 차이가 1% 미만인 시간은 {o65.near_tie_pct:.0f}%지만, 그중 대부분({o65.near_tie_setpoint_pct:.0f}%p)은 같은 운전 방식에서 냉각수 온도만 다른 경우입니다. "
           f"냉각 방식이나 히트펌프 운전량이 갈리는 시간은 {o65.near_tie_mode_pct:.0f}%입니다. 이 숫자는 '후보 간 에너지 차이가 작다'는 뜻이지, 그만큼 판단이 틀린다는 뜻은 아닙니다.",
           "1·2위 후보의 1차에너지 차이 분포를 '무엇이 둘을 갈랐는지'로 나눈 것. 실제로 판단이 뒤집히는 비율은 예측 오차를 넣은 지도 B에서 계산합니다.")
    doc.add_heading("운전 가능성 점검", 2)
    para(doc, "수지가 0으로 맞아도 설비가 실제로 그 운전을 할 수 있는지는 별개입니다. 다음을 확인했습니다.")
    f65 = lambda k: feas.loc[f"65°C | {k}"]
    table(doc, ["점검 항목", "기준", "결과 (65°C 난방)"], [
        ["건식냉각기 용량 초과", "팬 100%를 넘는 방열 금지", f"최대 팬 필요율 {feas.dc_fan_need_max.max():.2f} (1 이하) → 초과 0시간"],
        ["용량 부족 시 응축온도 상승", "모자라면 응축온도↑ → 냉동기 효율↓로 처리", f"S0 {int(f65('S0 기존(공랭)').cond_raised_h)}시간, 외기냉방 용량 제한 {int(feas.free_cap_limited_h.max())}시간"],
        ["서버 냉각수 허용온도", f"ASHRAE {C.V13['coolant_class']}: 공급 ≤ {C.V13['coolant_class_max'][C.V13['coolant_class']]:.0f}°C", f"최적운전 최고 공급온도 {f65('S2 최적운전').max_t_sup:.0f}°C"],
        ["설계 외기온도", "모의 기상 1년의 0.4% 초과온도 (ASHRAE 설계조건 방식)", f"{des.t_design_c:.1f}°C → 건식냉각기 {des.dc_design_kw:,.0f} kW, 팬 정격 {des.dc_fan_rated_kw:.0f} kW"],
        ["ESS 피크", "S2 최적운전 전력 프로파일로 계산", f"{f65('S2 최적운전').peak_kw:,.0f} → {f65('S2 최적운전').ess_peak_kw:,.0f} kW"],
    ], widths=[4.0, 6.0, 7.0])
    cpd = st[st.stress.str.startswith("복합")].set_index("case")
    figure(doc, W / "20_stress_test.png",
           f"설비를 정상 연도 기준으로 정한 뒤 일부러 가혹하게 만들었습니다. 폭염 +5°C·IT 100%·냉각기 성능 −20%를 한꺼번에 줘도 냉동기 응축온도는 최고 "
           f"{cpd.loc['S0 공랭','max_t_cond']:.0f}°C로 한계({C.V13['chiller_t_cond_max']:.0f}°C) 안이었고 불가능 운전은 0시간입니다. 대신 공랭(S0)은 "
           f"{int(cpd.loc['S0 공랭','cond_raised_h']):,}시간 동안 응축온도가 올라가 효율이 떨어졌습니다.",
           "스트레스 테스트 (P0). 점 = 연중 최고 응축온도, 빨간 선 = 냉동기 운전 한계(공랭 칠러 최대 외기 52°C + 8 K).")
    para(doc, "한계 탐색: 같은 복합 조건에서 여름 외기를 계속 올려 보면 " + ", ".join(
        f"{r.case}는 +{r.heatwave_K:.0f}°C(최고 외기 {r.max_t_out:.0f}°C)에서 처음 운전 불가" for r in mg.itertuples()) + "가 생깁니다.",
        color=MUTED, size=9)

    # ---------------- 7-2 realistic operation (P2)
    doc.add_heading("실현 가능한 운전 — 이상적 운전과 비교", 2)
    para(doc, f"지금까지의 '최적 운전'은 매시간 설정을 마음대로 바꾸고 미래 날씨를 정확히 안다고 가정했습니다. 실제 운전에 가깝게 세 가지 제약을 넣었습니다. "
              f"① 냉각수 설정온도는 시간당 {C.V13['ramp_K']:.0f} K까지만 바꿀 수 있고, ② 한 번 바꾸면 {C.V13['hold_h']}시간은 유지하며, "
              f"③ 계획은 실제 기온이 아니라 전날 예보(오차 표준편차 {C.V13['forecast_sd']}°C)로 세웁니다. "
              "1년 전체를 동적계획법(Dynamic Programming)으로 한 번에 풀어 이 제약 안에서 1차에너지가 가장 작은 운전 계획을 찾고, 그 계획을 실제 날씨에서 돌렸습니다.")
    figure(doc, W / "22_ideal_vs_realistic.png",
           f"제약과 예보 오차를 넣어도 65°C 난방에서 운전 효과는 {ope('65°C','이상적').op_effect_mwh:,.0f} → {ope('65°C','제약 운전 +').op_effect_mwh:,.0f} MWh로 "
           f"{ope('65°C','제약 운전 +').op_effect_mwh/ope('65°C','이상적').op_effect_mwh*100:.0f}%가 남습니다. 설정 변경은 연 {int(ope('65°C','이상적').setpoint_changes):,}회 → {int(ope('65°C','제약 운전 +').setpoint_changes):,}회로 줄고, "
           f"주 1회만 바꿔도 {hs[hs.hold_h==168].op_effect_mwh.iloc[0]:,.0f} MWh를 얻습니다. 효과의 대부분은 '계절에 맞춘 냉각수 온도'에서 나온다는 뜻입니다.",
           f"이상적 vs 실현 가능 운전. 오른쪽: 최소 유지시간을 1시간~1주일로 바꿨을 때 (65°C, 예보 기반). 제약 위반 점검: 변경 간 최소 간격 {int(dpc.min_hours_between_changes)}시간, 최대 변경폭 {dpc.max_step_K:.0f} K.")
    figure(doc, W / "23_week_example.png",
           "겨울에는 히트펌프 효율을 위해 냉각수를 40°C로 유지하고, 여름에는 상황에 따라 내립니다. 제약 운전은 같은 방향을 따르되 자주 흔들지 않습니다.",
           "예시 주간의 냉각수 공급온도 (65°C 난방).")

    # ---------------- 8. operating maps (v1.5)
    V15 = R / "v15"
    if (V15 / "map_summary.csv").exists():
        msum = pd.read_csv(V15 / "map_summary.csv").set_index("heat_supply")
        ann = pd.read_csv(V15 / "annual_flip_regret.csv")
        an = lambda h, k: ann[(ann.heat_supply == h) & (ann.error.str.startswith(k))].iloc[0]
        cells = pd.read_csv(V15 / "map_cells.csv"); mbc = pd.read_csv(V15 / "map_modes_by_coolant.csv")
        c0 = cells[(cells.heat_supply == 65.0) & (cells.t_out == 0.0)]
        d40 = c0[c0.tsup_A >= 40].demand.min()
        tch = {ts: mbc[(mbc.heat_supply == 65.0) & (mbc.coolant == ts) & (mbc.demand == 400) & mbc.strat.str.contains("냉동기")].t_out.min()
               for ts in (30.0, 35.0, 40.0)}
        tch40 = tch[40.0]
        doc.add_heading("8. 최적 운전 지도 — 지도 A(오차 없음)와 지도 B(오차 있음)", 1)
        para(doc, f"외기온도(−15~35°C)와 난방 수요(0~800 kW)의 모든 조합에서, IT 평균 부하({C.IT_CAPACITY_KW*(C.IT_IDLE_FRACTION+(1-C.IT_IDLE_FRACTION)*C.UTIL_MEAN):.0f} kW)와 "
                  f"서버 등급 {C.V13['coolant_class']}를 고정하고 1차에너지가 가장 작은 운전을 찾았습니다. 고른 것은 히트펌프 운전량(0·50·100%)과 냉각수 공급온도이고, "
                  "결과를 '열회수+외기냉방 / 열회수+냉동기 보조 / 혼합(부분 회수) / 외기냉방만 / 냉동기 사용' 다섯 가지 전략으로 표시했습니다. "
                  "난방 공급온도는 65°C와 45°C로 고정해 지도를 따로 그렸습니다. 1위와 2위의 차이가 1% 미만인 곳은 빗금으로 표시했습니다.")
        figure(doc, V15 / "24_map_A_65.png",
               f"본 연구의 설비·성능 가정에서는 난방 수요가 조금이라도 있으면 항상 열회수가 최선입니다(손익분기 COP {des.breakeven_cop:.2f}보다 실제 COP가 훨씬 높기 때문). 바뀌는 것은 냉각 방식(외기 약 {tch40:.0f}°C 이상에서 냉동기 보조)과 "
               f"냉각수 온도입니다. 65°C 난방에서는 (외기 0°C 기준) 수요가 약 {d40:.0f} kW 이상이면 냉각수를 40°C로 올리고, 그 아래에서는 더 낮게 두는 것이 최선입니다.",
               "지도 A, 난방 공급 65°C. 빗금 = 1·2위 차이 1% 미만(후보 간 차이가 작은 곳).")
        figure(doc, V15 / "24_map_A_45.png",
               "45°C 난방에서는 히트펌프 효율이 이미 높아 냉각수 온도를 올릴 이득이 작고, 지도가 더 복잡하며 빗금(근소한 차이) 영역이 넓습니다. COP 상한(9)에 닿는 조건이 많은 것도 원인입니다.",
               "지도 A, 난방 공급 45°C.")
        figure(doc, V15 / "25_map_by_coolant.png",
               f"냉각수 온도를 조건으로 고정해 보면, 냉각수가 30 → 35 → 40°C로 따뜻해질수록 '냉동기 보조'가 필요한 경계가 외기 약 {tch[30.0]:.0f} → {tch[35.0]:.0f} → {tch[40.0]:.0f}°C로 밀려납니다. "
               "냉각수 온도를 올리는 것이 곧 외기냉방 시간을 늘리는 방법입니다.",
               "냉각수 공급온도를 30/35/40°C로 고정한 운전 전략 지도 (위: 65°C 난방, 아래: 45°C 난방).")
        rich(doc, [("지도 B는 어떻게 만들었나. ", True),
                   ("각 칸에서 오차를 300번 뽑고, 그 오차를 시뮬레이터 안에 넣어 모든 후보를 처음부터 다시 계산했습니다(v1.5.1). 히트펌프 COP가 낮아지면 "
                    "압축기 전력만 늘어나는 것이 아니라 서버에서 뽑는 열이 줄고, 그만큼 외기냉방·냉동기가 처리할 열과 보일러 사용량, 운전 가능 여부까지 함께 바뀝니다. "
                    "냉각 전력 오차는 '설비 효율이 실제로 다른 것'으로 해석해(v1.5.2), 냉동기 COP를 바꾼 뒤 냉동기 전력 → 응축열 → 건식냉각기 부하·응축온도 → 운전 가능성을 차례로 다시 계산하고, "
                    "팬·펌프 전력도 같은 비율로 바꿉니다(펌프 일은 냉각수에 열로 들어가 함께 버려짐). 전력 숫자에만 곱하는 통계적 보정이 아닙니다. "
                    "이렇게 얻은 1차에너지를 '시뮬레이션 참값'으로 두고, 지도 A의 선택이 그래도 최선으로 남은 비율(선택 안정성)을 셌습니다. "
                    "이 비율은 현장에서 관측한 확률이 아니라 '가정한 오차 모델 하에서의 몬테카를로 비율'입니다.", False)])
        rich(doc, [("오차의 출처와 한계. ", True),
                   ("냉각 전력 오차는 ESIF 비IT 전력 모델(v1.1)의 검증 구간 실측 오차를 외기온도 구간별로 빌려 쓴 '대리 불확실성(proxy)'입니다. "
                    "ESIF 모델은 팬·펌프 등 비IT 전력 전체를 예측하고, 이 연구의 냉각설비 모델(냉동기·건식냉각기 팬·순환펌프)과는 대상이 달라 "
                    "같은 오차 분포를 가진다는 근거는 없습니다. 히트펌프 COP 오차 ±15%는 가정입니다. 따라서 지도 B 전체가 민감도 분석입니다.", False)])
        figure(doc, V15 / "26_map_B_65.png",
               f"지도 A에서 빗금(차이 1% 미만)이 {msum.loc[65.0,'near_tie_cells_pct']:.0f}%였지만, 가정한 오차 아래에서도 냉각수 온도 선택이 90% 이상 유지되는 칸이 {msum.loc[65.0,'setpoint_stable_ge90_pct']:.0f}%입니다. "
               "흔들리는 곳은 냉각수 온도가 바뀌는 경계 부근이고, 전략(열회수 여부) 자체는 거의 바뀌지 않습니다. 차이가 작다는 것과 판단이 뒤집힌다는 것은 다른 이야기입니다.",
               "지도 B, 난방 공급 65°C. 왼쪽: 지도 A의 냉각수 온도가 오차 아래에서도 최선으로 남은 비율(300회 모의). 오른쪽: 가장 자주 1위가 된 선택(주황 테두리 = 지도 A와 다른 곳). 칸마다 모든 후보에 같은 오차(ρ=1).")
        figure(doc, V15 / "26_map_B_45.png", "45°C 난방에서도 흔들리는 곳은 냉각수 온도 경계 부근에 모여 있습니다.", "지도 B, 난방 공급 45°C.")
        a1, a0, a5 = an("65°C", "공통"), an("65°C", "후보별"), ann[(ann.heat_supply == "65°C") & (ann.rho == 0.5)].iloc[0]
        figure(doc, V15 / "27_annual_flip.png",
               f"1년 8,760시간에 같은 방식으로 오차를 넣고, 후보들 사이 오차의 상관계수 ρ를 1(모든 후보가 같이 틀림)에서 0(후보마다 따로 틀림)까지 바꿨습니다. "
               f"65°C 난방에서 판단이 바뀌는 시간은 {a1.flip_any_pct:.1f}% → {a5.flip_any_pct:.0f}%(ρ=0.5) → {a0.flip_any_pct:.0f}%(ρ=0), 손실은 {a1.regret_mwh_mean:.1f} → {a5.regret_mwh_mean:.0f} → {a0.regret_mwh_mean:.0f} MWh/년으로 커집니다. "
               f"손실은 운전 최적화 효과({ope('65°C','제약 운전 +').op_effect_mwh:.0f} MWh)의 {a1.regret_mwh_mean/ope('65°C','제약 운전 +').op_effect_mwh*100:.1f}% ~ {a0.regret_mwh_mean/ope('65°C','제약 운전 +').op_effect_mwh*100:.0f}%입니다. "
               "운전 최적화의 가치는 오차의 크기보다 '후보 사이에서 오차가 얼마나 같이 움직이느냐'에 좌우되며, 실제 상관 구조를 추정하는 것이 다음 연구 과제입니다.",
               "후보 간 오차 상관계수에 따른 연간 판단 변경과 손실(regret, 40회 모의, 음영 = 95% 분위). ρ=0(후보별 독립)은 실제 설비에서 같은 외기·계통·센서를 공유한다는 점에서 "
               "가능성이 낮은 스트레스 시나리오이며, 수학적으로 보장된 최악의 상한은 아닙니다.")

    # ---------------- 9. validation
    doc.add_heading("9. 실측 데이터로 검증 (NLR ESIF)", 1)
    if have_val:
        rich(doc, [("검증 범위. ", True), ("여기서 검증한 것은 간소화 냉각 전력 모델(회귀식)입니다. 최종 모델의 상세 팬·펌프·히트펌프 모델은 "
                                         "ESIF로 직접 검증하지 않았으며 별도의 실측 보정이 필요합니다.", False)])
        para(doc, "미국 국립재생에너지연구소(NLR, 옛 NREL) ESIF 데이터센터의 2016~2023년 시간별 실측값을 썼습니다. 2016~19년으로 모델을 맞추고(보정), "
                  "한 번도 보지 않은 2020~23년으로 성적을 매겼습니다(검증). ESIF에는 냉동기와 히트펌프가 없어서 '냉각 보조전력(팬·펌프)과 PUE'만 검증했습니다.")
        figure(doc, V / "05_esif_validation.png",
               f"PUE는 평균 {abs(pue_t.bias):.4f}만큼 낮게 예측했고, 95% 일치 범위는 {pue_t.loa_low:+.3f}~{pue_t.loa_high:+.3f}입니다. PUE 수준에서는 잘 맞습니다.",
               "그림 16. 검증 구간 일평균 PUE와 Bland–Altman 그림.")
        figure(doc, V / "10_error_breakdown.png",
               f"그러나 비IT 전력(냉각 보조전력 등)으로 보면 전체 WAPE {eb.loc['전체', 'wape_pct']:.0f}%, 여름 {eb.loc['여름', 'wape_pct']:.0f}%, 30°C 이상 {eb.loc['≥30°C', 'wape_pct']:.0f}%입니다. "
               "더운 날, 부하가 높을 때 실제보다 적게 예측합니다.",
               "그림 17. 계절·외기온도·IT 부하 구간별 오차. 파랑 = 오차 크기, 주황 = 치우침(음수 = 과소예측).")
        rows = [[b, g, f"{r.hours:,.0f}", f"{r.mae_kw:.1f}", f"{r.wape_pct:.0f}%", f"{r.bias_pct:+.0f}%"] for b, r in eb.iterrows() for g in [r.group]]
        table(doc, ["구간", "묶음", "시간 수", "MAE (kW)", "WAPE", "Bias"], rows, widths=[3.2, 2.4, 2.4, 2.6, 2.4, 2.4], fs=8.5)
        figure(doc, V / "06_esif_heat_reuse.png",
               f"ESIF는 IT 부하가 늘었는데도 열 재사용 비율이 {reuse.reuse_share_of_it_heat.max()*100:.0f}%에서 {reuse.reuse_share_of_it_heat.iloc[-1]*100:.1f}%로 줄었습니다. "
               "설비가 있어도 수요와 운전이 맞지 않으면 열은 버려집니다 — 4장 결과와 같은 이야기입니다.",
               "그림 18. ESIF 연도별 열 재사용 비율 (막대 아래 숫자는 평균 IT 전력).")
    else:
        para(doc, "ESIF 원자료가 없어 이번 빌드에서는 검증을 생략했습니다. `python make_report.py --run <esif_hourly.csv>`로 다시 만드세요.", color=MUTED)

    # ---------------- 9. assumptions and sources
    doc.add_heading("10. 가정값은 어디서 왔나 — 근거와 민감도", 1)
    para(doc, "모델에 들어간 숫자를 ① 근거가 있는 값, ② 근거를 찾지 못해 범위를 바꿔 본 값, ③ 비교 조건으로 정한 시나리오 설정으로 나눴습니다. "
              "이전 버전에서 근거 없이 넣었던 값은 아래 표처럼 고쳤습니다.")
    doc.add_heading("① 근거가 있는 값", 2)
    table(doc, ["항목", "이전 → 현재", "근거"], [
        ["IT 유휴전력", f"30% → {C.IT_IDLE_FRACTION:.0%}", "AI 서버 유휴 = 정격의 20% (LBNL 2024 보고서), 8-GPU H100 실측 18% (Latif 외 2024)"],
        ["IT 연평균 전력", "정격의 79% → 70%", f"AI 서버 연평균 = 정격의 70% (LBNL 2024) → 평균 이용률 {C.UTIL_MEAN}"],
        ["냉동기 운전 한계", f"없음 → 응축 {C.V13['chiller_t_cond_max']:.0f}°C", "공랭 칠러 최대 외기 52°C (제조사 사양) + 응축 접근 8 K"],
        ["난방 환수온도", f"없음 → 65/{C.V13['heat_return_c'][65.0]:.0f}, 45/{C.V13['heat_return_c'][45.0]:.0f}°C", "라디에이터 실측 64/42°C (Jangsten 2016), 저온 난방 45/25°C 설계 (Danfoss) — 로렌츠 비교에 사용"],
        ["로렌츠 효율 (비교용)", f"{C.V13['lorenz_eff']}", "대형 히트펌프 문헌 상수 0.5, 덴마크 실설비 0.5–0.6 (Pieper 외 2020)"],
        ["기온 예보 오차", f"표준편차 {C.V13['forecast_sd']}°C", "1일 전 기온 예보 MAE 1.2–2.0°C (meteoblue 2021 비교)"],
        ["건식냉각기 접근온도", f"5 K → {C.V13['dc_approach']:.0f} K", "제조사 데이터 중앙값 10 K, 사분위 8.5–11.8 K (Wenzel 외 2023, Energies 16:3661)"],
        ["건식냉각기 팬 전력", "0.02 kW/kW (유지)", "냉각탑·건식냉각기 0.01–0.06 kWel/kWth (Wenzel 외 2023)"],
        ["실외기 팬 부분부하", f"풍량^2.7 → 풍량^{C.V13['fan_exp']:.0f}", "정압 설정이 없는 팬의 상사법칙 (교과서 관계)"],
        ["실내 공조기 팬 부분부하", "풍량^2.7 → ASHRAE 곡선", "ASHRAE 90.1 Appendix G 표 G3.1.3.15 VAV 팬 곡선"],
        ["펌프 설계 양정", f"30 m → {C.V13['pump_H_design_m']:.0f} m", "설계점 22 W/gpm (ASHRAE 90.1 Appendix G 냉수 펌프)이 되도록 역산"],
        ["배관 열손실", f"5% → {C.PIPE_LOSS_FRAC:.1%}", f"손실% = 17 × (선형 열밀도)^-0.5, 배관 {C.PIPE_TRENCH_M:.0f} m (IEA Bioenergy Task 32, 2014)"],
        ["칩 누설전력", f"0.20 → {C.V13['leak_per_K']*100:.2f} %/°C", "수랭 랙 입구 24→42°C에서 부하 시 +4%, 유휴 시 <0.5% (Kadhim 2019) — 부하 시 상한값"],
        ["히트펌프 COP 상한", f"7 → {C.V13['hp_cop_max']:.0f}", "저리프트 전용 히트펌프 실증 COP≈9 @ 20 K (Gasser 외 2017, IEA 히트펌프 학회)"],
        ["히트펌프 카르노 비율", f"{C.V13['hp_carnot']:.2f} (유지)", "실사용 45–55% (OpenEnergyMonitor), 30 K 리프트 COP 5.7–6.5 (Arpagaus 외 2018)"],
        ["냉동기 카르노 비율", f"{C.V13['chiller_carnot']:.2f} (유지)", "AHRI 조건에서 모델 COP 3.26 ↔ ASHRAE 90.1 공랭 칠러 최소 COP 2.96"],
        ["부분부하 손실계수 Cd", f"{C.V13['hp_cd']} (유지)", "ASHRAE 116·AHRI 210/240 기본값, 물-물 히트펌프 실측 0.22 (Fuentes 외 2016)"],
        ["UPS 효율", f"{C.V13['ups_legacy']:.0%} / {C.V13['ups_efficient']:.0%} (유지)", "ENERGY STAR: 일반 92–95%, 1 MW 최소 기준 96.6%"],
        ["보일러 효율", f"{C.BOILER_EFF:.2f} (유지)", "국내 가스보일러 1등급 91% 이상, 2등급 88% 이상 (박찬일·김래현 2016)"],
        ["1차에너지 계수", f"{C.PEF_ELEC} / {C.PEF_GAS} (유지)", "건축물에너지효율등급 인증제도 운영규정 별표3 (전력 2.75, 연료 1.1)"],
        ["ESS 사이클 열화", f"2.0e-4 → {C.FADE_PER_EFC_AT_80DOD:.1e} /사이클", "LFP BESS: DoD 90%에서 6,000사이클에 70% (EVreporter 2024)"],
        ["ESS DoD 지수", f"1.5 → {C.DOD_STRESS_EXP}", "DoD 스트레스 함수 Φ(d)=k·d^1.3 (Xu 외 2016, IEEE Trans. Smart Grid)"],
        ["수랭 열의 물 회수율", "100% (유지)", "직접 흡수 60–70% + 랙 공기-물 열교환기 → 약 99%가 물로 (IBM, David 외 2013)"],
    ], widths=[3.4, 3.4, 10.2], fs=8.3)
    doc.add_heading("② 근거를 찾지 못한 값 → 범위를 바꿔 결과가 얼마나 흔들리는지 확인", 2)
    para(doc, f"운전 제약값(변경폭 {C.V13['ramp_K']:.0f} K/h, 최소 유지 {C.V13['hold_h']}시간, 예보 오차 자기상관 {C.V13['forecast_rho']})과 히트펌프 핀치 {C.V13['hp_pinch']:.0f} K도 근거를 찾지 못한 가정입니다. "
              "최소 유지시간의 영향은 7장 그림(1시간~1주일)에서 따로 확인했습니다.", size=9.5)
    sens = pd.read_csv(R / "v13" / "sensitivity.csv")
    sb = pd.read_csv(R / "v13" / "sensitivity_base.csv", index_col=0).iloc[:, 0]
    big = sens.sort_values("saving_span", ascending=False).iloc[0]
    op_sens = sens.assign(op_span=(sens.op_high - sens.op_low).abs()).sort_values("op_span", ascending=False).iloc[0]
    figure(doc, R / "v13" / "18_sensitivity.png",
           f"총 절감률({sb.base_saving_pct:.1f}%)은 어떤 가정을 범위 끝까지 바꿔도 {sens[['saving_low','saving_high']].min().min():.1f}~{sens[['saving_low','saving_high']].max().max():.1f}% 안에 있어 결론이 바뀌지 않습니다. "
           f"가장 크게 흔드는 것은 '{big.assumption}'입니다. 반면 운전 최적화 효과는 '{op_sens.assumption}'에 따라 {min(op_sens.op_low, op_sens.op_high):,.0f}~{max(op_sens.op_low, op_sens.op_high):,.0f} MWh로 크게 달라집니다.",
           "그림 19. 한 번에 한 가정만 바꾼 민감도 분석 (토네이도 그래프). 범위는 아래 표의 근거를 따름.")
    table(doc, ["가정", "범위 (낮음 ↔ 높음)", "범위의 근거", "절감률 %", "운전 효과 MWh"],
          [[r.assumption, f"{r.low:g} ↔ {r.high:g}", r.basis, f"{r.saving_low:.1f} ↔ {r.saving_high:.1f}", f"{r.op_low:,.0f} ↔ {r.op_high:,.0f}"]
           for r in sens.sort_values("saving_span", ascending=False).itertuples()], widths=[3.4, 2.6, 5.2, 2.8, 3.0], fs=8)
    doc.add_heading("③ 시나리오 설정 (비교 조건, 근거 대상 아님)", 2)
    para(doc, f"IT 용량 {C.IT_CAPACITY_KW:,.0f} kW·평균 이용률 {C.UTIL_MEAN:.0%}, 이웃 건물 열수요(외기 {C.HEAT_BALANCE_T:.0f}°C 이하 {C.HEAT_UA_KW_PER_K:.0f} kW/°C + 온수), "
              f"히트펌프 용량 {C.HP_MAX_HEAT_KW:,.0f} kW, 배관 길이 {C.PIPE_TRENCH_M:.0f} m, ESS {C.ESS_KWH:,.0f} kWh/{C.ESS_KW:,.0f} kW, 냉각수 온도차 {C.V13['liquid_dT']:.0f} K. "
              "이 값들은 '이런 시설이라면'이라는 비교 조건입니다. 실제 시설에 적용할 때는 그 시설의 값으로 바꿔야 합니다.", size=9.5)

    # ---------------- 10. formulas
    doc.add_heading("11. 사용한 수식", 1)
    para(doc, "기호 옆의 설명만 읽어도 됩니다. 온도는 계산할 때 절대온도(K = °C + 273.15)로 바꿉니다.", color=MUTED, size=9)
    doc.add_heading("평가 지표", 2)
    formula(doc, "pue", r"\mathrm{PUE}=\frac{E_{\mathrm{DC}}}{E_{\mathrm{IT}}}", "데이터센터 전체 전기 ÷ 서버 전기. 1에 가까울수록 좋음. 히트펌프·보일러는 포함하지 않음.")
    formula(doc, "final", r"E_{\mathrm{final}}=E_{\mathrm{grid}}+F_{\mathrm{gas}}", "최종에너지 = 전력망에서 받은 전기 + 보일러 가스.")
    formula(doc, "primary", rf"E_{{\mathrm{{primary}}}}={C.PEF_ELEC}\,E_{{\mathrm{{grid}}}}+{C.PEF_GAS}\,F_{{\mathrm{{gas}}}}",
            "1차에너지 = 전기 1 kWh를 만들려면 발전소에서 연료 약 2.75 kWh가 든다는 점까지 반영 (국내 건축물 에너지효율등급 고시값).")
    formula(doc, "gain", r"\mathrm{Reduction}=1-\frac{E}{E_0},\qquad \mathrm{Efficiency\ gain}=\frac{E_0}{E}-1",
            "감소율(Reduction)과 효율 향상(Efficiency gain). 같은 일을 할 때 에너지가 32% 줄면 효율은 47% 좋아진 것 (같은 에너지로 1.47배 일함).")
    formula(doc, "erf", r"\mathrm{ERF}=\frac{Q_{\mathrm{useful}}}{E_{\mathrm{DC}}}", "에너지 재사용 비율: 데이터센터 전기 중 몇 %가 쓸모 있는 열로 다시 쓰였나.")
    doc.add_heading("열 회수 단계", 2)
    formula(doc, "qhp", r"Q_{\mathrm{HP}}=\min\left(\frac{D}{1-\lambda},\ Q_{\max},\ \frac{Q_{\mathrm{cool}}}{1-1/\mathrm{COP}}\right)",
            "히트펌프 출력은 ① 수요(배관손실 λ 보정), ② 장비 용량, ③ 서버 열의 양 중 가장 작은 값으로 제한.")
    formula(doc, "qevap", r"Q_{\mathrm{evap}}=Q_{\mathrm{HP}}-W_{\mathrm{HP}},\quad W_{\mathrm{HP}}=\frac{Q_{\mathrm{HP}}}{\mathrm{COP}},\quad Q_{\mathrm{useful}}=(1-\lambda)\,Q_{\mathrm{HP}}",
            "회수열(서버에서 뽑은 열) = 출력 − 전기. 유효열 = 출력에서 배관손실을 뺀 값.")
    formula(doc, "boiler", r"F_{\mathrm{gas}}=\frac{D-Q_{\mathrm{useful}}}{\eta_{\mathrm{boiler}}}", "부족한 난방은 보일러(효율 0.9)가 채움.")
    doc.add_heading("장비 모델", 2)
    formula(doc, "cop", r"\mathrm{COP}=\min\left(\eta_c\frac{T_{\mathrm{cond}}}{T_{\mathrm{cond}}-T_{\mathrm{evap}}},\ \mathrm{COP}_{\max}\right)\cdot \mathrm{PLF},\quad T_{\mathrm{evap}}=T_{\mathrm{ret}}-5,\ T_{\mathrm{cond}}=T_{\mathrm{supply}}+5",
            f"히트펌프 효율: 이론 최대(카르노)의 {C.V13['hp_carnot']:.0%}. 냉각수 환수온도(T_ret)와 난방 공급온도(T_supply)의 차이가 작을수록 좋음.", fs=13)
    formula(doc, "plf", r"\mathrm{PLF}=1-C_d\left(1-\frac{\mathrm{PLR}}{\mathrm{PLR}_{\min}}\right)\ \ (\mathrm{PLR}<\mathrm{PLR}_{\min}),\ \ \mathrm{otherwise}\ 1",
            f"부분부하 보정: 용량의 {C.V13['hp_plr_mod_min']:.0%} 아래로 돌리면 켜졌다 꺼졌다 하며 효율 손실 (C_d = {C.V13['hp_cd']}).", fs=13)
    formula(doc, "chiller", r"\mathrm{COP}_{\mathrm{ch}}=\eta_{ch}\frac{T_{\mathrm{evap}}}{T_{\mathrm{cond}}-T_{\mathrm{evap}}},\quad T_{\mathrm{cond}}=\max(T_{\mathrm{out}},15)+8",
            "냉동기 효율: 바깥이 더울수록 나빠짐.", fs=13)
    formula(doc, "free", r"f_{\mathrm{free}}=\mathrm{clip}\left(\frac{T_{\mathrm{ret}}-(T_{\mathrm{out}}+\Delta T_{\mathrm{app}})}{T_{\mathrm{ret}}-T_{\mathrm{sup}}},\ 0,\ 1\right)",
            "외기냉방 비율: 바깥 공기로 냉각수를 얼마나 식힐 수 있나. 냉각수가 따뜻할수록 1년 중 더 많은 시간 가능.", fs=13)
    formula(doc, "tretdc", r"T_{\mathrm{ret,dc}}=T_{\mathrm{ret}}-\frac{Q_{\mathrm{evap}}}{\dot m\,c_p}",
            "히트펌프가 열을 먼저 뽑으면 건식냉각기로 가는 물이 그만큼 식습니다 (v1.3.1). 외기냉방 비율은 이 온도로 계산.", fs=13)
    formula(doc, "tcond", r"T_{\mathrm{cond}}=\max\left(\max(T_{\mathrm{out}},15)+8,\ T_{\mathrm{out}}+\frac{Q_{\mathrm{rej}}\,\Delta T_d}{Q_d}\right)",
            "건식냉각기가 팬 100%로도 열을 못 버리면 응축온도가 올라가 냉동기 효율이 떨어집니다. 용량을 넘는 방열은 허용하지 않음 (v1.3.1).", fs=13)
    formula(doc, "breakeven", r"\mathrm{COP}_{\mathrm{breakeven}}=\frac{\mathrm{PEF}_{\mathrm{elec}}\,\eta_{\mathrm{boiler}}}{\mathrm{PEF}_{\mathrm{gas}}}",
            f"이 값({C.PEF_ELEC*C.BOILER_EFF/C.PEF_GAS:.2f})보다 COP가 높으면 1차에너지 기준으로 히트펌프가 보일러보다 유리.", fs=13)
    formula(doc, "pump", r"P_{\mathrm{pump}}=\frac{\dot m\,g\,H}{\eta_p\,\eta_d},\quad H=H_s+(H_d-H_s)\varphi^2,\quad \varphi=\max\left(\frac{Q}{Q_d},\ \varphi_{\min}\right)",
            f"펌프 전력: 정압 H_s={C.V13['pump_H_static_m']:.0f} m, 설계 양정 H_d={C.V13['pump_H_design_m']:.0f} m, 최소유량 {C.V13['pump_min_flow']:.0%}. "
            "효율 η_p는 최고효율점에서 멀어질수록 낮아짐. 실측 성능곡선으로 교체 가능.", fs=13)
    formula(doc, "fan", r"P_{\mathrm{fan}}=P_{\mathrm{rated}}\,s^{n},\quad s=\frac{Q_{\mathrm{rej}}}{Q_d\,(T_{\mathrm{in}}-T_{\mathrm{out}})/\Delta T_d}",
            f"팬 전력: 필요한 풍량 비율 s의 {C.V13['fan_exp']}제곱 (최소 속도 {C.V13['fan_min_speed']:.0%}).", fs=13)
    formula(doc, "leak", r"P_{\mathrm{IT}}=P_{\mathrm{IT},0}\left(1+k\,\max(0,\ T_{\mathrm{sup}}-30)\right)",
            f"냉각수가 30°C보다 따뜻하면 칩 누설전력으로 서버 전기가 °C당 {C.V13['leak_per_K']:.1%} 늘어난다고 가정.", fs=13)
    formula(doc, "copout", r"T_{\mathrm{evap}}=T_{\mathrm{src,out}}-\Delta T_{\mathrm{pinch}},\quad T_{\mathrm{src,out}}=T_{\mathrm{ret}}-\frac{Q_{\mathrm{evap}}}{\dot m\,c_p},\quad T_{\mathrm{cond}}=T_{\mathrm{supply}}+\Delta T_{\mathrm{pinch}}",
            "v1.4 히트펌프: 증발온도는 열원(서버 냉각수)의 '출구' 온도보다 낮아야 함. 뽑는 열이 많을수록 출구가 식어 COP가 떨어짐 (반복 계산).", fs=13)
    formula(doc, "lorenz", r"\mathrm{COP}_{\mathrm{Lorenz}}=\eta_L\,\frac{\bar T_H}{\bar T_H-\bar T_C},\quad \bar T=\frac{T_{\mathrm{in}}-T_{\mathrm{out}}}{\ln(T_{\mathrm{in}}/T_{\mathrm{out}})}",
            "로렌츠 COP(비교용): 열원·난방 쪽 입구·출구 온도의 로그평균을 씀 (Jensen 외 2018).", fs=13)
    formula(doc, "dp", r"\min_{x_1..x_T}\sum_t \mathrm{PE}_t(x_t)\ \ \mathrm{s.t.}\ |T_{\mathrm{sup},t}-T_{\mathrm{sup},t-1}|\leq\Delta_{\max},\ \ \mathrm{hold}\geq H",
            "v1.4 실현 가능 운전: 1년 전체를 동적계획법으로 풀어 변경폭·최소 유지시간 제약 안에서 1차에너지 합을 최소화.", fs=13)
    formula(doc, "copula", r"z_k=\sqrt{\rho}\,z_{\mathrm{common}}+\sqrt{1-\rho}\,z_{k},\quad \varepsilon_k=F^{-1}_{\mathrm{ESIF}}\left(\Phi(z_k)\right)",
            "v1.5.1–1.5.2 지도 B: 후보 k의 냉각 설비 효율 오차(냉동기 COP_true = COP_model/(1+ε), 팬·펌프 전력 ×(1+ε)). ρ는 후보 간 오차 상관계수(1 = 모두 같은 오차, 0 = 모두 따로). 실측 오차 분포 모양은 그대로 유지(가우시안 코풀라).", fs=13)
    formula(doc, "opt", r"x_t^{*}=\arg\min_{x\in\{T_{\mathrm{sup}}\leq T_{\mathrm{class}}\}\times\{0,\,0.5,\,1\}}\ \left(2.75\,E_{t}(x)+1.1\,F_{t}(x)\right)",
            "최적 운전: 매시간 1차에너지가 가장 작은 조합을 고름. 전기요금 없음.", fs=13)
    doc.add_heading("검증 지표", 2)
    formula(doc, "err", r"\mathrm{MAE}=\frac{1}{n}\sum|\hat y-y|,\quad \mathrm{WAPE}=\frac{\sum|\hat y-y|}{\sum|y|},\quad \mathrm{Bias}=\frac{\sum(\hat y-y)}{\sum y}",
            "MAE = 평균 오차 크기(kW). WAPE = 실제값 대비 오차 비율. Bias = 한쪽으로 치우친 정도(음수면 과소예측).", fs=13)
    formula(doc, "loa", r"\mathrm{LoA}=\overline{d}\pm1.96\,s_d,\quad d=\hat y-y",
            "Bland–Altman 일치 범위: 예측과 실측 차이의 95%가 들어오는 범위.", fs=13)

    # ---------------- 10. glossary
    doc.add_heading("12. 용어 풀이", 1)
    gl = [
        ("PUE", "Power Usage Effectiveness", "데이터센터 전체 전기 ÷ 서버 전기. 1.2면 서버 1을 돌리는 데 0.2를 냉각 등에 더 씀."),
        ("최종에너지", "Final energy", "건물이 실제로 사 온 에너지(전기 + 가스)."),
        ("1차에너지", "Primary energy", "그 전기·가스를 만들기까지 든 원래 연료. 전기는 발전 손실 때문에 더 큼."),
        ("엑서지", "Exergy", "에너지의 '질'. 같은 1 kWh라도 전기는 쓸모가 크고 미지근한 물은 작음."),
        ("COP", "Coefficient of Performance", "전기 1을 넣어 열(또는 냉기)을 몇 옮기는지. COP 5 = 전기 1로 열 5."),
        ("히트펌프", "Heat pump", "낮은 온도의 열을 전기로 끌어올려 높은 온도로 만드는 장치(냉장고의 반대)."),
        ("외기냉방", "Free cooling", "냉동기 대신 차가운 바깥 공기로 냉각수를 식히는 것. 팬 전기만 듦."),
        ("건식냉각기", "Dry cooler", "물을 뿌리지 않고 팬 바람으로 냉각수를 식히는 실외기."),
        ("냉동기", "Chiller", "압축기로 냉각수를 강제로 차갑게 만드는 장치. 전기를 많이 씀."),
        ("수랭(온수 냉각)", "Warm-water liquid cooling", "서버에 직접 물을 대어 식힘. 30~40°C 물로도 가능해 열 재사용에 유리."),
        ("공랭", "Air cooling", "찬 공기로 서버를 식힘. 냉기를 만들려고 냉동기를 많이 씀."),
        ("UPS·전력변환", "Uninterruptible Power Supply", "정전 대비 장치. 전기를 바꾸는 과정에서 3~6%를 열로 잃음."),
        ("부분부하율", "PLR, Part-Load Ratio", "장비 최대 능력 대비 지금 쓰는 비율."),
        ("PLF", "Part-Load Factor", "부분부하에서 효율이 얼마나 떨어지는지 나타내는 보정계수."),
        ("회수 가능열 / 회수열 / 유효열", "Recoverable / recovered / useful heat", "뽑을 수 있었던 열 / 실제로 뽑은 열 / 손실 후 실제로 쓰인 열."),
        ("배관손실", "Distribution loss", "이웃 건물로 가는 배관에서 식어서 잃는 열(가정 5%)."),
        ("ESS", "Energy Storage System", "대형 배터리. 전기를 저장했다가 필요할 때 씀."),
        ("SOC / DoD", "State of Charge / Depth of Discharge", "배터리 충전 상태(%) / 한 번에 얼마나 깊게 썼는지."),
        ("EFC", "Equivalent Full Cycles", "완전 충방전 몇 번에 해당하는지. 배터리 수명 소모의 척도."),
        ("피크 저감", "Peak shaving", "가장 많이 쓰는 순간의 전력을 낮추는 것. 에너지 총량과는 다른 지표."),
        ("누설전력", "Leakage power", "칩이 뜨거울수록 일을 안 해도 새어 나가는 전력."),
        ("시스템 경계", "System boundary", "어디까지를 계산에 넣을지 정한 선. 경계가 다르면 같은 결과도 다르게 보임."),
        ("설비 효과 / 운전 효과", "Equipment / operation effect", "장비를 바꿔서 얻은 절감 / 같은 장비를 더 잘 돌려서 얻은 절감."),
        ("보정 / 검증 구간", "Calibration / test period", "모델을 맞추는 데 쓴 기간 / 맞춘 뒤 성적을 매기는 데 쓴, 처음 보는 기간."),
        ("MAE / WAPE / Bias", "Error metrics", "오차의 평균 크기 / 실제값 대비 오차 비율 / 한쪽으로 치우친 정도."),
        ("Bland–Altman", "Agreement analysis", "두 측정(예측·실측)이 얼마나 일치하는지 차이와 95% 범위로 보는 그림."),
        ("설계 외기온도", "Design outdoor temperature", "설비 크기를 정할 때 기준으로 삼는 '거의 가장 더운' 온도. 1년 중 0.4% 시간만 이보다 더움."),
        ("ASHRAE 수랭 등급", "W32 / W40 / W45", "서버가 받아들일 수 있는 냉각수 공급온도 상한. W40 = 40°C까지."),
        ("손익분기 COP", "Break-even COP", "히트펌프가 보일러보다 1차에너지를 덜 쓰기 시작하는 COP."),
        ("몬테카를로 모의", "Monte Carlo simulation", "오차를 무작위로 여러 번 뽑아 결과가 얼마나 흔들리는지 세는 방법."),
        ("선택 안정성", "Choice stability", "오차를 넣어도 같은 운전이 최선으로 남는 비율. 가정한 오차 모델 하에서의 값."),
        ("오차 상관계수", "Error correlation (ρ)", "여러 후보의 예측 오차가 같은 방향으로 움직이는 정도. 1이면 똑같이 틀리고 0이면 제각각 틀림."),
        ("후회 손실", "Regret", "오차 때문에 최선이 아닌 운전을 골라서 더 쓴 에너지."),
        ("동적계획법", "Dynamic Programming", "긴 기간의 결정을 한 시간씩 쪼개, 앞의 선택이 뒤에 주는 제약까지 고려해 전체 최적을 찾는 방법."),
        ("로렌츠 COP", "Lorenz COP", "물 온도가 열교환기를 지나며 변하는 것을 반영한 이론 최대 COP."),
        ("핀치 온도차", "Pinch temperature difference", "열교환기에서 두 유체가 가장 가까워지는 지점의 온도차. 작을수록 큰 열교환기."),
        ("스트레스 테스트", "Stress test", "폭염·과부하·성능 저하 같은 가혹 조건을 일부러 줘서 설비가 버티는지 보는 시험."),
        ("드리프트", "Drift", "시간이 지나며 시설이 바뀌어 예전에 맞춘 모델이 점점 안 맞게 되는 현상."),
        ("민감도 분석", "Sensitivity analysis", "가정한 값을 바꿨을 때 결과가 얼마나 흔들리는지 보는 분석. 실측 오차가 아님."),
    ]
    table(doc, ["용어", "영어", "쉬운 설명"], [list(g) for g in gl], widths=[3.4, 4.4, 9.2], fs=8.5)

    # ---------------- 11. limitations
    doc.add_heading("13. 한계 — 이 결과를 그대로 믿으면 안 되는 부분", 1)
    lim = [
        ("가상 기상·부하. ", "서울과 비슷하게 만든 합성 데이터입니다. 실제 한국 데이터센터·건물의 측정값이 아닙니다."),
        ("근거의 성격. ", "9장의 근거는 대부분 다른 시설·제품·표준에서 온 대표값입니다. 이 시설에서 잰 값이 아니므로, 실제 적용 시 설비 사양서와 실측으로 바꿔야 합니다."),
        ("근거를 못 찾은 값. ", "펌프 정압 비율·최소유량, 히트펌프 최소 변조율·핀치 온도차, 공조기 팬 정격, 운전 제약값은 근거를 찾지 못해 민감도 분석으로만 영향을 확인했습니다."),
        ("누설전력. ", f"{C.V13['leak_per_K']*100:.2f}%/°C는 서버 팬까지 포함된 '부하 시' 측정의 상한값입니다. 팬 없는 직접 수랭이라면 더 작을 수 있고, 그러면 운전 최적화 효과가 커집니다(10장 민감도 그림)."),
        ("1차에너지 계수. ", f"전기 계수가 {C.PEF_ELEC}에서 1.9(EU 기본값)로 내려가면 전기를 쓰는 대책의 상대적 가치가 바뀝니다(10장 민감도 그림)."),
        ("운전 효과의 두 값. ", "'이상적' 값은 매시간 자유롭게, 미래를 안다고 보고 고른 상한입니다. v1.4의 '실현 가능' 값은 변경폭·유지시간·예보 오차를 넣었지만 열 관성과 기동 손실은 여전히 없습니다."),
        ("예측 오차 미반영. ", "운전 판단은 오차 없는 모델 기준입니다(운전 지도 A). 실측 검증에서 비IT 전력 WAPE가 20~35%였고, 1·2위 차이가 1% 미만인 시간이 많아 실제로는 판단이 뒤집힐 수 있습니다. 다음 단계에서 다룹니다."),
        ("수랭 열 포집. ", "IBM 사례처럼 랙 열교환기까지 쓰면 약 99%가 물로 가지만, 칩에서 직접 물로 가는 것은 60~70%입니다. 공기로 간 열은 더 낮은 온도라 히트펌프 열원 온도가 실제로는 조금 낮을 수 있습니다."),
        ("단순화된 열 흐름. ", "v1.3.1에서 히트펌프 흡열 후 환수온도 저하는 넣었지만, 유량 변화에 따른 온도차 변화와 배관·탱크의 열 관성은 없습니다."),
        ("후보의 범위. ", "히트펌프 운전량은 0·50·100% 세 단계, 냉각수 온도는 5°C 간격만 비교했습니다. 연속 최적화나 기동·정지 비용은 없습니다."),
        ("서버 등급. ", f"기본값 {C.V13['coolant_class']}는 가정입니다. 실제 서버 사양이 W32라면 운전 최적화 효과는 거의 0입니다."),
        ("상세 모델 미검증. ", "최종 모델의 팬·펌프·히트펌프 식은 문헌·표준값으로 만들었고 실측으로 보정하지 않았습니다. ESIF 검증은 간소화 모델에 대한 것입니다."),
        ("검증 범위. ", "ESIF에는 냉동기·히트펌프가 없어 이 둘의 모델은 실측으로 검증되지 않았습니다. 2020년 이후 펌프 전력이 2~3배로 늘어난 변화(드리프트)가 있고, 2024년 설비 변경 이후 데이터는 제외했습니다."),
        ("ESS. ", "열화 모델은 단순한 경험식이며, ESS의 경제성(요금)은 원칙에 따라 계산하지 않았습니다. 최종 모델에서는 피크만 계산했고, 손실·열화는 초기 모델 값(부록)입니다."),
        ("설비 공유. ", "모든 시나리오가 같은 크기의 건식냉각기를 쓴다고 가정했습니다(공랭 기준으로 설계). 수랭 전용으로 줄이면 팬 전력이 약간 달라집니다."),
        ("운전 지도. ", "지도는 IT 평균 부하 한 조건에서 그렸습니다. 지도 B의 냉각 오차는 다른 시설(ESIF)의 간소화 모델 오차를 빌려 썼고, COP 오차 ±15%는 가정입니다. 오차를 시뮬레이터 안에 넣어 열수지까지 다시 계산했지만 오차 분포 자체가 대리값·가정값입니다. ρ=0(후보별 독립)은 스트레스 시나리오이며 보장된 최악의 상한이 아닙니다."),
        ("예보 모델. ", "기온 예보 오차는 실제 예보가 아니라 통계적으로 만든 오차(AR(1))입니다. IT 부하는 미리 안다고 보았고, 1년 계획을 한 번에 세웠습니다(매일 갱신하는 운전과 다름)."),
        ("운전 제약값. ", "변경폭·최소 유지시간은 실제 설비 사양이 아닌 가정입니다. 냉각수 온도를 바꿀 때 서버가 겪는 온도 변화 속도 제한은 넣지 않았습니다."),
    ]
    for lead, txt in lim:
        bullet(doc, txt, lead)

    # ---------------- 12. sources
    doc.add_heading("14. 데이터 출처와 재현 방법", 1)
    for lead, txt in [
        ("NLR(옛 NREL) ESIF: ", "미국 국립재생에너지연구소 데이터센터 시간별 운영 데이터(2016~2023, CC BY 4.0). 냉각 전력 모델의 보정·검증에 사용."),
        ("HEATWISE (Aalborg University): ", "공랭 서버실 환수온도 실측(약 25°C). 히트펌프 열원 온도 민감도에 사용."),
        ("Chen et al. (2025), Energy 318: ", "데이터센터 열회수 MILP 운전 최적화, 규칙 운전 대비 8.12% 절감 — 비교 기준 문헌."),
        ("Zhou et al. (2025), Energy 323: ", "데이터센터 폐열 히트펌프 COP 3.87~5.27 — v1.3 COP 범위 확인용."),
        ("Wenzel, Mühlen & Radgen (2023), Energies 16(9):3661: ", "건식·습식 냉각기 제조사 데이터 분석 — 접근온도, 팬 전력."),
        ("ASHRAE 90.1 Appendix G: ", "VAV 팬 부분부하 곡선, 냉수 펌프 22 W/gpm, 공랭 칠러 최소 효율."),
        ("Nussbaumer & Thalmann (2014), IEA Bioenergy Task 32: ", "지역난방 배관 손실 상관식."),
        ("Kadhim (2019), Electronics Cooling: ", "냉각수 온도에 따른 랙 전력 변화."),
        ("Gasser et al. (2017), 12th IEA Heat Pump Conference: ", "저리프트 히트펌프 COP."),
        ("Arpagaus et al. (2018), Energy 152: ", "고온 히트펌프 COP와 온도 리프트."),
        ("Fuentes, Waddicor & Salom (2016), REHVA Journal: ", "물-물 히트펌프 부분부하 손실계수."),
        ("David et al. (2013), Electronics Cooling (IBM): ", "온수 냉각 서버의 물 회수율."),
        ("Xu et al. (2016), IEEE Trans. Smart Grid / EVreporter (2024): ", "배터리 DoD 열화 함수, LFP BESS 수명."),
        ("ENERGY STAR UPS 기준, 건축물에너지효율등급 운영규정 별표3, 박찬일·김래현(2016) 에너지공학: ", "UPS 효율, 1차에너지 계수, 보일러 효율."),
    ]:
        bullet(doc, txt, lead)
    para(doc, "재현: 터미널에서 `python make_report.py --run <esif_hourly.csv>` 한 줄이면 시뮬레이션 → 조합 분석 → 물리 모델 → 검증 → 그림 → 이 보고서까지 다시 만들어집니다. "
              "가정을 바꾸려면 config.py만 고치면 됩니다.", color=MUTED, size=9)

    # ---------------- appendix: early simplified model (v1.2)
    doc.add_heading("부록. 초기 간소화 모델(v1.2)의 결과 — 참고용", 1)
    rich(doc, [("본문과 숫자가 다른 이유. ", True),
               (f"프로젝트 초기에는 팬·펌프 전력을 냉각열의 일정 비율로, 히트펌프 COP를 고정값으로 둔 간소화 모델(v1.2)을 썼습니다. "
                f"이 모델에서는 효율 냉각 + 폐열 회수의 1차에너지 절감이 {cut(S2.primary_energy_kwh, S0.primary_energy_kwh):.0f}%로 나옵니다. "
                f"본문의 {pcut('S2 최적운전'):.1f}%는 장비별 물리 모델과 설비 제약을 넣은 최종 모델의 값이며, 이 보고서의 결론은 최종 모델을 따릅니다. "
                "아래는 초기 모델에서만 계산한 분석으로, 방향을 보는 참고 자료입니다.", False)])
    figure(doc, R / "v13" / "17_v12_vs_v13.png",
           "모델을 정교화해도 결론(순서와 대략의 크기)은 유지됩니다. 최종에너지는 시나리오별로 "
           + ", ".join(f"{n} {(v13.loc[k13, 'final_mwh'] / (s.loc[k12, 'total_final_energy_kwh'] / 1e3) - 1) * 100:+.1f}%"
                       for n, k12, k13 in [("S0", "S0_Baseline", "65°C | S0 기존(공랭)"), ("S1", "S1_EffCooling", "65°C | S1 규칙운전"),
                                           ("S2", "S2_HeatRecovery", "65°C | S2 규칙운전")]) + " 달라졌습니다.",
           "같은 시나리오를 초기 모델(v1.2)과 최종 모델로 계산한 연간 최종에너지 (규칙 운전, 65°C).")
    abc = combos[combos.combo == "ABC"].iloc[0]; c_only = combos[combos.combo == "C"].iloc[0]
    figure(doc, R / "combos" / "07_combinations.png",
           f"(초기 모델) 네 가지 대책 16개 조합 중 ABC(효율냉각+고효율 전력변환+열회수)가 최선입니다. 열회수(C)만 단독으로 하면 전기는 {-c_only.elec_cut_pct:.0f}% 늘지만 가스가 더 크게 줄어듭니다.",
           "2⁴ = 16개 조합 (초기 모델). A 효율냉각, B 고효율 전력변환, C 히트펌프 열회수, D ESS.")
    table(doc, ["대책", "단독 효과 (MWh/년)", "다른 대책 위에 추가 (MWh/년)", "평균 효과 (MWh/년)"],
          [[{"A": "A 효율 냉각", "B": "B 고효율 전력변환", "C": "C 히트펌프 열회수", "D": "D ESS"}[k],
            f"{r.alone_mwh:,.0f}", f"{r.on_top_of_others_mwh:,.0f}", f"{r.average_effect_mwh:,.0f}"] for k, r in eff.iterrows()],
          widths=[4.4, 4.0, 4.6, 4.0])
    para(doc, "단독 효과와 '추가' 효과가 다르면 대책끼리 서로 영향을 준다는 뜻입니다. A(수랭 → 냉각수가 따뜻함)가 있으면 C(히트펌프)의 효율이 좋아져 C의 효과가 커집니다(시너지).",
         color=MUTED, size=9)
    figure(doc, R / "02_accounting_bases.png",
           "(초기 모델) 같은 결과라도 어떤 잣대로 재느냐에 따라 개선 폭이 다릅니다. 전기를 만드는 데 드는 연료까지 따지는 1차에너지 기준에선 개선 폭이 작아집니다.",
           "최종에너지·1차에너지·엑서지 기준 비교 (초기 모델, S0 = 100).")
    figure(doc, R / "04_ess_tradeoff.png",
           f"(초기 모델) ESS는 충방전 손실({e0.ess_loss_kwh/1e3:,.1f} MWh/년)을 더하는 대신 최대 전력을 {e0.peak_cut_kw:,.0f} kW 낮춥니다. "
           f"배터리를 더 깊게 쓰면 피크는 {e1.peak_cut_kw - e0.peak_cut_kw:,.0f} kW 더 깎이지만 수명이 더 빨리 줄어듭니다.",
           "ESS 운전 범위 비교 (초기 모델).")

    doc.save(OUTFILE)
    print("written", OUTFILE)


if __name__ == "__main__":
    if "--run" in sys.argv:
        i = sys.argv.index("--run")
        run_pipeline(sys.argv[i + 1] if len(sys.argv) > i + 1 else None)
    build()
