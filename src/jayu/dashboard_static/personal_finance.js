/* ============================================================
 * personal_finance.js — Jayu 개인 투자 관리 5-tab 렌더 모듈
 * pages: goal-planner | cashflow | dividend-sim | investor-coach | invest-calendar
 * 디자인 일관성 고도화 버전 (Jayu 디자인 규격 준수)
 * ============================================================ */



// ──────────────────────────────────────────────
// 공통 포맷 헬퍼
// ──────────────────────────────────────────────
function pf_fmt(n, digits = 0) {
  if (n === undefined || n === null || isNaN(n)) return "–";
  return Number(n).toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function pf_pct(n, digits = 1) {
  if (n === undefined || n === null || isNaN(n)) return "–";
  const sign = n >= 0 ? "+" : "";
  return sign + Number(n).toFixed(digits) + "%";
}
function pf_esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function pf_order_amount(order) {
  const exec = order?.execution || {};
  const filled = Number(exec.filledAmount ?? order?.filledAmount);
  if (Number.isFinite(filled) && filled > 0) return filled;
  const direct = Number(order?.orderAmount);
  if (Number.isFinite(direct) && direct > 0) return direct;
  const price = Number(exec.averageFilledPrice ?? order?.price);
  const quantity = Number(exec.filledQuantity ?? order?.quantity);
  return Number.isFinite(price) && Number.isFinite(quantity) ? price * quantity : null;
}

function pf_money(value, currency = "KRW") {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  const digits = currency === "USD" ? 2 : 0;
  return `${pf_fmt(n, digits)} ${pf_esc(currency || "")}`.trim();
}

function renderTossOrderDetailCard() {
  const orderId = state.selectedTossOrderId;
  if (!orderId) {
    return `
      <div style="border-top:1px dashed var(--border); padding-top:10px; color:var(--muted); font-size:11.5px;">
        주문 행의 상세 버튼을 누르면 Toss getOrder 응답의 체결가, 수수료, 세금, 결제일을 여기서 확인합니다.
      </div>
      ${renderSourceCaption("Toss Order History getOrder · GET /api/v1/orders/{orderId}")}
    `;
  }
  const payload = state.tossOrderDetails?.[orderId] || {};
  const order = payload.order || {};
  if (!order || Object.keys(order).length === 0) {
    return `
      <div style="border-top:1px dashed var(--border); padding-top:10px; color:var(--warning); font-size:11.5px;">
        선택한 주문의 상세 캐시가 없습니다. 상세 버튼을 다시 눌러 조회하세요.
      </div>
      ${renderSourceCaption(payload.source || "Toss Order History getOrder · GET /api/v1/orders/{orderId}")}
    `;
  }
  const exec = order.execution || {};
  const rows = [
    ["주문 ID", order.orderId || orderId],
    ["종목", order.symbol],
    ["방향 / 유형", `${order.side || "-"} · ${order.orderType || "-"}`],
    ["상태", order.status],
    ["주문가 / 수량", `${pf_money(order.price, order.currency)} · ${pf_esc(order.quantity || "-")}`],
    ["주문 시각", order.orderedAt],
    ["체결 수량", exec.filledQuantity],
    ["평균 체결가", pf_money(exec.averageFilledPrice, order.currency)],
    ["체결 금액", pf_money(exec.filledAmount, order.currency)],
    ["수수료 / 세금", `${pf_money(exec.commission, order.currency)} · ${pf_money(exec.tax, order.currency)}`],
    ["체결 시각", exec.filledAt],
    ["결제일", exec.settlementDate],
  ];
  return `
    <div style="border-top:1px dashed var(--border); padding-top:10px;">
      <div style="display:flex; justify-content:space-between; gap:10px; align-items:center; margin-bottom:8px;">
        <strong style="font-size:12.5px;">주문 상세</strong>
        <span class="status-label status-${order.status === "FILLED" ? "success" : "not_evaluated"}">${pf_esc(order.status || "-")}</span>
      </div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:7px; font-size:11.5px;">
        ${rows.map(([label, value]) => `
          <div style="border-bottom:1px solid #eef2f7; padding-bottom:4px;">
            <span style="display:block; color:var(--muted);">${pf_esc(label)}</span>
            <strong style="word-break:break-word;">${pf_esc(value ?? "-")}</strong>
          </div>
        `).join("")}
      </div>
    </div>
    ${renderSourceCaption(payload.source || "Toss Order History getOrder · GET /api/v1/orders/{orderId}")}
  `;
}

function renderTossOrderHistoryPanel(orders) {
  const source = state.tossOrdersMeta?.source || "Toss Order History getOrders · GET /api/v1/orders";
  const fetch = state.tossOrdersMeta?.fetch_result;
  const caption = fetch?.from && fetch?.to
    ? `${source} · orderedAt KST ${fetch.from}~${fetch.to}`
    : source;
  const recent = (orders || []).slice(0, 8);
  const rows = recent.length === 0
    ? `<tr><td colspan="6" style="text-align:center; padding:18px; color:var(--muted);">저장된 Toss 주문 내역이 없습니다.</td></tr>`
    : recent.map((order) => {
        const orderId = order.orderId || "";
        const selected = state.selectedTossOrderId === orderId;
        const amount = pf_order_amount(order);
        return `
          <tr style="${selected ? "background:#f8fafc;" : ""}">
            <td class="nowrap">${pf_esc((order.orderedAt || "").slice(0, 16).replace("T", " "))}</td>
            <td class="nowrap"><strong>${pf_esc(order.symbol || "-")}</strong></td>
            <td class="nowrap">${pf_esc(order.side || "-")}</td>
            <td class="nowrap">${pf_esc(order.status || order.historyStatus || "-")}</td>
            <td class="nowrap" style="text-align:right;">${pf_money(amount, order.currency || "KRW")}</td>
            <td class="nowrap" style="text-align:right;">
              ${orderId ? `<button class="button button-secondary" type="button" data-toss-order-detail="${pf_esc(orderId)}" style="min-height:26px; padding:2px 8px; font-size:11px;">상세</button>` : "-"}
            </td>
          </tr>
        `;
      }).join("");
  return `
    <section class="panel" style="margin-top:14px; align-self:flex-start; width:100%;">
      <div class="panel-header" style="padding-bottom:10px; border-bottom:1px solid var(--border);">
        <div>
          <h2 style="font-size:13.5px; font-weight:700; margin:0;">Toss 최근 1년 주문 내역</h2>
          <p style="font-size:11px; margin:2px 0 0 0;">CLOSED 주문은 cursor 페이징, OPEN 주문은 별도 조회로 합칩니다.</p>
        </div>
        <span class="status-label status-${recent.length ? "success" : "not_evaluated"}">${recent.length}건</span>
      </div>
      <div class="panel-body" style="padding-top:12px;">
        <div style="overflow:auto;">
          <table class="compact-table">
            <thead>
              <tr>
                <th>주문시각</th><th>종목</th><th>방향</th><th>상태</th><th style="text-align:right;">금액</th><th style="text-align:right;">상세</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        ${renderSourceCaption(caption)}
        ${renderTossOrderDetailCard()}
      </div>
    </section>
  `;
}

// ──────────────────────────────────────────────
// 1. 투자 목표 & 계획 (goal-planner)
// ──────────────────────────────────────────────
function renderGoalPlanner() {
  const d = state.investmentGoals || {};
  const goals = d.goals || [];
  const solved = d.solved_goals || [];

  // 1. Calculate KPI Metrics
  const goalCount = goals.length;
  const totalTarget = goals.reduce((sum, g) => sum + (g.target_amount || 0), 0);
  const totalCurrent = goals.reduce((sum, g) => sum + (g.current_amount || 0), 0);
  
  const solvedValid = solved.filter(s => s.required_annual_return_pct != null && s.required_annual_return_pct > 0);
  const avgReturn = solvedValid.length > 0 
    ? (solvedValid.reduce((sum, s) => sum + s.required_annual_return_pct, 0) / solvedValid.length)
    : 0.0;

  // 2. Goal Lists
  const goalListHtml = goals.length === 0
    ? emptyTable("설정된 투자 목표가 없습니다.", "우측 새 목표 추가 폼에서 목표를 입력하세요.")
    : goals.map((g) => {
        const sv = (solved || []).find(s => s.goal_id === g.goal_id);
        const rateVal = sv ? pf_pct(sv.required_annual_return_pct) : "계산 불가";
        const isFeasible = sv ? sv.is_feasible : false;
        
        let barChartHtml = "";
        if (sv && sv.yearly_fv && sv.yearly_fv.length > 0) {
          const maxVal = Math.max(...sv.yearly_fv.map(y => y.fv), 1);
          const bars = sv.yearly_fv.map(y => {
            const pct = Math.min((y.fv / maxVal) * 100, 100);
            return `
              <div style="display:flex; flex-direction:column; align-items:center; gap:4px; flex:1;">
                <span style="font-size:9.5px; color:var(--muted); white-space:nowrap;">${pf_fmt(Math.round(y.fv / 10000))}만원</span>
                <div style="width:100%; background:var(--border); border-radius:3px; height:60px; display:flex; align-items:flex-end;">
                  <div style="width:100%; height:${pct.toFixed(1)}%; background:linear-gradient(180deg, #818cf8, #6366f1); border-radius:3px 3px 0 0; transition:height 0.4s;"></div>
                </div>
                <span style="font-size:9.5px; color:var(--muted);">${y.year}년</span>
              </div>
            `;
          }).join("");
          barChartHtml = `<div style="display:flex; gap:6px; align-items:flex-end; padding:8px 0; border-top:1px solid var(--border); margin-top:10px;">${bars}</div>`;
        }

        const curAmt = g.current_amount !== undefined ? g.current_amount : (g.current_value !== undefined ? g.current_value : 0);
        const tgtAmt = g.target_amount !== undefined ? g.target_amount : (g.target_value !== undefined ? g.target_value : 0);
        const monDep = g.monthly_deposit !== undefined ? g.monthly_deposit : (g.monthly_contribution !== undefined ? g.monthly_contribution : 0);
        
        let horizon = g.horizon_months;
        if (horizon === undefined && g.target_date) {
          try {
            const targetDt = new Date(g.target_date);
            const now = new Date();
            horizon = (targetDt.getFullYear() - now.getFullYear()) * 12 + (targetDt.getMonth() - now.getMonth());
          } catch(e) {}
        }
        if (horizon === undefined || horizon === null || isNaN(horizon) || horizon <= 0) {
          horizon = sv ? sv.months_remaining : 240;
        }

        return `
          <div class="panel" style="margin-bottom:14px; border-left:4px solid ${isFeasible ? "var(--success)" : "var(--warning)"};">
            <div class="panel-header" style="min-height:44px; padding:8px 12px;">
              <div>
                <h3 style="font-size:13.5px; font-weight:700; margin:0; display:inline-flex; align-items:center; gap:8px;">
                  🎯 ${pf_esc(g.name)}
                  <span class="status-label status-${isFeasible ? "success" : "warning"}">${pf_esc(g.goal_type || "일반")}</span>
                </h3>
              </div>
              <button class="button" data-delete-goal="${pf_esc(g.goal_id)}" style="min-height:26px; padding:2px 8px; font-size:11px; color:var(--failed); border-color:#e9958e; background:#feeceb;">삭제</button>
            </div>
            <div class="panel-body" style="padding:12px;">
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:12px; margin-bottom:10px;">
                <div style="display:flex; justify-content:space-between; border-bottom:1px solid #f1f5f9; padding-bottom:3px;">
                  <span style="color:var(--muted)">현재 자산 (PV)</span><strong>${pf_fmt(curAmt)}원</strong>
                </div>
                <div style="display:flex; justify-content:space-between; border-bottom:1px solid #f1f5f9; padding-bottom:3px;">
                  <span style="color:var(--muted)">목표 자산 (FV)</span><strong>${pf_fmt(tgtAmt)}원</strong>
                </div>
                <div style="display:flex; justify-content:space-between; border-bottom:1px solid #f1f5f9; padding-bottom:3px;">
                  <span style="color:var(--muted)">월 적립액 (PMT)</span><strong>${pf_fmt(monDep)}원</strong>
                </div>
                <div style="display:flex; justify-content:space-between; border-bottom:1px solid #f1f5f9; padding-bottom:3px;">
                  <span style="color:var(--muted)">목표 기간</span><strong>${horizon}개월 (${(horizon / 12).toFixed(1)}년)</strong>
                </div>
              </div>
              
              <div style="background:var(--surface-subtle); padding:10px; border-radius:6px; border:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
                <div>
                  <span style="font-size:11px; color:var(--muted); display:block;">목표 실현 필요 연 수익률</span>
                  <p style="font-size:11px; color:var(--muted); margin:2px 0 0 0;">${pf_esc(sv?.feasibility_comment || "")}</p>
                </div>
                <strong style="font-size:16px; color:${isFeasible ? "var(--success)" : "var(--warning)"}; font-weight:800;">${rateVal}</strong>
              </div>
              ${barChartHtml}
            </div>
          </div>
        `;
      }).join("");

  const lr = state.lossRecovery || {};
  let lrHtml = "";
  if (lr.break_even_return_pct) {
    const advices = lr.risk_reduction_advices || [];
    const recoveryMonths = lr.recovery_months_by_return || {};
    const depositScenarios = lr.deposit_scenarios_recovery_months_at_15pct || {};
    
    lrHtml = `
      <section class="panel" style="margin-top:20px;">
        <div class="panel-header" style="padding-bottom:10px; border-bottom:1px solid var(--border);">
          <div>
            <h2 style="font-size:13.5px; font-weight:700; margin:0;">📉 손실 복구 플랜 (Loss Recovery Planner)</h2>
            <p style="font-size:11px; margin:2px 0 0 0;">포트폴리오 평가 손실 발생 시 원금 복구를 위한 수학적 계산 및 추가 저축 단축 시나리오입니다.</p>
          </div>
          <span class="status-label status-warning">${lr.loss_pct}% 손실 기준</span>
        </div>
        <div class="panel-body" style="padding-top:12px;">
          <div class="status-banner status-warning" style="margin-bottom:14px; grid-template-columns:auto 1fr; border-left-width:3px; padding:10px 12px;">
            <div style="font-size:18px; margin-right:8px;">💡</div>
            <div>
              <strong style="font-size:12.5px; display:block; margin-bottom:2px;">원금 복구 필요 수익률: <span style="color:var(--failed); font-weight:800; font-size:13.5px;">+${lr.break_even_return_pct}%</span></strong>
              <span style="font-size:11.5px; color:var(--text); line-height:1.4;">손실금액: ${pf_fmt(lr.shortfall_amount_krw)}원. 손실이 커질수록 복구에 필요한 상승률은 기하급수적으로 증가합니다.</span>
            </div>
          </div>
          
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-bottom:14px;">
            <div>
              <h3 style="font-size:12px; font-weight:700; color:var(--text); margin:0 0 6px 0;">⏳ 무입금 자연 복구 기간 (DRIP만 활용)</h3>
              <ul style="font-size:11.5px; color:var(--muted); padding-left:16px; margin:0; line-height:1.6;">
                <li>연 8% 성장 시: <strong>${recoveryMonths["8pct_return"] ? recoveryMonths["8pct_return"] + "개월" : "계산 대기"}</strong></li>
                <li>연 15% 성장 시: <strong>${recoveryMonths["15pct_return"] ? recoveryMonths["15pct_return"] + "개월" : "계산 대기"}</strong></li>
                <li>연 25% 성장 시: <strong>${recoveryMonths["25pct_return"] ? recoveryMonths["25pct_return"] + "개월" : "계산 대기"}</strong></li>
              </ul>
            </div>
            <div>
              <h3 style="font-size:12px; font-weight:700; color:var(--text); margin:0 0 6px 0;">🚀 매월 추가 투자 시 복구 기간 (연 15% 가정)</h3>
              <ul style="font-size:11.5px; color:var(--muted); padding-left:16px; margin:0; line-height:1.6;">
                <li>월 50만원 추가: <strong>${depositScenarios.deposit_50ten_thousand_krw ? depositScenarios.deposit_50ten_thousand_krw + "개월" : "계산 대기"}</strong></li>
                <li>월 100만원 추가: <strong>${depositScenarios.deposit_100ten_thousand_krw ? depositScenarios.deposit_100ten_thousand_krw + "개월" : "계산 대기"}</strong></li>
                <li>월 200만원 추가: <strong>${depositScenarios.deposit_200ten_thousand_krw ? depositScenarios.deposit_200ten_thousand_krw + "개월" : "계산 대기"}</strong></li>
              </ul>
            </div>
          </div>

          <div style="background:var(--surface-subtle); padding:10px; border-radius:6px; border:1px solid var(--border); font-size:11.5px; line-height:1.5;">
            <strong style="display:block; margin-bottom:4px; color:var(--text); font-size:12px;">🛡️ 리스크 축소 및 원칙 대응 가이드</strong>
            ${advices.map(a => `<p style="margin:2px 0; color:var(--text);">${pf_esc(a)}</p>`).join("")}
          </div>
        </div>
      </section>
    `;
  }

  const orders = state.tossOrders || [];
  let tossTotalBuy = 0;
  let tossTotalSell = 0;
  let tossBuyCount = 0;
  let tossSellCount = 0;
  const tickerCounts = {};
  
  orders.forEach(o => {
    const status = o.status;
    if (status === "FILLED" || status === "PARTIAL_FILLED") {
      const exec = o.execution || {};
      const amt = parseFloat(exec.filledAmount || 0);
      const side = o.side;
      const currency = o.currency || "KRW";
      const rate = (currency === "USD") ? 1350.0 : 1.0;
      const amtKrw = amt * rate;
      
      const t = o.symbol.toUpperCase();
      tickerCounts[t] = (tickerCounts[t] || 0) + 1;
      
      if (side === "BUY") {
        tossTotalBuy += amtKrw;
        tossBuyCount++;
      } else if (side === "SELL") {
        tossTotalSell += amtKrw;
        tossSellCount++;
      }
    }
  });
  const tossNetInvested = tossTotalBuy - tossTotalSell;

  const topTickers = Object.entries(tickerCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([ticker, count]) => `${TOSS_TICKER_NAMES[ticker] || ticker} (${count}회)`)
    .join(", ") || "없음";

  const tossTradeStatsPanel = `
    <section class="panel" style="margin-top:14px; align-self: flex-start; width:100%;">
      <div class="panel-header" style="padding-bottom:10px; border-bottom:1px solid var(--border);">
        <div>
          <h2 style="font-size:13.5px; font-weight:700; margin:0;">🏷️ Toss 6개년 누적 거래 실적</h2>
          <p style="font-size:11px; margin:2px 0 0 0;">실계좌 주문 이력(최근 6년)을 기반으로 집계된 총 투자 투입금 명세입니다.</p>
        </div>
      </div>
      <div class="panel-body" style="padding-top:12px; display:flex; flex-direction:column; gap:10px;">
        <div style="display:flex; justify-content:space-between; font-size:12px;">
          <span style="color:var(--muted)">누적 총 매수 (${tossBuyCount}건)</span>
          <strong style="color:var(--success)">${pf_fmt(Math.round(tossTotalBuy))}원</strong>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:12px;">
          <span style="color:var(--muted)">누적 총 매도 (${tossSellCount}건)</span>
          <strong style="color:var(--failed)">${pf_fmt(Math.round(tossTotalSell))}원</strong>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:12px;">
          <span style="color:var(--muted)">주요 거래 종목 (TOP 3)</span>
          <strong style="color:var(--text)">${topTickers}</strong>
        </div>
        <div style="border-top:1px dashed var(--border); padding-top:8px; display:flex; justify-content:space-between; font-size:12.5px; font-weight:700;">
          <span>순자산 투입금 (Net Input)</span>
          <strong style="color:var(--text)">${pf_fmt(Math.round(tossNetInvested))}원</strong>
        </div>
      </div>
      ${renderSourceCaption(state.tossOrdersMeta?.source || "Toss Order History getOrders · GET /api/v1/orders")}
    </section>
  `;
  const tossOrderHistoryPanel = renderTossOrderHistoryPanel(orders);

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>투자 목표 &amp; 계획</h1>
        <p>목표 금액과 기간을 입력하면 미래 가치(FV) 방정식에 기초하여 실현에 필요한 연 수익률을 계산하고 연도별 시나리오를 시뮬레이션합니다.</p>
      </div>
      ${statusBadge(goals.length > 0 ? "success" : "not_evaluated")}
    </div>
    ${renderDataSourceNote("goal-planner")}
    ${renderOrderHistorySummaryPanel(state.orderHistorySummary, "goal-planner")}
    
    <section class="metric-grid">
      ${metricCard("목표 수", `${goalCount}개`, goalCount ? "success" : "not_evaluated", "등록된 투자 목표")}
      ${metricCard("총 목표금액", `${pf_fmt(Math.round(totalTarget / 10000))}만원`, totalTarget ? "success" : "not_evaluated", "미래 목표 자산 총합")}
      ${metricCard("현재 자산합", `${pf_fmt(Math.round(totalCurrent / 10000))}만원`, totalCurrent ? "success" : "not_evaluated", "현재 가치(PV) 총합")}
      ${metricCard("평균 필요수익률", avgReturn > 0 ? pf_pct(avgReturn) : "계산 불가", avgReturn > 15 ? "warning" : avgReturn > 0 ? "success" : "not_evaluated", "목표 달성 필요 평균 연익률")}
    </section>

    <div class="section-grid">
      <!-- Left side: Goals list -->
      <div style="display:flex; flex-direction:column;">
        <h2 style="font-size:14px; font-weight:700; margin:0 God 10px 0; color:var(--text);">📋 등록된 투자 목표 목록</h2>
        ${goalListHtml}
        ${lrHtml}
      </div>

      <!-- Right side: Add Goal Form & Trade stats -->
      <div style="display:flex; flex-direction:column; gap:14px;">
        <section class="panel" style="align-self: flex-start; width:100%;">
          <div class="panel-header">
            <div>
              <h2>➕ 새 투자 목표 추가</h2>
              <p>달성하려는 재무 목표를 설정하세요.</p>
            </div>
          </div>
          <div class="panel-body" style="display:flex; flex-direction:column; gap:12px;">
            <div>
              <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px;">목표 명칭</label>
              <input id="pf-goal-name" type="text" placeholder="예: 10억 은퇴 자금" style="width:100%; min-height:34px; padding:6px 9px; border:1px solid var(--border-strong); border-radius:6px; font-size:12.5px;">
            </div>
            <div>
              <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px;">유형 (Goal Type)</label>
              <select id="pf-goal-type" style="width:100%; min-height:34px; padding:6px 9px; border:1px solid var(--border-strong); border-radius:6px; font-size:12.5px;">
                <option value="retirement">🌱 retirement (은퇴 자금)</option>
                <option value="house">🏠 house (주택 구입)</option>
                <option value="education">🎓 education (자녀 학자금)</option>
                <option value="emergency">🛡️ emergency (비상금)</option>
                <option value="other">🎯 other (기타 목표)</option>
              </select>
            </div>
            <div>
              <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px;">현재 자산 (PV, 원화)</label>
              <input id="pf-goal-pv" type="number" placeholder="50000000" style="width:100%; min-height:34px; padding:6px 9px; border:1px solid var(--border-strong); border-radius:6px; font-size:12.5px;">
            </div>
            <div>
              <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px;">목표 자산 (FV, 원화)</label>
              <input id="pf-goal-fv" type="number" placeholder="1000000000" style="width:100%; min-height:34px; padding:6px 9px; border:1px solid var(--border-strong); border-radius:6px; font-size:12.5px;">
            </div>
            <div>
              <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px;">월 정기 적립액 (PMT, 원화)</label>
              <input id="pf-goal-pmt" type="number" placeholder="1000000" style="width:100%; min-height:34px; padding:6px 9px; border:1px solid var(--border-strong); border-radius:6px; font-size:12.5px;">
            </div>
            <div>
              <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px;">달성 목표 기간 (개월수)</label>
              <input id="pf-goal-months" type="number" placeholder="240" style="width:100%; min-height:34px; padding:6px 9px; border:1px solid var(--border-strong); border-radius:6px; font-size:12.5px;">
            </div>
            
            <div style="display:flex; gap:8px; margin-top:8px;">
              <button id="pf-goal-save" class="button button-primary" style="flex:1;">목표 저장</button>
              <button id="pf-goal-cancel" class="button button-secondary" style="flex:0 0 70px;">초기화</button>
            </div>
            <p id="pf-goal-msg" style="font-size:11px; margin:4px 0 0 0; color:var(--failed);" class="nowrap"></p>
          </div>
          ${renderSourceCaption("state/investment_goals.json")}
        </section>
        ${tossTradeStatsPanel}
        ${tossOrderHistoryPanel}
      </div>
    </div>
  `;

  // Bind Events
  document.querySelector("#pf-goal-cancel")?.addEventListener("click", () => {
    document.querySelector("#pf-goal-name").value = "";
    document.querySelector("#pf-goal-pv").value = "";
    document.querySelector("#pf-goal-fv").value = "";
    document.querySelector("#pf-goal-pmt").value = "";
    document.querySelector("#pf-goal-months").value = "";
    document.querySelector("#pf-goal-msg").textContent = "";
  });

  document.querySelector("#pf-goal-save")?.addEventListener("click", async () => {
    const msg = document.querySelector("#pf-goal-msg");
    const name = document.querySelector("#pf-goal-name").value.trim();
    const type = document.querySelector("#pf-goal-type").value;
    const pv = parseFloat(document.querySelector("#pf-goal-pv").value) || 0;
    const fv = parseFloat(document.querySelector("#pf-goal-fv").value) || 0;
    const pmt = parseFloat(document.querySelector("#pf-goal-pmt").value) || 0;
    const months = parseInt(document.querySelector("#pf-goal-months").value) || 0;

    if (!name) { msg.textContent = "⚠️ 목표 명칭을 입력하세요."; return; }
    if (fv <= 0) { msg.textContent = "⚠️ 목표 자산을 올바르게 입력하세요."; return; }
    if (months <= 0) { msg.textContent = "⚠️ 목표 기간(개월)을 1개월 이상 입력하세요."; return; }

    try {
      msg.textContent = "저장 중..."; msg.style.color = "var(--muted)";
      const res = await fetch("/api/v1/investment-goals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name,
          goal_type: type,
          current_value: pv,
          target_value: fv,
          monthly_contribution: pmt,
          horizon_months: months
        })
      });
      if (!res.ok) {
        const errPayload = await res.json().catch(() => ({}));
        throw new Error(errPayload.message || `HTTP ${res.status}`);
      }
      state.investmentGoals = null;
      navigate("goal-planner");
    } catch (e) {
      msg.textContent = `❌ 오류: ${e.message}`;
      msg.style.color = "var(--failed)";
    }
  });

  document.querySelectorAll("[data-delete-goal]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const gid = btn.dataset.deleteGoal;
      if (!confirm(`이 목표(ID: ${gid})를 정말로 삭제하시겠습니까?`)) return;
      try {
        const res = await fetch(`/api/v1/investment-goals/${encodeURIComponent(gid)}`, { method: "DELETE" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        state.investmentGoals = null;
        navigate("goal-planner");
      } catch (e) {
        alert(`삭제에 실패했습니다: ${e.message}`);
      }
    });
  });
}

// ──────────────────────────────────────────────
// 2. 현금흐름 배분 (cashflow)
// ──────────────────────────────────────────────
function renderCashflow() {
  const d = state.cashflows || {};
  const entries = d.entries || [];
  const budget = d.budget || {};

  // Calculations
  const totalIn = entries.filter(e => e.amount > 0).reduce((sum, e) => sum + e.amount, 0);
  const totalOut = entries.filter(e => e.amount < 0).reduce((sum, e) => sum + e.amount, 0);
  const netInvestable = totalIn + totalOut;

  const strategies = ["short_term", "swing", "long_term", "dividend"];
  const stratLabels = { short_term: "단기 전략 (Short-term Trading)", swing: "스윙 포지션 (Swing)", long_term: "장기 핵심 보유 (Long-term Core)", dividend: "정기 배당전략 (Dividend Growth)" };
  const stratColors = ["#4b7bec", "#8854d0", "#a55eea", "#2d98da"];
  const totalBudget = strategies.reduce((sum, k) => sum + (budget[k] || 0), 0);

  // Allocations Bars
  const allocationHtml = strategies.map((k, i) => {
    const amt = budget[k] || 0;
    const pct = totalBudget > 0 ? (amt / totalBudget * 100).toFixed(1) : "0.0";
    return `
      <div style="margin-bottom:12px;">
        <div style="display:flex; justify-content:space-between; margin-bottom:4px; font-size:12px;">
          <strong>${stratLabels[k]}</strong>
          <span style="font-variant-numeric: tabular-nums;">${pf_fmt(amt)}원 (${pct}%)</span>
        </div>
        <div style="background:var(--border); border-radius:4px; height:8px; overflow:hidden;">
          <div style="width:${pct}%; height:100%; background:${stratColors[i]}; border-radius:4px; transition:width 0.4s;"></div>
        </div>
      </div>
    `;
  }).join("");

  // Table rows
  const tableRows = entries.length === 0
    ? `<tr><td colspan="4" style="text-align:center; padding:20px; color:var(--muted);">등록된 가용 현금흐름 기록이 없습니다.</td></tr>`
    : entries.map(e => {
        const sign = e.amount >= 0 ? "+" : "";
        const isExpense = e.amount < 0;
        return `
          <tr>
            <td class="nowrap">${pf_esc(e.date)}</td>
            <td><span class="status-label status-${isExpense ? "failed" : "success"}">${pf_esc(e.category)}</span></td>
            <td><strong>${pf_esc(e.label)}</strong></td>
            <td class="numeric" style="color:${isExpense ? "var(--failed)" : "var(--success)"}; font-weight:700;">
              ${sign}${pf_fmt(e.amount)}원
            </td>
          </tr>
        `;
      }).join("");

  // Toss Monthly Flow Calculation
  const orders = state.tossOrders || [];
  const monthlyFlows = {};
  orders.forEach(o => {
    const status = o.status;
    if (status === "FILLED" || status === "PARTIAL_FILLED") {
      const exec = o.execution || {};
      const amt = parseFloat(exec.filledAmount || 0);
      const side = o.side;
      const currency = o.currency || "KRW";
      const rate = (currency === "USD") ? 1350.0 : 1.0;
      const amtKrw = amt * rate;
      
      const dateStr = o.orderedAt || "";
      if (dateStr.length >= 7) {
        const ym = dateStr.slice(0, 7);
        if (!monthlyFlows[ym]) {
          monthlyFlows[ym] = { buy: 0, sell: 0 };
        }
        if (side === "BUY") {
          monthlyFlows[ym].buy += amtKrw;
        } else if (side === "SELL") {
          monthlyFlows[ym].sell += amtKrw;
        }
      }
    }
  });

  const sortedMonths = Object.keys(monthlyFlows).sort().reverse().slice(0, 6);
  const monthlyRows = sortedMonths.map(ym => {
    const flow = monthlyFlows[ym];
    const net = flow.sell - flow.buy;
    const netColor = net >= 0 ? "var(--success)" : "var(--failed)";
    return `
      <tr>
        <td><strong>${ym}</strong></td>
        <td class="numeric" style="color:var(--success)">+${pf_fmt(Math.round(flow.sell))}원</td>
        <td class="numeric" style="color:var(--failed)">${pf_fmt(Math.round(flow.buy))}원</td>
        <td class="numeric" style="color:${netColor}; font-weight:700;">${net >= 0 ? "+" : ""}${pf_fmt(Math.round(net))}원</td>
      </tr>
    `;
  }).join("") || `<tr><td colspan="4" style="text-align:center; padding:10px; color:var(--muted);">Toss 실계좌 거래 이력이 없습니다.</td></tr>`;

  const tossFlowsPanel = `
    <section class="panel" style="margin-top:14px;">
      <div class="panel-header" style="padding-bottom:10px; border-bottom:1px solid var(--border);">
        <div>
          <h2 style="font-size:13.5px; font-weight:700; margin:0;">📊 Toss 실계좌 월별 매매 흐름 (최근 6개월)</h2>
          <p style="font-size:11px; margin:2px 0 0 0;">주문 체결 기록에서 집계된 월별 매수 및 매도 규모 흐름입니다.</p>
        </div>
      </div>
      <div class="table-wrap" style="padding-top:10px;">
        <table>
          <thead>
            <tr>
              <th>연월</th>
              <th class="numeric">총 매도액 (회수)</th>
              <th class="numeric">총 매수액 (투입)</th>
              <th class="numeric">순 현금흐름</th>
            </tr>
          </thead>
          <tbody>
            ${monthlyRows}
          </tbody>
        </table>
      </div>
      ${renderSourceCaption("state/toss_orders.json")}
    </section>
  `;

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>현금흐름 배분</h1>
        <p>월별 투자 예산 편성을 위해 고정 수입, 지출, 배당 유입을 기록하고 보유한 4대 운영 전략(단기/스윙/장기/배당)에 가용 자금을 분할 배분합니다.</p>
      </div>
      ${statusBadge(entries.length > 0 ? "success" : "not_evaluated")}
    </div>
    ${renderDataSourceNote("cashflow")}

    <section class="metric-grid">
      ${metricCard("총 수입", `+${pf_fmt(totalIn)}원`, totalIn ? "success" : "not_evaluated", "월별 급여, 배당 및 입금 합계")}
      ${metricCard("총 지출", `${pf_fmt(totalOut)}원`, totalOut ? "failed" : "success", "예비비 저축 및 고정 비용 누계")}
      ${metricCard("순 투자 가능액", `${netInvestable >= 0 ? "+" : ""}${pf_fmt(netInvestable)}원`, netInvestable >= 0 ? "success" : "failed", "전략 투입이 가능한 최종 순현금")}
      ${metricCard("배분 완료 예산", `${pf_fmt(totalBudget)}원`, totalBudget ? "success" : "not_evaluated", "4대 핵심 전략에 투입 대기 중인 자산")}
    </section>

    <div class="section-grid">
      <!-- Left: Table of Cashflow Items & Toss Trade Cash Flows -->
      <div style="display:flex; flex-direction:column;">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>📋 현금흐름 항목 내역</h2>
              <p>최근 유입되거나 유출된 자금의 역사적 흐름 기록입니다.</p>
            </div>
            <span class="muted">${entries.length}건 기록됨</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>날짜</th>
                  <th>카테고리</th>
                  <th>설명</th>
                  <th class="numeric">금액</th>
                </tr>
              </thead>
              <tbody>
                ${tableRows}
              </tbody>
            </table>
          </div>
          ${renderSourceCaption("state/cashflows.json")}
        </section>
        ${tossFlowsPanel}
      </div>

      <!-- Right: Allocations & Form -->
      <div style="display:flex; flex-direction:column; gap:14px;">
        <!-- Budget allocation card -->
        ${totalBudget > 0 ? `
          <section class="panel">
            <div class="panel-header">
              <div>
                <h2>📊 전략별 투자 예산 배분</h2>
                <p>순 투자 가능액을 리스크 성향 배분 비율에 맞춰 기계적으로 배분한 결과입니다.</p>
              </div>
            </div>
            <div class="panel-body">
              ${allocationHtml}
            </div>
            ${renderSourceCaption("cashflow_planner.py")}
          </section>
        ` : ""}

        <!-- Form panel -->
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>➕ 현금흐름 항목 추가</h2>
              <p>수입이나 지출 내역을 기입하세요.</p>
            </div>
          </div>
          <div class="panel-body" style="display:flex; flex-direction:column; gap:12px;">
            <div>
              <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px;">발생일자</label>
              <input id="pf-cf-date" type="date" style="width:100%; min-height:34px; padding:6px 9px; border:1px solid var(--border-strong); border-radius:6px; font-size:12.5px;" value="${new Date().toISOString().slice(0, 10)}">
            </div>
            <div>
              <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px;">카테고리 (Category)</label>
              <select id="pf-cf-cat" style="width:100%; min-height:34px; padding:6px 9px; border:1px solid var(--border-strong); border-radius:6px; font-size:12.5px;">
                <option value="salary">급여 (Salary)</option>
                <option value="dividend">배당 유입 (Dividend)</option>
                <option value="deposit">추가 예탁금 (Deposit)</option>
                <option value="expense">지출 / 출금 (Expense)</option>
                <option value="reserved">예비비 설정 (Reserved Cash)</option>
              </select>
            </div>
            <div>
              <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px;">적요 / 설명</label>
              <input id="pf-cf-label" type="text" placeholder="예: Toss 미국 주식 배당금" style="width:100%; min-height:34px; padding:6px 9px; border:1px solid var(--border-strong); border-radius:6px; font-size:12.5px;">
            </div>
            <div>
              <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px;">금액 (원화, 지출/출금은 마이너스값)</label>
              <input id="pf-cf-amount" type="number" placeholder="50000" style="width:100%; min-height:34px; padding:6px 9px; border:1px solid var(--border-strong); border-radius:6px; font-size:12.5px;">
            </div>

            <div style="display:flex; gap:8px; margin-top:8px;">
              <button id="pf-cf-save" class="button button-primary" style="flex:1;">기록 저장</button>
              <button id="pf-cf-cancel" class="button button-secondary" style="flex:0 0 70px;">초기화</button>
            </div>
            <p id="pf-cf-msg" style="font-size:11px; margin:4px 0 0 0; color:var(--failed);" class="nowrap"></p>
          </div>
          ${renderSourceCaption("state/cashflows.json")}
        </section>

        <!-- default salary settings card -->
        <section class="panel" style="margin-top:14px; align-self: flex-start; width:100%;">
          <div class="panel-header" style="padding-bottom:10px; border-bottom:1px solid var(--border);">
            <div>
              <h2 style="font-size:13px; font-weight:700; margin:0;">⚙️ 기본 월 급여 설정 (Salary Configuration)</h2>
              <p style="font-size:11px; margin:2px 0 0 0;">새 예산 계획 시 적용할 기본 월 급여 기준 액수입니다.</p>
            </div>
          </div>
          <div class="panel-body" style="padding-top:12px; display:flex; flex-direction:column; gap:10px;">
            <div>
              <label style="display:block; font-size:11px; color:var(--muted); margin-bottom:4px;">기본 급여액 (원화)</label>
              <input id="pf-cf-default-salary" type="number" value="${state.cashflowSettings ? state.cashflowSettings.default_salary_krw : 6500000}" style="width:100%; min-height:34px; padding:6px 9px; border:1px solid var(--border-strong); border-radius:6px; font-size:12.5px;">
            </div>
            <button id="pf-cf-settings-save" class="button button-primary" style="width:100%;">기본 설정 저장</button>
            <p id="pf-cf-settings-msg" style="font-size:11px; margin:4px 0 0 0; color:var(--success);" class="nowrap"></p>
          </div>
          ${renderSourceCaption("state/cashflow_settings.json")}
        </section>
      </div>
    </div>
  `;

  // Bind Events
  document.querySelector("#pf-cf-cancel")?.addEventListener("click", () => {
    document.querySelector("#pf-cf-label").value = "";
    document.querySelector("#pf-cf-amount").value = "";
    document.querySelector("#pf-cf-msg").textContent = "";
  });

  // Auto populate on category change
  document.querySelector("#pf-cf-cat")?.addEventListener("change", (e) => {
    const cat = e.target.value;
    const amountInput = document.querySelector("#pf-cf-amount");
    const labelInput = document.querySelector("#pf-cf-label");
    if (cat === "salary") {
      amountInput.value = state.cashflowSettings ? state.cashflowSettings.default_salary_krw : 6500000;
      labelInput.value = "월 정기 급여 유입";
    }
  });

  // Save Settings Event
  document.querySelector("#pf-cf-settings-save")?.addEventListener("click", async () => {
    const msg = document.querySelector("#pf-cf-settings-msg");
    const val = parseFloat(document.querySelector("#pf-cf-default-salary").value) || 0;
    if (val <= 0) { msg.textContent = "⚠️ 올바른 금액을 입력하세요."; msg.style.color = "var(--failed)"; return; }
    try {
      msg.textContent = "저장 중..."; msg.style.color = "var(--muted)";
      const res = await fetch("/api/v1/cashflows/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ default_salary_krw: val })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.cashflowSettings = { default_salary_krw: val };
      msg.textContent = "✅ 기본 설정이 정상 반영되었습니다.";
      msg.style.color = "var(--success)";
      
      // Auto update amount input value if salary cat is selected
      if (document.querySelector("#pf-cf-cat").value === "salary") {
        document.querySelector("#pf-cf-amount").value = val;
      }
    } catch (e) {
      msg.textContent = `❌ 오류: ${e.message}`;
      msg.style.color = "var(--failed)";
    }
  });

  document.querySelector("#pf-cf-save")?.addEventListener("click", async () => {
    const msg = document.querySelector("#pf-cf-msg");
    const date = document.querySelector("#pf-cf-date").value;
    const cat = document.querySelector("#pf-cf-cat").value;
    const label = document.querySelector("#pf-cf-label").value.trim();
    const amount = parseFloat(document.querySelector("#pf-cf-amount").value) || 0;

    if (!label) { msg.textContent = "⚠️ 설명 적요를 입력하세요."; return; }
    if (amount === 0) { msg.textContent = "⚠️ 0원이 아닌 유효금액을 입력하세요."; return; }

    try {
      msg.textContent = "저장 중..."; msg.style.color = "var(--muted)";
      const res = await fetch("/api/v1/cashflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          date: date,
          category: cat,
          label: label,
          amount: amount
        })
      });
      if (!res.ok) {
        const errPayload = await res.json().catch(() => ({}));
        throw new Error(errPayload.message || `HTTP ${res.status}`);
      }
      state.cashflows = null;
      navigate("cashflow");
    } catch (e) {
      msg.textContent = `❌ 오류: ${e.message}`;
      msg.style.color = "var(--failed)";
    }
  });
}

// ──────────────────────────────────────────────
// 3. 배당 시뮬레이션 (dividend-sim)
// ──────────────────────────────────────────────
function renderDividendSim() {
  const d = state.dividendSim;
  if (!d) {
    els.root.innerHTML = `
      <div class="page-heading">
        <div>
          <h1>배당 시뮬레이션</h1>
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

  const monthly = d.monthly_dividend_income || 0;
  const annual = d.annual_dividend_income || monthly * 12;
  const yieldPct = d.portfolio_yield_pct || 0;
  const holdings = d.holdings || [];
  const projections = d.reinvestment_projections || d.projections || {};

  // Projection bars for 1/3/5yr
  const projYears = [1, 3, 5];
  const projVals = projYears.map(y => projections[`${y}_year_value_krw`] || projections[`${y}yr`] || 0);
  const maxProj = Math.max(...projVals, 1);
  const projBarHtml = projYears.map((y, i) => {
    const v = projVals[i];
    const pct = (v / maxProj * 100).toFixed(1);
    return `
      <div style="flex:1; display:flex; flex-direction:column; align-items:center; gap:6px;">
        <span style="font-size:11px; font-weight:700; color:var(--text);">${pf_fmt(Math.round(v / 10000))}만원</span>
        <div style="width:100%; height:110px; background:var(--border); border-radius:6px; overflow:hidden; display:flex; align-items:flex-end;">
          <div style="width:100%; height:${pct}%; background:linear-gradient(180deg, #34d399, #10b981); border-radius:6px 6px 0 0; transition:height 0.5s ease;"></div>
        </div>
        <span style="font-size:11px; font-weight:700; color:var(--muted);">${y}년 후 자산</span>
      </div>
    `;
  }).join("");

  // Toss Trade-derived Dividend Estimation
  const orders = state.tossOrders || [];
  const symbolShares = {};
  orders.forEach(o => {
    const status = o.status;
    if (status === "FILLED" || status === "PARTIAL_FILLED") {
      const ticker = o.symbol.toUpperCase();
      const exec = o.execution || {};
      const qty = parseFloat(exec.filledQuantity || 0);
      const side = o.side;
      
      if (!symbolShares[ticker]) {
        symbolShares[ticker] = 0.0;
      }
      if (side === "BUY") {
        symbolShares[ticker] += qty;
      } else if (side === "SELL") {
        symbolShares[ticker] -= qty;
      }
    }
  });

  const defaultDividendProfiles = {
    "SCHD": { yield: 0.034, name: "Schwab US Dividend Equity ETF", price: 80.0 },
    "O": { yield: 0.055, name: "Realty Income Corp", price: 58.0 },
    "JEPI": { yield: 0.072, name: "JPMorgan Equity Premium Income ETF", price: 56.0 },
    "AAPL": { yield: 0.005, name: "Apple Inc.", price: 185.0 },
    "MSFT": { yield: 0.007, name: "Microsoft Corp.", price: 420.0 },
    "005930": { yield: 0.021, name: "삼성전자", price: 72000.0 }
  };

  const estimatedHoldings = [];
  Object.entries(symbolShares).forEach(([ticker, shares]) => {
    if (shares > 0) {
      const profile = defaultDividendProfiles[ticker] || { yield: 0.015, name: TOSS_TICKER_NAMES[ticker] || ticker, price: 100.0 };
      const isUs = !ticker.match(/^\d+$/);
      const rate = isUs ? 1350.0 : 1.0;
      const valueKrw = shares * profile.price * rate;
      const annualPayoutKrw = valueKrw * profile.yield;
      
      estimatedHoldings.push({
        ticker,
        name: TOSS_TICKER_NAMES[ticker] || profile.name,
        shares,
        valueKrw,
        yieldPct: profile.yield * 100,
        annualPayoutKrw
      });
    }
  });

  const estRows = estimatedHoldings.map(h => `
    <tr>
      <td><strong>${renderTicker(h.ticker)}</strong></td>
      <td><span style="font-size:11.5px; color:var(--muted);">${pf_esc(h.name)}</span></td>
      <td class="numeric">${h.shares}주</td>
      <td class="numeric" style="color:var(--success); font-weight:700;">+${pf_fmt(Math.round(h.annualPayoutKrw))}원</td>
    </tr>
  `).join("");
  
  const tossEstDividendPanel = `
    <section class="panel">
      <div class="panel-header" style="padding-bottom:10px; border-bottom:1px solid var(--border);">
        <div>
          <h2 style="font-size:13.5px; font-weight:700; margin:0;">💰 Toss 매매 이력 추정 배당 분석</h2>
          <p style="font-size:11px; margin:2px 0 0 0;">과거 체결된 순 매수 물량(매수-매도) 기준 추정 배당 연간 수입입니다.</p>
        </div>
      </div>
      <div class="table-wrap" style="padding-top:10px;">
        <table>
          <thead>
            <tr>
              <th>티커</th>
              <th>종목명</th>
              <th class="numeric">보유 수량</th>
              <th class="numeric">연 추정 배당</th>
            </tr>
          </thead>
          <tbody>
            ${estRows || `<tr><td colspan="4" style="text-align:center; padding:10px; color:var(--muted);">배당 매칭 종목이 없습니다.</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;

  // Table rows
  const holdingRows = holdings.length === 0
    ? `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--muted);">배당을 지급하는 보유 종목이 감지되지 않았습니다.</td></tr>`
    : holdings.map(h => `
        <tr>
          <td class="ticker-cell">${renderTicker(h.ticker)}</td>
          <td><span style="font-size:11.5px; color:var(--muted);">${pf_esc(h.name || "US Stock")}</span></td>
          <td class="numeric">${pf_fmt(h.value_krw || h.value)}원</td>
          <td class="numeric" style="color:var(--success); font-weight:700;">
            ${(h.dividend_yield != null ? (h.dividend_yield * 100).toFixed(2) : (h.yield_pct != null ? h.yield_pct.toFixed(2) : "0.00"))}%
          </td>
          <td class="numeric" style="color:var(--success); font-weight:700;">
            +${pf_fmt(h.annual_payout_krw || h.annual_dividend || 0)}원
          </td>
        </tr>
      `).join("");

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>배당 시뮬레이션</h1>
        <p>실시간 보유 자산 구조를 진단하여 월/연 배당 흐름을 추정하고, 배당 유입금을 전액 재투자(DRIP)하는 경우의 1년/3년/5년 누적 복리 성장 궤적을 연산합니다.</p>
      </div>
      ${statusBadge(holdings.length > 0 ? "success" : "not_evaluated")}
    </div>
    ${renderDataSourceNote("dividend-sim")}

    <section class="metric-grid">
      ${metricCard("월 예상 배당", `+${pf_fmt(Math.round(monthly))}원`, monthly ? "success" : "not_evaluated", "월평균 배당 권리 획득액")}
      ${metricCard("연 예상 배당", `+${pf_fmt(Math.round(annual))}원`, annual ? "success" : "not_evaluated", "포트폴리오 연간 총 배당 수입")}
      ${metricCard("배당 수익률", `${yieldPct.toFixed(2)}%`, yieldPct > 4.0 ? "success" : yieldPct > 0 ? "not_evaluated" : "failed", "포트폴리오 종합 배당 분배율")}
      ${metricCard("보유 배당주", `${holdings.length}개 종목`, holdings.length ? "success" : "not_evaluated", "현재 배당 지급 프로필 매칭 완료")}
    </section>

    <div class="section-grid">
      <!-- Left: Reinvestment Scenario & Living Expense Simulator & Toss estimation -->
      <div style="display:flex; flex-direction:column; gap:14px;">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>💹 배당 재투자 복리 성장 시나리오 (DRIP)</h2>
              <p>배당 수익률 and 자산 가치가 일정하며 분배 배당금 전액을 원형에 재복리 매수 투입한다고 가정한 성장 예측입니다.</p>
            </div>
          </div>
          <div class="panel-body" style="padding:20px 30px;">
            <div style="display:flex; gap:20px; align-items:flex-end; padding:10px 0;">
              ${projBarHtml}
            </div>
          </div>
          ${renderSourceCaption("dividend_cashflow_simulator.py · monthly compound model")}
        </section>
        ${tossEstDividendPanel}

        <!-- Dividend Living Expense Simulator -->
        ${(() => {
          const dle = state.dividendLivingExpense || {};
          if (!dle.monthly_target_krw) return "";
          const targetSnapshot = dle.drip_future_snapshots || {};
          return `
            <section class="panel">
              <div class="panel-header" style="padding-bottom:10px; border-bottom:1px solid var(--border);">
                <div>
                  <h2 style="font-size:13.5px; font-weight:700; margin:0;">🛡️ 배당 생활비 시뮬레이터 (Living Expense Simulator)</h2>
                  <p style="font-size:11px; margin:2px 0 0 0;">월 배당 목표액 대비 현재 수입과 목표 달성 달성도를 분석하고 복리 경로를 계산합니다.</p>
                </div>
                <span class="status-label status-success" style="font-size:11px; font-weight:700;">${dle.achievement_rate}% 달성</span>
              </div>
              <div class="panel-body" style="padding-top:12px;">
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-bottom:12px;">
                  <div style="background:var(--surface-subtle); padding:10px; border-radius:6px; border:1px solid var(--border); display:flex; flex-direction:column; justify-content:center;">
                    <span style="font-size:11px; color:var(--muted)">목표 월 배당금</span>
                    <strong style="font-size:16px; color:var(--text);">${pf_fmt(dle.monthly_target_krw)}원</strong>
                  </div>
                  <div style="background:var(--surface-subtle); padding:10px; border-radius:6px; border:1px solid var(--border); display:flex; flex-direction:column; justify-content:center;">
                    <span style="font-size:11px; color:var(--muted)">부족 월 배당금</span>
                    <strong style="font-size:16px; color:var(--failed);">${pf_fmt(dle.shortfall_krw)}원</strong>
                  </div>
                </div>

                <div style="font-size:12px; line-height:1.45; color:var(--text); margin-bottom:12px;">
                  목표 배당을 채우기 위해 필요한 추가 배당 투자금은 약 <strong>${pf_fmt(Math.round(dle.needed_additional_capital_krw / 10000))}만원</strong>입니다.<br>
                  추가 저축 없이 배당금 재투자(DRIP)만 유지할 시 목표 도달 예상 소요 기간은 <strong>${dle.years_to_goal_via_drip != null ? dle.years_to_goal_via_drip + "년" : "계산 불가"}</strong>입니다.
                </div>

                <div style="border-top:1px dashed var(--border); padding-top:10px; margin-bottom:14px;">
                  <h3 style="font-size:12px; font-weight:700; color:var(--text); margin:0 0 6px 0;">💡 DRIP 재투자 시 미래 예상 월 배당금</h3>
                  <ul style="font-size:11.5px; color:var(--muted); padding-left:16px; margin:0; line-height:1.5;">
                    <li>1년 후 월 배당: <strong>${pf_fmt(Math.round(targetSnapshot["1yr_monthly_dividend"] || 0))}원</strong></li>
                    <li>3년 후 월 배당: <strong>${pf_fmt(Math.round(targetSnapshot["3yr_monthly_dividend"] || 0))}원</strong></li>
                    <li>5년 후 월 배당: <strong>${pf_fmt(Math.round(targetSnapshot["5yr_monthly_dividend"] || 0))}원</strong></li>
                    <li>10년 후 월 배당: <strong>${pf_fmt(Math.round(targetSnapshot["10yr_monthly_dividend"] || 0))}원</strong></li>
                  </ul>
                </div>
                
                <div style="margin-top:10px; padding-top:10px; border-top:1px solid var(--border); display:flex; gap:8px; align-items:flex-end;">
                  <div style="flex:1;">
                    <label style="display:block; font-size:10px; color:var(--muted); margin-bottom:3px;">목표 월 배당금 변경 (원)</label>
                    <input id="pf-dle-target-input" type="number" value="${dle.monthly_target_krw}" style="width:100%; min-height:28px; padding:3px 6px; border:1px solid var(--border-strong); border-radius:4px; font-size:11.5px;">
                  </div>
                  <button id="pf-dle-target-save" class="button button-primary" style="min-height:28px; font-size:11px; padding:2px 8px;">목표 저장</button>
                </div>
              </div>
            </section>
          `;
        })()}
      </div>

      <!-- Right: Holdings Table -->
      <section class="panel">
        <div class="panel-header">
          <div>
            <h2>📊 종목별 배당 상세 내역</h2>
            <p>종목 마우스 오버 시 가설 카드 정보 툴팁이 활성화됩니다.</p>
          </div>
          <span class="muted">${holdings.length}개 보유</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>티커</th>
                <th>종목명</th>
                <th class="numeric">평가 금액</th>
                <th class="numeric">배당률</th>
                <th class="numeric">연 예상 배당</th>
              </tr>
            </thead>
            <tbody>
              ${holdingRows}
            </tbody>
          </table>
        </div>
        ${renderSourceCaption("toss_portfolio.csv · default_dividend_profiles")}
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
      state.dividendLivingExpense = null;
      navigate("dividend-sim");
    } catch (e) {
      alert(`배당 목표 저장에 실패했습니다: ${e.message}`);
    }
  });
}

// ──────────────────────────────────────────────
// 4. 투자 코치 & 다이어트 (investor-coach)
// ──────────────────────────────────────────────
function renderTradeBehaviorReviewPanel(data) {
  if (!data) {
    return `
      <section class="panel">
        <div class="panel-header"><div><h2>매매 습관 리뷰</h2><p>주문내역 기반 행동 리뷰 데이터를 불러오지 못했습니다.</p></div></div>
        ${renderSourceCaption("GET /api/v1/trade-behavior-review")}
      </section>
    `;
  }
  const summary = data.summary || {};
  const warnings = data.warnings || [];
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>매매 습관 리뷰</h2>
          <p>과거 주문내역에서 과열 거래, 취소율, 레버리지 집중, 빠른 손실 확정을 점검합니다.</p>
        </div>
        <span class="status-label status-${data.status === "success" ? "success" : data.status === "failed" ? "failed" : "warning"}">${data.behavior_score ?? "-"}점</span>
      </div>
      <section class="metric-grid" style="margin-top:12px;">
        ${metricCard("체결 거래", summary.filled_trade_count || 0, summary.filled_trade_count ? "success" : "not_evaluated", "Toss filled orders")}
        ${metricCard("최다 거래월", summary.peak_trade_month || "-", summary.peak_trade_month_count >= 12 ? "warning" : "success", `${summary.peak_trade_month_count || 0}건`)}
        ${metricCard("취소율", `${summary.cancel_ratio_pct ?? 0}%`, summary.cancel_ratio_pct >= 25 ? "warning" : "success", `${summary.cancel_count || 0}건 취소`)}
        ${metricCard("레버리지 비중", `${summary.leveraged_trade_ratio_pct ?? 0}%`, summary.leveraged_trade_ratio_pct >= 35 ? "warning" : "success", `${summary.leveraged_trade_count || 0}건`)}
      </section>
      <div class="panel-body" style="padding-top:12px;">
        ${warnings.length ? warnings.map(w => `
          <div class="status-banner status-${w.severity === "failed" ? "failed" : "warning"}" style="margin-bottom:10px; grid-template-columns:auto 1fr;">
            <div>${statusBadge(w.severity === "failed" ? "failed" : "warning")}</div>
            <div>
              <h2 style="font-size:12.5px;margin:0 0 4px">${pf_esc(w.code)}</h2>
              <p style="font-size:11.5px;margin:0;color:var(--text);">${pf_esc(w.message)}</p>
              <p style="font-size:11.5px;margin:4px 0 0;color:var(--muted);">${pf_esc(w.recommendation)}</p>
            </div>
          </div>
        `).join("") : `<div class="empty-state"><strong>주요 매매 습관 경고가 없습니다.</strong><span>현재 주문내역 기준으로 과열 패턴이 크지 않습니다.</span></div>`}
      </div>
      ${renderSourceCaption(data.source || "state/toss_orders.json · trade_behavior_review.py")}
    </section>
  `;
}

function renderInvestorCoach() {
  const bi = state.behaviorInsights || {};
  const pd = state.portfolioDiet || {};

  // Bias Warnings mapping into system style banners
  const biases = bi.warnings || bi.biases || [];
  
  const biasListHtml = biases.length === 0
    ? `
      <div class="empty-state">
        <strong>감지된 행동 편향 없음</strong>
        <span>시스템 검증 규칙을 충실히 따르고 있어 행동 오버트레이딩 징후가 발견되지 않았습니다.</span>
      </div>
    `
    : biases.map(b => {
        const levelClass = b.level === "danger" ? "failed" : (b.level === "warning" ? "warning" : "validating");
        return `
          <div class="status-banner status-${levelClass}" style="margin-bottom:12px; grid-template-columns: auto 1fr;">
            <div>${statusBadge(levelClass)}</div>
            <div>
              <h2 style="font-weight:700; font-size:13.5px; margin:0 0 4px 0;">
                ${pf_esc(b.bias || b.tag || b.type)}
              </h2>
              <p style="font-size:12px; line-height:1.4; color:var(--text);">${pf_esc(b.message || b.description)}</p>
              ${b.recommendation ? `
                <div style="margin-top:6px; padding:6px 10px; background:rgba(255,255,255,0.5); border-radius:4px; font-size:11.5px; border:1px solid rgba(0,0,0,0.04);">
                  <strong>💡 대응 가이드:</strong> ${pf_esc(b.recommendation)}
                </div>
              ` : ""}
            </div>
          </div>
        `;
      }).join("");

  // Diet suggestions
  const pruneList = pd.diet_recommendations || pd.prune_candidates || [];
  const redundancies = pd.redundancy_warnings || pd.redundancy_flags || [];

  let dietHtml = "";
  if (pruneList.length === 0 && redundancies.length === 0) {
    dietHtml = `
      <div class="empty-state">
        <strong>포트폴리오 다이어트 완료</strong>
        <span>1% 미만의 극소액 종목 및 레버리지 자산 중복 노출이 존재하지 않는 깔끔한 구조입니다.</span>
      </div>
    `;
  } else {
    const redundanciesHtml = redundancies.map(r => `
      <div style="background:#fff7ed; border:1px solid #fed7aa; border-radius:6px; padding:10px; margin-bottom:8px;">
        <span class="status-label status-warning" style="margin-bottom:4px;">⚠️ ${pf_esc(r.type || "중복성 검출")}</span>
        <strong style="display:block; font-size:12px; color:#c2410c; margin-top:2px;">관련 자산: ${pf_esc((r.tickers || []).join(", "))}</strong>
        <p style="font-size:11.5px; line-height:1.35; color:#7c2d12; margin:4px 0 0 0;">${pf_esc(r.reason || r.detail)}</p>
      </div>
    `).join("");

    const prunesHtml = pruneList.map(p => `
      <div style="background:#f8fafc; border:1px solid var(--border); border-radius:6px; padding:10px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
        <div>
          <span class="status-label status-not-evaluated" style="margin-bottom:4px;">✂️ 다이어트 대상</span>
          <strong style="display:block; font-size:12.5px; margin-top:2px;">
            ${pf_esc(p.category || "소액 포지션")} 
            ${p.tickers ? `<span class="code">${pf_esc(p.tickers.join(", "))}</span>` : ""}
          </strong>
          <p style="font-size:11.5px; color:var(--muted); margin:4px 0 0 0;">${pf_esc(p.message || "")}</p>
        </div>
      </div>
    `).join("");

    dietHtml = redundanciesHtml + prunesHtml;
  }

  // Coaching Score logic
  const scoreData = state.personalScore || {};
  const score = scoreData.total_score != null ? scoreData.total_score : (bi.coaching_score || 85);
  const scoreStatus = score >= 90 ? "success" : (score >= 70 ? "warning" : "failed");
  const grade = scoreData.grade || (score >= 90 ? "A" : (score >= 70 ? "B" : "C"));

  let scorePanelHtml = "";
  if (scoreData.total_score != null) {
    const bd = scoreData.breakdown || {};
    const scoreClass = scoreData.total_score >= 80 ? "success" : (scoreData.total_score >= 70 ? "warning" : "failed");
    scorePanelHtml = `
      <section class="panel" style="margin-bottom:14px;">
        <div class="panel-header">
          <div>
            <h2>🎯 개인 투자 점수판 세부 분석 (Scorecard Detail)</h2>
            <p>다차원 정량 매매 행동 진단입니다. 각 부문별 배점 대비 감점 요인을 보여줍니다.</p>
          </div>
          <span class="status-label status-${scoreClass}" style="font-size:12px; font-weight:700;">${grade} (${scoreData.total_score}점)</span>
        </div>
        <div class="panel-body">
          <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px;">
            <div style="background:var(--surface-subtle); padding:10px; border-radius:6px; border:1px solid var(--border);">
              <div style="display:flex; justify-content:space-between; font-size:11.5px; margin-bottom:4px;">
                <strong>🛡️ 리스크 준수율</strong>
                <span>${bd.risk_compliance_score} / 25</span>
              </div>
              <div style="background:var(--border); border-radius:3px; height:6px; overflow:hidden;">
                <div style="width:${(bd.risk_compliance_score / 25 * 100)}%; height:100%; background:var(--success); border-radius:3px;"></div>
              </div>
            </div>
            <div style="background:var(--surface-subtle); padding:10px; border-radius:6px; border:1px solid var(--border);">
              <div style="display:flex; justify-content:space-between; font-size:11.5px; margin-bottom:4px;">
                <strong>😰 손실 회피 준수</strong>
                <span>${bd.loss_avoidance_score} / 25</span>
              </div>
              <div style="background:var(--border); border-radius:3px; height:6px; overflow:hidden;">
                <div style="width:${(bd.loss_avoidance_score / 25 * 100)}%; height:100%; background:var(--success); border-radius:3px;"></div>
              </div>
            </div>
            <div style="background:var(--surface-subtle); padding:10px; border-radius:6px; border:1px solid var(--border);">
              <div style="display:flex; justify-content:space-between; font-size:11.5px; margin-bottom:4px;">
                <strong>🔄 거래 빈도 조절</strong>
                <span>${bd.trading_frequency_score} / 20</span>
              </div>
              <div style="background:var(--border); border-radius:3px; height:6px; overflow:hidden;">
                <div style="width:${(bd.trading_frequency_score / 20 * 100)}%; height:100%; background:var(--success); border-radius:3px;"></div>
              </div>
            </div>
            <div style="background:var(--surface-subtle); padding:10px; border-radius:6px; border:1px solid var(--border);">
              <div style="display:flex; justify-content:space-between; font-size:11.5px; margin-bottom:4px;">
                <strong>💵 자금 관리 평단</strong>
                <span>${bd.cash_management_score} / 15</span>
              </div>
              <div style="background:var(--border); border-radius:3px; height:6px; overflow:hidden;">
                <div style="width:${(bd.cash_management_score / 15 * 100)}%; height:100%; background:var(--success); border-radius:3px;"></div>
              </div>
            </div>
          </div>
        </div>
      </section>
    `;
  }

  const journalData = state.journals || {};
  const journalEntries = journalData.journals || [];
  
  const journalRows = journalEntries.length === 0
    ? `<tr><td colspan="8" style="text-align:center; padding:20px; color:var(--muted);">등록된 투자 일지 기록이 없습니다. 신호 승인/보류 시의 사유가 자동으로 기록됩니다.</td></tr>`
    : journalEntries.map(j => {
        const perf5 = j.return_5d_pct != null ? `${j.return_5d_pct >= 0 ? "+" : ""}${j.return_5d_pct}%` : "대기 중";
        const perf20 = j.return_20d_pct != null ? `${j.return_20d_pct >= 0 ? "+" : ""}${j.return_20d_pct}%` : "대기 중";
        const color5 = j.return_5d_pct != null ? (j.return_5d_pct >= 0 ? "var(--success)" : "var(--failed)") : "var(--muted)";
        const color20 = j.return_20d_pct != null ? (j.return_20d_pct >= 0 ? "var(--success)" : "var(--failed)") : "var(--muted)";
        
        return `
          <tr>
            <td class="nowrap">${formatDate(j.created_at)}</td>
            <td class="ticker-cell">${renderTicker(j.ticker)}</td>
            <td><span class="status-label status-${j.action_type === "approve" ? "success" : j.action_type === "hold" ? "warning" : "not-evaluated"}">${j.action_type === "approve" ? "승인" : j.action_type === "hold" ? "보류" : "무시"}</span></td>
            <td class="numeric">$${pf_fmt(j.entry_price, 2)}</td>
            <td class="numeric" style="color:${color5}; font-weight:700;">${perf5}</td>
            <td class="numeric" style="color:${color20}; font-weight:700;">${perf20}</td>
            <td style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${pf_esc(j.note)}">${pf_esc(j.note)}</td>
            <td>
              <button class="button" data-delete-journal="${pf_esc(j.entry_id)}" style="min-height:24px; padding:1px 6px; font-size:10px; color:var(--failed); border-color:#e9958e; background:#feeceb;">삭제</button>
            </td>
          </tr>
        `;
      }).join("");

  const journalPanelHtml = `
    <section class="panel" style="margin-top:20px; width:100%;">
      <div class="panel-header">
        <div>
          <h2>📋 의사결정 투자 일지 &amp; 사후 복기 (Decision Journal &amp; Retro)</h2>
          <p>수동 의사결정 시 입력된 메모가 일지로 저장되며, 결정 5일/20일 뒤의 실제 종목 수익률을 자동 역산하여 판단의 정확성을 복기합니다.</p>
        </div>
        <span class="muted">${journalEntries.length}개 일지 존재</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>작성일시</th>
              <th>종목</th>
              <th>의사결정</th>
              <th class="numeric">결정 시가</th>
              <th class="numeric">5일 후 성과</th>
              <th class="numeric">20일 후 성과</th>
              <th>의사결정 사유 및 근거</th>
              <th>관리</th>
            </tr>
          </thead>
          <tbody>
            ${journalRows}
          </tbody>
        </table>
      </div>
      ${renderSourceCaption("state/investment_journal.json · yfinance outcomes tracking")}
    </section>
  `;

  // Toss Habits Coaching Calculations
  const coachOrders = state.tossOrders || [];
  let numCancel = coachOrders.filter(o => o.status === "CANCELED").length;
  let numBuy = coachOrders.filter(o => o.side === "BUY" && (o.status === "FILLED" || o.status === "PARTIAL_FILLED")).length;
  let numSell = coachOrders.filter(o => o.side === "SELL" && (o.status === "FILLED" || o.status === "PARTIAL_FILLED")).length;
  
  const tradeCountsByMonth = {};
  coachOrders.forEach(o => {
    if (o.status === "FILLED" || o.status === "PARTIAL_FILLED") {
      const ym = (o.orderedAt || "").slice(0, 7);
      if (ym) {
        tradeCountsByMonth[ym] = (tradeCountsByMonth[ym] || 0) + 1;
      }
    }
  });
  
  const peakTradeMonth = Object.entries(tradeCountsByMonth).reduce((peak, [ym, count]) => {
    return count > peak.count ? { ym, count } : peak;
  }, { ym: "N/A", count: 0 });
  
  const overtradingFlag = peakTradeMonth.count > 10;

  const overtradingBanner = overtradingFlag 
    ? `<div class="status-banner status-failed" style="margin-bottom:10px; padding:10px; grid-template-columns:auto 1fr; border-left-width:3px;">
         <div style="font-size:16px; margin-right:8px;">🔄</div>
         <div>
           <strong style="font-size:12.5px; display:block;">과잉 거래 경고 (${peakTradeMonth.ym}월 기준 ${peakTradeMonth.count}회 체결)</strong>
           <p style="font-size:11.5px; margin:2px 0 0 0; color:var(--text); line-height:1.4;">한 달에 10회 이상의 잦은 실계좌 거래는 불필요한 거래 수수료를 발생시키며 매매 원칙을 해치기 쉽습니다.</p>
         </div>
       </div>`
    : `<div class="status-banner status-success" style="margin-bottom:10px; padding:10px; grid-template-columns:auto 1fr; border-left-width:3px;">
         <div style="font-size:16px; margin-right:8px;">✅</div>
         <div>
           <strong style="font-size:12.5px; display:block;">적정 거래 빈도 유지</strong>
           <p style="font-size:11.5px; margin:2px 0 0 0; color:var(--text); line-height:1.4;">월별 거래 빈도가 안정적이며 감정적인 거래 유혹을 잘 통제하고 있습니다.</p>
         </div>
       </div>`;

  const cancelRatio = numCancel / (numBuy + numSell + numCancel || 1);
  const cancelBanner = (cancelRatio > 0.3)
    ? `<div class="status-banner status-warning" style="margin-bottom:10px; padding:10px; grid-template-columns:auto 1fr; border-left-width:3px;">
         <div style="font-size:16px; margin-right:8px;">⚠️</div>
         <div>
           <strong style="font-size:12.5px; display:block;">잦은 주문 정정/취소 경고 (취소율 ${(cancelRatio * 100).toFixed(1)}%)</strong>
           <p style="font-size:11.5px; margin:2px 0 0 0; color:var(--text); line-height:1.4;">주문 취소 비중이 상대적으로 높습니다. 호가 변동에 뇌동 반응하기보다 신중히 진입가를 판단한 후 예약매매 위주로 집행하십시오.</p>
         </div>
       </div>`
    : `<div class="status-banner status-success" style="margin-bottom:10px; padding:10px; grid-template-columns:auto 1fr; border-left-width:3px;">
         <div style="font-size:16px; margin-right:8px;">✅</div>
         <div>
           <strong style="font-size:12.5px; display:block;">주문 집행 일관성 우수</strong>
           <p style="font-size:11.5px; margin:2px 0 0 0; color:var(--text); line-height:1.4;">한 번 내려진 매매 주문이 취소되거나 흔들리지 않고 원칙대로 잘 실행되고 있습니다.</p>
         </div>
       </div>`;

  const hasLeveraged = coachOrders.some(o => ["TQQQ", "SOXL", "NVDL", "NVDX", "MSTX"].includes(o.symbol.toUpperCase()));
  const leveragedBanner = hasLeveraged
    ? `<div class="status-banner status-warning" style="margin-bottom:10px; padding:10px; grid-template-columns:auto 1fr; border-left-width:3px;">
         <div style="font-size:16px; margin-right:8px;">⚠️</div>
         <div>
           <strong style="font-size:12.5px; display:block;">고위험 레버리지 포지션 감지 (TQQQ, SOXL 등)</strong>
           <p style="font-size:11.5px; margin:2px 0 0 0; color:var(--text); line-height:1.4;">거래 이력 중 레버리지 상품이 확인됩니다. 3배 레버리지는 횡보 장세에서 변동성 끌림(Volatility Drag)으로 인해 원금이 깎이므로, 중장기 보유 비중을 줄이고 패시브 지수로의 이동을 권고합니다.</p>
         </div>
       </div>`
    : "";

  const hasDividends = coachOrders.some(o => ["SCHD", "O", "JEPI"].includes(o.symbol.toUpperCase()));
  const dividendBanner = hasDividends
    ? `<div class="status-banner status-success" style="margin-bottom:10px; padding:10px; grid-template-columns:auto 1fr; border-left-width:3px;">
         <div style="font-size:16px; margin-right:8px;">🌱</div>
         <div>
           <strong style="font-size:12.5px; display:block;">우량 배당 연계 거래 확인 (SCHD, Realty Income)</strong>
           <p style="font-size:11.5px; margin:2px 0 0 0; color:var(--text); line-height:1.4;">SCHD, Realty Income 등 안정적인 연 배당형 자산 거래가 감지되었습니다. 장기적 복리 재투자(DRIP) 전략을 연계해 나가는 습관은 우수합니다.</p>
         </div>
       </div>`
    : "";

  const sellRatio = numSell / (numBuy + numSell || 1);
  const sellPatternBanner = (sellRatio > 0.4)
    ? `<div class="status-banner status-failed" style="margin-bottom:10px; padding:10px; grid-template-columns:auto 1fr; border-left-width:3px;">
         <div style="font-size:16px; margin-right:8px;">🏃</div>
         <div>
           <strong style="font-size:12.5px; display:block;">높은 매도 회전율 감지 (매도 비중 ${(sellRatio * 100).toFixed(1)}%)</strong>
           <p style="font-size:11.5px; margin:2px 0 0 0; color:var(--text); line-height:1.4;">매수 후 장기 보유하기보다는 잦은 매도를 통해 실현 손익을 조기 확정하고 있습니다. 이는 주식 복리 성장을 방해하므로 매매 템포를 늦추십시오.</p>
         </div>
       </div>`
    : `<div class="status-banner status-success" style="margin-bottom:10px; padding:10px; grid-template-columns:auto 1fr; border-left-width:3px;">
         <div style="font-size:16px; margin-right:8px;">🧘</div>
         <div>
           <strong style="font-size:12.5px; display:block;">장기 인내형 포지션 유지 (매도 비중 ${(sellRatio * 100).toFixed(1)}%)</strong>
           <p style="font-size:11.5px; margin:2px 0 0 0; color:var(--text); line-height:1.4;">매도 회전율이 매우 낮습니다. 불필요한 시장 진입/퇴출 수수료를 차단하고 장기 자산 가치 복리 상승을 유도하는 우수한 태도입니다.</p>
         </div>
       </div>`;

  const tossCoachPanel = `
    <section class="panel" style="margin-top:14px;">
      <div class="panel-header" style="padding-bottom:10px; border-bottom:1px solid var(--border);">
        <div>
          <h2 style="font-size:13.5px; font-weight:700; margin:0;">🤖 Toss 실계좌 거래 습관 진단 (Trade Habit Audit)</h2>
          <p style="font-size:11px; margin:2px 0 0 0;">6개년 실계좌 거래 이력을 바탕으로 한 심리적 행동 피드백입니다.</p>
        </div>
      </div>
      <div class="panel-body" style="padding-top:12px;">
        ${overtradingBanner}
        ${cancelBanner}
        ${leveragedBanner}
        ${dividendBanner}
        ${sellPatternBanner}
        <div style="background:var(--surface-subtle); padding:10px; border-radius:6px; border:1px solid var(--border); font-size:11.5px; line-height:1.45;">
          <strong>💡 실계좌 피드백 코칭</strong><br>
          6년 누적 매수 ${numBuy}회, 매도 ${numSell}회, 주문 취소 ${numCancel}회가 분석되었습니다. 거래량이 급증하는 장 초반 30분에 뇌동매매를 하지 않는 것만으로도 행동 등급을 추가로 높일 수 있습니다.
        </div>
      </div>
      ${renderSourceCaption("state/toss_orders.json")}
    </section>
  `;

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>투자 코치 &amp; 다이어트</h1>
        <p>수동 주문 승인 기록을 종합 분석하여 인간 투자자 고유의 행동 편향(FOMO, 잦은 거래, 손절 기피)을 진단하고, 자산 분산을 해치는 마이크로 포지션을 다이어트 조치합니다.</p>
      </div>
      ${statusBadge(scoreStatus, "습관 점수")}
    </div>
    ${renderDataSourceNote("investor-coach")}
    ${renderOrderHistorySummaryPanel(state.orderHistorySummary, "investor-coach")}

    <section class="metric-grid">
      ${metricCard("코칭 점수", `${score}점`, scoreStatus, "거래 감사 내역 기반 정량 습관 평가")}
      ${metricCard("총 승인 거래", `${bi.total_decisions_analyzed || 0}건`, "success", `최근 승인율: ${bi.biases_detected?.overtrading_approvals || 0}건`)}
      ${metricCard("감지된 편향", `${biases.length}개 편향`, biases.length ? "warning" : "success", "심리학적 편향 징후 감지 수")}
      ${metricCard("다이어트 종목", `${pruneList.length + redundancies.length}개 대상`, (pruneList.length + redundancies.length) ? "warning" : "success", "정리 또는 축소 권장 종목")}
    </section>

    ${scorePanelHtml}

    <div class="section-grid">
      <!-- Left: Behavior Insights -->
      <section class="panel">
        <div class="panel-header">
          <div>
            <h2>🧬 행동 편향 감지 리포트 (Behavior Bias Insights)</h2>
            <p>승인 가설 위반 여부를 스캔한 결과 검출된 심리적 편향 내역입니다.</p>
          </div>
        </div>
        <div class="panel-body">
          ${biasListHtml}
        </div>
        ${renderSourceCaption("state/user_approval_audit.jsonl · investor_behavior_insights.py")}
      </section>

      <!-- Right: Diet Mode & Toss Habit Audit -->
      <div style="display:flex; flex-direction:column; gap:14px;">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>✂️ 포트폴리오 다이어트 가이드 (Portfolio Diet)</h2>
              <p>비중 1% 미만 미세 자산 및 중복 테크/레버리지 제거 권고사항입니다.</p>
            </div>
          </div>
          <div class="panel-body">
            ${dietHtml}
          </div>
          ${renderSourceCaption("portfolio_diet_mode.py · toss_portfolio.csv")}
        </section>
        ${renderTradeBehaviorReviewPanel(state.tradeBehaviorReview)}
        ${tossCoachPanel}
      </div>
    </div>

    ${journalPanelHtml}
    ${renderOrderHistoryJournalPanel(state.orderHistorySummary)}
  `;

  // Bind delete journal events
  document.querySelectorAll("[data-delete-journal]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const jid = btn.dataset.deleteJournal;
      if (!confirm(`이 일지 기록(ID: ${jid})을 정말로 삭제하시겠습니까?`)) return;
      try {
        const res = await fetch(`/api/v1/investment-journals?entry_id=${encodeURIComponent(jid)}`, { method: "DELETE" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        state.journals = null;
        navigate("investor-coach");
      } catch (e) {
        alert("일지 삭제 실패: " + e.message);
      }
    });
  });
}

function biasIcon(type) {
  const icons = { overtrading: "🔄", fomo: "😱", loss_aversion: "😰", early_profit_taking: "🏃", averaging_down: "📉" };
  return icons[type] || "⚠️";
}

// ──────────────────────────────────────────────
// 5. 투자 캘린더 (invest-calendar)
// ──────────────────────────────────────────────
function renderInvestCalendar() {
  const d = state.investCalendar;
  if (!d) {
    els.root.innerHTML = `
      <div class="page-heading">
        <div>
          <h1>투자 캘린더</h1>
          <p>배당락일, 실적발표, 거시 경제 지표 발표 및 개인 급여/투자 일정</p>
        </div>
      </div>
      <div class="empty-state" style="margin-top:20px;">
        <strong>캘린더 데이터를 불러오지 못했습니다.</strong>
      </div>
    `;
    return;
  }

  const events = d.events || [];
  const orders = state.tossOrders || [];
  
  // Parse Toss orders into calendar events
  const tossEvents = orders.filter(o => o.status === "FILLED" || o.status === "PARTIAL_FILLED").map(o => {
    const side = o.side;
    const exec = o.execution || {};
    const filledQty = exec.filledQuantity || "0";
    const avgPrice = exec.averageFilledPrice || o.price;
    const commission = exec.commission || "0";
    const currency = o.currency || "KRW";
    const stockName = TOSS_TICKER_NAMES[o.symbol.toUpperCase()] || o.symbol;
    
    return {
      date: (o.orderedAt || "").slice(0, 10),
      type: "toss_order",
      title: `${side === "BUY" ? "🟢 Toss 매수 체결" : "🔴 Toss 매도 체결"} [${stockName}]`,
      description: `${filledQty}주 체결 @ 평균 ${avgPrice} ${currency} (수수료: ${commission} ${currency})`,
      ticker: o.symbol
    };
  });

  const allEvents = [...events, ...tossEvents];
  const today = new Date().toISOString().slice(0, 10);

  // Group by date
  const grouped = {};
  allEvents.forEach(e => {
    const dt = e.date || "unknown";
    if (!grouped[dt]) grouped[dt] = [];
    grouped[dt].push(e);
  });

  const sortedDates = Object.keys(grouped).sort().reverse(); // Show newest dates first so historical transactions are accessible

  const eventTypeStyle = {
    ex_dividend: { class: "success", icon: "🌱", label: "배당락 (Ex-Div)" },
    earnings: { class: "validating", icon: "📊", label: "실적 발표 (Earnings)" },
    macro: { class: "warning", icon: "🏛️", label: "거시 지표 (Macro)" },
    salary: { class: "success", icon: "💵", label: "급여 유입 (Salary)" },
    fomc: { class: "failed", icon: "🏦", label: "FOMC 결정" },
    toss_order: { class: "eligible", icon: "💸", label: "Toss 체결 이력" }
  };
  const defaultStyle = { class: "not-evaluated", icon: "📌", label: "기타 일정" };

  const calHtml = sortedDates.length === 0
    ? `
      <div class="empty-state">
        <strong>등록된 투자 일정이 존재하지 않습니다.</strong>
      </div>
    `
    : sortedDates.map(dt => {
        const isPast = dt < today;
        const isToday = dt === today;
        const dayEvts = grouped[dt];
        
        return `
          <div style="display:flex; gap:16px; margin-bottom:12px; opacity:${isPast ? "0.85" : "1"};">
            <div style="min-width:76px; text-align:right; padding-top:4px;">
              <div style="font-size:14px; font-weight:800; color:${isToday ? "var(--accent)" : "var(--text)"};">${dt.slice(5)}</div>
              <div style="font-size:10px; color:var(--muted);">${dt.slice(0, 4)}</div>
              ${isToday ? `<span class="status-label status-validating" style="font-size:8.5px; padding:1px 3px; min-height:auto; margin-top:2px;">TODAY</span>` : ""}
            </div>
            
            <div style="flex:1; display:flex; flex-direction:column; gap:6px;">
              ${dayEvts.map(e => {
                const s = eventTypeStyle[e.type] || defaultStyle;
                return `
                  <div class="status-banner status-${s.class}" style="margin-bottom:0; padding:10px 12px; grid-template-columns: auto 1fr auto; border-left-width:3px;">
                    <div style="font-size:16px; display:flex; align-items:center;">${s.icon}</div>
                    <div style="padding-left:4px;">
                      <strong style="font-size:12px; display:block;">[${pf_esc(s.label)}] ${pf_esc(e.title || e.label || "")}</strong>
                      <span style="font-size:11px; color:var(--muted); display:block; margin-top:2px;">${pf_esc(e.description || e.detail || "")}</span>
                    </div>
                    ${e.ticker ? `<span class="code" style="font-weight:700; align-self:center;">${pf_esc(e.ticker)}</span>` : ""}
                  </div>
                `;
              }).join("")}
            </div>
          </div>
        `;
      }).join("");

  // Legend
  const legendHtml = Object.entries(eventTypeStyle).map(([k, s]) =>
    `<span class="status-label status-${s.class}" style="margin-right:6px; min-height:22px; padding:2px 6px;">${s.icon} ${s.label}</span>`
  ).join("");

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>투자 캘린더</h1>
        <p>미국/한국 증시의 주요 배당락일(Ex-Dividend Date), 대형 빅테크 실적 공시(Earnings Call), CPI/FOMC 거시 경제 일정 및 개인 월급 적립 일정과 Toss 실계좌 매매 내역을 결합하여 보여줍니다.</p>
      </div>
      ${statusBadge("success")}
    </div>
    ${renderDataSourceNote("invest-calendar")}

    <section class="panel">
      <div class="panel-header" style="border-bottom:1px solid var(--border); padding-bottom:12px; margin-bottom:12px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
        <div style="display:flex; flex-wrap:wrap; gap:4px;">
          ${legendHtml}
        </div>
        <span class="muted">${allEvents.length}개 일정 통합</span>
      </div>
      <div class="panel-body" style="padding:10px 14px;">
        ${calHtml}
      </div>
      ${renderSourceCaption("investment_calendar.py · FRED economic releases · state/toss_orders.json")}
    </section>
  `;
}
