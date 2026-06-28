"use strict";

// Helper formatting functions to match previous personal_finance.js style
function div_fmt(val) {
  if (val == null || isNaN(val)) return "0";
  return Math.round(val).toLocaleString();
}

function div_esc(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function renderDividendPage() {
  const root = document.querySelector("#page-root");
  if (!root) return;

  const data = state.dividendDashboard;
  if (!data) {
    root.innerHTML = `
      <div class="page-heading">
        <div>
          <h1>배당 관리</h1>
          <p>보유 종목 기반 배당 수입 추정 및 복리 성장 시뮬레이션</p>
        </div>
      </div>
      <div class="empty-state" style="margin-top:20px;">
        <strong>배당 분석 데이터 누락</strong>
        <span>Toss 연동 계좌에 보유 자산이 존재하지 않거나 포트폴리오 허브 로드가 완료되지 않았습니다.</span>
      </div>
    `;
    return;
  }

  const { overview, monthly_cashflows, holdings_table, calendar_events, reconciliation, alerts } = data;

  const monthly = overview.this_month_net || 0;
  const annual = overview.annual_dividend_krw || monthly * 12;
  const yieldPct = overview.aggregate_yield_pct || 0;
  const holdings = holdings_table || [];

  // Alerts rendering
  let alertsHtml = "";
  if (alerts && alerts.length > 0) {
    alertsHtml = `
      <div class="card card-warning" style="margin-bottom: 16px; border-left: 4px solid var(--color-warning); background: var(--surface-subtle);">
        <div class="card-header" style="padding: 10px 15px;">
          <h3 class="card-title" style="font-size:12px; font-weight:700; margin:0;">⚠️ 실시간 배당락 안내</h3>
        </div>
        <div class="card-body" style="padding: 10px 15px; font-size:11.5px; color: var(--color-text-muted);">
          <ul style="margin: 0; padding-left: 20px; line-height: 1.5;">
            ${alerts.map(a => `<li><strong>${a.symbol}</strong>: ${a.message}</li>`).join("")}
          </ul>
        </div>
      </div>
    `;
  }

  // Projection bars for 1/3/5yr (DRIP Reinvestment)
  const projections = data.scenarios || {};
  const projYears = [1, 3, 5];
  // Calculate projections based on compound rate
  const annualYield = yieldPct / 100.0;
  const portfolioVal = data.portfolio_value_krw || 0;
  
  const projVals = projYears.map(y => {
    const monthlyRate = annualYield / 12.0;
    return portfolioVal * ((1.0 + monthlyRate) ** (y * 12));
  });
  
  const maxProj = Math.max(...projVals, 1);
  const projBarHtml = projYears.map((y, i) => {
    const v = projVals[i];
    const pct = (v / maxProj * 100).toFixed(1);
    return `
      <div style="flex:1; display:flex; flex-direction:column; align-items:center; gap:6px;">
        <span style="font-size:11px; font-weight:700; color:var(--text);">${div_fmt(Math.round(v / 10000))}만원</span>
        <div style="width:100%; height:110px; background:var(--border); border-radius:6px; overflow:hidden; display:flex; align-items:flex-end;">
          <div style="width:100%; height:${pct}%; background:linear-gradient(180deg, #34d399, #10b981); border-radius:6px 6px 0 0; transition:height 0.5s ease;"></div>
        </div>
        <span style="font-size:11px; font-weight:700; color:var(--muted);">${y}년 후 자산</span>
      </div>
    `;
  }).join("");

  // 12 Months Chart
  const maxGross = Math.max(...monthly_cashflows.map(c => c.gross), 1);
  const chartHtml = monthly_cashflows.map(c => {
    const grossHeight = (c.gross / maxGross) * 100;
    const netHeight = (c.net / maxGross) * 100;
    return `
      <div style="display: flex; flex-direction: column; align-items: center; flex: 1; min-width: 35px;">
        <div style="height: 100px; width: 100%; display: flex; align-items: flex-end; justify-content: center; gap: 3px; position: relative;">
          <div style="height: ${grossHeight}%; width: 8px; background: var(--color-primary); border-radius: 2px; transition: height 0.3s;" title="세전: ${c.gross.toLocaleString()}원"></div>
          <div style="height: ${netHeight}%; width: 8px; background: var(--color-success); border-radius: 2px; transition: height 0.3s;" title="세후: ${c.net.toLocaleString()}원"></div>
        </div>
        <span style="margin-top: 6px; font-size: 10px; color: var(--color-text-muted);">${c.month}월</span>
      </div>
    `;
  }).join("");

  // Holdings Table rows
  const holdingRows = holdings.length === 0
    ? `<tr><td colspan="6" style="text-align:center; padding:20px; color:var(--muted);">배당을 지급하는 보유 종목이 감지되지 않았습니다.</td></tr>`
    : holdings.map(h => {
        const badgeClass = h.decision === "pass" ? "status-success" : h.decision === "review" ? "status-warning" : "status-failed";
        const badgeText = h.decision === "pass" ? "안전" : h.decision === "review" ? "검토" : "차단";
        return `
          <tr>
            <td class="ticker-cell">${renderTicker(h.symbol)}</td>
            <td><span style="font-size:11.5px; color:var(--muted);">${div_esc(h.name || "US Stock")}</span></td>
            <td class="numeric">${div_fmt(h.value_krw)}원</td>
            <td class="numeric" style="color:var(--success); font-weight:700;">${h.dividend_yield.toFixed(2)}%</td>
            <td class="numeric" style="color:var(--success); font-weight:700;">+${div_fmt(h.annual_payout_krw)}원</td>
            <td style="text-align: center;">
              <span class="status-label ${badgeClass}" style="font-size: 10px; padding: 2px 6px;">${badgeText} (${h.trust_score}점)</span>
            </td>
          </tr>
        `;
      }).join("");

  // Reconciliation Table rows
  const reconRowsHtml = reconciliation.items.map(item => {
    const statusClass = item.status === "matched" ? "status-success" : item.status === "amount_diff" ? "status-warning" : "status-failed";
    const statusText = item.status === "matched" ? "일치" : item.status === "amount_diff" ? "차이" : "누락";
    return `
      <tr>
        <td><strong>${renderTicker(item.symbol)}</strong></td>
        <td class="numeric">${div_fmt(item.expected_amount)}원</td>
        <td class="numeric" style="color: var(--color-success);">${div_fmt(item.actual_amount)}원</td>
        <td class="numeric" style="color: ${item.diff >= 0 ? "var(--color-success)" : "var(--color-failed)"}; font-weight: 700;">
          ${item.diff >= 0 ? "+" : ""}${div_fmt(item.diff)}원
        </td>
        <td style="text-align: center;">
          <span class="status-label ${statusClass}" style="font-size: 10px; padding: 2px 6px;">${statusText}</span>
        </td>
      </tr>
    `;
  }).join("");

  // Target Goal Calculations
  const goalBridge = data.goal_bridge || {};
  const targetKrw = goalBridge.monthly_target_krw || overview.monthly_target_krw || 3000000.0;
  const currentMonthlyNet = goalBridge.current_monthly_net_krw || overview.this_month_net || 0.0;
  const shortfall = goalBridge.monthly_shortfall_krw ?? Math.max(0.0, targetKrw - currentMonthlyNet);
  const achievementRate = Number(goalBridge.achievement_rate_pct ?? ((currentMonthlyNet / targetKrw) * 100.0)).toFixed(1);
  const neededCapital = goalBridge.needed_additional_capital_krw ?? ((shortfall * 12.0) / (annualYield > 0 ? annualYield : 0.04));
  const requiredMonthlyInvestment = goalBridge.required_monthly_investment || {};

  root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>배당 관리 대시보드</h1>
        <p>실시간 보유 자산 구조를 진단하여 월/연 배당 흐름을 추정하고, 배당 유입금을 전액 재투자(DRIP)하는 경우의 1년/3년/5년 누적 복리 성장 궤적을 연산합니다.</p>
      </div>
      <span class="status-label status-success" style="font-size:12px; font-weight:700;">연동 완료</span>
    </div>
    ${renderDataSourceNote("dividend")}

    ${alertsHtml}

    <!-- Metric Grid -->
    <section class="metric-grid">
      ${metricCard("월 예상 배당 (세후)", `+${div_fmt(monthly)}원`, monthly ? "success" : "not_evaluated", "당월 예상 세후 배당금")}
      ${metricCard("연 예상 배당 (세전)", `+${div_fmt(annual)}원`, annual ? "success" : "not_evaluated", "포트폴리오 연간 총 배당 수입")}
      ${metricCard("종합 배당수익률", `${yieldPct.toFixed(2)}%`, yieldPct > 4.0 ? "success" : yieldPct > 0 ? "not_evaluated" : "failed", "포트폴리오 평균 배당 수익률")}
      ${metricCard("보유 배당주", `${holdings.length}개 종목`, holdings.length ? "success" : "not_evaluated", "실시간 매핑된 배당주 수")}
    </section>

    <!-- Main Section Grid -->
    <div class="section-grid">
      
      <!-- Left Column: DRIP, Forecast, Goal, Recon -->
      <div style="display:flex; flex-direction:column; gap:14px;">
        
        <!-- Reinvestment compound model -->
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>💹 배당 재투자 복리 성장 시나리오 (DRIP)</h2>
              <p>배당 수익률과 자산 가치가 일정하며 분배 배당금 전액을 원형에 재복리 매수 투입한다고 가정한 성장 예측입니다.</p>
            </div>
          </div>
          <div class="panel-body" style="padding:20px 30px;">
            <div style="display:flex; gap:20px; align-items:flex-end; padding:10px 0;">
              ${projBarHtml}
            </div>
          </div>
          ${renderSourceCaption("dividend_cashflow_simulator.py · monthly compound model")}
        </section>

        <!-- 12 Months Chart -->
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>📅 향후 12개월 예상 월별 배당 흐름</h2>
              <p>세전 배당금 및 세후 배당금의 월별 분배 예측 현금흐름 차트입니다.</p>
            </div>
          </div>
          <div class="panel-body" style="padding: 20px 30px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-end; height: 130px; padding: 10px; background: var(--surface-subtle); border-radius: 6px;">
              ${chartHtml}
            </div>
            <div style="display: flex; gap: 16px; margin-top: 12px; justify-content: center; font-size: 11px;">
              <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 10px; height: 10px; background: var(--color-primary); border-radius: 2px;"></div>
                <span style="color: var(--muted)">세전 배당</span>
              </div>
              <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 10px; height: 10px; background: var(--color-success); border-radius: 2px;"></div>
                <span style="color: var(--muted)">세후 배당</span>
              </div>
            </div>
          </div>
        </section>

        <!-- Living Expense Simulator -->
        <section class="panel">
          <div class="panel-header" style="padding-bottom:10px; border-bottom:1px solid var(--border);">
            <div>
              <h2 style="font-size:13.5px; font-weight:700; margin:0;">🛡️ 배당 생활비 시뮬레이터 (Living Expense Simulator)</h2>
              <p style="font-size:11px; margin:2px 0 0 0;">월 배당 목표액 대비 현재 수입과 목표 달성도를 분석하고 복리 경로를 계산합니다.</p>
            </div>
            <span class="status-label status-success" style="font-size:11px; font-weight:700;">${achievementRate}% 달성</span>
          </div>
          <div class="panel-body" style="padding-top:12px;">
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-bottom:12px;">
              <div style="background:var(--surface-subtle); padding:10px; border-radius:6px; border:1px solid var(--border); display:flex; flex-direction:column; justify-content:center;">
                <span style="font-size:11px; color:var(--muted)">목표 월 배당금</span>
                <strong style="font-size:16px; color:var(--text);">${div_fmt(targetKrw)}원</strong>
              </div>
              <div style="background:var(--surface-subtle); padding:10px; border-radius:6px; border:1px solid var(--border); display:flex; flex-direction:column; justify-content:center;">
                <span style="font-size:11px; color:var(--muted)">부족 월 배당금</span>
                <strong style="font-size:16px; color:var(--failed);">${div_fmt(shortfall)}원</strong>
              </div>
            </div>

            <div style="font-size:12px; line-height:1.45; color:var(--text); margin-bottom:12px;">
              목표 배당을 채우기 위해 필요한 추가 배당 투자금은 약 <strong>${div_fmt(Math.round(neededCapital / 10000))}만원</strong>입니다. (배당수익률 기준)<br>
              추가 저축 없이 배당금 재투자(DRIP)만 유지할 경우 복리 성장을 통해 목표치에 근접해 나갈 수 있습니다.
            </div>
            <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:8px; font-size:11px; margin-bottom:12px;">
              <div style="background:var(--surface-subtle); border:1px solid var(--border); border-radius:6px; padding:8px;">
                <span style="display:block; color:var(--muted);">1년 목표 월투자</span>
                <strong>${div_fmt(requiredMonthlyInvestment["1_year"] || 0)}원</strong>
              </div>
              <div style="background:var(--surface-subtle); border:1px solid var(--border); border-radius:6px; padding:8px;">
                <span style="display:block; color:var(--muted);">3년 목표 월투자</span>
                <strong>${div_fmt(requiredMonthlyInvestment["3_year"] || 0)}원</strong>
              </div>
              <div style="background:var(--surface-subtle); border:1px solid var(--border); border-radius:6px; padding:8px;">
                <span style="display:block; color:var(--muted);">5년 목표 월투자</span>
                <strong>${div_fmt(requiredMonthlyInvestment["5_year"] || 0)}원</strong>
              </div>
            </div>
            
            <div style="margin-top:10px; padding-top:10px; border-top:1px solid var(--border); display:flex; gap:8px; align-items:flex-end;">
              <div style="flex:1;">
                <label style="display:block; font-size:10px; color:var(--muted); margin-bottom:3px;">목표 월 배당금 변경 (원)</label>
                <input id="pf-dle-target-input" type="number" value="${targetKrw}" style="width:100%; min-height:28px; padding:3px 6px; border:1px solid var(--border-strong); border-radius:4px; font-size:11.5px; background: var(--surface-subtle); color: var(--text);">
              </div>
              <button id="pf-dle-target-save" class="button button-primary" style="min-height:28px; font-size:11px; padding:2px 8px;">목표 저장</button>
            </div>
          </div>
        </section>

        <!-- Reconciliation Section -->
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>⚖️ 이번 달 실제 입금 대사</h2>
              <p>예상 배당금 수입과 실제 입금 내역을 대조하여 누락이나 오차를 검증합니다.</p>
            </div>
          </div>
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>종목</th>
                  <th class="numeric">예상 세후</th>
                  <th class="numeric">실제 입금</th>
                  <th class="numeric">오차</th>
                  <th style="text-align: center;">상태</th>
                </tr>
              </thead>
              <tbody>
                ${reconRowsHtml || `<tr><td colspan="5" style="text-align:center; padding:15px; color:var(--muted);">이번 달 매칭된 입금 내역이 없습니다.</td></tr>`}
              </tbody>
            </table>
          </div>
          <div style="padding: 10px 15px; font-size: 11px; color: var(--color-text-muted); border-top: 1px solid var(--border);">
            실제 입금 내역 수동 등록은 <code>state/dividend_actual_receipts.csv</code> 파일을 이용하세요.
          </div>
        </section>

      </div>

      <!-- Right Column: Holdings Details -->
      <section class="panel" style="flex: 1; align-self: flex-start;">
        <div class="panel-header">
          <div>
            <h2>📊 종목별 배당 상세 내역</h2>
            <p>실시간 야후 파이낸스 배당 이력 및 품질 평가가 완료된 종목 목록입니다.</p>
          </div>
          <span class="muted">${holdings.length}개 보유</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>티커</th>
                <th>종목명</th>
                <th class="numeric">평가 금액</th>
                <th class="numeric">배당률</th>
                <th class="numeric">연 예상 배당</th>
                <th style="text-align: center;">품질 등급</th>
              </tr>
            </thead>
            <tbody>
              ${holdingRows}
            </tbody>
          </table>
        </div>
        ${renderSourceCaption("toss_portfolio.csv · yfinance real-time history")}
      </section>

    </div>
  `;

  // Bind Target Save Event
  document.querySelector("#pf-dle-target-save")?.addEventListener("click", async () => {
    const inputVal = parseFloat(document.querySelector("#pf-dle-target-input")?.value) || 0;
    if (inputVal <= 0) return alert("유효한 목표 금액을 입력하십시오.");
    try {
      const res = await fetch("/api/v1/dividend-living-expense-simulator", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ monthly_target_krw: inputVal })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // Refresh
      state.dividendDashboard = await api("/api/v1/dividend-dashboard");
      renderDividendPage();
    } catch (e) {
      alert(`배당 목표 저장에 실패했습니다: ${e.message}`);
    }
  });
}
