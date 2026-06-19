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
  apiMonitoring: null,
  tossAccountRegion: localStorage.getItem("jayu.toss.accountRegion") || "ALL",
  selectedTossAccount: localStorage.getItem("jayu.toss.selectedAccount") || "",
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
    if (state.page === "toss-account") {
      const params = new URLSearchParams();
      if (state.selectedTossAccount) params.set("account", state.selectedTossAccount);
      state.tossPortfolio = await api(`/api/v1/toss/portfolio${params.toString() ? `?${params.toString()}` : ""}`);
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
  }[page];
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
    <section class="decision-grid" aria-label="오늘 결론">
      <article class="decision-card status-${statusClass(decision.overall)}" aria-labelledby="status-title">
        <div class="decision-eyebrow">${statusBadge(decision.overall)} <span>${escapeHtml(String(run.mode || "unknown").toUpperCase())}</span></div>
        <h2 id="status-title">${escapeHtml(decisionHeadline(decision.overall))}</h2>
        <p>${escapeHtml(decision.headline)}</p>
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
    </section>
    <section class="panel">
      <div class="panel-header"><div><h2>불일치 상세</h2><p>날짜와 provider별 원본값을 함께 표시합니다.</p></div></div>
      ${renderMismatchTable(data.mismatches)}
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
    </section>
    <section class="panel">
      <div class="panel-header"><div><h2>종목별 판정</h2><p>요청 비중과 승인 비중, 차단 사유</p></div></div>
      ${renderRiskSignals(data.signals)}
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
      </section>
      <section class="panel">
        <div class="panel-header">
          <div><h2>Top decision notes</h2><p>The most important blockers from the run verdict.</p></div>
        </div>
        <div class="panel-body">${renderTraderDecisionNotes(notes)}</div>
      </section>
    </div>
    <div class="section-grid">
      <section class="panel">
        <div class="panel-header">
          <div><h2>Provider trust map</h2><p>Provider/ticker health with mismatch counts and hash trace.</p></div>
          <button class="button button-secondary" type="button" data-go="data-quality">Data Quality</button>
        </div>
        ${renderProviderTrustMap(data.provider_trust || [])}
      </section>
      <section class="panel">
        <div class="panel-header">
          <div><h2>Risk concentration</h2><p>Blocked reason codes grouped by count and excess.</p></div>
          <button class="button button-secondary" type="button" data-go="risk">Risk Gate</button>
        </div>
        <div class="panel-body">${renderRiskConcentration(data.risk_concentration || [])}</div>
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
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>Shadow 이력</h2><p>최근 일자별 근거</p></div></div>
        ${renderPromotionHistory(data.history)}
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
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>Toss Account Dashboard</h1>
        <p>첫 계좌를 자동 선택하고 USD/KRW 환율을 반영해 KRW 기준 보유 종목, 평가금액, 손익, 비중을 보여주는 읽기 전용 계좌 화면입니다.</p>
      </div>
      ${statusBadge(summary.status || data.status)}
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
    ${renderTossRegionTabs(data.region_totals || [])}
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div><h2>Account selector</h2><p>버튼을 누르지 않아도 첫 계좌가 자동으로 선택됩니다. 다른 계좌를 고르면 즉시 다시 조회합니다.</p></div>
        ${statusBadge(data.read_only ? "success" : "blocked", "read only")}
      </div>
      ${renderTossAccountCards(accounts, selected)}
    </section>
    <div class="visual-grid">
      <section class="panel">
        <div class="panel-header"><div><h2>Market split</h2><p>KRW 환산 기준 한국/미국/기타 비중입니다.</p></div></div>
        <div class="panel-body">${renderExposureDonut(data.region_totals || [], "region")}</div>
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>Currency split</h2><p>USD와 KRW가 섞여도 KRW 환산 기준으로 비교합니다.</p></div></div>
        <div class="panel-body">${renderExposureDonut(data.currency_totals || [], "currency")}</div>
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>FX rates</h2><p>환산에 사용한 환율과 유효 시각입니다.</p></div></div>
        <div class="panel-body">${renderFxRateCards(data.fx_rates || [])}</div>
      </section>
    </div>
    <div class="visual-grid">
      <section class="panel">
        <div class="panel-header"><div><h2>Category split</h2><p>주식, ETF, 레버리지 ETF 같은 종목 유형별 노출입니다.</p></div></div>
        <div class="panel-body">${renderExposureDonut(data.category_totals || [], "category")}</div>
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>Sector exposure</h2><p>종목 메타데이터에서 읽은 섹터 기준 상위 노출입니다.</p></div></div>
        <div class="panel-body">${renderExposureDonut(data.sector_totals || [], "sector")}</div>
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>Situation tags</h2><p>집중도, 손익, 당일 급등락, 경고 상태를 태그로 묶었습니다.</p></div></div>
        <div class="panel-body">${renderSituationTags(data.situation_totals || [])}</div>
      </section>
    </div>
    <div class="section-grid">
      <section class="panel">
        <div class="panel-header"><div><h2>Holding allocation</h2><p>${activeRegionLabel} 탭의 KRW 환산 평가금액 기준 보유 비중입니다.</p></div></div>
        <div class="panel-body">${renderHoldingAllocation(allocation)}</div>
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>P/L contributors</h2><p>KRW 환산 평가손익 기여도가 큰 종목입니다.</p></div></div>
        <div class="panel-body">${renderPnlContributors(visibleHoldings)}</div>
      </section>
    </div>
    <section class="panel">
      <div class="panel-header"><div><h2>Holdings</h2><p>수량, 평균단가, 현재가, 평가금액, 손익률을 한 표에서 확인합니다.</p></div></div>
      ${renderTossHoldingsTable(visibleHoldings)}
    </section>
    <section class="panel" style="margin-top:14px">
      <div class="panel-header"><div><h2>Account GET status</h2><p>계좌 화면에서 자동 호출한 GET endpoint 결과입니다.</p></div></div>
      ${renderTossSectionTable(sections)}
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
      <p id="toss-feedback" class="metric-detail" hidden></p>
    </section>
    ${market ? renderTossSnapshot(market) : renderTossEmptyState(status)}
    <section class="panel">
      <div class="panel-header"><div><h2>구현된 GET 엔드포인트</h2><p>토큰 발급을 제외한 API 호출은 모두 GET입니다.</p></div></div>
      ${renderTossEndpointTable(endpointRows)}
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
      <thead><tr><th>Symbol</th><th>Market</th><th>Category</th><th>Sector</th><th>Name</th><th class="numeric">Qty</th><th class="numeric">KRW value</th><th class="numeric">P/L KRW</th><th class="numeric">P/L %</th><th class="numeric">Day %</th><th class="numeric">Weight</th><th>Tags</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${escapeHtml(row.symbol || "-")}</td>
          <td>${statusBadge(row.market_region === "US" ? "warning" : row.market_region === "KR" ? "success" : "not_evaluated", row.market_region || "-")}</td>
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
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>계좌 범위 결과</h2><p>선택한 경우에만 호출됩니다.</p></div></div>
        ${renderTossSectionTable(accountSections)}
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

function metricCard(label, value, status, detail, ratio = null) {
  const width = ratio == null ? 0 : Math.max(0, Math.min(100, Number(ratio) * 100));
  return `
    <article class="metric-card">
      <div class="metric-label"><span>${escapeHtml(label)}</span>${statusBadge(status)}</div>
      <strong class="metric-value">${escapeHtml(value)}</strong>
      <span class="metric-detail">${escapeHtml(detail || "")}</span>
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
  if (data.status === "failed") return "Toss 계좌 조회에 실패했습니다.";
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

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>API 데이터 출처 모니터링</h1>
        <p>프로젝트에서 사용하는 모든 외부 API 데이터 출처의 상태, 자격증명, 정책, 캐시, 최근 활동을 확인합니다.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
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
        </div>
      </section>
    </div>
    ${renderCacheStatsPanel(cacheStats)}
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

  html += '</section>';
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
  const credLabel = p.credential_configured ? "인증 설정됨" : "인증 미설정";

  const envTags = (p.env_names || []).length
    ? `<div class="pmc-env-list">${p.env_names.map((e) => `<span class="pmc-env-tag">${escapeHtml(e)}</span>`).join("")}</div>`
    : "";

  const cacheTtlLabel = policy.cache_ttl_seconds
    ? policy.cache_ttl_seconds >= 3600
      ? `${(policy.cache_ttl_seconds / 3600).toFixed(1)}h`
      : `${Math.round(policy.cache_ttl_seconds / 60)}m`
    : "-";

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
    </article>
  `;
}

function renderCacheStatsPanel(cacheStats) {
  const entries = Object.entries(cacheStats);
  if (!entries.length) {
    return `
      <section class="panel" style="margin-bottom:14px">
        <div class="panel-header"><div><h2>캐시 상태</h2><p>캐시 디렉터리 통계입니다.</p></div></div>
        <div class="panel-body"><div class="empty-state"><strong>캐시 데이터 없음</strong>실행 후 캐시가 생성됩니다.</div></div>
      </section>
    `;
  }
  return `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>캐시 상태</h2><p>provider별 캐시 디렉터리의 파일 수와 용량입니다.</p></div></div>
      <div class="panel-body">
        <div class="cache-stat-grid">
          ${entries.map(([name, stat]) => `
            <div class="cache-stat-card">
              <strong>${escapeHtml(name)}</strong>
              <span>${stat.file_count ?? 0}개 파일 · ${formatBytes(stat.total_bytes ?? 0)}</span>
            </div>
          `).join("")}
        </div>
      </div>
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
}

function navigate(page) {
  if (!["overview", "data-quality", "risk", "signals", "trader-lens", "promotion", "settings", "toss-account", "toss", "api-monitoring"].includes(page)) return;
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
