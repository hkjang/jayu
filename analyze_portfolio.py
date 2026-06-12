import csv, json, os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

rows = []
with open(os.path.join(BASE_DIR, 'toss_portfolio.csv'), encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(dict(r))

# USD/KRW 환율 (yfinance로 조회)
import yfinance as yf
try:
    fx = yf.download('USDKRW=X', period='1d', auto_adjust=True, progress=False)
    close_data = fx['Close'].dropna() if not fx.empty else pd.Series(dtype=float)
    usd_krw = float(close_data.iloc[-1]) if len(close_data) > 0 else 1380
except Exception as e:
    print(f"⚠ 환율 조회 실패: {e}, 기본값 1380 사용")
    usd_krw = 1380
print(f"USD/KRW: {usd_krw:.2f}")

# 평가금을 KRW로 통일
total_krw = 0
for r in rows:
    if r['평가금'] == '':
        r['평가금_krw'] = 0
        continue
    val = float(r['평가금'])
    if r['통화'] == 'USD':
        r['평가금_krw'] = val * usd_krw
    else:
        r['평가금_krw'] = val
    total_krw += r['평가금_krw']

print(f"총 포트폴리오: {total_krw:,.0f} KRW ({total_krw/usd_krw:,.0f} USD)")

# 비중 계산 및 상위 종목
for r in rows:
    r['비중'] = round(r['평가금_krw'] / total_krw * 100, 3) if total_krw else 0

rows_sorted = sorted(rows, key=lambda x: x['평가금_krw'], reverse=True)

print("\n=== TOP 30 종목 ===")
for i, r in enumerate(rows_sorted[:30], 1):
    print(f"{i:2d}. {r['종목명']:<30} {r['티커']:<15} {r['비중']:6.2f}%  {r['평가금_krw']:>15,.0f} KRW")

# 섹터 분류
sector_map = {
    "레버리지ETF": ["SOXL","TQQQ","NVDU","NVDX","NVDL","TSLL","DFEN","FAS","NVDW","MSTU"],
    "YieldMax옵션수익": ["NVDY","SNOY","NFLY","CONY","SMCY","MSTY","APLY","GPIQ","QYLD","JEPQ","ROBO"],
    "반도체": ["SOXX","NVDA","INTC","QCOM","AMD","TSM","ON","TXN","COHR"],
    "AI/빅테크": ["GOOGL","MSFT","META","AAPL","AMZN","PLTR","SOUN","BBAI","TEM","MNDY","HUBS","DDOG","PATH","ESTC","GTLB","U","TEAM","ADBE","INTU","EPAM"],
    "양자컴퓨팅": ["IONQ","QBTS","RGTI"],
    "우주/방산": ["RKLB","JOBY","AVAV","KTOS","GD","BAH","LHX","RTX"],
    "에너지": ["XOM","COP","MPC","VLO","OXY","EOG","KMI","PBR","PBR-A"],
    "채권ETF": ["TLT","TIP","VTIP","JPIE"],
    "배당/리츠": ["SCHD","ABBV","KO","JNJ","PG","MO","VZ","DUK","OHI","SPG","NLY","ORC","STWD","RC","ACRE","MFA"],
    "성장주": ["TSLA","NFLX","AMZN","DIS","SBUX","RBLX","GME","RIVN","OPEN","CHWY","UPWK","ASAN","MQ","LULU","RKT","GRAB"],
    "원자재ETF": ["GCC","OILK","COMT","FTGC","PDBC","KRBN","EWZ"],
    "국내주식": [],
    "국내ETF": [],
}

# 국내 분류
for r in rows:
    if r['티커'].endswith('.KS') or r['티커'].endswith('.KQ'):
        name = r['종목명']
        if any(x in name for x in ['RISE','TIGER','KODEX','KBSTAR','HANARO']):
            sector_map["국내ETF"].append(r['종목명'])
        else:
            sector_map["국내주식"].append(r['종목명'])

# 섹터별 합계
ticker_to_row = {r['티커']: r for r in rows}
name_to_row = {r['종목명']: r for r in rows}

sector_totals = {}
assigned = set()
for sector, tickers in sector_map.items():
    total = 0
    for t in tickers:
        r = ticker_to_row.get(t) or name_to_row.get(t)
        if r:
            total += r['평가금_krw']
            assigned.add(r['종목명'])
    sector_totals[sector] = total

# 미분류
unassigned = [r for r in rows if r['종목명'] not in assigned]
if unassigned:
    sector_totals["기타"] = sum(r['평가금_krw'] for r in unassigned)

print("\n=== 섹터별 비중 ===")
for sector, amount in sorted(sector_totals.items(), key=lambda x: -x[1]):
    pct = amount / total_krw * 100 if total_krw > 0 else 0
    print(f"{sector:<20} {amount:>15,.0f} KRW  ({pct:.1f}%)")

# 10x 후보 (소형주 & 성장 테마)
ten_x_candidates = {
    "IONQ": "양자컴퓨팅 선두주자, 시장 초기 단계",
    "RKLB": "민간 우주 발사 서비스 + 위성 제조, Neutron 로켓 개발 중",
    "QBTS": "D-Wave 양자 어닐링, 실용화 가장 앞선",
    "RGTI": "Rigetti 초전도 양자컴퓨터",
    "SOUN": "AI 음성 솔루션, 자동차/엔터프라이즈 침투",
    "BBAI": "방산 특화 AI, 정부 계약 증가",
    "KTOS": "드론/극초음속 미사일 방산 순수주",
    "AVAV": "군용 드론 1위, AeroVironment",
    "PLTR": "AI 데이터 분석, 정부+민간 확장 (이미 중대형)",
    "RIVN": "전기트럭 아마존 독점 계약, 흑자전환 기대",
    "JOBY": "eVTOL 도심항공모빌리티 선두",
    "TEM": "AI 헬스케어 데이터, Tempus AI",
    "CRCL": "스테이블코인/결제 규제 수혜 (Circle Internet)",
    "OPEN": "주택 매매 플랫폼, 금리 인하 수혜",
    "MNDY": "B2B SaaS 업무관리, 고성장",
}

print("\n=== 10x 후보 (현재 보유 중) ===")
for ticker, reason in ten_x_candidates.items():
    r = ticker_to_row.get(ticker)
    if r:
        print(f"{ticker:<8} 평가금: {r['평가금_krw']:>10,.0f} KRW  | {reason}")

print(f"\n총 종목 수: {len(rows)}")
print(f"10x 후보 (보유): {sum(1 for t in ten_x_candidates if t in ticker_to_row)}")
