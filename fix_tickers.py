import csv
import os

import yfinance as yf

from jayu.yahoo import get_yahoo_session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "toss_portfolio.csv")

# 대안 티커 시도
alt_map = {
    "LAAC": ["LIAG", "LAAC"],  # 리튬아르헨티나AG
    "066970.KQ": ["066970.KS", "066970.KQ"],  # 엘앤에프
    "006145.KS": ["006730.KS", "006145.KS"],  # 서부T&D
    "287410.KQ": ["287410.KS", "287410.KQ"],  # 이지케어텍
    "027390.KS": ["455900.KS", "027390.KS"],  # BGF에코머티리얼즈
    "085260.KQ": ["085260.KS", "356860.KQ"],  # 넥써쓰
}

# 이름 -> 현재 티커 매핑
name_to_ticker = {
    "리튬아르헨티나AG": "LAAC",
    "엘앤에프": "066970.KQ",
    "서부T&D": "006145.KS",
    "이지케어텍": "287410.KQ",
    "BGF에코머티리얼즈": "027390.KS",
    "넥써쓰": "085260.KQ",
}

fixes = {}
for old_ticker, candidates in alt_map.items():
    for cand in candidates:
        try:
            d = yf.download(
                cand,
                period="5d",
                auto_adjust=True,
                progress=False,
                session=get_yahoo_session(),
            )
            if not d.empty and not d["Close"].dropna().empty:
                price = float(d["Close"].dropna().iloc[-1])
                fixes[old_ticker] = (cand, round(price, 4))
                print(f"OK: {old_ticker} -> {cand} = {price:.4f}")
                break
        except Exception:
            pass
    else:
        print(f"FAIL: {old_ticker}")

# CSV 업데이트
rows = []
with open(CSV_PATH, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(dict(r))

name_to_old = {v: k for k, v in name_to_ticker.items()}
KRW_SUFFIXES = (".KS", ".KQ")

for r in rows:
    old_t = r["티커"]
    if old_t in fixes:
        new_t, price = fixes[old_t]
        r["티커"] = new_t
        qty = float(r["보유 수량"])
        r["현재가"] = price
        r["평가금"] = round(price * qty, 2)
        r["통화"] = "KRW" if new_t.endswith(KRW_SUFFIXES) else "USD"
        print(f"Updated: {r['종목명']} -> {new_t} / {price}")

with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(
        f, fieldnames=["종목명", "티커", "보유 수량", "현재가", "평가금", "통화"]
    )
    writer.writeheader()
    writer.writerows(rows)

usd = sum(float(r["평가금"]) for r in rows if r["통화"] == "USD" and r["평가금"] != "")
krw = sum(float(r["평가금"]) for r in rows if r["통화"] == "KRW" and r["평가금"] != "")
no_price = [r["종목명"] for r in rows if r["현재가"] == ""]
print(f"\n최종 해외 평가금: ${usd:,.2f} USD")
print(f"최종 국내 평가금: {krw:,.0f} KRW")
print(f"가격 없음: {no_price}")
