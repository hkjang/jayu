const state = {
  page: "overview",
  runId: "latest",
  runs: [],
  overview: null,
  dataQuality: null,
  risk: null,
  signals: null,
  promotion: null,
  settingsValidation: null,
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

function shortHash(value) {
  return value ? String(value).slice(0, 8) : "-";
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
    if (state.page === "promotion") {
      state.promotion = await api("/api/v1/promotion");
    }
    if (state.page === "settings") {
      const mode = encodeURIComponent(state.overview?.run?.mode || "shadow");
      state.settingsValidation = await api(`/api/v1/settings/validation?mode=${mode}`);
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
}

function pageTitle(page) {
  return {
    overview: "Overview",
    "data-quality": "Data Quality",
    risk: "Risk Gate",
    signals: "Signal",
    promotion: "Shadow Promotion",
    settings: "Settings Validation",
  }[page];
}

function render() {
  els.root.hidden = false;
  if (state.page === "data-quality") renderDataQuality();
  else if (state.page === "risk") renderRisk();
  else if (state.page === "signals") renderSignals();
  else if (state.page === "promotion") renderPromotion();
  else if (state.page === "settings") renderSettingsValidation();
  else renderOverview();
  bindPageActions();
}

function renderOverview() {
  const data = state.overview;
  const run = data.run;
  const decision = data.decision;
  const gates = data.gates;
  const signals = data.signals;
  const health = data.health;
  const reasons = decision.top_reasons || [];
  const actions = data.recommended_actions || [];
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>운영 상태 Overview</h1>
        <p>실행 완료 여부와 운영 승인 여부를 분리해 표시합니다. 차단 사유가 있으면 정상 지표보다 먼저 검토하세요.</p>
      </div>
      ${statusBadge(run.execution_status, "실행")} 
    </div>
    <section class="status-banner status-${statusClass(decision.overall)}" aria-labelledby="status-title">
      <div>${statusBadge(decision.overall)}</div>
      <div>
        <h2 id="status-title">${escapeHtml(run.mode?.toUpperCase() || "UNKNOWN")} · 운영 ${escapeHtml(
          STATUS_LABELS[run.safety_decision] || run.safety_decision
        )}</h2>
        <p>${escapeHtml(decision.headline)}</p>
      </div>
      <span class="code">${escapeHtml(run.failure_code || "NO_BLOCKER")}</span>
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
          <div><h2>가장 중요한 경고</h2><p>차단 영향도가 높은 순서입니다.</p></div>
          <span class="muted">${reasons.length}건</span>
        </div>
        <div class="panel-body">
          ${renderReasons(reasons)}
        </div>
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>다음 행동</h2><p>현재 판정에 따른 안전한 검토 순서</p></div></div>
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
        <h1>Data Quality</h1>
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
      ${metricCard("Provider", summary.provider_count, summary.failed_source_count ? "warning" : summary.provider_count > 1 ? "success" : "not_evaluated",
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
        <h1>Risk Gate</h1>
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
      ${metricCard("Hold", summary.hold_count, "not_evaluated", "리스크 심사 비대상")}
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
        <h1>Signal</h1>
        <p>Today's signal candidates, publication status, price levels, data verification, and risk blocks.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    <section class="status-banner status-${statusClass(summary.status)}">
      <div>${statusBadge(summary.status)}</div>
      <div>
        <h2>${summary.blocked_count ? `${summary.blocked_count} blocked buy signal(s)` : summary.eligible_count ? `${summary.eligible_count} eligible buy signal(s)` : "No eligible buy signals"}</h2>
        <p>Publication is <strong>${escapeHtml(publication.status || "missing")}</strong>. Signals without verified price data remain operationally unsafe.</p>
      </div>
      <span class="code">${escapeHtml(publication.failure_code || publication.status || "NO_PUBLICATION")}</span>
    </section>
    <section class="metric-grid">
      ${metricCard("Publication", publication.status || "missing", publication.status === "published" ? "success" : publication.status === "blocked" ? "blocked" : "not_evaluated", publication.signal_date || "no approved sidecar")}
      ${metricCard("Eligible buys", `${summary.eligible_count}/${summary.buy_count}`, summary.eligible_count ? "success" : "not_evaluated", "buy signals allowed after gates", gateRatio(summary.eligible_count, summary.blocked_count))}
      ${metricCard("Blocked buys", summary.blocked_count, summary.blocked_count ? "blocked" : summary.buy_count ? "success" : "not_evaluated", "eligible=false")}
      ${metricCard("Hold", summary.hold_count, "not_evaluated", "not a buy candidate")}
      ${metricCard("Data verified", `${summary.data_verified_count}/${summary.total_count}`, summary.data_verified_count === summary.total_count && summary.total_count ? "success" : summary.total_count ? "data_error" : "not_evaluated", "price trust", summary.data_verified_rate)}
      ${metricCard("Signal hash", shortHash(publication.signal_hash), publication.signal_hash ? "success" : "not_evaluated", "publication provenance")}
    </section>
    <section class="panel">
      <div class="panel-header"><div><h2>Signal list</h2><p>Entry, stop, target, liquidity, and reason codes</p></div></div>
      ${renderSignalDetailTable(data.rows)}
    </section>
  `;
}

function renderPromotion() {
  const data = state.promotion;
  const summary = data.summary;
  const metrics = data.metrics || {};
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>Shadow Promotion</h1>
        <p>Shadow run evidence required before paper or live-like operation.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    <section class="status-banner status-${statusClass(summary.status)}">
      <div>${statusBadge(summary.status)}</div>
      <div>
        <h2>${summary.eligible ? "Promotion eligible" : "Promotion blocked"}</h2>
        <p>${summary.failed_criteria_count ? `${summary.failed_criteria_count} criterion/criteria still need evidence.` : "All configured criteria are satisfied."}</p>
      </div>
      <span class="code">${escapeHtml(summary.failure_code || "SHADOW_PROMOTION")}</span>
    </section>
    <section class="metric-grid">
      ${metricCard("Shadow days", summary.shadow_day_count, summary.eligible ? "success" : "warning", "distinct shadow files")}
      ${metricCard("Completed signals", summary.completed_signal_count, summary.completed_signal_count ? "success" : "warning", `${summary.buy_signal_count} buy signals`)}
      ${metricCard("Data success", formatPercent(metrics.data_validation_success_rate), metrics.data_validation_success_rate >= 0.95 ? "success" : "warning", "current / configured")}
      ${metricCard("Disagreement rate", formatPercent(metrics.provider_disagreement_rate), metrics.provider_disagreement_rate === 0 ? "success" : "data_error", "lower is safer")}
      ${metricCard("Risk pass rate", formatPercent(metrics.risk_gate_pass_rate), metrics.risk_gate_pass_rate >= 0.5 ? "success" : "warning", "eligible buy ratio")}
      ${metricCard("Signal stability", formatPercent(metrics.max_signal_count_change_ratio), metrics.max_signal_count_change_ratio <= 1 ? "success" : "warning", "max daily change")}
    </section>
    <div class="section-grid">
      <section class="panel">
        <div class="panel-header"><div><h2>Promotion criteria</h2><p>Observed values against required thresholds</p></div></div>
        ${renderCriteriaTable(data.criteria)}
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>Shadow history</h2><p>Recent daily evidence</p></div></div>
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
        <h1>Settings Validation</h1>
        <p>Mode-specific safety checks. Secrets are redacted and this screen does not write config files.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    <section class="status-banner status-${statusClass(summary.status)}">
      <div>${statusBadge(summary.status)}</div>
      <div>
        <h2>${escapeHtml(String(data.mode).toUpperCase())} configuration ${summary.safe ? "is safe enough to continue" : "needs correction"}</h2>
        <p>${summary.blocked_count} blocking issue(s), ${summary.warning_count} warning(s). Review current and required values before running.</p>
      </div>
      <span class="code">${summary.safe ? "CONFIG_OK" : "CONFIG_REVIEW"}</span>
    </section>
    <section class="metric-grid">
      ${metricCard("Blocking rules", summary.blocked_count, summary.blocked_count ? "blocked" : "success", "must fix")}
      ${metricCard("Warnings", summary.warning_count, summary.warning_count ? "warning" : "success", "review recommended")}
      ${metricCard("Provider audit", data.provider_audit.valid ? "valid" : "invalid", data.provider_audit.valid ? "success" : "blocked", (data.provider_audit.errors || []).join("; ") || "inventory ok")}
      ${metricCard("Survivorship", data.survivorship_audit.valid ? "valid" : "review", data.survivorship_audit.valid ? "success" : "warning", data.survivorship_audit.policy || "unknown")}
      ${metricCard("Promotion", data.promotion_audit.eligible ? "eligible" : "blocked", data.promotion_audit.eligible ? "success" : "warning", "paper/live gate")}
      ${metricCard("Secrets", "redacted", "not_evaluated", "values are never shown")}
    </section>
    <section class="panel">
      <div class="panel-header"><div><h2>Validation rules</h2><p>Current values, required values, and impact</p></div></div>
      ${renderSettingsRules(data.rules)}
    </section>
  `;
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

function renderReasons(reasons) {
  if (!reasons.length) {
    return '<div class="empty-state"><strong>중요 경고가 없습니다.</strong><span>필수 검증 결과를 계속 확인하세요.</span></div>';
  }
  return `<ol class="reason-list">${reasons
    .map(
      (reason) => `
      <li class="reason-item">
        <strong class="code">${escapeHtml(reason.code)}</strong>
        <p>${escapeHtml(reason.message)}</p>
        <small>${escapeHtml(reason.remediation)}</small>
      </li>`
    )
    .join("")}</ol>`;
}

function renderSignalTable(rows) {
  if (!rows?.length) return emptyTable("생성된 신호가 없습니다.", "선택한 run에는 signal artifact가 없습니다.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Ticker</th><th>Status</th><th>Action</th><th>Strategy</th><th class="numeric">Score</th><th class="numeric">Entry</th><th>Data</th><th>Reason codes</th></tr></thead>
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
      <thead><tr><th>Provider</th><th>Ticker</th><th>Status</th><th class="numeric">Rows</th><th>First</th><th>Last</th><th>Hash</th><th>Error</th></tr></thead>
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
      <thead><tr><th>Ticker</th><th>Date</th><th>Field</th><th>Providers</th><th>Values / Missing</th><th class="numeric">Delta</th><th class="numeric">Limit</th></tr></thead>
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
      <thead><tr><th>Status</th><th>Ticker</th><th>Metric</th><th class="numeric">Current</th><th class="numeric">Limit</th><th class="numeric">Excess</th><th>Reason code</th></tr></thead>
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
      <thead><tr><th>Ticker</th><th>Action</th><th>Status</th><th class="numeric">Approved</th><th class="numeric">Passed</th><th class="numeric">Failed</th><th>Reason codes</th></tr></thead>
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
  if (!rows?.length) return emptyTable("No run-local signals found.", "This run has no signal artifact. Global today_signals.json is not mixed into run review.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Ticker</th><th>Status</th><th>Action</th><th>Strategy</th><th class="numeric">Score</th><th class="numeric">Entry</th><th class="numeric">Stop</th><th class="numeric">Target</th><th class="numeric">Approved</th><th>Liquidity</th><th>Data</th><th>Reason codes</th></tr></thead>
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

function renderCriteriaTable(rows) {
  if (!rows?.length) return emptyTable("No promotion criteria recorded.", "Promotion has not been evaluated for the current state.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Criterion</th><th>Status</th><th class="numeric">Observed</th><th class="numeric">Required</th><th>Gap</th></tr></thead>
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
  if (!rows?.length) return emptyTable("No shadow history found.", "Run shadow mode for several days before promotion.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Date</th><th class="numeric">Signals</th><th class="numeric">Buys</th><th class="numeric">Completed</th><th class="numeric">Data valid</th><th class="numeric">Disagreements</th><th class="numeric">Risk pass</th></tr></thead>
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
  if (!rows?.length) return emptyTable("No validation rules returned.", "Configuration validation could not be evaluated.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Status</th><th>Rule</th><th>Current</th><th>Required</th><th>Impact</th></tr></thead>
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
}

function navigate(page) {
  if (!["overview", "data-quality", "risk", "signals", "promotion", "settings"].includes(page)) return;
  state.page = page;
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
  state.dataQuality = null;
  state.risk = null;
  state.signals = null;
  state.promotion = null;
  state.settingsValidation = null;
  loadPage();
});

document.querySelector("#refresh-button").addEventListener("click", async () => {
  state.runs = [];
  await loadPage();
});

document.querySelector("#retry-button").addEventListener("click", loadPage);

loadPage();
