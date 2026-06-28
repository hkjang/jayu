"use strict";

function renderDividendPage() {
  const root = document.querySelector("#page-root");
  if (!root) return;

  const data = state.dividendDashboard;
  if (!data) {
    root.innerHTML = `
      <div class="state-panel">
        <span class="status-label status-failed">데이터 없음</span>
        <h1>배당 관리 데이터를 불러오지 못했습니다.</h1>
        <p>백엔드 서버 또는 데이터 상태를 점검해 주세요.</p>
      </div>
    `;
    return;
  }

  const { overview, monthly_cashflows, holdings_table, calendar_events, reconciliation, alerts } = data;

  let alertsHtml = "";
  if (alerts && alerts.length > 0) {
    alertsHtml = `
      <div class="card-grid" style="grid-template-columns: 1fr; margin-bottom: 24px;">
        <div class="card card-warning" style="border-left: 4px solid var(--color-warning);">
          <div class="card-header">
            <h3 class="card-title">⚠️ 배당 일정 알림</h3>
          </div>
          <div class="card-body">
            <ul style="margin: 0; padding-left: 20px; color: var(--color-text-muted);">
              ${alerts.map(a => `<li><strong>${a.symbol}</strong>: ${a.message}</li>`).join("")}
            </ul>
          </div>
        </div>
      </div>
    `;
  }

  // Monthly Cashflow chart representation
  const maxGross = Math.max(...monthly_cashflows.map(c => c.gross), 1);
  const chartHtml = monthly_cashflows.map(c => {
    const grossHeight = (c.gross / maxGross) * 100;
    const netHeight = (c.net / maxGross) * 100;
    return `
      <div style="display: flex; flex-direction: column; align-items: center; flex: 1; min-width: 40px;">
        <div style="height: 150px; width: 100%; display: flex; align-items: flex-end; justify-content: center; gap: 4px; position: relative;">
          <div style="height: ${grossHeight}%; width: 12px; background: var(--color-primary); border-radius: 2px; transition: height 0.3s;" title="세전: ${c.gross.toLocaleString()}원"></div>
          <div style="height: ${netHeight}%; width: 12px; background: var(--color-success); border-radius: 2px; transition: height 0.3s;" title="세후: ${c.net.toLocaleString()}원"></div>
        </div>
        <span style="margin-top: 8px; font-size: 11px; color: var(--color-text-muted);">${c.month}월</span>
      </div>
    `;
  }).join("");

  // Holdings Table rows
  const tableRowsHtml = holdings_table.map(h => {
    const badgeClass = h.decision === "pass" ? "status-success" : h.decision === "review" ? "status-warning" : "status-failed";
    const badgeText = h.decision === "pass" ? "안전" : h.decision === "review" ? "검토" : "차단";
    return `
      <tr>
        <td>
          <div style="display: flex; flex-direction: column;">
            <span style="font-weight: bold; color: var(--color-text);">${h.symbol}</span>
            <span style="font-size: 11px; color: var(--color-text-muted);">${h.name}</span>
          </div>
        </td>
        <td style="text-align: right;">${h.quantity.toLocaleString(undefined, {minimumFractionDigits: 2})}</td>
        <td style="text-align: right;">${h.dividend_yield.toFixed(2)}%</td>
        <td style="text-align: right; font-weight: bold; color: var(--color-primary);">${h.annual_payout_krw.toLocaleString()}원</td>
        <td style="text-align: right; color: var(--color-success);">${h.net_annual_payout_krw.toLocaleString()}원</td>
        <td style="text-align: center;">
          <span class="status-label ${badgeClass}">${badgeText} (${h.trust_score}점)</span>
        </td>
        <td style="color: var(--color-text-muted); font-size: 12px;">
          ${h.next_ex_date ? `락: ${h.next_ex_date.substring(5)}<br>` : ""}
          ${h.next_pay_date ? `지급: ${h.next_pay_date.substring(5)}` : "일정 없음"}
        </td>
      </tr>
    `;
  }).join("");

  // Reconciliation Rows
  const reconRowsHtml = reconciliation.items.map(item => {
    const statusClass = item.status === "matched" ? "status-success" : item.status === "amount_diff" ? "status-warning" : "status-failed";
    const statusText = item.status === "matched" ? "일치" : item.status === "amount_diff" ? "차이" : "누락";
    return `
      <tr>
        <td><strong>${item.symbol}</strong></td>
        <td style="text-align: right;">${item.expected_amount.toLocaleString()}원</td>
        <td style="text-align: right;">${item.actual_amount.toLocaleString()}원</td>
        <td style="text-align: right; color: ${item.diff >= 0 ? "var(--color-success)" : "var(--color-failed)"}">
          ${item.diff >= 0 ? "+" : ""}${item.diff.toLocaleString()}원
        </td>
        <td style="text-align: center;">
          <span class="status-label ${statusClass}">${statusText}</span>
        </td>
      </tr>
    `;
  }).join("");

  root.innerHTML = `
    <div class="view-header">
      <h1 class="view-title">💰 배당 관리 대시보드</h1>
      <p class="view-subtitle">실시간 배당 이력, 세금, 환율 및 실제 입금 내역 통합 분석</p>
    </div>

    ${alertsHtml}

    <!-- Overview Cards -->
    <div class="card-grid">
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">이번 달 예상 배당 (세전)</h3>
        </div>
        <div class="card-body">
          <div class="metric-value">${overview.this_month_expected.toLocaleString()}원</div>
          <p class="metric-desc" style="color: var(--color-text-muted);">세후 예상: ${overview.this_month_net.toLocaleString()}원</p>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">연간 예상 배당금</h3>
        </div>
        <div class="card-body">
          <div class="metric-value" style="color: var(--color-primary);">${overview.annual_dividend_krw.toLocaleString()}원</div>
          <p class="metric-desc" style="color: var(--color-text-muted);">세후 연 배당: ${overview.annual_net_dividend_krw.toLocaleString()}원</p>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">포트폴리오 배당 수익률</h3>
        </div>
        <div class="card-body">
          <div class="metric-value" style="color: var(--color-success);">${overview.aggregate_yield_pct.toFixed(2)}%</div>
          <p class="metric-desc" style="color: var(--color-text-muted);">보유 배당 종목 수: ${holdings_table.length}개</p>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">월 목표 배당 달성률</h3>
        </div>
        <div class="card-body">
          <div class="metric-value">${overview.goal_achievement_pct.toFixed(1)}%</div>
          <p class="metric-desc" style="color: var(--color-text-muted);">목표: ${overview.monthly_target_krw.toLocaleString()}원 / 월</p>
        </div>
      </div>
    </div>

    <!-- Monthly Chart & Reinvestment Projections -->
    <div class="card-grid" style="grid-template-columns: 2fr 1fr; margin-top: 24px;">
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">📅 향후 12개월 예상 월별 흐름</h3>
        </div>
        <div class="card-body" style="display: flex; justify-content: space-between; align-items: flex-end; height: 200px; padding: 20px 10px; background: #181818; border-radius: 6px;">
          ${chartHtml}
        </div>
        <div style="display: flex; gap: 16px; margin-top: 12px; justify-content: center; font-size: 12px;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <div style="width: 12px; height: 12px; background: var(--color-primary); border-radius: 2px;"></div>
            <span>세전 배당</span>
          </div>
          <div style="display: flex; align-items: center; gap: 6px;">
            <div style="width: 12px; height: 12px; background: var(--color-success); border-radius: 2px;"></div>
            <span>세후 배당</span>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">📈 배당 재투자 복리 효과</h3>
        </div>
        <div class="card-body">
          <div style="display: flex; flex-direction: column; gap: 12px;">
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px;">
                <span>현재 자산 가치</span>
                <strong>${data.portfolio_value_krw.toLocaleString()}원</strong>
              </div>
            </div>
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px;">
                <span>1년 후 예상 자산 (재투자 시)</span>
                <strong style="color: var(--color-primary);">${data.reinvestment_projections["1_year_value_krw"].toLocaleString()}원</strong>
              </div>
            </div>
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px;">
                <span>3년 후 예상 자산</span>
                <strong style="color: var(--color-primary);">${data.reinvestment_projections["3_year_value_krw"].toLocaleString()}원</strong>
              </div>
            </div>
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px;">
                <span>5년 후 예상 자산</span>
                <strong style="color: var(--color-success);">${data.reinvestment_projections["5_year_value_krw"].toLocaleString()}원</strong>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Holdings Table & Reconciliation -->
    <div class="card-grid" style="grid-template-columns: 2fr 1fr; margin-top: 24px;">
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">📋 종목별 배당 상세 정보</h3>
        </div>
        <div class="card-body" style="padding: 0; overflow-x: auto;">
          <table class="table" style="width: 100%; margin: 0;">
            <thead>
              <tr>
                <th>종목</th>
                <th style="text-align: right;">보유량</th>
                <th style="text-align: right;">배당수익률</th>
                <th style="text-align: right;">연 배당 (세전)</th>
                <th style="text-align: right;">연 배당 (세후)</th>
                <th style="text-align: center;">신뢰도 게이트</th>
                <th>주요 일정</th>
              </tr>
            </thead>
            <tbody>
              ${tableRowsHtml || `<tr><td colspan="7" style="text-align: center; color: var(--color-text-muted); padding: 20px;">보유 중인 배당 종목이 없습니다.</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">⚖️ 이번 달 실제 입금 대사</h3>
        </div>
        <div class="card-body" style="padding: 0;">
          <table class="table" style="width: 100%; margin: 0;">
            <thead>
              <tr>
                <th>종목</th>
                <th style="text-align: right;">예상</th>
                <th style="text-align: right;">실제</th>
                <th style="text-align: right;">차이</th>
                <th style="text-align: center;">상태</th>
              </tr>
            </thead>
            <tbody>
              ${reconRowsHtml || `<tr><td colspan="5" style="text-align: center; color: var(--color-text-muted); padding: 20px;">대사 가능한 입금 내역이 없습니다.</td></tr>`}
            </tbody>
          </table>
          <div style="padding: 16px; border-top: 1px solid var(--color-border); font-size: 12px; color: var(--color-text-muted);">
            실제 입금 내역 등록은 <code>state/dividend_actual_receipts.csv</code> 파일을 통해 가능합니다.
          </div>
        </div>
      </div>
    </div>
  `;
}
