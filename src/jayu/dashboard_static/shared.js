const STATUS_LABELS = {
  success: "성공",
  warning: "경고",
  failed: "실패",
  blocked: "차단",
  validating: "검증 중",
  data_error: "데이터 오류",
  not_evaluated: "미검증",
  pass: "통과",
  eligible: "승인 후보",
  hold: "대기",
};

const ACTION_QUEUE_STATUS_LABELS = {
  new: "신규",
  reviewing: "확인 중",
  deferred: "보류",
  done: "완료",
  ignored: "무시",
};

const ACTION_TYPE_LABELS = {
  data_check: "데이터 확인",
  risk_review: "리스크 점검",
  buy_review: "매수 검토",
  sell_review: "매도 검토",
  dividend_review: "배당 점검",
  order_prepare: "주문 준비",
  broker_warning: "매수 유의",
};

const RECONCILIATION_ISSUE_LABELS = {
  unmapped: "매핑 미등록",
  missing_type: "운용 타입 미지정",
  missing_sector: "섹터 미지정",
  overweight: "한도 초과",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const TICKER_DESCRIPTIONS = {
  "SOXL": "Direxion Daily Semiconductor Bull 3X ETF (필라델피아 반도체 지수 일간 변동성의 3배 추종 레버리지 ETF)",
  "TQQQ": "ProShares UltraPro QQQ ETF (나스닥 100 지수 일간 변동성의 3배 추종 레버리지 ETF)",
  "TSLA": "Tesla, Inc. (글로벌 1위 전기차 제조 및 자율주행, AI, 태양광 에너지 솔루션 선도 혁신 기업)",
  "IONQ": "IonQ, Inc. (트랩트 이온 기술 기반 양자 컴퓨터 하드웨어 및 클라우드 서비스 공급 글로벌 리더)",
  "NVDL": "GraniteShares 2x Long NVIDIA Daily ETF (엔비디아 단일 주식 일간 수익률의 2배를 추종하는 레버리지 ETF)",
  "QBTS": "D-Wave Quantum Inc. (상용화된 양자 아닐링 컴퓨터 시스템 및 하드웨어, 클라우드 소프트웨어 솔루션 공급 기업)",
  "005930.KS": "삼성전자 (글로벌 메모리 반도체 1위 및 파운드리, 스마트폰, 디스플레이 선도 한국 대표 기업)",
  "DFEN": "Direxion Daily Aerospace & Defense Bull 3X ETF (미국 항공우주 및 방위산업 지수의 3배를 추종하는 레버리지 ETF)",
  "FAS": "Direxion Daily Financial Bull 3X ETF (미국 대형 금융기관 및 은행주 지수의 3배를 추종하는 레버리지 ETF)",
  "MSTU": "Direxion Daily MicroStrategy Bull 2X ETF (마이크로스트레티지 주식 일간 변동성의 2배를 추종하는 고레버리지 ETF)",
  "NVDA": "NVIDIA Corporation (글로벌 AI 가속기 및 GPU 설계 1위 반도체 기업, AI 가속 컴퓨팅 생태계 주도)",
  "NVDU": "Direxion Daily NVDA Bull 2X ETF (엔비디아 단일 주식 일간 변동성의 2배를 추종하는 레버리지 ETF)",
  "NVDW": "GraniteShares 1.5x Long NVDA Daily ETF (엔비디아 단일 주식 일간 변동성의 1.5배를 추종하는 레버리지 ETF)",
  "NVDX": "GraniteShares 2x Long NVIDIA Daily ETF / YieldMax 2배 레버리지 (엔비디아의 2배 변동성을 목표로 하는 레버리지 상품)",
  "MSTX": "Defiance Daily Target 1.75X Long MSTR ETF (마이크로스트레티지 주식 일간 변동성의 1.75배를 추종하는 레버리지 ETF)",
  "AAPL": "Apple Inc. (아이폰, 아이패드, 맥 등 혁신 하드웨어 및 서비스 생태계를 갖춘 글로벌 테크 선도 기업)",
  "MSFT": "Microsoft Corporation (글로벌 소프트웨어 1위 및 Azure 클라우드, OpenAI 협력 기반 생성형 AI 시장 리더)",
  "AMZN": "Amazon.com, Inc. (글로벌 최대 이커머스 쇼핑 플랫폼 및 AWS 클라우드 인프라 시장 점유율 1위 기업)",
  "GOOGL": "Alphabet Inc. (구글 검색 엔진, 유튜브, 안드로이드 운영체제 및 AI Gemini 모델을 보유한 테크 거인)",
  "META": "Meta Platforms, Inc. (페이스북, 인스타그램, 왓츠앱 등 글로벌 SNS 채널 및 메타버스, AI 인프라 선도 기업)"
};

function renderTicker(ticker) {
  if (!ticker) return "-";
  const cleanTicker = String(ticker).trim().toUpperCase();
  const desc = TICKER_DESCRIPTIONS[cleanTicker];
  if (desc) {
    return `<span class="ticker-tooltip-trigger" data-ticker="${escapeHtml(cleanTicker)}" data-desc="${escapeHtml(desc)}">${escapeHtml(ticker)}</span>`;
  }
  return escapeHtml(ticker);
}

function statusClass(status) {
  return String(status || "not_evaluated").replaceAll("_", "-");
}

function statusBadge(status, prefix = "") {
  const source = status || "not_evaluated";
  const normalized = {
    pass: "success",
    eligible: "success",
    hold: "not_evaluated",
    fail: "failed",
    review: "warning",
  }[source] || source;
  const label = STATUS_LABELS[source] || STATUS_LABELS[normalized] || source;
  return `<span class="status-label status-${statusClass(normalized)}">${escapeHtml(
    prefix ? `${prefix} ${label}` : label
  )}</span>`;
}

function publicationStatusLabel(status) {
  return {
    published: "출판 완료",
    blocked: "차단됨",
    missing: "기록 없음",
    failed: "실패",
    pending: "대기",
  }[status] || status || "기록 없음";
}

function formatDate(value) {
  if (!value) return "미기록";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "미계산";
  return Number(value).toLocaleString("ko-KR", { maximumFractionDigits: digits });
}

function formatPercent(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "미검증";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function formatMoney(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "미계산";
  return Number(value).toLocaleString("ko-KR", { maximumFractionDigits: digits });
}

function formatCurrency(value, currency = "KRW") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "미계산";
  const digits = currency === "KRW" ? 0 : 2;
  return `${Number(value).toLocaleString("ko-KR", { maximumFractionDigits: digits })} ${currency}`;
}

function shortHash(value) {
  return value ? String(value).slice(0, 8) : "-";
}

const PAGE_DATA_SOURCES = {
  overview: ["run_evidence.json", "run manifest", "safety_verdict.json", "health report", "today_signals sidecar", "failure_patterns.json"],
  "data-quality": ["data_lineage.json", "data_sources.json", "provider_disagreement_report.json", "OHLCV provider cache"],
  risk: ["risk report", "portfolio_mapping.json", "portfolio.csv", "Toss holdings snapshot"],
  signals: ["today_signals.json", "signal sidecar", "data quality gate", "risk gate"],
  "trader-lens": ["signals artifact", "risk gate", "provider trust map", "safety verdict"],
  promotion: ["promotion state", "shadow run history", "health report", "signal history"],
  settings: ["config.json", ".env / environment", "provider policy", "survivorship audit"],
  "toss-account": ["Toss Open API GET", "accounts", "holdings", "exchange-rate", "portfolio_mapping.json"],
  toss: ["Toss Open API GET", "prices", "stocks", "warnings", "market calendar"],
  "api-monitoring": ["provider audit", "events.jsonl", "cache directories", "latest run artifacts"],
  analysis: ["Yahoo Finance", "FRED", "TradingView scanner", "TradingView news-mediator", "Toss Open API", "run artifacts"],
  "portfolio-hub": ["portfolio_mapping.json", "yfinance price history", "derived indicators"],
  autotrading: ["autotrading safety gates", "operational run lock", "Toss API config"],
  "simulation-log": ["cli execute simulate", "events.jsonl", "VIX & Index benchmark"],
  "run-history": ["run_evidence.json", "api list runs", "manifest.json", "safety_verdict.json", "risk_explanation.json", "events.jsonl per run_id"],
};

const METRIC_DATA_SOURCE_BY_PAGE = {
  overview: {
    "데이터 검증": "data_sources.json · provider_disagreement_report.json",
    "리스크 게이트": "risk report · portfolio.csv",
    "생존편향 정책": "survivorship audit",
    "Shadow 승격": "promotion state · shadow run history",
    "오늘의 신호": "today_signals.json · signal sidecar",
    Health: "health report",
    "세션 리플레이": "session_replay.json · latest run artifacts",
    "복구 가이드": "safety_verdict.json · latest run manifest · operational_status.json",
    "반복 실패": "failure_patterns.json · runs/*/manifest.json",
    "연속 차단": "failure_patterns.json · safety_verdict.json",
    "증거 완성도": "run_evidence.json · run artifact existence checks",
    "필수 증거": "run_evidence.json · required artifacts",
    "누락 증거": "run_evidence.json · filesystem existence checks",
    "경고 증거": "run_evidence.json · optional/warning artifacts",
    __default: "latest run manifest",
  },
  "data-quality": {
    "계보 노드": "data_lineage.json · latest run artifacts",
    "계보 연결": "data_lineage.json · provider/artifact/process edges",
    "누락 산출물": "data_lineage.json · filesystem existence checks",
    "차단 게이트": "data_lineage.json · risk/safety/process nodes",
    "검증 성공률": "data_sources.json",
    "Provider 수": "provider audit config · data_sources.json",
    불일치: "provider_disagreement_report.json",
    "차단 ticker": "provider_disagreement_report.json",
    "Provider 실패": "data_sources.json",
    상태: "data quality summary",
    __default: "data quality artifacts",
  },
  risk: {
    "승인 신호": "risk report",
    "차단 신호": "risk report",
    대기: "risk report",
    "실패 게이트": "risk gate details",
    "최상위 사유": "risk report reason counts",
    "판정 상태": "risk report summary",
    __default: "risk report",
  },
  signals: {
    "출판 상태": "signal sidecar",
    "검토 가능 매수": "today_signals.json · risk gate",
    "차단 매수": "today_signals.json · risk gate",
    대기: "today_signals.json",
    "데이터 검증": "today_signals.json · data quality gate",
    "신호 hash": "signal sidecar",
    __default: "today_signals.json",
  },
  "trader-lens": {
    "Avg reward/risk": "signal ladder artifact",
    "Signals reviewed": "today_signals.json",
    "Eligible / blocked": "risk gate",
    "Provider issues": "provider trust map",
    "Risk issues": "risk concentration",
    Controls: "dashboard policy",
    __default: "run-local review artifacts",
  },
  promotion: {
    "Shadow 일수": "shadow run history",
    "완료 신호": "signal history",
    "데이터 성공률": "promotion metrics",
    불일치율: "provider disagreement metrics",
    "리스크 통과율": "risk gate history",
    "신호 안정성": "signal history",
    __default: "promotion state",
  },
  settings: {
    "차단 규칙": "settings validation rules",
    경고: "settings validation rules",
    "Provider 점검": "provider policy audit",
    생존편향: "survivorship audit",
    승격: "promotion audit",
    비밀값: ".env / environment presence check",
    __default: "config.json · environment",
  },
  "toss-account": {
    계좌: "Toss Open API accounts GET",
    "총 평가금액(KRW)": "Toss holdings GET · exchange-rate GET",
    "평가손익(KRW)": "Toss holdings GET · exchange-rate GET",
    "USD/KRW": "Toss exchange-rate GET",
    "FX 당일효과": "Toss holdings GET · Toss prices GET · Toss exchange-rate GET",
    "계좌 변화": "account_attribution.json · Toss portfolio snapshots",
    "조회 실패": "Toss account section status",
    OrderIntent: "order_plan.json · jayu.paper_trading",
    OrderPlan: "order_plan.json · today_signals.json · jayu.paper_trading",
    OrderApproval: "order_plan.json · manual approval policy",
    "자금 배분": "allocation_preview.json · order_plan.json · holdings JSON",
    __default: "Toss holdings GET",
  },
  toss: {
    "API 키": "environment variable presence check",
    Secret: "environment variable presence check",
    계좌: "environment / selected Toss account",
    "GET 엔드포인트": "TOSS_GET_ENDPOINTS registry",
    "계좌 필요 API": "TOSS_GET_ENDPOINTS registry",
    "POST 요청": "dashboard read-only policy",
    "조회 종목": "Toss symbol normalization",
    "성공 섹션": "Toss market snapshot GET results",
    "실패 섹션": "Toss market snapshot GET results",
    "계좌 섹션": "Toss account-scoped GET results",
    "Read-only": "dashboard read-only policy",
    "다음 행동": "Toss snapshot summary",
    __default: "Toss Open API GET",
  },
  "api-monitoring": {
    "전체 Provider": "provider registry",
    "자격증명 설정": "environment / config presence check",
    "활성 Provider": "config.json provider settings",
    실패: "latest run API logs",
    불일치: "provider disagreement report",
    "알림 실패": "notification logs",
    __default: "API monitoring artifacts",
  },
  "run-history": {
    "반복 실패": "failure_patterns.json · runs/*/manifest.json",
    "연속 차단": "failure_patterns.json · latest completed runs",
    "실패 실행": "runs/*/manifest.json",
    "최다 코드": "failure_patterns.json · safety_verdict.json · risk_explanation.json",
    "증거 완성도": "run_evidence.json · active run artifacts",
    "필수 증거": "run_evidence.json · required artifacts",
    "누락 증거": "run_evidence.json · filesystem existence checks",
    "경고 증거": "run_evidence.json · warning artifacts",
    __default: "runs/*/manifest.json",
  },
};

function renderSourceLabel(source, className = "data-source-inline") {
  const text = Array.isArray(source) ? source.filter(Boolean).join(" · ") : String(source || "").trim();
  if (!text) return "";
  return `<span class="${className}">출처: ${escapeHtml(text)}</span>`;
}

function renderSourceCaption(source) {
  return renderSourceLabel(source, "data-source-caption");
}

function metricSourceFor(label) {
  const sources = METRIC_DATA_SOURCE_BY_PAGE[state.page] || {};
  return sources[label] || sources.__default || "";
}

function renderDataSourceNote(page, extra = []) {
  const seen = new Set();
  const sources = [...(PAGE_DATA_SOURCES[page] || []), ...extra]
    .map((item) => String(item || "").trim())
    .filter((item) => item && !seen.has(item) && seen.add(item));
  if (!sources.length) return "";
  return `<p class="metric-detail data-source-note" style="margin:6px 0 14px;color:var(--muted);font-size:11px;line-height:1.4">데이터 출처 · Data sources: ${sources.map(escapeHtml).join(" · ")}</p>`;
}

function renderMetricDictionaryStrip(entries, title = "지표 쉬운 설명") {
  const items = (entries || []).filter(Boolean);
  if (!items.length) return "";
  return `
    <section class="metric-help-panel" aria-label="${escapeHtml(title)}">
      <div class="metric-help-header">
        <strong>${escapeHtml(title)}</strong>
        <span>표시명 · 쉬운 설명 · 좋은 값 · 주의할 점</span>
      </div>
      <div class="metric-help-grid">
        ${items.map((item) => `
          <article class="metric-help-card">
            <div class="metric-help-title">
              <strong>${escapeHtml(item.label || item.key || "-")}</strong>
              <span>${escapeHtml(item.plain_name || "")}</span>
            </div>
            <p>${escapeHtml(item.short_description || "")}</p>
            <dl>
              <div><dt>좋은 값</dt><dd>${escapeHtml(item.good_value || "-")}</dd></div>
              <div><dt>주의</dt><dd>${escapeHtml(item.watch_out || "-")}</dd></div>
            </dl>
            ${renderSourceLabel(item.source || "src/jayu/metric_dictionary.py")}
          </article>
        `).join("")}
      </div>
    </section>`;
}

function compactJson(value) {
  const text = JSON.stringify(value ?? null);
  return text.length > 420 ? `${text.slice(0, 420)}...` : text;
}

function emptyTable(title, detail) {
  return `<div class="empty-state"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>`;
}

function ratioValue(left, right) {
  return right ? `${left}/${right}` : "미검증";
}

function gateRatio(approved, blocked) {
  const total = approved + blocked;
  return total ? approved / total : null;
}

function formatBoolean(value) {
  if (value === true) return "포함";
  if (value === false) return "미포함";
  return "미검증";
}

function dataQualityHeadline(summary) {
  if (summary.status === "not_evaluated") return "비교 가능한 가격 데이터가 없어 검증 성공으로 간주하지 않습니다.";
  if (summary.disagreement_count) return `${summary.disagreement_count}건의 provider disagreement가 기록됐습니다. 영향 ticker는 운영 신호에서 차단됩니다.`;
  if (summary.failed_source_count) return `${summary.failed_source_count}개 provider 수집이 실패했습니다.`;
  return "가격 provider 교차 검증이 허용 범위 안에서 완료됐습니다.";
}

function riskHeadline(summary) {
  if (summary.status === "not_evaluated") return "리스크 검증 근거가 없어 운영 승인으로 간주하지 않습니다.";
  if (summary.blocked_count) return `승인 ${summary.approved_count}개, 차단 ${summary.blocked_count}개입니다. 상위 차단 사유를 먼저 확인하세요.`;
  return `${summary.approved_count}개 신호가 리스크 게이트를 통과했습니다.`;
}

function traderLensHeadline(summary) {
  if (summary.status === "data_error") return "Provider disagreement or failed source blocks trader review.";
  if (summary.status === "blocked") return "Risk gate blockers are concentrated in the selected run.";
  if (summary.status === "success") return "Signals have reviewable reward/risk and no top blockers.";
  return "Trader Lens needs a completed run with signal and data artifacts.";
}

function tossAccountHeadline(data, summary) {
  if (data.status === "missing_credentials") return "Toss API 키 설정이 필요합니다.";
  if (data.status === "no_accounts") return "조회 가능한 Toss 계좌가 없습니다.";
  if (data.status === "failed") return `Toss 계좌 조회에 실패했습니다: ${data.error || "이유 알 수 없음"}`;
  if (summary.failed_section_count) return "일부 계좌 GET 조회가 실패했습니다.";
  return `${summary.holding_count || 0}개 보유 종목을 첫 계좌 기준으로 조회했습니다.`;
}

// Global Ticker Tooltip System
(function() {
  const globalTooltip = document.createElement("div");
  globalTooltip.className = "global-ticker-tooltip";
  document.body.appendChild(globalTooltip);

  const hideTooltip = () => {
    globalTooltip.classList.remove("visible");
    globalTooltip.style.display = "none";
  };

  document.addEventListener("mouseover", (event) => {
    const trigger = event.target.closest(".ticker-tooltip-trigger");
    if (!trigger) return;

    const ticker = trigger.dataset.ticker;
    const desc = trigger.dataset.desc;
    if (!ticker || !desc) return;

    globalTooltip.innerHTML = `<strong>${escapeHtml(ticker)}</strong>${escapeHtml(desc)}`;
    globalTooltip.style.display = "block";

    const rect = trigger.getBoundingClientRect();
    const tooltipWidth = globalTooltip.offsetWidth || 280;
    const tooltipHeight = globalTooltip.offsetHeight || 60;

    let left = rect.left + window.scrollX + (rect.width - tooltipWidth) / 2;
    let top = rect.top + window.scrollY - tooltipHeight - 8;

    // Keep on screen horizontally
    if (left < 10) {
      left = 10;
    } else if (left + tooltipWidth > window.innerWidth - 10) {
      left = window.innerWidth - tooltipWidth - 10;
    }

    // Keep on screen vertically (place below if it overflows above top of page)
    if (rect.top - tooltipHeight - 8 < 10) {
      top = rect.bottom + window.scrollY + 8;
    }

    globalTooltip.style.left = `${left}px`;
    globalTooltip.style.top = `${top}px`;

    requestAnimationFrame(() => {
      globalTooltip.classList.add("visible");
    });
  });

  document.addEventListener("mouseout", (event) => {
    const trigger = event.target.closest(".ticker-tooltip-trigger");
    if (!trigger) return;

    const related = event.relatedTarget ? event.relatedTarget.closest(".ticker-tooltip-trigger") : null;
    if (related === trigger) return;

    hideTooltip();
  });

  document.addEventListener("scroll", hideTooltip, { capture: true, passive: true });
})();

function metricCard(label, value, status, detail, ratio = null, source = null) {
  const width = ratio == null ? 0 : Math.max(0, Math.min(100, Number(ratio) * 100));
  const resolvedSource = source === null ? metricSourceFor(label) : source;
  return `
    <article class="metric-card">
      <div class="metric-label"><span>${escapeHtml(label)}</span>${statusBadge(status)}</div>
      <strong class="metric-value">${escapeHtml(value)}</strong>
      <span class="metric-detail">${escapeHtml(detail || "")}</span>
      ${renderSourceLabel(resolvedSource)}
      ${ratio == null ? "" : `<div class="metric-bar" aria-hidden="true"><span style="width:${width}%"></span></div>`}
    </article>
  `;
}

