function findLastDecision(runId, ticker, action) {
  if (!state.approvalHistory?.history) return null;
  return state.approvalHistory.history.find(
    (item) =>
      item.run_id === runId &&
      item.ticker.toUpperCase() === ticker.toUpperCase() &&
      item.action.toLowerCase() === action.toLowerCase()
  );
}

function renderApprovalAuditHistoryPanel(history) {
  const rows = history || [];
  if (!rows.length) {
    return `
      <section class="panel">
        <div class="panel-header">
          <div><h2>의사결정 감사 장부 (Approval Audit Ledger)</h2><p>사용자가 승인, 보류, 무시 처리한 감사 로그 이력입니다.</p></div>
        </div>
        <div class="panel-body">
          <div class="empty-state">감사 로그 기록이 없습니다. 신호에 대해 의사결정을 내려주세요.</div>
        </div>
      </section>
    `;
  }
  return `
    <section class="panel">
      <div class="panel-header">
        <div><h2>의사결정 감사 장부 (Approval Audit Ledger)</h2><p>사용자가 승인, 보류, 무시 처리한 감사 로그 이력입니다.</p></div>
        <span class="muted">${rows.length}건</span>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>일시</th><th>실행 ID</th><th>종목</th><th>행동</th><th>추천 상태</th><th>결정</th><th>의사결정 사유</th></tr></thead>
        <tbody>${rows.map((row) => `
          <tr>
            <td>${formatDate(row.timestamp)}</td>
            <td class="code">${escapeHtml(row.run_id)}</td>
            <td class="ticker-cell">${renderTicker(row.ticker)}</td>
            <td>${escapeHtml(row.action)}</td>
            <td>${statusBadge(row.recommendation_verdict)}</td>
            <td>${statusBadge(row.user_decision === "approve" ? "success" : row.user_decision === "hold" ? "warning" : "not_evaluated", row.user_decision === "approve" ? "승인" : row.user_decision === "hold" ? "보류" : "무시")}</td>
            <td>${escapeHtml(row.rationale || "-")}</td>
          </tr>`).join("")}</tbody>
      </table></div>
    </section>
  `;
}

function renderSignals() {
  const data = state.signals;
  
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>투자 신호 명세</h1>
        <p>전체 전략에서 발생한 개별 매수·매도 신호의 상태, 진입 가격, 유동성 및 통과 여부를 검토합니다.</p>
      </div>
      ${statusBadge(data.rows?.length ? "success" : "not_evaluated")}
    </div>
    ${renderDataSourceNote("signals")}
    ${renderOrderHistorySummaryPanel(state.orderHistorySummary, "signals")}
    <section class="panel">
      <div class="panel-header">
        <div><h2>전체 투자 신호 상세 (All Signals)</h2><p>선택한 실행(Run)에서 생성된 전체 매수/매도/관망 신호 목록입니다.</p></div>
        <span class="muted">${(data.rows || []).length}건</span>
      </div>
      ${renderSignalDetailTable(data.rows)}
      ${renderSourceCaption("today_signals.json of the selected run")}
    </section>
    ${renderApprovalAuditHistoryPanel(state.approvalHistory?.history)}
    ${renderSignalHistoryCards(data.history)}
    ${renderStockLifecycle(data.lifecycle)}
    ${renderSignalStabilityPanel(data.stability)}
    ${renderSignalOutcomePanel(data.outcome)}
    ${renderMetricDictionaryStrip(data.metric_dictionary?.signals, "신호 지표 쉬운 설명")}
  `;
}

function renderTraderLens() {
  const data = state.traderLens;
  const summary = data.summary;
  
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>Trader Lens (트레이더 다차원 렌즈)</h1>
        <p>트레이더 시각에서 오늘 신호의 Risk/Reward 비율, 데이터 제공자 신뢰도, 리스크 집중도를 다차원으로 분석합니다.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    ${renderDataSourceNote("trader-lens")}
    <section class="decision-grid">
      <article class="decision-card status-${statusClass(summary.status)}">
        <div class="decision-eyebrow">${statusBadge(summary.status)} <span>Trader Perspective</span></div>
        <h2>트레이더 종합 진단</h2>
        <p>${escapeHtml(traderLensHeadline(summary))}</p>
        <div class="decision-meta">
          <span>Avg Reward/Risk ${formatNumber(summary.avg_reward_risk, 2)}R</span>
        </div>
      </article>
    </section>
    <section class="section-grid">
      <section class="panel">
        <div class="panel-header">
          <div><h2>의사결정 보조 노트 (Blocker Notes)</h2><p>오늘 실행 VERDICT를 뒤흔든 핵심 차단 사유입니다.</p></div>
          <span class="muted">${(data.verdict_notes || []).length}건</span>
        </div>
        <div class="panel-body">
          ${renderTraderDecisionNotes(data.verdict_notes || [])}
          ${renderSourceCaption("safety_verdict.json inside selected run")}
        </div>
      </section>
      <section class="panel">
        <div class="panel-header">
          <div><h2>리스크 오차 집중도 (Risk Concentration)</h2><p>차단된 리스크 코드가 특정 종목에 얼마나 많이 집중되었는지 보여줍니다.</p></div>
          <span class="muted">${(data.risk_concentration || []).length}건</span>
        </div>
        <div class="panel-body">
          ${renderRiskConcentration(data.risk_concentration || [])}
          ${renderSourceCaption("risk_explanation.json inside selected run")}
        </div>
      </section>
    </section>
    <section class="panel">
      <div class="panel-header">
        <div><h2>R/R 사다리 (Reward to Risk Ladder)</h2><p>기대 수익 대비 감수 위험 비율이 높은 순서로 정렬된 종목 목록입니다.</p></div>
        <span class="muted">${(data.signals || []).length}건</span>
      </div>
      ${renderTraderSignalLadder(data.signals)}
      ${renderSourceCaption("today_signals.json of the selected run")}
    </section>
    <section class="panel">
      <div class="panel-header">
        <div><h2>제공처 신뢰도 맵 (Provider Trust Map)</h2><p>데이터 제공자(Yahoo, Tiingo, Massive)별 데이터 수집 무결성 스코어입니다.</p></div>
        <span class="muted">${(data.providers || []).length}건</span>
      </div>
      ${renderProviderTrustMap(data.providers)}
      ${renderSourceCaption("data_sources.json and provider_disagreement_report.json")}
    </section>
  `;
}

function renderSignalDetailTable(rows) {
  if (!rows?.length) return emptyTable("선택한 run의 신호가 없습니다.", "run-local signal artifact가 없습니다. 전역 today_signals.json은 run 검토에 섞지 않습니다.");
  const runId = state.signals?.run_id || state.runId;
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>종목</th><th>상태</th><th>행동</th><th>전략</th><th class="numeric">점수</th><th class="numeric">진입가</th><th class="numeric">손절가</th><th class="numeric">목표가</th><th class="numeric">승인 비중</th><th>유동성</th><th>데이터</th><th>Reason code</th><th>의사결정</th></tr></thead>
      <tbody>${rows.map((row) => {
        const decision = findLastDecision(runId, row.ticker, row.action);
        let decisionHtml = "";
        if (decision) {
          const badgeType = decision.user_decision === "approve" ? "success" : decision.user_decision === "hold" ? "warning" : "not_evaluated";
          const label = decision.user_decision === "approve" ? "승인됨" : decision.user_decision === "hold" ? "보류됨" : "무시됨";
          decisionHtml = `
            <div class="decision-status-cell">
              ${statusBadge(badgeType, label)}
              ${decision.rationale ? `<small class="decision-rationale" title="${escapeHtml(decision.rationale)}">${escapeHtml(decision.rationale)}</small>` : ""}
              <button class="btn-change-decision" data-ticker="${escapeHtml(row.ticker)}" data-action="${escapeHtml(row.action)}" data-run-id="${escapeHtml(runId)}" data-rec-verdict="${escapeHtml(row.status)}">변경</button>
            </div>
          `;
        } else {
          decisionHtml = `
            <div class="decision-buttons-cell">
              <button class="btn-decide btn-decide-approve" data-decision="approve" data-ticker="${escapeHtml(row.ticker)}" data-action="${escapeHtml(row.action)}" data-run-id="${escapeHtml(runId)}" data-rec-verdict="${escapeHtml(row.status)}">승인</button>
              <button class="btn-decide btn-decide-hold" data-decision="hold" data-ticker="${escapeHtml(row.ticker)}" data-action="${escapeHtml(row.action)}" data-run-id="${escapeHtml(runId)}" data-rec-verdict="${escapeHtml(row.status)}">보류</button>
              <button class="btn-decide btn-decide-ignore" data-decision="ignore" data-ticker="${escapeHtml(row.ticker)}" data-action="${escapeHtml(row.action)}" data-run-id="${escapeHtml(runId)}" data-rec-verdict="${escapeHtml(row.status)}">무시</button>
            </div>
          `;
        }
        return `
        <tr>
          <td class="ticker-cell">${renderTicker(row.ticker)}</td>
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
          <td>${decisionHtml}</td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>`;
}

function renderTraderSignalLadder(rows) {
  if (!rows?.length) return emptyTable("No signal rows found.", "Run-local signals are required before Trader Lens can score reward/risk.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Ticker</th><th>Status</th><th class="numeric">R/R</th><th class="numeric">Risk</th><th class="numeric">Reward</th><th class="numeric">Entry</th><th class="numeric">Stop</th><th class="numeric">Target</th><th>Data</th><th>Reason code</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${renderTicker(row.ticker)}</td>
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
          <td class="ticker-cell">${renderTicker(row.ticker)}</td>
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

function renderSignalHistoryCards(history) {
  const data = history || {};
  const cards = data.cards || [];
  const source = data.source || "runs/*/manifest.json · signals_risk.json";
  const cardsHtml = cards.length ? cards.map((card) => {
    const seven = card.windows?.["7d"] || {};
    const thirty = card.windows?.["30d"] || {};
    const changes = (card.changes || []).slice(-3);
    const recent = (card.recent || []).slice(-4);
    const failedCodes = card.latest_failed_codes || [];
    const reasonCodes = card.latest_reason_codes || [];
    return `
      <article class="signal-history-card status-${statusClass(card.status || "not_evaluated")}">
        <div class="signal-history-head">
          <div>
            <strong>${renderTicker(card.ticker)}</strong>
            <span>${escapeHtml(card.latest_action_label || card.latest_action || "판단 없음")}</span>
          </div>
          ${statusBadge(signalTrendStatus(card.trend), signalTrendLabel(card.trend))}
        </div>
        <p>${escapeHtml(card.summary || "")}</p>
        <div class="signal-history-windows">
          ${renderSignalHistoryWindow("최근 7일", seven)}
          ${renderSignalHistoryWindow("최근 30일", thirty)}
        </div>
        ${changes.length ? `
          <div class="signal-history-changes">
            ${changes.map((change) => `
              <div>
                <strong>${escapeHtml(formatDate(change.occurred_at))}</strong>
                <span>${escapeHtml(change.summary || "")}</span>
              </div>
            `).join("")}
          </div>` : `<div class="signal-history-empty">최근 변화 이벤트가 없습니다.</div>`}
        ${(failedCodes.length || reasonCodes.length) ? `
          <div class="signal-history-tags">
            ${failedCodes.map((code) => `<span class="is-failed">${escapeHtml(code)}</span>`).join("")}
            ${reasonCodes.map((code) => `<span>${escapeHtml(code)}</span>`).join("")}
          </div>` : ""}
        ${recent.length ? `
          <div class="signal-history-recent">
            ${recent.map((item) => `<span title="${escapeHtml(item.run_id || "")}">${escapeHtml(item.action_label || item.action || "-")} · ${escapeHtml(item.status || "-")}</span>`).join("")}
          </div>` : ""}
        ${renderSourceLabel(card.source || source)}
      </article>
    `;
  }).join("") : `
    <div class="signal-history-empty">
      <strong>종목별 판단 이력 없음</strong>
      <span>최근 run의 signals_risk.json이 쌓이면 7일·30일 판단 흐름이 표시됩니다.</span>
    </div>
  `;
  return `
    <section class="signal-history-section" aria-label="종목별 판단 이력">
      <div class="signal-history-section-head">
        <div>
          <h2>종목별 판단 이력</h2>
          <p>${escapeHtml(data.summary || "최근 실행 기준으로 종목별 판단 변화를 요약합니다.")}</p>
        </div>
        ${statusBadge(data.status || "not_evaluated")}
      </div>
      <div class="signal-history-grid">${cardsHtml}</div>
      ${renderSourceCaption(source)}
    </section>
  `;
}

function renderSignalHistoryWindow(label, windowData) {
  return `
    <div class="signal-history-window">
      <span>${escapeHtml(label)}</span>
      <strong>${formatNumber(windowData.run_count || 0, 0)}회</strong>
      <small>매수 ${formatNumber(windowData.buy_count || 0, 0)} · 운영가능 ${formatNumber(windowData.eligible_count || 0, 0)} · 차단 ${formatNumber(windowData.blocked_count || 0, 0)}</small>
    </div>
  `;
}

function renderStockLifecycle(lifecycle) {
  const data = lifecycle || {};
  const summary = data.summary || {};
  const items = data.items || [];
  const counts = summary.status_counts || {};
  const source = data.source || "state/stock_lifecycle.json · signals_risk.json";
  const stateOrder = ["caution", "reduce", "candidate", "holding", "watch", "excluded"];
  const stateLabels = {
    watch: "관심",
    candidate: "후보",
    holding: "보유",
    caution: "경고",
    reduce: "축소",
    excluded: "제외",
  };
  const itemHtml = items.length ? items.slice(0, 12).map((item) => `
    <article class="stock-lifecycle-card state-${escapeHtml(item.status || "watch")}">
      <div class="stock-lifecycle-card-head">
        <div>
          <strong>${renderTicker(item.ticker)}</strong>
          <span>${escapeHtml(item.status_label || item.status || "-")}</span>
        </div>
        ${statusBadge(stockLifecycleStatus(item.status), item.status_label || item.status || "-")}
      </div>
      <p>${escapeHtml(item.transition_reason || "")}</p>
      <div class="stock-lifecycle-meta">
        <span>이전 ${escapeHtml(item.previous_status_label || "-")}</span>
        <span>유지 ${item.days_in_status == null ? "-" : `${formatNumber(item.days_in_status, 0)}일`}</span>
        <span>신호 ${escapeHtml(item.related_signal || "-")}</span>
      </div>
      ${(item.related_risk_codes || []).length ? `<div class="signal-history-tags">${item.related_risk_codes.map((code) => `<span class="is-failed">${escapeHtml(code)}</span>`).join("")}</div>` : ""}
      <div class="stock-lifecycle-action">${escapeHtml(item.recommended_action || "")}</div>
      ${renderSourceLabel(item.source || source)}
    </article>
  `).join("") : `
    <div class="stock-lifecycle-empty">
      <strong>종목 상태 없음</strong>
      <span>jayu report stock-lifecycle 실행 후 관심, 후보, 보유, 경고, 축소, 제외 상태가 표시됩니다.</span>
    </div>
  `;
  return `
    <section class="stock-lifecycle-section" aria-label="종목 상태 머신">
      <div class="stock-lifecycle-head">
        <div>
          <h2>종목 상태 머신</h2>
          <p>신호와 리스크 상태를 종목 생애주기 상태로 바꾸고 전환 사유를 추적합니다.</p>
        </div>
        ${statusBadge(data.status || "not_evaluated")}
      </div>
      <div class="stock-lifecycle-counts">
        ${stateOrder.map((state) => `
          <div>
            <span>${escapeHtml(stateLabels[state] || state)}</span>
            <strong>${formatNumber(counts[state] || 0, 0)}</strong>
          </div>
        `).join("")}
      </div>
      <div class="stock-lifecycle-grid">${itemHtml}</div>
      ${renderSourceCaption(source)}
    </section>
  `;
}

function stockLifecycleStatus(status) {
  return {
    candidate: "success",
    holding: "success",
    caution: "warning",
    reduce: "warning",
    excluded: "blocked",
    watch: "not_evaluated",
  }[status] || "not_evaluated";
}

function renderSignalStabilityPanel(stability) {
  const data = stability || {};
  const summary = data.summary || {};
  const items = data.items || [];
  const source = data.source || "runs/*/manifest.json · signals_risk.json";
  const cards = items.length ? items.slice(0, 12).map((item) => `
    <article class="signal-stability-card status-${statusClass(signalStabilityStatus(item.status))}">
      <div class="signal-stability-card-head">
        <div>
          <strong>${renderTicker(item.ticker)}</strong>
          <span>${escapeHtml(item.latest_signal_label || item.latest_signal_state || "-")}</span>
        </div>
        ${statusBadge(signalStabilityStatus(item.status), signalStabilityLabel(item.status))}
      </div>
      <div class="signal-stability-score">
        <strong>${item.signal_stability_score == null ? "-" : formatNumber(item.signal_stability_score, 0)}</strong>
        <span>10일 안정성 점수</span>
      </div>
      <div class="signal-stability-windows">
        ${["5d", "10d", "20d"].map((key) => {
          const stat = item.windows?.[key] || {};
          return `
            <div>
              <span>${escapeHtml(key.toUpperCase())}</span>
              <strong>${stat.score == null ? "-" : formatNumber(stat.score, 0)}</strong>
              <small>전환 ${formatNumber(stat.transition_count || 0, 0)} · n=${formatNumber(stat.run_count || 0, 0)}</small>
            </div>
          `;
        }).join("")}
      </div>
      <p>${escapeHtml(item.summary || "")}</p>
      ${item.auto_candidate_excluded ? `<div class="signal-stability-exclusion">자동매매 후보 제외</div>` : ""}
      ${renderSourceLabel(item.source || source)}
    </article>
  `).join("") : `
    <div class="signal-stability-empty">
      <strong>신호 안정성 이력 없음</strong>
      <span>최근 runs의 signals_risk.json이 쌓이면 5/10/20일 안정성 점수가 표시됩니다.</span>
    </div>
  `;
  return `
    <section class="signal-stability-section" aria-label="신호 안정성 점수">
      <div class="signal-stability-head">
        <div>
          <h2>신호 안정성 점수</h2>
          <p>최근 5/10/20일 동안 신호가 얼마나 자주 뒤집혔는지 계산하고 불안정 종목을 자동 후보에서 제외합니다.</p>
        </div>
        ${statusBadge(data.status || "not_evaluated")}
      </div>
      <section class="metric-grid signal-stability-metrics">
        ${metricCard("평균 안정성", summary.average_stability_score == null ? "-" : formatNumber(summary.average_stability_score, 0), summary.unstable_count ? "warning" : data.status || "not_evaluated", "10일 기준 평균", null, source)}
        ${metricCard("불안정 종목", summary.unstable_count || 0, summary.unstable_count ? "warning" : "success", "점수 60 미만 또는 5일 2회 이상 전환", null, source)}
        ${metricCard("자동 후보 제외", summary.auto_candidate_excluded_count || 0, summary.auto_candidate_excluded_count ? "blocked" : "success", "불안정 또는 이력 부족", null, source)}
        ${metricCard("평가 종목", summary.ticker_count || 0, summary.ticker_count ? "success" : "not_evaluated", "최근 run 기준", null, source)}
      </section>
      <div class="signal-stability-grid">${cards}</div>
      ${renderSourceCaption(source)}
    </section>
  `;
}

function signalStabilityStatus(status) {
  return {
    stable: "success",
    warning: "warning",
    unstable: "blocked",
    insufficient: "not_evaluated",
  }[status] || "not_evaluated";
}

function signalStabilityLabel(status) {
  return {
    stable: "안정",
    warning: "주의",
    unstable: "불안정",
    insufficient: "이력 부족",
  }[status] || "미검증";
}

function renderSignalOutcomePanel(outcome) {
  const data = outcome || {};
  const summary = data.summary || {};
  const horizonKeys = (data.horizons?.length ? data.horizons : [1, 5, 20]).map((item) => `${item}d`);
  const aggregate = data.aggregate || {};
  const source = data.source || "state/signal_outcome.json";
  const blocked5d = data.blocked_avoidance?.["5d"] || {};
  const groups = data.by_decision_group || [];
  const strategies = (data.by_strategy || []).slice(0, 6);
  const groupsHtml = groups.length ? groups.map((group) => renderSignalOutcomeGroup(group, horizonKeys)).join("") : `
    <div class="signal-outcome-empty">
      <strong>사후 성과 없음</strong>
      <span>jayu report signal-outcome 실행 후 매수 후보, 관망, 차단 신호의 1D/5D/20D 결과가 표시됩니다.</span>
    </div>
  `;
  const strategyHtml = strategies.length ? `
    <div class="signal-outcome-strategy-list">
      ${strategies.map((item) => {
        const five = item.horizons?.["5d"] || {};
        return `
          <div class="signal-outcome-strategy-row">
            <span>${escapeHtml(item.label || item.key || "unknown")}</span>
            <strong>${formatPercent(five.avg_return)}</strong>
            <small>적중 ${formatPercent(five.hit_rate)} · n=${formatNumber(five.sample_count || 0, 0)}</small>
          </div>
        `;
      }).join("")}
    </div>
  ` : `<div class="signal-outcome-empty compact">전략별 표본이 아직 없습니다.</div>`;
  return `
    <section class="signal-outcome-section" aria-label="신호 사후 성과">
      <div class="signal-outcome-head">
        <div>
          <h2>신호 사후 성과</h2>
          <p>매수 후보, 관망, 차단 신호를 실제 1D/5D/20D 수익률로 되돌려 본 결과입니다.</p>
        </div>
        ${statusBadge(data.status || summary.status || "not_evaluated")}
      </div>
      <div class="signal-outcome-metrics">
        ${metricCard("평가 신호", `${formatNumber(summary.evaluated_count || 0, 0)}/${formatNumber(summary.signal_count || 0, 0)}`, data.status || summary.status, "price history matched", null, source)}
        ${metricCard("1D 평균", formatPercent(aggregate["1d"]?.avg_return), outcomeReturnStatus(aggregate["1d"]?.avg_return), `n=${formatNumber(aggregate["1d"]?.sample_count || 0, 0)}`, null, source)}
        ${metricCard("5D 평균", formatPercent(aggregate["5d"]?.avg_return), outcomeReturnStatus(aggregate["5d"]?.avg_return), `적중 ${formatPercent(aggregate["5d"]?.hit_rate)}`, null, source)}
        ${metricCard("차단 회피", formatNumber(blocked5d.avoided_loss_count || 0, 0), blocked5d.avoided_loss_count ? "success" : "not_evaluated", `5D 평균 회피손실 ${formatPercent(blocked5d.avg_avoided_loss)}`, null, source)}
      </div>
      <div class="signal-outcome-grid">${groupsHtml}</div>
      <div class="signal-outcome-strategy">
        <div class="signal-outcome-subhead">
          <strong>전략별 5D 평균</strong>
          <span>표본 수와 적중률 기준</span>
        </div>
        ${strategyHtml}
      </div>
      ${renderSourceCaption(source)}
    </section>
  `;
}

function renderSignalOutcomeGroup(group, horizonKeys) {
  const key = group.key || "unknown";
  const horizons = group.horizons || {};
  const five = horizons["5d"] || {};
  const status = outcomeGroupStatus(key, five.avg_return);
  return `
    <article class="signal-outcome-card status-${statusClass(status)}">
      <div class="signal-outcome-card-head">
        <div>
          <strong>${escapeHtml(group.label || key)}</strong>
          <span>${formatNumber(group.evaluated_count || 0, 0)}/${formatNumber(group.signal_count || 0, 0)} 평가</span>
        </div>
        ${statusBadge(status, signalOutcomeGroupBadge(key, five.avg_return))}
      </div>
      <div class="signal-outcome-horizons">
        ${horizonKeys.map((horizon) => {
          const stats = horizons[horizon] || {};
          return `
            <div class="signal-outcome-horizon">
              <span>${escapeHtml(horizon.toUpperCase())}</span>
              <strong>${formatPercent(stats.avg_return)}</strong>
              <small>적중 ${formatPercent(stats.hit_rate)} · n=${formatNumber(stats.sample_count || 0, 0)}</small>
            </div>
          `;
        }).join("")}
      </div>
    </article>
  `;
}

function outcomeReturnStatus(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "not_evaluated";
  return Number(value) > 0 ? "success" : Number(value) < 0 ? "warning" : "not_evaluated";
}

function outcomeGroupStatus(group, value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "not_evaluated";
  if (group === "blocked_buy") return Number(value) < 0 ? "success" : "warning";
  return outcomeReturnStatus(value);
}

function signalOutcomeGroupBadge(group, value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "대기";
  if (group === "blocked_buy") return Number(value) < 0 ? "차단 유효" : "기회비용";
  return Number(value) > 0 ? "양호" : Number(value) < 0 ? "부진" : "중립";
}

function signalTrendLabel(trend) {
  return {
    improving: "개선",
    deteriorating: "보수 전환",
    changed: "방향 변경",
    stable: "유지",
    insufficient: "이력 부족",
  }[trend] || "확인";
}

function signalTrendStatus(trend) {
  return {
    improving: "success",
    deteriorating: "warning",
    changed: "warning",
    stable: "not_evaluated",
    insufficient: "not_evaluated",
  }[trend] || "not_evaluated";
}
