import yfinance as yf, csv, os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, 'toss_portfolio.csv')

# 리튬아르헨티나AG 후보: LAAC, LIAG, LAC (원래 회사)
# 이지케어텍 후보: 287410.KQ, 287410.KS, 030800.KQ
# 뉴인텍 21R: 신주인수권 - 기준가로 뉴인텍(012340) 주가 사용

candidates = {
    "리튬아르헨티나AG": ["LIAG", "LAAC", "LAC"],
    "이지케어텍": ["287410.KQ", "287410.KS", "030800.KQ", "064850.KQ"],
    "뉴인텍 21R": ["012340.KS"],   # 모주 주가로 대체
}

found = {}
for name, tickers in candidates.items():
    for t in tickers:
        try:
            d = yf.download(t, period='5d', auto_adjust=True, progress=False)
            if not d.empty:
                s = d['Close'].dropna()
                if not s.empty:
                    found[name] = (t, round(float(s.iloc[-1]), 4))
                    print(f"OK [{name}]: {t} = {found[name][1]}")
                    break
        except:
            pass
    if name not in found:
        print(f"FAIL [{name}]")

# CSV 업데이트
rows = []
with open(CSV_PATH, encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(dict(r))

for r in rows:
    name = r['종목명']
    if name in found and r['현재가'] == '':
        ticker, price = found[name]
        r['티커'] = ticker
        qty = float(r['보유 수량'])
        r['현재가'] = price
        r['평가금'] = round(price * qty, 2)
        r['통화'] = 'KRW' if ticker.endswith(('.KS','.KQ')) else 'USD'
        note = ' (모주 기준)' if name == '뉴인텍 21R' else ''
        print(f"Updated: {name} -> {ticker} / {price}{note}")

with open(CSV_PATH, 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['종목명','티커','보유 수량','현재가','평가금','통화'])
    writer.writeheader()
    writer.writerows(rows)

usd = sum(float(r['평가금']) for r in rows if r['통화']=='USD' and r['평가금']!='')
krw = sum(float(r['평가금']) for r in rows if r['통화']=='KRW' and r['평가금']!='')
no_price = [r['종목명'] for r in rows if r['현재가']=='']
print(f"\n해외 평가금: ${usd:,.2f} USD")
print(f"국내 평가금: {krw:,.0f} KRW")
print(f"가격 없음: {no_price}")
