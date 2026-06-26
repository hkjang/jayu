function renderTossAccountDashboard() {
  const data = state.tossPortfolio || {};
  const summary = data.summary || {};
  const fxImpactSummary = data.fx_impact?.summary || {};
  const accounts = data.accounts || [];
  const selected = data.selected_account || {};
  const holdings = data.holdings || [];
  const visibleHoldings = filterTossHoldingsByRegion(holdings);
  const visibleSummary = summarizeTossHoldings(visibleHoldings, summary);
  const allocation = visibleHoldings.filter((item) => item.weight !== null && item.weight !== undefined);
  const sections = data.sections || {};
  const activeRegionLabel = { ALL: "전체", KR: "한국", US: "미국" }[state.tossAccountRegion] || "전체";

  let activeContentHtml = "";
  if (state.tossSubTab === "reconciliation") {
    activeContentHtml = renderReconciliation(state.tossReconciliation);
  } else if (state.tossSubTab === "order-plan") {
    activeContentHtml = renderOrderPlan(state.tossOrderPlan);
  } else {
    activeContentHtml = `
      ${renderTossRegionTabs(data.region_totals || [])}
      <section class="panel" style="margin-bottom:14px">
        <div class="panel-header">
          <div><h2>포트폴리오 타입별 요약</h2><p>보유종목을 단타, 중타, 장타, 배당 관리 관점으로 나눠 확인합니다.</p></div>
        </div>
        <div class="panel-body">
          ${renderPortfolioTypeCards(data.portfolio_type_totals || [])}
          ${renderSourceCaption("portfolio_mapping.json · portfolio_type_overrides.json · Toss holdings/stocks metadata")}
        </div>
      </section>
      <section class="panel" style="margin-bottom:14px">
        <div class="panel-header">
          <div><h2>Account selector</h2><p>버튼을 누르지 않아도 첫 계좌가 자동으로 선택됩니다. 다른 계좌를 고르면 즉시 다시 조회합니다.</p></div>
          ${statusBadge(data.read_only ? "success" : "blocked", "read only")}
        </div>
        ${renderTossAccountCards(accounts, selected)}
        ${renderSourceCaption("Toss Open API accounts GET")}
      </section>
      <div class="visual-grid">
        <section class="panel">
          <div class="panel-header"><div><h2>Market split</h2><p>KRW 환산 기준 한국/미국/기타 비중입니다.</p></div></div>
          <div class="panel-body">${renderExposureDonut(data.region_totals || [], "region")}${renderSourceCaption("Toss holdings GET · KRW conversion")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>Currency split</h2><p>USD와 KRW가 섞여도 KRW 환산 기준으로 비교합니다.</p></div></div>
          <div class="panel-body">${renderExposureDonut(data.currency_totals || [], "currency")}${renderSourceCaption("Toss holdings GET · currency fields")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>FX rates</h2><p>환산에 사용한 환율과 유효 시각입니다.</p></div></div>
          <div class="panel-body">${renderFxRateCards(data.fx_rates || [])}${renderSourceCaption("Toss exchange-rate GET")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>FX impact split</h2><p>당일 KRW 변화를 가격 효과와 환율 효과로 나눕니다.</p></div></div>
          <div class="panel-body">${renderFxImpactPanel(data.fx_impact)}${renderSourceCaption(data.fx_impact?.source || "Toss holdings GET · Toss prices GET · Toss exchange-rate GET")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>계좌 변화 원인</h2><p>이전 스냅샷 대비 평가금액 변화를 가격, 환율, 현금, 보유 변화로 나눕니다.</p></div></div>
          <div class="panel-body">${renderAccountAttributionPanel(data.account_attribution)}${renderSourceCaption(data.account_attribution?.source || "state/account_attribution.json")}</div>
        </section>
      </div>
      <div class="visual-grid">
        <section class="panel">
          <div class="panel-header"><div><h2>Category split</h2><p>주식, ETF, 레버리지 ETF 같은 종목 유형별 노출입니다.</p></div></div>
          <div class="panel-body">${renderExposureDonut(data.category_totals || [], "category")}${renderSourceCaption("portfolio_mapping.json · holdings enrichment")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>Sector exposure</h2><p>종목 메타데이터에서 읽은 섹터 기준 상위 노출입니다.</p></div></div>
          <div class="panel-body">${renderExposureDonut(data.sector_totals || [], "sector")}${renderSourceCaption("portfolio_mapping.json sector metadata")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>Situation tags</h2><p>집중도, 손익, 당일 급등락, 경고 상태를 태그로 묶었습니다.</p></div></div>
          <div class="panel-body">${renderSituationTags(data.situation_totals || [])}${renderSourceCaption("Toss holdings GET · warnings enrichment · price changes")}</div>
        </section>
      </div>
      <div class="section-grid">
        <section class="panel">
          <div class="panel-header"><div><h2>Holding allocation</h2><p>${activeRegionLabel} 탭의 KRW 환산 평가금액 기준 보유 비중입니다.</p></div></div>
          <div class="panel-body">${renderHoldingAllocation(allocation)}${renderSourceCaption("Toss holdings GET · selected market filter")}</div>
        </section>
        <section class="panel">
          <div class="panel-header"><div><h2>P/L contributors</h2><p>KRW 환산 평가손익 기여도가 큰 종목입니다.</p></div></div>
          <div class="panel-body">${renderPnlContributors(visibleHoldings)}${renderSourceCaption("Toss holdings GET · unrealized P/L fields")}</div>
        </section>
      </div>
      <section class="panel">
        <div class="panel-header"><div><h2>Holdings</h2><p>수량, 평균단가, 현재가, 평가금액, 손익률을 한 표에서 확인합니다.</p></div></div>
        ${renderTossHoldingsTable(visibleHoldings)}
        ${renderSourceCaption("Toss Open API holdings GET · exchange-rate GET")}
      </section>
      <section class="panel" style="margin-top:14px">
        <div class="panel-header"><div><h2>Account GET status</h2><p>계좌 화면에서 자동 호출한 GET endpoint 결과입니다.</p></div></div>
        ${renderTossSectionTable(sections)}
        ${renderSourceCaption("Toss account endpoint status from latest dashboard fetch")}
      </section>
    `;
  }

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>Toss Account Dashboard</h1>
        <p>첫 계좌를 자동 선택하고 USD/KRW 환율을 반영해 KRW 기준 보유 종목, 평가금액, 손익, 비중을 보여주는 읽기 전용 계좌 화면입니다.</p>
      </div>
      ${statusBadge(summary.status || data.status)}
    </div>
    ${renderDataSourceNote("toss-account", ["Toss warnings endpoint", "today_signals broker readiness"])}

    <div class="segmented-tabs" role="tablist" style="margin-bottom:14px">
      <button class="${state.tossSubTab === 'overview' ? 'is-active' : ''}" type="button" data-toss-subtab="overview">
        <span>자산 요약 (Asset Summary)</span>
      </button>
      <button class="${state.tossSubTab === 'reconciliation' ? 'is-active' : ''}" type="button" data-toss-subtab="reconciliation">
        <span>보유 종목 대조 (Reconciliation)</span>
      </button>
      <button class="${state.tossSubTab === 'order-plan' ? 'is-active' : ''}" type="button" data-toss-subtab="order-plan">
        <span>주문 준비도 및 전표 (Order Plan)</span>
      </button>
    </div>

    <section class="status-banner status-${statusClass(summary.status || data.status)}">
      <div>${statusBadge(summary.status || data.status)}</div>
      <div>
        <h2>${tossAccountHeadline(data, summary)}</h2>
        <p>화면 진입만으로 accounts, holdings, 필요한 exchange-rate GET 조회를 수행합니다. 주문 생성/정정/취소 요청은 없습니다.</p>
      </div>
      <span class="code">READ_ONLY_ACCOUNT</span>
    </section>
    <section class="metric-grid">
      ${metricCard("계좌", selected.display_name || "-", selected.account_seq ? "success" : "warning", selected.masked_account_no || "첫 계좌 자동 선택")}
      ${metricCard(`${activeRegionLabel} 종목`, visibleSummary.holding_count ?? 0, visibleSummary.holding_count ? "success" : "not_evaluated", "filtered holdings")}
      ${metricCard("총 평가금액(KRW)", formatCurrency(visibleSummary.total_market_value_krw, "KRW"), summary.failed_section_count ? "warning" : "success", "FX converted")}
      ${metricCard("평가손익(KRW)", formatCurrency(visibleSummary.unrealized_pnl_krw, "KRW"), Number(visibleSummary.unrealized_pnl_krw || 0) < 0 ? "warning" : "success", formatPercent(visibleSummary.unrealized_pnl_pct, 2))}
      ${metricCard("USD/KRW", fxRateLabel(data.fx_rates, "USD"), fxRateStatus(data.fx_rates, "USD"), fxRateDetail(data.fx_rates, "USD"))}
      ${metricCard("FX 당일효과", formatCurrency(fxImpactSummary.fx_effect_krw, "KRW"), data.fx_impact?.status || "not_evaluated", `가격효과 ${formatCurrency(fxImpactSummary.asset_effect_krw, "KRW")}`, null, data.fx_impact?.source || "Toss holdings GET · Toss prices GET · Toss exchange-rate GET")}
      ${metricCard("조회 실패", summary.failed_section_count ?? 0, summary.failed_section_count ? "warning" : "success", (summary.failed_sections || []).join(", ") || "없음")}
    </section>
    
    ${activeContentHtml}
  `;
}

function renderReconciliation(reconciliation) {
  const recon = reconciliation || {};
  const status = recon.status || "unknown";
  const differences = recon.differences || [];
  const unmapped = recon.unmapped_tickers || [];
  const reviewHtml = renderReconciliationReview(recon);

  let statusHtml = "";
  if (status === "synchronized") {
    statusHtml = `
      <section class="status-banner status-success">
        <div>${statusBadge("success")}</div>
        <div>
          <h2>포트폴리오 일치 (Synchronized)</h2>
          <p>Local portfolio.csv와 Toss 실계좌 보유 종목 및 수량이 완벽히 일치합니다.</p>
        </div>
      </section>
    `;
  } else if (status === "diverged") {
    statusHtml = `
      <section class="status-banner status-warning">
        <div>${statusBadge("warning")}</div>
        <div>
          <h2>포트폴리오 불일치 (Diverged)</h2>
          <p>Local portfolio.csv와 Toss 실계좌 간에 수량 불일치 또는 누락된 종목이 있습니다. 실계좌 보유 종목 기준으로 로컬 CSV를 갱신할 수 있습니다.</p>
          <div style="margin-top: 10px;">
            <button id="btn-sync-portfolio-banner" class="button button-primary" type="button">실계좌 종목으로 동기화</button>
          </div>
        </div>
      </section>
    `;
  } else if (status === "missing_credentials") {
    statusHtml = `
      <section class="status-banner status-warning">
        <div>${statusBadge("warning")}</div>
        <div>
          <h2>자격증명 미설정</h2>
          <p>Toss API Key와 Secret Key가 설정되지 않아 실계좌 대조를 진행할 수 없습니다.</p>
        </div>
      </section>
    `;
  } else {
    statusHtml = `
      <section class="status-banner status-failed">
        <div>${statusBadge("failed")}</div>
        <div>
          <h2>조회 실패</h2>
          <p>${escapeHtml(recon.message || "Toss 실계좌 정보를 가져올 수 없습니다.")}</p>
        </div>
      </section>
    `;
  }

  let tableHtml = "";
  if (differences.length === 0) {
    tableHtml = `
      <div class="empty-state">
        <strong>불일치 내역이 없습니다.</strong>
        <span>Local 포트폴리오 파일과 실계좌 보유 종목의 수량이 같습니다.</span>
      </div>
    `;
  } else {
    tableHtml = `
      <div class="table-wrap"><table>
        <thead>
          <tr>
            <th>종목 (Ticker)</th>
            <th class="numeric">로컬 수량 (portfolio.csv)</th>
            <th class="numeric">토스 수량 (Holdings)</th>
            <th class="numeric">차이 (Diff)</th>
            <th>구분</th>
          </tr>
        </thead>
        <tbody>
          ${differences.map(d => {
            const diffClass = Number(d.difference || 0) < 0 ? "negative" : "positive";
            const diffTypeLabel = {
              missing_in_toss: "토스 누락",
              missing_in_local: "로컬 누락",
              quantity_mismatch: "수량 불일치"
            }[d.type] || d.type;
            const badgeType = d.type === "quantity_mismatch" ? "warning" : "blocked";
            return `
              <tr>
                <td class="ticker-cell">${renderTicker(d.ticker)}</td>
                <td class="numeric">${formatNumber(d.local_quantity, 4)}</td>
                <td class="numeric">${formatNumber(d.toss_quantity, 4)}</td>
                <td class="numeric ${diffClass}">${formatNumber(d.difference, 4)}</td>
                <td>${statusBadge(badgeType, diffTypeLabel)}</td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table></div>
    `;
  }

  let unmappedHtml = "";
  if (unmapped.length > 0) {
    unmappedHtml = `
      <section class="panel" style="margin-top:14px">
        <div class="panel-header">
          <div><h2>미매핑 종목 (Unmapped Tickers)</h2><p>portfolio_mapping.json에 등록되지 않은 종목 코드입니다.</p></div>
          ${statusBadge("blocked", `${unmapped.length}건`)}
        </div>
        <div class="panel-body">
          <div class="tag-cloud">
            ${unmapped.map(ticker => `
              <div class="tag-pill" style="border-color:var(--status-blocked)">
                <strong style="color:var(--status-blocked)">${renderTicker(ticker)}</strong>
                <span>매핑 미등록</span>
              </div>
            `).join("")}
          </div>
          ${renderSourceCaption("portfolio_mapping.json · portfolio.csv · Toss holdings GET")}
        </div>
      </section>
    `;
  }

  return `
    ${statusHtml}
    ${reviewHtml}
    <section class="panel">
      <div class="panel-header" style="align-items: center;">
        <div><h2>보유 종목 대조 상세</h2><p>Local portfolio.csv와 Toss 실계좌 수량을 비교한 내역입니다.</p></div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <button id="btn-sync-portfolio" class="button button-secondary" type="button">실계좌 종목으로 동기화</button>
          ${statusBadge(differences.length ? "warning" : "success", differences.length ? "불일치 발견" : "일치")}
        </div>
      </div>
      ${tableHtml}
      ${renderSourceCaption("portfolio.csv · Toss holdings GET")}
    </section>
    ${unmappedHtml}
  `;
}

function renderReconciliationReview(recon) {
  const summary = recon.review_summary || {};
  const issues = recon.mapping_issues || [];
  const typeTotals = recon.portfolio_type_totals || [];
  const reviewSource = recon.review_source || "portfolio.csv · portfolio_mapping.json · portfolio_type_overrides.json";
  const issueStatus = issues.length ? "warning" : "success";
  const issuesHtml = issues.length ? `
    <div class="table-wrap reconciliation-issue-table"><table>
      <thead>
        <tr>
          <th>종목</th>
          <th>이슈</th>
          <th>운용 타입</th>
          <th>상세</th>
          <th class="numeric">현재/한도</th>
        </tr>
      </thead>
      <tbody>
        ${issues.map((issue) => {
          const observedLimit = issue.observed != null || issue.limit != null
            ? `${issue.observed != null ? formatPercent(issue.observed, 1) : "-"} / ${issue.limit != null ? formatPercent(issue.limit, 1) : "-"}`
            : "-";
          return `
            <tr>
              <td class="ticker-cell">${renderTicker(issue.ticker)}</td>
              <td>${statusBadge(issue.severity === "blocked" ? "blocked" : "warning", issue.label || RECONCILIATION_ISSUE_LABELS[issue.issue_type] || issue.issue_type || "점검")}</td>
              <td>${escapeHtml(issue.portfolio_type_label || issue.portfolio_type || "-")}</td>
              <td>${escapeHtml(issue.detail || "")}</td>
              <td class="numeric">${escapeHtml(observedLimit)}</td>
            </tr>`;
        }).join("")}
      </tbody>
    </table></div>
  ` : `
    <div class="empty-state">
      <strong>매핑/정책 이슈가 없습니다.</strong>
      <span>portfolio_mapping.json, portfolio_type_overrides.json, 타입별 리스크 정책 기준으로 추가 점검할 항목이 없습니다.</span>
    </div>
  `;
  return `
    <section class="panel">
      <div class="panel-header">
        <div><h2>매핑/정책 점검</h2><p>수량 동기화 전 운용 타입, 섹터, 타입별 단일종목 한도를 확인합니다.</p></div>
        ${statusBadge(issueStatus, issues.length ? `${issues.length}건 점검` : "정상")}
      </div>
      <div class="visual-grid" style="margin-bottom:14px">
        ${metricCard("전체 이슈", summary.issue_count || 0, issueStatus, "매핑·타입·섹터·한도")}
        ${metricCard("매핑 미등록", summary.unmapped_count || 0, summary.unmapped_count ? "blocked" : "success", "portfolio_mapping.json")}
        ${metricCard("타입/섹터 누락", Number(summary.missing_type_count || 0) + Number(summary.missing_sector_count || 0), Number(summary.missing_type_count || 0) + Number(summary.missing_sector_count || 0) ? "warning" : "success", "mapping/override 보강")}
        ${metricCard("한도 초과", summary.overweight_count || 0, summary.overweight_count ? "warning" : "success", "risk.portfolio_policy")}
      </div>
      ${issuesHtml}
      ${renderSourceCaption(reviewSource)}
    </section>
    <section class="panel">
      <div class="panel-header">
        <div><h2>운용 타입별 대조 비중</h2><p>로컬 portfolio.csv를 운용 타입 정책 기준으로 다시 집계한 비중입니다.</p></div>
      </div>
      ${renderPortfolioTypeCards(typeTotals)}
      ${renderSourceCaption("portfolio.csv · portfolio_mapping.json · portfolio_type_overrides.json")}
    </section>
  `;
}

function renderOrderPlan(orderPlanData) {
  const planData = orderPlanData || {};
  const orderPlan = planData.order_plan || {};
  const warningsGate = planData.warnings_gate || {};
  const marketSession = planData.market_session || {};
  const todaySignals = planData.today_signals || {};
  const paperContract = planData.paper_order_contract || {};
  const allocationPreview = planData.allocation_preview || {};

  const krOpen = marketSession.KR?.open || false;
  const usOpen = marketSession.US?.open || false;

  const orders = orderPlan.orders || [];

  const sessionHtml = `
    <div class="visual-grid" style="margin-bottom:14px">
      <div class="panel">
        <div class="panel-header"><div><h2>한국 시장 (KR Session)</h2><p>토스 API 실시간 조회 기준</p></div></div>
        <div class="panel-body">
          <div class="metric-card" style="border:none;box-shadow:none;padding:0">
            <span class="value" style="font-size:24px">${krOpen ? "개장 중 (OPEN)" : "휴장/장마감 (CLOSED)"}</span>
            <span class="status ${krOpen ? "success" : "not_evaluated"}" style="margin-top:5px;display:inline-block">${krOpen ? "실시간 거래 가능" : "주문 보류"}</span>
            ${renderSourceLabel("Toss market-calendar KR GET")}
          </div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header"><div><h2>미국 시장 (US Session)</h2><p>토스 API 실시간 조회 기준</p></div></div>
        <div class="panel-body">
          <div class="metric-card" style="border:none;box-shadow:none;padding:0">
            <span class="value" style="font-size:24px">${usOpen ? "개장 중 (OPEN)" : "휴장/장마감 (CLOSED)"}</span>
            <span class="status ${usOpen ? "success" : "not_evaluated"}" style="margin-top:5px;display:inline-block">${usOpen ? "실시간 거래 가능" : "주문 보류"}</span>
            ${renderSourceLabel("Toss market-calendar US GET")}
          </div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header"><div><h2>오늘의 주문 계획 요약</h2><p>eligible buy signals</p></div></div>
        <div class="panel-body">
          <div class="metric-card" style="border:none;box-shadow:none;padding:0">
            <span class="value" style="font-size:24px">${orders.length} 건</span>
            <span class="status ${orders.length ? "success" : "not_evaluated"}" style="margin-top:5px;display:inline-block">${orders.length ? "수동 매수 slip 대기" : "주문 대상 없음"}</span>
            ${renderSourceLabel("order_plan.json")}
          </div>
        </div>
      </div>
    </div>
  `;

  const tickers = Object.keys(todaySignals);
  let readinessHtml = "";
  if (tickers.length === 0) {
    readinessHtml = `
      <div class="empty-state">
        <strong>오늘 생성된 신호가 없습니다.</strong>
        <span>신호가 생성되고 toss readiness가 연동되면 상세 준비도가 표시됩니다.</span>
      </div>
    `;
  } else {
    readinessHtml = `
      <div class="table-wrap"><table>
        <thead>
          <tr>
            <th>종목 (Ticker)</th>
            <th>신호 방향</th>
            <th>Eligible</th>
            <th>Toss 보유 여부</th>
            <th>매수 가능 금액 (Buying Power)</th>
            <th>수수료 구조</th>
            <th>경고 여부</th>
            <th>메시지</th>
          </tr>
        </thead>
        <tbody>
          ${tickers.map(ticker => {
            const sig = todaySignals[ticker] || {};
            const readiness = sig.broker_readiness || {};
            const warnInfo = warningsGate[ticker] || {};
            const isHeld = readiness.is_held || false;
            const buyingPower = readiness.buying_power?.amount ?? 0;
            const currency = readiness.buying_power?.currency || "-";
            const comm = readiness.commission_structure || {};
            const hasWarning = warnInfo.has_warning || readiness.warnings?.has_warning || false;
            const warnMsg = warnInfo.message || readiness.warnings?.message || "-";

            return `
              <tr>
                <td class="ticker-cell">${renderTicker(ticker)}</td>
                <td><strong>${escapeHtml(sig.action || sig.signal || "-")}</strong></td>
                <td>${statusBadge(sig.eligible ? "success" : "blocked", sig.eligible ? "Eligible" : "Blocked")}</td>
                <td>${statusBadge(isHeld ? "warning" : "not_evaluated", isHeld ? "보유 중" : "미보유")}</td>
                <td class="numeric">${formatNumber(buyingPower, 2)} ${escapeHtml(currency)}</td>
                <td class="code" style="font-size:10px">${compactJson(comm) || "-"}</td>
                <td>${statusBadge(hasWarning ? "blocked" : "success", hasWarning ? "위험/정지" : "정상")}</td>
                <td><small style="color:var(--muted)">${escapeHtml(warnMsg)}</small></td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table></div>
    `;
  }

  let slipsHtml = "";
  if (orders.length === 0) {
    slipsHtml = `
      <div class="empty-state">
        <strong>대상 수동 주문이 없습니다.</strong>
        <span>eligible buy 신호가 존재하는 경우 여기에 주문 가이드 전표가 노출됩니다.</span>
      </div>
    `;
  } else {
    slipsHtml = `
      <div class="table-wrap"><table>
        <thead>
          <tr>
            <th>종목</th>
            <th>행동</th>
            <th class="numeric">승인 비중 (Approved %)</th>
            <th class="numeric">주문 예정 금액 (Target Cash)</th>
            <th class="numeric">기준 가격 (Price)</th>
            <th class="numeric">예상 수량 (Est Qty)</th>
          </tr>
        </thead>
        <tbody>
          ${orders.map(o => `
            <tr>
              <td class="ticker-cell"><strong>${renderTicker(o.ticker)}</strong></td>
              <td><span style="color:var(--status-success);font-weight:bold">${escapeHtml(o.action)}</span></td>
              <td class="numeric">${formatPercent(o.approved_pct, 1)}</td>
              <td class="numeric"><strong>${formatNumber(o.estimated_cash, 2)} ${escapeHtml(o.currency)}</strong></td>
              <td class="numeric">${formatNumber(o.price, 2)}</td>
              <td class="numeric" style="color:var(--brand-primary)"><strong>${formatNumber(o.estimated_quantity, 4)}</strong></td>
            </tr>
          `).join("")}
        </tbody>
      </table></div>
    `;
  }

  let markdownPlan = "# Manual Order Plan Report\n";
  markdownPlan += `Generated At: ${planData.order_plan?.generated_at || new Date().toISOString()}\n\n`;
  markdownPlan += "| Ticker | Action | Approved Pct | Target Cash | Est Price | Est Qty |\n";
  markdownPlan += "|---|---|---|---|---|---|\n";
  orders.forEach(o => {
    markdownPlan += `| \`${o.ticker}\` | **${o.action}** | ${(o.approved_pct * 100).toFixed(1)}% | ${o.estimated_cash.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} ${o.currency} | ${o.price.toLocaleString()} | ${o.estimated_quantity.toFixed(4)} |\n`;
  });
  if (orders.length === 0) {
    markdownPlan += "| - | - | - | - | - | - |\n\n*No eligible buy orders.*";
  }

  return `
    ${sessionHtml}
    ${renderAllocationPreview(allocationPreview)}
    ${renderPaperOrderContract(paperContract)}
    
    <div class="section-grid" style="margin-bottom:14px">
      <section class="panel">
        <div class="panel-header">
          <div><h2>수동 주문 전표 (Manual Buy Slips)</h2><p>실제 주문 체결 없이 운영자가 참고용으로 확인하는 slip 목록입니다.</p></div>
          ${statusBadge(orders.length ? "success" : "not_evaluated")}
        </div>
        ${slipsHtml}
        ${renderSourceCaption("order_plan.json · today_signals.json")}
      </section>
      
      <section class="panel">
        <div class="panel-header">
          <div><h2>Markdown 전표 복사</h2><p>카카오톡이나 노션 공유용 전표입니다.</p></div>
          <button class="button button-secondary" type="button" data-command="${escapeHtml(markdownPlan)}">전표 복사</button>
        </div>
        <div class="panel-body">
          <pre class="code" style="max-height: 250px; overflow-y: auto; font-size: 11px; white-space: pre-wrap; margin:0">${escapeHtml(markdownPlan)}</pre>
          ${renderSourceCaption("order_plan.json · today_signals.json · generated markdown slips")}
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="panel-header">
        <div><h2>종목별 실시간 준비도 및 경고 상태 (Signal Readiness)</h2><p>투자경고/거래정지/유의종목인 경우 eligible은 false로 자동 강제 차단됩니다.</p></div>
        ${statusBadge("success", "준비도 검사 완료")}
      </div>
      ${readinessHtml}
      ${renderSourceCaption("today_signals.json · stock_warning_gate.json · Toss /api/v1/stocks/{symbol}/warnings")}
    </section>
  `;
}

function renderAllocationPreview(data) {
  const preview = data || {};
  const summary = preview.summary || {};
  const source = preview.source || summary.source || "state/allocation_preview.json";
  const checks = preview.limit_checks || [];
  const holdings = (preview.holdings || []).slice(0, 7);
  const sectors = (preview.sector_totals || []).slice(0, 6);
  const status = preview.status || "not_evaluated";
  const cashStatus = summary.cash_known === false ? "not_evaluated" : (Number(summary.cash_pct_after || 0) < Number(preview.limits?.min_cash_pct || 0.15) ? "blocked" : "success");

  const checkHtml = checks.length ? `
    <div class="allocation-preview-checks">
      ${checks.map(check => `
        <div class="allocation-preview-check">
          <span>${escapeHtml(check.label || check.id || "점검")}</span>
          ${statusBadge(check.status || "not_evaluated", check.observed == null ? "미평가" : `${formatPercent(check.observed, 1)} / ${formatPercent(check.limit, 1)}`)}
          ${renderSourceLabel(check.source || source)}
        </div>
      `).join("")}
    </div>
  ` : `
    <div class="empty-state compact">
      <strong>배분 점검 산출물이 아직 없습니다.</strong>
      <span><code>jayu report allocation-preview</code> 실행 후 주문 전후 비중이 표시됩니다.</span>
    </div>
  `;

  const sectorHtml = sectors.length ? `
    <div class="table-wrap allocation-preview-table"><table>
      <thead>
        <tr>
          <th>섹터</th>
          <th class="numeric">전</th>
          <th class="numeric">후</th>
          <th class="numeric">변화</th>
          <th>상태</th>
        </tr>
      </thead>
      <tbody>
        ${sectors.map(row => `
          <tr>
            <td>${escapeHtml(row.sector || "UNKNOWN")}</td>
            <td class="numeric">${formatPercent(row.before_weight, 1)}</td>
            <td class="numeric">${formatPercent(row.after_weight, 1)}</td>
            <td class="numeric allocation-preview-delta ${Number(row.delta_weight || 0) < 0 ? "negative" : "positive"}">${formatPercent(row.delta_weight, 1)}</td>
            <td>${statusBadge(row.status || "not_evaluated")}</td>
          </tr>
        `).join("")}
      </tbody>
    </table></div>
  ` : `<div class="empty-state compact"><strong>섹터 변화 없음</strong><span>보유/주문 데이터가 연결되면 섹터 비중 변화가 표시됩니다.</span></div>`;

  const holdingHtml = holdings.length ? `
    <div class="table-wrap allocation-preview-table"><table>
      <thead>
        <tr>
          <th>종목</th>
          <th>섹터</th>
          <th class="numeric">전</th>
          <th class="numeric">후</th>
          <th class="numeric">변화</th>
        </tr>
      </thead>
      <tbody>
        ${holdings.map(row => `
          <tr>
            <td class="ticker-cell">${renderTicker(row.ticker)}</td>
            <td>${escapeHtml(row.sector || "UNKNOWN")}</td>
            <td class="numeric">${formatPercent(row.before_weight, 1)}</td>
            <td class="numeric">${formatPercent(row.after_weight, 1)}</td>
            <td class="numeric allocation-preview-delta ${Number(row.delta_weight || 0) < 0 ? "negative" : "positive"}">${formatPercent(row.delta_weight, 1)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table></div>
  ` : `<div class="empty-state compact"><strong>종목 변화 없음</strong><span>보유/주문 데이터가 연결되면 단일 종목 비중 변화가 표시됩니다.</span></div>`;

  return `
    <section class="panel allocation-preview-section" style="margin-bottom:14px">
      <div class="panel-header">
        <div><h2>자금 배분 시뮬레이터</h2><p>수동 주문 전표를 반영했을 때 현금, 섹터, 단일종목 비중이 어떻게 바뀌는지 미리 봅니다.</p></div>
        ${statusBadge(status, status === "success" ? "통과" : status === "blocked" ? "차단" : "점검")}
      </div>
      <div class="metric-grid" style="margin:12px">
        ${metricCard("예상 현금", summary.after_cash_krw == null ? "미확인" : formatCurrency(summary.after_cash_krw, "KRW"), cashStatus, summary.cash_pct_after == null ? "cash_krw 미입력" : formatPercent(summary.cash_pct_after, 1), null, source)}
        ${metricCard("적용 주문", `${formatNumber(summary.applied_order_count || 0, 0)}/${formatNumber(summary.order_count || 0, 0)}건`, summary.skipped_order_count ? "blocked" : status, `매수 ${formatCurrency(summary.buy_cash_krw || 0, "KRW")}`, null, source)}
        ${metricCard("단일종목 초과", formatNumber(summary.max_position_breach_count || 0, 0), summary.max_position_breach_count ? "blocked" : "success", "risk.max_single_position_pct", null, source)}
        ${metricCard("섹터 초과", formatNumber(summary.sector_breach_count || 0, 0), summary.sector_breach_count ? "blocked" : "success", "risk.max_sector_exposure", null, source)}
      </div>
      ${checkHtml}
      <div class="allocation-preview-grid">
        <section class="allocation-preview-card">
          <div class="mini-heading">섹터 비중 변화</div>
          ${sectorHtml}
          ${renderSourceCaption("allocation_preview.json sector_totals · holdings JSON · order_plan.json")}
        </section>
        <section class="allocation-preview-card">
          <div class="mini-heading">종목 비중 변화</div>
          ${holdingHtml}
          ${renderSourceCaption("allocation_preview.json holdings · holdings JSON · order_plan.json")}
        </section>
      </div>
      ${renderSourceCaption(source)}
    </section>
  `;
}

function renderPaperOrderContract(contract) {
  const intents = contract.intents || [];
  const approval = contract.approval || {};
  const qualitySummary = contract.quality_summary || {};
  return `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div><h2>Paper 주문 의도 계약</h2><p>OrderIntent · OrderPlan · OrderApproval 구조를 live 주문 없이 검토합니다.</p></div>
        ${statusBadge(contract.live_order_enabled ? "blocked" : "success", contract.live_order_enabled ? "Live 주문 켜짐" : "Live 주문 비활성")}
      </div>
      <section class="metric-grid" style="margin:12px">
        ${metricCard("OrderIntent", `${intents.length}건`, intents.length ? "success" : "not_evaluated", "paper fill 후보")}
        ${metricCard("OrderPlan", contract.mode || "paper", "not_evaluated", "실행 모드")}
        ${metricCard("OrderApproval", approval.status || "not_requested", approval.live_order_enabled ? "blocked" : "success", approval.reason || "승인 대기")}
        ${metricCard("품질 점수", qualitySummary.average_score != null ? `${formatNumber(qualitySummary.average_score, 1)}점` : "미검증", qualitySummary.status || "not_evaluated", qualitySummary.summary || "OrderIntent validation")}
      </section>
      ${renderOrderIntentQuality(contract)}
      ${intents.length ? `
        <div class="table-wrap"><table>
          <thead>
            <tr>
              <th>종목</th>
              <th>Side</th>
              <th>품질</th>
              <th class="numeric">수량</th>
              <th class="numeric">결정가</th>
              <th class="numeric">도착 중간가</th>
              <th class="numeric">최종가</th>
            </tr>
          </thead>
          <tbody>
            ${intents.map((intent) => `
              <tr>
                <td class="ticker-cell"><strong>${renderTicker(intent.ticker)}</strong></td>
                <td>${escapeHtml(intent.side)}</td>
                <td>${statusBadge(intent.quality?.status || "not_evaluated", intent.quality?.score != null ? `${formatNumber(intent.quality.score, 1)}점` : "")}</td>
                <td class="numeric">${formatNumber(intent.quantity, 4)}</td>
                <td class="numeric">${formatNumber(intent.decision_price, 2)}</td>
                <td class="numeric">${formatNumber(intent.arrival_mid, 2)}</td>
                <td class="numeric">${formatNumber(intent.final_price, 2)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table></div>
      ` : `
        <div class="empty-state">
          <strong>Paper 주문 의도가 없습니다.</strong>
          <span>수량과 기준 가격이 있는 수동 order_plan 항목이 생기면 여기에 OrderIntent가 표시됩니다.</span>
        </div>
      `}
      ${renderSourceCaption(contract.source || "order_plan.json · today_signals.json · jayu.paper_trading")}
    </section>`;
}

function renderOrderIntentQuality(contract) {
  const summary = contract.quality_summary || {};
  const intents = contract.intents || [];
  const rejected = contract.rejected_intents || [];
  const rows = intents.map((intent) => {
    const quality = intent.quality || {};
    const checks = quality.checks || [];
    return `
      <div class="order-quality-row status-${statusClass(quality.status)}">
        <div class="order-quality-main">
          <strong>${renderTicker(intent.ticker)} · ${escapeHtml(intent.side || "-")}</strong>
          <span>${escapeHtml(quality.summary || "품질 점수 미검증")}</span>
          ${renderSourceCaption(quality.source || contract.source || "OrderIntent validation")}
        </div>
        <div class="order-quality-score">
          ${statusBadge(quality.status || "not_evaluated")}
          <b>${quality.score == null ? "미검증" : `${formatNumber(quality.score, 1)}점`}</b>
          <small>${escapeHtml(quality.grade || "F")}</small>
        </div>
        <div class="order-quality-checks">
          ${checks.map((check) => `
            <div class="order-quality-check status-${statusClass(check.status)}">
              <strong>${escapeHtml(check.label || check.id)}</strong>
              <span>${escapeHtml(check.value || "")}</span>
              <small>${escapeHtml(check.message || "")}</small>
              ${renderSourceCaption(check.source || "OrderIntent validation")}
            </div>
          `).join("")}
        </div>
      </div>
    `;
  }).join("");
  const rejectedRows = rejected.map((item) => `
    <div class="order-quality-rejected">
      <strong>${escapeHtml(item.ticker || "-")} · #${escapeHtml(item.index || "")}</strong>
      <span>${(item.reasons || []).map((reason) => escapeHtml(reason)).join(" · ") || "차단 사유 없음"}</span>
      ${renderSourceCaption(item.source || "order_plan.json")}
    </div>
  `).join("");

  return `
    <section class="order-quality-panel">
      <div class="order-quality-summary">
        <div>
          <strong>주문 의도 품질 점수</strong>
          <span>${escapeHtml(summary.summary || "품질 점수를 계산할 유효한 OrderIntent가 없습니다.")}</span>
          ${renderSourceCaption(summary.source || contract.source || "OrderIntent validation")}
        </div>
        <div class="order-quality-summary-score">
          ${statusBadge(summary.status || "not_evaluated")}
          <b>${summary.average_score == null ? "미검증" : `${formatNumber(summary.average_score, 1)}점`}</b>
          <small>${escapeHtml(summary.grade || "F")} · 유효 ${formatNumber(summary.intent_count || 0, 0)}건 · 거절 ${formatNumber(summary.rejected_count || 0, 0)}건</small>
        </div>
      </div>
      ${rows ? `<div class="order-quality-list">${rows}</div>` : ""}
      ${rejectedRows ? `
        <div class="order-quality-rejected-list">
          <h3>거절된 주문 후보</h3>
          ${rejectedRows}
        </div>
      ` : ""}
    </section>
  `;
}

function renderTossMarket() {
  const status = state.tossStatus || {};
  const market = state.tossMarket;
  const credentials = status.credentials || {};
  const endpointRows = status.endpoints || [];
  const accountData = state.tossAccounts || {};
  const accounts = accountData.accounts || [];
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>Toss Market Data</h1>
        <p>토스증권 Open API의 GET 엔드포인트만 사용하는 읽기 전용 화면입니다. 종목 조회를 실행해도 주문 생성, 정정, 취소 요청은 발생하지 않습니다.</p>
      </div>
      ${statusBadge(status.status === "configured" ? "success" : "warning")}
    </div>
    ${renderDataSourceNote("toss", ["Toss warnings endpoint", "Toss price-limit/orderbook/trades/candles GET"])}
    <section class="status-banner status-${status.status === "configured" ? "success" : "warning"}">
      <div>${statusBadge(status.status === "configured" ? "success" : "warning")}</div>
      <div>
        <h2>${status.status === "configured" ? "Toss API 조회 준비 완료" : "Toss API 키 설정 필요"}</h2>
        <p>${status.status === "configured" ? "Market Data와 계좌 범위 GET 조회를 사용할 수 있습니다. 계좌 조회는 TS_ACCOUNT 또는 --account 값이 필요합니다." : "TS_API_KEY와 TS_SECRET_KEY를 .env 또는 환경변수에 설정하세요."}</p>
      </div>
      <span class="code">READ_ONLY_GET</span>
    </section>
    <section class="metric-grid">
      ${metricCard("API 키", credentials.api_key ? "설정됨" : "없음", credentials.api_key ? "success" : "warning", "값은 화면에 표시하지 않음")}
      ${metricCard("Secret", credentials.secret_key ? "설정됨" : "없음", credentials.secret_key ? "success" : "warning", "값은 화면에 표시하지 않음")}
      ${metricCard("계좌", credentials.account ? "설정됨" : "선택 필요", credentials.account ? "success" : "not_evaluated", "계좌 범위 GET 조회용")}
      ${metricCard("GET 엔드포인트", endpointRows.length, "success", "구현된 read-only API")}
      ${metricCard("계좌 필요 API", status.account_required_for?.length || 0, "not_evaluated", "X-Tossinvest-Account 필요")}
      ${metricCard("POST 요청", "없음", "success", "POST/PATCH/DELETE 미구현")}
    </section>
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div><h2>계좌 선택</h2><p>선택한 계좌는 이 브라우저의 Jayu 콘솔에서 보유/매도가능수량 같은 계좌 범위 GET 조회에 사용됩니다.</p></div>
        ${statusBadge(accountData.status === "success" ? "success" : accountData.status === "failed" ? "failed" : "warning")}
      </div>
      ${renderTossAccountSetup(accountData, accounts)}
      ${renderSourceCaption("Toss Open API accounts GET")}
    </section>
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div><h2>종목 Market snapshot</h2><p>현재가, 종목정보, 주의사항, 상하한가, 호가, 체결, 1일/1분 캔들을 GET으로 묶어 조회합니다.</p></div>
      </div>
      <form id="toss-market-form" class="inline-form">
        <label>
          <span>Symbol</span>
          <input id="toss-symbol-input" name="symbol" value="${escapeHtml(market?.symbol || "AAPL")}" autocomplete="off" inputmode="latin">
        </label>
        <label>
          <span>Account</span>
          ${renderTossAccountControl(accounts)}
        </label>
        <label class="checkbox-field">
          <input id="toss-include-account" name="include_account" type="checkbox" ${state.selectedTossAccount ? "checked" : ""}>
          <span>보유/매도가능수량 포함</span>
        </label>
        <button class="button button-primary" type="submit">조회</button>
      </form>
      ${renderSourceCaption("Toss prices/stocks/warnings/price-limits/orderbook/trades/candles GET")}
      <p id="toss-feedback" class="metric-detail" hidden></p>
    </section>
    ${market ? renderTossSnapshot(market) : renderTossEmptyState(status)}
    <section class="panel">
      <div class="panel-header"><div><h2>구현된 GET 엔드포인트</h2><p>토큰 발급을 제외한 API 호출은 모두 GET입니다.</p></div></div>
      ${renderTossEndpointTable(endpointRows)}
      ${renderSourceCaption("TOSS_GET_ENDPOINTS registry")}
    </section>
  `;
}

function renderTossAccountSetup(accountData, accounts) {
  if (accountData.status === "missing_credentials") {
    return emptyTable(
      "Toss API 키가 필요합니다.",
      "TS_API_KEY와 TS_SECRET_KEY를 설정하면 계좌 목록을 GET으로 조회할 수 있습니다."
    );
  }
  if (accountData.status === "failed") {
    return emptyTable("계좌 조회에 실패했습니다.", accountData.error || "Toss accounts 응답을 확인하세요.");
  }
  if (!accounts.length) {
    return emptyTable("조회 가능한 계좌가 없습니다.", "Toss API 권한과 계좌 연결 상태를 확인하세요.");
  }
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>선택</th><th>계좌</th><th>마스킹 번호</th><th>유형</th><th>통화</th><th>권한</th></tr></thead>
      <tbody>${accounts.map((account) => `
        <tr>
          <td>
            <button class="button ${account.account_seq === state.selectedTossAccount ? "button-primary" : "button-secondary"}" type="button" data-toss-account="${escapeHtml(account.account_seq)}">
              ${account.account_seq === state.selectedTossAccount ? "선택됨" : "선택"}
            </button>
          </td>
          <td><strong>${escapeHtml(account.display_name || "Toss account")}</strong>${account.is_default ? " " + statusBadge("success", "기본") : ""}</td>
          <td class="code">${escapeHtml(account.masked_account_no || "-")}</td>
          <td>${escapeHtml(account.account_type || "-")}</td>
          <td>${escapeHtml(account.currency || "-")}</td>
          <td>${statusBadge("success", "조회")} ${statusBadge("not_evaluated", "주문 비활성")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function filterTossHoldingsByRegion(rows) {
  if (state.tossAccountRegion === "ALL") return rows || [];
  return (rows || []).filter((row) => row.market_region === state.tossAccountRegion);
}

function summarizeTossHoldings(rows, fallbackSummary = {}) {
  if (state.tossAccountRegion === "ALL") {
    return {
      ...fallbackSummary,
      total_market_value_krw: fallbackSummary.total_market_value,
      unrealized_pnl_krw: fallbackSummary.unrealized_pnl,
    };
  }
  const totalMarket = rows.reduce((sum, row) => sum + (Number(row.market_value_krw) || 0), 0);
  const totalCost = rows.reduce((sum, row) => sum + (Number(row.cost_basis_krw) || 0), 0);
  const pnl = rows.reduce((sum, row) => sum + (Number(row.unrealized_pnl_krw) || 0), 0);
  return {
    status: rows.length ? "success" : "not_evaluated",
    holding_count: rows.length,
    total_market_value_krw: totalMarket,
    total_cost_basis_krw: totalCost,
    unrealized_pnl_krw: pnl,
    unrealized_pnl_pct: totalCost ? pnl / totalCost : null,
  };
}

function renderTossRegionTabs(regionTotals) {
  const counts = Object.fromEntries((regionTotals || []).map((row) => [row.region, row.count]));
  const tabs = [
    ["ALL", "전체", Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0)],
    ["KR", "한국", counts.KR || 0],
    ["US", "미국", counts.US || 0],
  ];
  return `<div class="segmented-tabs" role="tablist" aria-label="Toss account market filter">${tabs
    .map(([value, label, count]) => `
      <button class="${state.tossAccountRegion === value ? "is-active" : ""}" type="button" role="tab" data-toss-region="${value}" aria-selected="${state.tossAccountRegion === value}">
        <span>${label}</span><strong>${formatNumber(count, 0)}</strong>
      </button>`)
    .join("")}</div>`;
}

function renderExposureDonut(rows, keyName) {
  const filtered = (rows || []).filter((row) => Number(row.market_value_krw) > 0);
  if (!filtered.length) {
    return '<div class="empty-state"><strong>노출 비중이 없습니다.</strong><span>평가금액 환산이 완료되면 차트가 채워집니다.</span></div>';
  }
  let cursor = 0;
  const colors = ["#175cd3", "#126b45", "#b42318", "#8a4b08", "#475467"];
  const segments = filtered
    .map((row, index) => {
      const start = cursor;
      const end = cursor + Number(row.weight || 0) * 100;
      cursor = end;
      return `${colors[index % colors.length]} ${start}% ${end}%`;
    })
    .join(", ");
  return `
    <div class="donut-layout">
      <div class="donut-chart" style="background: conic-gradient(${segments})" aria-hidden="true"></div>
      <div class="donut-legend">
        ${filtered.map((row, index) => `
          <div class="legend-row">
            <span class="legend-dot" style="background:${colors[index % colors.length]}"></span>
            <strong>${escapeHtml(row[keyName] || "-")}</strong>
            <span>${formatPercent(row.weight, 1)} · ${formatCurrency(row.market_value_krw, "KRW")}</span>
          </div>`).join("")}
      </div>
    </div>`;
}

function renderFxRateCards(rows) {
  const usable = rows || [];
  if (!usable.length) {
    return '<div class="empty-state"><strong>환율 데이터가 없습니다.</strong><span>USD 보유 종목이 있으면 USD/KRW 환율을 조회합니다.</span></div>';
  }
  return `<div class="fx-card-list">${usable
    .map((row) => `
      <div class="fx-card">
        <span>${escapeHtml(row.base_currency || "-")} / ${escapeHtml(row.quote_currency || "-")}</span>
        <strong>${row.rate == null ? "미계산" : formatNumber(row.rate, 4)}</strong>
        <small>${escapeHtml(row.valid_from || row.rate_change_type || row.status || "-")}</small>
      </div>`)
    .join("")}</div>`;
}

function renderFxImpactPanel(impact) {
  const data = impact || {};
  const summary = data.summary || {};
  const rows = data.rows || [];
  if (!rows.length) {
    return '<div class="empty-state"><strong>FX 영향 분리 데이터가 없습니다.</strong><span>Toss holdings, prices, exchange-rate 조회가 모두 있어야 계산됩니다.</span></div>';
  }
  return `
    <div class="fx-impact">
      <div class="fx-impact-summary">
        <div>
          <span>가격 효과</span>
          <strong class="${numericClass(summary.asset_effect_krw)}">${formatCurrency(summary.asset_effect_krw, "KRW")}</strong>
        </div>
        <div>
          <span>환율 효과</span>
          <strong class="${numericClass(summary.fx_effect_krw)}">${formatCurrency(summary.fx_effect_krw, "KRW")}</strong>
        </div>
        <div>
          <span>교차항</span>
          <strong class="${numericClass(summary.cross_effect_krw)}">${formatCurrency(summary.cross_effect_krw, "KRW")}</strong>
        </div>
      </div>
      <div class="fx-impact-list">
        ${rows.map((row) => `
          <div class="fx-impact-row status-${statusClass(row.fx_impact_status || "not_evaluated")}">
            <div>
              <strong>${escapeHtml(row.symbol || "-")}</strong>
              <span>${escapeHtml(row.currency || "-")} · 가격 ${formatPercent(row.asset_return_pct, 2)} · FX ${formatPercent(row.fx_return_pct, 2)}</span>
            </div>
            <div>
              <strong class="${numericClass(row.total_day_pnl_krw)}">${formatCurrency(row.total_day_pnl_krw, "KRW")}</strong>
              <span>FX ${formatCurrency(row.fx_effect_krw, "KRW")}</span>
            </div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderAccountAttributionPanel(attribution) {
  const data = attribution || {};
  const summary = data.summary || {};
  const rows = data.rows || [];
  if (!rows.length) {
    return '<div class="empty-state"><strong>계좌 변화 분해 데이터가 없습니다.</strong><span>jayu report account-attribution 실행 후 이전/현재 스냅샷 차이가 표시됩니다.</span></div>';
  }
  return `
    <div class="account-attribution">
      <div class="account-attribution-summary">
        <div>
          <span>계좌 변화</span>
          <strong class="${numericClass(summary.account_value_delta_krw)}">${formatCurrency(summary.account_value_delta_krw, "KRW")}</strong>
        </div>
        <div>
          <span>가격 효과</span>
          <strong class="${numericClass(summary.price_effect_krw)}">${formatCurrency(summary.price_effect_krw, "KRW")}</strong>
        </div>
        <div>
          <span>환율 효과</span>
          <strong class="${numericClass(summary.fx_effect_krw)}">${formatCurrency(summary.fx_effect_krw, "KRW")}</strong>
        </div>
        <div>
          <span>현금/보유 변화</span>
          <strong class="${numericClass(Number(summary.cash_delta_krw || 0) + Number(summary.holding_flow_krw || 0))}">${formatCurrency(Number(summary.cash_delta_krw || 0) + Number(summary.holding_flow_krw || 0), "KRW")}</strong>
        </div>
      </div>
      <div class="account-attribution-list">
        ${rows.slice(0, 6).map((row) => `
          <div class="account-attribution-row status-${statusClass(row.status || "not_evaluated")}">
            <div>
              <strong>${renderTicker(row.symbol)}</strong>
              <span>${escapeHtml(accountAttributionEffectLabel(row.dominant_effect))} · ${escapeHtml(row.position_status || "-")}</span>
              ${renderSourceLabel(row.source || data.source || "account_attribution.json")}
            </div>
            <div>
              <strong class="${numericClass(row.value_delta_krw)}">${formatCurrency(row.value_delta_krw, "KRW")}</strong>
              <span>가격 ${formatCurrency(row.price_effect_krw, "KRW")} · FX ${formatCurrency(row.fx_effect_krw, "KRW")}</span>
            </div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function accountAttributionEffectLabel(effect) {
  return {
    price: "가격",
    fx: "환율",
    flow: "현금/보유",
    none: "변화 없음",
  }[effect] || "기타";
}

function numericClass(value) {
  const parsed = Number(value);
  if (Number.isNaN(parsed) || parsed === 0) return "";
  return parsed < 0 ? "negative" : "positive";
}

function renderSituationTags(rows) {
  const tags = rows || [];
  if (!tags.length) {
    return '<div class="empty-state"><strong>상황 태그가 없습니다.</strong><span>종목 메타와 가격 정보가 보강되면 태그가 채워집니다.</span></div>';
  }
  return `<div class="tag-cloud">${tags
    .map((row) => `
      <div class="tag-pill">
        <strong>${escapeHtml(row.tag || "-")}</strong>
        <span>${formatNumber(row.count, 0)}종목 · ${formatPercent(row.weight, 1)}</span>
      </div>`)
    .join("")}</div>`;
}

function renderPortfolioTypeCards(rows) {
  const items = rows || [];
  if (!items.length) {
    return '<div class="empty-state"><strong>포트폴리오 타입 데이터가 없습니다.</strong><span>holdings 응답과 portfolio_mapping.json을 읽으면 자동으로 채워집니다.</span></div>';
  }
  return `<div class="portfolio-type-grid">${items
    .map((row) => {
      const status = Number(row.warning_count || 0) > 0 ? "warning" : Number(row.count || 0) ? "success" : "not_evaluated";
      return `
        <article class="portfolio-type-card">
          <div class="portfolio-type-card-head">
            <strong>${escapeHtml(row.label || row.type || "-")}</strong>
            ${statusBadge(status, row.risk_level || "risk")}
          </div>
          <p>${escapeHtml(row.description || "")}</p>
          <div class="portfolio-type-metrics">
            <span><b>${formatNumber(row.count, 0)}</b>종목</span>
            <span><b>${formatPercent(row.weight, 1)}</b>비중</span>
            <span><b>${formatCurrency(row.market_value_krw, "KRW")}</b></span>
          </div>
          <small>확인: ${escapeHtml(row.focus || "-")}</small>
          ${(row.checklist || []).length ? `<ul>${row.checklist.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
          ${row.symbols?.length ? `<span class="portfolio-type-symbols">${row.symbols.map(escapeHtml).join(" · ")}</span>` : ""}
          ${renderSourceLabel(row.source || "portfolio_mapping.json · Toss holdings/stocks metadata")}
        </article>`;
    })
    .join("")}</div>`;
}

function renderPortfolioTypeBadges(row) {
  const labels = row.portfolio_type_labels?.length
    ? row.portfolio_type_labels
    : row.primary_portfolio_type_label
      ? [row.primary_portfolio_type_label]
      : [];
  if (!labels.length) return "-";
  return labels.map((label) => `<span>${escapeHtml(label)}</span>`).join("");
}

function renderPnlContributors(rows) {
  const ranked = [...(rows || [])]
    .filter((row) => row.unrealized_pnl_krw !== null && row.unrealized_pnl_krw !== undefined)
    .sort((a, b) => Math.abs(Number(b.unrealized_pnl_krw || 0)) - Math.abs(Number(a.unrealized_pnl_krw || 0)))
    .slice(0, 12);
  if (!ranked.length) {
    return '<div class="empty-state"><strong>손익 기여도가 없습니다.</strong><span>손익 필드가 있는 holdings 응답이면 자동 계산됩니다.</span></div>';
  }
  const maxAbs = Math.max(...ranked.map((row) => Math.abs(Number(row.unrealized_pnl_krw) || 0)), 1);
  return `<div class="pnl-bar-list">${ranked
    .map((row) => {
      const value = Number(row.unrealized_pnl_krw) || 0;
      const width = Math.max(4, Math.min(100, (Math.abs(value) / maxAbs) * 100));
      return `
        <div class="pnl-bar-row ${value < 0 ? "is-negative" : "is-positive"}">
          <div><strong>${escapeHtml(row.symbol || "-")}</strong><span>${escapeHtml(row.name || row.market_region || "-")}</span></div>
          <div class="pnl-bar-track" aria-hidden="true"><span style="width:${width}%"></span></div>
          <div class="pnl-bar-meta">${formatCurrency(value, "KRW")}</div>
        </div>`;
    })
    .join("")}</div>`;
}

function fxRateLabel(rows, baseCurrency) {
  const row = (rows || []).find((item) => item.base_currency === baseCurrency);
  if (!row) return baseCurrency === "USD" ? "불필요" : "-";
  return row.rate == null ? "미계산" : formatNumber(row.rate, 2);
}

function fxRateStatus(rows, baseCurrency) {
  const row = (rows || []).find((item) => item.base_currency === baseCurrency);
  if (!row) return "not_evaluated";
  return row.status === "success" && row.rate != null ? "success" : "warning";
}

function fxRateDetail(rows, baseCurrency) {
  const row = (rows || []).find((item) => item.base_currency === baseCurrency);
  if (!row) return "USD holdings 없음";
  return row.valid_from || row.message || "KRW 환산";
}

function renderTossAccountCards(accounts, selected) {
  if (!accounts.length) {
    return emptyTable("조회 가능한 계좌가 없습니다.", "Toss API 권한과 계좌 연결 상태를 확인하세요.");
  }
  return `<div class="account-card-grid">${accounts
    .map((account) => {
      const isSelected = account.account_seq === selected.account_seq;
      return `
        <button class="account-card ${isSelected ? "is-selected" : ""}" type="button" data-toss-account="${escapeHtml(account.account_seq)}">
          <span>${isSelected ? "Selected" : "Account"}</span>
          <strong>${escapeHtml(account.display_name || "Toss account")}</strong>
          <small class="code">${escapeHtml(account.masked_account_no || "-")}</small>
          <small>${escapeHtml([account.account_type, account.currency].filter(Boolean).join(" / ") || "read only")}</small>
        </button>`;
    })
    .join("")}</div>`;
}

function renderHoldingAllocation(rows) {
  if (!rows?.length) {
    return '<div class="empty-state"><strong>보유 비중 데이터가 없습니다.</strong><span>holdings 응답에 평가금액이 있으면 자동으로 채워집니다.</span></div>';
  }
  return `<div class="holding-allocation">${rows
    .map((row) => {
      const width = Math.max(3, Math.min(100, Number(row.weight || 0) * 100));
      return `
        <div class="holding-bar-row">
          <div>
            <strong>${escapeHtml(row.symbol || "-")}</strong>
            <span>${escapeHtml(row.name || row.currency || "-")}</span>
          </div>
          <div class="holding-bar-track" aria-hidden="true"><span style="width:${width}%"></span></div>
          <div class="holding-bar-meta">
            <strong>${formatPercent(row.weight, 1)}</strong>
            <span>${formatCurrency(row.market_value_krw, "KRW")}</span>
          </div>
        </div>`;
    })
    .join("")}</div>`;
}

function renderTossHoldingsTable(rows) {
  if (!rows?.length) {
    return emptyTable("보유 종목이 없습니다.", "Toss holdings 응답이 비어 있거나 아직 계좌 조회가 완료되지 않았습니다.");
  }
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Symbol</th><th>Market</th><th>투자 타입</th><th>Category</th><th>Sector</th><th>Name</th><th class="numeric">Qty</th><th class="numeric">KRW value</th><th class="numeric">P/L KRW</th><th class="numeric">P/L %</th><th class="numeric">Day %</th><th class="numeric">FX day</th><th class="numeric">Weight</th><th>Tags</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${renderTicker(row.symbol)}</td>
          <td>${statusBadge(row.market_region === "US" ? "warning" : row.market_region === "KR" ? "success" : "not_evaluated", row.market_region || "-")}</td>
          <td class="tag-cell portfolio-type-cell">${renderPortfolioTypeBadges(row)}<small>${escapeHtml(row.portfolio_type_focus || "-")}</small>${renderSourceLabel(row.portfolio_type_source || "portfolio_mapping.json · Toss holdings/stocks metadata")}</td>
          <td>${escapeHtml(row.category || row.asset_type || "-")}</td>
          <td>${escapeHtml(row.sector || "-")}</td>
          <td>${escapeHtml(row.name || "-")}</td>
          <td class="numeric">${formatNumber(row.quantity, 4)}</td>
          <td class="numeric">${formatCurrency(row.market_value_krw, "KRW")}</td>
          <td class="numeric ${Number(row.unrealized_pnl_krw || 0) < 0 ? "negative" : "positive"}">${formatCurrency(row.unrealized_pnl_krw, "KRW")}</td>
          <td class="numeric ${Number(row.unrealized_pnl_pct || 0) < 0 ? "negative" : "positive"}">${formatPercent(row.unrealized_pnl_pct, 2)}</td>
          <td class="numeric ${Number(row.day_change_pct || 0) < 0 ? "negative" : "positive"}">${formatPercent(row.day_change_pct, 2)}</td>
          <td class="numeric ${numericClass(row.fx_effect_krw)}">${formatCurrency(row.fx_effect_krw, "KRW")}</td>
          <td class="numeric">${formatPercent(row.weight, 1)}</td>
          <td class="tag-cell">${(row.situation_tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("") || "-"}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderTossAccountControl(accounts) {
  if (!accounts.length) {
    return `<input id="toss-account-input" name="account" value="${escapeHtml(state.selectedTossAccount)}" autocomplete="off" placeholder="선택 사항">`;
  }
  return `
    <select id="toss-account-input" name="account">
      <option value="">계좌 범위 조회 안 함</option>
      ${accounts.map((account) => `
        <option value="${escapeHtml(account.account_seq)}" ${account.account_seq === state.selectedTossAccount ? "selected" : ""}>
          ${escapeHtml(`${account.display_name || "Toss"} ${account.masked_account_no || ""}`.trim())}
        </option>`).join("")}
    </select>`;
}

function renderTossSnapshot(market) {
  const summary = market.summary || {};
  const sections = market.sections || {};
  const accountSections = market.account_sections || {};
  return `
    <section class="metric-grid">
      ${metricCard("조회 종목", market.symbol || "-", summary.status || "not_evaluated", "대문자 정규화")}
      ${metricCard("성공 섹션", summary.successful_sections || 0, summary.failed_sections ? "warning" : "success", "Market Data GET")}
      ${metricCard("실패 섹션", summary.failed_sections || 0, summary.failed_sections ? "failed" : "success", "개별 API 오류")}
      ${metricCard("계좌 섹션", summary.account_sections_included ? "포함" : "제외", "not_evaluated", "보유/매도가능수량")}
      ${metricCard("Read-only", market.read_only ? "예" : "아니오", market.read_only ? "success" : "blocked", "주문 요청 없음")}
      ${metricCard("다음 행동", summary.failed_sections ? "오류 확인" : "분석 계속", summary.failed_sections ? "warning" : "success", "섹션별 메시지 확인")}
    </section>
    <div class="section-grid">
      <section class="panel">
        <div class="panel-header"><div><h2>Market Data 결과</h2><p>가격, 종목정보, 호가, 체결, 캔들 응답 요약</p></div></div>
        ${renderTossSectionTable(sections)}
        ${renderSourceCaption("Toss prices/stocks/warnings/price-limits/orderbook/trades/candles GET")}
      </section>
      <section class="panel">
        <div class="panel-header"><div><h2>계좌 범위 결과</h2><p>선택한 경우에만 호출됩니다.</p></div></div>
        ${renderTossSectionTable(accountSections)}
        ${renderSourceCaption("Toss holdings/sellable-quantity GET")}
      </section>
    </div>
  `;
}

function renderTossEmptyState(status) {
  return `
    <section class="panel" style="margin-bottom:14px">
      ${emptyTable(
        status.status === "configured" ? "아직 조회한 종목이 없습니다." : "Toss API 키가 아직 준비되지 않았습니다.",
        status.status === "configured" ? "위 폼에서 AAPL, 005930 같은 심볼을 입력해 조회하세요." : "TS_API_KEY와 TS_SECRET_KEY를 설정한 뒤 새로고침하세요."
      )}
      ${renderSourceCaption("Toss status config · symbol form input · read-only GET policy")}
    </section>
  `;
}

function renderTossEndpointTable(rows) {
  if (!rows?.length) return emptyTable("엔드포인트 카탈로그가 없습니다.", "Toss status API 응답을 확인하세요.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Operation</th><th>Method</th><th>Path</th><th>Account</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="code">${escapeHtml(row.operation_id)}</td>
          <td>${statusBadge(row.method === "GET" ? "success" : "blocked", row.method)}</td>
          <td class="code">${escapeHtml(row.path)}</td>
          <td>${row.requires_account ? statusBadge("warning", "필요") : statusBadge("not_evaluated", "불필요")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderTossSectionTable(sections) {
  const entries = Object.entries(sections || {});
  if (!entries.length) return emptyTable("호출된 계좌 범위 섹션이 없습니다.", "계좌 정보를 포함하려면 체크박스를 선택하세요.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Section</th><th>Status</th><th class="numeric">Latency</th><th>Operation</th><th>Payload / Error</th></tr></thead>
      <tbody>${entries.map(([name, row]) => `
        <tr>
          <td><strong>${escapeHtml(name)}</strong></td>
          <td>${statusBadge(row.status === "success" ? "success" : "failed")}</td>
          <td class="numeric">${formatNumber(row.latency_ms, 1)} ms</td>
          <td class="code">${escapeHtml(row.operation_id || "-")}</td>
          <td class="code toss-payload">${escapeHtml(row.status === "success" ? compactJson(row.payload) : row.message || "-")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}
