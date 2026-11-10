"""All model assumptions in one place. Every value is an editable assumption, not measured data."""

HOURS = 8760

# --- Climate (synthetic, Seoul-like) ---
T_MEAN, T_SEASON_AMP, T_DAY_AMP = 12.5, 14.0, 4.0   # °C; coldest mid-Jan, hottest early Aug
T_NOISE_SD = 1.5

# --- IT workload (same in every scenario) ---
IT_CAPACITY_KW = 1000.0          # 1 MW IT room
IT_IDLE_FRACTION = 0.20          # [근거] AI 서버 유휴전력 = 정격의 20% (LBNL 2024 데이터센터 보고서; 8-GPU H100 실측 18%, Latif et al. 2024)
UTIL_MEAN, UTIL_DAY_AMP = 0.625, 0.15   # [근거] 연평균 전력 = 정격의 70% (LBNL 2024) → 0.20 + 0.80 × 0.625 = 0.70
JOBS_PER_UTIL_HOUR = 1000.0      # 1 'job' = normalized unit of AI compute; jobs/h = util * 1000

# --- Power path ---
MISC_FRACTION = 0.02             # lighting, controls etc. as share of IT power

# --- Space heating + hot water demand of neighbouring facility ---
HEAT_BALANCE_T = 18.0            # °C, no space heating above this
HEAT_UA_KW_PER_K = 25.0          # kW per K below balance temperature
DHW_KW_DAY, DHW_KW_NIGHT = 120.0, 40.0   # domestic hot water (06–22 / otherwise)
HOT_WATER_SUPPLY_C = 65.0
BOILER_EFF = 0.90                # [근거] 국내 가스보일러 1등급 R≥91%, 2등급 ≥88% (박찬일·김래현 2016, 에너지공학 25(3)); 실사용은 더 낮음 → 절감 과소평가 쪽

# --- Primary energy factors (assumption: Korean building-rating style factors) ---
PEF_ELEC, PEF_GAS = 2.75, 1.10   # [근거] 건축물에너지효율등급 인증제도 운영규정 [별표3]: 전력 2.75, 연료 1.1, 지역난방 0.728

SCENARIOS = {
    "S0_Baseline": dict(
        label="기존: 공랭 + 냉동기, 열은 외부 방출, 난방은 보일러",
        ups_eff=0.94, cooling="air", heat_pump=False, ess=False),
    "S1_EffCooling": dict(
        label="효율 냉각: 수랭(온수 냉각) + 외기냉방 + 고효율 전력변환",
        ups_eff=0.97, cooling="liquid", heat_pump=False, ess=False),
    "S2_HeatRecovery": dict(
        label="S1 + 히트펌프 폐열회수 → 인근 난방·온수",
        ups_eff=0.97, cooling="liquid", heat_pump=True, ess=False),
    "S3_HR_ESS": dict(
        label="S2 + ESS 피크 저감 (열화 고려 운전)",
        ups_eff=0.97, cooling="liquid", heat_pump=True, ess=True),
}

# --- Cooling models ---
CARNOT_FRACTION_CHILLER = 0.45   # [근거] AHRI 550/590 조건(외기 35°C, 냉수 6.7°C)에서 모델 COP 3.26 → ASHRAE 90.1 공랭 칠러 최소 EER 10.1(COP 2.96)과 고효율 제품 사이
AIR = dict(t_evap=5.0, cond_approach=8.0, cond_min=15.0, aux_frac=0.08, free_cool_below=4.0)
LIQUID = dict(supply_c=30.0, return_c=40.0, t_evap=25.0, cond_approach=8.0, cond_min=15.0,
              aux_frac=0.03, dry_cooler_approach=10.0)   # [근거] 건식냉각기 접근온도 제조사 중앙값 10 K (IQR 8.5–11.8), Wenzel et al. 2023, Energies 16:3661

# --- Heat pump (source = liquid-cooling return water) ---
CARNOT_FRACTION_HP = 0.50        # [근거] 실사용 히트펌프 카르노 대비 45–55% (OpenEnergyMonitor HeatpumpMonitor); Arpagaus 2018 30 K 리프트 COP 5.7–6.5 ≈ 0.45–0.50
HP_SOURCE_EVAP_C = 35.0          # evaporator temp on 40 °C return water
HP_SINK_COND_C = 70.0            # condenser temp to supply 65 °C water
HP_MAX_HEAT_KW = 800.0
# [근거] 배관 열손실(연간, 공급열 대비 %) = 17 × (선형 열밀도 MWh/(a·m))^-0.5  (IEA Bioenergy Task 32, Nussbaumer & Thalmann 2014)
PIPE_TRENCH_M = 200.0            # 이웃 건물까지 배관 길이 (시나리오 설정)
ANNUAL_HEAT_MWH = 2505.0         # 연간 열수요 (sim.climate_and_load 결과와 같음)
PIPE_LOSS_FRAC = round(0.17 * (ANNUAL_HEAT_MWH / PIPE_TRENCH_M) ** -0.5, 3)   # = 0.048
# Heat pump on an air-cooled room: source = room-cooling return water ~25 °C (HEATWISE AAU measured 24.5–25.8 °C)
AIR_HP_SOURCE_RETURN_C = 25.0
AIR_HP_SOURCE_EVAP_C = 20.0

# --- ESS ---
ESS_KWH, ESS_KW = 1000.0, 250.0
ESS_ETA_CH, ESS_ETA_DIS = 0.95, 0.95       # round trip ≈ 0.90
ESS_SOC_MIN, ESS_SOC_MAX = 0.20, 0.90      # degradation-aware window
# Peak target: lowest grid peak the ESS can hold all year (found by binary search in sim.py)
# Degradation (simple, adjustable): cycle fade per equivalent full cycle scaled by DoD stress,
# plus calendar fade per year.
# [근거] LFP BESS: DoD 90%·0.5C에서 6,000사이클에 SoH 70% (EVreporter 2024, 314Ah LFP 셀 BESS) → 30%/6000 = 5.0e-5 /EFC @90% DoD
# DoD 지수 1.3: Xu et al. 2016, IEEE Trans. Smart Grid (Φ(d)=k·d^1.3)
DOD_STRESS_EXP = 1.3
FADE_PER_EFC_AT_80DOD = 5.0e-5 * (0.8 / 0.9) ** DOD_STRESS_EXP   # ≈ 4.3e-5 (이전 2.0e-4는 근거 없음)
CALENDAR_FADE_PER_YEAR = 0.015   # [근거] 0.3C급 LFP BESS 달력수명 20년에 SoH 70% → 약 1.5%/년 (EVreporter 2024)

# ======================= v1.3 physics (all values are editable assumptions) =======================
V13 = dict(
    # heat pump: COP from water temperatures + part load (outdoor air does NOT enter directly)
    hp_carnot=0.50, hp_evap_approach=5.0, hp_cond_approach=5.0,
    hp_cop_max=9.0,        # [근거] 저리프트 전용 히트펌프 실증 COP≈9 @20 K 리프트 (Gasser et al. 2017, IEA HPT Conf.); 일반 제품은 30–60 K 리프트용 설계
    hp_plr_mod_min=0.30,   # inverter modulates down to 30 % load; below that it cycles on/off
    hp_cd=0.25,            # [근거] ASHRAE 116 / AHRI 210/240 기본값 0.25, 물-물 히트펌프 실측 0.22 (Fuentes et al. 2016, REHVA J.)
    heat_supply_c=(65.0, 45.0),   # two fixed heating supply temperatures (stated, not optimised)
    # chiller
    chiller_carnot=0.45,   # 위 CARNOT_FRACTION_CHILLER 근거와 동일
    chiller_evap_approach=2.0, cond_approach=8.0, cond_min=15.0, chiller_cop_max=15.0,
    # dry cooler (heat rejection) fans
    dc_approach=10.0, dc_design_dT=10.0,   # [근거] 접근온도 중앙값 10 K (Wenzel et al. 2023)
    dc_design_kw=None,     # v1.3.1: 설계 외기(0.4% 초과온도)에서 S0 최대 방열을 감당하도록 sim13.size_dry_cooler()가 계산
    dc_design_exceed=0.004,  # [근거] ASHRAE 냉방 설계조건 0.4% 초과 확률 (Handbook Fundamentals Ch.14)
    dc_fan_kw_per_kw=0.02,
    dc_fan_rated_kw=None,  # = dc_fan_kw_per_kw × 설계용량. [근거] 0.02 kWel/kWth: 제조사 범위 0.01–0.06 (Wenzel et al. 2023)
    fan_exp=3.0,           # [근거] 정압 설정이 없는 실외기 팬 = 팬 상사법칙(풍량^3)
    fan_min_speed=0.20,    # 가정 (민감도 분석)
    # air-side fans (air-cooled room only): CRAH units
    crah_fan_rated_kw=40.0,   # 가정 (민감도 분석). 부분부하는 ASHRAE 90.1 App. G VAV 팬 곡선 사용
    crah_curve=(0.0013, 0.1470, 0.9506, -0.0998),   # [근거] ASHRAE 90.1 Appendix G Table G3.1.3.15 (Method 2)
    # pumps: P = m*g*H/(eta_pump*eta_drive), H = H_static + (H_design - H_static)*phi^2, min flow
    pump_H_design_m=23.0,  # [근거] 설계점 비전력 22 W/gpm (ASHRAE 90.1 App. G G3.1.3.10 냉수 펌프)이 되도록 양정 역산
    pump_H_static_m=8.0,   # 가정: 차압 설정분 = 설계 양정의 1/3 (민감도 분석)
    pump_eta_max=0.75, pump_bep_flow=0.85,
    pump_eta_floor=0.25, drive_eta=0.90, pump_min_flow=0.30,   # 가정 (민감도 분석). 선호 운전영역 70–120% BEP, 온도상승 한계 ~10% BEP (Budris 2016)
   
    pump_curve_csv=None,   # optional measured curve: columns flow_frac, head_m, eff  (replaces the formula)
    # water loops
    liquid_dT=10.0, liquid_supply_design=30.0, liquid_supply_options=(25.0, 30.0, 35.0, 40.0, 45.0),
    # [근거] ASHRAE TC9.9 Thermal Guidelines 5th ed.(2021) 수랭 등급 = 설비 공급수 상한온도
    coolant_class="W40", coolant_class_max={"W27": 27.0, "W32": 32.0, "W40": 40.0, "W45": 45.0},
    hp_levels=(0.0, 0.5, 1.0),   # 히트펌프 운전량 후보 (수요 대비 0 / 50 / 100 %)
    # ---- v1.4 P1: heat pump COP from source/sink inlet-outlet temperatures
    hp_cop_method="outlet",  # "outlet": 증발=열원 출구−핀치, 응축=난방 출구+핀치 (단단 증기압축 사이클) | "lorenz" | "inlet"(v1.3)
    hp_pinch=3.0,            # 열교환기 핀치 온도차 K. [근거] Jensen et al. 2018 검토 범위 0–10 K (가정, 민감도)
    lorenz_eff=0.50,         # [근거] 대형 히트펌프 로렌츠 효율 0.5 (Lund 2017 등 문헌 상수), 덴마크 실설비 0.5–0.6 (Pieper et al. 2020)
    heat_return_c={65.0: 40.0, 45.0: 25.0},  # [근거] 라디에이터 실측 64/42°C (Jangsten 2016), 저온 난방 45/25°C 설계 (Danfoss)
    # ---- v1.4 P0: equipment limits
    chiller_t_cond_max=60.0,  # [근거] 공랭 칠러 최대 외기 52°C (Aggreko 700 kW 사양) + 응축 접근 8 K
    dc_derate=1.0,            # 건식냉각기 성능 계수 (스트레스 테스트에서 0.8)
    # ---- v1.4 P2: realistic operation
    ramp_K=5.0,              # 시간당 냉각수 설정온도 최대 변경폭 (가정, 민감도)
    hold_h=4,                # 설정 변경 후 최소 유지시간 h (가정, 민감도)
    forecast_sd=1.9,         # [근거] 1일 전 기온 예보 MAE 1.2–2.0°C (meteoblue 2021 비교) → 표준편차 ≈ MAE×1.25
    forecast_rho=0.95,       # 예보 오차의 시간 자기상관 (가정)
    air_chw_supply=12.0, air_dT=6.0, design_heat_kw=1100.0,
    ups_legacy=0.94,       # [근거] 구형 <90%, 일반 고효율 92–95% (ENERGY STAR) → 상단값 사용(절감 과대평가 방지)
    ups_efficient=0.97,    # [근거] ENERGY STAR UPS 최소 평균효율 0.0058·ln(P)+0.886 → 1 MW에서 0.966
   
    # warmer coolant -> hotter chips -> more leakage power (assumption, liquid only)
    leak_per_K=0.0022,     # [근거] 하이브리드 수랭 랙: 부하 시 입구 24→42°C에서 랙 전력 +4% (≈0.22%/°C), 유휴 시 <0.5% (Kadhim 2019, Electronics Cooling)
    leak_ref_c=30.0,
)
