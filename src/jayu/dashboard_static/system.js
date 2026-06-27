// ─── System, Settings, API Monitoring, and Simulation Log Pages (07, 10, 14, 15번 메뉴) ───

// ─── 설정 검증 (07번 메뉴) ──────────────────────────────────────────

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
    
    ${renderFeatureInventorySection(state.featureInventory)}
    <section class="panel" style="margin-top: 1.5rem;" id="backup-restore-panel">
      ${renderBackupRestoreSection()}
    </section>
    
    <section class="panel" style="margin-top: 1.5rem;" id="experiments-panel">
      ${renderExperimentsSection()}
    </section>
    
    <section class="panel" style="margin-top: 1.5rem;" id="events-panel">
      ${renderEventsSection()}
    </section>
  `;

  setTimeout(() => {
    bindSettingsExtensionsActions();
  }, 100);
}

function renderFeatureInventorySection(data) {
  if (!data) {
    return `
      <section class="panel" style="margin-top:1.5rem;">
        <div class="panel-header"><div><h2>Feature Inventory</h2><p>기능 인벤토리를 불러오지 못했습니다.</p></div></div>
        ${renderSourceCaption("GET /api/v1/features")}
      </section>
    `;
  }
  const summary = data.summary || {};
  const statusCounts = data.status_counts || {};
  const features = (data.features || []).slice(0, 12);
  return `
    <section class="panel" style="margin-top:1.5rem;">
      <div class="panel-header">
        <div>
          <h2>Feature Inventory &amp; Status Matrix</h2>
          <p>Python 모듈, CLI 명령, Dashboard API, 화면 섹션을 자동 수집한 기능 관리 표입니다.</p>
        </div>
        <span class="status-label status-success">${summary.feature_count || 0} features</span>
      </div>
      <section class="metric-grid" style="margin-top:12px;">
        ${metricCard("Features", summary.feature_count || 0, "success", "src/jayu module inventory")}
        ${metricCard("CLI Commands", summary.cli_command_count || 0, summary.cli_command_count ? "success" : "warning", "Typer command decorators")}
        ${metricCard("Dashboard API", summary.dashboard_route_count || 0, summary.dashboard_route_count ? "success" : "warning", "dashboard.py /api/v1 routes")}
        ${metricCard("Tested", summary.tested_feature_count || 0, summary.tested_feature_count ? "success" : "warning", "tests/test_*.py related files")}
      </section>
      <div class="table-wrap" style="margin-top:12px;">
        <table>
          <thead><tr><th>Feature</th><th>Status</th><th>CLI</th><th>API</th><th>UI</th><th>Tests</th></tr></thead>
          <tbody>
            ${features.map((feature) => `
              <tr>
                <td><strong>${escapeHtml(feature.name || feature.feature_id)}</strong><br><span class="code">${escapeHtml(feature.module || "-")}</span></td>
                <td><span class="status-label status-${feature.status === "stable" ? "success" : feature.status === "deprecated" ? "failed" : "warning"}">${escapeHtml(feature.status || "-")}</span></td>
                <td>${(feature.cli_commands || []).length}</td>
                <td>${(feature.dashboard_routes || []).length}</td>
                <td>${(feature.dashboard_sections || []).length}</td>
                <td>${(feature.tests || []).length}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      <p class="metric-detail" style="margin:10px 0 0;color:var(--muted);font-size:11px;">
        stable ${statusCounts.stable || 0} · beta ${statusCounts.beta || 0} · experimental ${statusCounts.experimental || 0} · deprecated ${statusCounts.deprecated || 0}
      </p>
      ${renderSourceCaption("GET /api/v1/features · configs/feature_status.yaml · src/jayu")}
    </section>
  `;
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


// ─── API Monitoring (10번 메뉴) ───────────────────────────────────────────────

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
  const tossDrift = data.toss_api_drift || {};

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
      ${metricCard("Toss API Drift", tossDrift.status_label || "미확인", tossApiDriftTone(tossDrift.status), `${tossDrift.missing_count || 0} 누락 · ${tossDrift.extra_count || 0} 로컬 전용`, null, tossDrift.source || "state/toss_api_drift.json")}
    </section>
    ${renderTossApiDriftPanel(tossDrift)}
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

function tossApiDriftTone(status) {
  return {
    synchronized: "success",
    drifted: "warning",
    failed_to_fetch: "failed",
    not_checked: "not_evaluated",
    stale: "warning",
    unknown: "warning",
  }[status] || "not_evaluated";
}

function renderTossApiDriftPanel(drift) {
  const data = drift || {};
  const missing = data.missing_endpoints || [];
  const extra = data.extra_endpoints || [];
  const tone = tossApiDriftTone(data.status);
  const endpointRows = [
    ...missing.map((path) => ({ kind: "OpenAPI에만 있음", status: "warning", path })),
    ...extra.map((path) => ({ kind: "로컬에만 있음", status: "not_evaluated", path })),
  ];
  return `
    <section class="panel toss-drift-panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div>
          <h2>Toss OpenAPI Drift Check</h2>
          <p>토스증권 OpenAPI 최신 GET 스펙과 Jayu 로컬 읽기 전용 엔드포인트 카탈로그 차이를 확인합니다.</p>
          ${renderSourceCaption(data.source || "state/toss_api_drift.json · TOSS_GET_ENDPOINTS")}
        </div>
        ${statusBadge(tone, data.status_label || data.status || "미확인")}
      </div>
      <div class="toss-drift-summary status-${statusClass(tone)}">
        <div>
          <strong>${escapeHtml(data.summary || "Toss OpenAPI drift check 상태가 없습니다.")}</strong>
          <span>마지막 확인: ${escapeHtml(data.last_checked_at || "미기록")} · 경과 ${data.age_hours == null ? "미계산" : `${formatNumber(data.age_hours, 1)}시간`}</span>
          ${renderSourceCaption(data.source || "state/toss_api_drift.json")}
        </div>
        <div class="toss-drift-stats">
          <span><b>${formatNumber(data.local_endpoint_count || 0, 0)}</b>로컬 GET</span>
          <span><b>${formatNumber(data.missing_count || 0, 0)}</b>누락</span>
          <span><b>${formatNumber(data.extra_count || 0, 0)}</b>로컬 전용</span>
          <span><b>${data.fallback_snapshot_used ? "사용" : "미사용"}</b>snapshot</span>
        </div>
      </div>
      ${endpointRows.length ? `
        <div class="table-wrap"><table>
          <thead><tr><th>구분</th><th>상태</th><th>Endpoint</th></tr></thead>
          <tbody>${endpointRows.map((row) => `
            <tr>
              <td>${escapeHtml(row.kind)}</td>
              <td>${statusBadge(row.status)}</td>
              <td class="code">${escapeHtml(row.path)}</td>
            </tr>
          `).join("")}</tbody>
        </table></div>
      ` : `
        <div class="empty-state">
          <strong>엔드포인트 차이 없음</strong>
          <span>최근 drift check 기준으로 누락 또는 로컬 전용 GET 경로가 없습니다.</span>
          ${renderSourceCaption(data.source || "state/toss_api_drift.json")}
        </div>
      `}
      <div class="toss-drift-footer">
        <code>${escapeHtml(data.next_action || "uv run jayu toss endpoints --sync")}</code>
        <span>${data.snapshot_available ? "fallback snapshot 파일 있음" : "fallback snapshot 파일 없음"} · ${escapeHtml(data.snapshot_source || "state/toss_openapi_snapshot.json")}</span>
      </div>
      ${renderSourceCaption("Toss OpenAPI latest spec · state/toss_openapi_snapshot.json")}
    </section>
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
            <td class="ticker-cell">${renderTicker(d.ticker || d.symbol)}</td>
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


// ─── Simulation Log (14번 메뉴) ────────────────────────────────────────────────

let simulationLogTimer = null;

function highlightLog(text) {
  if (!text) return "";
  let escaped = escapeHtml(text);
  
  // 국면 하이라이팅
  escaped = escaped.replaceAll("BULL 국면", '<span style="color:#22c55e;font-weight:bold">BULL 국면</span>');
  escaped = escaped.replaceAll("BULL]", '<span style="color:#22c55e;font-weight:bold">BULL]</span>');
  escaped = escaped.replaceAll("BEAR 국면", '<span style="color:#ef4444;font-weight:bold">BEAR 국면</span>');
  escaped = escaped.replaceAll("BEAR]", '<span style="color:#ef4444;font-weight:bold">BEAR]</span>');
  escaped = escaped.replaceAll("SIDEWAYS 국면", '<span style="color:#f59e0b;font-weight:bold">SIDEWAYS 국면</span>');
  escaped = escaped.replaceAll("SIDEWAYS]", '<span style="color:#f59e0b;font-weight:bold">SIDEWAYS]</span>');
  
  // INFO, ERROR, WARNING 하이라이팅
  escaped = escaped.replaceAll("INFO", '<span style="color:#38bdf8;font-weight:bold">INFO</span>');
  escaped = escaped.replaceAll("ERROR", '<span style="color:#f43f5e;font-weight:bold">ERROR</span>');
  escaped = escaped.replaceAll("WARNING", '<span style="color:#fbbf24;font-weight:bold">WARNING</span>');
  
  // 종목 하이라이팅 [SOXL], [TQQQ] 등
  escaped = escaped.replace(/\[([A-Z]{3,5})\]/g, '<span style="color:#38bdf8;font-weight:bold">[$1]</span>');
  
  // 특수기호 하이라이팅 (🔬, 📉, 📈, └, → 등)
  escaped = escaped.replaceAll("🔬", '<span style="font-size:14px">🔬</span>');
  escaped = escaped.replaceAll("📉", '<span style="color:#ef4444">📉</span>');
  escaped = escaped.replaceAll("📈", '<span style="color:#22c55e">📈</span>');
  
  return escaped;
}

function parseSimulationLog(logs) {
  const result = {
    vix: null,
    indexes: [],
    tickers: {}
  };
  
  if (!logs) return result;
  
  const lines = logs.split("\n");
  let currentTicker = null;
  
  lines.forEach(line => {
    // 1. VIX 파싱
    if (line.includes("현재 VIX 지수:")) {
      const match = line.match(/현재 VIX 지수:\s*(\d+\.\d+)/);
      if (match) result.vix = parseFloat(match[1]);
    }
    
    // 2. 지수 모멘텀 수집 완료 파싱
    if (line.includes("지수") && line.includes("모멘텀 수집 완료")) {
      const match = line.match(/지수\s*([^\s]+)\s*모멘텀/);
      if (match) result.indexes.push(match[1]);
    }
    
    // 3. 종목 데이터 로드 중 파싱
    if (line.startsWith("[") && line.includes("] 데이터 로드 중...")) {
      const match = line.match(/^\[([A-Z0-9]+)\]/);
      if (match) {
        currentTicker = match[1];
        result.tickers[currentTicker] = {
          rows: null,
          warmup_rows: null,
          indicators: [],
          regimes: {}
        };
      }
    }
    
    // 4. 종목 행 및 지표 파싱
    if (currentTicker && result.tickers[currentTicker]) {
      const tickerInfo = result.tickers[currentTicker];
      if (line.includes("행 | 워밍업 제외")) {
        const match = line.match(/(\d+)행\s*\|\s*워밍업 제외\s*(\d+)행/);
        if (match) {
          tickerInfo.rows = parseInt(match[1], 10);
          tickerInfo.warmup_rows = parseInt(match[2], 10);
        }
        const indMatch = line.match(/지표:\s*(.+)$/);
        if (indMatch) {
          tickerInfo.indicators = indMatch[1].split("/").map(s => s.trim());
        }
      }
      
      // 5. 국면별 최적화 정보 파싱
      if (line.includes("국면] 최적화 진화...")) {
        const match = line.match(/\[(BULL|BEAR|SIDEWAYS) 국면\]/);
        if (match) {
          const regime = match[1];
          tickerInfo.regimes[regime] = {
            status: "running",
            trials: null,
            evals: null,
            change: null,
            sharpe: null,
            return: null
          };
        }
      }
      
      // 진행 상황 구체 데이터 파싱
      const activeRegimes = Object.keys(tickerInfo.regimes);
      if (activeRegimes.length > 0) {
        const lastRegime = activeRegimes[activeRegimes.length - 1];
        const rInfo = tickerInfo.regimes[lastRegime];
        
        if (line.includes("회 시뮬레이션") && line.includes("평가")) {
          const m = line.match(/(\d+)회 시뮬레이션.*평가\s*(\d+)회/);
          if (m) {
            rInfo.trials = parseInt(m[1], 10);
            rInfo.evals = parseInt(m[2], 10);
            if (line.includes("완료")) {
              rInfo.status = "completed";
            }
          }
        }
        
        if (line.includes("→") && line.includes(lastRegime)) {
          const changeType = line.includes("기존 유지") ? "keep" : "improved";
          const m = line.match(/Sharpe\s*(\d+\.\d+)\s*\|\s*수익\s*(\d+\.\d+)/);
          if (m) {
            rInfo.change = changeType;
            rInfo.sharpe = parseFloat(m[1]);
            rInfo.return = parseFloat(m[2]);
            rInfo.status = "completed";
          }
        }
      }
    }
  });
  
  return result;
}

function renderSimulationAnalysisReport(analysis) {
  let html = "";
  
  // 1. 시장 환경 분석 원인 설명 카드
  let vixNote = "VIX 수집 대기 중...";
  let vixColor = "#64748b";
  if (analysis.vix !== null) {
    if (analysis.vix <= 15) {
      vixNote = `현재 VIX가 ${analysis.vix.toFixed(2)}로 낮아 시장이 안정적입니다. 단타 진입에 우호적인 강한 추세장이 형성될 가능성이 높습니다.`;
      vixColor = "#22c55e";
    } else if (analysis.vix <= 22) {
      vixNote = `현재 VIX가 ${analysis.vix.toFixed(2)}로 보통 수준입니다. 국면별(BULL/BEAR) 독립 변동성을 반영하여 신중한 파라미터 튜닝이 요구됩니다.`;
      vixColor = "#f59e0b";
    } else {
      vixNote = `현재 VIX가 ${analysis.vix.toFixed(2)}로 높습니다! 시장 공포가 확산되어 유동성과 변동성이 급증했습니다. 조기종료 및 타이트한 손절가 파라미터 훈련이 필수적입니다.`;
      vixColor = "#ef4444";
    }
  }
  
  const momentumNotes = analysis.indexes.length > 0 
    ? `모멘텀 수집 완료 지수: <strong>${analysis.indexes.join(", ")}</strong><br>해당 벤치마크 지수의 이동평균(EMA20) 상하 밴드를 기준으로 강세/약세/횡보 레짐을 자동으로 판단하여 최적화를 수행합니다.`
    : "지수 모멘텀 수집 대기 중...";
    
  html += `
    <div class="sim-analysis-grid">
      <div class="sim-analysis-card" style="border-left: 4px solid ${vixColor}">
        <div class="sim-card-title">📉 시장 변동성(VIX) 진단</div>
        <p class="sim-card-desc">${vixNote}</p>
      </div>
      <div class="sim-analysis-card" style="border-left: 4px solid #3b82f6">
        <div class="sim-card-title">📈 시장 모멘텀 및 벤치마크</div>
        <p class="sim-card-desc">${momentumNotes}</p>
      </div>
    </div>
  `;
  
  // 2. 종목별 진화 최적화 분석 결과 카드
  const tickerNames = Object.keys(analysis.tickers);
  if (tickerNames.length === 0) {
    html += `
      <div class="sim-results-empty">
        <p>시뮬레이션 진화 분석 대기 중...</p>
        <small>프로세스가 실행되면서 수집된 결과가 이곳에 분석 보고서로 자동 정리됩니다.</small>
      </div>
    `;
  } else {
    html += `<div class="sim-ticker-analysis-container">`;
    tickerNames.forEach(tName => {
      const tInfo = analysis.tickers[tName];
      const indChips = (tInfo.indicators || []).map(ind => `<span class="sim-indicator-chip">${escapeHtml(ind)}</span>`).join("");
      
      let regimesHtml = "";
      const regimes = ["BULL", "BEAR", "SIDEWAYS"];
      regimes.forEach(reg => {
        const rData = tInfo.regimes[reg];
        let regColor = { BULL: "#22c55e", BEAR: "#ef4444", SIDEWAYS: "#f59e0b" }[reg];
        
        if (!rData) {
          regimesHtml += `
            <div class="sim-regime-row">
              <span class="sim-regime-label" style="color:#94a3b8">● ${reg} 국면</span>
              <span class="sim-regime-status" style="color:#94a3b8">대기 중</span>
            </div>
          `;
        } else {
          let statusLabel = "진행 중...";
          let statusStyle = "color: #3b82f6; font-weight: bold;";
          if (rData.status === "completed") {
            const chgLabel = rData.change === "keep" ? "기존 전략 유지" : "전략 업그레이드!";
            const chgStyle = rData.change === "keep" ? "color: #64748b" : "color: #22c55e; font-weight: bold;";
            statusLabel = `${chgLabel} (Sharpe: ${rData.sharpe?.toFixed(2) || "—"}, 수익: ${rData.return?.toFixed(1) || "—"}%)`;
            statusStyle = chgStyle;
          }
          regimesHtml += `
            <div class="sim-regime-row">
              <span class="sim-regime-label" style="color:${regColor}">● ${reg} 국면</span>
              <span class="sim-regime-status" style="${statusStyle}">${statusLabel}</span>
            </div>
          `;
        }
      });
      
      html += `
        <div class="sim-ticker-result-card">
          <div class="sim-ticker-result-header">
            <strong>${escapeHtml(tName)}</strong>
            <span class="sim-ticker-data-meta">${tInfo.rows ? `${tInfo.rows}행 로드` : "로딩 중..."}</span>
          </div>
          <div style="margin: 8px 0; display: flex; flex-wrap: wrap; gap: 4px;">
            ${indChips}
          </div>
          <div class="sim-regime-box">
            ${regimesHtml}
          </div>
        </div>
      `;
    });
    html += `</div>`;
  }
  
  return `
    <section class="panel" style="margin-bottom: 20px;">
      <div class="panel-header" style="padding-bottom: 8px; border-bottom: 1px solid #f1f5f9;">
        <div>
          <h2>🧠 실시간 시뮬레이션 환경 원인 & 분석 리포트</h2>
          <p>수집된 실시간 로그를 기반으로 시장 환경과 진화된 국면별 전략 성능을 분석한 요약 리포트입니다.</p>
        </div>
      </div>
      <div class="panel-body" style="padding-top: 12px;">
        ${html}
        
        <!-- 💡 자율 진화 엔진 가이드 섹션 -->
        <div class="sim-guide-panel" style="margin-top: 20px; padding-top: 16px; border-top: 1px dashed #cbd5e1;">
          <h3 style="font-size: 14px; color: #1e3a8a; margin: 0 0 12px 0; display: flex; align-items: center; gap: 6px;">
            <span>💡</span> 자율 진화 엔진 가이드 (지금 무엇을 하고 있나요?)
          </h3>
          <div class="sim-guide-grid">
            <div class="sim-guide-box">
              <strong>🔍 데이터 로드 출처 & 범위</strong>
              <p>주가 데이터는 <strong>Yahoo Finance API</strong>를 통해 실시간/역사적 일봉 데이터를 수집(로컬 캐시)하여 사용합니다. 현재 VIX 지수와 미국 지수(예: 반도체 지수인 <strong>^SOX</strong>)를 함께 분석하여 현 시장의 변동성 분위기와 트렌드 방향성을 진단합니다.</p>
            </div>
            
            <div class="sim-guide-box">
              <strong>🧬 유전자 풀 (Gene Pool) & 최적화 진화</strong>
              <p>유전 알고리즘(Genetic Algorithm)에 기반하여 최선의 성과를 낸 전략 파라미터 조합(진입선, 손절 폭 등)을 <strong>유전자 풀</strong>에 보관합니다. 세대를 거치며 성능이 우수한 부모 파라미터들을 결합(교배)하고 일부 무작위성(변이)을 주어 더 똑똑한 매매 규칙을 찾아냅니다.</p>
            </div>
            
            <div class="sim-guide-box">
              <strong>⚙️ 어떤 전략인가요? (Walk-Forward)</strong>
              <p>시장 국면(BULL 강세 / BEAR 약세 / SIDEWAYS 횡보)별로 각각 독립적인 파라미터를 사용하는 돌파/추세 추종 단타 전략입니다. 과거 특정 기간에만 딱 들어맞는 현상(과적합)을 방지하기 위해 학습 구간과 검증 구간을 쪼개어 테스트하는 <strong>전진 분석(Walk-Forward)</strong> 기법이 핵심입니다.</p>
            </div>
            
            <div class="sim-guide-box">
              <strong>🚀 이렇게 하면 무엇이 좋아지나요?</strong>
              <ul style="margin: 4px 0 0 14px; padding: 0; font-size: 11.5px; color: #475569; line-height: 1.45;">
                <li><strong>실전 강건성 (과적합 방지):</strong> 과거 우연히 잘 들어맞은 '가짜 전략'을 걸러내어 실전에서도 기댓값을 확보합니다.</li>
                <li><strong>시장 레짐 자동 대응:</strong> 폭락장에서는 보수적인 진입선과 좁은 손절을 적용하고, 불장에서는 적극적으로 기회를 포착해 자산을 지키며 복리 수익을 냅니다.</li>
                <li><strong>뇌동매매 방지:</strong> 인간의 감정(공포/탐욕)을 철저히 배제하고, 수십만 번의 시뮬레이션을 거친 통계적 기댓값에 따라 기계적으로 행동하게 됩니다.</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </section>
  `;
}

function renderSimulationLog() {
  const logs = state.simulationLog || "";
  const status = state.simulationStatus || "idle";
  
  let statusText = "대기 중";
  let statusColor = "#64748b";
  if (status === "running") {
    statusText = "⚡ 시뮬레이션 진화 중...";
    statusColor = "#3b82f6";
  } else if (status === "completed") {
    statusText = "✅ 완료";
    statusColor = "#10b981";
  } else if (status === "failed") {
    statusText = "❌ 실패";
    statusColor = "#ef4444";
  }
  
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>단타 시뮬레이션 로그</h1>
        <p>단타 시뮬레이션 v4 자율 진화 엔진의 최적화 유전 알고리즘 진행 상황을 실시간 모니터링합니다.</p>
      </div>
      <span class="status-label" style="background:${statusColor}22;color:${statusColor};border:1px solid ${statusColor}">${statusText}</span>
    </div>

    <div class="sim-layout-row">
      <div class="sim-layout-main">
        <div class="sim-controls-panel">
          <div class="sim-input-group">
            <label for="sim-tickers">대상 종목</label>
            <input id="sim-tickers" class="sim-input" type="text" placeholder="SOXL,TQQQ,TSLA (쉼표 구분)" value="${state.portfolioHubTickers || ''}">
          </div>
          <button id="btn-run-sim" class="button button-primary" ${status === "running" ? "disabled" : ""}>
            ${status === "running" ? "⏳ 진화 진행 중..." : "🔬 시뮬레이션 최적화 시작"}
          </button>
        </div>
        
        <div id="sim-report-area">
          ${renderSimulationAnalysisReport(parseSimulationLog(logs))}
        </div>
      </div>
      
      <div class="sim-layout-terminal">
        <div class="terminal-container">
          <div class="terminal-header">
            <div class="terminal-buttons">
              <span class="term-btn term-red"></span>
              <span class="term-btn term-yellow"></span>
              <span class="term-btn term-green"></span>
            </div>
            <span class="terminal-title">simulation_evolution.log</span>
          </div>
          <div class="terminal-body" id="simulation-terminal-body">
            <pre>${highlightLog(logs)}</pre>
          </div>
        </div>
      </div>
    </div>
  `;
}

function bindSimulationLogActions() {
  const btnRun = document.querySelector("#btn-run-sim");
  if (btnRun) {
    btnRun.addEventListener("click", async () => {
      const tickersVal = document.querySelector("#sim-tickers")?.value || "";
      const tickers = tickersVal.split(",").map(t => t.trim().toUpperCase()).filter(t => t);
      
      btnRun.disabled = true;
      btnRun.textContent = "⏳ 요청 중...";
      try {
        const res = await fetch("/api/v1/simulation/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tickers: tickers.length ? tickers : null })
        });
        const data = await res.json();
        
        state.simulationStatus = "running";
        state.simulationLog = "INFO 시뮬레이션 프로세스 가동 요청이 완료되었습니다...\n";
        renderSimulationLog();
        bindSimulationLogActions();
        
        // 실시간 폴링 시작
        startSimulationPolling();
      } catch (err) {
        alert("시뮬레이션 구동 실패: " + err.message);
        btnRun.disabled = false;
        btnRun.textContent = "🔬 시뮬레이션 최적화 시작";
      }
    });
  }

  if (state.simulationStatus === "running") {
    startSimulationPolling();
  } else {
    stopSimulationPolling();
  }
}

function startSimulationPolling() {
  if (simulationLogTimer) return;
  
  simulationLogTimer = setInterval(async () => {
    if (state.page !== "simulation-log") {
      stopSimulationPolling();
      return;
    }
    
    try {
      const res = await api("/api/v1/simulation/log");
      state.simulationLog = res.logs || "";
      state.simulationStatus = res.status || "idle";
      
      const term = document.querySelector("#simulation-terminal-body pre");
      if (term) {
        term.innerHTML = highlightLog(state.simulationLog);
        
        const body = document.querySelector("#simulation-terminal-body");
        if (body) {
          body.scrollTop = body.scrollHeight;
        }
      }
      
      const reportArea = document.querySelector("#sim-report-area");
      if (reportArea) {
        reportArea.innerHTML = renderSimulationAnalysisReport(parseSimulationLog(state.simulationLog));
      }
      
      if (state.simulationStatus !== "running") {
        stopSimulationPolling();
        renderSimulationLog();
        bindSimulationLogActions();
      }
    } catch (err) {
      console.warn("Polling simulation log failed", err);
    }
  }, 1000);
}

function stopSimulationPolling() {
  if (simulationLogTimer) {
    clearInterval(simulationLogTimer);
    simulationLogTimer = null;
  }
}


// ─── Run History (15번 메뉴) ───────────────────────────────────────────────────

let selectedRunHistoryId = null;
let selectedRunLogs = [];
let artifactSearchQuery = "";
let artifactSearchType = "";
let artifactSearchMode = "";
let artifactSearchResults = [];
let artifactHasSearched = false;

function renderRunHistory() {
  const runs = state.runs || [];
  
  const totalCount = runs.length;
  const successCount = runs.filter(r => String(r.status).toLowerCase() === "success").length;
  const failedCount = runs.filter(r => ["failed", "error"].includes(String(r.status).toLowerCase())).length;
  const runningCount = runs.filter(r => ["running", "pending"].includes(String(r.status).toLowerCase())).length;
  
  const summaryCardsHtml = `
    <div class="sim-analysis-grid" style="grid-template-columns: repeat(4, 1fr); margin-bottom: 20px;">
      <div class="sim-analysis-card" style="border-left: 4px solid #3b82f6;">
        <div class="sim-card-title" style="color:#3b82f6; font-size:12px;">총 실행 횟수</div>
        <div style="font-size: 22px; font-weight: 800; color: #1e293b; margin-top: 5px;">${totalCount} <span style="font-size:12px; font-weight:normal; color:#64748b;">회</span></div>
      </div>
      <div class="sim-analysis-card" style="border-left: 4px solid #10b981;">
        <div class="sim-card-title" style="color:#10b981; font-size:12px;">성공 완료</div>
        <div style="font-size: 22px; font-weight: 800; color: #1e293b; margin-top: 5px;">${successCount} <span style="font-size:12px; font-weight:normal; color:#64748b;">회</span></div>
      </div>
      <div class="sim-analysis-card" style="border-left: 4px solid #ef4444;">
        <div class="sim-card-title" style="color:#ef4444; font-size:12px;">실패 / 에러</div>
        <div style="font-size: 22px; font-weight: 800; color: #1e293b; margin-top: 5px;">${failedCount} <span style="font-size:12px; font-weight:normal; color:#64748b;">회</span></div>
      </div>
      <div class="sim-analysis-card" style="border-left: 4px solid #f59e0b;">
        <div class="sim-card-title" style="color:#f59e0b; font-size:12px;">진행 중</div>
        <div style="font-size: 22px; font-weight: 800; color: #1e293b; margin-top: 5px;">${runningCount} <span style="font-size:12px; font-weight:normal; color:#64748b;">회</span></div>
      </div>
    </div>
  `;

  let tableRows = "";
  if (runs.length) {
    tableRows = runs.map(run => {
      const isCurrent = run.run_id === state.runId;
      const status = String(run.status || "").toLowerCase();
      
      let statusBadge = "";
      if (status === "success") {
        statusBadge = `<span style="background:#d1fae5; color:#065f46; padding:3px 8px; border-radius:4px; font-size:10px; font-weight:600; display:inline-block;">SUCCESS</span>`;
      } else if (["failed", "error"].includes(status)) {
        statusBadge = `<span style="background:#fee2e2; color:#991b1b; padding:3px 8px; border-radius:4px; font-size:10px; font-weight:600; display:inline-block;">FAILED</span>`;
      } else {
        statusBadge = `<span style="background:#fef3c7; color:#92400e; padding:3px 8px; border-radius:4px; font-size:10px; font-weight:600; display:inline-block;">${status.toUpperCase()}</span>`;
      }
      
      const modeLabel = String(run.mode || "unknown").toUpperCase();
      const currentLabel = isCurrent 
        ? `<span style="background:#ecfdf5; color:#047857; border: 1px solid #a7f3d0; padding:1px 5px; border-radius:4px; font-size:10px; font-weight:bold; margin-left:6px; display:inline-block;">활성</span>` 
        : "";

      let durationStr = "-";
      if (run.started_at && run.finished_at) {
        const start = new Date(run.started_at);
        const end = new Date(run.finished_at);
        const diffMs = end - start;
        if (diffMs > 0) {
          const diffSec = Math.floor(diffMs / 1000);
          if (diffSec < 60) {
            durationStr = `${diffSec}초`;
          } else {
            const diffMin = Math.floor(diffSec / 60);
            durationStr = `${diffMin}분 ${diffSec % 60}초`;
          }
        }
      }

      const activeBg = isCurrent ? "background-color: #f0fdf4;" : "";

      return `
        <tr style="${activeBg}">
          <td style="text-align:center; padding: 12px 8px; vertical-align:middle;">
            <input type="checkbox" class="chk-compare-run" data-run-id="${escapeHtml(run.run_id)}" style="cursor:pointer; width:16px; height:16px;">
          </td>
          <td style="font-weight: 700; color: #1e293b; padding: 12px 8px; vertical-align:middle;">
            <div style="display:flex; align-items:center; flex-wrap:wrap; gap:4px;">
              <span>${escapeHtml(run.run_id)}</span>
              ${currentLabel}
            </div>
          </td>
          <td style="padding: 12px 8px; vertical-align:middle;"><span style="background:#f1f5f9; color:#475569; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:600;">${modeLabel}</span></td>
          <td style="padding: 12px 8px; vertical-align:middle;">${statusBadge}</td>
          <td style="font-size:11px; color:#64748b; padding: 12px 8px; vertical-align:middle;">${escapeHtml(formatDate(run.started_at) || "-")}</td>
          <td style="font-size:11px; color:#64748b; text-align:center; padding: 12px 8px; vertical-align:middle;">${durationStr}</td>
          <td style="padding: 12px 8px; vertical-align:middle;">
            <div style="max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-family:monospace; font-size:10px; color:#64748b;" title="${escapeHtml(run.command || '')}">
              ${escapeHtml(run.command || "-")}
            </div>
          </td>
          <td style="text-align:right; padding: 12px 8px; white-space:nowrap; vertical-align:middle;">
            <button class="button button-secondary btn-select-run" data-run-id="${escapeHtml(run.run_id)}" style="padding:4px 8px; font-size:11px; margin-right:4px;" ${isCurrent ? 'disabled' : ''}>
              ✅ 적용
            </button>
            <button class="button button-primary btn-view-run-log" data-run-id="${escapeHtml(run.run_id)}" style="padding:4px 8px; font-size:11px; background:${selectedRunHistoryId === run.run_id ? '#4f46e5':'#3b82f6'}; border-color:${selectedRunHistoryId === run.run_id ? '#4f46e5':'#3b82f6'}; color:white;">
              📄 로그
            </button>
          </td>
        </tr>
      `;
    }).join("");
  } else {
    tableRows = `
      <tr>
        <td colspan="8" style="text-align:center; padding: 40px; color:#64748b;">
          실행 이력이 존재하지 않습니다.
        </td>
      </tr>
    `;
  }

  let logViewerHtml = "";
  if (selectedRunHistoryId) {
    logViewerHtml = `
      <div class="terminal-container" style="height: 100%; min-height: 550px;">
        <div class="terminal-header" style="background:#1e1b4b; border-bottom: 1px solid #312e81;">
          <div class="terminal-buttons">
            <span class="term-btn term-red"></span>
            <span class="term-btn term-yellow"></span>
            <span class="term-btn term-green"></span>
          </div>
          <span class="terminal-title" style="color: #c7d2fe;">Run Events: ${escapeHtml(selectedRunHistoryId)}</span>
        </div>
        <div class="terminal-body" style="background:#090514; overflow-y:auto; padding: 20px; height: calc(100% - 40px);">
          ${renderRunEventsTimeline(selectedRunLogs)}
        </div>
      </div>
    `;
  } else {
    logViewerHtml = `
      <div style="height:100%; min-height:550px; display:flex; flex-direction:column; justify-content:center; align-items:center; background:#f8fafc; border: 1px dashed #cbd5e1; border-radius:8px; color:#64748b; padding:20px; text-align:center;">
        <span style="font-size:40px; margin-bottom:15px;">📄</span>
        <strong>실행 세부 로그 미선택</strong>
        <p style="font-size:12px; margin-top:5px; max-width:240px; line-height:1.5; color:#94a3b8;">왼쪽 목록의 [📄 로그] 버튼을 누르면 해당 실행 과정의 세부 이벤트 타임라인 및 파라미터가 여기에 로드됩니다.</p>
      </div>
    `;
  }

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>실행 이력 & 로그</h1>
        <p>백엔드 엔진의 역대 실행(Runs) 목록을 관리하고, 상세 이벤트 로그 조회 및 대시보드 전역 필터 적용이 가능합니다.</p>
      </div>
    </div>
    ${renderDataSourceNote("run-history")}

    ${summaryCardsHtml}
    ${renderRunEvidenceOverview(state.overview?.run_evidence)}
    ${renderFailurePatternOverview(state.failurePatterns)}
    
    ${renderArtifactSearchCenter()}

    <div class="sim-layout-row">
      <div class="sim-layout-main" style="flex: 1.6;">
        <div class="sim-analysis-card" style="padding:0; overflow:hidden; background:white; border: 1px solid #e2e8f0; border-radius:8px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
          <div style="padding: 16px; border-bottom: 1px solid #e2e8f0; background:#f8fafc; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div style="display:flex; align-items:center;">
              <strong style="color:#1e293b; font-size:14px;">실행 이력 리스트 (최근 100개)</strong>
              <button class="button btn-compare-runs" type="button" style="padding:4px 10px; font-size:11px; background:#7c3aed; border-color:#7c3aed; color:white; margin-left:15px; font-weight:bold;">
                ⚖️ 선택 실행 비교 (Compare)
              </button>
            </div>
            <span style="font-size:11px; color:#64748b;">체크박스 2개를 선택해 실행을 교차 비교해보세요.</span>
          </div>
          <div style="overflow-x:auto;">
            <table class="table" style="margin:0; width:100%; border-collapse: collapse;">
              <thead>
                <tr style="background:#f8fafc; border-bottom: 1px solid #e2e8f0; text-align:left;">
                  <th style="padding: 10px 8px; font-size:12px; color:#475569; width:40px; text-align:center;">비교</th>
                  <th style="padding: 10px 8px; font-size:12px; color:#475569;">실행 ID</th>
                  <th style="padding: 10px 8px; font-size:12px; color:#475569;">모드</th>
                  <th style="padding: 10px 8px; font-size:12px; color:#475569;">상태</th>
                  <th style="padding: 10px 8px; font-size:12px; color:#475569;">시작 일시</th>
                  <th style="padding: 10px 8px; font-size:12px; color:#475569; text-align:center;">소요시간</th>
                  <th style="padding: 10px 8px; font-size:12px; color:#475569;">명령어</th>
                  <th style="padding: 10px 8px; font-size:12px; color:#475569; text-align:right;">액션</th>
                </tr>
              </thead>
              <tbody style="font-size:13px; color:#334155;">
                ${tableRows}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      
      <div class="sim-layout-terminal" style="flex: 1.1;">
        ${logViewerHtml}
      </div>
    </div>
  `;

  bindRunHistoryActions();
}

function renderArtifactSearchCenter() {
  let resultsHtml = "";
  if (!artifactHasSearched) {
    resultsHtml = `
      <tr>
        <td colspan="6" style="text-align:center; padding:30px; color:#94a3b8; font-size:13px;">
          검색 조건을 입력한 후 [🔍 검색] 버튼을 클릭해 주세요.
        </td>
      </tr>
    `;
  } else if (!artifactSearchResults.length) {
    resultsHtml = `
      <tr>
        <td colspan="6" style="text-align:center; padding:30px; color:#f43f5e; font-weight:600; font-size:13px;">
          일치하는 산출물(Artifact)을 찾을 수 없습니다.
        </td>
      </tr>
    `;
  } else {
    resultsHtml = artifactSearchResults.map(art => {
      const sizeKb = (art.size_bytes / 1024).toFixed(1);
      const tickers = (art.tickers || []).join(", ") || "-";
      const failureCode = art.failure_code 
        ? `<span style="background:#fee2e2; color:#991b1b; padding:1px 4px; border-radius:3px; font-size:10px; font-family:monospace;">${escapeHtml(art.failure_code)}</span>` 
        : "-";
        
      let typeBadge = "";
      if (art.type === "run") typeBadge = `<span style="background:#e0f2fe; color:#0369a1; padding:2px 5px; border-radius:3px; font-size:10px; font-weight:bold;">RUN</span>`;
      else if (art.type === "signal") typeBadge = `<span style="background:#fef3c7; color:#d97706; padding:2px 5px; border-radius:3px; font-size:10px; font-weight:bold;">SIGNAL</span>`;
      else if (art.type === "report") typeBadge = `<span style="background:#d1fae5; color:#059669; padding:2px 5px; border-radius:3px; font-size:10px; font-weight:bold;">REPORT</span>`;
      else typeBadge = `<span style="background:#f3e8ff; color:#7e22ce; padding:2px 5px; border-radius:3px; font-size:10px; font-weight:bold;">STATE</span>`;

      return `
        <tr>
          <td style="font-weight:700; color:#1e293b; padding:10px 8px;">
            <code style="font-size:11px;">${escapeHtml(art.name)}</code>
          </td>
          <td style="padding:10px 8px;">${typeBadge}</td>
          <td style="padding:10px 8px; font-size:11px; font-family:monospace; color:#475569;">${escapeHtml(art.run_id || "-")}</td>
          <td style="padding:10px 8px; font-size:11px; color:#64748b;" title="${tickers}">${escapeHtml(tickers.length > 20 ? tickers.slice(0,20)+'...' : tickers)}</td>
          <td style="padding:10px 8px; font-size:11px; color:#64748b;">${failureCode}</td>
          <td style="padding:10px 8px; font-size:11px; color:#64748b; text-align:right;">${sizeKb} KB</td>
          <td style="padding:10px 8px; font-size:11px; color:#64748b;">${formatDate(art.modified_at)}</td>
          <td style="text-align:right; padding:10px 8px; white-space:nowrap;">
            <button class="button button-secondary btn-copy-artifact-path" data-path="${escapeHtml(art.path)}" style="padding:2px 6px; font-size:10px; margin-right:4px;">
              📁 경로복사
            </button>
            <button class="button button-primary btn-view-artifact-content" data-path="${escapeHtml(art.path)}" style="padding:2px 6px; font-size:10px; background:#0284c7; border-color:#0284c7; color:white;">
              👁️ 내용보기
            </button>
          </td>
        </tr>
      `;
    }).join("");
  }

  return `
    <section class="panel" style="margin-bottom: 20px;">
      <div class="panel-header" style="background:#f8fafc; border-bottom:1px solid #e2e8f0;">
        <div>
          <h2 style="font-size:14px; margin:0;">증거 산출물 검색 센터 (Artifact Search Center)</h2>
          <p style="margin:2px 0 0 0; font-size:11px; color:#64748b;"> runs, signals, reports, state 디렉토리 내의 원천 데이터와 증거 파일들을 정밀 색인하여 다차원으로 조건 검색합니다.</p>
        </div>
      </div>
      <div class="panel-body" style="padding:15px;">
        <!-- 검색 조건 그리드 -->
        <div style="display:grid; grid-template-columns: 2fr 1fr 1fr 80px; gap:10px; margin-bottom:15px; align-items:end;">
          <div>
            <label style="display:block; font-size:11px; font-weight:bold; color:#475569; margin-bottom:4px;">통합 검색어 (파일명, Ticker, 사유, 런ID)</label>
            <input type="text" id="search-artifact-query" value="${escapeHtml(artifactSearchQuery)}" placeholder="예: SOXL, DATA_DISAGREEMENT, run-..." style="width:100%; font-size:12px; padding:6px 10px; border-radius:6px; border:1px solid #cbd5e1; box-sizing:border-box;">
          </div>
          <div>
            <label style="display:block; font-size:11px; font-weight:bold; color:#475569; margin-bottom:4px;">산출물 구분 (Type)</label>
            <select id="search-artifact-type" style="width:100%; font-size:12px; padding:6px; border-radius:6px; border:1px solid #cbd5e1; background:white; box-sizing:border-box;">
              <option value="" ${artifactSearchType === "" ? "selected" : ""}>[전체 구분]</option>
              <option value="run" ${artifactSearchType === "run" ? "selected" : ""}>RUN (실행 증거)</option>
              <option value="signal" ${artifactSearchType === "signal" ? "selected" : ""}>SIGNAL (매매 신호)</option>
              <option value="report" ${artifactSearchType === "report" ? "selected" : ""}>REPORT (리포트)</option>
              <option value="state" ${artifactSearchType === "state" ? "selected" : ""}>STATE (전역 상태)</option>
            </select>
          </div>
          <div>
            <label style="display:block; font-size:11px; font-weight:bold; color:#475569; margin-bottom:4px;">실행 모드 (Mode)</label>
            <select id="search-artifact-mode" style="width:100%; font-size:12px; padding:6px; border-radius:6px; border:1px solid #cbd5e1; background:white; box-sizing:border-box;">
              <option value="" ${artifactSearchMode === "" ? "selected" : ""}>[전체 모드]</option>
              <option value="shadow" ${artifactSearchMode === "shadow" ? "selected" : ""}>SHADOW (쉐도우)</option>
              <option value="paper" ${artifactSearchMode === "paper" ? "selected" : ""}>PAPER (모의)</option>
              <option value="live" ${artifactSearchMode === "live" ? "selected" : ""}>LIVE (실전)</option>
              <option value="research" ${artifactSearchMode === "research" ? "selected" : ""}>RESEARCH (연구)</option>
              <option value="backtest" ${artifactSearchMode === "backtest" ? "selected" : ""}>BACKTEST (백테스트)</option>
            </select>
          </div>
          <div>
            <button class="button button-primary" id="btn-search-artifacts" type="button" style="width:100%; padding:7px; font-size:12px; font-weight:bold; background:#0284c7; border-color:#0284c7; color:white; border-radius:6px;">
              🔍 검색
            </button>
          </div>
        </div>

        <!-- 검색 결과 테이블 -->
        <div class="table-wrap" style="max-height: 280px; overflow-y:auto; border: 1px solid #e2e8f0; border-radius:6px;">
          <table class="table" style="margin:0; width:100%; border-collapse: collapse;">
            <thead>
              <tr style="background:#f8fafc; border-bottom: 1px solid #e2e8f0; text-align:left; position:sticky; top:0; z-index:10;">
                <th style="padding: 8px; font-size:11px; color:#475569;">파일명</th>
                <th style="padding: 8px; font-size:11px; color:#475569; width:70px;">구분</th>
                <th style="padding: 8px; font-size:11px; color:#475569; width:100px;">실행 ID</th>
                <th style="padding: 8px; font-size:11px; color:#475569;">관련 종목</th>
                <th style="padding: 8px; font-size:11px; color:#475569; width:100px;">차단 코드</th>
                <th style="padding: 8px; font-size:11px; color:#475569; width:70px; text-align:right;">크기</th>
                <th style="padding: 8px; font-size:11px; color:#475569; width:110px;">수정 일시</th>
                <th style="padding: 8px; font-size:11px; color:#475569; text-align:right; width:140px;">액션</th>
              </tr>
            </thead>
            <tbody style="font-size:12px; color:#334155;">
              ${resultsHtml}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  `;
}

function bindRunHistoryActions() {
  // 1. 실행 전역 적용
  document.querySelectorAll(".btn-select-run").forEach(btn => {
    btn.addEventListener("click", async () => {
      const runId = btn.dataset.runId;
      if (!runId) return;
      
      btn.disabled = true;
      btn.textContent = "⏳ 적용 중..";
      
      state.runId = runId;
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
      
      await loadRuns();
      await loadPage();
      
      renderRunHistory();
    });
  });

  // 2. 실행 로그 조회
  document.querySelectorAll(".btn-view-run-log").forEach(btn => {
    btn.addEventListener("click", async () => {
      const runId = btn.dataset.runId;
      if (!runId) return;
      
      if (selectedRunHistoryId === runId) {
        selectedRunHistoryId = null;
        selectedRunLogs = [];
        renderRunHistory();
        return;
      }
      
      selectedRunHistoryId = runId;
      btn.innerHTML = "⏳ 로딩..";
      
      try {
        const payload = await api(`/api/v1/runs/${encodeURIComponent(runId)}/log`);
        selectedRunLogs = payload.logs || [];
      } catch (err) {
        selectedRunLogs = [{"timestamp": "", "level": "ERROR", "message": `로그 로드 실패: ${err.message}`}];
      }
      
      renderRunHistory();
    });
  });

  // 3. 실행 비교 (Run Compare) 액션
  const compareBtn = document.querySelector(".btn-compare-runs");
  if (compareBtn) {
    compareBtn.addEventListener("click", async () => {
      const checkedBoxes = Array.from(document.querySelectorAll(".chk-compare-run:checked"));
      const selectedIds = checkedBoxes.map(cb => cb.dataset.runId);
      
      if (selectedIds.length !== 2) {
        alert("교차 비교를 위해 실행(Run) 항목을 목록에서 정확히 2개 선택(체크)해 주세요.");
        return;
      }
      
      compareBtn.disabled = true;
      compareBtn.textContent = "⏳ 교차 비교 중...";
      
      try {
        const left = selectedIds[1];  // 시간 상 더 이전 런이 왼쪽
        const right = selectedIds[0]; // 더 최신 런이 오른쪽
        const data = await api(`/api/v1/runs/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`);
        showRunCompareModal(left, right, data);
      } catch (err) {
        alert("비교 수행 중 오류 발생: " + err.message);
      } finally {
        compareBtn.disabled = false;
        compareBtn.innerHTML = "⚖️ 선택 실행 비교 (Compare)";
      }
    });
  }

  // 4. 산출물 검색 (Artifact Search) 액션
  const searchBtn = document.querySelector("#btn-search-artifacts");
  if (searchBtn) {
    searchBtn.addEventListener("click", async () => {
      const queryVal = document.querySelector("#search-artifact-query").value;
      const typeVal = document.querySelector("#search-artifact-type").value;
      const modeVal = document.querySelector("#search-artifact-mode").value;
      
      artifactSearchQuery = queryVal;
      artifactSearchType = typeVal;
      artifactSearchMode = modeVal;
      
      searchBtn.disabled = true;
      searchBtn.textContent = "⏳ 검색 중..";
      
      try {
        let url = "/api/v1/artifacts/search?";
        const params = [];
        if (queryVal) params.push(`query=${encodeURIComponent(queryVal)}`);
        if (typeVal) params.push(`artifact_type=${encodeURIComponent(typeVal)}`);
        if (modeVal) params.push(`mode=${encodeURIComponent(modeVal)}`);
        url += params.join("&");
        
        const payload = await api(url);
        artifactSearchResults = payload.artifacts || [];
        artifactHasSearched = true;
      } catch (err) {
        alert("검색 실패: " + err.message);
      } finally {
        searchBtn.disabled = false;
        searchBtn.textContent = "🔍 검색";
        renderRunHistory();
      }
    });
  }

  // 5. 산출물 절대경로 복사
  document.querySelectorAll(".btn-copy-artifact-path").forEach(btn => {
    btn.addEventListener("click", async () => {
      const path = btn.dataset.path;
      if (!path) return;
      try {
        await navigator.clipboard.writeText(path);
        btn.textContent = "📋 복사 완료";
        btn.style.background = "#059669";
        btn.style.color = "white";
        setTimeout(() => {
          btn.textContent = "📁 경로복사";
          btn.style.background = "";
          btn.style.color = "";
        }, 1500);
      } catch (err) {
        alert("경로 복사 실패: " + err.message);
      }
    });
  });

  // 6. 산출물 본문 모달 뷰어
  document.querySelectorAll(".btn-view-artifact-content").forEach(btn => {
    btn.addEventListener("click", async () => {
      const path = btn.dataset.path;
      if (!path) return;
      
      btn.disabled = true;
      const originalText = btn.textContent;
      btn.textContent = "⏳ 로딩..";
      
      try {
        const payload = await api(`/api/v1/artifacts/view?path=${encodeURIComponent(path)}`);
        showArtifactContentModal(payload.name, payload.path, payload.content);
      } catch (err) {
        alert("본문 로드 실패 (바이너리 파일은 조회가 불가합니다): " + err.message);
      } finally {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    });
  });

  // 타임라인 상세보기 토글
  document.querySelectorAll(".timeline-details-toggle").forEach(toggle => {
    toggle.addEventListener("click", () => {
      const idx = toggle.dataset.index;
      const detailsBox = document.querySelector(`#details-box-${idx}`);
      if (detailsBox) {
        const isHidden = detailsBox.style.display === "none";
        detailsBox.style.display = isHidden ? "block" : "none";
        toggle.innerHTML = isHidden ? "▲ 접기" : "▼ 상세보기";
      }
    });
  });

  // JSON 복사
  document.querySelectorAll(".btn-copy-raw-json").forEach(btn => {
    btn.addEventListener("click", async () => {
      const rawJson = btn.dataset.json;
      if (!rawJson) return;
      try {
        await navigator.clipboard.writeText(rawJson);
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = "Copy JSON"; }, 1500);
      } catch (err) {
        alert("복사 실패: " + err.message);
      }
    });
  });
}

/* ─── 모달 뷰어 구현 ─── */

function showRunCompareModal(left, right, data) {
  // 기존 모달이 있으면 제거
  const exist = document.querySelector("#run-compare-modal-root");
  if (exist) exist.remove();
  
  const modal = document.createElement("div");
  modal.id = "run-compare-modal-root";
  modal.style = `
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(15, 23, 42, 0.75); backdrop-filter: blur(4px);
    display: flex; justify-content: center; align-items: center;
    z-index: 9999; font-family: sans-serif;
  `;
  
  const configChanged = data.config.changed;
  const dataChanged = data.data_quality.changed;
  const decisionChanged = data.decision.left_status !== data.decision.right_status || data.risk.left_status !== data.risk.right_status;
  
  modal.innerHTML = `
    <div style="background: white; width: 900px; max-width: 95%; max-height: 85%; border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2), 0 10px 10px -5px rgba(0, 0, 0, 0.04);">
      <!-- 모달 헤더 -->
      <div style="background: #1e1b4b; color: white; padding: 18px 24px; display: flex; justify-content: space-between; align-items: center;">
        <div>
          <h3 style="margin: 0; font-size: 1.25rem;">⚖️ Jayu 실행 교차 비교 보고서</h3>
          <p style="margin: 4px 0 0 0; font-size: 0.85rem; color: #a5b4fc;">이전 실행과 현재 실행의 메타데이터, 데이터 제공자 상태, 진입 신호, 리스크 판결 차이를 요약합니다.</p>
        </div>
        <button id="btn-close-compare-modal" style="background: transparent; border: none; color: #cbd5e1; font-size: 24px; cursor: pointer; line-height: 1;">&times;</button>
      </div>
      
      <!-- 탭 네비게이션 -->
      <div style="background: #f1f5f9; padding: 0 24px; border-bottom: 1px solid #e2e8f0; display: flex; gap: 20px;">
        <button id="tab-compare-summary" class="modal-tab-btn active" style="padding: 12px 6px; border: none; background: transparent; font-weight: bold; border-bottom: 3px solid #4f46e5; color: #4f46e5; cursor: pointer;">종합 비교 표</button>
        <button id="tab-compare-markdown" class="modal-tab-btn" style="padding: 12px 6px; border: none; background: transparent; font-weight: bold; border-bottom: 3px solid transparent; color: #64748b; cursor: pointer;">마크다운 보고서</button>
      </div>
      
      <!-- 모달 바디 -->
      <div id="modal-compare-body" style="padding: 24px; overflow-y: auto; flex: 1; min-height: 350px;">
        <!-- 1번 탭: 종합 비교 표 -->
        <div id="panel-compare-summary">
          <!-- 종합 요약 말풍선 -->
          <div style="background: #f8fafc; border-left: 4px solid #7c3aed; padding: 14px; border-radius: 4px; margin-bottom: 20px;">
            <strong style="display:block; color:#1e1b4b; margin-bottom:4px; font-size:0.95rem;">💡 교차 변동 요약 분석 (한국어)</strong>
            <p style="margin:0; font-size:0.9rem; line-height:1.5; color:#334155;">${escapeHtml(data.decision.explanation)}</p>
          </div>
          
          <table class="table" style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
              <tr style="background: #f8fafc; border-bottom: 2px solid #cbd5e1;">
                <th style="padding: 8px; text-align: left; color: #475569;">비교 지표</th>
                <th style="padding: 8px; text-align: center; color: #475569; width: 35%;">이전 실행 (${left.slice(0, 15)}...)</th>
                <th style="padding: 8px; text-align: center; color: #475569; width: 35%;">현재 실행 (${right.slice(0, 15)}...)</th>
                <th style="padding: 8px; text-align: center; color: #475569; width: 12%;">변경</th>
              </tr>
            </thead>
            <tbody>
              <tr style="border-bottom: 1px solid #e2e8f0; ${decisionChanged ? 'background: #fffbeb;' : ''}">
                <td style="padding: 10px 8px; font-weight: bold;">의사결정 및 판정</td>
                <td style="padding: 10px 8px; text-align: center;"><code style="font-size:12px; background:#f1f5f9; padding:2px 6px; border-radius:3px;">${data.decision.left_status}/${data.risk.left_status}</code></td>
                <td style="padding: 10px 8px; text-align: center;"><code style="font-size:12px; background:#fee2e2; color:#991b1b; padding:2px 6px; border-radius:3px; font-weight:bold;">${data.decision.right_status}/${data.risk.right_status}</code></td>
                <td style="padding: 10px 8px; text-align: center;">${decisionChanged ? '⚠️ 변경됨' : '동일'}</td>
              </tr>
              <tr style="border-bottom: 1px solid #e2e8f0; ${configChanged ? 'background: #fffbeb;' : ''}">
                <td style="padding: 10px 8px; font-weight: bold;">설정 파일 해시 (Config)</td>
                <td style="padding: 10px 8px; text-align: center; font-family: monospace;">${data.config.left_hash.slice(0, 8)}</td>
                <td style="padding: 10px 8px; text-align: center; font-family: monospace; ${configChanged ? 'color:#d97706; font-weight:bold;' : ''}">${data.config.right_hash.slice(0, 8)}</td>
                <td style="padding: 10px 8px; text-align: center;">${configChanged ? '⚠️ 변경됨' : '동일'}</td>
              </tr>
              <tr style="border-bottom: 1px solid #e2e8f0; ${dataChanged ? 'background: #fffbeb;' : ''}">
                <td style="padding: 10px 8px; font-weight: bold;">수집 데이터 해시 (Data)</td>
                <td style="padding: 10px 8px; text-align: center; font-family: monospace;">${data.data_quality.left_hash.slice(0, 8)}</td>
                <td style="padding: 10px 8px; text-align: center; font-family: monospace; ${dataChanged ? 'color:#d97706; font-weight:bold;' : ''}">${data.data_quality.right_hash.slice(0, 8)}</td>
                <td style="padding: 10px 8px; text-align: center;">${dataChanged ? '⚠️ 변경됨' : '동일'}</td>
              </tr>
              <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 10px 8px; font-weight: bold;">제공처 간 불일치 종목 수</td>
                <td style="padding: 10px 8px; text-align: center;">${data.data_quality.left_disagreements} 개</td>
                <td style="padding: 10px 8px; text-align: center; ${data.data_quality.left_disagreements !== data.data_quality.right_disagreements ? 'color:#ef4444; font-weight:bold;' : ''}">${data.data_quality.right_disagreements} 개</td>
                <td style="padding: 10px 8px; text-align: center;">${data.data_quality.left_disagreements !== data.data_quality.right_disagreements ? '⚠️ 변동' : '동일'}</td>
              </tr>
              <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 10px 8px; font-weight: bold;">총 생성 신호(Signals) 수</td>
                <td style="padding: 10px 8px; text-align: center;">${data.signals.left_total} 개</td>
                <td style="padding: 10px 8px; text-align: center;">${data.signals.right_total} 개</td>
                <td style="padding: 10px 8px; text-align: center;">${data.signals.right_total - data.signals.left_total >= 0 ? '+' : ''}${data.signals.right_total - data.signals.left_total}</td>
              </tr>
              <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 10px 8px; font-weight: bold;">최종 진입 승인(Eligible) 수</td>
                <td style="padding: 10px 8px; text-align: center; color:#059669; font-weight:bold;">${data.signals.left_eligible} 개</td>
                <td style="padding: 10px 8px; text-align: center; color:#059669; font-weight:bold;">${data.signals.right_eligible} 개</td>
                <td style="padding: 10px 8px; text-align: center;">${data.signals.right_eligible - data.signals.left_eligible >= 0 ? '+' : ''}${data.signals.right_eligible - data.signals.left_eligible}</td>
              </tr>
              <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 10px 8px; font-weight: bold;">리스크 게이트 차단(Blocked) 수</td>
                <td style="padding: 10px 8px; text-align: center; color:#dc2626;">${data.signals.left_blocked} 개</td>
                <td style="padding: 10px 8px; text-align: center; color:#dc2626; font-weight:bold;">${data.signals.right_blocked} 개</td>
                <td style="padding: 10px 8px; text-align: center;">${data.signals.right_blocked - data.signals.left_blocked >= 0 ? '+' : ''}${data.signals.right_blocked - data.signals.left_blocked}</td>
              </tr>
              <tr style="border-bottom: 1px solid #cbd5e1;">
                <td style="padding: 10px 8px; font-weight: bold;">증거 완성도 점수 (Evidence)</td>
                <td style="padding: 10px 8px; text-align: center;">${data.artifacts.left_completeness}%</td>
                <td style="padding: 10px 8px; text-align: center; font-weight:bold;">${data.artifacts.right_completeness}%</td>
                <td style="padding: 10px 8px; text-align: center;">${data.artifacts.left_completeness !== data.artifacts.right_completeness ? '⚠️ 변동' : '동일'}</td>
              </tr>
            </tbody>
          </table>
          
          <div style="margin-top: 15px; font-size:12px;">
            <p style="margin: 0 0 5px 0;"><strong>이전 차단 사유:</strong> <code style="color:#ef4444; font-family:monospace;">${data.risk.left_blockers.join(", ") || "없음"}</code></p>
            <p style="margin: 0;"><strong>현재 차단 사유:</strong> <code style="color:#ef4444; font-family:monospace;">${data.risk.right_blockers.join(", ") || "없음"}</code></p>
          </div>
        </div>
        
        <!-- 2번 탭: 마크다운 보고서 -->
        <div id="panel-compare-markdown" style="display: none;">
          <pre style="background: #0f172a; color: #e2e8f0; padding: 20px; border-radius: 8px; font-family: monospace; font-size: 12px; overflow-x: auto; white-space: pre-wrap; margin: 0; line-height: 1.5; text-align:left;">${escapeHtml(data.markdown)}</pre>
        </div>
      </div>
      
      <!-- 모달 푸터 -->
      <div style="background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 14px 24px; text-align: right;">
        <button id="btn-close-compare-modal-footer" class="button button-secondary" style="padding: 6px 16px;">닫기</button>
      </div>
    </div>
  `;
  
  document.body.appendChild(modal);
  
  // 모달 제어 이벤트
  const closeModal = () => { modal.remove(); };
  document.querySelector("#btn-close-compare-modal").addEventListener("click", closeModal);
  document.querySelector("#btn-close-compare-modal-footer").addEventListener("click", closeModal);
  
  // 탭 제어
  const summaryBtn = document.querySelector("#tab-compare-summary");
  const markdownBtn = document.querySelector("#tab-compare-markdown");
  const summaryPanel = document.querySelector("#panel-compare-summary");
  const markdownPanel = document.querySelector("#panel-compare-markdown");
  
  summaryBtn.addEventListener("click", () => {
    summaryBtn.style.borderBottom = "3px solid #4f46e5";
    summaryBtn.style.color = "#4f46e5";
    markdownBtn.style.borderBottom = "3px solid transparent";
    markdownBtn.style.color = "#64748b";
    summaryPanel.style.display = "block";
    markdownPanel.style.display = "none";
  });
  
  markdownBtn.addEventListener("click", () => {
    markdownBtn.style.borderBottom = "3px solid #4f46e5";
    markdownBtn.style.color = "#4f46e5";
    summaryBtn.style.borderBottom = "3px solid transparent";
    summaryBtn.style.color = "#64748b";
    summaryPanel.style.display = "none";
    markdownPanel.style.display = "block";
  });
}

function showArtifactContentModal(name, path, content) {
  const exist = document.querySelector("#artifact-view-modal-root");
  if (exist) exist.remove();
  
  const modal = document.createElement("div");
  modal.id = "artifact-view-modal-root";
  modal.style = `
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(15, 23, 42, 0.75); backdrop-filter: blur(4px);
    display: flex; justify-content: center; align-items: center;
    z-index: 9999; font-family: sans-serif;
  `;
  
  modal.innerHTML = `
    <div style="background: white; width: 850px; max-width: 95%; max-height: 80%; border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2);">
      <!-- 헤더 -->
      <div style="background: #0284c7; color: white; padding: 15px 20px; display: flex; justify-content: space-between; align-items: center;">
        <div>
          <h3 style="margin: 0; font-size: 1.1rem;">👁️ 산출물 내용 뷰어: ${escapeHtml(name)}</h3>
          <p style="margin: 4px 0 0 0; font-size: 0.75rem; color: #e0f2fe; font-family:monospace; word-break:break-all;">${escapeHtml(path)}</p>
        </div>
        <button id="btn-close-view-modal" style="background: transparent; border: none; color: white; font-size: 24px; cursor: pointer; line-height: 1;">&times;</button>
      </div>
      
      <!-- 본문 -->
      <div style="padding: 20px; overflow-y: auto; flex: 1; background: #0f172a; display:flex; flex-direction:column;">
        <pre id="pre-artifact-content" style="color: #cbd5e1; font-family: monospace; font-size: 12px; overflow-x: auto; white-space: pre-wrap; margin: 0; line-height: 1.5; text-align:left; flex:1;">${escapeHtml(content)}</pre>
      </div>
      
      <!-- 푸터 -->
      <div style="background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 10px 20px; display:flex; justify-content:space-between; align-items:center;">
        <button id="btn-copy-artifact-content" class="button button-secondary" style="padding: 5px 12px; font-size:12px;">📋 전체내용 복사</button>
        <button id="btn-close-view-modal-footer" class="button button-secondary" style="padding: 5px 12px; font-size:12px;">닫기</button>
      </div>
    </div>
  `;
  
  document.body.appendChild(modal);
  
  const closeModal = () => { modal.remove(); };
  document.querySelector("#btn-close-view-modal").addEventListener("click", closeModal);
  document.querySelector("#btn-close-view-modal-footer").addEventListener("click", closeModal);
  
  // 내용 복사 기능
  document.querySelector("#btn-copy-artifact-content").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(content);
      const btn = document.querySelector("#btn-copy-artifact-content");
      btn.textContent = "📋 복사 완료!";
      btn.style.background = "#10b981";
      btn.style.color = "white";
      setTimeout(() => {
        btn.textContent = "📋 전체내용 복사";
        btn.style.background = "";
        btn.style.color = "";
      }, 1500);
    } catch (err) {
      alert("복사 실패: " + err.message);
    }
  });
}

function renderRunEventsTimeline(logs) {
  if (!logs || !logs.length) {
    return `<div style="color:#64748b; font-size:13px; text-align:center; padding: 40px 10px;">이 실행에 대한 events.jsonl 기록이 비어있거나 없습니다.</div>`;
  }
  
  return `
    <div class="run-timeline" style="position:relative; padding-left:24px; border-left: 2px solid #312e81; margin-left: 10px; text-align:left; color:#cbd5e1;">
      ${logs.map((log, index) => {
        const time = log.timestamp ? new Date(log.timestamp).toLocaleString("ko-KR", {hour12: false}) : "-";
        const level = String(log.level || "INFO").toUpperCase();
        const event = log.event || "log_message";
        const message = log.message || "";
        
        let levelColor = "#3b82f6";
        if (level === "ERROR" || level === "FATAL") levelColor = "#ef4444";
        else if (level === "WARN" || level === "WARNING") levelColor = "#f59e0b";
        else if (level === "DEBUG") levelColor = "#64748b";
        
        let icon = "⚙️";
        if (event.includes("start")) icon = "🚀";
        else if (event.includes("complete") || event.includes("success")) icon = "✅";
        else if (event.includes("fail") || event.includes("error")) icon = "❌";
        else if (event.includes("indicator")) icon = "📊";
        else if (event.includes("optimizer") || event.includes("genetic")) icon = "🧬";
        else if (event.includes("trade") || event.includes("order")) icon = "💸";
        
        const detailKeys = Object.keys(log).filter(k => !["timestamp", "level", "logger", "message", "run_id", "event"].includes(k));
        let detailsHtml = "";
        
        if (detailKeys.length > 0) {
          const detailObj = {};
          detailKeys.forEach(k => { detailObj[k] = log[k]; });
          
          detailsHtml = `
            <div style="margin-top:8px;">
              <button class="timeline-details-toggle" data-index="${index}" style="background:none; border:none; color:#c7d2fe; font-size:11px; padding:0; cursor:pointer; font-weight:600; text-decoration:underline;">
                ▼ 상세보기
              </button>
              <div id="details-box-${index}" style="display:none; background:#110c22; border: 1px solid #312e81; border-radius:6px; padding:10px; margin-top:6px; font-family:monospace; font-size:11px; color:#cbd5e1; overflow-x:auto; white-space:pre-wrap; position:relative;">
                <button class="btn-copy-raw-json" data-json="${escapeHtml(JSON.stringify(log, null, 2))}" style="position:absolute; right:8px; top:8px; background:#1e1b4b; border:1px solid #4f46e5; color:#c7d2fe; border-radius:4px; font-size:9px; padding:2px 6px; cursor:pointer;">
                  Copy JSON
                </button>
                <div style="margin-bottom:8px; font-weight:bold; color:#818cf8; border-bottom:1px solid #1e1b4b; padding-bottom:4px;">상세 파라미터 / 속성</div>
                ${Object.entries(detailObj).map(([k, v]) => {
                  let valStr = typeof v === 'object' ? JSON.stringify(v) : String(v);
                  if (typeof v === 'object') {
                     valStr = `<div style="padding-left:10px; color:#a7f3d0; margin-top:2px;">${Object.entries(v).map(([subK, subV]) => `· <strong>${subK}</strong>: ${subV}`).join("<br>")}</div>`;
                  }
                  return `<div><strong style="color:#93c5fd;">${escapeHtml(k)}</strong>: ${valStr}</div>`;
                }).join("")}
              </div>
            </div>
          `;
        }

        return `
          <div class="timeline-item" style="position:relative; margin-bottom: 24px;">
            <span style="position:absolute; left:-33px; top:2px; display:flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%; background:#1e1b4b; border: 2px solid #4f46e5; font-size:11px; z-index:2;">
              ${icon}
            </span>
            <div>
              <div style="display:flex; align-items:center; justify-content:space-between; font-size:11px; color:#818cf8; margin-bottom:4px;">
                <span>${time}</span>
                <span style="background:${levelColor}22; color:${levelColor}; border:1px solid ${levelColor}; padding:1px 4px; border-radius:3px; font-size:9px; font-weight:800;">${level}</span>
              </div>
              <strong style="font-size:13px; color:#e0e7ff; display:block; margin-bottom:4px;">${escapeHtml(event.toUpperCase())}</strong>
              <p style="margin:0; font-size:12px; color:#94a3b8; line-height:1.4;">${escapeHtml(message)}</p>
              ${detailsHtml}
            </div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

// ─────────────────────────────────────────────────────────────────────────────
// 개인 투자 운영 OS 확장 모듈 프론트엔드 연동 구현 (2차 고도화)
// ─────────────────────────────────────────────────────────────────────────────

function renderBackupRestoreSection() {
  const isAdmin = state.permissionMode === "admin";
  return `
    <div class="panel-header" style="display:flex; justify-content:space-between; align-items:center; border-bottom: 1px solid #e2e8f0; padding-bottom: 12px; margin-bottom: 12px;">
      <div>
        <h2 style="font-size:16px; font-weight:700; color:#0f172a; margin:0;">📦 운영 백업 및 복원 콘솔</h2>
        <p style="font-size:12px; color:#64748b; margin:4px 0 0 0;">시스템 설정, 실행 이력, 신호, 보고서 및 SQLite 데이터마트를 백업하고 안전하게 복원합니다.</p>
      </div>
      <button id="btn-create-backup" class="button button-primary" ${isAdmin ? "" : "disabled"} style="font-size:12px; padding: 6px 12px; height: auto;">
        📦 즉시 백업 생성
      </button>
    </div>
    <div id="backup-console-status" style="margin-bottom:12px; display:none; padding:10px; border-radius:6px; font-size:12px;"></div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>백업 파일명</th>
            <th>크기</th>
            <th>생성 일시</th>
            <th style="text-align:right;">작업</th>
          </tr>
        </thead>
        <tbody id="backup-list-tbody">
          <tr><td colspan="4" style="text-align:center; padding:20px; color:#64748b;">백업 목록을 불러오는 중...</td></tr>
        </tbody>
      </table>
    </div>
  `;
}

function renderExperimentsSection() {
  const isAdmin = state.permissionMode === "admin";
  return `
    <div class="panel-header" style="border-bottom: 1px solid #e2e8f0; padding-bottom: 12px; margin-bottom: 12px;">
      <div>
        <h2 style="font-size:16px; font-weight:700; color:#0f172a; margin:0;">🔬 시뮬레이션 실험 Registry</h2>
        <p style="font-size:12px; color:#64748b; margin:4px 0 0 0;">운영 실행과 분리된 전략 실험, 단타 시뮬레이션, Paper 결과를 실험 단위로 등록하고 비교 관리합니다.</p>
      </div>
    </div>
    
    <div style="display:grid; grid-template-columns: 1fr 340px; gap: 20px;">
      <div>
        <h3 style="font-size:13px; color:#334155; margin:0 0 10px 0; font-weight:700;">🔬 등록된 실험 목록</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>전략명</th>
                <th>대상 종목</th>
                <th>가설 / 목적</th>
                <th>성과 지표</th>
                <th>상태</th>
              </tr>
            </thead>
            <tbody id="experiment-list-tbody">
              <tr><td colspan="5" style="text-align:center; padding:20px; color:#64748b;">실험 목록을 불러오는 중...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      
      <div style="background:#f8fafc; border: 1px solid #e2e8f0; border-radius:8px; padding:15px; box-shadow: inset 0 1px 2px rgba(0,0,0,0.02);">
        <h3 style="font-size:13px; color:#0f172a; margin:0 0 12px 0; font-weight:700; border-bottom:1px solid #e2e8f0; padding-bottom:8px;">🔬 신규 실험 등록</h3>
        <form id="form-register-experiment" style="display:flex; flex-direction:column; gap:10px;">
          <div>
            <label style="display:block; font-size:11px; color:#475569; margin-bottom:4px; font-weight:600;">실행 ID (Run ID) *</label>
            <input type="text" id="exp-run-id" required placeholder="예: run_20260627_120000" style="width:100%; padding:6px 10px; font-size:12px; border: 1px solid #cbd5e1; border-radius:6px; box-sizing:border-box;">
          </div>
          <div>
            <label style="display:block; font-size:11px; color:#475569; margin-bottom:4px; font-weight:600;">전략명 (Strategy Name) *</label>
            <input type="text" id="exp-strategy" required placeholder="예: Momentum_V4" style="width:100%; padding:6px 10px; font-size:12px; border: 1px solid #cbd5e1; border-radius:6px; box-sizing:border-box;">
          </div>
          <div>
            <label style="display:block; font-size:11px; color:#475569; margin-bottom:4px; font-weight:600;">대상 종목 (쉼표 구분) *</label>
            <input type="text" id="exp-tickers" required placeholder="예: SOXL, TQQQ" style="width:100%; padding:6px 10px; font-size:12px; border: 1px solid #cbd5e1; border-radius:6px; box-sizing:border-box;">
          </div>
          <div>
            <label style="display:block; font-size:11px; color:#475569; margin-bottom:4px; font-weight:600;">실험 목적 (Objective)</label>
            <textarea id="exp-objective" rows="2" placeholder="실험의 목적을 설명하세요" style="width:100%; padding:6px 10px; font-size:12px; border: 1px solid #cbd5e1; border-radius:6px; resize:none; box-sizing:border-box;"></textarea>
          </div>
          <div>
            <label style="display:block; font-size:11px; color:#475569; margin-bottom:4px; font-weight:600;">가설 (Hypothesis)</label>
            <textarea id="exp-hypothesis" rows="2" placeholder="가설을 설명하세요" style="width:100%; padding:6px 10px; font-size:12px; border: 1px solid #cbd5e1; border-radius:6px; resize:none; box-sizing:border-box;"></textarea>
          </div>
          <button type="submit" class="button button-primary" ${isAdmin ? "" : "disabled"} style="width:100%; font-size:12px; padding:8px; height:auto; margin-top:5px;">
            🔬 실험 등록하기
          </button>
        </form>
      </div>
    </div>
  `;
}

function renderEventsSection() {
  return `
    <div class="panel-header" style="border-bottom: 1px solid #e2e8f0; padding-bottom: 12px; margin-bottom: 12px;">
      <div>
        <h2 style="font-size:16px; font-weight:700; color:#0f172a; margin:0;">🔔 실시간 도메인 이벤트 타임라인 (Event Bus)</h2>
        <p style="font-size:12px; color:#64748b; margin:4px 0 0 0;">신호 생성, 리스크 차단, 의사결정 승인, 알림 라우팅 등 시스템 핵심 도메인 이벤트를 실시간으로 모니터링합니다.</p>
      </div>
    </div>
    <div class="timeline-wrap" style="max-height:350px; overflow-y:auto; background:#0f172a; border-radius:8px; padding:15px; border:1px solid #1e293b;">
      <div id="event-timeline-container" style="display:flex; flex-direction:column; gap:12px;">
        <div style="text-align:center; padding:20px; color:#94a3b8; font-size:12px;">이벤트 로그를 불러오는 중...</div>
      </div>
    </div>
  `;
}

async function bindSettingsExtensionsActions() {
  // 1. 데이터 로드
  await Promise.all([
    loadBackupList(),
    loadExperimentList(),
    loadEventTimeline()
  ]);

  // 2. 백업 생성 이벤트 바인딩
  const btnCreateBackup = document.querySelector("#btn-create-backup");
  if (btnCreateBackup) {
    btnCreateBackup.addEventListener("click", async () => {
      const statusDiv = document.querySelector("#backup-console-status");
      statusDiv.style.display = "block";
      statusDiv.style.background = "#eff6ff";
      statusDiv.style.color = "#1d4ed8";
      statusDiv.style.border = "1px solid #bfdbfe";
      statusDiv.textContent = "⚙️ 백업 파일 압축 및 체크섬 생성 중...";
      btnCreateBackup.disabled = true;

      try {
        const response = await fetch("/api/v1/backup/create", { method: "POST" });
        const res = await response.json();
        if (res.status === "success") {
          statusDiv.style.background = "#ecfdf5";
          statusDiv.style.color = "#065f46";
          statusDiv.style.border = "1px solid #a7f3d0";
          statusDiv.textContent = `✅ 백업 성공: ${res.backup_file} (SHA256: ${res.sha256.slice(0,8)}...)`;
          await loadBackupList();
        } else {
          throw new Error(res.message || "알 수 없는 오류");
        }
      } catch (err) {
        statusDiv.style.background = "#fef2f2";
        statusDiv.style.color = "#991b1b";
        statusDiv.style.border = "1px solid #fca5a5";
        statusDiv.textContent = `❌ 백업 실패: ${err.message}`;
      } finally {
        if (state.permissionMode === "admin") {
          btnCreateBackup.disabled = false;
        }
      }
    });
  }

  // 3. 실험 등록 폼 이벤트 바인딩
  const formExp = document.querySelector("#form-register-experiment");
  if (formExp) {
    formExp.addEventListener("submit", async (e) => {
      e.preventDefault();
      const runId = document.querySelector("#exp-run-id").value.trim();
      const strategy = document.querySelector("#exp-strategy").value.trim();
      const tickers = document.querySelector("#exp-tickers").value.split(",").map(t => t.trim().toUpperCase()).filter(t => t);
      const objective = document.querySelector("#exp-objective").value.trim();
      const hypothesis = document.querySelector("#exp-hypothesis").value.trim();

      try {
        const response = await fetch("/api/v1/experiments", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            run_id: runId,
            strategy_name: strategy,
            target_tickers: tickers,
            objective: objective,
            hypothesis: hypothesis
          })
        });
        const res = await response.json();
        if (res.status === "success") {
          alert(`🔬 실험 등록 성공! (Run ID: ${res.run_id})`);
          formExp.reset();
          await loadExperimentList();
        } else {
          throw new Error(res.message || "등록 실패");
        }
      } catch (err) {
        alert(`❌ 실험 등록 실패: ${err.message}`);
      }
    });
  }
}

async function loadBackupList() {
  const tbody = document.querySelector("#backup-list-tbody");
  if (!tbody) return;

  try {
    const res = await api("/api/v1/backup/list");
    const backups = res.backups || [];
    if (backups.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:20px; color:#64748b;">백업 파일이 존재하지 않습니다.</td></tr>`;
      return;
    }

    const isAdmin = state.permissionMode === "admin";
    tbody.innerHTML = backups.map(b => {
      const sizeKB = (b.size / 1024).toFixed(1);
      const timeStr = new Date(b.mtime).toLocaleString("ko-KR");
      return `
        <tr>
          <td class="code" style="font-weight:600; color:#0f172a;">${escapeHtml(b.name)}</td>
          <td>${sizeKB} KB</td>
          <td>${timeStr}</td>
          <td style="text-align:right; display:flex; gap:6px; justify-content:flex-end;">
            <button class="button btn-backup-dryrun" data-file="${escapeHtml(b.name)}" style="font-size:11px; padding:3px 8px; height:auto; background:#f1f5f9; color:#334155; border:1px solid #cbd5e1;">
              🔍 검증
            </button>
            <button class="button button-danger btn-backup-restore" data-file="${escapeHtml(b.name)}" ${isAdmin ? "" : "disabled"} style="font-size:11px; padding:3px 8px; height:auto;">
              ⏪ 복원
            </button>
          </td>
        </tr>
      `;
    }).join("");

    // 이벤트 바인딩
    document.querySelectorAll(".btn-backup-dryrun").forEach(btn => {
      btn.addEventListener("click", () => handleBackupRestore(btn.dataset.file, true));
    });
    document.querySelectorAll(".btn-backup-restore").forEach(btn => {
      btn.addEventListener("click", () => handleBackupRestore(btn.dataset.file, false));
    });

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:20px; color:#ef4444;">백업 목록 로드 실패: ${err.message}</td></tr>`;
  }
}

async function handleBackupRestore(filename, dryRun) {
  const modeText = dryRun ? "드라이런 검증" : "실제 복원";
  if (!dryRun && !confirm(`⚠️ 정말로 백업 파일 [${filename}]로 복원하시겠습니까?\n현재 모든 운영 데이터(state, runs, signals 등)가 덮어씌워지며 복원 완료 후 서버가 최신 데이터로 동기화됩니다.`)) {
    return;
  }

  const statusDiv = document.querySelector("#backup-console-status");
  if (statusDiv) {
    statusDiv.style.display = "block";
    statusDiv.style.background = "#fef3c7";
    statusDiv.style.color = "#d97706";
    statusDiv.style.border = "1px solid #fde68a";
    statusDiv.textContent = `⚙️ 백업 복원 [${modeText}] 진행 중...`;
  }

  try {
    const response = await fetch("/api/v1/backup/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: filename, dry_run: dryRun })
    });
    const res = await response.json();
    if (res.status === "success") {
      const r = res.report;
      if (statusDiv) {
        if (r.valid) {
          statusDiv.style.background = "#ecfdf5";
          statusDiv.style.color = "#065f46";
          statusDiv.style.border = "1px solid #a7f3d0";
          statusDiv.textContent = `✅ 복원 [${modeText}] 무결성 검증 성공! 변경 작업 수: ${r.actions.length}건`;
        } else {
          statusDiv.style.background = "#fef2f2";
          statusDiv.style.color = "#991b1b";
          statusDiv.style.border = "1px solid #fca5a5";
          statusDiv.textContent = `❌ 복원 [${modeText}] 검증 실패: ${r.error || "무결성 위반 감지"}`;
        }
      }
      
      let details = r.actions.map(a => `· [${a.type}] ${a.path} (${a.status})`).join("\n");
      alert(`[${modeText} 결과]\n무결성 상태: ${r.valid ? "유효 (PASS)" : "무효 (FAIL)"}\n\n작업 내역:\n${details || "없음"}`);

      if (!dryRun && r.valid) {
        await loadPage();
      }
    } else {
      throw new Error(res.message || "복원 처리 오류");
    }
  } catch (err) {
    if (statusDiv) {
      statusDiv.style.background = "#fef2f2";
      statusDiv.style.color = "#991b1b";
      statusDiv.style.border = "1px solid #fca5a5";
      statusDiv.textContent = `❌ 복원 실패: ${err.message}`;
    }
    alert(`❌ 복원 오류: ${err.message}`);
  }
}

async function loadExperimentList() {
  const tbody = document.querySelector("#experiment-list-tbody");
  if (!tbody) return;

  try {
    const res = await api("/api/v1/experiments");
    const exps = res.experiments || [];
    if (exps.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:#64748b;">등록된 시뮬레이션 실험이 없습니다.</td></tr>`;
      return;
    }

    tbody.innerHTML = exps.map(e => {
      const tickersStr = (e.target_tickers || []).join(", ");
      const metrics = e.result_metrics || {};
      const metricsStr = Object.entries(metrics).map(([k, v]) => `${k}: ${v}`).join(", ") || "대기 중";
      const statusBadgeHtml = e.promoted 
        ? `<span class="badge badge-success">🚀 운영 승격</span>` 
        : `<span class="badge badge-warning">🔬 실험 중</span>`;
      
      return `
        <tr>
          <td><strong style="color:#0f172a;">${escapeHtml(e.strategy_name)}</strong><br><span class="code" style="font-size:10px; color:#64748b;">${escapeHtml(e.run_id)}</span></td>
          <td><span class="code">${escapeHtml(tickersStr)}</span></td>
          <td>
            <div style="font-weight:600; font-size:12px; color:#334155;">${escapeHtml(e.objective || "-")}</div>
            <div style="font-size:11px; color:#64748b; margin-top:2px;">가설: ${escapeHtml(e.hypothesis || "-")}</div>
          </td>
          <td class="code" style="font-size:11px;">${escapeHtml(metricsStr)}</td>
          <td>${statusBadgeHtml}</td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:#ef4444;">실험 목록 로드 실패: ${err.message}</td></tr>`;
  }
}

async function loadEventTimeline() {
  const container = document.querySelector("#event-timeline-container");
  if (!container) return;

  try {
    const res = await api("/api/v1/events");
    const events = res.events || [];
    if (events.length === 0) {
      container.innerHTML = `<div style="text-align:center; padding:20px; color:#94a3b8; font-size:12px;">발행된 도메인 이벤트가 없습니다.</div>`;
      return;
    }

    container.innerHTML = events.map(e => {
      const time = new Date(e.created_at).toLocaleTimeString("ko-KR", { hour12: false });
      const sev = String(e.severity || "info").toLowerCase();
      
      let badgeColor = "#3b82f6"; // blue (info)
      if (sev === "critical" || sev === "error" || sev === "blocked") badgeColor = "#ef4444"; // red
      else if (sev === "warning" || sev === "warn") badgeColor = "#f59e0b"; // yellow
      
      let icon = "🔔";
      if (e.event_type.includes("created")) icon = "✨";
      else if (e.event_type.includes("blocked")) icon = "🛑";
      else if (e.event_type.includes("approved") || e.event_type.includes("recorded")) icon = "✍️";
      else if (e.event_type.includes("completed")) icon = "🏁";
      else if (e.event_type.includes("queued")) icon = "💬";

      const payloadStr = JSON.stringify(e.payload || {});

      return `
        <div style="display:flex; gap:10px; border-bottom:1px solid #1e293b; padding-bottom:8px; align-items:flex-start;">
          <span style="font-size:14px; background:#1e293b; padding:4px; border-radius:4px; display:flex; align-items:center; justify-content:center;">
            ${icon}
          </span>
          <div style="flex:1; min-width:0;">
            <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; margin-bottom:2px;">
              <span style="font-weight:700; color:#818cf8;">${escapeHtml(e.event_type.toUpperCase())}</span>
              <span style="color:#64748b;">${time}</span>
            </div>
            <div style="font-size:12px; color:#e2e8f0; word-break:break-all;">
              <strong style="color:#cbd5e1;">[${escapeHtml(e.source_module)}]</strong> 
              ${escapeHtml(e.ticker ? `(${e.ticker}) ` : "")}
              ${escapeHtml(payloadStr.length > 120 ? payloadStr.slice(0, 120) + "..." : payloadStr)}
            </div>
          </div>
          <span style="background:${badgeColor}22; color:${badgeColor}; border:1px solid ${badgeColor}; padding:1px 4px; border-radius:3px; font-size:9px; font-weight:800;">
            ${sev.toUpperCase()}
          </span>
        </div>
      `;
    }).join("");

  } catch (err) {
    container.innerHTML = `<div style="text-align:center; padding:20px; color:#ef4444; font-size:12px;">이벤트 로드 실패: ${err.message}</div>`;
  }
}

