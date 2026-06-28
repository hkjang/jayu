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

  // Reactively load Home Briefing and Account Change Diff data if not present
  if (state.homeBriefing === undefined || state.accountDiff === undefined) {
    state.homeBriefing = null;
    state.accountDiff = null;
    Promise.all([
      fetch("/api/v1/home-briefing").then(r => r.ok ? r.json() : null).catch(() => null),
      fetch("/api/v1/account-diff").then(r => r.ok ? r.json() : null).catch(() => null)
    ]).then(([briefing, diff]) => {
      state.homeBriefing = briefing;
      state.accountDiff = diff;
      renderOverview();
    });
  }

  // 1. Home Briefing Card HTML
  let briefingHtml = "";
  if (state.homeBriefing && state.homeBriefing.briefings) {
    const bList = state.homeBriefing.briefings;
    const overall = state.homeBriefing.overall_status;
    const overallClass = overall === "정상" ? "success" : "warning";
    
    briefingHtml = `
      <article class="decision-card status-${overallClass}" style="margin-bottom: 20px;">
        <div class="decision-eyebrow">
          <span class="status-label status-${overallClass}">오늘의 상태: ${overall}</span>
          <span>🛡️ JAYU HOME BRIEFING</span>
        </div>
        <h2 style="font-size: 20px; font-weight: 800; margin: 10px 0 15px 0;">📋 오늘 확인해야 할 투자 요약 (Top ${bList.length})</h2>
        <div style="display: flex; flex-direction: column; gap: 12px;">
          ${bList.map((b, idx) => {
            const sevClass = b.severity === "blocked" ? "failed" : b.severity === "warning" ? "warning" : "success";
            const badge = b.severity === "blocked" ? "🚨 차단" : b.severity === "warning" ? "⚠️ 경고" : "ℹ️ 정보";
            return `
              <div style="padding: 12px; background: var(--bg-card); border-left: 4px solid var(--${sevClass}); border-radius: 4px; display: flex; flex-direction: column; gap: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px;">
                  <strong style="color: var(--${sevClass});">${badge} [${b.status}]</strong>
                  <span style="color: var(--muted); font-size: 10px;">출처: ${b.source_module}</span>
                </div>
                <p style="margin: 4px 0; font-size: 12.5px; line-height: 1.4; color: var(--text); font-weight: 500;">
                  ${escapeHtml(b.reason)}
                </p>
                <div style="font-size: 11px; color: var(--accent); margin-top: 2px;">
                  <strong>💡 추천 액션:</strong> ${escapeHtml(b.next_action)}
                </div>
              </div>
            `;
          }).join("")}
        </div>
      </article>
    `;
  } else if (state.homeBriefing === null) {
    briefingHtml = `
      <div style="padding:20px; text-align:center; background: var(--bg-card); border: 1px dashed var(--border); border-radius: 6px; margin-bottom:20px;">
        <span class="spinner"></span> 오늘의 브리핑을 요약하는 중...
      </div>
    `;
  }

  // 2. Account Change Diff Card HTML
  let diffHtml = "";
  if (state.accountDiff && state.accountDiff.status === "success" && state.accountDiff.compare_file !== "none") {
    const sum = state.accountDiff.summary;
    const pct = sum.total_change_pct;
    const changeClass = pct >= 0 ? "success" : "failed";
    const directionSign = pct >= 0 ? "+" : "";
    
    diffHtml = `
      <article class="decision-card status-${changeClass}" style="margin-bottom: 20px;">
        <div class="decision-eyebrow">
          <span class="status-label status-${changeClass}">변동률: ${directionSign}${pct}%</span>
          <span>🔄 PORTFOLIO ACCOUNT DIFF</span>
        </div>
        <h2 style="font-size: 18px; font-weight: 800; margin: 10px 0 5px 0;">📊 자산 변동 기여도 분석 (Decomposition)</h2>
        <p style="font-size:12px; color: var(--muted); margin-bottom: 15px;">직전 스냅샷(${state.accountDiff.compare_file}) 대비 변동 분석 결과</p>
        
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 15px;">
          <div style="padding: 10px; background: var(--bg-card); border-radius: 4px; border: 1px solid var(--border);">
            <span style="font-size: 11px; color: var(--muted);">이전 자산</span>
            <div style="font-size: 16px; font-weight: 700; margin-top: 2px;">${sum.previous_value_krw.toLocaleString()} 원</div>
          </div>
          <div style="padding: 10px; background: var(--bg-card); border-radius: 4px; border: 1px solid var(--border);">
            <span style="font-size: 11px; color: var(--muted);">현재 자산</span>
            <div style="font-size: 16px; font-weight: 700; margin-top: 2px;">${sum.current_value_krw.toLocaleString()} 원</div>
          </div>
          <div style="padding: 10px; background: var(--bg-card); border-radius: 4px; border: 1px solid var(--border);">
            <span style="font-size: 11px; color: var(--muted);">전체 순변동액</span>
            <div style="font-size: 16px; font-weight: 700; color: var(--${changeClass}); margin-top: 2px;">
              ${directionSign}${sum.total_change_krw.toLocaleString()} 원 (${directionSign}${pct}%)
            </div>
          </div>
        </div>
        
        <h3 style="font-size: 13px; font-weight: 700; margin: 10px 0; color: var(--text);">기여 요인 상세</h3>
        <div style="font-size: 12px; display: flex; flex-direction: column; gap: 8px;">
          <div style="display:flex; justify-content:space-between; border-bottom:1px dashed var(--border); padding-bottom:6px;">
            <span>📈 <strong>시장 가격 변동 기여분 (Price Effect)</strong></span>
            <strong style="color: ${sum.effects.price_change_contribution_usd >= 0 ? 'var(--success)' : 'var(--failed)'};">
              ${sum.effects.price_change_contribution_krw.toLocaleString()} 원
            </strong>
          </div>
          <div style="display:flex; justify-content:space-between; border-bottom:1px dashed var(--border); padding-bottom:6px;">
            <span>🛒 <strong>수량 변동 및 매매 기여분 (Quantity Effect)</strong></span>
            <strong style="color: ${sum.effects.quantity_change_contribution_usd >= 0 ? 'var(--success)' : 'var(--failed)'};">
              ${sum.effects.quantity_change_contribution_krw.toLocaleString()} 원
            </strong>
          </div>
        </div>
      </article>
    `;
  }

    // Personal investment dashboard summary cards
    let pfSummaryHtml = "";
    const scoreData = state.personalScore;
    const goalsData = state.investmentGoals;
    if (scoreData || (goalsData && goalsData.goals && goalsData.goals.length > 0)) {
      let scoreCardHtml = "";
      if (scoreData) {
        const scoreClass = scoreData.total_score >= 80 ? "success" : (scoreData.total_score >= 70 ? "warning" : "failed");
        scoreCardHtml = `
          <article class="decision-card status-${scoreClass}" style="margin:0;">
            <div class="decision-eyebrow">
              <span class="status-label status-${scoreClass}">${scoreData.grade}</span>
              <span>개인 투자 점수</span>
            </div>
            <h2 style="font-size:22px; font-weight:800; margin:10px 0 5px 0;">🎯 ${scoreData.total_score}점</h2>
            <p style="font-size:12px; line-height:1.4; color:var(--text);">${scoreData.description}</p>
            <div style="font-size:10.5px; color:var(--muted); margin-top:8px; display:grid; grid-template-columns: 1fr 1fr; gap:6px; border-top:1px dashed var(--border); padding-top:6px;">
              <span>🛡️ 리스크 준수: ${scoreData.breakdown.risk_compliance_score}/25</span>
              <span>😰 손실 회피: ${scoreData.breakdown.loss_avoidance_score}/25</span>
              <span>🔄 매매 빈도: ${scoreData.breakdown.trading_frequency_score}/20</span>
              <span>💵 자금 관리: ${scoreData.breakdown.cash_management_score}/15</span>
            </div>
          </article>
        `;
      }
      
      let goalsCardHtml = "";
      if (goalsData && goalsData.goals && goalsData.goals.length > 0) {
        const firstGoal = goalsData.goals[0];
        const shortfall = Math.max(0, firstGoal.target_amount - firstGoal.current_amount);
        const achPercent = firstGoal.target_amount > 0 ? (firstGoal.current_amount / firstGoal.target_amount * 100) : 0;
        goalsCardHtml = `
          <article class="decision-card status-success" style="margin:0;">
            <div class="decision-eyebrow">
              <span class="status-label status-success">${achPercent.toFixed(1)}% 달성</span>
              <span>내 투자 목표</span>
            </div>
            <h2 style="font-size:15px; font-weight:800; margin:10px 0 5px 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">🎯 ${escapeHtml(firstGoal.name)}</h2>
            <p style="font-size:11.5px; color:var(--text); margin:4px 0; line-height:1.4;">
              목표액: <strong>${Math.round(firstGoal.target_amount / 10000).toLocaleString()}만원</strong><br>
              부족액: <strong style="color:var(--failed);">${Math.round(shortfall / 10000).toLocaleString()}만원</strong>
            </p>
            <div style="font-size:10.5px; color:var(--muted); margin-top:6px; padding-top:6px; border-top:1px dashed var(--border);">
              <span>이번 달 필요 적립: <strong>${Math.round(firstGoal.monthly_deposit / 10000).toLocaleString()}만원</strong></span>
            </div>
          </article>
        `;
      } else {
        goalsCardHtml = `
          <article class="decision-card status-not-evaluated" style="margin:0; display:flex; flex-direction:column; justify-content:center; align-items:center; text-align:center; padding:15px;">
            <span style="font-size:24px; margin-bottom:4px;">🎯</span>
            <strong style="font-size:12.5px; display:block; margin-bottom:2px;">설정된 투자 목표가 없습니다</strong>
            <button class="button button-secondary" type="button" data-go="goal-planner" style="font-size:10.5px; padding:3px 8px; min-height:auto; margin-top:4px;">목표 설정하러 가기</button>
          </article>
        `;
      }
      
      pfSummaryHtml = `
        <h2 style="font-size:13px; font-weight:700; margin:20px 0 10px 0; color:var(--text);">🌱 개인 투자 생활관리 요약</h2>
        <section class="decision-grid" style="grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:16px; margin-bottom:20px;">
          ${scoreCardHtml}
          ${goalsCardHtml}
        </section>
      `;
    }

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>운영 상태 개요</h1>
        <p>오늘 실행을 계속 볼지, 멈추고 재검증할지 먼저 판단합니다. 차단 사유와 다음 행동을 상단에 고정합니다.</p>
      </div>
      ${statusBadge(run.execution_status, "실행")} 
    </div>
    ${renderDataSourceNote("overview")}
    ${briefingHtml}
    ${diffHtml}
    ${renderDecisionInboxPanel(state.decisionInbox)}
    ${renderOrderHistorySummaryPanel(state.orderHistorySummary, "overview")}
    ${renderNextCommandRecommendation(state.nextCommand)}
    ${pfSummaryHtml}
    ${renderDecisionDiffCard(data.decision_diff)}
    ${renderOverviewPortfolioHub(state.portfolioHub)}
    ${renderTodayBoard(data.today_board)}
    ${renderDecisionTimeline(data.decision_timeline)}
    ${renderDataLineageOverview(data.data_lineage)}
    ${renderRunEvidenceOverview(data.run_evidence)}
    ${renderFailurePatternOverview(data.failure_patterns || state.failurePatterns)}
    ${renderSessionReplay(data.session_replay)}
    ${renderRecoveryGuide(data.recovery_guide)}
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
      ${metricCard("증거 완성도", data.evidence_completeness?.score == null ? "미검증" : `${data.evidence_completeness.score}%`,
        data.evidence_completeness?.score >= 90 ? "success" : data.evidence_completeness?.score >= 70 ? "warning" : "blocked",
        `필수 ${7 - (data.evidence_completeness?.missing?.length || 0)}/7 개 존재`)}
      ${metricCard("운영 품질 (SLO)", data.ops_slo?.score == null ? "미검증" : `${data.ops_slo.score}점`,
        data.ops_slo?.score >= 90 ? "success" : data.ops_slo?.score >= 70 ? "warning" : "blocked",
        `최근 30일 건강도: ${data.ops_slo?.status === 'success' ? '정상' : (data.ops_slo?.status === 'warning' ? '우려' : '위험')}`,
        data.ops_slo?.score == null ? null : data.ops_slo.score / 100)}
    </section>
    ${renderRoutineScheduler(data.routines)}
    ${renderMetricDictionaryStrip(data.metric_dictionary?.overview, "운영 지표 쉬운 설명")}
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

function renderDecisionInboxPanel(inbox) {
  if (!inbox) return "";
  const summary = inbox.summary || {};
  const items = (inbox.items || []).slice(0, 8);
  const status = inbox.status || "not_evaluated";
  return `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div>
          <h2>오늘의 Decision Inbox</h2>
          <p>데이터 품질, Toss freshness, 배당, 주문 이력, 자동매매 가드에서 확인할 항목을 한 곳에 모았습니다.</p>
        </div>
        ${statusBadge(status, `${summary.item_count || 0}건`)}
      </div>
      <section class="metric-grid" style="margin-top:12px">
        ${metricCard("차단", summary.blocked_count || 0, summary.blocked_count ? "blocked" : "success", "즉시 확인", null, inbox.source || "decision_inbox.py")}
        ${metricCard("검토", (summary.warning_count || 0) + (summary.review_count || 0), (summary.warning_count || summary.review_count) ? "warning" : "success", "오늘 확인", null, inbox.source || "decision_inbox.py")}
        ${metricCard("메뉴", Object.keys(summary.by_menu || {}).length, "not_evaluated", "관련 화면 수", null, inbox.source || "decision_inbox.py")}
      </section>
      ${items.length ? `
        <div class="table-wrap" style="margin-top:12px">
          <table>
            <thead><tr><th>Priority</th><th>Menu</th><th>Symbol</th><th>Code</th><th>Detail</th></tr></thead>
            <tbody>${items.map((item) => `
              <tr>
                <td>${statusBadge(item.status || "warning", `P${item.priority || 3}`)}</td>
                <td>${escapeHtml(item.menu || "-")}</td>
                <td>${item.symbol ? renderTicker(item.symbol) : "-"}</td>
                <td class="code">${escapeHtml(item.code || "-")}</td>
                <td><strong>${escapeHtml(item.title || "-")}</strong><br><span class="muted">${escapeHtml(item.detail || "")}</span>${renderSourceLabel(item.source || inbox.source || "decision_inbox.py")}</td>
              </tr>
            `).join("")}</tbody>
          </table>
        </div>
      ` : `<div class="empty-state"><strong>오늘 확인할 차단/검토 항목이 없습니다.</strong><span>공통 decision inbox 기준으로 즉시 조치할 항목이 없습니다.</span></div>`}
      ${renderSourceCaption(inbox.source || "GET /api/v1/decision-inbox")}
    </section>
  `;
}

function renderTodayBoard(board) {
  if (!board) return "";
  const sections = [
    ["tasks", "오늘 할 일", "먼저 처리할 운영 검토", "runs/*/manifest.json · safety_verdict.json"],
    ["risky_stocks", "위험 종목", "차단·경고·데이터 확인 대상", "today_signals.json · risk gate status"],
    ["buy_candidates", "매수 후보", "리스크 게이트 통과 후보", "today_signals.json"],
    ["sell_candidates", "매도 후보", "축소 또는 청산 검토 후보", "today_signals.json"],
    ["order_prepares", "주문 준비", "매수 후보가 있으면 OrderIntent 전 검증", "today_signals.json · OrderIntent validation queue"],
    ["dividend_reviews", "배당 점검", "배당 타입 보유·관심 종목", "portfolio_mapping.json"],
  ];
  return `
    <section class="today-board" aria-label="오늘 확인할 항목">
      <div class="today-board-header">
        <div>
          <h2>오늘 확인할 항목</h2>
          <p>실행 결과를 사용자가 바로 행동으로 옮길 수 있게 나눈 읽기 전용 점검판입니다.</p>
        </div>
        ${renderSourceLabel("latest run manifest · safety_verdict.json · today_signals.json · portfolio_mapping.json")}
      </div>
      <div class="today-board-grid">
        ${sections.map(([key, title, emptyText, source]) => renderTodayBoardCard(title, board[key] || [], emptyText, source)).join("")}
      </div>
    </section>`;
}

function renderTodayBoardCard(title, items, emptyText, fallbackSource) {
  return `
    <article class="today-card">
      <div class="today-card-header">
        <strong>${escapeHtml(title)}</strong>
        <span>${items.length}건</span>
      </div>
      <div class="today-list">
        ${items.length ? items.map((item) => renderTodayBoardItem(item, fallbackSource)).join("") : `
          <div class="today-empty">${escapeHtml(emptyText)}</div>
          ${renderSourceLabel(fallbackSource)}
        `}
      </div>
    </article>`;
}

function renderTodayBoardItem(item, fallbackSource) {
  const targetAttr = item.page
    ? `data-go="${escapeHtml(item.page)}"`
    : item.command
    ? `data-command="${escapeHtml(item.command)}"`
    : "";
  const priceBits = [
    item.entry_price != null ? `진입 ${formatNumber(item.entry_price, 2)}` : "",
    item.stop_price != null ? `손절 ${formatNumber(item.stop_price, 2)}` : "",
    item.target_price != null ? `목표 ${formatNumber(item.target_price, 2)}` : "",
  ].filter(Boolean);
  const queueStatus = item.queue_status || "new";
  const actionType = item.action_type || "";
  const tags = [
    ACTION_QUEUE_STATUS_LABELS[queueStatus] || queueStatus,
    ACTION_TYPE_LABELS[actionType] || actionType,
    item.priority ? `P${item.priority}` : "",
  ].filter(Boolean);
  return `
    <div class="today-item status-${statusClass(item.status || "not_evaluated")}">
      <div class="today-item-main">
        <strong>${renderTicker(item.label || item.ticker)} <span style="font-size:12px;color:var(--muted);font-weight:normal;">(${escapeHtml(getStockName(item.label || item.ticker))})</span></strong>
        ${tags.length ? `<div class="today-item-tags">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
        <span>${escapeHtml(item.detail || "")}</span>
        ${priceBits.length ? `<small>${escapeHtml(priceBits.join(" · "))}</small>` : ""}
      </div>
      ${targetAttr ? `<button class="icon-button today-jump" type="button" ${targetAttr} title="관련 화면으로 이동">›</button>` : ""}
      ${renderSourceLabel(item.source || fallbackSource)}
    </div>`;
}

function renderDecisionTimeline(timeline) {
  const events = Array.isArray(timeline) ? timeline : [];
  const rows = events.length ? events.map((event) => {
    const action = event.next_action || {};
    const attrs = action.page
      ? `data-go="${escapeHtml(action.page)}"`
      : action.command
        ? `data-command="${escapeHtml(action.command)}"`
        : "";
    const actionButton = attrs
      ? `<button class="button button-secondary timeline-action" type="button" ${attrs}>${escapeHtml(action.label || "확인")}</button>`
      : "";
    const meta = [
      event.occurred_at ? `시각 ${formatDate(event.occurred_at)}` : "",
      event.failure_code ? `실패 코드 ${event.failure_code}` : "",
      event.evidence ? `근거 ${event.evidence}` : "",
    ].filter(Boolean);
    return `
      <article class="timeline-item status-${statusClass(event.status || "not_evaluated")}">
        <div class="timeline-marker">${escapeHtml(event.step || "")}</div>
        <div class="timeline-content">
          <div class="timeline-title">
            <strong>${escapeHtml(event.label || "판단 단계")}</strong>
            ${statusBadge(event.status || "not_evaluated")}
          </div>
          <p>${escapeHtml(event.summary || "")}</p>
          <span>${escapeHtml(event.detail || "")}</span>
          ${meta.length ? `<div class="timeline-meta">${meta.map((item) => `<small>${escapeHtml(item)}</small>`).join("")}</div>` : ""}
          ${renderSourceLabel(event.source || event.evidence || "latest run artifacts")}
        </div>
        ${actionButton}
      </article>
    `;
  }).join("") : `
    <div class="timeline-empty">
      <strong>투자 판단 타임라인 없음</strong>
      <span>완료된 실행 또는 관련 artifact가 생기면 여기에 시간순 판단 흐름이 표시됩니다.</span>
    </div>
  `;
  return `
    <section class="decision-timeline" aria-label="투자 판단 타임라인">
      <div class="timeline-header">
        <div>
          <h2>투자 판단 타임라인</h2>
          <p>데이터 수집부터 알림 준비까지 오늘 결론이 만들어진 순서를 보여줍니다.</p>
        </div>
        ${renderSourceLabel("manifest.json · data_sources.json · signals_risk.json · risk_explanation.json · state artifacts")}
      </div>
      <div class="timeline-list">${rows}</div>
    </section>
  `;
}

function renderDataLineageOverview(lineage) {
  const data = lineage || {};
  const summary = data.summary || {};
  const source = data.source || summary.source || "data_lineage.json";
  if (!summary.node_count) return "";
  return `
    <section class="data-lineage-overview" aria-label="데이터 계보 요약">
      <div class="data-lineage-overview-head">
        <div>
          <h2>데이터 계보 요약</h2>
          <p>수집 데이터가 신호와 운영 게이트로 이어지는 경로의 현재 상태입니다.</p>
        </div>
        <button class="button button-secondary" type="button" data-go="data-quality">계보 상세</button>
      </div>
      <div class="data-lineage-summary">
        ${metricCard("계보 노드", formatNumber(summary.node_count || 0, 0), data.status || "not_evaluated", `연결 ${formatNumber(summary.edge_count || 0, 0)}개`, null, source)}
        ${metricCard("Provider", formatNumber(summary.provider_count || 0, 0), summary.failed_provider_count ? "warning" : "success", `실패 ${formatNumber(summary.failed_provider_count || 0, 0)}개`, null, source)}
        ${metricCard("누락 산출물", formatNumber(summary.missing_artifact_count || 0, 0), summary.missing_artifact_count ? "warning" : "success", "파일 존재 확인", null, source)}
        ${metricCard("차단 게이트", formatNumber(summary.blocked_gate_count || 0, 0), summary.blocked_gate_count ? "blocked" : "success", "process/gate 상태", null, source)}
      </div>
      ${renderSourceCaption(source)}
    </section>
  `;
}

function renderRunEvidenceOverview(evidence) {
  const data = evidence || {};
  const summary = data.summary || {};
  const source = data.source || summary.source || "run_evidence.json";
  if (!summary.required_count) return "";
  const missing = (data.items || []).filter((item) => item.exists !== true && item.severity !== "optional");
  
  const comp = state.overview?.evidence_completeness;
  let checklistHtml = "";
  if (comp) {
    const labels = {
      manifest: "실행 정보 (manifest.json)",
      data_sources: "데이터 출처 (data_sources.json)",
      provider_disagreement_report: "제공자 불일치 리포트 (provider_disagreement_report.json)",
      signals: "리스크 및 신호 (signals_risk.json)",
      risk_explanation: "리스크 사유 사전 (risk_explanation.json)",
      safety_verdict: "안전 진단 판결 (safety_verdict.json)",
      report: "분석 종합 리포트 (report.md/html)"
    };
    checklistHtml = `
      <div class="evidence-checklist" style="margin-top: 15px; padding: 12px; background: rgba(0,0,0,0.05); border: 1px solid var(--border); border-radius: 6px;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 13px; font-weight: bold;">
          <span>⚖️ 핵심 7대 운영 증거 점검 (체크리스트)</span>
          <span style="color: ${comp.score >= 90 ? '#10b981' : comp.score >= 70 ? '#f59e0b' : '#ef4444'}">${comp.score}점</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 6px;">
          ${Object.entries(labels).map(([key, lbl]) => {
            const has = comp.present && comp.present.includes(key);
            return `
              <div style="display: flex; align-items: center; gap: 6px; font-size: 11px; padding: 4px 8px; border-radius: 4px; background: ${has ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)'}; border: 1px solid ${has ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'};">
                <span style="color: ${has ? '#10b981' : '#ef4444'}; font-weight: bold;">${has ? '✓' : '✗'}</span>
                <span style="color: var(--text);">${escapeHtml(lbl)}</span>
              </div>
            `;
          }).join("")}
        </div>
      </div>
    `;
  }

  return `
    <section class="run-evidence-section status-${statusClass(data.status || "not_evaluated")}" aria-label="실행 증거 완성도">
      <div class="run-evidence-head">
        <div>
          <h2>실행 증거 완성도</h2>
          <p>운영 판단에 필요한 run 산출물이 빠짐없이 남아 있는지 확인합니다.</p>
        </div>
        ${statusBadge(data.status || "not_evaluated")}
      </div>
      <div class="run-evidence-summary">
        ${metricCard("증거 완성도", summary.completeness_rate == null ? "미검증" : formatPercent(summary.completeness_rate), data.status || "not_evaluated", `${formatNumber(summary.present_required_count || 0, 0)}/${formatNumber(summary.required_count || 0, 0)} 필수`, summary.completeness_rate, source)}
        ${metricCard("필수 증거", formatNumber(summary.required_count || 0, 0), summary.missing_required_count ? "blocked" : "success", `확인 ${formatNumber(summary.present_required_count || 0, 0)}개`, null, source)}
        ${metricCard("누락 증거", formatNumber(summary.missing_required_count || 0, 0), summary.missing_required_count ? "blocked" : "success", "필수 산출물", null, source)}
        ${metricCard("경고 증거", formatNumber(summary.missing_warning_count || 0, 0), summary.missing_warning_count ? "warning" : "success", "권장 산출물", null, source)}
      </div>
      ${checklistHtml}
      ${missing.length ? `
        <div class="run-evidence-list">
          ${missing.slice(0, 6).map((item) => renderRunEvidenceItem(item, source)).join("")}
        </div>
      ` : `
        <div class="timeline-empty">
          <strong>필수 증거 누락 없음</strong>
          <span>현재 run은 운영 판단에 필요한 핵심 산출물을 갖추고 있습니다.</span>
        </div>
      `}
      ${renderSourceCaption(source)}
    </section>
  `;
}

function renderRunEvidenceItem(item, fallbackSource) {
  return `
    <article class="run-evidence-item severity-${escapeHtml(item.severity || "warning")}">
      <div class="run-evidence-item-head">
        <div>
          <strong>${escapeHtml(item.label || item.id)}</strong>
          <span>${escapeHtml(item.path || "-")}</span>
        </div>
        ${statusBadge(item.status || "not_evaluated")}
      </div>
      <p>${escapeHtml(item.detail || "")}</p>
      ${(item.alternatives || []).length > 1 ? `<div class="run-evidence-paths">${item.alternatives.map((path) => `<span>${escapeHtml(path)}</span>`).join("")}</div>` : ""}
      ${renderSourceLabel(item.source || fallbackSource)}
    </article>
  `;
}

function renderFailurePatternOverview(patterns) {
  const data = patterns || {};
  const summary = data.summary || {};
  const source = data.source || summary.source || "failure_patterns.json";
  if (!summary.run_count) return "";
  const activeCode = summary.active_streak_code || summary.latest_failure_code || "-";
  const patternRows = (data.patterns || []).slice(0, 3);
  return `
    <section class="failure-pattern-section status-${statusClass(data.status || "not_evaluated")}" aria-label="반복 실패 패턴">
      <div class="failure-pattern-head">
        <div>
          <h2>반복 실패 패턴</h2>
          <p>최근 실행에서 같은 차단 코드가 반복되는지 확인합니다.</p>
        </div>
        <button class="button button-secondary" type="button" data-go="run-history">이력 상세</button>
      </div>
      <div class="failure-pattern-summary">
        ${metricCard("반복 실패", formatNumber(summary.repeated_code_count || 0, 0), summary.repeated_code_count ? "warning" : "success", `최근 ${formatNumber(summary.run_count || 0, 0)}회`, null, source)}
        ${metricCard("연속 차단", formatNumber(summary.active_streak_count || 0, 0), summary.active_streak_count >= 2 ? "blocked" : summary.active_streak_count ? "warning" : "success", activeCode, null, source)}
        ${metricCard("실패 실행", formatNumber(summary.failed_run_count || 0, 0), summary.failed_run_count ? "warning" : "success", "failed/error 상태", null, source)}
        ${metricCard("최다 코드", summary.top_code || "-", summary.top_code ? "warning" : "success", `${formatNumber(summary.top_code_count || 0, 0)}회`, null, source)}
      </div>
      ${patternRows.length ? `
        <div class="failure-pattern-list">
          ${patternRows.map((item) => renderFailurePatternItem(item, source)).join("")}
        </div>
      ` : `
        <div class="timeline-empty">
          <strong>반복 차단 없음</strong>
          <span>최근 완료 run에서 반복 실패 코드가 감지되지 않았습니다.</span>
        </div>
      `}
      ${renderSourceCaption(source)}
    </section>
  `;
}

function renderFailurePatternItem(item, fallbackSource) {
  const action = item.action || {};
  return `
    <article class="failure-pattern-item severity-${escapeHtml(item.severity || "warning")}">
      <div class="failure-pattern-item-head">
        <div>
          <strong>${escapeHtml(item.code || "UNKNOWN")}</strong>
          <span>${formatNumber(item.count || 0, 0)}회 · 최근 ${escapeHtml(formatDate(item.last_seen_at))}</span>
        </div>
        ${statusBadge(item.severity === "blocked" ? "blocked" : "warning")}
      </div>
      <p>${escapeHtml(action.detail || "manifest와 safety_verdict의 failure_code를 확인하세요.")}</p>
      <div class="failure-pattern-meta">
        ${(item.run_ids || []).slice(0, 5).map((runId) => `<span>${escapeHtml(runId)}</span>`).join("")}
      </div>
      ${action.page ? `<button class="button button-secondary" type="button" data-go="${escapeHtml(action.page)}">${escapeHtml(action.label || "상세 확인")}</button>` : ""}
      ${renderSourceLabel(item.source || fallbackSource)}
    </article>
  `;
}

function renderSessionReplay(replay) {
  const data = replay || {};
  const summary = data.summary || {};
  const events = data.events || [];
  const artifacts = data.artifacts || [];
  const source = data.source || summary.source || "state/session_replay.json";
  const status = data.status || "not_evaluated";
  const eventHtml = events.length ? events.map((event) => `
    <article class="session-replay-event status-${statusClass(event.status || "not_evaluated")}">
      <div class="session-replay-marker">${escapeHtml(event.step || "")}</div>
      <div class="session-replay-main">
        <div class="session-replay-title">
          <strong>${escapeHtml(event.title || "세션 단계")}</strong>
          ${statusBadge(event.status || "not_evaluated")}
        </div>
        <p>${escapeHtml(event.summary || "")}</p>
        ${(event.details || []).length ? `<div class="session-replay-details">${event.details.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
        ${(event.artifacts || []).length ? `<div class="session-replay-artifacts">${event.artifacts.map((artifact) => `
          <span class="${artifact.exists ? "exists" : "missing"}">${escapeHtml(artifact.path || artifact.source || "-")}</span>
        `).join("")}</div>` : ""}
        ${renderSourceLabel(event.source || source)}
      </div>
    </article>
  `).join("") : `
    <div class="timeline-empty">
      <strong>투자 세션 리플레이 없음</strong>
      <span>완료된 run의 manifest와 산출물이 생기면 실행 흐름을 재생합니다.</span>
    </div>
  `;
  return `
    <section class="session-replay-section" aria-label="투자 세션 리플레이">
      <div class="session-replay-head">
        <div>
          <h2>투자 세션 리플레이</h2>
          <p>한 번의 실행이 어떤 단계와 산출물을 거쳐 오늘 결론으로 이어졌는지 복기합니다.</p>
        </div>
        ${statusBadge(status, `${formatNumber(summary.step_count || events.length || 0, 0)}단계`)}
      </div>
      <div class="session-replay-summary">
        ${metricCard("성공 단계", formatNumber(summary.success_count || 0, 0), summary.success_count ? "success" : "not_evaluated", `전체 ${formatNumber(summary.step_count || events.length || 0, 0)}`, null, source)}
        ${metricCard("경고 단계", formatNumber(summary.warning_count || 0, 0), summary.warning_count ? "warning" : "success", "review needed", null, source)}
        ${metricCard("차단 단계", formatNumber(summary.blocked_count || 0, 0), summary.blocked_count ? "blocked" : "success", "blocked/data error", null, source)}
        ${metricCard("증거 파일", formatNumber(summary.artifact_count || artifacts.length || 0, 0), artifacts.length ? "success" : "not_evaluated", "artifact index", null, source)}
      </div>
      <div class="session-replay-list">${eventHtml}</div>
      ${renderSourceCaption(source)}
    </section>
  `;
}

function renderRecoveryGuide(guide) {
  const data = guide || {};
  const summary = data.summary || {};
  const items = data.items || [];
  const source = data.source || summary.source || "state/recovery_guide.json";
  const status = data.status || "success";
  if (!items.length) {
    return `
      <section class="recovery-guide-section status-${statusClass(status)}">
        <div class="recovery-guide-head">
          <div>
            <h2>실패 복구 가이드</h2>
            <p>현재 차단된 실패 코드가 없어 추가 복구 단계가 없습니다.</p>
          </div>
          ${statusBadge("success", "정상")}
        </div>
        ${renderSourceCaption(source)}
      </section>
    `;
  }
  return `
    <section class="recovery-guide-section status-${statusClass(status)}" aria-label="실패 복구 가이드">
      <div class="recovery-guide-head">
        <div>
          <h2>실패 복구 가이드</h2>
          <p>실패 코드별 원인, 확인 파일, 다시 검증할 명령을 순서대로 정리합니다.</p>
        </div>
        ${statusBadge(status, `${formatNumber(summary.issue_count || items.length, 0)}건`)}
      </div>
      <div class="recovery-guide-summary">
        ${metricCard("차단 복구", formatNumber(summary.blocked_count || 0, 0), summary.blocked_count ? "blocked" : "success", "blocked severity", null, source)}
        ${metricCard("주의 복구", formatNumber(summary.warning_count || 0, 0), summary.warning_count ? "warning" : "success", "warning severity", null, source)}
        ${metricCard("최우선 코드", summary.top_code || "-", status, "가장 먼저 볼 항목", null, source)}
      </div>
      <div class="recovery-guide-list">
        ${items.slice(0, 6).map((item, index) => `
          <article class="recovery-guide-card severity-${escapeHtml(item.severity || "warning")}">
            <div class="recovery-guide-card-head">
              <div>
                <span class="code">${escapeHtml(item.code || "UNKNOWN")}</span>
                <strong>${formatNumber(index + 1, 0)}. ${escapeHtml(item.title || "복구 확인")}</strong>
              </div>
              ${statusBadge(item.severity === "blocked" ? "blocked" : "warning", item.severity || "warning")}
            </div>
            <p>${escapeHtml(item.diagnosis || item.message || "")}</p>
            <div class="recovery-guide-columns">
              <div>
                <b>복구 단계</b>
                <ol>${(item.steps || []).map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>
                ${renderSourceCaption(item.source || source)}
              </div>
              <div>
                <b>확인 산출물</b>
                <div class="recovery-guide-artifacts">
                  ${(item.artifacts || []).map((artifact) => `<span>${escapeHtml(artifact)}</span>`).join("") || "<span>manifest.json</span>"}
                </div>
                ${(item.commands || []).length ? `
                  <b>검증 명령</b>
                  <div class="recovery-guide-commands">
                    ${item.commands.map((command) => `<button class="button button-secondary" type="button" data-command="${escapeHtml(command)}">${escapeHtml(command)}</button>`).join("")}
                  </div>
                ` : ""}
                ${(item.verification || []).length ? `
                  <b>완료 확인</b>
                  <ul>${item.verification.map((check) => `<li>${escapeHtml(check)}</li>`).join("")}</ul>
                ` : ""}
              </div>
            </div>
          </article>
        `).join("")}
      </div>
      ${renderSourceCaption(source)}
    </section>
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
      <thead><tr><th>종목</th><th>종목명</th><th>상태</th><th>행동</th><th>전략</th><th class="numeric">점수</th><th class="numeric">진입가</th><th>데이터</th><th>Reason code</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${renderTicker(row.ticker)}</td>
          <td><span style="font-size:11.5px;color:var(--muted);">${escapeHtml(getStockName(row.ticker))}${renderSecurityBadge(row.ticker)}</span></td>
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

// Shadow 승격 화면 렌더링 (Overview 근처 화면이므로 overview.js에 통합)
function renderPromotion() {
  const data = state.promotion;
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>Shadow 승격 심사</h1>
        <p>Shadow 모드 실행 기록을 기반으로 실거래(Production) 모드 승격 조건을 달성했는지 평가합니다.</p>
      </div>
      ${statusBadge(data.overall_status)}
    </div>
    ${renderDataSourceNote("promotion")}
    <section class="decision-grid">
      <article class="decision-card status-${statusClass(data.overall_status)}">
        <div class="decision-eyebrow">${statusBadge(data.overall_status)} <span>Shadow Audit</span></div>
        <h2>${data.eligible ? "승격 요건 충족" : "승격 대기 중"}</h2>
        <p>${escapeHtml(data.headline || "")}</p>
        <div class="decision-meta">
          <span>누적 실행 ${formatNumber(data.metrics?.shadow_day_count, 0)}일</span>
          <span>신호 안정성 ${formatNumber(data.metrics?.signal_stability_score, 0)}점</span>
        </div>
      </article>
    </section>
    <section class="metric-grid">
      ${metricCard("Shadow 일수", `${data.metrics?.shadow_day_count ?? 0}일`, data.gates?.shadow_days?.status, `기준 ${data.gates?.shadow_days?.limit ?? 0}일 이상`)}
      ${metricCard("완료 신호", `${data.metrics?.completed_run_count ?? 0}회`, data.gates?.completed_runs?.status, `기준 ${data.gates?.completed_runs?.limit ?? 0}회 이상`)}
      ${metricCard("데이터 성공률", formatPercent(data.metrics?.data_success_rate), data.gates?.data_success?.status, `기준 ${formatPercent(data.gates?.data_success?.limit)} 이상`)}
      ${metricCard("불일치율", formatPercent(data.metrics?.disagreement_rate), data.gates?.disagreement?.status, `기준 ${formatPercent(data.gates?.disagreement?.limit)} 이하`)}
      ${metricCard("리스크 통과율", formatPercent(data.metrics?.risk_pass_rate), data.gates?.risk_pass?.status, `기준 ${formatPercent(data.gates?.risk_pass?.limit)} 이상`)}
      ${metricCard("신호 안정성", `${data.metrics?.signal_stability_score ?? 0}점`, data.gates?.signal_stability?.status, `기준 ${data.gates?.signal_stability?.limit ?? 0}점 이상`)}
    </section>
    ${renderMetricDictionaryStrip(data.metric_dictionary?.promotion, "승격 조건 쉬운 설명")}
  `;
}

function renderDecisionDiffCard(diff) {
  if (!diff) return "";
  const isChanged = diff.overall_changed;
  const badgeClass = isChanged ? "status-warning" : "status-success";
  
  let blockersHtml = "";
  if (diff.blockers && diff.blockers.changed) {
    if (diff.blockers.added && diff.blockers.added.length) {
      blockersHtml += `<span class="badge badge-error" style="background: #f43f5e; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; margin-right: 4px;">추가 차단: ${diff.blockers.added.join(", ")}</span> `;
    }
    if (diff.blockers.removed && diff.blockers.removed.length) {
      blockersHtml += `<span class="badge badge-success" style="background: #10b981; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; margin-right: 4px;">해제 차단: ${diff.blockers.removed.join(", ")}</span> `;
    }
  }
  
  let tickersHtml = "";
  if (diff.affected_tickers && diff.affected_tickers.changed) {
    if (diff.affected_tickers.added && diff.affected_tickers.added.length) {
      tickersHtml += `<span class="badge badge-info" style="background: #3b82f6; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; margin-right: 4px;">추가 신호: ${diff.affected_tickers.added.join(", ")}</span> `;
    }
    if (diff.affected_tickers.removed && diff.affected_tickers.removed.length) {
      tickersHtml += `<span class="badge badge-muted" style="background: #64748b; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; margin-right: 4px;">제외 신호: ${diff.affected_tickers.removed.join(", ")}</span> `;
    }
  }

  return `
    <section class="panel decision-diff-card" style="margin-top: 1rem; border-left: 5px solid ${isChanged ? "#f59e0b" : "#10b981"};">
      <div class="panel-header">
        <div>
          <h2 style="font-size: 1.2rem; margin: 0;">오늘의 판단 변화 (Decision Diff)</h2>
          <p style="margin: 4px 0 0 0; font-size: 0.9rem; color: var(--muted);">
            이전 실행(<strong>${diff.left_run_id || "없음"}</strong>) 대비 오늘 실행(<strong>${diff.right_run_id || "없음"}</strong>)의 의사결정 변화 내역입니다.
          </p>
        </div>
        <span class="badge ${badgeClass}" style="padding: 4px 10px; border-radius: 12px; font-size: 0.8rem;">${isChanged ? "변화 감지됨" : "동일 유지"}</span>
      </div>
      <div class="panel-body" style="padding: 1rem 0 0 0;">
        <div class="diff-summary-box" style="background: var(--surface-subtle); border: 1px solid var(--border); padding: 1rem; border-radius: 6px;">
          <p style="font-size: 1rem; line-height: 1.5; margin: 0 0 0.5rem 0; color: var(--text);">
            <strong>판결 흐름:</strong> 
            <code style="background: var(--neutral-bg); border: 1px solid var(--border); padding: 2px 6px; border-radius: 4px; color: var(--text);">${diff.left_status || "N/A"}</code> 
            ➔ 
            <code style="background: rgba(244,63,94,0.1); padding: 2px 6px; border-radius: 4px; color: #f43f5e; font-weight: bold;">${diff.right_status || "N/A"}</code>
          </p>
          <p style="margin: 0; line-height: 1.6; color: var(--text); font-size: 0.95rem;">${escapeHtml(diff.explanation || "")}</p>
        </div>
        
        ${blockersHtml || tickersHtml ? `
          <div style="margin-top: 1rem; display: flex; flex-wrap: wrap; gap: 0.5rem;">
            ${blockersHtml}
            ${tickersHtml}
          </div>
        ` : ""}
        
        <div style="margin-top: 1rem; padding-top: 0.8rem; border-top: 1px dashed var(--border);">
          <p style="margin: 0; font-size: 0.9rem; color: var(--muted);">
            <strong>💡 대응 권장 조치:</strong> <span style="color: var(--text); font-weight: 600;">${escapeHtml(diff.recommended_action?.text || "")}</span>
          </p>
        </div>
      </div>
    </section>
  `;
}

function renderRoutineScheduler(routines) {
  if (!routines || !routines.routines) return "";
  const list = Object.values(routines.routines);
  return `
    <section class="panel routine-scheduler-section" style="margin-top: 1.5rem;">
      <div class="panel-header">
        <div>
          <h2 style="font-size: 1.2rem; margin: 0; color: var(--accent);">⏳ 오늘의 투자 루틴 스케줄러</h2>
          <p style="margin: 4px 0 0 0; font-size: 0.9rem; color: var(--muted);">개인 투자 운영 OS로서 매일 확인해야 할 장전, 장중, 장후 필수 점검 사항과 실행 명령 가이드입니다.</p>
        </div>
      </div>
      <div class="panel-body" style="padding: 1rem 0 0 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem;">
        ${list.map(r => `
          <article class="routine-card" style="background: var(--surface-subtle); padding: 1rem; border-radius: 8px; border: 1px solid var(--border); display: flex; flex-direction: column; justify-content: space-between;">
            <div>
              <strong style="font-size: 1rem; color: var(--text); display: block; margin-bottom: 0.5rem; font-weight: 700;">${escapeHtml(r.title)}</strong>
              <p style="font-size: 0.8rem; color: var(--muted); margin-bottom: 0.8rem; line-height: 1.4;">${escapeHtml(r.description)}</p>
              
              <div class="routine-tasks" style="margin-bottom: 0.8rem;">
                ${r.tasks.map(t => `
                  <div style="display: flex; align-items: flex-start; gap: 6px; font-size: 0.75rem; margin-bottom: 6px; line-height: 1.3;">
                     <span style="color: ${t.completed ? '#10b981' : '#f59e0b'}; font-weight: bold; font-size: 0.85rem;">${t.completed ? '✓' : '⏳'}</span>
                    <span style="color: var(--text);">${escapeHtml(t.label)}</span>
                  </div>
                `).join("")}
              </div>
            </div>
            
            ${r.commands && r.commands.length ? `
              <div class="routine-commands" style="display: flex; flex-direction: column; gap: 4px; border-top: 1px dashed var(--border); padding-top: 0.5rem; margin-top: auto;">
                ${r.commands.map(cmd => `
                  <button class="button button-secondary" type="button" data-command="${escapeHtml(cmd.command)}" style="padding: 4px 8px; font-size: 0.7rem; text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; width: 100%;">
                    📋 ${escapeHtml(cmd.label)}
                  </button>
                `).join("")}
              </div>
            ` : ""}
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function renderNextCommandRecommendation(recommendation) {
  if (!recommendation) return "";
  return `
    <article class="panel" style="margin-top: 1.5rem; border: 1px solid var(--border); border-left: 4px solid var(--info); background: var(--info-bg);">
      <div class="panel-header" style="padding-bottom: 0.5rem; border-bottom: 1px dashed var(--border);">
        <div>
          <h2 style="font-size: 1.1rem; margin: 0; color: var(--info); display: flex; align-items: center; gap: 8px;">
            <span>🤖 AI 후속 CLI 명령 추천</span>
          </h2>
          <p style="margin: 4px 0 0 0; font-size: 0.85rem; color: var(--muted);">현재 시스템 상태 및 운용 성과를 토대로 제안되는 다음 행동입니다.</p>
        </div>
        <span class="status-label status-success" style="font-size: 0.75rem; padding: 2px 6px; background: var(--success-bg); color: var(--success); border: 1px solid var(--success); border-radius: 4px;">한국어 가이드</span>
      </div>
      <div class="panel-body" style="padding-top: 1rem; display: flex; flex-direction: column; gap: 12px;">
        <div style="background: var(--neutral-bg); color: var(--accent); padding: 12px 16px; border-radius: 6px; font-family: monospace; font-size: 0.85rem; display: flex; justify-content: space-between; align-items: center; border: 1px solid var(--border);">
          <span id="recommended-cli-command" style="word-break: break-all;">${escapeHtml(recommendation.command)}</span>
          <button class="button button-secondary" style="font-size: 0.75rem; padding: 4px 8px; border-color: var(--border); color: var(--text); background: var(--surface); cursor: pointer; white-space: nowrap; margin-left: 8px;" 
            type="button" onclick="navigator.clipboard.writeText(document.getElementById('recommended-cli-command').textContent); alert('명령어가 클립보드에 복사되었습니다.');">
            📋 복사
          </button>
        </div>
        <div style="font-size: 0.85rem; color: var(--text); line-height: 1.5;">
          <p style="margin: 0 0 4px 0;"><strong>이유:</strong> ${escapeHtml(recommendation.reason)}</p>
          <p style="margin: 0;"><strong>예상 결과:</strong> ${escapeHtml(recommendation.expected_result)}</p>
        </div>
      </div>
    </article>
  `;
}
