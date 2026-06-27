function renderRisk() {
  const data = state.risk;
  const summary = data.summary;
  
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>리스크 게이트 심사</h1>
        <p>투자 신호가 포트폴리오 리스크 허용 한도(비중, 금액, 개수 등)를 통과했는지 실시간 대조하고 위험을 통제합니다.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    ${renderDataSourceNote("risk")}
    ${renderOrderHistorySummaryPanel(state.orderHistorySummary, "risk")}
    <section class="decision-grid" aria-label="오늘 결론">
      <article class="decision-card status-${statusClass(summary.status)}">
        <div class="decision-eyebrow">${statusBadge(summary.status)} <span>리스크 및 안전 통제</span></div>
        <h2>투자 신호 심사 결과</h2>
        <p>${escapeHtml(riskHeadline(summary))}</p>
        <div class="decision-meta">
          <span>통과 ${summary.approved_count} / 차단 ${summary.blocked_count} / 보류 ${summary.pending_count}</span>
        </div>
      </article>
    </section>
    <section class="metric-grid" aria-label="리스크 게이트 메트릭">
      ${metricCard("승인 신호", summary.approved_count || 0, "success", "주문 제출 가능 신호")}
      ${metricCard("차단 신호", summary.blocked_count || 0, summary.blocked_count ? "blocked" : "success", "리스크 한도 초과로 기각")}
      ${metricCard("대기", summary.pending_count || 0, "not_evaluated", "추가 승인 검토 필요")}
      ${metricCard("실패 게이트", summary.failed_rule_count || 0, summary.failed_rule_count ? "blocked" : "success", "기준치 위반 룰 수")}
      ${metricCard("최상위 사유", summary.top_reason_code || "없음", summary.blocked_count ? "blocked" : "success", "가장 빈번한 차단 코드")}
      ${metricCard("판정 상태", STATUS_LABELS[summary.status] || summary.status || "미검증", summary.status)}
    </section>
    ${renderMetricDictionaryStrip(data.metric_dictionary?.risk, "리스크 지표 쉬운 설명")}
    <section class="panel">
      <div class="panel-header">
        <div><h2>리스크 규칙 검증 (Rule Violations)</h2><p>포트폴리오 비중, 일간 한도, 현금 비율 등 리스크 규칙별 세부 평가 결과입니다.</p></div>
        <span class="muted">${(data.rules || []).length}건</span>
      </div>
      ${renderRiskChecks(data.rules)}
      ${renderSourceCaption("risk_explanation.json inside latest run")}
    </section>
    <section class="panel">
      <div class="panel-header">
        <div><h2>종목별 심사 결과 (Ticker Risk Details)</h2><p>투자 신호가 발생한 개별 종목이 리스크 통과 및 비중 승인을 얻었는지 보여줍니다.</p></div>
        <span class="muted">${(data.tickers || []).length}건</span>
      </div>
      ${renderRiskSignals(data.tickers)}
      ${renderSourceCaption("signals_risk.json inside latest run")}
    </section>
    <section class="panel" style="margin-top: 1.5rem;">
      ${renderStrategyRiskBudgets(state.strategyBudgets)}
    </section>
    <section class="panel" id="strategy-cards-section" style="margin-top: 1.5rem;"></section>
  `;
}

function renderRiskChecks(rows) {
  if (!rows?.length) return emptyTable("리스크 게이트가 평가되지 않았습니다.", "심사 대상 신호와 portfolio snapshot을 확인하세요.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>상태</th><th>종목</th><th>종목명</th><th>지표</th><th class="numeric">현재값</th><th class="numeric">한도</th><th class="numeric">초과값</th><th>Reason code</th></tr></thead>
      <tbody>${rows.map((row) => {
        const observed = Number(row.observed);
        const limit = Number(row.limit);
        const ratio = Number.isFinite(observed) && Number.isFinite(limit) && limit !== 0 ? Math.abs(observed / limit) : 0;
        return `
        <tr>
          <td>${statusBadge(row.status)}</td>
          <td class="ticker-cell">${renderTicker(row.ticker)}</td>
          <td><span style="font-size:11.5px;color:var(--muted);">${escapeHtml(getStockName(row.ticker))}</span>${renderSecurityBadge(row.ticker)}</td>
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
      <thead><tr><th>종목</th><th>종목명</th><th>행동</th><th>상태</th><th class="numeric">승인 비중</th><th class="numeric">통과</th><th class="numeric">실패</th><th>Reason code</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${renderTicker(row.ticker)}</td>
          <td><span style="font-size:11.5px;color:var(--muted);">${escapeHtml(getStockName(row.ticker))}</span>${renderSecurityBadge(row.ticker)}</td>
          <td>${escapeHtml(row.action || "-")}</td>
          <td>${statusBadge(row.eligible ? "success" : row.reviewed === false ? "not_evaluated" : "blocked")}</td>
          <td class="numeric">${row.approved_position_pct == null ? "미계산" : formatPercent(row.approved_position_pct)}</td>
          <td class="numeric">${(row.passed || []).length}</td>
          <td class="numeric">${(row.failed || []).length}</td>
          <td class="code">${escapeHtml((row.failed || []).map((item) => item.code).filter(Boolean).join(", ") || "-")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderStrategyRiskBudgets(budgetsData) {
  const list = budgetsData?.budgets || [];
  
  let rowsHtml = "";
  if (list.length) {
    rowsHtml = list.map(b => {
      const remainingLoss = b.current_usage.remaining_loss_budget;
      const remainingTrades = b.current_usage.remaining_trade_budget;
      const lossPct = ((b.current_usage.monthly_loss / b.budget_limit.monthly_loss_limit) * 100).toFixed(1);
      const tradePct = ((b.current_usage.trade_count / b.budget_limit.max_trade_count) * 100).toFixed(1);
      
      return `
        <tr>
          <td><strong>${escapeHtml(b.strategy)}</strong></td>
          <td>${b.suspended ? '<span class="status-label status-failed">SUSPENDED</span>' : '<span class="status-label status-success">ACTIVE</span>'}</td>
          <td class="numeric">$${b.current_usage.monthly_loss.toFixed(2)} / $${b.budget_limit.monthly_loss_limit.toFixed(2)} (${lossPct}%)</td>
          <td class="numeric">${b.current_usage.trade_count} / ${b.budget_limit.max_trade_count} (${tradePct}%)</td>
          <td class="numeric">${(b.current_usage.capital_allocation * 100).toFixed(1)}% / ${(b.budget_limit.max_capital_allocation * 100).toFixed(1)}%</td>
          <td class="numeric" style="color: #60a5fa; font-weight: bold;">$${remainingLoss.toFixed(2)}</td>
          <td class="numeric" style="color: #60a5fa; font-weight: bold;">${remainingTrades}회</td>
          <td><span style="font-size: 11px; color:#94a3b8;">${b.reason ? escapeHtml(b.reason) : "한도 준수 중"}</span></td>
        </tr>
      `;
    }).join("");
  } else {
    rowsHtml = '<tr><td colspan="8" style="text-align:center; color:#94a3b8; padding:20px;">설정된 전략 위험 예산이 없습니다.</td></tr>';
  }

  return `
    <div class="panel-header">
      <div>
        <h2 style="color: #f87171; font-size: 1.2rem; margin:0;">🛡️ 전략 위험 예산 회계 (Strategy Risk Budgeting)</h2>
        <p style="margin: 4px 0 0 0; font-size: 0.9rem; color: #94a3b8;">
          전략의 과도한 누적 손실과 남발을 통제하기 위해 개별 전략별로 할당된 월간 자금, 손실 한도 및 최대 거래 횟수 소진율을 감시합니다.
        </p>
      </div>
      <span class="status-label status-danger" style="font-size:0.75rem;">오버트레이딩 차단</span>
    </div>
    <div class="panel-body" style="padding-top: 1rem;">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>전략명</th>
              <th>동작 상태</th>
              <th class="numeric">월 누적 손실 / 한도</th>
              <th class="numeric">월 누적 거래 / 한도</th>
              <th class="numeric">자금 사용률 / 한도</th>
              <th class="numeric">남은 손실 예산</th>
              <th class="numeric">남은 거래 횟수</th>
              <th>차단 사유</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

async function loadAndRenderStrategyCards() {
  const container = document.querySelector("#strategy-cards-section");
  if (!container) return;

  container.innerHTML = `
    <div class="panel-header">
      <div>
        <h2 style="color: #60a5fa; font-size: 1.2rem; margin:0;">🎴 전략 카드 마켓 (Strategy Cards Registry)</h2>
        <p style="margin: 4px 0 0 0; font-size: 0.9rem; color: #94a3b8;">
          등록된 핵심 투자 전략의 성격과 운용 적합국면, 성과 지표를 카드 구조로 시각화하여 간편하게 비교/검토합니다.
        </p>
      </div>
      <span class="status-label status-success" style="font-size:0.75rem;">자율 전략 비교</span>
    </div>
    <div class="panel-body" style="padding-top: 1rem;">
      <div style="text-align: center; padding: 1.5rem; color: #94a3b8;">전략 카드를 불러오는 중...</div>
    </div>
  `;

  try {
    const response = await fetch("/api/v1/strategies/cards");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const cards = data.cards || [];

    if (!cards.length) {
      container.querySelector(".panel-body").innerHTML = `
        <div style="text-align: center; padding: 1.5rem; color: #94a3b8;">등록된 전략 카드가 없습니다.</div>
      `;
      return;
    }

    const cardsHtml = cards.map(c => {
      const perf = c.recent_performance || {};
      const forbiddenRegimesHtml = (c.forbidden_market_regimes || [])
        .map(r => `<span class="status-badge" style="background:#fecaca; color:#b91c1c; border:1px solid #fca5a5; font-size:0.75rem; margin-right:0.3rem;">${r.toUpperCase()} 금지</span>`)
        .join("");
      
      return `
        <div style="border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; background: var(--neutral-bg, #f8fafc); display: flex; flex-direction: column; justify-content: space-between; gap: 0.8rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); transition: transform 0.2s, box-shadow 0.2s;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
              <span class="status-badge" style="background:#dbeafe; color:#1e40af; border:1px solid #bfdbfe; font-size:0.75rem; font-weight:bold;">${escapeHtml(c.type)}</span>
              <span style="font-size: 0.8rem; color:#94a3b8; font-family: monospace;">ID: ${escapeHtml(c.strategy_id)}</span>
            </div>
            <h3 style="font-size: 1.1rem; margin: 0 0 0.6rem 0; color: var(--text); font-weight: bold;">${escapeHtml(c.name)}</h3>
            <p style="font-size: 0.85rem; color: var(--muted); margin: 0; line-height: 1.5; height: 4.5rem; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;">
              ${escapeHtml(c.investment_objective)}
            </p>
          </div>

          <div style="border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 0.6rem 0; display: flex; justify-content: space-between; font-size: 0.8rem;">
            <div>
              <span style="display:block; color:#94a3b8; font-size:0.7rem; margin-bottom:2px;">Sharpe Ratio</span>
              <strong style="color: #60a5fa; font-size:1rem;">${perf.sharpe_ratio || "N/A"}</strong>
            </div>
            <div>
              <span style="display:block; color:#94a3b8; font-size:0.7rem; margin-bottom:2px;">최대 낙폭 (MDD)</span>
              <strong style="color: #f87171; font-size:1rem;">${perf.mdd_pct ? `${perf.mdd_pct}%` : "N/A"}</strong>
            </div>
            <div>
              <span style="display:block; color:#94a3b8; font-size:0.7rem; margin-bottom:2px;">평균 승률</span>
              <strong style="color: #34d399; font-size:1rem;">${perf.win_rate_pct ? `${perf.win_rate_pct}%` : "N/A"}</strong>
            </div>
          </div>

          <div style="font-size: 0.8rem;">
            <div style="margin-bottom: 0.4rem;">
              <span class="muted">🎯 적합 포트폴리오:</span>
              <strong style="color: var(--text);">${escapeHtml(c.suitable_portfolio_type.toUpperCase())}</strong>
            </div>
            <div style="margin-bottom: 0.4rem; display: flex; align-items: center; flex-wrap: wrap;">
              <span class="muted" style="margin-right:0.3rem;">🚫 제한 국면:</span>
              ${forbiddenRegimesHtml || "<span style='color:#34d399;'>없음</span>"}
            </div>
            <div style="color: #94a3b8; font-size: 0.75rem; line-height: 1.4; margin-top: 0.4rem; font-style: italic;">
              * 위험: ${escapeHtml(c.risk_description)}
            </div>
          </div>
        </div>
      `;
    }).join("");

    container.querySelector(".panel-body").innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1.2rem;">
        ${cardsHtml}
      </div>
    `;
  } catch (e) {
    container.querySelector(".panel-body").innerHTML = `
      <div style="text-align: center; padding: 1.5rem; color: #f87171;">전략 카드를 불러오지 못했습니다: ${escapeHtml(e.message)}</div>
    `;
  }
}
