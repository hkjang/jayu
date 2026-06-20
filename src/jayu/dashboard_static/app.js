const state = {
  page: localStorage.getItem("jayu.dashboard.activePage") || "overview",
  runId: "latest",
  runs: [],
  decision: null,
  overview: null,
  dataQuality: null,
  risk: null,
  signals: null,
  traderLens: null,
  promotion: null,
  settingsValidation: null,
  tossStatus: null,
  tossAccounts: null,
  tossMarket: null,
  tossPortfolio: null,
  tossReconciliation: null,
  tossOrderPlan: null,
  tossSubTab: localStorage.getItem("jayu.toss.subTab") || "overview",
  apiMonitoring: null,
  tossAccountRegion: localStorage.getItem("jayu.toss.accountRegion") || "ALL",
  selectedTossAccount: localStorage.getItem("jayu.toss.selectedAccount") || "",
  apiMonitoringRefreshSec: localStorage.getItem("jayu.apiMonitoring.refresh") || "off",
  autoRefreshTimer: null,
  analysis: null,
  analysisTicker: localStorage.getItem("jayu.analysis.ticker") || "SOXL",
  analysisMacro: localStorage.getItem("jayu.analysis.macro") || "FEDFUNDS",
  analysisPeriod: localStorage.getItem("jayu.analysis.period") || "1y",
  analysisTab: "market",
  analysisMarketOverview: null,
  analysisTechnical: null,
  analysisCompare: null,
  analysisPortfolio: null,
  analysisCalendar: null,
};

const els = {
  root: document.querySelector("#page-root"),
  loading: document.querySelector("#loading-state"),
  error: document.querySelector("#error-state"),
  errorMessage: document.querySelector("#error-message"),
  liveRegion: document.querySelector("#live-region"),
  runSelector: document.querySelector("#run-selector"),
  modeBadge: document.querySelector("#mode-badge"),
  runTime: document.querySelector("#run-time"),
  hashSummary: document.querySelector("#hash-summary"),
  accountSummary: document.querySelector("#account-summary"),
};

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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
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

function reconcileSelectedTossAccount() {
  const accounts = state.tossAccounts?.accounts || [];
  if (!state.selectedTossAccount && state.tossAccounts?.auto_select_account_seq) {
    setSelectedTossAccount(state.tossAccounts.auto_select_account_seq, false);
    return;
  }
  if (
    state.selectedTossAccount &&
    accounts.length &&
    !accounts.some((account) => account.account_seq === state.selectedTossAccount)
  ) {
    setSelectedTossAccount("", false);
  }
}

function setSelectedTossAccount(accountSeq, announce = true) {
  state.selectedTossAccount = accountSeq || "";
  if (state.selectedTossAccount) {
    localStorage.setItem("jayu.toss.selectedAccount", state.selectedTossAccount);
  } else {
    localStorage.removeItem("jayu.toss.selectedAccount");
  }
  if (els.accountSummary) {
    els.accountSummary.textContent = selectedTossAccountLabel();
  }
  if (announce) {
    els.liveRegion.textContent = state.selectedTossAccount
      ? `Toss 계좌 ${selectedTossAccountLabel()}를 선택했습니다.`
      : "Toss 계좌 선택을 해제했습니다.";
  }
}

function selectedTossAccountLabel() {
  const account = (state.tossAccounts?.accounts || []).find(
    (item) => item.account_seq === state.selectedTossAccount
  );
  if (account) {
    return `${account.display_name || "Toss"} ${account.masked_account_no || ""}`.trim();
  }
  return state.selectedTossAccount ? `선택됨 ${state.selectedTossAccount.slice(-4)}` : "미선택";
}

async function api(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return response.json();
}

async function loadRuns() {
  const payload = await api("/api/v1/runs");
  state.runs = payload.runs || [];
  els.runSelector.innerHTML = state.runs.length
    ? state.runs
        .map(
          (run) =>
            `<option value="${escapeHtml(run.run_id)}">${escapeHtml(run.run_id)} · ${escapeHtml(
              String(run.mode || "unknown").toUpperCase()
            )} · ${escapeHtml(run.status)}</option>`
        )
        .join("")
    : '<option value="latest">완료된 실행 없음</option>';
  if (state.runId === "latest" && state.runs[0]) state.runId = state.runs[0].run_id;
  els.runSelector.value = state.runId;
}

async function loadPage() {
  setLoading(true);
  try {
    if (!state.runs.length) await loadRuns();
    const run = encodeURIComponent(state.runId);
    state.decision = await api(`/api/v1/decision?run_id=${run}`);
    state.overview = await api(`/api/v1/overview?run_id=${run}`);
    if (state.page === "data-quality") {
      state.dataQuality = await api(`/api/v1/runs/${run}/data-quality`);
    }
    if (state.page === "risk") {
      state.risk = await api(`/api/v1/runs/${run}/risk`);
    }
    if (state.page === "signals") {
      state.signals = await api(`/api/v1/runs/${run}/signals`);
    }
    if (state.page === "trader-lens") {
      state.traderLens = await api(`/api/v1/runs/${run}/trader-lens`);
    }
    if (state.page === "promotion") {
      state.promotion = await api("/api/v1/promotion");
    }
    if (state.page === "settings") {
      const mode = encodeURIComponent(state.overview?.run?.mode || "shadow");
      state.settingsValidation = await api(`/api/v1/settings/validation?mode=${mode}`);
    }
    if (state.page === "toss") {
      state.tossStatus = await api("/api/v1/toss/status");
      state.tossAccounts = await api("/api/v1/toss/accounts");
      reconcileSelectedTossAccount();
    }
    if (state.page === "api-monitoring") {
      state.apiMonitoring = await api("/api/v1/api-monitoring");
    }
    if (state.page === "analysis") {
      // Analysis tabs load data themselves via bindPageActions auto-triggers
    }
    if (state.page === "toss-account") {
      const params = new URLSearchParams();
      if (state.selectedTossAccount) params.set("account", state.selectedTossAccount);
      
      const [portfolio, reconciliation, orderPlan] = await Promise.all([
        api(`/api/v1/toss/portfolio${params.toString() ? `?${params.toString()}` : ""}`),
        api(`/api/v1/toss/reconciliation${params.toString() ? `?${params.toString()}` : ""}`),
        api("/api/v1/toss/order-plan")
      ]);

      state.tossPortfolio = portfolio;
      state.tossReconciliation = reconciliation;
      state.tossOrderPlan = orderPlan;

      state.tossAccounts = {
        status: state.tossPortfolio.status,
        accounts: state.tossPortfolio.accounts || [],
        auto_select_account_seq: state.tossPortfolio.auto_select_account_seq,
      };
      if (state.tossPortfolio.auto_select_account_seq) {
        setSelectedTossAccount(state.tossPortfolio.auto_select_account_seq, false);
      }
    }
    updateContext();
    render();
    setupApiMonitoringRefreshTimer();
    setLoading(false);
    els.liveRegion.textContent = `${pageTitle(state.page)} 화면을 갱신했습니다.`;
  } catch (error) {
    showError(error);
  }
}

function setLoading(loading) {
  els.loading.hidden = !loading;
  els.error.hidden = true;
  els.root.hidden = loading;
}

function showError(error) {
  els.loading.hidden = true;
  els.root.hidden = true;
  els.error.hidden = false;
  els.errorMessage.textContent = error.message || "잠시 후 다시 시도하세요.";
}

function updateContext() {
  const run = state.overview?.run || {};
  els.modeBadge.textContent = String(run.mode || "unknown").toUpperCase();
  els.runTime.textContent = formatDate(run.finished_at);
  els.hashSummary.textContent = `${shortHash(run.config_hash)} / ${shortHash(run.data_hash)}`;
  els.hashSummary.title = `config: ${run.config_hash || "-"}\ndata: ${run.data_hash || "-"}`;
  if (els.accountSummary) {
    els.accountSummary.textContent = selectedTossAccountLabel();
  }
}

function pageTitle(page) {
  return {
    overview: "개요",
    "data-quality": "데이터 품질",
    risk: "리스크 게이트",
    signals: "신호",
    "trader-lens": "Trader Lens",
    promotion: "Shadow 승격",
    settings: "설정 검증",
    "toss-account": "Toss Account",
    toss: "Toss Market",
    "api-monitoring": "API 모니터링",
    analysis: "주식 & 경제 분석",
  }[page];
}

const PAGE_DATA_SOURCES = {
  overview: ["run manifest", "safety_verdict.json", "health report", "today_signals sidecar"],
  "data-quality": ["data_sources.json", "provider_disagreement_report.json", "OHLCV provider cache"],
  risk: ["risk report", "portfolio_mapping.json", "portfolio.csv", "Toss holdings snapshot"],
  signals: ["today_signals.json", "signal sidecar", "data quality gate", "risk gate"],
  "trader-lens": ["signals artifact", "risk gate", "provider trust map", "safety verdict"],
  promotion: ["promotion state", "shadow run history", "health report", "signal history"],
  settings: ["config.json", ".env / environment", "provider policy", "survivorship audit"],
  "toss-account": ["Toss Open API GET", "accounts", "holdings", "exchange-rate", "portfolio_mapping.json"],
  toss: ["Toss Open API GET", "prices", "stocks", "warnings", "market calendar"],
  "api-monitoring": ["provider audit", "events.jsonl", "cache directories", "latest run artifacts"],
  analysis: ["Yahoo Finance", "FRED", "TradingView scanner", "Toss Open API", "run artifacts"],
};

const METRIC_DATA_SOURCE_BY_PAGE = {
  overview: {
    "데이터 검증": "data_sources.json · provider_disagreement_report.json",
    "리스크 게이트": "risk report · portfolio.csv",
    "생존편향 정책": "survivorship audit",
    "Shadow 승격": "promotion state · shadow run history",
    "오늘의 신호": "today_signals.json · signal sidecar",
    Health: "health report",
    __default: "latest run manifest",
  },
  "data-quality": {
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
    "조회 실패": "Toss account section status",
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

function render() {
  els.root.hidden = false;
  if (state.page === "data-quality") renderDataQuality();
  else if (state.page === "risk") renderRisk();
  else if (state.page === "signals") renderSignals();
  else if (state.page === "trader-lens") renderTraderLens();
  else if (state.page === "promotion") renderPromotion();
  else if (state.page === "settings") renderSettingsValidation();
  else if (state.page === "toss-account") renderTossAccountDashboard();
  else if (state.page === "toss") renderTossMarket();
  else if (state.page === "api-monitoring") renderApiMonitoring();
  else if (state.page === "analysis") renderAnalysis();
  else renderOverview();
  bindPageActions();
}

function renderOverview() {
  const data = state.overview;
  const run = data.run;
  const decision = state.decision || data.decision;
  const gates = data.gates;
  const signals = data.signals;
  const health = data.health;
  const reasons = decision.top_blockers || decision.top_reasons || [];
  const actions = decision.recommended_actions || data.recommended_actions || [];
  const primaryAction = decision.recommended_next_action || actions[0] || null;
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>운영 상태 개요</h1>
        <p>오늘 실행을 계속 볼지, 멈추고 재검증할지 먼저 판단합니다. 차단 사유와 다음 행동을 상단에 고정합니다.</p>
      </div>
      ${statusBadge(run.execution_status, "실행")} 
    </div>
    ${renderDataSourceNote("overview")}
    <section class="decision-grid" aria-label="오늘 결론">
      <article class="decision-card status-${statusClass(decision.overall)}" aria-labelledby="status-title">
        <div class="decision-eyebrow">${statusBadge(decision.overall)} <span>${escapeHtml(String(run.mode || "unknown").toUpperCase())}</span></div>
        <h2 id="status-title">${escapeHtml(decisionHeadline(decision.overall))}</h2>
        <p>${escapeHtml(decision.headline)}</p>
        ${renderSourceLabel("safety_verdict.json · latest run manifest")}
        <div class="decision-meta">
          <span>실행 ${escapeHtml(STATUS_LABELS[run.execution_status] || run.execution_status || "미검증")}</span>
          <span>운영 ${escapeHtml(STATUS_LABELS[run.safety_decision] || run.safety_decision || "미검증")}</span>
          <span class="code">${escapeHtml(run.failure_code || reasons[0]?.code || "NO_BLOCKER")}</span>
        </div>
      </article>
      ${renderPrimaryAction(primaryAction)}
    </section>
    <section class="metric-grid" aria-label="핵심 운영 지표">
      ${metricCard("데이터 검증", ratioValue(gates.data.verified, gates.data.total), gates.data.status,
        gates.data.total ? `${formatPercent(gates.data.validation_rate)} · provider ${gates.data.provider_count}` : "가격 데이터 미검증",
        gates.data.validation_rate)}
      ${metricCard("리스크 게이트", `${gates.risk.approved_count}/${gates.risk.approved_count + gates.risk.blocked_count}`,
        gates.risk.status, `승인 ${gates.risk.approved_count} · 차단 ${gates.risk.blocked_count}`,
        gateRatio(gates.risk.approved_count, gates.risk.blocked_count))}
      ${metricCard("생존편향 정책", gates.survivorship.policy || "미검증", gates.survivorship.status,
        `Delisted ${formatBoolean(gates.survivorship.includes_delisted)}`)}
      ${metricCard("Shadow 승격", gates.promotion.eligible ? "가능" : "대기", gates.promotion.status,
        `${gates.promotion.shadow_day_count ?? 0}일 실행`)}
      ${metricCard("오늘의 신호", `${signals.eligible}/${signals.buy}`, signals.blocked ? "blocked" : signals.buy ? "success" : "not_evaluated",
        `매수 ${signals.buy} · 차단 ${signals.blocked}`)}
      ${metricCard("Health", health.score ?? "미검증", health.status === "healthy" ? "success" : health.status,
        `기준 ${health.threshold ?? "-"} / 100`, health.score == null ? null : health.score / 100)}
    </section>
    <div class="section-grid">
      <section class="panel">
        <div class="panel-header">
          <div><h2>차단 원인 Top 3</h2><p>차단 영향도가 높은 순서입니다. 관련 화면 또는 안전 명령으로 바로 이어집니다.</p></div>
          <span class="muted">${reasons.length}건</span>
        </div>
        <div class="panel-body">
          ${renderReasons(reasons, actions)}
          ${renderSourceCaption("safety_verdict.json · decision reasons")}
        </div>
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>다음 행동 목록</h2><p>실행 버튼이 아니라 안전한 화면 이동과 명령 복사만 제공합니다.</p></div></div>
        <div class="panel-body">
          <div class="action-list">
            ${actions.length ? actions.map((action) =>
              `<button class="button ${action.priority === 1 ? "button-primary" : "button-secondary"}" type="button" ${
                action.page
                  ? `data-go="${escapeHtml(action.page)}"`
                  : `data-command="${escapeHtml(action.command || "")}"`
              }>${escapeHtml(action.label)}</button>`
            ).join("") : '<span class="muted">추가 조치가 없습니다.</span>'}
          </div>
          ${renderSourceCaption("recommended_actions from safety verdict")}
          <p id="command-feedback" class="metric-detail" hidden></p>
        </div>
      </section>
    </div>
    <section class="panel">
      <div class="panel-header">
        <div><h2>신호 요약</h2><p>데이터와 리스크 검증 이후 상태</p></div>
        <button class="button button-secondary" type="button" data-go="risk">리스크 상세</button>
      </div>
      ${renderSignalTable(signals.rows)}
      ${renderSourceCaption("today_signals.json · risk gate status")}
    </section>
  `;
}

function renderDataQuality() {
  const data = state.dataQuality;
  const summary = data.summary;
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>데이터 품질</h1>
        <p>동일 ticker와 기간의 provider별 행 수, 날짜, 가격, 거래량을 비교합니다.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    ${renderDataSourceNote("data-quality")}
    <section class="status-banner status-${statusClass(summary.status)}">
      <div>${statusBadge(summary.status)}</div>
      <div>
        <h2>${summary.total ? `가격 데이터 ${summary.verified}/${summary.total} 검증` : "가격 데이터 미검증"}</h2>
        <p>${dataQualityHeadline(summary)}</p>
      </div>
      <span class="code">${summary.disagreement_count ? "DATA_DISAGREEMENT" : "NO_DISAGREEMENT"}</span>
    </section>
    <section class="metric-grid">
      ${metricCard("검증 성공률", summary.validation_rate == null ? "미검증" : formatPercent(summary.validation_rate), summary.status,
        `${summary.verified}/${summary.total} ticker`, summary.validation_rate)}
      ${metricCard("Provider 수", summary.provider_count, summary.failed_source_count ? "warning" : summary.provider_count > 1 ? "success" : "not_evaluated",
        summary.providers.join(", ") || "수집 기록 없음")}
      ${metricCard("불일치", summary.disagreement_count, summary.disagreement_count ? "data_error" : summary.total ? "success" : "not_evaluated",
        "임계값 초과 report")}
      ${metricCard("차단 ticker", summary.blocked_ticker_count, summary.blocked_ticker_count ? "blocked" : summary.total ? "success" : "not_evaluated",
        summary.blocked_tickers.join(", ") || "없음")}
      ${metricCard("Provider 실패", summary.failed_source_count, summary.failed_source_count ? "failed" : summary.provider_count ? "success" : "not_evaluated",
        "수집 실패 source")}
      ${metricCard("상태", STATUS_LABELS[summary.status] || summary.status, summary.status,
        summary.status === "not_evaluated" ? "성공으로 간주하지 않음" : "현재 run 기준")}
    </section>
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>Provider 수집 결과</h2><p>행 수, 기간, hash와 실패 원인</p></div></div>
      ${renderSourcesTable(data.sources)}
      ${renderSourceCaption("data_sources.json")}
    </section>
    <section class="panel">
      <div class="panel-header"><div><h2>불일치 상세</h2><p>날짜와 provider별 원본값을 함께 표시합니다.</p></div></div>
      ${renderMismatchTable(data.mismatches)}
      ${renderSourceCaption("provider_disagreement_report.json")}
    </section>
  `;
}

function renderRisk() {
  const data = state.risk;
  const summary = data.summary;
  const checks = data.checks || [];
  const blockedChecks = checks.filter((item) => item.status === "blocked");
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>리스크 게이트</h1>
        <p>현재값, 한도, 초과값을 기준으로 포트폴리오 위험 판정을 설명합니다.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    ${renderDataSourceNote("risk")}
    <section class="status-banner status-${statusClass(summary.status)}">
      <div>${statusBadge(summary.status)}</div>
      <div>
        <h2>${summary.blocked_count ? `${summary.blocked_count}개 신호 차단` : summary.status === "not_evaluated" ? "리스크 미검증" : "리스크 게이트 통과"}</h2>
        <p>${riskHeadline(summary)}</p>
      </div>
      <span class="code">${escapeHtml(summary.top_block_reasons?.[0]?.code || "NO_BLOCKER")}</span>
    </section>
    <section class="metric-grid">
      ${metricCard("승인 신호", summary.approved_count, summary.approved_count ? "success" : "not_evaluated", "검토 가능한 buy")}
      ${metricCard("차단 신호", summary.blocked_count, summary.blocked_count ? "blocked" : summary.status === "pass" ? "success" : "not_evaluated", "eligible=false")}
      ${metricCard("대기", summary.hold_count, "not_evaluated", "리스크 심사 비대상")}
      ${metricCard("실패 게이트", blockedChecks.length, blockedChecks.length ? "blocked" : summary.status === "pass" ? "success" : "not_evaluated", "reason detail")}
      ${metricCard("최상위 사유", summary.top_block_reasons?.[0]?.code || "없음", summary.blocked_count ? "blocked" : "not_evaluated", summary.top_block_reasons?.[0]?.count ? `${summary.top_block_reasons[0].count}건` : "기록 없음")}
      ${metricCard("판정 상태", STATUS_LABELS[summary.status] || summary.status, summary.status, "현재 run 기준")}
    </section>
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>게이트별 판정</h2><p>수치는 0으로 보정하지 않고 미계산 상태를 유지합니다.</p></div></div>
      ${renderRiskChecks(checks)}
      ${renderSourceCaption("risk report gate details")}
    </section>
    <section class="panel">
      <div class="panel-header"><div><h2>종목별 판정</h2><p>요청 비중과 승인 비중, 차단 사유</p></div></div>
      ${renderRiskSignals(data.signals)}
      ${renderSourceCaption("risk report signal rows · portfolio.csv")}
    </section>
  `;
}

function renderSignals() {
  const data = state.signals;
  const summary = data.summary;
  const publication = data.publication || {};
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>신호</h1>
        <p>오늘 신호 후보, 출판 상태, 가격 레벨, 데이터 검증, 리스크 차단 여부를 함께 봅니다.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    ${renderDataSourceNote("signals")}
    <section class="status-banner status-${statusClass(summary.status)}">
      <div>${statusBadge(summary.status)}</div>
      <div>
        <h2>${summary.blocked_count ? `매수 신호 ${summary.blocked_count}개 차단` : summary.eligible_count ? `매수 신호 ${summary.eligible_count}개 검토 가능` : "검토 가능한 매수 신호 없음"}</h2>
        <p>출판 상태는 <strong>${escapeHtml(publicationStatusLabel(publication.status))}</strong>입니다. 검증된 가격 데이터가 없는 신호는 운영에 사용할 수 없습니다.</p>
      </div>
      <span class="code">${escapeHtml(publication.failure_code || publication.status || "NO_PUBLICATION")}</span>
    </section>
    <section class="metric-grid">
      ${metricCard("출판 상태", publicationStatusLabel(publication.status), publication.status === "published" ? "success" : publication.status === "blocked" ? "blocked" : "not_evaluated", publication.signal_date || "승인된 sidecar 없음")}
      ${metricCard("검토 가능 매수", `${summary.eligible_count}/${summary.buy_count}`, summary.eligible_count ? "success" : "not_evaluated", "게이트 통과 buy 신호", gateRatio(summary.eligible_count, summary.blocked_count))}
      ${metricCard("차단 매수", summary.blocked_count, summary.blocked_count ? "blocked" : summary.buy_count ? "success" : "not_evaluated", "eligible=false")}
      ${metricCard("대기", summary.hold_count, "not_evaluated", "매수 후보 아님")}
      ${metricCard("데이터 검증", `${summary.data_verified_count}/${summary.total_count}`, summary.data_verified_count === summary.total_count && summary.total_count ? "success" : summary.total_count ? "data_error" : "not_evaluated", "가격 신뢰도", summary.data_verified_rate)}
      ${metricCard("신호 hash", shortHash(publication.signal_hash), publication.signal_hash ? "success" : "not_evaluated", "출판 근거")}
    </section>
    <section class="panel">
      <div class="panel-header"><div><h2>신호 목록</h2><p>진입가, 손절가, 목표가, 유동성, reason code</p></div></div>
      ${renderSignalDetailTable(data.rows)}
      ${renderSourceCaption("today_signals.json · signal publication sidecar")}
    </section>
  `;
}

function renderTraderLens() {
  const data = state.traderLens;
  const summary = data.summary || {};
  const notes = data.decision_notes || [];
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>Trader Lens</h1>
        <p>Run-local decision board for reward/risk, data trust, and block concentration. Read-only review surface; no order controls are exposed.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    ${renderDataSourceNote("trader-lens")}
    <section class="status-banner status-${statusClass(summary.status)}">
      <div>${statusBadge(summary.status)}</div>
      <div>
        <h2>${traderLensHeadline(summary)}</h2>
        <p>Use this view to decide whether to continue reviewing the run, repair data/provider issues, or keep the signal blocked.</p>
      </div>
      <span class="code">${summary.provider_issue_count ? "DATA_REVIEW" : summary.risk_issue_count ? "RISK_REVIEW" : "READ_ONLY_LENS"}</span>
    </section>
    <section class="metric-grid">
      ${metricCard("Avg reward/risk", summary.average_reward_to_risk == null ? "-" : `${formatNumber(summary.average_reward_to_risk, 2)}R`, summary.status, "target distance divided by stop distance")}
      ${metricCard("Signals reviewed", summary.signals_reviewed ?? 0, summary.signals_reviewed ? "success" : "not_evaluated", "run-local signal rows")}
      ${metricCard("Eligible / blocked", `${summary.eligible_count ?? 0}/${summary.blocked_count ?? 0}`, summary.blocked_count ? "blocked" : summary.eligible_count ? "success" : "not_evaluated", "risk gate result")}
      ${metricCard("Provider issues", summary.provider_issue_count ?? 0, summary.provider_issue_count ? "data_error" : "success", "failed source or disagreement")}
      ${metricCard("Risk issues", summary.risk_issue_count ?? 0, summary.risk_issue_count ? "blocked" : "success", "blocked gate count")}
      ${metricCard("Controls", data.read_only ? "read only" : "review", "not_evaluated", "no order execution button")}
    </section>
    <div class="section-grid">
      <section class="panel">
        <div class="panel-header">
          <div><h2>Signal reward/risk ladder</h2><p>Entry, stop, target, data verification, and reason codes in one sortable review table.</p></div>
          <button class="button button-secondary" type="button" data-go="signals">Open Signals</button>
        </div>
        ${renderTraderSignalLadder(data.signal_ladder || [])}
        ${renderSourceCaption("today_signals.json · risk gate · data verification flags")}
      </section>
      <section class="panel">
        <div class="panel-header">
          <div><h2>Top decision notes</h2><p>The most important blockers from the run verdict.</p></div>
        </div>
        <div class="panel-body">
          ${renderTraderDecisionNotes(notes)}
          ${renderSourceCaption("safety_verdict.json · decision notes")}
        </div>
      </section>
    </div>
    <div class="section-grid">
      <section class="panel">
        <div class="panel-header">
          <div><h2>Provider trust map</h2><p>Provider/ticker health with mismatch counts and hash trace.</p></div>
          <button class="button button-secondary" type="button" data-go="data-quality">Data Quality</button>
        </div>
        ${renderProviderTrustMap(data.provider_trust || [])}
        ${renderSourceCaption("data_sources.json · provider_disagreement_report.json")}
      </section>
      <section class="panel">
        <div class="panel-header">
          <div><h2>Risk concentration</h2><p>Blocked reason codes grouped by count and excess.</p></div>
          <button class="button button-secondary" type="button" data-go="risk">Risk Gate</button>
        </div>
        <div class="panel-body">
          ${renderRiskConcentration(data.risk_concentration || [])}
          ${renderSourceCaption("risk report reason counts")}
        </div>
      </section>
    </div>
  `;
}

function renderPromotion() {
  const data = state.promotion;
  const summary = data.summary;
  const metrics = data.metrics || {};
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>Shadow 승격</h1>
        <p>paper 또는 live 성격 운영 전에 필요한 shadow 실행 근거를 확인합니다.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    ${renderDataSourceNote("promotion")}
    <section class="status-banner status-${statusClass(summary.status)}">
      <div>${statusBadge(summary.status)}</div>
      <div>
        <h2>${summary.eligible ? "승격 가능" : "승격 차단"}</h2>
        <p>${summary.failed_criteria_count ? `${summary.failed_criteria_count}개 조건에 근거가 더 필요합니다.` : "설정된 승격 조건을 모두 충족했습니다."}</p>
      </div>
      <span class="code">${escapeHtml(summary.failure_code || "SHADOW_PROMOTION")}</span>
    </section>
    <section class="metric-grid">
      ${metricCard("Shadow 일수", summary.shadow_day_count, summary.eligible ? "success" : "warning", "서로 다른 shadow 파일")}
      ${metricCard("완료 신호", summary.completed_signal_count, summary.completed_signal_count ? "success" : "warning", `매수 신호 ${summary.buy_signal_count}개`)}
      ${metricCard("데이터 성공률", formatPercent(metrics.data_validation_success_rate), metrics.data_validation_success_rate >= 0.95 ? "success" : "warning", "현재값 / 설정 기준")}
      ${metricCard("불일치율", formatPercent(metrics.provider_disagreement_rate), metrics.provider_disagreement_rate === 0 ? "success" : "data_error", "낮을수록 안전")}
      ${metricCard("리스크 통과율", formatPercent(metrics.risk_gate_pass_rate), metrics.risk_gate_pass_rate >= 0.5 ? "success" : "warning", "eligible buy 비율")}
      ${metricCard("신호 안정성", formatPercent(metrics.max_signal_count_change_ratio), metrics.max_signal_count_change_ratio <= 1 ? "success" : "warning", "일별 최대 변화")}
    </section>
    <div class="section-grid">
      <section class="panel">
        <div class="panel-header"><div><h2>승격 조건</h2><p>현재값과 필수 기준 비교</p></div></div>
        ${renderCriteriaTable(data.criteria)}
        ${renderSourceCaption("promotion state · promotion policy")}
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>Shadow 이력</h2><p>최근 일자별 근거</p></div></div>
        ${renderPromotionHistory(data.history)}
        ${renderSourceCaption("shadow run history artifacts")}
      </section>
    </div>
  `;
}

function renderSettingsValidation() {
  const data = state.settingsValidation;
  const summary = data.summary;
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>설정 검증</h1>
        <p>실행 모드별 안전 설정을 확인합니다. 비밀값은 숨기며, 이 화면은 config 파일을 저장하지 않습니다.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    ${renderDataSourceNote("settings")}
    <section class="status-banner status-${statusClass(summary.status)}">
      <div>${statusBadge(summary.status)}</div>
      <div>
        <h2>${escapeHtml(String(data.mode).toUpperCase())} 설정 ${summary.safe ? "계속 진행 가능" : "수정 필요"}</h2>
        <p>차단 ${summary.blocked_count}건, 경고 ${summary.warning_count}건입니다. 실행 전 현재값과 필수 기준을 확인하세요.</p>
      </div>
      <span class="code">${summary.safe ? "CONFIG_OK" : "CONFIG_REVIEW"}</span>
    </section>
    <section class="metric-grid">
      ${metricCard("차단 규칙", summary.blocked_count, summary.blocked_count ? "blocked" : "success", "반드시 수정")}
      ${metricCard("경고", summary.warning_count, summary.warning_count ? "warning" : "success", "검토 권장")}
      ${metricCard("Provider 점검", data.provider_audit.valid ? "유효" : "무효", data.provider_audit.valid ? "success" : "blocked", (data.provider_audit.errors || []).join("; ") || "목록 정상")}
      ${metricCard("생존편향", data.survivorship_audit.valid ? "유효" : "검토", data.survivorship_audit.valid ? "success" : "warning", data.survivorship_audit.policy || "unknown")}
      ${metricCard("승격", data.promotion_audit.eligible ? "가능" : "차단", data.promotion_audit.eligible ? "success" : "warning", "paper/live 게이트")}
      ${metricCard("비밀값", "숨김", "not_evaluated", "값은 절대 표시하지 않음")}
    </section>
    <section class="panel">
      <div class="panel-header"><div><h2>검증 규칙</h2><p>현재값, 필수 기준, 영향</p></div></div>
      ${renderSettingsRules(data.rules)}
      ${renderSourceCaption("config.json · environment · policy audits")}
    </section>
  `;
}

function renderTossAccountDashboard() {
  const data = state.tossPortfolio || {};
  const summary = data.summary || {};
  const accounts = data.accounts || [];
  const selected = data.selected_account || {};
  const holdings = data.holdings || [];
  const visibleHoldings = filterTossHoldingsByRegion(holdings);
  const visibleSummary = summarizeTossHoldings(visibleHoldings, summary);
  const allocation = visibleHoldings.filter((item) => item.weight !== null && item.weight !== undefined);
  const sections = data.sections || {};
  const activeRegionLabel = { ALL: "전체", KR: "한국", US: "미국" }[state.tossAccountRegion] || "전체";

  let activeContentHtml = "";
  if (state.tossSubTab === "reconciliation") {
    activeContentHtml = renderReconciliation(state.tossReconciliation);
  } else if (state.tossSubTab === "order-plan") {
    activeContentHtml = renderOrderPlan(state.tossOrderPlan);
  } else {
    activeContentHtml = `
      ${renderTossRegionTabs(data.region_totals || [])}
      <section class="panel" style="margin-bottom:14px">
        <div class="panel-header">
          <div><h2>포트폴리오 타입별 요약</h2><p>보유종목을 단타, 중타, 장타, 배당 관리 관점으로 나눠 확인합니다.</p></div>
        </div>
        <div class="panel-body">${renderPortfolioTypeCards(data.portfolio_type_totals || [])}</div>
      </section>
      <section class="panel" style="margin-bottom:14px">
        <div class="panel-header">
          <div><h2>Account selector</h2><p>버튼을 누르지 않아도 첫 계좌가 자동으로 선택됩니다. 다른 계좌를 고르면 즉시 다시 조회합니다.</p></div>
          ${statusBadge(data.read_only ? "success" : "blocked", "read only")}
        </div>
        ${renderTossAccountCards(accounts, selected)}
        ${renderSourceCaption("Toss Open API accounts GET")}
      </section>
      <div class="visual-grid">
        <section class="panel">
          <div class="panel-header"><div><h2>Market split</h2><p>KRW 환산 기준 한국/미국/기타 비중입니다.</p></div></div>
          <div class="panel-body">${renderExposureDonut(data.region_totals || [], "region")}${renderSourceCaption("Toss holdings GET · KRW conversion")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>Currency split</h2><p>USD와 KRW가 섞여도 KRW 환산 기준으로 비교합니다.</p></div></div>
          <div class="panel-body">${renderExposureDonut(data.currency_totals || [], "currency")}${renderSourceCaption("Toss holdings GET · currency fields")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>FX rates</h2><p>환산에 사용한 환율과 유효 시각입니다.</p></div></div>
          <div class="panel-body">${renderFxRateCards(data.fx_rates || [])}${renderSourceCaption("Toss exchange-rate GET")}</div>
        </section>
      </div>
      <div class="visual-grid">
        <section class="panel">
          <div class="panel-header"><div><h2>Category split</h2><p>주식, ETF, 레버리지 ETF 같은 종목 유형별 노출입니다.</p></div></div>
          <div class="panel-body">${renderExposureDonut(data.category_totals || [], "category")}${renderSourceCaption("portfolio_mapping.json · holdings enrichment")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>Sector exposure</h2><p>종목 메타데이터에서 읽은 섹터 기준 상위 노출입니다.</p></div></div>
          <div class="panel-body">${renderExposureDonut(data.sector_totals || [], "sector")}${renderSourceCaption("portfolio_mapping.json sector metadata")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>Situation tags</h2><p>집중도, 손익, 당일 급등락, 경고 상태를 태그로 묶었습니다.</p></div></div>
          <div class="panel-body">${renderSituationTags(data.situation_totals || [])}${renderSourceCaption("Toss holdings GET · warnings enrichment · price changes")}</div>
        </section>
      </div>
      <div class="section-grid">
        <section class="panel">
          <div class="panel-header"><div><h2>Holding allocation</h2><p>${activeRegionLabel} 탭의 KRW 환산 평가금액 기준 보유 비중입니다.</p></div></div>
          <div class="panel-body">${renderHoldingAllocation(allocation)}${renderSourceCaption("Toss holdings GET · selected market filter")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>P/L contributors</h2><p>KRW 환산 평가손익 기여도가 큰 종목입니다.</p></div></div>
          <div class="panel-body">${renderPnlContributors(visibleHoldings)}${renderSourceCaption("Toss holdings GET · unrealized P/L fields")}</div>
        </section>
      </div>
      <section class="panel">
        <div class="panel-header"><div><h2>Holdings</h2><p>수량, 평균단가, 현재가, 평가금액, 손익률을 한 표에서 확인합니다.</p></div></div>
        ${renderTossHoldingsTable(visibleHoldings)}
        ${renderSourceCaption("Toss Open API holdings GET · exchange-rate GET")}
      </section>
      <section class="panel" style="margin-top:14px">
        <div class="panel-header"><div><h2>Account GET status</h2><p>계좌 화면에서 자동 호출한 GET endpoint 결과입니다.</p></div></div>
        ${renderTossSectionTable(sections)}
        ${renderSourceCaption("Toss account endpoint status from latest dashboard fetch")}
      </section>
    `;
  }

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>Toss Account Dashboard</h1>
        <p>첫 계좌를 자동 선택하고 USD/KRW 환율을 반영해 KRW 기준 보유 종목, 평가금액, 손익, 비중을 보여주는 읽기 전용 계좌 화면입니다.</p>
      </div>
      ${statusBadge(summary.status || data.status)}
    </div>
    ${renderDataSourceNote("toss-account", ["Toss warnings endpoint", "today_signals broker readiness"])}

    <div class="segmented-tabs" role="tablist" style="margin-bottom:14px">
      <button class="${state.tossSubTab === 'overview' ? 'is-active' : ''}" type="button" data-toss-subtab="overview">
        <span>자산 요약 (Asset Summary)</span>
      </button>
      <button class="${state.tossSubTab === 'reconciliation' ? 'is-active' : ''}" type="button" data-toss-subtab="reconciliation">
        <span>보유 종목 대조 (Reconciliation)</span>
      </button>
      <button class="${state.tossSubTab === 'order-plan' ? 'is-active' : ''}" type="button" data-toss-subtab="order-plan">
        <span>주문 준비도 및 전표 (Order Plan)</span>
      </button>
    </div>

    <section class="status-banner status-${statusClass(summary.status || data.status)}">
      <div>${statusBadge(summary.status || data.status)}</div>
      <div>
        <h2>${tossAccountHeadline(data, summary)}</h2>
        <p>화면 진입만으로 accounts, holdings, 필요한 exchange-rate GET 조회를 수행합니다. 주문 생성/정정/취소 요청은 없습니다.</p>
      </div>
      <span class="code">READ_ONLY_ACCOUNT</span>
    </section>
    <section class="metric-grid">
      ${metricCard("계좌", selected.display_name || "-", selected.account_seq ? "success" : "warning", selected.masked_account_no || "첫 계좌 자동 선택")}
      ${metricCard(`${activeRegionLabel} 종목`, visibleSummary.holding_count ?? 0, visibleSummary.holding_count ? "success" : "not_evaluated", "filtered holdings")}
      ${metricCard("총 평가금액(KRW)", formatCurrency(visibleSummary.total_market_value_krw, "KRW"), summary.failed_section_count ? "warning" : "success", "FX converted")}
      ${metricCard("평가손익(KRW)", formatCurrency(visibleSummary.unrealized_pnl_krw, "KRW"), Number(visibleSummary.unrealized_pnl_krw || 0) < 0 ? "warning" : "success", formatPercent(visibleSummary.unrealized_pnl_pct, 2))}
      ${metricCard("USD/KRW", fxRateLabel(data.fx_rates, "USD"), fxRateStatus(data.fx_rates, "USD"), fxRateDetail(data.fx_rates, "USD"))}
      ${metricCard("조회 실패", summary.failed_section_count ?? 0, summary.failed_section_count ? "warning" : "success", (summary.failed_sections || []).join(", ") || "없음")}
    </section>
    
    ${activeContentHtml}
  `;
}

function renderReconciliation(reconciliation) {
  const recon = reconciliation || {};
  const status = recon.status || "unknown";
  const differences = recon.differences || [];
  const unmapped = recon.unmapped_tickers || [];

  let statusHtml = "";
  if (status === "synchronized") {
    statusHtml = `
      <section class="status-banner status-success">
        <div>${statusBadge("success")}</div>
        <div>
          <h2>포트폴리오 일치 (Synchronized)</h2>
          <p>Local portfolio.csv와 Toss 실계좌 보유 종목 및 수량이 완벽히 일치합니다.</p>
        </div>
      </section>
    `;
  } else if (status === "diverged") {
    statusHtml = `
      <section class="status-banner status-warning">
        <div>${statusBadge("warning")}</div>
        <div>
          <h2>포트폴리오 불일치 (Diverged)</h2>
          <p>Local portfolio.csv와 Toss 실계좌 간에 수량 불일치 또는 누락된 종목이 있습니다. 실계좌 보유 종목 기준으로 로컬 CSV를 갱신할 수 있습니다.</p>
          <div style="margin-top: 10px;">
            <button id="btn-sync-portfolio-banner" class="button button-primary" type="button">실계좌 종목으로 동기화</button>
          </div>
        </div>
      </section>
    `;
  } else if (status === "missing_credentials") {
    statusHtml = `
      <section class="status-banner status-warning">
        <div>${statusBadge("warning")}</div>
        <div>
          <h2>자격증명 미설정</h2>
          <p>Toss API Key와 Secret Key가 설정되지 않아 실계좌 대조를 진행할 수 없습니다.</p>
        </div>
      </section>
    `;
  } else {
    statusHtml = `
      <section class="status-banner status-failed">
        <div>${statusBadge("failed")}</div>
        <div>
          <h2>조회 실패</h2>
          <p>${escapeHtml(recon.message || "Toss 실계좌 정보를 가져올 수 없습니다.")}</p>
        </div>
      </section>
    `;
  }

  let tableHtml = "";
  if (differences.length === 0) {
    tableHtml = `
      <div class="empty-state">
        <strong>불일치 내역이 없습니다.</strong>
        <span>Local 포트폴리오 파일과 실계좌 보유 종목의 수량이 같습니다.</span>
      </div>
    `;
  } else {
    tableHtml = `
      <div class="table-wrap"><table>
        <thead>
          <tr>
            <th>종목 (Ticker)</th>
            <th class="numeric">로컬 수량 (portfolio.csv)</th>
            <th class="numeric">토스 수량 (Holdings)</th>
            <th class="numeric">차이 (Diff)</th>
            <th>구분</th>
          </tr>
        </thead>
        <tbody>
          ${differences.map(d => {
            const diffClass = Number(d.difference || 0) < 0 ? "negative" : "positive";
            const diffTypeLabel = {
              missing_in_toss: "토스 누락",
              missing_in_local: "로컬 누락",
              quantity_mismatch: "수량 불일치"
            }[d.type] || d.type;
            const badgeType = d.type === "quantity_mismatch" ? "warning" : "blocked";
            return `
              <tr>
                <td class="ticker-cell">${escapeHtml(d.ticker)}</td>
                <td class="numeric">${formatNumber(d.local_quantity, 4)}</td>
                <td class="numeric">${formatNumber(d.toss_quantity, 4)}</td>
                <td class="numeric ${diffClass}">${formatNumber(d.difference, 4)}</td>
                <td>${statusBadge(badgeType, diffTypeLabel)}</td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table></div>
    `;
  }

  let unmappedHtml = "";
  if (unmapped.length > 0) {
    unmappedHtml = `
      <section class="panel" style="margin-top:14px">
        <div class="panel-header">
          <div><h2>미매핑 종목 (Unmapped Tickers)</h2><p>portfolio_mapping.json에 등록되지 않은 종목 코드입니다.</p></div>
          ${statusBadge("blocked", `${unmapped.length}건`)}
        </div>
        <div class="panel-body">
          <div class="tag-cloud">
            ${unmapped.map(ticker => `
              <div class="tag-pill" style="border-color:var(--status-blocked)">
                <strong style="color:var(--status-blocked)">${escapeHtml(ticker)}</strong>
                <span>매핑 미등록</span>
              </div>
            `).join("")}
          </div>
        </div>
      </section>
    `;
  }

  return `
    ${statusHtml}
    <section class="panel">
      <div class="panel-header" style="align-items: center;">
        <div><h2>보유 종목 대조 상세</h2><p>Local portfolio.csv와 Toss 실계좌 수량을 비교한 내역입니다.</p></div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <button id="btn-sync-portfolio" class="button button-secondary" type="button">실계좌 종목으로 동기화</button>
          ${statusBadge(differences.length ? "warning" : "success", differences.length ? "불일치 발견" : "일치")}
        </div>
      </div>
      ${tableHtml}
      ${renderSourceCaption("portfolio.csv · Toss holdings GET")}
    </section>
    ${unmappedHtml}
  `;
}

function renderOrderPlan(orderPlanData) {
  const planData = orderPlanData || {};
  const orderPlan = planData.order_plan || {};
  const warningsGate = planData.warnings_gate || {};
  const marketSession = planData.market_session || {};
  const todaySignals = planData.today_signals || {};

  const krOpen = marketSession.KR?.open || false;
  const usOpen = marketSession.US?.open || false;

  const orders = orderPlan.orders || [];

  const sessionHtml = `
    <div class="visual-grid" style="margin-bottom:14px">
      <div class="panel">
        <div class="panel-header"><div><h2>한국 시장 (KR Session)</h2><p>토스 API 실시간 조회 기준</p></div></div>
        <div class="panel-body">
          <div class="metric-card" style="border:none;box-shadow:none;padding:0">
            <span class="value" style="font-size:24px">${krOpen ? "개장 중 (OPEN)" : "휴장/장마감 (CLOSED)"}</span>
            <span class="status ${krOpen ? "success" : "not_evaluated"}" style="margin-top:5px;display:inline-block">${krOpen ? "실시간 거래 가능" : "주문 보류"}</span>
            ${renderSourceLabel("Toss market-calendar KR GET")}
          </div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header"><div><h2>미국 시장 (US Session)</h2><p>토스 API 실시간 조회 기준</p></div></div>
        <div class="panel-body">
          <div class="metric-card" style="border:none;box-shadow:none;padding:0">
            <span class="value" style="font-size:24px">${usOpen ? "개장 중 (OPEN)" : "휴장/장마감 (CLOSED)"}</span>
            <span class="status ${usOpen ? "success" : "not_evaluated"}" style="margin-top:5px;display:inline-block">${usOpen ? "실시간 거래 가능" : "주문 보류"}</span>
            ${renderSourceLabel("Toss market-calendar US GET")}
          </div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header"><div><h2>오늘의 주문 계획 요약</h2><p>eligible buy signals</p></div></div>
        <div class="panel-body">
          <div class="metric-card" style="border:none;box-shadow:none;padding:0">
            <span class="value" style="font-size:24px">${orders.length} 건</span>
            <span class="status ${orders.length ? "success" : "not_evaluated"}" style="margin-top:5px;display:inline-block">${orders.length ? "수동 매수 slip 대기" : "주문 대상 없음"}</span>
            ${renderSourceLabel("order_plan.json")}
          </div>
        </div>
      </div>
    </div>
  `;

  const tickers = Object.keys(todaySignals);
  let readinessHtml = "";
  if (tickers.length === 0) {
    readinessHtml = `
      <div class="empty-state">
        <strong>오늘 생성된 신호가 없습니다.</strong>
        <span>신호가 생성되고 toss readiness가 연동되면 상세 준비도가 표시됩니다.</span>
      </div>
    `;
  } else {
    readinessHtml = `
      <div class="table-wrap"><table>
        <thead>
          <tr>
            <th>종목 (Ticker)</th>
            <th>신호 방향</th>
            <th>Eligible</th>
            <th>Toss 보유 여부</th>
            <th>매수 가능 금액 (Buying Power)</th>
            <th>수수료 구조</th>
            <th>경고 여부</th>
            <th>메시지</th>
          </tr>
        </thead>
        <tbody>
          ${tickers.map(ticker => {
            const sig = todaySignals[ticker] || {};
            const readiness = sig.broker_readiness || {};
            const warnInfo = warningsGate[ticker] || {};
            const isHeld = readiness.is_held || false;
            const buyingPower = readiness.buying_power?.amount ?? 0;
            const currency = readiness.buying_power?.currency || "-";
            const comm = readiness.commission_structure || {};
            const hasWarning = warnInfo.has_warning || readiness.warnings?.has_warning || false;
            const warnMsg = warnInfo.message || readiness.warnings?.message || "-";

            return `
              <tr>
                <td class="ticker-cell">${escapeHtml(ticker)}</td>
                <td><strong>${escapeHtml(sig.action || sig.signal || "-")}</strong></td>
                <td>${statusBadge(sig.eligible ? "success" : "blocked", sig.eligible ? "Eligible" : "Blocked")}</td>
                <td>${statusBadge(isHeld ? "warning" : "not_evaluated", isHeld ? "보유 중" : "미보유")}</td>
                <td class="numeric">${formatNumber(buyingPower, 2)} ${escapeHtml(currency)}</td>
                <td class="code" style="font-size:10px">${compactJson(comm) || "-"}</td>
                <td>${statusBadge(hasWarning ? "blocked" : "success", hasWarning ? "위험/정지" : "정상")}</td>
                <td><small style="color:var(--muted)">${escapeHtml(warnMsg)}</small></td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table></div>
    `;
  }

  let slipsHtml = "";
  if (orders.length === 0) {
    slipsHtml = `
      <div class="empty-state">
        <strong>대상 수동 주문이 없습니다.</strong>
        <span>eligible buy 신호가 존재하는 경우 여기에 주문 가이드 전표가 노출됩니다.</span>
      </div>
    `;
  } else {
    slipsHtml = `
      <div class="table-wrap"><table>
        <thead>
          <tr>
            <th>종목</th>
            <th>행동</th>
            <th class="numeric">승인 비중 (Approved %)</th>
            <th class="numeric">주문 예정 금액 (Target Cash)</th>
            <th class="numeric">기준 가격 (Price)</th>
            <th class="numeric">예상 수량 (Est Qty)</th>
          </tr>
        </thead>
        <tbody>
          ${orders.map(o => `
            <tr>
              <td class="ticker-cell"><strong>${escapeHtml(o.ticker)}</strong></td>
              <td><span style="color:var(--status-success);font-weight:bold">${escapeHtml(o.action)}</span></td>
              <td class="numeric">${formatPercent(o.approved_pct, 1)}</td>
              <td class="numeric"><strong>${formatNumber(o.estimated_cash, 2)} ${escapeHtml(o.currency)}</strong></td>
              <td class="numeric">${formatNumber(o.price, 2)}</td>
              <td class="numeric" style="color:var(--brand-primary)"><strong>${formatNumber(o.estimated_quantity, 4)}</strong></td>
            </tr>
          `).join("")}
        </tbody>
      </table></div>
    `;
  }

  let markdownPlan = "# Manual Order Plan Report\n";
  markdownPlan += `Generated At: ${planData.order_plan?.generated_at || new Date().toISOString()}\n\n`;
  markdownPlan += "| Ticker | Action | Approved Pct | Target Cash | Est Price | Est Qty |\n";
  markdownPlan += "|---|---|---|---|---|---|\n";
  orders.forEach(o => {
    markdownPlan += `| \`${o.ticker}\` | **${o.action}** | ${(o.approved_pct * 100).toFixed(1)}% | ${o.estimated_cash.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} ${o.currency} | ${o.price.toLocaleString()} | ${o.estimated_quantity.toFixed(4)} |\n`;
  });
  if (orders.length === 0) {
    markdownPlan += "| - | - | - | - | - | - |\n\n*No eligible buy orders.*";
  }

  return `
    ${sessionHtml}
    
    <div class="section-grid" style="margin-bottom:14px">
      <section class="panel">
        <div class="panel-header">
          <div><h2>수동 주문 전표 (Manual Buy Slips)</h2><p>실제 주문 체결 없이 운영자가 참고용으로 확인하는 slip 목록입니다.</p></div>
          ${statusBadge(orders.length ? "success" : "not_evaluated")}
        </div>
        ${slipsHtml}
        ${renderSourceCaption("order_plan.json · today_signals.json")}
      </section>
      
      <section class="panel">
        <div class="panel-header">
          <div><h2>Markdown 전표 복사</h2><p>카카오톡이나 노션 공유용 전표입니다.</p></div>
          <button class="button button-secondary" type="button" data-command="${escapeHtml(markdownPlan)}">전표 복사</button>
        </div>
        <div class="panel-body">
          <pre class="code" style="max-height: 250px; overflow-y: auto; font-size: 11px; white-space: pre-wrap; margin:0">${escapeHtml(markdownPlan)}</pre>
          ${renderSourceCaption("order_plan.json 쨌 today_signals.json 쨌 generated markdown slips")}
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="panel-header">
        <div><h2>종목별 실시간 준비도 및 경고 상태 (Signal Readiness)</h2><p>투자경고/거래정지/유의종목인 경우 eligible은 false로 자동 강제 차단됩니다.</p></div>
        ${statusBadge("success", "준비도 검사 완료")}
      </div>
      ${readinessHtml}
      ${renderSourceCaption("today_signals.json · stock_warning_gate.json · Toss /api/v1/stocks/{symbol}/warnings")}
    </section>
  `;
}

function renderTossMarket() {
  const status = state.tossStatus || {};
  const market = state.tossMarket;
  const credentials = status.credentials || {};
  const endpointRows = status.endpoints || [];
  const accountData = state.tossAccounts || {};
  const accounts = accountData.accounts || [];
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>Toss Market Data</h1>
        <p>토스증권 Open API의 GET 엔드포인트만 사용하는 읽기 전용 화면입니다. 종목 조회를 실행해도 주문 생성, 정정, 취소 요청은 발생하지 않습니다.</p>
      </div>
      ${statusBadge(status.status === "configured" ? "success" : "warning")}
    </div>
    ${renderDataSourceNote("toss", ["Toss warnings endpoint", "Toss price-limit/orderbook/trades/candles GET"])}
    <section class="status-banner status-${status.status === "configured" ? "success" : "warning"}">
      <div>${statusBadge(status.status === "configured" ? "success" : "warning")}</div>
      <div>
        <h2>${status.status === "configured" ? "Toss API 조회 준비 완료" : "Toss API 키 설정 필요"}</h2>
        <p>${status.status === "configured" ? "Market Data와 계좌 범위 GET 조회를 사용할 수 있습니다. 계좌 조회는 TS_ACCOUNT 또는 --account 값이 필요합니다." : "TS_API_KEY와 TS_SECRET_KEY를 .env 또는 환경변수에 설정하세요."}</p>
      </div>
      <span class="code">READ_ONLY_GET</span>
    </section>
    <section class="metric-grid">
      ${metricCard("API 키", credentials.api_key ? "설정됨" : "없음", credentials.api_key ? "success" : "warning", "값은 화면에 표시하지 않음")}
      ${metricCard("Secret", credentials.secret_key ? "설정됨" : "없음", credentials.secret_key ? "success" : "warning", "값은 화면에 표시하지 않음")}
      ${metricCard("계좌", credentials.account ? "설정됨" : "선택 필요", credentials.account ? "success" : "not_evaluated", "계좌 범위 GET 조회용")}
      ${metricCard("GET 엔드포인트", endpointRows.length, "success", "구현된 read-only API")}
      ${metricCard("계좌 필요 API", status.account_required_for?.length || 0, "not_evaluated", "X-Tossinvest-Account 필요")}
      ${metricCard("POST 요청", "없음", "success", "POST/PATCH/DELETE 미구현")}
    </section>
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div><h2>계좌 선택</h2><p>선택한 계좌는 이 브라우저의 Jayu 콘솔에서 보유/매도가능수량 같은 계좌 범위 GET 조회에 사용됩니다.</p></div>
        ${statusBadge(accountData.status === "success" ? "success" : accountData.status === "failed" ? "failed" : "warning")}
      </div>
      ${renderTossAccountSetup(accountData, accounts)}
      ${renderSourceCaption("Toss Open API accounts GET")}
    </section>
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div><h2>종목 Market snapshot</h2><p>현재가, 종목정보, 주의사항, 상하한가, 호가, 체결, 1일/1분 캔들을 GET으로 묶어 조회합니다.</p></div>
      </div>
      <form id="toss-market-form" class="inline-form">
        <label>
          <span>Symbol</span>
          <input id="toss-symbol-input" name="symbol" value="${escapeHtml(market?.symbol || "AAPL")}" autocomplete="off" inputmode="latin">
        </label>
        <label>
          <span>Account</span>
          ${renderTossAccountControl(accounts)}
        </label>
        <label class="checkbox-field">
          <input id="toss-include-account" name="include_account" type="checkbox" ${state.selectedTossAccount ? "checked" : ""}>
          <span>보유/매도가능수량 포함</span>
        </label>
        <button class="button button-primary" type="submit">조회</button>
      </form>
      ${renderSourceCaption("Toss prices/stocks/warnings/price-limits/orderbook/trades/candles GET")}
      <p id="toss-feedback" class="metric-detail" hidden></p>
    </section>
    ${market ? renderTossSnapshot(market) : renderTossEmptyState(status)}
    <section class="panel">
      <div class="panel-header"><div><h2>구현된 GET 엔드포인트</h2><p>토큰 발급을 제외한 API 호출은 모두 GET입니다.</p></div></div>
      ${renderTossEndpointTable(endpointRows)}
      ${renderSourceCaption("TOSS_GET_ENDPOINTS registry")}
    </section>
  `;
}

function renderTossAccountSetup(accountData, accounts) {
  if (accountData.status === "missing_credentials") {
    return emptyTable(
      "Toss API 키가 필요합니다.",
      "TS_API_KEY와 TS_SECRET_KEY를 설정하면 계좌 목록을 GET으로 조회할 수 있습니다."
    );
  }
  if (accountData.status === "failed") {
    return emptyTable("계좌 조회에 실패했습니다.", accountData.error || "Toss accounts 응답을 확인하세요.");
  }
  if (!accounts.length) {
    return emptyTable("조회 가능한 계좌가 없습니다.", "Toss API 권한과 계좌 연결 상태를 확인하세요.");
  }
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>선택</th><th>계좌</th><th>마스킹 번호</th><th>유형</th><th>통화</th><th>권한</th></tr></thead>
      <tbody>${accounts.map((account) => `
        <tr>
          <td>
            <button class="button ${account.account_seq === state.selectedTossAccount ? "button-primary" : "button-secondary"}" type="button" data-toss-account="${escapeHtml(account.account_seq)}">
              ${account.account_seq === state.selectedTossAccount ? "선택됨" : "선택"}
            </button>
          </td>
          <td><strong>${escapeHtml(account.display_name || "Toss account")}</strong>${account.is_default ? " " + statusBadge("success", "기본") : ""}</td>
          <td class="code">${escapeHtml(account.masked_account_no || "-")}</td>
          <td>${escapeHtml(account.account_type || "-")}</td>
          <td>${escapeHtml(account.currency || "-")}</td>
          <td>${statusBadge("success", "조회")} ${statusBadge("not_evaluated", "주문 비활성")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function filterTossHoldingsByRegion(rows) {
  if (state.tossAccountRegion === "ALL") return rows || [];
  return (rows || []).filter((row) => row.market_region === state.tossAccountRegion);
}

function summarizeTossHoldings(rows, fallbackSummary = {}) {
  if (state.tossAccountRegion === "ALL") {
    return {
      ...fallbackSummary,
      total_market_value_krw: fallbackSummary.total_market_value,
      unrealized_pnl_krw: fallbackSummary.unrealized_pnl,
    };
  }
  const totalMarket = rows.reduce((sum, row) => sum + (Number(row.market_value_krw) || 0), 0);
  const totalCost = rows.reduce((sum, row) => sum + (Number(row.cost_basis_krw) || 0), 0);
  const pnl = rows.reduce((sum, row) => sum + (Number(row.unrealized_pnl_krw) || 0), 0);
  return {
    status: rows.length ? "success" : "not_evaluated",
    holding_count: rows.length,
    total_market_value_krw: totalMarket,
    total_cost_basis_krw: totalCost,
    unrealized_pnl_krw: pnl,
    unrealized_pnl_pct: totalCost ? pnl / totalCost : null,
  };
}

function renderTossRegionTabs(regionTotals) {
  const counts = Object.fromEntries((regionTotals || []).map((row) => [row.region, row.count]));
  const tabs = [
    ["ALL", "전체", Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0)],
    ["KR", "한국", counts.KR || 0],
    ["US", "미국", counts.US || 0],
  ];
  return `<div class="segmented-tabs" role="tablist" aria-label="Toss account market filter">${tabs
    .map(([value, label, count]) => `
      <button class="${state.tossAccountRegion === value ? "is-active" : ""}" type="button" role="tab" data-toss-region="${value}" aria-selected="${state.tossAccountRegion === value}">
        <span>${label}</span><strong>${formatNumber(count, 0)}</strong>
      </button>`)
    .join("")}</div>`;
}

function renderExposureDonut(rows, keyName) {
  const filtered = (rows || []).filter((row) => Number(row.market_value_krw) > 0);
  if (!filtered.length) {
    return '<div class="empty-state"><strong>노출 비중이 없습니다.</strong><span>평가금액 환산이 완료되면 차트가 채워집니다.</span></div>';
  }
  let cursor = 0;
  const colors = ["#175cd3", "#126b45", "#b42318", "#8a4b08", "#475467"];
  const segments = filtered
    .map((row, index) => {
      const start = cursor;
      const end = cursor + Number(row.weight || 0) * 100;
      cursor = end;
      return `${colors[index % colors.length]} ${start}% ${end}%`;
    })
    .join(", ");
  return `
    <div class="donut-layout">
      <div class="donut-chart" style="background: conic-gradient(${segments})" aria-hidden="true"></div>
      <div class="donut-legend">
        ${filtered.map((row, index) => `
          <div class="legend-row">
            <span class="legend-dot" style="background:${colors[index % colors.length]}"></span>
            <strong>${escapeHtml(row[keyName] || "-")}</strong>
            <span>${formatPercent(row.weight, 1)} · ${formatCurrency(row.market_value_krw, "KRW")}</span>
          </div>`).join("")}
      </div>
    </div>`;
}

function renderFxRateCards(rows) {
  const usable = rows || [];
  if (!usable.length) {
    return '<div class="empty-state"><strong>환율 데이터가 없습니다.</strong><span>USD 보유 종목이 있으면 USD/KRW 환율을 조회합니다.</span></div>';
  }
  return `<div class="fx-card-list">${usable
    .map((row) => `
      <div class="fx-card">
        <span>${escapeHtml(row.base_currency || "-")} / ${escapeHtml(row.quote_currency || "-")}</span>
        <strong>${row.rate == null ? "미계산" : formatNumber(row.rate, 4)}</strong>
        <small>${escapeHtml(row.valid_from || row.rate_change_type || row.status || "-")}</small>
      </div>`)
    .join("")}</div>`;
}

function renderSituationTags(rows) {
  const tags = rows || [];
  if (!tags.length) {
    return '<div class="empty-state"><strong>상황 태그가 없습니다.</strong><span>종목 메타와 가격 정보가 보강되면 태그가 채워집니다.</span></div>';
  }
  return `<div class="tag-cloud">${tags
    .map((row) => `
      <div class="tag-pill">
        <strong>${escapeHtml(row.tag || "-")}</strong>
        <span>${formatNumber(row.count, 0)}종목 · ${formatPercent(row.weight, 1)}</span>
      </div>`)
    .join("")}</div>`;
}

function renderPortfolioTypeCards(rows) {
  const items = rows || [];
  if (!items.length) {
    return '<div class="empty-state"><strong>포트폴리오 타입 데이터가 없습니다.</strong><span>holdings 응답과 portfolio_mapping.json을 읽으면 자동으로 채워집니다.</span></div>';
  }
  return `<div class="portfolio-type-grid">${items
    .map((row) => {
      const status = Number(row.warning_count || 0) > 0 ? "warning" : Number(row.count || 0) ? "success" : "not_evaluated";
      return `
        <article class="portfolio-type-card">
          <div class="portfolio-type-card-head">
            <strong>${escapeHtml(row.label || row.type || "-")}</strong>
            ${statusBadge(status, row.risk_level || "risk")}
          </div>
          <p>${escapeHtml(row.description || "")}</p>
          <div class="portfolio-type-metrics">
            <span><b>${formatNumber(row.count, 0)}</b>종목</span>
            <span><b>${formatPercent(row.weight, 1)}</b>비중</span>
            <span><b>${formatCurrency(row.market_value_krw, "KRW")}</b></span>
          </div>
          <small>확인: ${escapeHtml(row.focus || "-")}</small>
          ${(row.checklist || []).length ? `<ul>${row.checklist.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
          ${row.symbols?.length ? `<span class="portfolio-type-symbols">${row.symbols.map(escapeHtml).join(" · ")}</span>` : ""}
          ${renderSourceLabel(row.source || "portfolio_mapping.json · Toss holdings/stocks metadata")}
        </article>`;
    })
    .join("")}</div>`;
}

function renderPortfolioTypeBadges(row) {
  const labels = row.portfolio_type_labels?.length
    ? row.portfolio_type_labels
    : row.primary_portfolio_type_label
      ? [row.primary_portfolio_type_label]
      : [];
  if (!labels.length) return "-";
  return labels.map((label) => `<span>${escapeHtml(label)}</span>`).join("");
}

function renderPnlContributors(rows) {
  const ranked = [...(rows || [])]
    .filter((row) => row.unrealized_pnl_krw !== null && row.unrealized_pnl_krw !== undefined)
    .sort((a, b) => Math.abs(Number(b.unrealized_pnl_krw || 0)) - Math.abs(Number(a.unrealized_pnl_krw || 0)))
    .slice(0, 12);
  if (!ranked.length) {
    return '<div class="empty-state"><strong>손익 기여도가 없습니다.</strong><span>손익 필드가 있는 holdings 응답이면 자동 계산됩니다.</span></div>';
  }
  const maxAbs = Math.max(...ranked.map((row) => Math.abs(Number(row.unrealized_pnl_krw) || 0)), 1);
  return `<div class="pnl-bar-list">${ranked
    .map((row) => {
      const value = Number(row.unrealized_pnl_krw) || 0;
      const width = Math.max(4, Math.min(100, (Math.abs(value) / maxAbs) * 100));
      return `
        <div class="pnl-bar-row ${value < 0 ? "is-negative" : "is-positive"}">
          <div><strong>${escapeHtml(row.symbol || "-")}</strong><span>${escapeHtml(row.name || row.market_region || "-")}</span></div>
          <div class="pnl-bar-track" aria-hidden="true"><span style="width:${width}%"></span></div>
          <div class="pnl-bar-meta">${formatCurrency(value, "KRW")}</div>
        </div>`;
    })
    .join("")}</div>`;
}

function fxRateLabel(rows, baseCurrency) {
  const row = (rows || []).find((item) => item.base_currency === baseCurrency);
  if (!row) return baseCurrency === "USD" ? "불필요" : "-";
  return row.rate == null ? "미계산" : formatNumber(row.rate, 2);
}

function fxRateStatus(rows, baseCurrency) {
  const row = (rows || []).find((item) => item.base_currency === baseCurrency);
  if (!row) return "not_evaluated";
  return row.status === "success" && row.rate != null ? "success" : "warning";
}

function fxRateDetail(rows, baseCurrency) {
  const row = (rows || []).find((item) => item.base_currency === baseCurrency);
  if (!row) return "USD holdings 없음";
  return row.valid_from || row.message || "KRW 환산";
}

function renderTossAccountCards(accounts, selected) {
  if (!accounts.length) {
    return emptyTable("조회 가능한 계좌가 없습니다.", "Toss API 권한과 계좌 연결 상태를 확인하세요.");
  }
  return `<div class="account-card-grid">${accounts
    .map((account) => {
      const isSelected = account.account_seq === selected.account_seq;
      return `
        <button class="account-card ${isSelected ? "is-selected" : ""}" type="button" data-toss-account="${escapeHtml(account.account_seq)}">
          <span>${isSelected ? "Selected" : "Account"}</span>
          <strong>${escapeHtml(account.display_name || "Toss account")}</strong>
          <small class="code">${escapeHtml(account.masked_account_no || "-")}</small>
          <small>${escapeHtml([account.account_type, account.currency].filter(Boolean).join(" / ") || "read only")}</small>
        </button>`;
    })
    .join("")}</div>`;
}

function renderHoldingAllocation(rows) {
  if (!rows?.length) {
    return '<div class="empty-state"><strong>보유 비중 데이터가 없습니다.</strong><span>holdings 응답에 평가금액이 있으면 자동으로 채워집니다.</span></div>';
  }
  return `<div class="holding-allocation">${rows
    .map((row) => {
      const width = Math.max(3, Math.min(100, Number(row.weight || 0) * 100));
      return `
        <div class="holding-bar-row">
          <div>
            <strong>${escapeHtml(row.symbol || "-")}</strong>
            <span>${escapeHtml(row.name || row.currency || "-")}</span>
          </div>
          <div class="holding-bar-track" aria-hidden="true"><span style="width:${width}%"></span></div>
          <div class="holding-bar-meta">
            <strong>${formatPercent(row.weight, 1)}</strong>
            <span>${formatCurrency(row.market_value_krw, "KRW")}</span>
          </div>
        </div>`;
    })
    .join("")}</div>`;
}

function renderTossHoldingsTable(rows) {
  if (!rows?.length) {
    return emptyTable("보유 종목이 없습니다.", "Toss holdings 응답이 비어 있거나 아직 계좌 조회가 완료되지 않았습니다.");
  }
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Symbol</th><th>Market</th><th>투자 타입</th><th>Category</th><th>Sector</th><th>Name</th><th class="numeric">Qty</th><th class="numeric">KRW value</th><th class="numeric">P/L KRW</th><th class="numeric">P/L %</th><th class="numeric">Day %</th><th class="numeric">Weight</th><th>Tags</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${escapeHtml(row.symbol || "-")}</td>
          <td>${statusBadge(row.market_region === "US" ? "warning" : row.market_region === "KR" ? "success" : "not_evaluated", row.market_region || "-")}</td>
          <td class="tag-cell portfolio-type-cell">${renderPortfolioTypeBadges(row)}<small>${escapeHtml(row.portfolio_type_focus || "-")}</small>${renderSourceLabel(row.portfolio_type_source || "portfolio_mapping.json · Toss holdings/stocks metadata")}</td>
          <td>${escapeHtml(row.category || row.asset_type || "-")}</td>
          <td>${escapeHtml(row.sector || "-")}</td>
          <td>${escapeHtml(row.name || "-")}</td>
          <td class="numeric">${formatNumber(row.quantity, 4)}</td>
          <td class="numeric">${formatCurrency(row.market_value_krw, "KRW")}</td>
          <td class="numeric ${Number(row.unrealized_pnl_krw || 0) < 0 ? "negative" : "positive"}">${formatCurrency(row.unrealized_pnl_krw, "KRW")}</td>
          <td class="numeric ${Number(row.unrealized_pnl_pct || 0) < 0 ? "negative" : "positive"}">${formatPercent(row.unrealized_pnl_pct, 2)}</td>
          <td class="numeric ${Number(row.day_change_pct || 0) < 0 ? "negative" : "positive"}">${formatPercent(row.day_change_pct, 2)}</td>
          <td class="numeric">${formatPercent(row.weight, 1)}</td>
          <td class="tag-cell">${(row.situation_tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("") || "-"}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderTossAccountControl(accounts) {
  if (!accounts.length) {
    return `<input id="toss-account-input" name="account" value="${escapeHtml(state.selectedTossAccount)}" autocomplete="off" placeholder="선택 사항">`;
  }
  return `
    <select id="toss-account-input" name="account">
      <option value="">계좌 범위 조회 안 함</option>
      ${accounts.map((account) => `
        <option value="${escapeHtml(account.account_seq)}" ${account.account_seq === state.selectedTossAccount ? "selected" : ""}>
          ${escapeHtml(`${account.display_name || "Toss"} ${account.masked_account_no || ""}`.trim())}
        </option>`).join("")}
    </select>`;
}

function renderTossSnapshot(market) {
  const summary = market.summary || {};
  const sections = market.sections || {};
  const accountSections = market.account_sections || {};
  return `
    <section class="metric-grid">
      ${metricCard("조회 종목", market.symbol || "-", summary.status || "not_evaluated", "대문자 정규화")}
      ${metricCard("성공 섹션", summary.successful_sections || 0, summary.failed_sections ? "warning" : "success", "Market Data GET")}
      ${metricCard("실패 섹션", summary.failed_sections || 0, summary.failed_sections ? "failed" : "success", "개별 API 오류")}
      ${metricCard("계좌 섹션", summary.account_sections_included ? "포함" : "제외", "not_evaluated", "보유/매도가능수량")}
      ${metricCard("Read-only", market.read_only ? "예" : "아니오", market.read_only ? "success" : "blocked", "주문 요청 없음")}
      ${metricCard("다음 행동", summary.failed_sections ? "오류 확인" : "분석 계속", summary.failed_sections ? "warning" : "success", "섹션별 메시지 확인")}
    </section>
    <div class="section-grid">
      <section class="panel">
        <div class="panel-header"><div><h2>Market Data 결과</h2><p>가격, 종목정보, 호가, 체결, 캔들 응답 요약</p></div></div>
        ${renderTossSectionTable(sections)}
        ${renderSourceCaption("Toss prices/stocks/warnings/price-limits/orderbook/trades/candles GET")}
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>계좌 범위 결과</h2><p>선택한 경우에만 호출됩니다.</p></div></div>
        ${renderTossSectionTable(accountSections)}
        ${renderSourceCaption("Toss holdings/sellable-quantity GET")}
      </section>
    </div>
  `;
}

function renderTossEmptyState(status) {
  return `
    <section class="panel" style="margin-bottom:14px">
      ${emptyTable(
        status.status === "configured" ? "아직 조회한 종목이 없습니다." : "Toss API 키가 아직 준비되지 않았습니다.",
        status.status === "configured" ? "위 폼에서 AAPL, 005930 같은 심볼을 입력해 조회하세요." : "TS_API_KEY와 TS_SECRET_KEY를 설정한 뒤 새로고침하세요."
      )}
      ${renderSourceCaption("Toss status config 쨌 symbol form input 쨌 read-only GET policy")}
    </section>
  `;
}

function renderTossEndpointTable(rows) {
  if (!rows?.length) return emptyTable("엔드포인트 카탈로그가 없습니다.", "Toss status API 응답을 확인하세요.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Operation</th><th>Method</th><th>Path</th><th>Account</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="code">${escapeHtml(row.operation_id)}</td>
          <td>${statusBadge(row.method === "GET" ? "success" : "blocked", row.method)}</td>
          <td class="code">${escapeHtml(row.path)}</td>
          <td>${row.requires_account ? statusBadge("warning", "필요") : statusBadge("not_evaluated", "불필요")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderTossSectionTable(sections) {
  const entries = Object.entries(sections || {});
  if (!entries.length) return emptyTable("호출된 계좌 범위 섹션이 없습니다.", "계좌 정보를 포함하려면 체크박스를 선택하세요.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Section</th><th>Status</th><th class="numeric">Latency</th><th>Operation</th><th>Payload / Error</th></tr></thead>
      <tbody>${entries.map(([name, row]) => `
        <tr>
          <td><strong>${escapeHtml(name)}</strong></td>
          <td>${statusBadge(row.status === "success" ? "success" : "failed")}</td>
          <td class="numeric">${formatNumber(row.latency_ms, 1)} ms</td>
          <td class="code">${escapeHtml(row.operation_id || "-")}</td>
          <td class="code toss-payload">${escapeHtml(row.status === "success" ? compactJson(row.payload) : row.message || "-")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

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

function renderPrimaryAction(action) {
  if (!action) {
    return `
      <article class="primary-action-card">
        <span class="metric-label">가장 중요한 다음 행동</span>
        <strong>추가 조치 없음</strong>
        <p>현재 run에서 즉시 수행할 안전 조치가 없습니다.</p>
        ${renderSourceLabel("recommended_actions from safety verdict")}
      </article>`;
  }
  const attrs = action.page
    ? `data-go="${escapeHtml(action.page)}"`
    : `data-command="${escapeHtml(action.command || "")}"`;
  const detail = action.command
    ? "명령을 클립보드에 복사합니다. 대시보드는 실행하지 않습니다."
    : "관련 화면으로 이동해 근거를 확인합니다.";
  return `
    <article class="primary-action-card">
      <span class="metric-label">가장 중요한 다음 행동</span>
      <strong>${escapeHtml(action.label || "검토 계속")}</strong>
      <p>${escapeHtml(detail)}</p>
      ${renderSourceLabel("recommended_actions from safety verdict")}
      <button class="button button-primary" type="button" ${attrs}>${escapeHtml(action.label || "확인")}</button>
    </article>`;
}

function renderReasons(reasons, actions = []) {
  if (!reasons.length) {
    return '<div class="empty-state"><strong>중요 경고가 없습니다.</strong><span>필수 검증 결과를 계속 확인하세요.</span></div>';
  }
  return `<ol class="reason-list">${reasons
    .map((reason) => {
      const action = reason.action || actions.find((item) => item.id === `review-${reason.component}`) || {};
      const attrs = action.page
        ? `data-go="${escapeHtml(action.page)}"`
        : action.command
          ? `data-command="${escapeHtml(action.command)}"`
          : "";
      const tickerText = (reason.affected_tickers || []).length
        ? `영향 종목: ${(reason.affected_tickers || []).join(", ")}`
        : reason.count
          ? `영향 건수: ${reason.count}`
          : "영향 종목 미기록";
      return `
      <li class="reason-item">
        <strong class="code">${escapeHtml(reason.code)}</strong>
        <p>${escapeHtml(reason.message)}</p>
        <small>${escapeHtml(tickerText)}</small>
        <small>${escapeHtml(reason.remediation)}</small>
        ${attrs ? `<button class="button button-secondary reason-action" type="button" ${attrs}>${escapeHtml(action.label || "관련 화면 확인")}</button>` : ""}
      </li>`;
    })
    .join("")}</ol>`;
}

function decisionHeadline(status) {
  return {
    success: "오늘 결론: 운영 검토 가능",
    warning: "오늘 결론: 검토 필요",
    failed: "오늘 결론: 실행 실패",
    blocked: "오늘 결론: 운영 차단",
    validating: "오늘 결론: 검증 중",
    data_error: "오늘 결론: 데이터 오류",
    not_evaluated: "오늘 결론: 판단 보류",
  }[status] || "오늘 결론: 확인 필요";
}

function renderSignalTable(rows) {
  if (!rows?.length) return emptyTable("생성된 신호가 없습니다.", "선택한 run에는 signal artifact가 없습니다.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>종목</th><th>상태</th><th>행동</th><th>전략</th><th class="numeric">점수</th><th class="numeric">진입가</th><th>데이터</th><th>Reason code</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${escapeHtml(row.ticker)}</td>
          <td>${statusBadge(row.status)}</td>
          <td>${escapeHtml(row.action || "-")}</td>
          <td>${escapeHtml(row.strategy || "-")}</td>
          <td class="numeric">${formatNumber(row.score)}</td>
          <td class="numeric">${formatNumber(row.entry_price)}</td>
          <td>${row.data_verified === true ? statusBadge("success") : row.data_verified === false ? statusBadge("data_error") : statusBadge("not_evaluated")}</td>
          <td class="code">${escapeHtml((row.reason_codes || []).join(", ") || "-")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderSourcesTable(rows) {
  if (!rows?.length) return emptyTable("Provider 수집 기록이 없습니다.", "비교 대상이 없으므로 검증 성공으로 간주하지 않습니다.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Provider</th><th>종목</th><th>상태</th><th class="numeric">행 수</th><th>첫 날짜</th><th>마지막 날짜</th><th>Hash</th><th>오류</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td>${escapeHtml(row.provider || "-")}</td>
          <td class="ticker-cell">${escapeHtml(row.ticker || row.symbol || "-")}</td>
          <td>${statusBadge(row.status === "success" ? "success" : "failed")}</td>
          <td class="numeric">${formatNumber(row.rows, 0)}</td>
          <td class="nowrap">${escapeHtml(row.first_date || "-")}</td>
          <td class="nowrap">${escapeHtml(row.last_date || "-")}</td>
          <td class="code" title="${escapeHtml(row.hash || "")}">${escapeHtml(shortHash(row.hash))}</td>
          <td>${escapeHtml(row.error || "-")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderMismatchTable(rows) {
  if (!rows?.length) return emptyTable("임계값 초과 불일치가 없습니다.", "Provider 비교가 실행되지 않았다면 상단 상태는 미검증으로 유지됩니다.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>종목</th><th>날짜</th><th>필드</th><th>Providers</th><th>값 / 누락</th><th class="numeric">차이</th><th class="numeric">한도</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${escapeHtml(row.ticker || "-")}</td>
          <td class="nowrap">${escapeHtml(row.date || "-")}</td>
          <td>${escapeHtml(row.field || "-")}</td>
          <td>${escapeHtml([row.baseline, row.candidate].filter(Boolean).join(" / ") || "-")}</td>
          <td class="code">${escapeHtml(row.kind === "date" ? `missing: ${(row.missing_in || []).join(", ")}` : Object.entries(row.values || {}).map(([key, value]) => `${key}=${value}`).join(" / "))}</td>
          <td class="numeric">${row.relative_delta == null ? "-" : formatPercent(row.relative_delta, 3)}</td>
          <td class="numeric">${row.threshold == null ? "-" : formatPercent(row.threshold, 3)}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderRiskChecks(rows) {
  if (!rows?.length) return emptyTable("리스크 게이트가 평가되지 않았습니다.", "심사 대상 신호와 portfolio snapshot을 확인하세요.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>상태</th><th>종목</th><th>지표</th><th class="numeric">현재값</th><th class="numeric">한도</th><th class="numeric">초과값</th><th>Reason code</th></tr></thead>
      <tbody>${rows.map((row) => {
        const observed = Number(row.observed);
        const limit = Number(row.limit);
        const ratio = Number.isFinite(observed) && Number.isFinite(limit) && limit !== 0 ? Math.abs(observed / limit) : 0;
        return `
        <tr>
          <td>${statusBadge(row.status)}</td>
          <td class="ticker-cell">${escapeHtml(row.ticker || "-")}</td>
          <td class="threshold-cell">${escapeHtml(row.metric || row.message || "-")}
            ${Number.isFinite(ratio) && ratio > 0 ? `<div class="threshold-track ${row.status === "blocked" ? "is-blocked" : ""}"><span style="width:${Math.min(100, ratio * 100)}%"></span></div>` : ""}
          </td>
          <td class="numeric">${formatNumber(row.observed, 4)}</td>
          <td class="numeric">${formatNumber(row.limit, 4)}</td>
          <td class="numeric">${formatNumber(row.excess, 4)}</td>
          <td class="code">${escapeHtml(row.code || "-")}</td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>`;
}

function renderRiskSignals(rows) {
  if (!rows?.length) return emptyTable("종목별 리스크 결과가 없습니다.", "Risk explanation artifact가 아직 생성되지 않았습니다.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>종목</th><th>행동</th><th>상태</th><th class="numeric">승인 비중</th><th class="numeric">통과</th><th class="numeric">실패</th><th>Reason code</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${escapeHtml(row.ticker || "-")}</td>
          <td>${escapeHtml(row.action || "-")}</td>
          <td>${statusBadge(row.eligible ? "success" : row.reviewed === false ? "not_evaluated" : "blocked")}</td>
          <td class="numeric">${row.approved_position_pct == null ? "미계산" : formatPercent(row.approved_position_pct)}</td>
          <td class="numeric">${(row.passed || []).length}</td>
          <td class="numeric">${(row.failed || []).length}</td>
          <td class="code">${escapeHtml((row.failed || []).map((item) => item.code).filter(Boolean).join(", ") || "-")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderSignalDetailTable(rows) {
  if (!rows?.length) return emptyTable("선택한 run의 신호가 없습니다.", "run-local signal artifact가 없습니다. 전역 today_signals.json은 run 검토에 섞지 않습니다.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>종목</th><th>상태</th><th>행동</th><th>전략</th><th class="numeric">점수</th><th class="numeric">진입가</th><th class="numeric">손절가</th><th class="numeric">목표가</th><th class="numeric">승인 비중</th><th>유동성</th><th>데이터</th><th>Reason code</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${escapeHtml(row.ticker || "-")}</td>
          <td>${statusBadge(row.status)}</td>
          <td>${escapeHtml(row.action || "-")}</td>
          <td>${escapeHtml(row.strategy || "-")}</td>
          <td class="numeric">${formatNumber(row.score)}</td>
          <td class="numeric">${formatNumber(row.entry_price)}</td>
          <td class="numeric">${formatNumber(row.stop_price)}</td>
          <td class="numeric">${formatNumber(row.target_price)}</td>
          <td class="numeric">${row.approved_position_pct == null ? "미계산" : formatPercent(row.approved_position_pct)}</td>
          <td>${statusBadge(row.liquidity_status || "not_evaluated")}</td>
          <td>${row.data_verified === true ? statusBadge("success") : row.data_verified === false ? statusBadge("data_error") : statusBadge("not_evaluated")}</td>
          <td class="code">${escapeHtml((row.reason_codes || []).join(", ") || "-")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderTraderSignalLadder(rows) {
  if (!rows?.length) return emptyTable("No signal rows found.", "Run-local signals are required before Trader Lens can score reward/risk.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Ticker</th><th>Status</th><th class="numeric">R/R</th><th class="numeric">Risk</th><th class="numeric">Reward</th><th class="numeric">Entry</th><th class="numeric">Stop</th><th class="numeric">Target</th><th>Data</th><th>Reason code</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${escapeHtml(row.ticker || "-")}</td>
          <td>${statusBadge(row.review_priority || row.status)}</td>
          <td class="numeric"><strong>${row.reward_to_risk == null ? "-" : `${formatNumber(row.reward_to_risk, 2)}R`}</strong></td>
          <td class="numeric">${formatPercent(row.risk_pct, 2)}</td>
          <td class="numeric">${formatPercent(row.reward_pct, 2)}</td>
          <td class="numeric">${formatNumber(row.entry_price)}</td>
          <td class="numeric">${formatNumber(row.stop_price)}</td>
          <td class="numeric">${formatNumber(row.target_price)}</td>
          <td>${row.data_verified === true ? statusBadge("success") : row.data_verified === false ? statusBadge("data_error") : statusBadge("not_evaluated")}</td>
          <td class="code">${escapeHtml((row.reason_codes || []).join(", ") || "-")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderProviderTrustMap(rows) {
  if (!rows?.length) return emptyTable("No provider trust rows.", "Data source artifacts are missing or provider comparison has not run.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Provider</th><th>Ticker</th><th>Status</th><th class="numeric">Rows</th><th class="numeric">Mismatches</th><th>Dates</th><th>Hash</th><th>Error</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td><span class="provider-chip">${escapeHtml(row.provider || "-")}</span></td>
          <td class="ticker-cell">${escapeHtml(row.ticker || "-")}</td>
          <td>${statusBadge(row.status)}</td>
          <td class="numeric">${formatNumber(row.rows, 0)}</td>
          <td class="numeric">${formatNumber(row.mismatch_count, 0)}</td>
          <td class="nowrap">${escapeHtml([row.first_date, row.last_date].filter(Boolean).join(" to ") || "-")}</td>
          <td class="code" title="${escapeHtml(row.hash || "")}">${escapeHtml(row.hash_short || shortHash(row.hash))}</td>
          <td>${escapeHtml(row.error || "-")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderRiskConcentration(rows) {
  if (!rows?.length) {
    return '<div class="empty-state"><strong>No blocked risk codes.</strong><span>Risk concentration is clean for the selected run.</span></div>';
  }
  const maxCount = Math.max(...rows.map((row) => Number(row.count) || 0), 1);
  return `<div class="risk-bar-list">${rows
    .map((row) => {
      const width = Math.max(4, Math.min(100, ((Number(row.count) || 0) / maxCount) * 100));
      return `
        <div class="risk-bar-row">
          <div>
            <strong class="code">${escapeHtml(row.code)}</strong>
            <span>${escapeHtml((row.tickers || []).join(", ") || "portfolio")}</span>
          </div>
          <div class="risk-bar-track" aria-hidden="true"><span style="width:${width}%"></span></div>
          <div class="risk-bar-meta">
            <strong>${formatNumber(row.count, 0)}</strong>
            <span>max excess ${formatNumber(row.max_excess, 4)}</span>
          </div>
        </div>`;
    })
    .join("")}</div>`;
}

function renderTraderDecisionNotes(notes) {
  if (!notes.length) {
    return '<div class="empty-state"><strong>No blocker notes.</strong><span>The run verdict did not produce a top blocker list.</span></div>';
  }
  return `<ol class="reason-list">${notes
    .map((note) => `
      <li class="reason-item">
        <strong class="code">${escapeHtml(note.code || "REVIEW")}</strong>
        <p>${escapeHtml(note.message || note.remediation || "Review required")}</p>
        <small>${escapeHtml(note.component || "run")}</small>
      </li>`)
    .join("")}</ol>`;
}

function renderCriteriaTable(rows) {
  if (!rows?.length) return emptyTable("승격 조건 기록이 없습니다.", "현재 상태에서 promotion이 아직 평가되지 않았습니다.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>조건</th><th>상태</th><th class="numeric">현재값</th><th class="numeric">필수 기준</th><th>부족분</th></tr></thead>
      <tbody>${rows.map((row) => {
        const observed = Number(row.observed);
        const required = Number(row.required);
        const gap = Number.isFinite(observed) && Number.isFinite(required) ? required - observed : null;
        return `
        <tr>
          <td>${escapeHtml(row.name || "-")}</td>
          <td>${statusBadge(row.passed ? "success" : "blocked")}</td>
          <td class="numeric">${formatNumber(row.observed, 4)}</td>
          <td class="numeric">${formatNumber(row.required, 4)}</td>
          <td class="numeric">${gap == null ? "미계산" : formatNumber(Math.max(0, gap), 4)}</td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>`;
}

function renderPromotionHistory(rows) {
  if (!rows?.length) return emptyTable("Shadow 이력이 없습니다.", "승격 전에 shadow 모드를 며칠 더 실행하세요.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>날짜</th><th class="numeric">신호</th><th class="numeric">매수</th><th class="numeric">완료</th><th class="numeric">데이터 검증</th><th class="numeric">불일치</th><th class="numeric">리스크 통과</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="nowrap">${escapeHtml(row.date || "-")}</td>
          <td class="numeric">${formatNumber(row.signal_count, 0)}</td>
          <td class="numeric">${formatNumber(row.buy_count, 0)}</td>
          <td class="numeric">${formatNumber(row.completed_count, 0)}</td>
          <td class="numeric">${formatNumber(row.data_verified_count, 0)}</td>
          <td class="numeric">${formatNumber(row.provider_disagreement_count, 0)}</td>
          <td class="numeric">${formatNumber(row.risk_pass_count, 0)}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderSettingsRules(rows) {
  if (!rows?.length) return emptyTable("검증 규칙이 없습니다.", "설정 검증 결과를 평가할 수 없습니다.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>상태</th><th>규칙</th><th>현재값</th><th>필수 기준</th><th>영향</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td>${statusBadge(row.status)}</td>
          <td><strong>${escapeHtml(row.label || row.key)}</strong><br><span class="code">${escapeHtml(row.key)}</span></td>
          <td class="code">${escapeHtml(formatSettingValue(row.current))}</td>
          <td class="code">${escapeHtml(formatSettingValue(row.required))}</td>
          <td>${escapeHtml(row.message || "-")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function formatSettingValue(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
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

function renderApiMonitoring() {
  const data = state.apiMonitoring;
  const summary = data.summary;
  const providers = data.providers || [];
  const categories = data.categories || [];
  const disagreements = data.disagreements || [];
  const notifFailures = data.notification_failures || [];
  const kakao = data.kakao_status || {};
  const cacheStats = data.cache_stats || {};
  const config = data.config || {};
  const runCtx = data.run_context || {};

  const monitoringStatusLabel = {
    success: "모든 데이터 출처 정상",
    warning: "일부 출처에 경고가 있습니다",
    failed: "실패한 데이터 출처가 있습니다",
  }[summary.status] || "상태 확인 필요";

  const selectedRefresh = state.apiMonitoringRefreshSec || "off";

  els.root.innerHTML = `
    <div class="page-heading" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
      <div>
        <h1>API 데이터 출처 모니터링</h1>
        <p>프로젝트에서 사용하는 모든 외부 API 데이터 출처의 상태, 자격증명, 정책, 캐시, 최근 활동을 확인합니다.</p>
      </div>
      <div style="display:flex; align-items:center; gap:12px;">
        <div class="auto-refresh-control" style="display:flex; align-items:center; gap:6px; font-size:12px; background:#ffffff; padding:6px 12px; border-radius:6px; border:1px solid var(--border); box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
          <span style="font-weight:600; color:var(--text-muted);">자동 갱신</span>
          <select id="select-auto-refresh" style="font-size:12px; padding:2px 6px; border-radius:4px; border:1px solid var(--border); background:#ffffff; cursor:pointer;">
            <option value="off" ${selectedRefresh === "off" ? "selected" : ""}>꺼짐</option>
            <option value="10" ${selectedRefresh === "10" ? "selected" : ""}>10초</option>
            <option value="30" ${selectedRefresh === "30" ? "selected" : ""}>30초</option>
          </select>
        </div>
        <button class="button button-primary" id="btn-ping-all" type="button" style="padding: 8px 14px; font-size: 12px; font-weight:600; display:inline-flex; align-items:center; gap:6px;">모든 API 연결 테스트</button>
        ${statusBadge(summary.status)}
      </div>
    </div>
    ${renderDataSourceNote("api-monitoring")}
    <section class="status-banner status-${statusClass(summary.status)}">
      <div>${statusBadge(summary.status)}</div>
      <div>
        <h2>${monitoringStatusLabel}</h2>
        <p>${runCtx.run_id ? `최근 실행 <strong>${escapeHtml(runCtx.run_id)}</strong> 기준 (${formatDate(runCtx.finished_at)})` : "완료된 실행 기록이 없습니다. Provider 정책과 자격증명만 표시합니다."}</p>
      </div>
      <span class="code">${summary.failed_count ? "PROVIDER_FAILURE" : summary.partial_count ? "PARTIAL_FAILURE" : "ALL_SOURCES_OK"}</span>
    </section>
    <section class="metric-grid" aria-label="API 출처 요약">
      ${metricCard("전체 Provider", summary.total_providers, "not_evaluated", `${categories.length}개 카테고리`)}
      ${metricCard("자격증명 설정", `${summary.configured_count}/${summary.total_providers}`, summary.configured_count === summary.total_providers ? "success" : "warning", "환경변수 또는 설정 파일")}
      ${metricCard("활성 Provider", summary.active_count, summary.active_count ? "success" : "not_evaluated", "현재 설정에서 사용 중")}
      ${metricCard("실패", summary.failed_count, summary.failed_count ? "failed" : "success", "최근 run 기준")}
      ${metricCard("불일치", summary.disagreement_count, summary.disagreement_count ? "data_error" : "success", "provider간 데이터 차이")}
      ${metricCard("알림 실패", summary.notification_failure_count, summary.notification_failure_count ? "warning" : "success", "카카오 알림 기록")}
    </section>
    ${renderProviderCards(providers, categories)}
    <div class="section-grid">
      <section class="panel">
        <div class="panel-header"><div><h2>데이터 설정 요약</h2><p>현재 설정 파일의 provider 관련 설정입니다.</p></div></div>
        <div class="panel-body">
          <div class="config-summary-grid">
            ${configItem("Primary Provider", config.primary_price_provider || "-")}
            ${configItem("Fallback Provider", config.fallback_price_provider || "none")}
            ${configItem("Cross Validation", config.cross_validation_mode || "off")}
            ${configItem("CV Providers", (config.cross_validation_providers || []).join(", ") || "없음")}
            ${configItem("Supplemental", (config.supplemental_providers || []).join(", ") || "없음")}
            ${configItem("불일치 정책", config.price_disagreement_policy || "-")}
          </div>
          ${renderSourceCaption("config.json provider settings")}
        </div>
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>카카오 알림 상태</h2><p>토큰과 자격증명 설정 여부입니다.</p></div></div>
        <div class="panel-body">
          <div class="config-summary-grid">
            ${configItem("Access Token", kakao.has_access_token ? "설정됨 ✓" : "미설정")}
            ${configItem("Refresh Token", kakao.has_refresh_token ? "설정됨 ✓" : "미설정")}
            ${configItem("REST API Key", kakao.has_rest_api_key ? "설정됨 ✓" : "미설정")}
            ${configItem("Client Secret", kakao.has_client_secret ? "설정됨 ✓" : "미설정")}
          </div>
          ${renderSourceCaption("environment / Kakao credential presence check")}
        </div>
      </section>
    </div>
    ${renderCacheStatsPanel(cacheStats)}
    ${renderEnvTemplatePanel(providers, kakao)}
    ${renderApiLogsPanel(data.api_logs || [])}
    ${disagreements.length ? renderDisagreementsPanel(disagreements) : ""}
    ${notifFailures.length ? renderNotificationFailuresPanel(notifFailures) : ""}
  `;
}


function renderProviderCards(providers, categories) {
  const grouped = {};
  for (const cat of categories) {
    grouped[cat.key] = { label: cat.label, icon: cat.icon, items: [] };
  }
  for (const p of providers) {
    if (grouped[p.category]) {
      grouped[p.category].items.push(p);
    }
  }

  let html = '<section class="panel" style="margin-bottom:14px"><div class="panel-header"><div><h2>Provider 상태</h2><p>카테고리별 API 데이터 출처의 자격증명, 정책, 최근 활동을 확인합니다.</p></div></div>';

  for (const key of Object.keys(grouped)) {
    const group = grouped[key];
    if (!group.items.length) continue;
    html += `<div class="category-separator">${group.icon} ${escapeHtml(group.label)}</div>`;
    html += '<div class="provider-grid">';
    for (const p of group.items) {
      html += renderProviderCard(p);
    }
    html += '</div>';
  }

  html += `${renderSourceCaption("provider registry · config.json · latest run API events")}</section>`;
  return html;
}

function renderProviderCard(p) {
  const policy = p.policy || {};
  const recent = p.recent || {};
  const statusCls = {
    success: "pmc-success",
    partial: "pmc-partial",
    failed: "pmc-failed",
    unused: "pmc-unused",
  }[recent.status] || "pmc-unused";

  const recentStatusLabel = {
    success: "성공",
    partial: "일부 실패",
    failed: "실패",
    unused: "미사용",
  }[recent.status] || "미사용";

  const credClass = p.credential_configured ? "is-set" : "is-missing";
  let credLabel = p.credential_configured ? "인증 설정됨" : "인증 미설정";
  if (p.name === "openfigi") {
    credLabel = p.credential_configured ? "인증 설정됨 (제한 완화)" : "인증 미설정 (기본 한도)";
  }

  const envTags = (p.env_names || []).length
    ? `<div class="pmc-env-list">${p.env_names.map((e) => `<span class="pmc-env-tag">${escapeHtml(e)}</span>`).join("")}</div>`
    : "";

  const cacheTtlLabel = policy.cache_ttl_seconds
    ? policy.cache_ttl_seconds >= 3600
      ? `${(policy.cache_ttl_seconds / 3600).toFixed(1)}h`
      : `${Math.round(policy.cache_ttl_seconds / 60)}m`
    : "-";

  // Calculate Success Rate
  const totalRequests = (recent.success_count || 0) + (recent.failed_count || 0);
  const successRate = totalRequests > 0
    ? Math.round((recent.success_count || 0) / totalRequests * 100)
    : 100;

  let successRateColor = "var(--success)";
  if (recent.status === "unused") {
    successRateColor = "var(--border-strong)";
  } else if (successRate < 100 && successRate > 0) {
    successRateColor = "var(--warning)";
  } else if (successRate === 0 && totalRequests > 0) {
    successRateColor = "var(--failed)";
  }

  const showProgressBar = recent.status !== "unused" && totalRequests > 0;
  const progressHtml = showProgressBar
    ? `
      <div class="pmc-success-bar-container" style="margin: 10px 0 6px 0;">
        <div class="pmc-success-bar-header" style="display:flex; justify-content:space-between; align-items:center; font-size:11px; margin-bottom:4px;">
          <span style="color:var(--text-muted)">수집 성공률</span>
          <strong style="color:${successRateColor}">${successRate}%</strong>
        </div>
        <div class="pmc-success-bar-track" style="height:6px; background:#f0f3f7; border-radius:3px; overflow:hidden; border: 1px solid var(--border);">
          <div class="pmc-success-bar-fill" style="height:100%; width:${successRate}%; background-color:${successRateColor}; border-radius:3px; transition:width 0.3s ease;"></div>
        </div>
      </div>
    `
    : `
      <div class="pmc-success-bar-container" style="margin: 10px 0 6px 0;">
        <div class="pmc-success-bar-header" style="display:flex; justify-content:space-between; align-items:center; font-size:11px; margin-bottom:4px;">
          <span style="color:var(--text-muted)">수집 기록 없음 (미사용)</span>
          <strong style="color:var(--text-muted)">-</strong>
        </div>
        <div class="pmc-success-bar-track" style="height:6px; background:#f0f3f7; border-radius:3px; overflow:hidden; border: 1px solid var(--border);">
          <div class="pmc-success-bar-fill" style="height:100%; width:0%; background-color:var(--border-strong); border-radius:3px;"></div>
        </div>
      </div>
    `;

  return `
    <article class="provider-monitor-card ${statusCls}">
      <div class="pmc-header">
        <div class="pmc-header-left">
          <strong>${escapeHtml(p.display_name)}</strong>
          <span class="pmc-category-badge">${escapeHtml(p.category)}</span>
          ${p.in_use ? '<span class="pmc-category-badge" style="background:#e8f5ee;border-color:#8bc9aa;color:#126b45">활성</span>' : ""}
        </div>
        <span class="pmc-credential ${credClass}">${credLabel}</span>
      </div>
      <span class="pmc-url">${escapeHtml(p.base_url)}</span>
      <div class="pmc-detail-row">
        <span class="policy-tag">timeout <strong>${policy.timeout_seconds ?? "-"}s</strong></span>
        <span class="policy-tag">retry <strong>${policy.retries ?? "-"}</strong></span>
        <span class="policy-tag">rate <strong>${policy.rate_limit_per_minute ?? "-"}/min</strong></span>
        <span class="policy-tag">cache <strong>${cacheTtlLabel}</strong></span>
        ${!p.enabled ? '<span class="policy-tag" style="color:var(--failed);border-color:var(--failed)">비활성</span>' : ""}
      </div>
      ${envTags}
      ${progressHtml}
      <div class="pmc-activity">
        <div class="pmc-activity-item">
          <span>최근 상태</span>
          <strong class="${recent.status === "success" ? "positive" : recent.status === "failed" ? "negative" : ""}">${recentStatusLabel}</strong>
        </div>
        <div class="pmc-activity-item">
          <span>성공 / 실패</span>
          <strong>${recent.success_count ?? 0} / ${recent.failed_count ?? 0}</strong>
        </div>
        <div class="pmc-activity-item">
          <span>수집 행 수</span>
          <strong>${formatNumber(recent.total_rows, 0)}</strong>
        </div>
        <div class="pmc-activity-item">
          <span>소스 수</span>
          <strong>${(recent.sources || []).length}</strong>
        </div>
      </div>
      <div class="pmc-footer">
        <button class="btn-pm-action btn-test" data-test-provider="${escapeHtml(p.name)}" type="button">연결 테스트</button>
        <span class="pmc-test-result" id="test-result-${escapeHtml(p.name)}"></span>
      </div>
    </article>
  `;
}

function renderCacheStatsPanel(cacheStats) {
  const entries = Object.entries(cacheStats);
  if (!entries.length) {
    return `
      <section class="panel" style="margin-bottom:14px">
        <div class="panel-header"><div><h2>캐시 상태</h2><p>캐시 디렉터리 통계입니다.</p></div></div>
        <div class="panel-body"><div class="empty-state"><strong>캐시 데이터 없음</strong>실행 후 캐시가 생성됩니다.</div>${renderSourceCaption("provider cache directories")}</div>
      </section>
    `;
  }
  return `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header" style="display:flex; justify-content:space-between; align-items:center;">
        <div><h2>캐시 상태</h2><p>provider별 캐시 디렉터리의 파일 수와 용량입니다.</p></div>
        <button class="btn-pm-action btn-clear-cache" data-clear-cache="all" type="button">전체 캐시 비우기</button>
      </div>
      <div class="panel-body">
        <div class="cache-stat-grid">
          ${entries.map(([name, stat]) => `
            <div class="cache-stat-card" style="display:flex; justify-content:space-between; align-items:center; width:100%;">
              <div>
                <strong>${escapeHtml(name)}</strong>
                <span>${stat.file_count ?? 0}개 파일 · ${formatBytes(stat.total_bytes ?? 0)}</span>
              </div>
              <button class="btn-pm-action btn-clear-cache" data-clear-cache="${escapeHtml(name)}" style="padding: 2px 8px; font-size: 10px;" type="button">비우기</button>
            </div>
          `).join("")}
        </div>
        ${renderSourceCaption("provider cache directories")}
      </div>
    </section>
  `;
}


function renderEnvTemplatePanel(providers, kakao) {
  return `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header" style="display:flex; justify-content:space-between; align-items:center;">
        <div>
          <h2>환경 변수 (.env) 구성 도우미</h2>
          <p>프로젝트 루트의 <code>.env</code> 파일에 설정할 수 있는 환경 변수 템플릿입니다. 미설정된 키를 입력하여 환경을 완성하세요.</p>
        </div>
        <button class="btn-pm-action btn-test" id="btn-copy-env-template" type="button">템플릿 복사</button>
      </div>
      <div class="panel-body">
        <pre class="code-block" style="background:#1e1e1e; color:#d4d4d4; padding:16px; border-radius:6px; font-family:'Cascadia Code',Consolas,monospace; font-size:12px; line-height:1.6; overflow-x:auto; margin:0;" id="env-template-text">${renderEnvTemplateText(providers, kakao)}</pre>
        ${renderSourceCaption("provider registry · missing environment keys")}
      </div>
    </section>
  `;
}

function renderEnvTemplateText(providers, kakao) {
  let text = "";
  const toss = providers.find(p => p.name === "toss") || {};
  text += `# --- Toss Securities ---\n`;
  text += `TS_API_KEY=${toss.credential_configured ? "******** # ✓ 설정됨" : "your_toss_api_key"}\n`;
  text += `TS_SECRET_KEY=${toss.credential_configured ? "******** # ✓ 설정됨" : "your_toss_secret_key"}\n`;
  text += `TS_ACCOUNT=\n\n`;

  const pKeys = {
    tiingo: { key: "TIINGO_API_KEY", label: "Tiingo API Key" },
    alpha_vantage_news: { key: "ALPHA_VANTAGE_KEY", label: "Alpha Vantage API Key" },
    finnhub_events: { key: "FINNHUB_API", label: "Finnhub API Key" },
    openfigi: { key: "OPEN_FIGI", label: "OpenFIGI API Key (선택)" },
    fred: { key: "FRED_API_KEY", label: "FRED (stlouisfed) API Key" },
    sec_edgar: { key: "SEC_USER_AGENT", label: "SEC EDGAR User-Agent (이름/이메일)" },
    massive: { key: "MASSIVE_API_KEY", label: "Massive API Key" },
  };

  text += `# --- Price & Supplemental Data ---\n`;
  for (const [name, info] of Object.entries(pKeys)) {
    const p = providers.find(item => item.name === name) || {};
    text += `# ${info.label}\n`;
    text += `${info.key}=${p.credential_configured ? "******** # ✓ 설정됨" : ""}\n`;
  }
  text += `\n`;

  text += `# --- Kakao Notification ---\n`;
  text += `JAYU_KAKAO_REST_API_KEY=${kakao.has_rest_api_key ? "******** # ✓ 설정됨" : ""}\n`;
  text += `JAYU_KAKAO_CLIENT_SECRET=${kakao.has_client_secret ? "******** # ✓ 설정됨" : ""}\n`;

  return text;
}

function renderApiLogsPanel(logs) {
  if (!logs.length) {
    return `
      <section class="panel" style="margin-bottom:14px" id="api-logs-section">
        <div class="panel-header"><div><h2>최근 연동 에러/경고 로그</h2><p>최근 run에서 기록된 API 연동 관련 로그가 없습니다.</p></div></div>
        <div class="panel-body"><div class="empty-state"><strong>기록된 로그 없음</strong>모든 연동 요청이 경고 없이 수행되었습니다.</div>${renderSourceCaption("latest run logs/events.jsonl")}</div>
      </section>
    `;
  }
  return `
    <section class="panel" style="margin-bottom:14px" id="api-logs-section">
      <div class="panel-header" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
        <div>
          <h2>최근 연동 에러/경고 로그</h2>
          <p>최근 run의 로그 파일(events.jsonl)에서 추출한 에러/경고 및 연동 관련 로그 목록입니다. (최대 30건)</p>
        </div>
        <div class="log-filters-container" style="display:flex; align-items:center; gap:8px;">
          <input type="text" id="log-search-input" placeholder="이벤트, 메시지 검색..." style="font-size:12px; padding:6px 10px; border-radius:4px; border:1px solid var(--border); width:200px;" autocomplete="off">
          <select id="log-level-filter" style="font-size:12px; padding:6px 8px; border-radius:4px; border:1px solid var(--border); background:var(--bg);">
            <option value="ALL">모든 레벨</option>
            <option value="ERROR">ERROR / CRITICAL</option>
            <option value="WARNING">WARNING</option>
          </select>
          <span class="muted" id="filtered-log-count">${logs.length}건</span>
        </div>
      </div>
      <div class="table-wrap"><table class="logs-table" id="api-logs-table">
        <thead><tr>
          <th style="width: 140px;">시각</th>
          <th style="width: 80px;">레벨</th>
          <th style="width: 150px;">이벤트</th>
          <th>로그 메시지</th>
        </tr></thead>
        <tbody>
          ${logs.map((log) => {
            const levelCls = {
              ERROR: "negative",
              CRITICAL: "negative",
              WARNING: "warning",
            }[log.level] || "";
            return `
              <tr class="log-row" data-level="${escapeHtml(log.level)}">
                <td style="font-size: 11px; white-space: nowrap;">${formatDate(log.timestamp)}</td>
                <td><span class="status-label status-${levelCls || "not-evaluated"}" style="padding: 1px 6px; font-size: 9px; line-height:1.2;">${escapeHtml(log.level)}</span></td>
                <td class="code log-event-cell" style="font-size: 11px;">${escapeHtml(log.event)}</td>
                <td class="log-message-cell" style="font-size: 11px; white-space: pre-wrap; line-height: 1.4; text-align: left;">${escapeHtml(log.message)}</td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table></div>
      ${renderSourceCaption("latest run logs/events.jsonl")}
    </section>
  `;
}


function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, i);
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function configItem(label, value) {
  return `
    <div class="config-summary-item">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value))}</strong>
    </div>
  `;
}

function renderDisagreementsPanel(disagreements) {
  return `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>최근 Provider 불일치</h2><p>최근 run에서 발견된 provider간 데이터 차이입니다.</p></div><span class="muted">${disagreements.length}건</span></div>
      <div class="table-wrap"><table>
        <thead><tr>
          <th>Ticker</th>
          <th>날짜</th>
          <th>필드</th>
          <th>Provider A</th>
          <th>Provider B</th>
          <th>차이</th>
        </tr></thead>
        <tbody>
          ${disagreements.slice(0, 20).map((d) => `<tr>
            <td class="ticker-cell">${escapeHtml(d.ticker || d.symbol || "-")}</td>
            <td>${escapeHtml(d.date || "-")}</td>
            <td>${escapeHtml(d.field || "-")}</td>
            <td class="code">${escapeHtml(d.provider_a || d.source_a || "-")}: ${escapeHtml(d.value_a ?? "-")}</td>
            <td class="code">${escapeHtml(d.provider_b || d.source_b || "-")}: ${escapeHtml(d.value_b ?? "-")}</td>
            <td class="numeric">${escapeHtml(d.delta ?? d.relative_delta ?? "-")}</td>
          </tr>`).join("")}
        </tbody>
      </table></div>
      ${renderSourceCaption("provider_disagreement_report.json")}
    </section>
  `;
}

function renderNotificationFailuresPanel(failures) {
  return `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>알림 실패 이력</h2><p>최근 카카오 알림 전송 실패 기록입니다.</p></div><span class="muted">${failures.length}건</span></div>
      <div class="table-wrap"><table>
        <thead><tr>
          <th>시각</th>
          <th>유형</th>
          <th>오류 메시지</th>
        </tr></thead>
        <tbody>
          ${failures.map((f) => `<tr>
            <td>${formatDate(f.timestamp || f.time || f.at)}</td>
            <td>${escapeHtml(f.type || f.kind || "-")}</td>
            <td class="toss-payload">${escapeHtml(f.message || f.error || "-")}</td>
          </tr>`).join("")}
        </tbody>
      </table></div>
      ${renderSourceCaption("notification logs · Kakao send failure records")}
    </section>
  `;
}

function bindPageActions() {
  document.querySelectorAll("[data-go]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.go));
  });
  document.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", async () => {
      const command = button.dataset.command;
      const feedback = document.querySelector("#command-feedback");
      try {
        await navigator.clipboard.writeText(command);
        feedback.textContent = `명령을 복사했습니다: ${command}`;
      } catch {
        feedback.textContent = `실행 명령: ${command}`;
      }
      feedback.hidden = false;
      els.liveRegion.textContent = feedback.textContent;
    });
  });
  document.querySelectorAll("[data-toss-account]").forEach((button) => {
    button.addEventListener("click", () => {
      setSelectedTossAccount(button.dataset.tossAccount || "");
      if (state.page === "toss-account") {
        state.tossPortfolio = null;
        loadPage();
        return;
      }
      renderTossMarket();
      bindPageActions();
    });
  });
  document.querySelectorAll("[data-toss-region]").forEach((button) => {
    button.addEventListener("click", () => {
      state.tossAccountRegion = button.dataset.tossRegion || "ALL";
      localStorage.setItem("jayu.toss.accountRegion", state.tossAccountRegion);
      renderTossAccountDashboard();
      bindPageActions();
    });
  });
  document.querySelectorAll("[data-toss-subtab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.tossSubTab = button.dataset.tossSubtab || "overview";
      localStorage.setItem("jayu.toss.subTab", state.tossSubTab);
      renderTossAccountDashboard();
      bindPageActions();
    });
  });
  const tossForm = document.querySelector("#toss-market-form");
  if (tossForm) {
    tossForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const feedback = document.querySelector("#toss-feedback");
      const symbol = document.querySelector("#toss-symbol-input")?.value || "";
      const account = document.querySelector("#toss-account-input")?.value || state.selectedTossAccount || "";
      const includeAccount = document.querySelector("#toss-include-account")?.checked || false;
      if (account) {
        setSelectedTossAccount(account, false);
      }
      const params = new URLSearchParams({ symbol });
      if (account) params.set("account", account);
      if (includeAccount) params.set("include_account", "true");
      feedback.hidden = false;
      feedback.textContent = "Toss Market Data를 조회하는 중입니다.";
      try {
        state.tossMarket = await api(`/api/v1/toss/market?${params.toString()}`);
        feedback.textContent = "Toss Market Data 조회가 완료되었습니다.";
        renderTossMarket();
        bindPageActions();
      } catch (error) {
        feedback.textContent = error.message || "Toss Market Data 조회에 실패했습니다.";
      }
      els.liveRegion.textContent = feedback.textContent;
    });
  }

  // API Connection Test action
  document.querySelectorAll("[data-test-provider]").forEach((button) => {
    button.addEventListener("click", async () => {
      const provider = button.dataset.testProvider;
      const resultSpan = document.querySelector(`#test-result-${provider}`);
      if (!resultSpan) return;
      button.disabled = true;
      resultSpan.className = "pmc-test-result";
      resultSpan.textContent = "테스트 중...";
      try {
        const res = await fetch("/api/v1/api-monitoring/test-connection", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider }),
        });
        const data = await res.json();
        if (data.status === "success") {
          resultSpan.className = "pmc-test-result success";
          resultSpan.textContent = `✓ 연결 성공 (${data.latency_ms}ms)`;
        } else {
          resultSpan.className = "pmc-test-result failed";
          resultSpan.textContent = `✗ 실패 (${data.latency_ms}ms): ${data.message || "오류"}`;
        }
      } catch (err) {
        resultSpan.className = "pmc-test-result failed";
        resultSpan.textContent = `✗ 에러: ${err.message}`;
      } finally {
        button.disabled = false;
      }
    });
  });

  // Clear Cache action
  document.querySelectorAll("[data-clear-cache]").forEach((button) => {
    button.addEventListener("click", async () => {
      const cacheType = button.dataset.clearCache;
      const confirmMsg = cacheType === "all"
        ? "정말로 모든 API 캐시를 삭제하시겠습니까?"
        : `정말로 ${cacheType} 캐시를 삭제하시겠습니까?`;
      if (!confirm(confirmMsg)) return;
      button.disabled = true;
      try {
        const res = await fetch("/api/v1/api-monitoring/clear-cache", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cache_type: cacheType }),
        });
        const data = await res.json();
        if (data.status === "success") {
          alert(data.message);
          // Reload the page data to update stats
          state.apiMonitoring = null;
          loadPage();
        } else {
          alert(`캐시 삭제 실패: ${data.message}`);
        }
      } catch (err) {
        alert(`캐시 삭제 에러: ${err.message}`);
      } finally {
        button.disabled = false;
      }
    });
  });

  // Copy Env Template action
  const btnCopyTemplate = document.querySelector("#btn-copy-env-template");
  if (btnCopyTemplate) {
    btnCopyTemplate.addEventListener("click", async () => {
      const templatePre = document.querySelector("#env-template-text");
      if (!templatePre) return;
      try {
        await navigator.clipboard.writeText(templatePre.textContent);
        btnCopyTemplate.textContent = "복사 완료 ✓";
        setTimeout(() => { btnCopyTemplate.textContent = "템플릿 복사"; }, 2000);
      } catch (err) {
        alert(`복사 실패: ${err.message}`);
      }
    });
  }

  // Auto refresh select change
  const selectAutoRefresh = document.querySelector("#select-auto-refresh");
  if (selectAutoRefresh) {
    selectAutoRefresh.addEventListener("change", () => {
      const val = selectAutoRefresh.value;
      state.apiMonitoringRefreshSec = val;
      localStorage.setItem("jayu.apiMonitoring.refresh", val);
      setupApiMonitoringRefreshTimer();
    });
  }

  // Ping All action
  const btnPingAll = document.querySelector("#btn-ping-all");
  if (btnPingAll) {
    btnPingAll.addEventListener("click", async () => {
      btnPingAll.disabled = true;
      btnPingAll.textContent = "연결 테스트 중...";
      const buttons = Array.from(document.querySelectorAll("[data-test-provider]"));

      const promises = buttons.map(async (btn) => {
        const provider = btn.dataset.testProvider;
        const resultSpan = document.querySelector(`#test-result-${provider}`);
        if (!resultSpan) return;
        btn.disabled = true;
        resultSpan.className = "pmc-test-result";
        resultSpan.textContent = "테스트 중...";
        try {
          const res = await fetch("/api/v1/api-monitoring/test-connection", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ provider }),
          });
          const data = await res.json();
          if (data.status === "success") {
            resultSpan.className = "pmc-test-result success";
            resultSpan.textContent = `✓ 연결 성공 (${data.latency_ms}ms)`;
          } else {
            resultSpan.className = "pmc-test-result failed";
            resultSpan.textContent = `✗ 실패 (${data.latency_ms}ms): ${data.message || "오류"}`;
          }
        } catch (err) {
          resultSpan.className = "pmc-test-result failed";
          resultSpan.textContent = `✗ 에러: ${err.message}`;
        } finally {
          btn.disabled = false;
        }
      });
      await Promise.all(promises);
      btnPingAll.disabled = false;
      btnPingAll.textContent = "모든 API 연결 테스트";
    });
  }

  // Logs filtering
  const logSearchInput = document.querySelector("#log-search-input");
  const logLevelFilter = document.querySelector("#log-level-filter");
  const filteredLogCount = document.querySelector("#filtered-log-count");
  if (logSearchInput && logLevelFilter) {
    const filterLogs = () => {
      const query = logSearchInput.value.toLowerCase().trim();
      const level = logLevelFilter.value;
      let visibleCount = 0;
      const rows = document.querySelectorAll("#api-logs-table tbody .log-row");
      rows.forEach((row) => {
        const rowLevel = row.dataset.level || "";
        const eventText = row.querySelector(".log-event-cell")?.textContent.toLowerCase() || "";
        const messageText = row.querySelector(".log-message-cell")?.textContent.toLowerCase() || "";

        const matchLevel = (level === "ALL") ||
                           (level === "ERROR" && (rowLevel === "ERROR" || rowLevel === "CRITICAL")) ||
                           (level === "WARNING" && rowLevel === "WARNING");
        const matchSearch = !query || eventText.includes(query) || messageText.includes(query);

        if (matchLevel && matchSearch) {
          row.style.display = "";
          visibleCount++;
        } else {
          row.style.display = "none";
        }
      });
      if (filteredLogCount) {
        filteredLogCount.textContent = `${visibleCount}건`;
      }
    };
    logSearchInput.addEventListener("input", filterLogs);
    logLevelFilter.addEventListener("change", filterLogs);
  }

  // Portfolio sync action
  const syncButtons = document.querySelectorAll("#btn-sync-portfolio, #btn-sync-portfolio-banner");
  syncButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const confirmMsg = "현재 토스 실계좌 보유 종목 정보를 가져와서 로컬 portfolio.csv 파일을 갱신하시겠습니까?";
      if (!confirm(confirmMsg)) return;

      btn.disabled = true;
      const originalText = btn.textContent;
      btn.textContent = "동기화 진행 중...";

      try {
        const payload = {};
        if (state.selectedTossAccount) {
          payload.account = state.selectedTossAccount;
        }

        const res = await fetch("/api/v1/toss/reconciliation/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.status === "success") {
          alert(data.message || "성공적으로 동기화되었습니다.");
          // Clear cached portfolio and reconciliation data so they are re-fetched
          state.tossPortfolio = null;
          state.tossReconciliation = null;
          loadPage();
        } else {
          alert(`동기화 실패: ${data.message || "오류가 발생했습니다."}`);
        }
      } catch (err) {
        alert(`동기화 에러: ${err.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    });
  });

  // ── Analysis Tab Switching ─────────────────────────────────────────────────
  document.querySelectorAll("[data-analysis-tab]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.analysisTab = btn.dataset.analysisTab;
      renderAnalysis();
      bindPageActions();
    });
  });

  // ── Market Overview ────────────────────────────────────────────────────────
  const btnLoadMarket = document.querySelector("#btn-load-market");
  if (btnLoadMarket) {
    btnLoadMarket.addEventListener("click", async () => {
      btnLoadMarket.disabled = true;
      btnLoadMarket.textContent = "⏳ 로딩 중...";
      try {
        state.analysisMarketOverview = await api("/api/v1/analysis/market-overview");
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("시장 데이터 조회 실패: " + (err.message || "오류"));
      } finally {
        btnLoadMarket.disabled = false;
        btnLoadMarket.textContent = "🔄 시장 데이터 새로고침";
      }
    });
    // Auto-load market data on tab entry if not loaded yet
    if (!state.analysisMarketOverview && state.analysisTab === "market") {
      btnLoadMarket.click();
    }
  }

  // ── Basic Analysis Fetch ───────────────────────────────────────────────────
  const btnAnalysisFetch = document.querySelector("#btn-analysis-fetch");
  if (btnAnalysisFetch) {
    btnAnalysisFetch.addEventListener("click", async () => {
      const ticker = document.querySelector("#analysis-ticker")?.value || state.analysisTicker || "SOXL";
      const macro = document.querySelector("#analysis-macro")?.value || state.analysisMacro || "FEDFUNDS";
      const period = document.querySelector("#analysis-period")?.value || state.analysisPeriod || "1y";
      state.analysisTicker = ticker;
      state.analysisMacro = macro;
      state.analysisPeriod = period;
      localStorage.setItem("jayu.analysis.ticker", ticker);
      localStorage.setItem("jayu.analysis.macro", macro);
      localStorage.setItem("jayu.analysis.period", period);
      state.analysis = null;
      btnAnalysisFetch.disabled = true;
      btnAnalysisFetch.textContent = "⏳ 조회 중...";
      try {
        state.analysis = await api(`/api/v1/analysis?ticker=${encodeURIComponent(ticker)}&macro_series=${encodeURIComponent(macro)}&period=${encodeURIComponent(period)}`);
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("분석 조회 실패: " + (err.message || "오류"));
      } finally {
        btnAnalysisFetch.disabled = false;
        btnAnalysisFetch.textContent = "📊 조회";
      }
    });
  }

  // ── Technical Indicators Fetch ─────────────────────────────────────────────
  const btnTechFetch = document.querySelector("#btn-tech-fetch");
  if (btnTechFetch) {
    btnTechFetch.addEventListener("click", async () => {
      const ticker = document.querySelector("#tech-ticker")?.value || state.analysisTicker || "SOXL";
      const period = document.querySelector("#tech-period")?.value || state.analysisPeriod || "1y";
      state.analysisTicker = ticker;
      state.analysisPeriod = period;
      btnTechFetch.disabled = true;
      btnTechFetch.textContent = "⏳ 계산 중...";
      try {
        state.analysisTechnical = await api(`/api/v1/analysis/technical?ticker=${encodeURIComponent(ticker)}&period=${encodeURIComponent(period)}`);
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("기술적 지표 조회 실패: " + (err.message || "오류"));
      } finally {
        btnTechFetch.disabled = false;
        btnTechFetch.textContent = "📊 조회";
      }
    });
  }

  // ── Multi-Compare Fetch ────────────────────────────────────────────────────
  const btnCompareFetch = document.querySelector("#btn-compare-fetch");
  if (btnCompareFetch) {
    btnCompareFetch.addEventListener("click", async () => {
      const rawTickers = document.querySelector("#compare-tickers")?.value || "SOXL,TQQQ,NVDA,QQQ,SPY";
      const period = document.querySelector("#compare-period")?.value || state.analysisPeriod || "1y";
      state.analysisPeriod = period;
      btnCompareFetch.disabled = true;
      btnCompareFetch.textContent = "⏳ 비교 중...";
      try {
        const tickers = rawTickers.split(",").map(t => t.trim()).filter(Boolean).join(",");
        state.analysisCompare = await api(`/api/v1/analysis/multi-compare?tickers=${encodeURIComponent(tickers)}&period=${encodeURIComponent(period)}`);
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("비교 조회 실패: " + (err.message || "오류"));
      } finally {
        btnCompareFetch.disabled = false;
        btnCompareFetch.textContent = "📊 비교";
      }
    });
  }

  // ── Portfolio Stats Fetch ──────────────────────────────────────────────────
  const btnPortfolioFetch = document.querySelector("#btn-portfolio-fetch");
  if (btnPortfolioFetch) {
    btnPortfolioFetch.addEventListener("click", async () => {
      btnPortfolioFetch.disabled = true;
      btnPortfolioFetch.textContent = "⏳ 로딩 중...";
      try {
        const run = state.runId ? `?run_id=${encodeURIComponent(state.runId)}` : "";
        state.analysisPortfolio = await api(`/api/v1/analysis/portfolio-stats${run}`);
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("포트폴리오 성과 조회 실패: " + (err.message || "오류"));
      } finally {
        btnPortfolioFetch.disabled = false;
        btnPortfolioFetch.textContent = "📊 실행 데이터 조회";
      }
    });
    // Auto-load if not loaded yet
    if (!state.analysisPortfolio && state.analysisTab === "portfolio") {
      btnPortfolioFetch.click();
    }
  }

  // ── Economic Calendar Fetch ────────────────────────────────────────────────
  const btnCalendarFetch = document.querySelector("#btn-calendar-fetch");
  if (btnCalendarFetch) {
    btnCalendarFetch.addEventListener("click", async () => {
      btnCalendarFetch.disabled = true;
      btnCalendarFetch.textContent = "⏳ 로딩 중...";
      try {
        state.analysisCalendar = await api("/api/v1/analysis/economic-calendar");
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("경제 캘린더 조회 실패: " + (err.message || "오류"));
      } finally {
        btnCalendarFetch.disabled = false;
        btnCalendarFetch.textContent = "📅 캘린더 로드";
      }
    });
    // Auto-load if not loaded yet
    if (!state.analysisCalendar && state.analysisTab === "calendar") {
      btnCalendarFetch.click();
    }
  }
}



function clearApiMonitoringRefreshTimer() {
  if (state.autoRefreshTimer) {
    clearInterval(state.autoRefreshTimer);
    state.autoRefreshTimer = null;
  }
}

function setupApiMonitoringRefreshTimer() {
  clearApiMonitoringRefreshTimer();
  if (state.page !== "api-monitoring") return;
  const refreshSec = state.apiMonitoringRefreshSec || "off";
  if (refreshSec === "off") return;

  const sec = parseInt(refreshSec, 10);
  if (Number.isNaN(sec)) return;

  state.autoRefreshTimer = setInterval(async () => {
    if (state.page === "api-monitoring") {
      try {
        const run = encodeURIComponent(state.runId);
        state.decision = await api(`/api/v1/decision?run_id=${run}`);
        state.overview = await api(`/api/v1/overview?run_id=${run}`);
        state.apiMonitoring = await api("/api/v1/api-monitoring");
        updateContext();
        render();
      } catch (err) {
        console.error("Auto refresh failed", err);
      }
    }
  }, sec * 1000);
}

function navigate(page) {
  if (!["overview", "data-quality", "risk", "signals", "trader-lens", "promotion", "settings", "toss-account", "toss", "api-monitoring", "analysis"].includes(page)) return;
  clearApiMonitoringRefreshTimer();
  state.page = page;
  localStorage.setItem("jayu.dashboard.activePage", page);
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.page === page);
  });
  loadPage();
}

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => navigate(item.dataset.page));
});

els.runSelector.addEventListener("change", () => {
  state.runId = els.runSelector.value;
  state.decision = null;
  state.overview = null;
  state.dataQuality = null;
  state.risk = null;
  state.signals = null;
  state.traderLens = null;
  state.promotion = null;
  state.settingsValidation = null;
  state.tossStatus = null;
  state.tossAccounts = null;
  state.tossMarket = null;
  state.tossPortfolio = null;
  state.apiMonitoring = null;
  loadPage();
});

document.querySelector("#refresh-button").addEventListener("click", async () => {
  state.runs = [];
  state.decision = null;
  state.overview = null;
  state.traderLens = null;
  state.tossStatus = null;
  state.tossAccounts = null;
  state.tossMarket = null;
  state.tossPortfolio = null;
  state.apiMonitoring = null;
  await loadPage();
});

document.querySelector("#retry-button").addEventListener("click", loadPage);

// Initialize active sidebar menu item from state on load
document.querySelectorAll(".nav-item").forEach((item) => {
  item.classList.toggle("is-active", item.dataset.page === state.page);
});

loadPage();

// ─── Analysis Page ────────────────────────────────────────────────────────────

const ANALYSIS_TABS = [
  { id: "market",    label: "🌐 시장 현황",       key: "analysisMarketOverview" },
  { id: "basic",     label: "📊 기본 분석",        key: "analysis" },
  { id: "technical", label: "📈 기술적 지표",      key: "analysisTechnical" },
  { id: "compare",   label: "⚖️ 멀티 비교",       key: "analysisCompare" },
  { id: "portfolio", label: "🏆 포트폴리오 성과", key: "analysisPortfolio" },
  { id: "calendar",  label: "📅 경제 캘린더",      key: "analysisCalendar" },
];

const TICKER_OPTIONS = ["SOXL","TQQQ","TSLA","AAPL","NVDA","NVDL","IONQ","QBTS","QQQ","SPY","MSFT","GOOGL","AMZN","META","AMD"];
const MACRO_OPTIONS = [
  { id: "FEDFUNDS",  label: "기준금리 (Fed Funds)" },
  { id: "CPIAUCSL",  label: "소비자물가지수 (CPI)" },
  { id: "UNRATE",    label: "실업률" },
  { id: "T10Y2Y",    label: "10년-2년 국채 스프레드" },
  { id: "GDPC1",     label: "실질 GDP" },
  { id: "M2SL",      label: "M2 통화량" },
  { id: "BAMLH0A0HYM2", label: "하이일드 스프레드" },
];
const PERIOD_OPTIONS = [
  { id: "3m", label: "3개월" }, { id: "6m", label: "6개월" },
  { id: "1y", label: "1년" }, { id: "2y", label: "2년" },
  { id: "5y", label: "5년" },
];

// ── formatters ─────────────────────────────────────────────────────────────
const _$ = (v, d = 2) => v == null ? "-" : `$${Number(v).toFixed(d)}`;
const _pct = (v, d = 2) => v == null ? "-" : `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(d)}%`;
const _num = (v, d = 2) => v == null ? "-" : Number(v).toFixed(d);
const _chgCls = (v) => Number(v) > 0 ? "analysis-positive" : Number(v) < 0 ? "analysis-negative" : "";
const _score = (v, d = 2) => v == null ? "-" : Number(v).toFixed(d);
const _volume = (v) => {
  if (v == null || Number.isNaN(Number(v))) return "-";
  const n = Number(v);
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
};
const _signalToneColor = (tone) => tone === "buy" ? "#16a34a" : tone === "sell" ? "#dc2626" : "#64748b";
const _statusForAction = (action) => action === "buy" ? "success" : action === "sell" ? "failed" : "warning";

// ── SVG helpers ────────────────────────────────────────────────────────────
function _svgScale(vals, h, pad = 0.08) {
  const clean = vals.filter(v => v != null && !isNaN(v));
  if (!clean.length) return { min: 0, max: 1, toY: () => h / 2 };
  const mn = Math.min(...clean), mx = Math.max(...clean);
  const p = (mx - mn) * pad || Math.abs(mn) * 0.05 || 1;
  const lo = mn - p, hi = mx + p;
  return { min: lo, max: hi, toY: (v) => h - ((v - lo) / (hi - lo)) * h };
}
function _svgLine(pts, stroke, sw = 1.8, dash = "") {
  if (!pts.length) return "";
  return `<polyline fill="none" stroke="${stroke}" stroke-width="${sw}" stroke-linejoin="round" stroke-linecap="round" ${dash ? `stroke-dasharray="${dash}"` : ""} points="${pts.join(" ")}"/>`;
}
function _svgArea(pts, fill) {
  if (pts.length < 2) return "";
  const first = pts[0].split(","), last = pts[pts.length - 1].split(",");
  return `<polygon fill="${fill}" points="${pts.join(" ")} ${last[0]},9999 ${first[0]},9999"/>`;
}

function _renderTradingViewDetailsPanel(details, { compact = false } = {}) {
  if (!details || details.status !== "ok") {
    return details?.error ? `
      <section class="panel" style="margin-bottom:14px">
        <div class="panel-header"><div><h2>TradingView 상세 스냅샷</h2><p>${escapeHtml(details.error)}</p></div></div>
      </section>` : "";
  }

  const profile = details.profile || {};
  const quote = details.quote || {};
  const performance = details.performance || {};
  const volume = details.volume || {};
  const fund = details.fund || {};
  const derivatives = details.derivatives || {};
  const recommendation = quote.recommendation || {};
  const nav = fund.nav_discount_premium;
  const hasDerivativeData = ["open_interest", "iv", "delta", "gamma", "theta", "vega", "theo_price"].some((key) => derivatives[key] != null);
  const perfRows = [
    ["1주", performance.week],
    ["1개월", performance.one_month],
    ["3개월", performance.three_month],
    ["6개월", performance.six_month],
    ["YTD", performance.year_to_date],
    ["1년", performance.one_year],
  ];

  return `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div>
          <h2>TradingView 상세 스냅샷</h2>
          <p>${escapeHtml(details.symbol || "-")} · ${escapeHtml(profile.market || "-")} · ${escapeHtml(profile.country || "-")}</p>
        </div>
        <span class="status-badge status-${_statusForAction(recommendation.action)}">${escapeHtml(recommendation.label || "-")}</span>
      </div>
      <div class="panel-body">
        <section class="metric-grid" style="margin-bottom:12px">
          <div class="metric-card">
            <span class="metric-label">섹터 / 국가</span>
            <span class="metric-value" style="font-size:15px">${escapeHtml(profile.sector || "-")}</span>
            <span class="metric-sub">${escapeHtml(profile.country_code_fund || profile.country || "-")}</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
          <div class="metric-card">
            <span class="metric-label">52주 범위</span>
            <span class="metric-value" style="font-size:15px">${_$(quote.price_52_week_low)} - ${_$(quote.price_52_week_high)}</span>
            <span class="metric-sub">TradingView right-details</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
          <div class="metric-card">
            <span class="metric-label">1개월 범위</span>
            <span class="metric-value" style="font-size:15px">${_$(quote.low_1m)} - ${_$(quote.high_1m)}</span>
            <span class="metric-sub">고가/저가</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
          <div class="metric-card">
            <span class="metric-label">평균 거래량</span>
            <span class="metric-value" style="font-size:15px">${_volume(volume.average_10d)} / ${_volume(volume.average_30d)}</span>
            <span class="metric-sub">10일 / 30일</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
          <div class="metric-card">
            <span class="metric-label">NAV 프리미엄</span>
            <span class="metric-value ${_chgCls(nav)}" style="font-size:15px">${_pct(nav)}</span>
            <span class="metric-sub">ETF 괴리율</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
          <div class="metric-card">
            <span class="metric-label">추천 점수</span>
            <span class="metric-value" style="font-size:15px;color:${_signalToneColor(recommendation.tone)}">${_score(quote.recommend_all)}</span>
            <span class="metric-sub">${escapeHtml(recommendation.label || "-")}</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
        </section>
        ${compact ? "" : `
        <div style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:13px">
            <thead><tr style="border-bottom:2px solid var(--border)">
              <th style="text-align:left;padding:7px 10px">성과</th>
              ${perfRows.map(([label]) => `<th style="text-align:right;padding:7px 10px">${label}</th>`).join("")}
            </tr></thead>
            <tbody>
              <tr style="border-bottom:1px solid var(--border)">
                <td style="padding:7px 10px;font-weight:700">수익률</td>
                ${perfRows.map(([, value]) => `<td class="${_chgCls(value)}" style="text-align:right;padding:7px 10px;font-weight:700">${_pct(value)}</td>`).join("")}
              </tr>
            </tbody>
          </table>
        </div>
        ${renderSourceCaption("TradingView scanner right-details performance fields")}
        ${hasDerivativeData ? `
        <div style="margin-top:10px;color:var(--muted);font-size:12px">
          옵션성 지표: OI ${_volume(derivatives.open_interest)} · IV ${_pct(derivatives.iv)} · Δ ${_score(derivatives.delta)} · Θ ${_score(derivatives.theta)} · Theo ${_$(derivatives.theo_price)}
          ${renderSourceLabel("TradingView scanner right-details derivative fields")}
        </div>` : ""}`}
      </div>
    </section>`;
}

// ── Tab render coordinator ─────────────────────────────────────────────────
function renderAnalysis() {
  const tab = state.analysisTab || "market";
  const ticker = state.analysisTicker || "SOXL";
  const period = state.analysisPeriod || "1y";
  const macro = state.analysisMacro || "FEDFUNDS";

  const tabBar = `
    <div class="analysis-tab-bar">
      ${ANALYSIS_TABS.map(t => `
        <button class="analysis-tab-btn ${t.id === tab ? "is-active" : ""}"
          data-analysis-tab="${t.id}" type="button">${t.label}</button>
      `).join("")}
    </div>`;

  const pageHead = `
    <div class="page-heading" style="margin-bottom:12px">
      <div><h1>📈 주식 & 경제 분석</h1>
        <p>Yahoo Finance · FRED · 기술적 지표 · 섹터 현황을 통합 분석합니다.</p>
      </div>
    </div>`;

  els.root.innerHTML = pageHead + renderDataSourceNote("analysis") + tabBar + `<div id="analysis-tab-content"></div>`;

  const content = document.querySelector("#analysis-tab-content");

  if (tab === "market") {
    renderAnalysisMarket(content);
  } else if (tab === "basic") {
    renderAnalysisBasic(content, ticker, macro, period);
  } else if (tab === "technical") {
    renderAnalysisTechnical(content, ticker, period);
  } else if (tab === "compare") {
    renderAnalysisCompare(content, period);
  } else if (tab === "portfolio") {
    renderAnalysisPortfolio(content);
  } else if (tab === "calendar") {
    renderAnalysisCalendar(content);
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1: 시장 현황
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisMarket(container) {
  const data = state.analysisMarketOverview || {};

  if (!data.indices) {
    container.innerHTML = renderDataSourceNote("analysis", ["Yahoo Finance index/sector ETFs", "VIX proxy"]) + `<div class="analysis-loading">⏳ 시장 데이터를 불러오는 중... <button id="btn-load-market" class="button button-primary" style="margin-left:12px">조회</button></div>`;
    return;
  }

  const indices = data.indices || [];
  const sectors = data.sectors || [];
  const fg = data.fear_greed || { value: 50, label: "중립", vix: 20 };

  // Fear & Greed gauge (SVG semicircle)
  const fgAngle = (fg.value / 100) * 180 - 90; // -90 to 90 degrees
  const r = 54, cx = 70, cy = 68;
  const toRad = (deg) => (deg * Math.PI) / 180;
  const needle = {
    x: cx + r * 0.85 * Math.cos(toRad(fgAngle)),
    y: cy + r * 0.85 * Math.sin(toRad(fgAngle)),
  };
  const fgColor = fg.value >= 70 ? "#22c55e" : fg.value >= 55 ? "#84cc16" : fg.value >= 40 ? "#eab308" : fg.value >= 25 ? "#f97316" : "#ef4444";

  const fgGauge = `
    <svg viewBox="0 0 140 80" style="width:140px;height:80px" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="fgGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#ef4444"/>
          <stop offset="40%" stop-color="#f97316"/>
          <stop offset="60%" stop-color="#eab308"/>
          <stop offset="80%" stop-color="#84cc16"/>
          <stop offset="100%" stop-color="#22c55e"/>
        </linearGradient>
      </defs>
      <path d="M16,68 A54,54 0 0,1 124,68" fill="none" stroke="url(#fgGrad)" stroke-width="10" stroke-linecap="round"/>
      <line x1="${cx}" y1="${cy}" x2="${needle.x.toFixed(1)}" y2="${needle.y.toFixed(1)}" stroke="#1e293b" stroke-width="2.5" stroke-linecap="round"/>
      <circle cx="${cx}" cy="${cy}" r="4" fill="#1e293b"/>
      <text x="${cx}" y="${cy + 14}" text-anchor="middle" font-size="10" font-weight="700" fill="${fgColor}">${fg.label}</text>
      <text x="${cx}" y="${cy + 25}" text-anchor="middle" font-size="9" fill="#64748b">${fg.value} / 100</text>
    </svg>`;

  // Sparkline SVG
  const sparkSvg = (vals, positive) => {
    if (!vals || vals.length < 2) return `<svg width="60" height="20"></svg>`;
    const s = _svgScale(vals, 16, 0.05);
    const pts = vals.map((v, i) => `${(i / (vals.length - 1) * 58 + 1).toFixed(1)},${(s.toY(v) + 2).toFixed(1)}`);
    const col = positive ? "#22c55e" : "#ef4444";
    return `<svg width="60" height="20" xmlns="http://www.w3.org/2000/svg" style="overflow:visible">${_svgLine(pts, col, 1.5)}</svg>`;
  };

  // Sector heatmap
  const sectorHeatmap = sectors.map(s => {
    const pct = s.change_pct || 0;
    const intensity = Math.min(Math.abs(pct) / 3, 1);
    const bg = pct > 0
      ? `rgba(34,197,94,${0.15 + intensity * 0.45})`
      : `rgba(239,68,68,${0.15 + intensity * 0.45})`;
    const textColor = pct > 0 ? "#14532d" : "#7f1d1d";
    return `<div class="sector-cell" style="background:${bg};color:${textColor}">
      <span class="sector-name">${s.name}</span>
      <span class="sector-sym">${s.symbol}</span>
      <span class="sector-pct">${_pct(pct)}</span>
    </div>`;
  }).join("");

  container.innerHTML = `
    ${renderDataSourceNote("analysis", ["Yahoo Finance index/sector ETFs", "VIX proxy"])}
    <div class="analysis-market-grid">
      <!-- Fear & Greed + VIX -->
      <section class="panel analysis-fg-panel">
        <div class="panel-header"><div><h2>🎯 공포 & 탐욕 지수</h2><p>VIX 기반 시장 심리 추정</p></div></div>
        <div class="panel-body" style="display:flex;align-items:center;gap:20px;flex-wrap:wrap">
          ${fgGauge}
          <div>
            <div style="font-size:28px;font-weight:800;color:${fgColor}">${fg.value}</div>
            <div style="font-size:13px;font-weight:600;color:${fgColor}">${fg.label}</div>
            <div style="font-size:12px;color:var(--muted);margin-top:4px">VIX = ${_num(fg.vix)}</div>
            ${renderSourceLabel("Yahoo Finance VIX proxy")}
          </div>
        </div>
      </section>

      <!-- Reload button -->
      <div style="grid-column:1/-1;display:flex;justify-content:flex-end;margin-bottom:-6px">
        <button id="btn-load-market" class="button button-primary" type="button">🔄 시장 데이터 새로고침</button>
      </div>

      <!-- Major Indices -->
      <section class="panel" style="grid-column:1/-1">
        <div class="panel-header"><div><h2>📊 주요 지수 & 자산</h2></div></div>
        <div class="panel-body" style="overflow-x:auto">
          <div class="analysis-index-grid">
            ${indices.map(idx => {
              const up = idx.change_pct >= 0;
              return `<div class="analysis-index-card ${up ? "up" : "down"}">
                <div class="idx-name">${escapeHtml(idx.name)}</div>
                <div class="idx-price">${_num(idx.price, idx.price > 1000 ? 0 : 2)}</div>
                <div class="idx-chg ${_chgCls(idx.change_pct)}">${_pct(idx.change_pct)}</div>
                <div class="idx-spark">${sparkSvg(idx.sparkline, up)}</div>
                ${renderSourceLabel("Yahoo Finance quote/history")}
              </div>`;
            }).join("")}
          </div>
        </div>
      </section>

      <!-- Sector Heatmap -->
      <section class="panel" style="grid-column:1/-1">
        <div class="panel-header"><div><h2>🗺️ 섹터 히트맵</h2><p>전일 대비 섹터 ETF 등락률</p></div></div>
        <div class="panel-body">
          <div class="sector-heatmap">${sectorHeatmap}</div>
          ${renderSourceCaption("Yahoo Finance sector ETF daily change")}
        </div>
      </section>
    </div>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2: 기본 분석 (기존 개선)
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisBasic(container, ticker, macro, period) {
  const data = state.analysis || {};
  const stock = data.stock || {};
  const macroData = data.macro || {};
  const news = data.news || [];
  const toss = data.toss || {};
  const tvDetails = data.tradingview_details || {};

  const macroLabel = MACRO_OPTIONS.find(m => m.id === macro)?.label || macro;

  const controlPanel = `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>조회 설정</h2></div></div>
      <div class="panel-body">
        <div class="analysis-controls">
          <div class="analysis-control-group">
            <label>종목 (Ticker)</label>
            <select id="analysis-ticker" class="analysis-select">
              ${TICKER_OPTIONS.map(t => `<option value="${t}" ${t===ticker?"selected":""}>${t}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group">
            <label>경제 지표 (FRED)</label>
            <select id="analysis-macro" class="analysis-select">
              ${MACRO_OPTIONS.map(s => `<option value="${s.id}" ${s.id===macro?"selected":""}>${s.label}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group">
            <label>기간</label>
            <select id="analysis-period" class="analysis-select">
              ${PERIOD_OPTIONS.map(p => `<option value="${p.id}" ${p.id===period?"selected":""}>${p.label}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group" style="align-self:flex-end">
            <button id="btn-analysis-fetch" class="button button-primary" type="button" style="height:38px">📊 조회</button>
          </div>
        </div>
      </div>
    </section>`;

  if (!data.stock) {
    container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance OHLCV/news", "FRED series", "TradingView right-details", "Toss holdings"]) + `<div class="analysis-loading">종목, 지표, 기간을 선택 후 조회 버튼을 누르세요.</div>`;
    return;
  }

  const sentimentBadge = (s) => {
    if (s === "Positive") return `<span class="analysis-badge-pos">▲ 긍정</span>`;
    if (s === "Negative") return `<span class="analysis-badge-neg">▼ 부정</span>`;
    return `<span class="analysis-badge-neu">— 중립</span>`;
  };

  const newsHtml = news.length ? news.slice(0, 10).map(n => `
    <article class="analysis-news-item">
      <div class="analysis-news-meta">
        ${sentimentBadge(n.sentiment)}
        <span class="analysis-news-source">${escapeHtml(n.source||"-")}</span>
        <span class="analysis-news-date">${n.published_at?n.published_at.slice(0,10):"-"}</span>
      </div>
      <a class="analysis-news-title" href="${escapeHtml(n.url||"#")}" target="_blank" rel="noopener">${escapeHtml(n.headline||"제목 없음")}</a>
    </article>`).join("") : `<p style="color:var(--muted);padding:10px 0">Finnhub 또는 Alpha Vantage API 키가 설정되어 있지 않습니다.</p>`;

  const chartHtml = _renderDualAxisChart(stock.history || [], macroData.history || []);
  const tradingViewDetailsHtml = _renderTradingViewDetailsPanel(tvDetails);

  let tossHtml = "";
  if (toss.positions?.length) {
    tossHtml = `<section class="panel" style="margin-top:14px">
      <div class="panel-header"><div><h2>📂 Toss 보유 종목</h2><p>${escapeHtml(toss.account_no||"")}</p></div></div>
      <div class="panel-body" style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead><tr style="border-bottom:2px solid var(--border)">
            <th style="text-align:left;padding:7px 10px">종목</th><th style="text-align:right;padding:7px 10px">수량</th>
            <th style="text-align:right;padding:7px 10px">매수가</th><th style="text-align:right;padding:7px 10px">현재가</th>
            <th style="text-align:right;padding:7px 10px">손익</th><th style="text-align:right;padding:7px 10px">수익률</th>
          </tr></thead>
          <tbody>${toss.positions.map(pos => {
            const plr = parseFloat(pos.profit_loss_rate||0);
            const c = plr>=0?"color:var(--success)":"color:var(--failed)";
            return `<tr style="border-bottom:1px solid var(--border)">
              <td style="padding:6px 10px;font-weight:600">${escapeHtml(pos.symbol||"-")}</td>
              <td style="text-align:right;padding:6px 10px">${pos.qty??"-"}</td>
              <td style="text-align:right;padding:6px 10px">${_$(pos.buy_price)}</td>
              <td style="text-align:right;padding:6px 10px">${_$(pos.current_price)}</td>
              <td style="text-align:right;padding:6px 10px;${c}">${_num(pos.profit_loss)}</td>
              <td style="text-align:right;padding:6px 10px;font-weight:600;${c}">${_pct(plr)}</td>
            </tr>`;
          }).join("")}</tbody>
        </table>
        ${renderSourceCaption("Toss Open API holdings GET")}
      </div>
    </section>`;
  }

  container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance OHLCV/news", "FRED series", "TradingView right-details", "Toss holdings"]) + `
    <section class="metric-grid" style="margin-bottom:14px">
      <div class="metric-card">
        <span class="metric-label">현재가</span>
        <span class="metric-value" style="font-size:22px">${_$(stock.latest_price)}</span>
        <span class="metric-sub">${escapeHtml(stock.ticker||ticker)}</span>
        ${renderSourceLabel("Yahoo Finance OHLCV")}
      </div>
      <div class="metric-card">
        <span class="metric-label">전일 대비</span>
        <span class="metric-value ${_chgCls(stock.change_pct)}" style="font-size:22px">${_pct(stock.change_pct)}</span>
        <span class="metric-sub">일간 수익률</span>
        ${renderSourceLabel("Yahoo Finance OHLCV")}
      </div>
      <div class="metric-card">
        <span class="metric-label">기간 최고가</span>
        <span class="metric-value">${_$(stock.fifty_two_week_high)}</span>
        <span class="metric-sub">구간 내 최고</span>
        ${renderSourceLabel("Yahoo Finance OHLCV")}
      </div>
      <div class="metric-card">
        <span class="metric-label">기간 최저가</span>
        <span class="metric-value">${_$(stock.fifty_two_week_low)}</span>
        <span class="metric-sub">구간 내 최저</span>
        ${renderSourceLabel("Yahoo Finance OHLCV")}
      </div>
      ${!macroData.error ? `
      <div class="metric-card">
        <span class="metric-label">${escapeHtml((macroData.name||macro).slice(0,32))}</span>
        <span class="metric-value">${_num(macroData.latest_value,2)}</span>
        <span class="metric-sub">${escapeHtml(macroData.latest_date||"-")}</span>
        ${renderSourceLabel("FRED series")}
      </div>
      <div class="metric-card">
        <span class="metric-label">지표 변화</span>
        <span class="metric-value ${_chgCls(macroData.change)}">${macroData.change!=null?(macroData.change>=0?"+":"")+_num(macroData.change,3):"-"}</span>
        <span class="metric-sub">전기 대비</span>
        ${renderSourceLabel("FRED series")}
      </div>` : ""}
    </section>
    ${tradingViewDetailsHtml}
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>가격 & ${macroLabel} 차트</h2></div></div>
      <div class="panel-body" style="padding:0 4px">${chartHtml}${renderSourceCaption("Yahoo Finance OHLCV · FRED series")}</div>
    </section>
    ${tossHtml}
    <section class="panel" style="margin-top:14px">
      <div class="panel-header"><div><h2>📰 뉴스 & 감성 분석</h2></div></div>
      <div class="panel-body"><div class="analysis-news-list">${newsHtml}</div>${renderSourceCaption("Finnhub / Alpha Vantage news providers")}</div>
    </section>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3: 기술적 지표
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisTechnical(container, ticker, period) {
  const data = state.analysisTechnical || {};

  const controlPanel = `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>기술적 지표 설정</h2></div></div>
      <div class="panel-body">
        <div class="analysis-controls">
          <div class="analysis-control-group">
            <label>종목</label>
            <select id="tech-ticker" class="analysis-select">
              ${TICKER_OPTIONS.map(t => `<option value="${t}" ${t===ticker?"selected":""}>${t}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group">
            <label>기간</label>
            <select id="tech-period" class="analysis-select">
              ${PERIOD_OPTIONS.map(p => `<option value="${p.id}" ${p.id===period?"selected":""}>${p.label}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group" style="align-self:flex-end">
            <button id="btn-tech-fetch" class="button button-primary" style="height:38px">📊 조회</button>
          </div>
        </div>
      </div>
    </section>`;

  if (!data.records) {
    container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance OHLCV", "TradingView scanner popup-technicals", "TradingView right-details"]) + `<div class="analysis-loading">종목을 선택하고 조회 버튼을 누르세요.</div>`;
    return;
  }

  const recs = data.records || [];
  const regime = data.latest_regime || "unknown";
  const regimeColor = regime === "bull" ? "#22c55e" : regime === "bear" ? "#ef4444" : "#eab308";
  const regimeLabel = regime === "bull" ? "🐂 강세장 (Bull)" : regime === "bear" ? "🐻 약세장 (Bear)" : "↔️ 횡보장 (Sideways)";

  // Summary cards
  const rsi = data.latest_rsi;
  const rsiColor = rsi == null ? "" : rsi > 70 ? "#ef4444" : rsi < 30 ? "#22c55e" : "#3b82f6";
  const rsiLabel = rsi == null ? "-" : rsi > 70 ? "과매수" : rsi < 30 ? "과매도" : "중립";
  const tv = data.tradingview || {};
  const tvConsensus = tv.consensus || {};
  const tvScore = (score) => score == null ? "-" : Number(score).toFixed(2);
  const tvSignalLabel = (row) => escapeHtml(row?.recommendation?.label || "데이터 없음");
  const tvRows = Array.isArray(tv.timeframes) ? tv.timeframes : [];
  const tradingViewDetailsHtml = _renderTradingViewDetailsPanel(data.tradingview_details || {}, { compact: true });
  const tvErrors = Array.isArray(tv.errors) ? tv.errors : [];
  const tvDetail = tvRows.find(row => row.timeframe === "1") || tvRows[tvRows.length - 1] || {};
  const tvOsc = tvDetail.oscillators || {};
  const tvMas = tvDetail.moving_averages || {};
  const tvNearest = tvDetail.nearest_pivots || {};
  const pivotLabel = (level) => level ? `${escapeHtml(level.family || "-")} ${escapeHtml(String(level.level || "").toUpperCase())} ${_$(level.value)} (${_pct(level.distance_pct)})` : "-";
  const rationaleHtml = Array.isArray(tvDetail.rationale) && tvDetail.rationale.length
    ? tvDetail.rationale.map(note => `<span class="status-badge status-${_statusForAction(note.tone)}" style="margin:0 6px 6px 0">${escapeHtml(note.text || "")}</span>`).join("")
    : `<span style="color:var(--muted)">세부 근거 없음</span>`;
  const tvDetailHtml = tvDetail.timeframe ? `
    <section style="margin-top:14px;border-top:1px solid var(--border);padding-top:12px">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
        <h3 style="margin:0;font-size:15px">초단기 상세 진단 · ${escapeHtml(tvDetail.label || tvDetail.timeframe)}</h3>
        <span class="status-badge status-${_statusForAction(tvDetail?.recommendation?.action)}">${escapeHtml(tvDetail?.recommendation?.label || "-")}</span>
      </div>
      <div class="metric-grid" style="margin-bottom:10px">
        <div class="metric-card">
          <span class="metric-label">RSI / Stoch</span>
          <span class="metric-value" style="font-size:15px">${_num(tvOsc.rsi)} / ${_num(tvOsc.stoch_k)}</span>
          <span class="metric-sub">D ${_num(tvOsc.stoch_d)} · Stoch RSI ${_num(tvOsc.stoch_rsi_k)}</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
        <div class="metric-card">
          <span class="metric-label">ADX 방향성</span>
          <span class="metric-value" style="font-size:15px">${_num(tvOsc.adx)}</span>
          <span class="metric-sub">+DI ${_num(tvOsc.adx_plus_di)} / -DI ${_num(tvOsc.adx_minus_di)}</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
        <div class="metric-card">
          <span class="metric-label">MACD / Momentum</span>
          <span class="metric-value" style="font-size:15px">${_score(tvOsc.macd)} / ${_score(tvOsc.macd_signal)}</span>
          <span class="metric-sub">Mom ${_score(tvOsc.mom)} · AO ${_score(tvOsc.ao)}</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
        <div class="metric-card">
          <span class="metric-label">이평선 위치</span>
          <span class="metric-value" style="font-size:15px">${_$(tvDetail.close)}</span>
          <span class="metric-sub">EMA20 ${_$(tvMas.ema20)} · EMA200 ${_$(tvMas.ema200)}</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
        <div class="metric-card">
          <span class="metric-label">근접 지지</span>
          <span class="metric-value" style="font-size:13px">${pivotLabel(tvNearest.support)}</span>
          <span class="metric-sub">월간 피벗 기준</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
        <div class="metric-card">
          <span class="metric-label">근접 저항</span>
          <span class="metric-value" style="font-size:13px">${pivotLabel(tvNearest.resistance)}</span>
          <span class="metric-sub">월간 피벗 기준</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
      </div>
      <div>${rationaleHtml}${renderSourceCaption("TradingView scanner popup-technicals · derived rationale")}</div>
    </section>` : "";
  const tradingViewHtml = (tv.status === "ok" || tv.status === "partial") && tvRows.length ? `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div>
          <h2>TradingView 기술적 매매 신호</h2>
          <p>${escapeHtml(tv.symbol || data.ticker || ticker)} scanner consensus${tv.status === "partial" ? " · 일부 시간대 실패" : ""}</p>
        </div>
        <span class="status-badge status-${_statusForAction(tvConsensus.action)}">${escapeHtml(tvConsensus.label || "-")}</span>
      </div>
      <div class="panel-body">
        <div class="metric-grid" style="margin-bottom:12px">
          <div class="metric-card">
            <span class="metric-label">최종 액션</span>
            <span class="metric-value" style="font-size:22px;color:${_signalToneColor(tvConsensus.tone)}">${escapeHtml(tvConsensus.label || "-")}</span>
            <span class="metric-sub">평균 점수 ${tvScore(tv.consensus_score)}</span>
            ${renderSourceLabel("TradingView scanner popup-technicals")}
          </div>
          <div class="metric-card">
            <span class="metric-label">신뢰도</span>
            <span class="metric-value">${Math.round((tv.confidence || 0) * 100)}%</span>
            <span class="metric-sub">점수 절대값 기반</span>
            ${renderSourceLabel("TradingView scanner popup-technicals")}
          </div>
          <div class="metric-card">
            <span class="metric-label">강한 신호</span>
            <span class="metric-value">${tv.strong_signal_count || 0}</span>
            <span class="metric-sub">강한 매수/매도 시간대</span>
            ${renderSourceLabel("TradingView scanner popup-technicals")}
          </div>
        </div>
        <div style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="border-bottom:2px solid var(--border)">
                <th style="text-align:left;padding:7px 10px">시간대</th>
                <th style="text-align:left;padding:7px 10px">신호</th>
                <th style="text-align:right;padding:7px 10px">종합</th>
                <th style="text-align:right;padding:7px 10px">MA</th>
                <th style="text-align:right;padding:7px 10px">Osc</th>
                <th style="text-align:right;padding:7px 10px">RSI</th>
                <th style="text-align:right;padding:7px 10px">MACD</th>
                <th style="text-align:right;padding:7px 10px">Close</th>
              </tr>
            </thead>
            <tbody>
              ${tvRows.map(row => `
                <tr style="border-bottom:1px solid var(--border)">
                  <td style="padding:7px 10px;font-weight:700">${escapeHtml(row.label || row.timeframe || "-")}</td>
                  <td style="padding:7px 10px;color:${_signalToneColor(row?.recommendation?.tone)};font-weight:700">${tvSignalLabel(row)}</td>
                  <td style="text-align:right;padding:7px 10px">${tvScore(row.recommend_all)}</td>
                  <td style="text-align:right;padding:7px 10px">${tvScore(row.recommend_ma)}</td>
                  <td style="text-align:right;padding:7px 10px">${tvScore(row.recommend_other)}</td>
                  <td style="text-align:right;padding:7px 10px">${_num(row.rsi)}</td>
                  <td style="text-align:right;padding:7px 10px">${tvScore(row.macd)}</td>
                  <td style="text-align:right;padding:7px 10px">${_$(row.close)}</td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>
        ${renderSourceCaption("TradingView scanner popup-technicals by timeframe")}
        ${tvErrors.length ? `<p style="margin:10px 0 0;color:var(--muted);font-size:12px">일부 시간대 실패: ${tvErrors.map(err => escapeHtml(err.label || err.timeframe || "-")).join(", ")}</p>` : ""}
        ${tvDetailHtml}
      </div>
    </section>` : `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>TradingView 기술적 매매 신호</h2><p>${escapeHtml(tv.error || "scanner 데이터를 불러오지 못했습니다.")}</p></div></div>
    </section>`;

  // Generate charts
  const dates = recs.map(r => r.date);
  const chartHtml = _renderTechnicalCharts(recs, dates);

  container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance OHLCV", "TradingView scanner popup-technicals", "TradingView right-details"]) + `
    <section class="metric-grid" style="margin-bottom:14px">
      <div class="metric-card">
        <span class="metric-label">현재가</span>
        <span class="metric-value" style="font-size:22px">${_$(data.latest_price)}</span>
        <span class="metric-sub ${_chgCls(data.change_pct)}">${_pct(data.change_pct)} 전일 대비</span>
        ${renderSourceLabel("Yahoo Finance OHLCV")}
      </div>
      <div class="metric-card">
        <span class="metric-label">시장 레짐</span>
        <span class="metric-value" style="font-size:16px;color:${regimeColor}">${regimeLabel}</span>
        <span class="metric-sub">EMA200 기준</span>
        ${renderSourceLabel("Yahoo Finance OHLCV · derived EMA200")}
      </div>
      <div class="metric-card">
        <span class="metric-label">RSI(14)</span>
        <span class="metric-value" style="color:${rsiColor}">${_num(rsi)}</span>
        <span class="metric-sub" style="color:${rsiColor}">${rsiLabel}</span>
        ${renderSourceLabel("Yahoo Finance OHLCV · derived RSI")}
      </div>
      <div class="metric-card">
        <span class="metric-label">EMA 20 / 50 / 200</span>
        <span class="metric-value" style="font-size:13px">${_$(data.latest_ema20,2)} / ${_$(data.latest_ema50,2)}</span>
        <span class="metric-sub">EMA200 = ${_$(data.latest_ema200,2)}</span>
        ${renderSourceLabel("Yahoo Finance OHLCV · derived EMA")}
      </div>
      <div class="metric-card">
        <span class="metric-label">ATR(14) 일간 변동성</span>
        <span class="metric-value">${_$(data.latest_atr)}</span>
        <span class="metric-sub">±${data.latest_atr && data.latest_price ? _num(data.latest_atr/data.latest_price*100)+"%" : "-"}</span>
        ${renderSourceLabel("Yahoo Finance OHLCV · derived ATR")}
      </div>
    </section>
    ${tradingViewHtml}
    ${tradingViewDetailsHtml}
    <section class="panel">
      <div class="panel-header"><div><h2>기술적 지표 차트</h2><p>가격·볼린저·EMA / MACD / RSI / 거래량</p></div></div>
      <div class="panel-body" style="padding:0 4px">${chartHtml}${renderSourceCaption("Yahoo Finance OHLCV · derived Bollinger/EMA/MACD/RSI/volume")}</div>
    </section>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4: 멀티 비교
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisCompare(container, period) {
  const data = state.analysisCompare || {};
  const COMPARE_COLORS = ["#6366f1","#f59e0b","#22c55e","#ef4444","#06b6d4","#d946ef"];

  const defaultTickers = "SOXL,TQQQ,NVDA,QQQ,SPY";

  const controlPanel = `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>멀티 종목 비교</h2><p>최대 6개 종목의 정규화 수익률 (시작=100)</p></div></div>
      <div class="panel-body">
        <div class="analysis-controls">
          <div class="analysis-control-group" style="flex:3;min-width:220px">
            <label>종목 (쉼표로 구분, 최대 6개)</label>
            <input id="compare-tickers" class="analysis-select" type="text" value="${escapeHtml(data.tickers?.join(",")||defaultTickers)}" placeholder="SOXL,TQQQ,NVDA,QQQ,SPY"/>
          </div>
          <div class="analysis-control-group">
            <label>기간</label>
            <select id="compare-period" class="analysis-select">
              ${PERIOD_OPTIONS.map(p => `<option value="${p.id}" ${p.id===period?"selected":""}>${p.label}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group" style="align-self:flex-end">
            <button id="btn-compare-fetch" class="button button-primary" style="height:38px">📊 비교</button>
          </div>
        </div>
      </div>
    </section>`;

  if (!data.dates) {
    container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance adjusted close series"]) + `<div class="analysis-loading">종목과 기간을 설정하고 비교 버튼을 누르세요.</div>`;
    return;
  }

  const dates = data.dates || [];
  const tickers = data.tickers || [];
  const series = data.series || {};
  const summary = data.summary || [];

  // Multi-line chart
  const W = 900, H = 260, PL = 55, PR = 20, PT = 20, PB = 38;
  const innerW = W - PL - PR, innerH = H - PT - PB;
  const allVals = tickers.flatMap(t => (series[t]||[]).filter(v=>v!=null));
  const sc = _svgScale(allVals, innerH, 0.05);

  const dateToX = (i) => PL + (i / Math.max(dates.length - 1, 1)) * innerW;
  const valToY = (v) => PT + sc.toY(v);

  const lines = tickers.map((t, ti) => {
    const pts = (series[t]||[]).map((v,i) => v!=null ? `${dateToX(i).toFixed(1)},${valToY(v).toFixed(1)}` : null).filter(Boolean);
    return _svgLine(pts, COMPARE_COLORS[ti % COMPARE_COLORS.length], 2);
  });

  // Baseline 100 line
  const baseY = valToY(100);

  // X-axis labels
  let xLabels = "";
  const step = Math.max(1, Math.floor(dates.length / 5));
  for (let i = 0; i < dates.length; i += step) {
    xLabels += `<text x="${dateToX(i).toFixed(1)}" y="${PT+innerH+14}" font-size="10" fill="#94a3b8" text-anchor="middle">${dates[i].slice(0,7)}</text>`;
  }

  // Y-axis labels
  let yLabels = "";
  for (let i = 0; i <= 4; i++) {
    const v = sc.min + (i / 4) * (sc.max - sc.min);
    const y = PT + sc.toY(v);
    yLabels += `<text x="${PL-5}" y="${y.toFixed(1)}" font-size="10" fill="#94a3b8" text-anchor="end" dominant-baseline="middle">${v.toFixed(0)}</text>`;
  }

  // Legend
  const legend = tickers.map((t, ti) => `
    <span style="display:inline-flex;align-items:center;gap:5px;margin-right:14px;font-size:12px;font-weight:600;color:${COMPARE_COLORS[ti]}">
      <span style="width:18px;height:2px;display:inline-block;background:${COMPARE_COLORS[ti]};border-radius:1px"></span>${t}
    </span>`).join("");

  container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance adjusted close series"]) + `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>정규화 수익률 차트 (시작 = 100)</h2></div></div>
      <div class="panel-body" style="padding:4px">
        <div style="margin-bottom:8px">${legend}</div>
        <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-height:280px;display:block">
          <rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}" fill="#fafbfc" rx="4"/>
          <line x1="${PL}" y1="${baseY.toFixed(1)}" x2="${PL+innerW}" y2="${baseY.toFixed(1)}" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="4,3"/>
          ${[0,1,2,3,4].map(i => {
            const v = sc.min + (i/4)*(sc.max-sc.min);
            const y = PT + sc.toY(v);
            return `<line x1="${PL}" y1="${y.toFixed(1)}" x2="${PL+innerW}" y2="${y.toFixed(1)}" stroke="#e2e8f0" stroke-width="0.7"/>`;
          }).join("")}
          <clipPath id="compareClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}"/></clipPath>
          <g clip-path="url(#compareClip)">${lines.join("")}</g>
          <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
          <line x1="${PL}" y1="${PT+innerH}" x2="${PL+innerW}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
          ${yLabels}${xLabels}
        </svg>
        ${renderSourceCaption("Yahoo Finance adjusted close series")}
      </div>
    </section>
    <section class="panel">
      <div class="panel-header"><div><h2>기간 수익률 순위</h2></div></div>
      <div class="panel-body" style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <thead><tr style="border-bottom:2px solid var(--border)">
            <th style="text-align:left;padding:8px 10px">순위</th>
            <th style="text-align:left;padding:8px 10px">종목</th>
            <th style="text-align:right;padding:8px 10px">정규화 현재값</th>
            <th style="text-align:right;padding:8px 10px">기간 수익률</th>
            <th style="padding:8px 10px;min-width:120px">게이지</th>
          </tr></thead>
          <tbody>
            ${summary.map((s, i) => {
              const ret = s.total_return_pct;
              const pct100 = Math.max(Math.min(Math.abs(ret||0)/50*100, 100), 0);
              const barColor = ret >= 0 ? "#22c55e" : "#ef4444";
              const color = COMPARE_COLORS[tickers.indexOf(s.ticker) % COMPARE_COLORS.length];
              return `<tr style="border-bottom:1px solid var(--border)">
                <td style="padding:7px 10px;color:var(--muted)">#${i+1}</td>
                <td style="padding:7px 10px;font-weight:700;color:${color}">${escapeHtml(s.ticker)}</td>
                <td style="text-align:right;padding:7px 10px">${_num(s.latest_norm,2)}</td>
                <td style="text-align:right;padding:7px 10px;font-weight:700;${ret>=0?"color:#15803d":"color:#b91c1c"}">${_pct(ret)}</td>
                <td style="padding:7px 10px">
                  <div style="background:#e2e8f0;border-radius:4px;height:8px;overflow:hidden">
                    <div style="height:100%;width:${pct100}%;background:${barColor};border-radius:4px;transition:width 0.5s"></div>
                  </div>
                </td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
        ${renderSourceCaption("Yahoo Finance adjusted close series · normalized return calculation")}
      </div>
    </section>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 5: 포트폴리오 성과
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisPortfolio(container) {
  const data = state.analysisPortfolio || {};
  const agg = data.aggregate || {};
  const runs = data.runs || [];
  const curve = data.equity_curve || [];
  const diagnostics = data.diagnostics || {};
  const skippedRuns = diagnostics.skipped_runs || [];
  const statusCounts = diagnostics.status_counts || {};

  const loadBtn = `<div style="display:flex;justify-content:flex-end;margin-bottom:10px">
    <button id="btn-portfolio-fetch" class="button button-primary" type="button">📊 실행 데이터 조회</button>
  </div>`;
  const portfolioSourceNote = renderDataSourceNote("analysis", ["runs/*/manifest.json", "trades.json", "equity curve artifacts"]);

  if (!data.aggregate) {
    container.innerHTML = loadBtn + portfolioSourceNote + `<div class="analysis-loading">전략 실행 성과 데이터를 불러옵니다.</div>`;
    return;
  }
  const emptyPortfolioHtml = !runs.length ? `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div>
          <h2>성과 산출 가능한 실행 없음</h2>
          <p>${escapeHtml(diagnostics.empty_reason || "최근 실행에서 매매 결과를 찾지 못했습니다.")}</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="metric-grid" style="margin-bottom:12px">
          <div class="metric-card">
            <span class="metric-label">검사한 실행</span>
            <span class="metric-value">${diagnostics.checked_run_count ?? 0}</span>
            <span class="metric-sub">최근 실행 기준</span>
            ${renderSourceLabel("runs/*/manifest.json")}
          </div>
          <div class="metric-card">
            <span class="metric-label">성과 가능 실행</span>
            <span class="metric-value">${diagnostics.performance_run_count ?? 0}</span>
            <span class="metric-sub">trades.json 포함</span>
            ${renderSourceLabel("trades.json discovery")}
          </div>
          <div class="metric-card">
            <span class="metric-label">실패 실행</span>
            <span class="metric-value">${statusCounts.failed ?? 0}</span>
            <span class="metric-sub">최근 검사 범위</span>
            ${renderSourceLabel("runs/*/manifest.json status")}
          </div>
        </div>
        <p style="margin:0 0 10px;color:var(--muted);font-size:13px">
          현재 최근 실행은 매매 로그가 생성되기 전에 중단되었습니다. 실패 코드를 먼저 해결한 뒤 simulate를 다시 실행하면 Sharpe, Sortino, MDD가 채워집니다.
        </p>
        ${skippedRuns.length ? `
        <div style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:12px">
            <thead><tr style="border-bottom:2px solid var(--border)">
              <th style="text-align:left;padding:6px 8px">실행 ID</th>
              <th style="text-align:left;padding:6px 8px">상태</th>
              <th style="text-align:left;padding:6px 8px">실패 코드</th>
              <th style="text-align:left;padding:6px 8px">건너뛴 이유</th>
            </tr></thead>
            <tbody>
              ${skippedRuns.map(r => `<tr style="border-bottom:1px solid var(--border)">
                <td style="padding:5px 8px;font-family:monospace;font-size:11px">${escapeHtml(String(r.run_id || "").slice(-24))}</td>
                <td style="padding:5px 8px">${statusBadge(r.status || "unknown")}</td>
                <td style="padding:5px 8px;font-family:monospace;font-size:11px">${escapeHtml(r.failure_code || "-")}</td>
                <td style="padding:5px 8px;color:var(--muted)">${escapeHtml(r.error || r.reason || "-")}</td>
              </tr>`).join("")}
            </tbody>
          </table>
        </div>` : ""}
      </div>
    </section>` : "";

  // Equity curve chart
  let eqChart = "<p style='color:var(--muted);font-size:13px'>에쿼티 커브 데이터 없음</p>";
  if (curve.length > 1) {
    const W = 900, H = 180, PL = 70, PR = 20, PT = 10, PB = 30;
    const innerW = W - PL - PR, innerH = H - PT - PB;
    const eqVals = curve.map(r => r.equity).filter(v => v!=null);
    const sc = _svgScale(eqVals, innerH, 0.05);
    const dateIdxs = curve.map((_, i) => i);
    const pts = curve.map((r,i) =>
      r.equity != null ? `${(PL + i/(curve.length-1)*innerW).toFixed(1)},${(PT+sc.toY(r.equity)).toFixed(1)}` : null
    ).filter(Boolean);
    const areaPts = [...pts, `${PL+innerW},${PT+innerH}`, `${PL},${PT+innerH}`].join(" ");
    const step = Math.max(1, Math.floor(curve.length / 5));
    let xL = "", yL = "";
    for (let i = 0; i < curve.length; i += step) {
      const x = PL + i/(curve.length-1)*innerW;
      const d = curve[i].date?.slice(0,10)||"";
      xL += `<text x="${x.toFixed(1)}" y="${PT+innerH+14}" font-size="10" fill="#94a3b8" text-anchor="middle">${d.slice(0,7)}</text>`;
    }
    for (let i = 0; i <= 4; i++) {
      const v = sc.min + (i/4)*(sc.max-sc.min);
      const y = PT + sc.toY(v);
      yL += `<text x="${PL-5}" y="${y.toFixed(1)}" font-size="10" fill="#94a3b8" text-anchor="end" dominant-baseline="middle">$${(v/1000).toFixed(0)}K</text>`;
    }
    eqChart = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-height:200px;display:block">
      <defs>
        <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#6366f1" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="#6366f1" stop-opacity="0"/>
        </linearGradient>
        <clipPath id="eqClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}"/></clipPath>
      </defs>
      <rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}" fill="#fafbfc" rx="4"/>
      <g clip-path="url(#eqClip)">
        <polygon fill="url(#eqGrad)" points="${areaPts}"/>
        ${_svgLine(pts, "#6366f1", 2)}
      </g>
      <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
      <line x1="${PL}" y1="${PT+innerH}" x2="${PL+innerW}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
      ${yL}${xL}
    </svg>`;
  }

  container.innerHTML = loadBtn + portfolioSourceNote + `
    <section class="metric-grid" style="margin-bottom:14px">
      <div class="metric-card">
        <span class="metric-label">분석 실행 수</span>
        <span class="metric-value" style="font-size:24px">${agg.run_count??"-"}</span>
        <span class="metric-sub">최근 10개 기준</span>
        ${renderSourceLabel("runs/*/manifest.json · trades.json")}
      </div>
      <div class="metric-card">
        <span class="metric-label">평균 Sharpe 비율</span>
        <span class="metric-value ${_chgCls(agg.avg_sharpe)}">${_num(agg.avg_sharpe)}</span>
        <span class="metric-sub">연환산 일간</span>
        ${renderSourceLabel("trades.json · equity curve artifacts")}
      </div>
      <div class="metric-card">
        <span class="metric-label">평균 Sortino 비율</span>
        <span class="metric-value ${_chgCls(agg.avg_sortino)}">${_num(agg.avg_sortino)}</span>
        <span class="metric-sub">하방 표준편차 기준</span>
        ${renderSourceLabel("trades.json · equity curve artifacts")}
      </div>
      <div class="metric-card">
        <span class="metric-label">평균 승률</span>
        <span class="metric-value">${_num(agg.avg_win_rate)}%</span>
        <span class="metric-sub">전체 매매 기준</span>
        ${renderSourceLabel("trades.json")}
      </div>
      <div class="metric-card">
        <span class="metric-label">평균 MDD</span>
        <span class="metric-value analysis-negative">-${_num(agg.avg_max_drawdown)}%</span>
        <span class="metric-sub">최대 낙폭</span>
        ${renderSourceLabel("equity curve artifacts")}
      </div>
      <div class="metric-card">
        <span class="metric-label">평균 수익률</span>
        <span class="metric-value ${_chgCls(agg.avg_total_return)}">${_pct(agg.avg_total_return)}</span>
        <span class="metric-sub">누적 기준</span>
        ${renderSourceLabel("trades.json · final capital")}
      </div>
    </section>
    ${emptyPortfolioHtml}
    ${curve.length > 1 ? `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>에쿼티 커브</h2><p>최근 실행 자본금 추이</p></div></div>
      <div class="panel-body" style="padding:0 4px">${eqChart}${renderSourceCaption("equity curve artifacts from completed runs")}</div>
    </section>` : ""}
    <section class="panel">
      <div class="panel-header"><div><h2>실행 이력</h2></div></div>
      <div class="panel-body" style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:12px">
          <thead><tr style="border-bottom:2px solid var(--border)">
            <th style="text-align:left;padding:6px 8px">실행 ID</th>
            <th style="text-align:right;padding:6px 8px">매매수</th>
            <th style="text-align:right;padding:6px 8px">Sharpe</th>
            <th style="text-align:right;padding:6px 8px">Sortino</th>
            <th style="text-align:right;padding:6px 8px">승률</th>
            <th style="text-align:right;padding:6px 8px">MDD</th>
            <th style="text-align:right;padding:6px 8px">누적수익</th>
            <th style="text-align:right;padding:6px 8px">최종자본</th>
          </tr></thead>
          <tbody>
            ${runs.map(r => `<tr style="border-bottom:1px solid var(--border)">
              <td style="padding:5px 8px;font-family:monospace;font-size:11px">${escapeHtml((r.run_id||"").slice(-12))}</td>
              <td style="text-align:right;padding:5px 8px">${r.total_trades??"-"}</td>
              <td style="text-align:right;padding:5px 8px;${_chgCls(r.sharpe)?`color:${r.sharpe>0?"var(--success)":"var(--failed)"}`:"color:var(--muted)"}">${_num(r.sharpe)}</td>
              <td style="text-align:right;padding:5px 8px">${_num(r.sortino)}</td>
              <td style="text-align:right;padding:5px 8px">${_num(r.win_rate)}%</td>
              <td style="text-align:right;padding:5px 8px;color:var(--failed)">-${_num(r.max_drawdown)}%</td>
              <td style="text-align:right;padding:5px 8px;font-weight:600;${r.total_return>=0?"color:var(--success)":"color:var(--failed)"}">${_pct(r.total_return)}</td>
              <td style="text-align:right;padding:5px 8px">${_$(r.final_capital,0)}</td>
            </tr>`).join("")}
          </tbody>
        </table>
        ${renderSourceCaption("runs/*/manifest.json · trades.json")}
      </div>
    </section>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 6: 경제 캘린더
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisCalendar(container) {
  const data = state.analysisCalendar || {};
  const events = data.events || [];

  const loadBtn = `<div style="display:flex;justify-content:flex-end;margin-bottom:10px">
    <button id="btn-calendar-fetch" class="button button-primary" type="button">📅 캘린더 로드</button>
  </div>`;
  const calendarSourceNote = renderDataSourceNote("analysis", ["FRED economic series", "release cadence estimates"]);

  if (!events.length) {
    container.innerHTML = loadBtn + calendarSourceNote + `<div class="analysis-loading">FRED 경제 지표 발표 일정을 불러옵니다.</div>`;
    return;
  }

  const today = new Date().toISOString().slice(0, 10);

  const rows = events.map(ev => {
    const upcoming = ev.is_upcoming;
    const change = ev.change;
    const changeColor = change == null ? "" : change > 0 ? "color:var(--success)" : change < 0 ? "color:var(--failed)" : "color:var(--muted)";

    return `<div class="calendar-event ${upcoming ? "calendar-upcoming" : ""}">
      <div class="calendar-icon">${ev.icon}</div>
      <div class="calendar-main">
        <div class="calendar-name">${escapeHtml(ev.name)}</div>
        <div class="calendar-meta">
          <span class="calendar-freq">${ev.frequency}</span>
          <span class="calendar-series">${ev.series_id}</span>
        </div>
      </div>
      <div class="calendar-values">
        <div>최근: <strong>${ev.latest_value != null ? _num(ev.latest_value, 3) : "-"}</strong>
          ${change != null ? `<span style="${changeColor};font-size:11px;margin-left:4px">(${change >= 0 ? "+" : ""}${_num(change, 3)})</span>` : ""}
        </div>
        <div style="font-size:11px;color:var(--muted)">${ev.latest_date || "-"}</div>
      </div>
      <div class="calendar-next ${upcoming ? "is-upcoming" : ""}">
        <div style="font-size:11px;font-weight:600">${upcoming ? "⏳ 예정" : "📆 추정"}</div>
        <div style="font-size:13px;font-weight:700">${ev.next_estimated || "-"}</div>
      </div>
    </div>`;
  }).join("");

  container.innerHTML = loadBtn + calendarSourceNote + `
    <section class="panel">
      <div class="panel-header"><div><h2>📅 주요 경제 지표 발표 일정</h2><p>기준일: ${today} | FRED 최신 데이터 기반, 다음 발표일은 추정치입니다.</p></div></div>
      <div class="panel-body">
        <div class="calendar-list">${rows}</div>
        ${renderSourceCaption("FRED economic series · release cadence estimates")}
      </div>
    </section>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// SVG Chart Helpers
// ══════════════════════════════════════════════════════════════════════════════

function _renderDualAxisChart(stockHistory, macroHistory) {
  const W = 900, H = 260, PL = 60, PR = 65, PT = 20, PB = 40;
  const innerW = W - PL - PR, innerH = H - PT - PB;

  if (!stockHistory.length) return `<div style="height:200px;display:flex;align-items:center;justify-content:center;color:var(--muted)">데이터 없음</div>`;

  const stockDates = stockHistory.map(d => d.date);
  const allDates = [...new Set([...stockDates, ...macroHistory.map(d => d.date)])].sort();
  const xMin = allDates[0], xMax = allDates[allDates.length - 1];
  const dtX = (d) => { const t = d >= xMax ? 1 : d <= xMin ? 0 : d.localeCompare(xMin) / xMax.localeCompare(xMin); return PL + t * innerW; };

  const sVals = stockHistory.map(d => d.close).filter(v => v!=null && !isNaN(v));
  const sc = _svgScale(sVals, innerH, 0.08);
  const sToY = (v) => PT + sc.toY(v);

  const sPts = stockHistory.filter(d => d.close!=null).map(d => `${dtX(d.date).toFixed(1)},${sToY(d.close).toFixed(1)}`);
  const sAreaPts = [...sPts, `${(PL+innerW).toFixed(1)},${(PT+innerH).toFixed(1)}`, `${PL},${(PT+innerH).toFixed(1)}`].join(" ");

  let macroLine = "", macroAxis = "";
  const mVals = macroHistory.map(d => d.value).filter(v => v!=null && !isNaN(v));
  if (mVals.length > 1) {
    const msc = _svgScale(mVals, innerH, 0.08);
    const mToY = (v) => PT + msc.toY(v);
    const mPts = macroHistory.filter(d => d.value!=null && !isNaN(d.value) && d.date>=xMin && d.date<=xMax)
      .map(d => `${dtX(d.date).toFixed(1)},${mToY(d.value).toFixed(1)}`);
    if (mPts.length) macroLine = _svgLine(mPts, "#f59e0b", 2, "5,3");
    for (let i = 0; i <= 4; i++) {
      const v = msc.min + (i/4)*(msc.max-msc.min);
      macroAxis += `<text x="${W-PR+7}" y="${(PT+msc.toY(v)).toFixed(1)}" font-size="10" fill="#f59e0b" dominant-baseline="middle">${v.toFixed(2)}</text>`;
    }
    macroAxis += `<line x1="${W-PR}" y1="${PT}" x2="${W-PR}" y2="${PT+innerH}" stroke="#f59e0b" stroke-width="0.5" opacity="0.4"/>`;
  }

  let leftAxis = "";
  for (let i = 0; i <= 4; i++) {
    const v = sc.min + (i/4)*(sc.max-sc.min);
    leftAxis += `<text x="${PL-5}" y="${(PT+sc.toY(v)).toFixed(1)}" font-size="10" fill="#6366f1" text-anchor="end" dominant-baseline="middle">$${v.toFixed(0)}</text>`;
  }
  let xAxis = "";
  const xStep = Math.max(1, Math.floor(allDates.length/5));
  for (let i = 0; i < allDates.length; i += xStep) {
    const d = allDates[i];
    xAxis += `<text x="${dtX(d).toFixed(1)}" y="${PT+innerH+14}" font-size="10" fill="#94a3b8" text-anchor="middle">${d.slice(0,7)}</text>`;
  }

  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-height:280px;display:block" preserveAspectRatio="xMidYMid meet">
    <defs>
      <linearGradient id="sGrad2" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#6366f1" stop-opacity="0.25"/><stop offset="100%" stop-color="#6366f1" stop-opacity="0"/>
      </linearGradient>
      <clipPath id="dualClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}"/></clipPath>
    </defs>
    <rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}" fill="#fafbfc" rx="4"/>
    ${[0,1,2,3,4].map(i => { const v=sc.min+(i/4)*(sc.max-sc.min); const y=PT+sc.toY(v); return `<line x1="${PL}" y1="${y.toFixed(1)}" x2="${PL+innerW}" y2="${y.toFixed(1)}" stroke="#e2e8f0" stroke-width="1"/>`; }).join("")}
    <g clip-path="url(#dualClip)">
      <polygon fill="url(#sGrad2)" points="${sAreaPts}"/>
      ${_svgLine(sPts, "#6366f1", 2.2)}
      ${macroLine}
    </g>
    <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
    <line x1="${PL}" y1="${PT+innerH}" x2="${PL+innerW}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
    ${leftAxis}${macroAxis}${xAxis}
    <text x="${PL+8}" y="${PT+14}" font-size="11" font-weight="600" fill="#6366f1">● 주가 (좌축)</text>
    ${mVals.length>1?`<text x="${PL+110}" y="${PT+14}" font-size="11" font-weight="600" fill="#f59e0b">--- 경제 지표 (우축)</text>`:""}
  </svg>`;
}

function _renderTechnicalCharts(recs, dates) {
  if (!recs.length) return `<div style="color:var(--muted);padding:16px">데이터 없음</div>`;

  const W = 900;
  const PL = 62, PR = 10, PT = 10, PB = 24;
  const innerW = W - PL - PR;

  const dtX = (i) => PL + (i / Math.max(dates.length - 1, 1)) * innerW;

  // ── Panel 1: Price + Bollinger + EMA ─────────────────────
  const H1 = 220;
  const closes = recs.map(r => r.close);
  const bbU = recs.map(r => r.bb_upper);
  const bbL = recs.map(r => r.bb_lower);
  const ema20 = recs.map(r => r.ema20);
  const ema50 = recs.map(r => r.ema50);
  const ema200 = recs.map(r => r.ema200);

  const allP1 = [...closes, ...bbU.filter(v=>v!=null), ...bbL.filter(v=>v!=null)].filter(v=>v!=null);
  const sc1 = _svgScale(allP1, H1 - PT - PB, 0.03);
  const toY1 = (v) => PT + sc1.toY(v);

  const pricePts = closes.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);
  const bbUPts = bbU.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);
  const bbLPts = bbL.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);
  const ema20Pts = ema20.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);
  const ema50Pts = ema50.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);
  const ema200Pts = ema200.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);

  let yL1 = "";
  for (let i = 0; i <= 4; i++) {
    const v = sc1.min + (i/4)*(sc1.max-sc1.min);
    yL1 += `<text x="${PL-5}" y="${toY1(v).toFixed(1)}" font-size="10" fill="#94a3b8" text-anchor="end" dominant-baseline="middle">$${v.toFixed(0)}</text>`;
  }

  // Regime color bars
  const regimeBars = recs.map((r,i) => {
    const col = r.regime==="bull"?"rgba(34,197,94,0.12)":r.regime==="bear"?"rgba(239,68,68,0.12)":"rgba(234,179,8,0.08)";
    const x = dtX(i), nx = dtX(i+1);
    return `<rect x="${x.toFixed(1)}" y="${PT}" width="${(nx-x).toFixed(1)}" height="${H1-PT-PB}" fill="${col}" opacity="0.7"/>`;
  }).join("");

  const chart1 = `<svg viewBox="0 0 ${W} ${H1}" style="width:100%;display:block;margin-bottom:4px">
    <defs>
      <linearGradient id="p1Grad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#6366f1" stop-opacity="0.2"/><stop offset="100%" stop-color="#6366f1" stop-opacity="0"/>
      </linearGradient>
      <clipPath id="p1Clip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${H1-PT-PB}"/></clipPath>
    </defs>
    <rect x="${PL}" y="${PT}" width="${innerW}" height="${H1-PT-PB}" fill="#fafbfc" rx="4"/>
    <g clip-path="url(#p1Clip)">
      ${regimeBars}
      ${_svgLine(bbUPts,"#94a3b8",1,"3,3")}
      ${_svgLine(bbLPts,"#94a3b8",1,"3,3")}
      ${_svgArea(pricePts,"url(#p1Grad)")}
      ${_svgLine(pricePts,"#6366f1",2)}
      ${_svgLine(ema20Pts,"#f59e0b",1.5)}
      ${_svgLine(ema50Pts,"#22c55e",1.5)}
      ${_svgLine(ema200Pts,"#ef4444",1.5,"6,3")}
    </g>
    <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${H1-PB}" stroke="#cbd5e1" stroke-width="1"/>
    <line x1="${PL}" y1="${H1-PB}" x2="${PL+innerW}" y2="${H1-PB}" stroke="#cbd5e1" stroke-width="1"/>
    ${yL1}
    <text x="${PL+6}" y="${PT+13}" font-size="10" font-weight="600" fill="#6366f1">● 가격</text>
    <text x="${PL+55}" y="${PT+13}" font-size="10" font-weight="600" fill="#f59e0b">EMA20</text>
    <text x="${PL+100}" y="${PT+13}" font-size="10" font-weight="600" fill="#22c55e">EMA50</text>
    <text x="${PL+148}" y="${PT+13}" font-size="10" font-weight="600" fill="#ef4444">EMA200</text>
    <text x="${PL+200}" y="${PT+13}" font-size="10" fill="#94a3b8">--- 볼린저 밴드</text>
  </svg>`;

  // ── Panel 2: MACD ───────────────────────────────────────
  const H2 = 100;
  const macdL = recs.map(r => r.macd_line);
  const macdS = recs.map(r => r.macd_signal);
  const macdH = recs.map(r => r.macd_hist);
  const allM = [...macdL,...macdS,...macdH].filter(v=>v!=null&&!isNaN(v));
  const sc2 = _svgScale(allM, H2 - PT - PB, 0.15);
  const toY2 = (v) => PT + sc2.toY(v);
  const zero2 = toY2(0);

  const macdLPts = macdL.map((v,i)=>v!=null?`${dtX(i).toFixed(1)},${toY2(v).toFixed(1)}`:null).filter(Boolean);
  const macdSPts = macdS.map((v,i)=>v!=null?`${dtX(i).toFixed(1)},${toY2(v).toFixed(1)}`:null).filter(Boolean);
  const macdBars = macdH.map((v,i)=>{
    if (v==null) return "";
    const x=dtX(i), bw=Math.max(innerW/dates.length-1,1), y=Math.min(toY2(v),zero2), h=Math.abs(toY2(v)-zero2);
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(h,0.5).toFixed(1)}" fill="${v>=0?"#22c55e":"#ef4444"}" opacity="0.7"/>`;
  }).join("");

  const chart2 = `<svg viewBox="0 0 ${W} ${H2}" style="width:100%;display:block;margin-bottom:4px">
    <defs><clipPath id="macdClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${H2-PT-PB}"/></clipPath></defs>
    <rect x="${PL}" y="${PT}" width="${innerW}" height="${H2-PT-PB}" fill="#fafbfc" rx="4"/>
    <line x1="${PL}" y1="${zero2.toFixed(1)}" x2="${PL+innerW}" y2="${zero2.toFixed(1)}" stroke="#cbd5e1" stroke-width="0.8" stroke-dasharray="3,2"/>
    <g clip-path="url(#macdClip)">
      ${macdBars}
      ${_svgLine(macdLPts,"#6366f1",1.5)}
      ${_svgLine(macdSPts,"#f59e0b",1.5)}
    </g>
    <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${H2-PB}" stroke="#cbd5e1" stroke-width="1"/>
    <text x="${PL+6}" y="${PT+13}" font-size="10" font-weight="600" fill="#1e293b">MACD</text>
    <text x="${PL+46}" y="${PT+13}" font-size="10" fill="#6366f1">MACD(12,26)</text>
    <text x="${PL+120}" y="${PT+13}" font-size="10" fill="#f59e0b">Signal(9)</text>
  </svg>`;

  // ── Panel 3: RSI ────────────────────────────────────────
  const H3 = 100;
  const rsi14 = recs.map(r => r.rsi14);
  const sc3 = { min: 0, max: 100, toY: (v) => (H3-PT-PB) * (1 - v/100) };
  const toY3 = (v) => PT + sc3.toY(v);
  const rsiPts = rsi14.map((v,i)=>v!=null?`${dtX(i).toFixed(1)},${toY3(v).toFixed(1)}`:null).filter(Boolean);
  const ob = toY3(70), os = toY3(30);

  const chart3 = `<svg viewBox="0 0 ${W} ${H3}" style="width:100%;display:block;margin-bottom:4px">
    <defs><clipPath id="rsiClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${H3-PT-PB}"/></clipPath></defs>
    <rect x="${PL}" y="${PT}" width="${innerW}" height="${H3-PT-PB}" fill="#fafbfc" rx="4"/>
    <rect x="${PL}" y="${ob.toFixed(1)}" width="${innerW}" height="${(os-ob).toFixed(1)}" fill="rgba(99,102,241,0.04)"/>
    <line x1="${PL}" y1="${ob.toFixed(1)}" x2="${PL+innerW}" y2="${ob.toFixed(1)}" stroke="#ef4444" stroke-width="0.8" stroke-dasharray="4,3"/>
    <line x1="${PL}" y1="${os.toFixed(1)}" x2="${PL+innerW}" y2="${os.toFixed(1)}" stroke="#22c55e" stroke-width="0.8" stroke-dasharray="4,3"/>
    <g clip-path="url(#rsiClip)">${_svgLine(rsiPts,"#6366f1",1.8)}</g>
    <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${H3-PB}" stroke="#cbd5e1" stroke-width="1"/>
    <text x="${PL+6}" y="${PT+13}" font-size="10" font-weight="600" fill="#1e293b">RSI(14)</text>
    <text x="${PL-5}" y="${ob.toFixed(1)}" font-size="9" fill="#ef4444" text-anchor="end">70</text>
    <text x="${PL-5}" y="${os.toFixed(1)}" font-size="9" fill="#22c55e" text-anchor="end">30</text>
  </svg>`;

  // ── Panel 4: Volume ─────────────────────────────────────
  const H4 = 80;
  const vols = recs.map(r => r.volume);
  const volMA = recs.map(r => r.vol_ma20);
  const maxVol = Math.max(...vols.filter(v=>v!=null));
  const toY4 = (v) => PT + (H4-PT-PB) * (1 - v/maxVol);
  const bw4 = Math.max(innerW/dates.length-0.5, 1);
  const volBars = vols.map((v,i)=>v!=null?`<rect x="${dtX(i).toFixed(1)}" y="${toY4(v).toFixed(1)}" width="${bw4.toFixed(1)}" height="${(H4-PB-toY4(v)).toFixed(1)}" fill="#6366f1" opacity="0.35"/>` : "").join("");
  const volMAPts = volMA.map((v,i)=>v!=null?`${dtX(i).toFixed(1)},${toY4(v).toFixed(1)}`:null).filter(Boolean);

  // X-axis labels (shared)
  const step = Math.max(1, Math.floor(dates.length/5));
  let xL = "";
  for (let i = 0; i < dates.length; i += step) {
    xL += `<text x="${dtX(i).toFixed(1)}" y="${H4-PB+14}" font-size="10" fill="#94a3b8" text-anchor="middle">${dates[i].slice(0,7)}</text>`;
  }

  const chart4 = `<svg viewBox="0 0 ${W} ${H4}" style="width:100%;display:block">
    <defs><clipPath id="volClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${H4-PT-PB}"/></clipPath></defs>
    <rect x="${PL}" y="${PT}" width="${innerW}" height="${H4-PT-PB}" fill="#fafbfc" rx="4"/>
    <g clip-path="url(#volClip)">
      ${volBars}
      ${_svgLine(volMAPts,"#f59e0b",1.5)}
    </g>
    <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${H4-PB}" stroke="#cbd5e1" stroke-width="1"/>
    <line x1="${PL}" y1="${H4-PB}" x2="${PL+innerW}" y2="${H4-PB}" stroke="#cbd5e1" stroke-width="1"/>
    <text x="${PL+6}" y="${PT+13}" font-size="10" font-weight="600" fill="#1e293b">Volume</text>
    <text x="${PL+60}" y="${PT+13}" font-size="10" fill="#f59e0b">MA20</text>
    ${xL}
  </svg>`;

  return chart1 + chart2 + chart3 + chart4;
}
