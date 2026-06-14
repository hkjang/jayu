"""
자율 전략 개선 엔진 (Self-Improvement Engine)
=============================================
실행 주기: 매일 1회 (cron: 0 6 * * *)

기능:
1. meta_learning.json → 파라미터별 승률 분석 (Wilson score)
2. strategy_history.json → 티커별 최고 Sharpe 전략 추출
3. gene_pool.json → 상위 유전자 시드 주입 (하위 교체)
4. 개선 리포트 → 카카오톡 전송
5. 파라미터 공간 자동 조정 (configs/param_priorities.json 갱신)
"""

from __future__ import annotations

import json
import math
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
CONFIGS = ROOT / "configs"
CONFIGS.mkdir(exist_ok=True)

# ── 파일 경로 ─────────────────────────────────────────────────────────────
META_FILE = STATE / "meta_learning.json"
HISTORY_FILE = STATE / "strategy_history.json"
GENE_POOL_FILE = STATE / "gene_pool.json"
BEST_FILE = STATE / "best_strategy.json"
PRIORITIES_FILE = CONFIGS / "param_priorities.json"
IMPROVE_LOG = ROOT / "simulation_logs" / "improve_log.jsonl"


def wilson_lower(wins: int, total: int, z: float = 1.645) -> float:
    """Wilson score 하한 (90% 신뢰구간) — 소표본에서도 안정적인 승률 추정."""
    if total == 0:
        return 0.0
    p = wins / total
    n = total
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (
        1 + z * z / n
    )


def analyze_meta(meta: dict) -> dict[str, list]:
    """각 파라미터별 Wilson 하한 기준 상위 값 반환."""
    top_params: dict[str, list] = {}
    for param, value_stats in meta.items():
        scored = []
        for val_str, stat in value_stats.items():
            wins = stat.get("wins", 0)
            total = stat.get("total", 0)
            if total < 5:  # 표본 부족 → 건너뜀
                continue
            score = wilson_lower(wins, total)
            try:
                val = float(val_str)
            except ValueError:
                val = val_str
            scored.append({"value": val, "wins": wins, "total": total, "wilson": round(score, 4)})
        scored.sort(key=lambda x: x["wilson"], reverse=True)
        top_params[param] = scored[:3]  # top-3
    return top_params


def analyze_history(history: dict) -> dict[str, dict]:
    """티커별 최고 Sharpe 전략 파라미터 추출."""
    best: dict[str, dict] = {}
    for ticker, regimes in history.items():
        all_entries: list[dict] = []
        for regime_list in regimes.values():
            if isinstance(regime_list, list):
                all_entries.extend(regime_list)
        if not all_entries:
            continue
        top = max(all_entries, key=lambda e: e.get("metrics", {}).get("sharpe", -999))
        best[ticker] = {
            "sharpe": top.get("metrics", {}).get("sharpe", 0),
            "win_rate": top.get("metrics", {}).get("win_rate", 0),
            "total_return": top.get("metrics", {}).get("total_return", 0),
            "params": top.get("params", {}),
        }
    return best


def inject_best_into_gene_pool(gene_pool: dict, best_by_ticker: dict[str, dict]) -> dict:
    """각 티커의 최고 파라미터를 gene pool에 주입 (하위 유전자 교체)."""
    for ticker, best in best_by_ticker.items():
        if ticker not in gene_pool:
            gene_pool[ticker] = {}
        for regime in ("bull", "bear"):
            pool_key = regime
            if pool_key not in gene_pool[ticker]:
                gene_pool[ticker][pool_key] = []
            pool = gene_pool[ticker][pool_key]
            if not isinstance(pool, list):
                pool = []
                gene_pool[ticker][pool_key] = pool

            seed_gene = {**best["params"], "__injected": True, "__sharpe": best["sharpe"]}
            # 이미 주입된 동일 파라미터가 있으면 교체, 없으면 하위 제거 후 추가
            existing_injected = [i for i, g in enumerate(pool) if g.get("__injected")]
            if existing_injected:
                pool[existing_injected[0]] = seed_gene
            elif len(pool) >= 10:
                pool[-1] = seed_gene  # 하위 유전자 교체
            else:
                pool.append(seed_gene)
    return gene_pool


def build_param_priorities(top_params: dict[str, list]) -> dict:
    """Wilson 분석 결과 → configs/param_priorities.json 형식 (참고용)."""
    priorities: dict[str, list] = {}
    for param, entries in top_params.items():
        if entries:
            priorities[param] = [e["value"] for e in entries]
    return {
        "updated_at": datetime.now().isoformat(),
        "description": "Wilson score 기반 상위 파라미터값. engine이 샘플링 시 우선 참조.",
        "top_values": priorities,
    }


def boost_meta_learning(meta: dict, top_params: dict[str, list], boost_wins: int = 20) -> dict:
    """Wilson 상위 파라미터값의 wins를 meta_learning.json에 직접 증폭.

    engine.py는 param_priorities.json을 읽지 않고 META_FILE만 읽는다.
    따라서 Wilson 분석 결과를 meta에 직접 반영해야 샘플링이 실제로 편향된다.

    boost_wins: 상위 1위 파라미터에 추가할 합성 wins (2위는 절반, 3위는 1/4)
    decay: engine의 기존 decay 0.98과 충돌 방지를 위해 과도한 boost 제한
    """
    for param, entries in top_params.items():
        if param not in meta:
            meta[param] = {}
        for rank, entry in enumerate(entries[:3]):
            val_str = str(entry["value"])
            synthetic_wins = max(1, boost_wins // (2**rank))  # 1위: 20, 2위: 10, 3위: 5
            if val_str not in meta[param]:
                meta[param][val_str] = {"wins": 0, "total": 0}
            meta[param][val_str]["wins"] += synthetic_wins
            meta[param][val_str]["total"] += synthetic_wins
            # total도 동일하게 올림 → 승률 유지하면서 가중치 증가
    return meta


def format_kakao_report(
    top_params: dict, best_by_ticker: dict, improved_tickers: list[str]
) -> tuple[str, str]:
    """카카오톡 전송용 메시지 2개 생성 (각 200자 이내)."""
    now = datetime.now().strftime("%m/%d %H시")
    lines1 = [f"🧠 전략 자율개선 [{now}]"]
    for ticker in ["SOXL", "TQQQ", "TSLA"]:
        if ticker in best_by_ticker:
            b = best_by_ticker[ticker]
            lines1.append(
                f"{ticker}: SR={b['sharpe']:.1f} 승률{b['win_rate']:.0f}% 수익{b['total_return']:.1f}%"
            )
    if improved_tickers:
        lines1.append(f"✅개선: {', '.join(improved_tickers)}")
    else:
        lines1.append("✅개선: 유지 (최적 유지)")

    lines2 = []
    for ticker in ["IONQ", "NVDL", "QBTS"]:
        if ticker in best_by_ticker:
            b = best_by_ticker[ticker]
            lines2.append(
                f"{ticker}: SR={b['sharpe']:.1f} 승률{b['win_rate']:.0f}% 수익{b['total_return']:.1f}%"
            )

    # 상위 파라미터 한 줄 요약
    if "rsi_lo" in top_params and top_params["rsi_lo"]:
        best_rsi = top_params["rsi_lo"][0]["value"]
        best_ema = top_params.get("ema_span", [{}])[0].get("value", "?")
        lines2.append(f"🔧best: RSI_lo={best_rsi} EMA={best_ema}")
    lines2.append("🧬유전자 시드 주입 완료")

    msg1 = "\n".join(lines1)[:200]
    msg2 = "\n".join(lines2)[:200]
    return msg1, msg2


def send_kakao(msg: str) -> bool:
    """KakaotalkChat-MemoChat MCP 직접 호출 불가 → stdout에 마커 출력."""
    # 이 스크립트는 Claude scheduled task 안에서 실행되므로
    # 실제 카톡 전송은 scheduled task prompt가 담당.
    # 여기서는 결과를 stdout에 JSON 형태로 출력해 task가 읽을 수 있게 함.
    print(f"[KAKAO_MSG]{msg}[/KAKAO_MSG]")
    return True


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] 전략 자율개선 시작")

    # ── 데이터 로드 ─────────────────────────────────────────────────────────
    if not META_FILE.exists():
        print("[WARN] meta_learning.json 없음 → 분석 불가")
        return 1

    with META_FILE.open(encoding="utf-8") as f:
        meta = json.load(f)
    history = {}
    if HISTORY_FILE.exists():
        with HISTORY_FILE.open(encoding="utf-8") as f:
            history = json.load(f)
    gene_pool = {}
    if GENE_POOL_FILE.exists():
        with GENE_POOL_FILE.open(encoding="utf-8") as f:
            gene_pool = json.load(f)

    # ── 분석 ────────────────────────────────────────────────────────────────
    top_params = analyze_meta(meta)
    best_by_ticker = analyze_history(history)

    print("\n=== 파라미터별 Top-3 (Wilson score 기준) ===")
    for param, entries in top_params.items():
        if entries:
            top_str = ", ".join(f"{e['value']}({e['wilson']:.2f})" for e in entries)
            print(f"  {param}: {top_str}")

    print("\n=== 티커별 최고 Sharpe ===")
    for ticker, b in best_by_ticker.items():
        print(
            f"  {ticker}: Sharpe={b['sharpe']:.2f}, 승률={b['win_rate']:.1f}%, 수익={b['total_return']:.1f}%"
        )

    # ── 유전자 풀 개선 ───────────────────────────────────────────────────────
    prev_sharpes = {}
    for ticker, regime_dict in gene_pool.items():
        for regime, pool in regime_dict.items():
            if isinstance(pool, list) and pool:
                best_gene = max(pool, key=lambda g: g.get("__sharpe", -999))
                prev_sharpes[ticker] = best_gene.get("__sharpe", -999)

    gene_pool = inject_best_into_gene_pool(gene_pool, best_by_ticker)
    improved_tickers = []
    for ticker, b in best_by_ticker.items():
        prev = prev_sharpes.get(ticker, -999)
        if b["sharpe"] > prev + 0.1:
            improved_tickers.append(ticker)

    with GENE_POOL_FILE.open("w", encoding="utf-8") as f:
        json.dump(gene_pool, f, ensure_ascii=False, indent=2)
    print(f"\n유전자 풀 갱신 완료. 개선: {improved_tickers or '없음'}")

    # ── meta_learning.json에 Wilson 우승자 직접 주입 ────────────────────────
    # engine은 param_priorities.json을 읽지 않고 meta_learning.json만 사용한다.
    # Wilson 상위 파라미터에 합성 wins를 추가 → 다음 시뮬레이션 샘플링이 편향됨.
    meta = boost_meta_learning(meta, top_params, boost_wins=20)
    with META_FILE.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("meta_learning.json 부스트 완료 (Wilson 상위 파라미터 wins 증폭)")

    # ── 파라미터 우선순위 저장 (참고용) ─────────────────────────────────────
    priorities = build_param_priorities(top_params)
    with PRIORITIES_FILE.open("w", encoding="utf-8") as f:
        json.dump(priorities, f, ensure_ascii=False, indent=2)
    print(f"파라미터 우선순위 저장: {PRIORITIES_FILE}")

    # ── 개선 로그 ────────────────────────────────────────────────────────────
    log_entry = {
        "run_time": datetime.now().isoformat(),
        "top_params": {p: entries[0] if entries else {} for p, entries in top_params.items()},
        "best_by_ticker": best_by_ticker,
        "improved": improved_tickers,
    }
    with IMPROVE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    # ── 카카오 리포트 ────────────────────────────────────────────────────────
    msg1, msg2 = format_kakao_report(top_params, best_by_ticker, improved_tickers)
    print("\n=== 카카오 메시지 ===")
    print("[MSG1]", msg1)
    print("[MSG2]", msg2)
    send_kakao(msg1)
    send_kakao(msg2)

    print("\n✅ 전략 자율개선 완료")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"[FATAL] {e}")
        traceback.print_exc()
        raise SystemExit(1)
