"""
주요 주식 정보 수집 → 카카오톡 나에게 보내기
데이터: yfinance (한국+미국 지수), Massive API (보조)
"""

import requests
import yfinance as yf
from datetime import datetime

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

MASSIVE_API_KEY = ""
KAKAO_ACCESS_TOKEN = ""

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            MASSIVE_API_KEY = config.get("MASSIVE_API_KEY", "")
            KAKAO_ACCESS_TOKEN = config.get("KAKAO_ACCESS_TOKEN", "")
    except Exception as e:
        print(f"설정 파일 로드 실패: {e}")



def get_index(symbol):
    """지수 조회 (yfinance)"""
    try:
        fi = yf.Ticker(symbol).fast_info
        close = fi.last_price
        prev  = fi.previous_close
        if not prev or prev == 0:
            return {"value": close, "pct": 0.0}
        pct   = (close - prev) / prev * 100
        return {"value": close, "pct": pct}
    except Exception as e:
        return {"error": str(e)}


def get_massive_indices():
    """Massive API로 미국 지수 스냅샷 (yfinance 실패 시 대체)"""
    try:
        resp = requests.get(
            "https://api.massive.com/v3/snapshot/indices",
            params={"ticker": "I:SPX,I:NDX,I:DJI", "apiKey": MASSIVE_API_KEY},
            timeout=10,
        )
        result = {}
        for item in resp.json().get("results", []):
            label = {"I:SPX": "S&P500", "I:NDX": "NASDAQ", "I:DJI": "DOW"}.get(item["ticker"])
            if label:
                s = item.get("session", {})
                result[label] = {"value": item.get("value"), "pct": s.get("change_percent")}
        return result
    except Exception as e:
        print(f"Massive API 조회 실패: {e}")
        return {}


def fmt(name, data, decimals=0):
    if "error" in data or data.get("value") is None:
        return f"{name}: 조회실패"
    val = data["value"]
    pct = data.get("pct") or 0
    arrow = "▲" if pct >= 0 else "▼"
    val_str = f"{val:,.{decimals}f}"
    return f"{name}: {val_str} {arrow}{abs(pct):.2f}%"


def build_message():
    today = datetime.now().strftime("%Y.%m.%d")

    indices = {
        "KOSPI":  get_index("^KS11"),
        "KOSDAQ": get_index("^KQ11"),
        "DOW":    get_index("^DJI"),
        "S&P500": get_index("^GSPC"),
        "NASDAQ": get_index("^IXIC"),
        "VIX":    get_index("^VIX"),
    }

    # Massive API로 미국 지수 보강
    massive = get_massive_indices()
    for key in ["S&P500", "NASDAQ", "DOW"]:
        if "error" in indices.get(key, {"error": True}):
            if key in massive:
                indices[key] = massive[key]

    lines = [
        f"📊 주요 주식 ({today})",
        fmt("🇰🇷 KOSPI",  indices["KOSPI"]),
        fmt("🇰🇷 KOSDAQ", indices["KOSDAQ"]),
        fmt("🇺🇸 DOW",    indices["DOW"]),
        fmt("🇺🇸 S&P500", indices["S&P500"]),
        fmt("🇺🇸 NASDAQ", indices["NASDAQ"]),
    ]
    vix = indices.get("VIX", {})
    if "error" not in vix:
        lines.append(f"📉 VIX: {vix['value']:.2f}")

    return "\n".join(lines)


def send_kakao(message: str):
    # 토큰 유효성 검사 (한글 포함 여부 및 기본값 검사)
    if not KAKAO_ACCESS_TOKEN or "여기에" in KAKAO_ACCESS_TOKEN or any(ord(c) > 127 for c in KAKAO_ACCESS_TOKEN):
        raise ValueError("유효하지 않은 카카오 토큰입니다. config.json에서 KAKAO_ACCESS_TOKEN을 설정해주세요.")

    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {
        "Authorization": f"Bearer {KAKAO_ACCESS_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
    }
    template_obj = {
        "object_type": "text",
        "text": message,
        "link": {
            "web_url": "https://finance.naver.com",
            "mobile_web_url": "https://finance.naver.com"
        }
    }
    payload = {
        "template_object": json.dumps(template_obj, ensure_ascii=False)
    }
    resp = requests.post(url, headers=headers, data=payload, timeout=10)
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
    return resp.json()


if __name__ == "__main__":
    msg = build_message()
    print(msg)
    if KAKAO_ACCESS_TOKEN and "여기에" not in KAKAO_ACCESS_TOKEN:
        print("\n카카오 전송:", send_kakao(msg))
