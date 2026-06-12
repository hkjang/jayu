import yfinance as yf
import csv
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TICKER_MAP = {
    # ── 미국 ETF/종목 (영문 티커) ──
    "SOXL":"SOXL","SOXX":"SOXX","TQQQ":"TQQQ","HEWJ":"HEWJ",
    "NVDU":"NVDU","NVDX":"NVDX","AIBU":"AIBU","SPY":"SPY",
    "NVDL":"NVDL","QQQ":"QQQ","LRNZ":"LRNZ","XSW":"XSW",
    "GCC":"GCC","OILK":"OILK","EWZ":"EWZ","TSLL":"TSLL",
    "GPIQ":"GPIQ","SVXY":"SVXY","COMT":"COMT","FTGC":"FTGC",
    "SCHD":"SCHD","VTWO":"VTWO","QYLD":"QYLD","VTIP":"VTIP",
    "VOO":"VOO","ROBO":"ROBO","JEPQ":"JEPQ","TIP":"TIP",
    "RTX":"RTX","DFEN":"DFEN","TERG":"TERG","JPIE":"JPIE",
    "FAS":"FAS","IMVP":"IMVP","ARKG":"ARKG","BOTZ":"BOTZ",
    "PDBC":"PDBC","APLY":"APLY","BITC":"BITC","TLT":"TLT",
    "KRBN":"KRBN","NVDW":"NVDW","NVDY":"NVDY","SNOY":"SNOY",
    "NFLY":"NFLY","BITO":"BITO","IONX":"IONX","CONY":"CONY",
    "SMCY":"SMCY","MSTY":"MSTY","MSTU":"MSTU","FCVT":"FCVT",
    "IBM":"IBM",
    # ── 미국 종목 (한글 이름) ──
    "코히런트":"COHR","넷플릭스":"NFLX",
    "ASML홀딩(ADR)":"ASML","알파벳A":"GOOGL",
    "마라톤페트롤리움":"MPC","인텔":"INTC",
    "시스코시스템즈":"CSCO","TSMC(ADR)":"TSM",
    "월마트":"WMT","발레로에너지":"VLO",
    "데이터독":"DDOG","이튼":"ETN",
    "부킹홀딩스":"BKNG","팔란티어":"PLTR",
    "SK텔레콤(ADR)":"SKM","텍사스인스트루먼츠":"TXN",
    "모건스탠리":"MS","엑슨모빌":"XOM",
    "코스트코":"COST","킨더모건":"KMI",
    "오메가헬스케어인베스터스":"OHI","몽고DB":"MDB",
    "엔비디아":"NVDA","놋오프쇼어파트너스":"KNOP",
    "유니티그룹":"UNIT","비자":"V",
    "버크셔해서웨이B":"BRK-B","버크셔해서웨이A":"BRK-A",
    "테슬라":"TSLA","머크":"MRK",
    "마이크로소프트":"MSFT","페트로브라스(ADR)":"PBR",
    "메트라이프":"MET","알트리아그룹":"MO",
    "존슨앤존슨":"JNJ","애플":"AAPL",
    "뱅크오브아메리카":"BAC","코카콜라":"KO",
    "파가야테크놀로지스":"PGY","페트로브라스우선주(ADR)":"PBR-A",
    "코노코필립스":"COP","아이온큐":"IONQ",
    "오픈도어테크놀로지스":"OPEN","시그나그룹":"CI",
    "AT&T":"T","EOG리소시스":"EOG",
    "그랩홀딩스":"GRAB","사이먼프로퍼티그룹":"SPG",
    "로우스":"LOW","애브비":"ABBV",
    "듀크에너지":"DUK","스타벅스":"SBUX",
    "옥시덴탈페트롤리움":"OXY","바이두(ADR)":"BIDU",
    "스타벌크캐리어스":"SBLK","오토데스크":"ADSK",
    "트루이스트파이낸셜":"TFC","애널리캐피탈매니지먼트":"NLY",
    "포드":"F","아마존":"AMZN",
    "로켓랩":"RKLB","푸르덴셜파이낸셜":"PRU",
    "조비에비에이션":"JOBY","버라이즌":"VZ",
    "제너럴다이내믹스":"GD","부즈알렌해밀턴홀딩":"BAH",
    "P&G":"PG","L3해리스":"LHX",
    "온세미컨덕터":"ON","디즈니":"DIS",
    "제르다우(ADR)":"GGB","퀄컴":"QCOM",
    "도미노피자":"DPZ","아처대니얼스미들랜드":"ADM",
    "로켓컴퍼니스":"RKT","템퍼스AI":"TEM",
    "빅베어AI홀딩스":"BBAI","로블록스":"RBLX",
    "MFA파이낸셜":"MFA","엘라스틱":"ESTC",
    "스타우드프로퍼티":"STWD","펩시코":"PEP",
    "메타":"META","알버말":"ALB",
    "유나이티드헬스그룹":"UNH","센틴":"CNC",
    "버티브홀딩스":"VRT","슈퍼마이크로컴퓨터":"SMCI",
    "홈디포":"HD","사운드하운드AI":"SOUN",
    "츄이":"CHWY","게임스탑":"GME",
    "인튜이트":"INTU","먼데이닷컴":"MNDY",
    "에어로바이런먼트":"AVAV","디웨이브퀀텀":"QBTS",
    "오키드아일랜드캐피탈":"ORC","깃랩":"GTLB",
    "유아이패스":"PATH","크라토스디펜스앤시큐리티솔루션즈":"KTOS",
    "어도비":"ADBE","도세보":"DCBO",
    "허브스팟":"HUBS","리비안":"RIVN",
    "유니티소프트웨어":"U","업워크":"UPWK",
    "리게티컴퓨팅":"RGTI","아레스커머셜리얼에스테이트":"ACRE",
    "리튬아메리카스":"LAC","콘아그라브랜즈":"CAG",
    "써클인터넷그룹":"CRCL","나이키":"NKE",
    "불리쉬":"BULL","이팸시스템즈":"EPAM",
    "마르케타":"MQ","룰루레몬":"LULU",
    "아틀라시언":"TEAM","리튬아르헨티나AG":"LAAC",
    "아사나":"ASAN","레디캐피탈":"RC",
    # ── 국내 주식 (KRX) ──
    "삼성전자":"005930.KS","SNT홀딩스":"100840.KS",
    "삼지전자":"037460.KQ","우리금융지주":"316140.KS",
    "하나금융지주":"086790.KS","한국금융지주":"071050.KS",
    "신한지주":"055550.KS","BNK금융지주":"138930.KS",
    "기업은행":"024110.KS","DB증권":"016610.KS",
    "덕산하이메탈":"077360.KQ","펌텍코리아":"251970.KQ",
    "기아":"000270.KS","코오롱":"002020.KS",
    "엘앤에프":"066970.KQ","서부T&D":"006145.KS",
    "JYP Ent.":"035900.KQ","한국콜마":"161890.KS",
    "NAVER":"035420.KS","SK디스커버리":"006120.KS",
    "카카오뱅크":"323410.KQ",
    "RISE 미국나스닥100":"133690.KS",
    "TIGER 미국테크TOP10타겟커버드콜":"437080.KS",
    "이마트":"139480.KS","넥센우":"005725.KS",
    "KISCO홀딩스":"001390.KS","카카오페이":"377300.KQ",
    "RISE 미국S&P500":"360750.KS","세아제강":"306200.KS",
    "한일홀딩스":"003460.KS",
    "KODEX 삼성전자단일종목레버리지":"292150.KS",
    "메가스터디":"072870.KQ",
    "TIGER 미국배당다우존스타겟커버드콜2호":"458730.KS",
    "유니트론텍":"142210.KQ","코나아이":"052400.KQ",
    "카카오":"035720.KQ","더블유게임즈":"192080.KQ",
    "쿠쿠홀딩스":"192400.KS","와이지엔터테인먼트":"122870.KQ",
    "HL만도":"204320.KS","씨아이에스":"222080.KQ",
    "샘표":"007540.KS","한국알콜":"017890.KS",
    "헥토이노베이션":"234340.KQ","네오위즈":"095660.KQ",
    "다날":"064260.KQ","휴메딕스":"200130.KQ",
    "이지케어텍":"287410.KQ","IPARK현대산업개발":"012690.KS",
    "DSR":"155660.KS","하나투어":"039130.KQ",
    "BGF에코머티리얼즈":"027390.KS","쇼박스":"086980.KQ",
    "에피소드컴퍼니":"382800.KQ","위메이드":"112040.KQ",
    "샘표식품":"248170.KQ","현대바이오랜드":"052260.KQ",
    "배럴":"355150.KQ","넥써쓰":"085260.KQ",
    "키다리스튜디오":"020120.KQ","한온시스템":"018880.KS",
    "천보":"278280.KQ","시디즈":"134790.KQ",
    "소프트센":"032680.KQ","원익피앤이":"094820.KQ",
    "케어랩스":"263700.KQ","인크로스":"216050.KQ",
    "에스디바이오센서":"137310.KQ","뉴인텍":"012340.KS",
    "유틸렉스":"263050.KQ","뉴인텍 21R":"N/A",
}

rows = []
with open(os.path.join(BASE_DIR, 'toss_portfolio.csv'), encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(dict(r))

print(f"총 {len(rows)}개 종목 로드")

# 기존 컬럼 초기화
for r in rows:
    name = r['종목명']
    r['티커'] = TICKER_MAP.get(name, '?')

unmapped = [r['종목명'] for r in rows if r['티커'] == '?']
if unmapped:
    print(f"미매핑 종목: {unmapped}")

# 유효 티커만 수집
valid_tickers = list({r['티커'] for r in rows if r['티커'] not in ('?', 'N/A')})
print(f"{len(valid_tickers)}개 티커 가격 조회 중...")

# yfinance 조회
raw = yf.download(valid_tickers, period='5d', auto_adjust=True, progress=False)
prices = {}

if hasattr(raw.columns, 'levels'):
    # MultiIndex
    for t in valid_tickers:
        try:
            s = raw['Close'][t].dropna()
            if not s.empty:
                prices[t] = round(float(s.iloc[-1]), 4)
        except Exception:
            pass
else:
    try:
        s = raw['Close'].dropna()
        if not s.empty:
            prices[valid_tickers[0]] = round(float(s.iloc[-1]), 4)
    except Exception:
        pass

print(f"가격 조회 성공: {len(prices)}개 / 실패: {len(valid_tickers)-len(prices)}개")
failed = [t for t in valid_tickers if t not in prices]
if failed:
    print(f"실패 티커: {failed}")

KRW_SET = {t for t in valid_tickers if t.endswith('.KS') or t.endswith('.KQ')}

for r in rows:
    ticker = r['티커']
    qty = float(r['보유 수량'])
    if ticker in prices:
        price = prices[ticker]
        r['현재가'] = price
        r['평가금'] = round(price * qty, 2)
    else:
        r['현재가'] = ''
        r['평가금'] = ''
    r['통화'] = 'KRW' if ticker in KRW_SET else 'USD'

out = os.path.join(BASE_DIR, 'toss_portfolio.csv')
fieldnames = ['종목명','티커','보유 수량','현재가','평가금','통화']
with open(out, 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

usd_total = sum(float(r['평가금']) for r in rows if r['통화']=='USD' and r['평가금']!='')
krw_total = sum(float(r['평가금']) for r in rows if r['통화']=='KRW' and r['평가금']!='')
print(f"\n저장 완료: {out}")
print(f"해외 평가금 합계: ${usd_total:,.2f} USD")
print(f"국내 평가금 합계: {krw_total:,.0f} KRW")
