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
                  <span style="color:var(--muted)">현재 자산 (PV)</span><strong>${pf_fmt(g.current_value)}원</strong>
                </div>
                <div style="display:flex; justify-content:space-between; border-bottom:1px solid #f1f5f9; padding-bottom:3px;">
                  <span style="color:var(--muted)">목표 자산 (FV)</span><strong>${pf_fmt(g.target_value)}원</strong>
                </div>
                <div style="display:flex; justify-content:space-between; border-bottom:1px solid #f1f5f9; padding-bottom:3px;">
                  <span style="color:var(--muted)">월 적립액 (PMT)</span><strong>${pf_fmt(g.monthly_contribution)}원</strong>
                </div>
                <div style="display:flex; justify-content:space-between; border-bottom:1px solid #f1f5f9; padding-bottom:3px;">
                  <span style="color:var(--muted)">목표 기간</span><strong>${g.horizon_months}개월 (${(g.horizon_months / 12).toFixed(1)}년)</strong>
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

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>투자 목표 &amp; 계획</h1>
        <p>목표 금액과 기간을 입력하면 미래 가치(FV) 방정식에 기초하여 실현에 필요한 연 수익률을 계산하고 연도별 시나리오를 시뮬레이션합니다.</p>
      </div>
      ${statusBadge(goals.length > 0 ? "success" : "not_evaluated")}
    </div>
    ${renderDataSourceNote("goal-planner")}
    
    <section class="metric-grid">
      ${metricCard("목표 수", `${goalCount}개`, goalCount ? "success" : "not_evaluated", "등록된 투자 목표")}
      ${metricCard("총 목표금액", `${pf_fmt(Math.round(totalTarget / 10000))}만원`, totalTarget ? "success" : "not_evaluated", "미래 목표 자산 총합")}
      ${metricCard("현재 자산합", `${pf_fmt(Math.round(totalCurrent / 10000))}만원`, totalCurrent ? "success" : "not_evaluated", "현재 가치(PV) 총합")}
      ${metricCard("평균 필요수익률", avgReturn > 0 ? pf_pct(avgReturn) : "계산 불가", avgReturn > 15 ? "warning" : avgReturn > 0 ? "success" : "not_evaluated", "목표 달성 필요 평균 연익률")}
    </section>

    <div class="section-grid">
      <!-- Left side: Goals list -->
      <div style="display:flex; flex-direction:column;">
        <h2 style="font-size:14px; font-weight:700; margin:0 0 10px 0; color:var(--text);">📋 등록된 투자 목표 목록</h2>
        ${goalListHtml}
      </div>

      <!-- Right side: Add Goal Form -->
      <section class="panel" style="align-self: flex-start;">
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
      <!-- Left: Table of Cashflow Items -->
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
      </div>
    </div>
  `;

  // Bind Events
  document.querySelector("#pf-cf-cancel")?.addEventListener("click", () => {
    document.querySelector("#pf-cf-label").value = "";
    document.querySelector("#pf-cf-amount").value = "";
    document.querySelector("#pf-cf-msg").textContent = "";
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
      <!-- Left: Reinvestment Scenario -->
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
}

// ──────────────────────────────────────────────
// 4. 투자 코치 & 다이어트 (investor-coach)
// ──────────────────────────────────────────────
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
  const score = bi.coaching_score || 85;
  const scoreStatus = score >= 90 ? "success" : (score >= 70 ? "warning" : "failed");

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>투자 코치 &amp; 다이어트</h1>
        <p>수동 주문 승인 기록을 종합 분석하여 인간 투자자 고유의 행동 편향(FOMO, 잦은 거래, 손절 기피)을 진단하고, 자산 분산을 해치는 마이크로 포지션을 다이어트 조치합니다.</p>
      </div>
      ${statusBadge(scoreStatus, "습관 점수")}
    </div>
    ${renderDataSourceNote("investor-coach")}

    <section class="metric-grid">
      ${metricCard("코칭 점수", `${score}점`, scoreStatus, "거래 감사 내역 기반 정량 습관 평가")}
      ${metricCard("총 승인 거래", `${bi.total_decisions_analyzed || 0}건`, "success", `최근 승인율: ${bi.biases_detected?.overtrading_approvals || 0}건`)}
      ${metricCard("감지된 편향", `${biases.length}개 편향`, biases.length ? "warning" : "success", "심리학적 편향 징후 감지 수")}
      ${metricCard("다이어트 종목", `${pruneList.length + redundancies.length}개 대상`, (pruneList.length + redundancies.length) ? "warning" : "success", "정리 또는 축소 권장 종목")}
    </section>

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

      <!-- Right: Diet Mode -->
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
    </div>
  `;
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
  const today = new Date().toISOString().slice(0, 10);

  // Group by date
  const grouped = {};
  events.forEach(e => {
    const dt = e.date || "unknown";
    if (!grouped[dt]) grouped[dt] = [];
    grouped[dt].push(e);
  });

  const sortedDates = Object.keys(grouped).sort();

  const eventTypeStyle = {
    ex_dividend: { class: "success", icon: "🌱", label: "배당락 (Ex-Div)" },
    earnings: { class: "validating", icon: "📊", label: "실적 발표 (Earnings)" },
    macro: { class: "warning", icon: "🏛️", label: "거시 지표 (Macro)" },
    salary: { class: "success", icon: "💵", label: "급여 유입 (Salary)" },
    fomc: { class: "failed", icon: "🏦", label: "FOMC 결정" },
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
          <div style="display:flex; gap:16px; margin-bottom:12px; opacity:${isPast ? "0.5" : "1"};">
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
        <p>미국/한국 증시의 주요 배당락일(Ex-Dividend Date), 대형 빅테크 실적 공시(Earnings Call), CPI/FOMC 거시 경제 일정 및 개인 월급 적립 일정을 결합하여 보여줍니다.</p>
      </div>
      ${statusBadge("success")}
    </div>
    ${renderDataSourceNote("invest-calendar")}

    <section class="panel">
      <div class="panel-header" style="border-bottom:1px solid var(--border); padding-bottom:12px; margin-bottom:12px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
        <div style="display:flex; flex-wrap:wrap; gap:4px;">
          ${legendHtml}
        </div>
        <span class="muted">${events.length}개 일정 통합</span>
      </div>
      <div class="panel-body" style="padding:10px 14px;">
        ${calHtml}
      </div>
      ${renderSourceCaption("investment_calendar.py · FRED economic releases")}
    </section>
  `;
}
