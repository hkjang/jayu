function autotradingStageStatus(stage) {
  return {
    auto_candidate: "success",
    semi_auto_review: "warning",
    paper_required: "warning",
    analysis_only: "not_evaluated",
    blocked: "blocked",
  }[stage] || "not_evaluated";
}

function renderAutotradingReadiness(readiness) {
  const data = readiness || {};
  const components = data.components || [];
  const actions = data.next_actions || [];
  const score = Number(data.score || 0);
  const maxScore = Number(data.max_score || 100) || 100;
  const ratio = Math.max(0, Math.min(100, (score / maxScore) * 100));
  const stageStatus = autotradingStageStatus(data.stage);
  const componentRows = components.length
    ? components.map((item) => `
        <div class="at-score-component status-${statusClass(item.status)}">
          <div>
            <strong>${escapeHtml(item.label || item.id)}</strong>
            <span>${escapeHtml(item.message || "")}</span>
            ${renderSourceCaption(item.source || "autotrading readiness score")}
          </div>
          <div class="at-score-component-meta">
            ${statusBadge(item.status)}
            <b>${formatNumber(item.score, 1)} / ${formatNumber(item.max_score, 1)}</b>
            <small>${escapeHtml(item.value || "")}</small>
          </div>
        </div>
      `).join("")
    : `<div class="empty-state">자동매매 준비 점수를 계산할 자료가 없습니다.</div>`;
  const actionRows = actions.length
    ? actions.map((item) => `
        <li>
          <strong>${escapeHtml(item.label || item.component)}</strong>
          <span>${escapeHtml(item.action || "")}</span>
          ${renderSourceCaption(item.source || "autotrading readiness score")}
        </li>
      `).join("")
    : `<li><strong>추가 조치 없음</strong><span>현재 점수 기준에서 우선 보강 항목이 없습니다.</span></li>`;

  return `
    <section class="at-section at-score-section">
      <div class="at-score-layout">
        <div class="at-score-gauge">
          <span>자동매매 준비 점수</span>
          <strong>${formatNumber(score, 1)}</strong>
          <small>/ ${formatNumber(maxScore, 0)} · ${escapeHtml(data.grade || "F")}</small>
          <div class="at-score-track"><div style="width:${ratio}%"></div></div>
          ${renderSourceCaption((data.sources || []).join(" · ") || "latest run manifest · operational_status.json · paper trading report")}
        </div>
        <div class="at-score-summary">
          ${statusBadge(stageStatus, data.stage_label || "분석 모드 유지")}
          <h2>${escapeHtml(data.summary || "자동매매 준비 상태를 점검 중입니다.")}</h2>
          <p>80점 이상이면 반자동 검토 후보, 90점 이상이고 Paper 성과가 충분할 때만 자동매매 후보로 봅니다. 실제 주문 전송은 계속 비활성입니다.</p>
          <div class="at-threshold-row">
            <span>반자동 ${formatNumber(data.thresholds?.semi_auto_review ?? 80, 0)}점</span>
            <span>자동 후보 ${formatNumber(data.thresholds?.auto_candidate ?? 90, 0)}점</span>
          </div>
        </div>
      </div>
      <div class="at-score-components">${componentRows}</div>
      <div class="at-next-actions">
        <h3>다음 보강 항목</h3>
        <ol>${actionRows}</ol>
      </div>
    </section>
  `;
}

function renderPaperPromotionReport(report) {
  const data = report || {};
  const criteria = data.criteria || [];
  const actions = data.next_actions || [];
  const status = data.status || "not_evaluated";
  const statusLabel = data.status_label || STATUS_LABELS[status] || status;
  const criteriaRows = criteria.length
    ? criteria.map((item) => `
        <div class="at-paper-criterion status-${statusClass(item.status)}">
          <div>
            <strong>${escapeHtml(item.label || item.id)}</strong>
            <span>${escapeHtml(item.message || "")}</span>
            ${renderSourceCaption(item.source || data.source || "paper trading report")}
          </div>
          <div class="at-paper-criterion-meta">
            ${statusBadge(item.status)}
            <b>${escapeHtml(item.observed || "미검증")}</b>
            <small>기준 ${escapeHtml(item.required || "-")}</small>
          </div>
        </div>
      `).join("")
    : `<div class="empty-state">Paper Trading 승격 기준을 계산할 데이터가 없습니다.</div>`;
  const actionRows = actions.length
    ? actions.map((item) => `
        <li>
          <strong>${escapeHtml(item.label || item.criterion)}</strong>
          <span>${escapeHtml(item.action || "")}</span>
          ${renderSourceCaption(item.source || data.source || "paper trading report")}
        </li>
      `).join("")
    : `<li><strong>추가 조치 없음</strong><span>현재 Paper 승격 기준에서 즉시 보강할 항목이 없습니다.</span></li>`;

  return `
    <section class="at-section at-paper-report">
      <div class="at-paper-header">
        <div>
          <div class="at-section-eyebrow">Paper Trading</div>
          <h2>Paper Trading 승격 리포트</h2>
          ${renderSourceCaption(data.source || "paper_trading.json · autotrading readiness score")}
        </div>
        <span class="status-label status-${statusClass(status)}">${escapeHtml(statusLabel)}</span>
      </div>
      <div class="at-paper-summary">
        <p>${escapeHtml(data.summary || "Paper Trading 승격 상태를 계산하지 못했습니다.")}</p>
        <div class="at-paper-eligibility">
          <span class="${data.eligible_for_semi_auto ? "is-pass" : "is-wait"}">
            반자동 검토 ${data.eligible_for_semi_auto ? "가능" : "보류"}
          </span>
          <span class="${data.eligible_for_auto_candidate ? "is-pass" : "is-wait"}">
            자동 후보 ${data.eligible_for_auto_candidate ? "가능" : "보류"}
          </span>
        </div>
      </div>
      <div class="at-paper-criteria">${criteriaRows}</div>
      <div class="at-next-actions at-paper-actions">
        <h3>승격 전 보강 항목</h3>
        <ol>${actionRows}</ol>
      </div>
    </section>
  `;
}

function renderAutotrading() {
  const data = state.autotradingStatus;

  if (!data) {
    els.root.innerHTML = `
      <div class="page-heading"><h1>자동매매 준비</h1></div>
      <div class="analysis-loading">⏳ 자동매매 상태 로딩 중...</div>`;
    return;
  }

  const status = data.status || {};
  const phases = data.phases || [];
  const requirements = data.safety_requirements || [];
  const passedCount = requirements.filter(r => r.current).length;
  const totalCount = requirements.length;

  const phaseCards = phases.map(phase => `
    <div class="at-phase-card ${phase.is_current ? "is-current" : ""}" style="border-left:4px solid ${phase.color}">
      <div class="at-phase-header">
        <span class="at-phase-label" style="color:${phase.color}">${escapeHtml(phase.label)}</span>
        ${phase.is_current ? '<span class="at-phase-badge">현재 상태</span>' : ""}
      </div>
      <p class="at-phase-desc">${escapeHtml(phase.description)}</p>
      ${phase.requirements ? `
      <div class="at-phase-reqs">
        ${phase.requirements.map(r => `<span class="at-phase-req">✓ ${escapeHtml(r)}</span>`).join("")}
      </div>` : ""}
    </div>`).join("");

  const reqItems = requirements.map(req => `
    <div class="at-req-item ${req.current ? "is-done" : ""}">
      <span class="at-req-icon">${req.current ? "✅" : "⬜"}</span>
      <div class="at-req-body">
        <strong>${escapeHtml(req.label)}</strong>
        <p>${escapeHtml(req.description)}</p>
      </div>
    </div>`).join("");

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>자동매매 준비 상태</h1>
        <p>자동매매는 모든 안전장치를 갖춘 후 단계적으로 활성화합니다. 현재는 비활성 상태입니다.</p>
      </div>
      <span class="at-status-badge">🔒 비활성</span>
    </div>

    <div class="at-warning-box">
      <div class="at-warning-icon">⚠️</div>
      <div>
        <strong>자동매매 위험 안내</strong>
        <p>${escapeHtml(status.warning || data.warning || "")}</p>
      </div>
    </div>

    <div class="at-disclaimer-box">
      <strong>투자 책임 고지</strong>
      <p>${escapeHtml(status.disclaimer || data.disclaimer || "")}</p>
    </div>

    ${renderAutotradingReadiness(data.readiness_score)}
    ${renderPaperPromotionReport(data.paper_promotion_report)}

    <section class="at-section">
      <h2>단계별 활성화 로드맵</h2>
      <p style="font-size:13px;color:#64748b;margin-bottom:12px">자동매매는 비활성 → 모의투자 → 반자동 → 자동 순서로 단계적으로 확장됩니다.</p>
      <div class="at-phases-grid">${phaseCards}</div>
    </section>

    <section class="at-section">
      <h2>안전장치 체크리스트</h2>
      <div class="at-progress-bar-wrap">
        <div class="at-progress-bar" style="width:${totalCount ? Math.round(passedCount/totalCount*100) : 0}%"></div>
      </div>
      <p style="font-size:12px;color:#64748b;margin:4px 0 12px">${passedCount}/${totalCount} 항목 완료</p>
      <div class="at-req-list">${reqItems}</div>
    </section>

    <section class="at-section">
      <h2>현재 자동매매 상태</h2>
      <div class="at-current-status">
        <div class="at-status-row"><strong>활성 여부:</strong> <span style="color:#ef4444">비활성 (disabled)</span></div>
        <div class="at-status-row"><strong>현재 단계:</strong> 비활성 (모의투자 단계 아님)</div>
        <div class="at-status-row"><strong>주문 발송:</strong> <span style="color:#ef4444">불가 — 자동매매 기능 미구현</span></div>
        <div class="at-status-row"><strong>안전장치 충족:</strong> ${passedCount}/${totalCount}</div>
      </div>
      <p style="margin-top:12px;font-size:13px;color:#64748b">${escapeHtml(status.message || "자동매매는 현재 비활성 상태입니다.")}</p>
    </section>
  `;
}
