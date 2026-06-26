const PORTFOLIO_TYPE_ORDER_HUB = ["short_term", "swing", "long_term", "dividend"];

const PORTFOLIO_TYPE_COLORS = {
  short_term: { bg: "#fef2f2", border: "#ef4444", text: "#ef4444", label: "단타" },
  swing:      { bg: "#fffbeb", border: "#f59e0b", text: "#d97706", label: "중타" },
  long_term:  { bg: "#eef2ff", border: "#6366f1", text: "#6366f1", label: "장타" },
  dividend:   { bg: "#f0fdf4", border: "#22c55e", text: "#16a34a", label: "배당" },
};

const SIGNAL_DISPLAY_HUB = {
  buy_candidate:  { label: "매수 후보",  color: "#22c55e", emoji: "🟢", bg: "rgba(34,197,94,0.10)" },
  weak_buy:       { label: "약한 매수",  color: "#86efac", emoji: "🔵", bg: "rgba(134,239,172,0.12)" },
  hold:           { label: "관망",       color: "#94a3b8", emoji: "⚪", bg: "rgba(148,163,184,0.08)" },
  weak_sell:      { label: "약한 매도",  color: "#fca5a5", emoji: "🟡", bg: "rgba(252,165,165,0.12)" },
  sell_candidate: { label: "매도 후보",  color: "#ef4444", emoji: "🔴", bg: "rgba(239,68,68,0.10)" },
  caution:        { label: "점검 필요",  color: "#f59e0b", emoji: "⚠️", bg: "rgba(245,158,11,0.10)" },
  insufficient:   { label: "데이터 부족", color: "#6b7280", emoji: "❓", bg: "rgba(107,114,128,0.08)" },
};

function hubSignalBadge(signalKey) {
  const d = SIGNAL_DISPLAY_HUB[signalKey] || SIGNAL_DISPLAY_HUB.hold;
  return `<span class="hub-signal-badge" style="background:${d.bg};color:${d.color};border:1px solid ${d.color}33">${d.emoji} ${d.label}</span>`;
}

function renderMarketRegimeBanner(regimeInfo) {
  if (!regimeInfo) return "";
  const r = regimeInfo.regime;
  const desc = regimeInfo.description;
  const metrics = regimeInfo.metrics || {};
  const weights = regimeInfo.weights || {};
  
  const emojis = { bull: "🐂", bear: "🐻", sideways: "↔️", volatile: "⚡", risk_off: "🚨" };
  const labels = { bull: "강세장 (Bull)", bear: "약세장 (Bear)", sideways: "횡보장 (Sideways)", volatile: "변동성 장세 (Volatile)", risk_off: "위험 회피 (Risk-off)" };
  const colors = { bull: "#22c55e", bear: "#ef4444", sideways: "#f59e0b", volatile: "#a855f7", risk_off: "#ef4444" };
  const bgColors = { bull: "rgba(34,197,94,0.04)", bear: "rgba(239,68,68,0.04)", sideways: "rgba(245,158,11,0.04)", volatile: "rgba(168,85,247,0.04)", risk_off: "rgba(239,68,68,0.06)" };

  const emoji = emojis[r] || "❓";
  const label = labels[r] || "알 수 없음";
  const color = colors[r] || "#64748b";
  const bg = bgColors[r] || "rgba(100,116,139,0.04)";

  const weightBadges = Object.entries(weights).map(([k, v]) => {
    const typeLabels = { short_term: "단타 ⚡", swing: "중타 📈", long_term: "장타 🏛️", dividend: "배당 💰" };
    const wColor = v >= 1.2 ? "#22c55e" : v <= 0.5 ? "#ef4444" : "#64748b";
    return `<span style="border: 1px solid ${wColor}33; background: ${wColor}11; color: ${wColor}; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; display: inline-block; margin: 2px">
      ${typeLabels[k] || k}: x${v}
    </span>`;
  }).join("");

  return `
    <div style="background: ${bg}; border-left: 4px solid ${color}; padding: 14px; border-radius: 8px; margin-bottom: 18px; box-shadow: 0 1px 2px rgba(0,0,0,0.02)">
      <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px">
        <div style="flex: 1; min-width: 250px">
          <h2 style="margin: 0 0 4px 0; font-size: 16px; color: ${color}; display: flex; align-items: center; gap: 8px; font-weight: bold; border-bottom: none">
            <span>${emoji}</span> 현재 시장 국면: <strong>${label}</strong>
          </h2>
          <p style="margin: 0; font-size: 12.5px; color: #475569; line-height: 1.4">${escapeHtml(desc)}</p>
        </div>
        <div style="text-align: right; min-width: 200px">
          <div style="margin-bottom: 4px; font-size: 11px; color: #64748b; font-weight: 600">포트폴리오 타입별 추천 승수</div>
          <div>${weightBadges}</div>
        </div>
      </div>
      <div style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed #e2e8f0; display: flex; flex-wrap: wrap; gap: 14px; font-size: 11.5px; color: #64748b">
        <span>📉 VIX 공포지수: <strong style="color:#334155">${metrics.vix || "—"}</strong></span>
        <span>💵 원달러 환율: <strong style="color:#334155">${metrics.usdkrw || "—"}원</strong></span>
        <span>🇺🇸 S&P 500 추세: <strong style="color: ${metrics.spy_trend === "bull" ? "#22c55e" : metrics.spy_trend === "bear" ? "#ef4444" : "#f59e0b"}">${metrics.spy_trend || "—"}</strong></span>
        <span>🇰🇷 KOSPI 추세: <strong style="color: ${metrics.kospi_trend === "bull" ? "#22c55e" : metrics.kospi_trend === "bear" ? "#ef4444" : "#f59e0b"}">${metrics.kospi_trend || "—"}</strong></span>
      </div>
    </div>
  `;
}

function renderDecisionOsMonitoring(data) {
  if (!data) return "";
  const retirement = data.strategy_retirement || {};
  const violations = data.playbook_violations || [];
  
  const retiredCards = (retirement.candidates || []).map(c => {
    const severityColor = c.severity === "critical" ? "#ef4444" : "#f59e0b";
    const reasons = (c.reasons_ko || []).map(r => `<li>${escapeHtml(r)}</li>`).join("");
    return `
      <div style="border: 1px solid ${severityColor}22; background: ${severityColor}05; padding: 10px; border-radius: 6px; margin-bottom: 8px">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px">
          <strong style="color: ${severityColor}; font-size: 13px">⚠️ 폐기 권고: ${escapeHtml(c.name)}</strong>
          <span style="font-size: 10px; background: ${severityColor}15; color: ${severityColor}; padding: 1px 5px; border-radius: 3px; font-weight: bold">${c.status === "retired" ? "영구폐기" : "폐기검토"}</span>
        </div>
        <ul style="margin: 0; padding-left: 14px; font-size: 11.5px; color: #475569; line-height:1.4">${reasons}</ul>
      </div>
    `;
  }).join("") || `<div style="text-align: center; color: #64748b; padding: 12px; font-size: 13px">✅ 성과가 양호하며 기준 이하인 폐기 대상 전략이 없습니다.</div>`;

  const violationRows = violations.slice(0, 8).map(v => {
    const actionLabels = { block_buy: "❌ 매수차단", cooldown: "⏳ 쿨다운", warn: "⚠️ 경고" };
    const actionColors = { block_buy: "#ef4444", cooldown: "#f59e0b", warn: "#eab308" };
    const actionLabel = actionLabels[v.action] || v.action;
    const color = actionColors[v.action] || "#64748b";
    const timeStr = v.timestamp ? new Date(v.timestamp).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";

    return `
      <div style="display: flex; align-items: flex-start; gap: 8px; border-bottom: 1px solid #f1f5f9; padding: 6px 0; font-size: 11.5px; line-height: 1.4">
        <span style="color: #94a3b8; min-width: 60px">${timeStr}</span>
        <span style="font-weight: bold; min-width: 50px">${escapeHtml(v.ticker)}</span>
        <span style="color: #475569; min-width: 45px">${escapeHtml(v.portfolio_type === "short_term" ? "단타" : v.portfolio_type === "swing" ? "중타" : v.portfolio_type === "long_term" ? "장타" : "배당")}</span>
        <span style="background: ${color}15; color: ${color}; padding: 1px 4px; border-radius: 3px; font-weight: bold; font-size: 10px; min-width: 55px; text-align: center; display: inline-block">${escapeHtml(actionLabel)}</span>
        <span style="color: #334155; flex: 1">${escapeHtml(v.reason_ko)}</span>
      </div>
    `;
  }).join("") || `<div style="text-align: center; color: #64748b; padding: 20px; font-size: 12.5px">원칙 위반 감사 내역이 없습니다.</div>`;

  return `
    <section style="margin-top: 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px">
      <div class="hub-checklist-section" style="margin: 0; padding: 16px; border: 1px solid #e2e8f0; border-radius: 8px">
        <h2 style="font-size: 14px; margin: 0 0 10px 0; color: #1e293b; display: flex; align-items: center; gap: 6px; font-weight: bold; border-bottom: none">
          <span>🛡️</span> 전략 사용 승인 & 폐기 심사
        </h2>
        <p style="font-size: 11px; color: #64748b; margin: 0 0 12px 0">${escapeHtml(retirement.recommendation_summary || "")}</p>
        <div style="max-height: 220px; overflow-y: auto">${retiredCards}</div>
      </div>
      <div class="hub-checklist-section" style="margin: 0; padding: 16px; border: 1px solid #e2e8f0; border-radius: 8px">
        <h2 style="font-size: 14px; margin: 0 0 10px 0; color: #1e293b; display: flex; align-items: center; gap: 6px; font-weight: bold; border-bottom: none">
          <span>📜</span> 투자 규칙 위반 감사 로그 (Audit Log)
        </h2>
        <p style="font-size: 11px; color: #64748b; margin: 0 0 12px 0">플레이북 투자 원칙을 위반해 실시간 감지 및 조치된 최신 로그입니다.</p>
        <div style="max-height: 220px; overflow-y: auto; display: flex; flex-direction: column">${violationRows}</div>
      </div>
    </section>
  `;
}

function renderPortfolioHub() {
  const data = state.portfolioHub;
  const tab = state.portfolioHubTab || "short_term";

  // 설명 수준 동기화
  if (data && data.explanation_level) {
    const expSelector = document.querySelector("#explanation-level-selector");
    if (expSelector) expSelector.value = data.explanation_level;
  }

  const tabButtons = PORTFOLIO_TYPE_ORDER_HUB.map(pt => {
    const c = PORTFOLIO_TYPE_COLORS[pt];
    const isActive = pt === tab;
    const summary = data?.type_summaries?.[pt];
    const cnt = summary?.ticker_count ?? 0;
    const buyN = summary?.buy_candidate_count ?? 0;
    return `<button class="hub-tab-btn ${isActive ? "is-active" : ""}" data-hub-tab="${pt}"
      style="border-bottom-color:${isActive ? c.border : "transparent"};color:${isActive ? c.text : "#64748b"}">
      ${c.label} <span class="hub-tab-count">${cnt}종목</span>
      ${buyN > 0 ? `<span class="hub-tab-badge" style="background:${c.border}">${buyN}</span>` : ""}
    </button>`;
  }).join("");

  const tabContent = data ? renderHubTabContent(data, tab) : `
    <div class="hub-load-area">
      <p>포트폴리오 허브 데이터를 불러오려면 조회 버튼을 클릭하세요.</p>
      <p style="font-size:12px;color:#94a3b8;margin-top:6px">portfolio_mapping.json의 종목이 자동으로 불러와집니다.</p>
    </div>`;

  const checklist = data?.today_checklist;

  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>포트폴리오 허브</h1>
        <p>단타 · 중타 · 장타 · 배당 4가지 투자 타입별로 보유 종목을 관리하고, 오늘 확인할 사항을 빠르게 파악합니다.</p>
      </div>
      <button id="btn-hub-load" class="button button-primary">📊 데이터 조회</button>
    </div>

    ${renderMarketRegimeBanner(data?.market_regime)}
    ${renderHubTodayChecklist(checklist)}
    ${renderHubSignalConflictPanel(data?.signal_conflicts)}

    <div class="hub-ticker-input-row">
      <label for="hub-tickers-input" style="font-size:13px;font-weight:600;color:#475569">종목 직접 입력 (선택사항)</label>
      <input id="hub-tickers-input" class="hub-input" type="text"
        placeholder="SOXL,TQQQ,NVDA,QQQ (쉼표로 구분, 비워두면 포트폴리오 매핑 자동 사용)"
        value="${escapeHtml(state.portfolioHubTickers)}">
      <small style="color:#94a3b8;font-size:11px">비워두면 portfolio_mapping.json의 종목이 자동으로 사용됩니다.</small>
    </div>

    <div class="hub-tab-bar">${tabButtons}</div>
    <div id="hub-tab-content">${tabContent}</div>

    ${renderDecisionOsMonitoring(data)}

    <div class="hub-disclaimer">
      ⚠️ 이 화면의 신호와 지표는 <strong>투자 보조 분석 결과</strong>이며 투자 추천이 아닙니다.
      투자 결정과 결과에 대한 책임은 전적으로 투자자 본인에게 있습니다.
    </div>
  `;
}

function renderHubTodayChecklist(checklist) {
  if (!checklist) return "";
  const { buy_candidates = [], sell_candidates = [], risk_items = [], dividend_items = [], conflict_items = [] } = checklist;
  if (!buy_candidates.length && !sell_candidates.length && !risk_items.length && !dividend_items.length && !conflict_items.length) return "";

  const checklistReason = (item) => Array.isArray(item.reasons)
    ? (item.reasons[0] || "")
    : (item.reason || "");
  const renderItems = (items) => items.map(item => `
    <div class="hub-checklist-item">
      <span class="hub-checklist-signal">${hubSignalBadge(item.signal)}</span>
      <span class="hub-checklist-ticker">${renderTicker(item.ticker)}</span>
      <span class="hub-checklist-type">${escapeHtml(item.portfolio_type_label || "")}</span>
      <span class="hub-checklist-reason">${escapeHtml(checklistReason(item))}</span>
    </div>`).join("");

  return `
    <section class="hub-checklist-section">
      <h2>📋 오늘 확인할 사항</h2>
      <div class="hub-checklist-grid">
        ${buy_candidates.length ? `
        <div class="hub-checklist-group">
          <div class="hub-checklist-group-title" style="color:#22c55e">🟢 매수 후보 (${buy_candidates.length})</div>
          ${renderItems(buy_candidates)}
        </div>` : ""}
        ${sell_candidates.length ? `
        <div class="hub-checklist-group">
          <div class="hub-checklist-group-title" style="color:#ef4444">🔴 매도 후보 (${sell_candidates.length})</div>
          ${renderItems(sell_candidates)}
        </div>` : ""}
        ${risk_items.length ? `
        <div class="hub-checklist-group">
          <div class="hub-checklist-group-title" style="color:#f59e0b">⚠️ 급등락 확인 (${risk_items.length})</div>
          ${renderItems(risk_items)}
        </div>` : ""}
        ${dividend_items.length ? `
        <div class="hub-checklist-group">
          <div class="hub-checklist-group-title" style="color:#16a34a">💰 배당락 임박 (${dividend_items.length})</div>
          ${renderItems(dividend_items)}
        </div>` : ""}
        ${conflict_items.length ? `
        <div class="hub-checklist-group">
          <div class="hub-checklist-group-title" style="color:#b42318">⚠️ 신호 충돌 (${conflict_items.length})</div>
          ${renderItems(conflict_items)}
        </div>` : ""}
      </div>
      ${renderSourceCaption("portfolio_hub.py · Yahoo Finance OHLCV · portfolio_mapping.json")}
    </section>`;
}

function renderHubSignalConflictPanel(conflicts) {
  if (!conflicts) return "";
  const summary = conflicts.summary || {};
  const items = conflicts.items || [];
  const source = conflicts.source || summary.source || "portfolio_hub.py · Yahoo Finance OHLCV · portfolio_mapping.json";
  const tone = summary.high_count ? "blocked" : summary.medium_count || summary.watch_count ? "warning" : "success";
  const levelLabel = { high: "강한 충돌", medium: "시간축 충돌", watch: "주의", aligned: "정렬" };
  const actionLabel = {
    defer_order: "주문 보류",
    timeframe_review: "시간축 분리",
    risk_review: "리스크 점검",
    proceed_review: "일반 검토",
  };
  const itemHtml = items.length ? `
    <div class="hub-conflict-list">
      ${items.slice(0, 8).map((item) => `
        <article class="hub-conflict-card level-${escapeHtml(item.level || "watch")}">
          <div class="hub-conflict-head">
            <strong>${renderTicker(item.ticker)}</strong>
            ${statusBadge(item.level === "high" ? "blocked" : "warning", levelLabel[item.level] || item.level || "주의")}
          </div>
          <p>${escapeHtml(item.summary || "")}</p>
          <div class="hub-conflict-signals">
            ${(item.active_signals || []).map((signal) => `
              <span>
                <b>${escapeHtml(signal.portfolio_type_label || signal.portfolio_type || "-")}</b>
                ${hubSignalBadge(signal.signal || "hold")}
              </span>
            `).join("")}
          </div>
          <small>${escapeHtml(actionLabel[item.primary_action] || item.primary_action || "검토")} · ${escapeHtml(item.recommendation || "")}</small>
          ${renderSourceLabel(item.source || source)}
        </article>
      `).join("")}
    </div>
  ` : `
    <div class="hub-conflict-empty">
      <strong>신호 충돌 없음</strong>
      <span>활성 운용 타입 기준으로 매수/매도 결론이 크게 엇갈리지 않습니다.</span>
    </div>
  `;
  return `
    <section class="hub-conflict-section">
      <div class="hub-conflict-section-head">
        <div>
          <h2>신호 충돌 해석</h2>
          <p>단타 · 중타 · 장타 · 배당 신호가 서로 다른 결론을 낼 때 주문 보류 또는 시간축 분리를 제안합니다.</p>
        </div>
        ${statusBadge(tone, items.length ? `${items.length}건` : "정렬")}
      </div>
      <div class="hub-conflict-summary">
        <div><strong>${formatNumber(summary.high_count || 0, 0)}</strong><span>강한 충돌</span></div>
        <div><strong>${formatNumber(summary.medium_count || 0, 0)}</strong><span>시간축 충돌</span></div>
        <div><strong>${formatNumber(summary.watch_count || 0, 0)}</strong><span>주의</span></div>
        <div><strong>${formatNumber(summary.aligned_count || 0, 0)}</strong><span>정렬</span></div>
      </div>
      ${itemHtml}
      ${renderSourceCaption(source)}
    </section>
  `;
}

function renderHubTickerCard(tab, item) {
  const sig = item.signals?.[tab] || {};
  const sigKey = sig.signal || "hold";
  const d = SIGNAL_DISPLAY_HUB[sigKey] || SIGNAL_DISPLAY_HUB.hold;
  const price = item.latest_price != null ? `$${Number(item.latest_price).toFixed(2)}` : "—";
  const chg = item.change_pct != null ? `${item.change_pct >= 0 ? "+" : ""}${Number(item.change_pct).toFixed(2)}%` : "—";
  const chgClass = (item.change_pct || 0) >= 0 ? "text-up" : "text-down";

  const keyMetrics = renderHubKeyMetrics(item.ticker_info || {}, tab);
  const reasons = (sig.reasons || []).slice(0, 2).map(r => `<li>${escapeHtml(r)}</li>`).join("");
  const cautions = (sig.cautions || []).slice(0, 2).map(r => `<li class="hub-caution-item">${escapeHtml(r)}</li>`).join("");
  const priceSource = "Yahoo Finance OHLCV latest close · daily change";
  const metricSource = hubMetricSource(tab);
  const signalSource = "portfolio_hub.py signal rules · Yahoo Finance derived indicators";

  const dqColor = { good: "#22c55e", partial: "#f59e0b", poor: "#ef4444", unavailable: "#94a3b8" }[item.data_quality] || "#94a3b8";

  let extraBadges = "";
  if (sig.governance && !sig.governance.approved) {
    extraBadges += `<span style="background:#ef444412; color:#ef4444; border:1px solid #ef444433; font-size:10px; font-weight:bold; padding:1px 5px; border-radius:3px; margin-left:6px; display:inline-block">🛡️ 거버넌스 제한</span>`;
  }
  if (sig.cost_analysis && sig.cost_analysis.priority_downgrade) {
    extraBadges += `<span style="background:#f59e0b12; color:#b45309; border:1px solid #f59e0b33; font-size:10px; font-weight:bold; padding:1px 5px; border-radius:3px; margin-left:6px; display:inline-block">💰 비용 과다</span>`;
  }

  let playbookHtml = "";
  if (sig.playbook && sig.playbook.triggered_rules && sig.playbook.triggered_rules.length > 0) {
    playbookHtml = sig.playbook.triggered_rules.map(tr => `
      <div style="background:#ef444405; border: 1px solid #ef444422; color:#ef4444; font-size:11px; padding:6px 10px; border-radius:4px; margin-top:8px; display:flex; align-items:flex-start; gap:6px; line-height: 1.4">
        <span>📜</span> <div><strong>투자 규칙 위반 (${escapeHtml(tr.name)}):</strong> ${escapeHtml(tr.reason_ko)}</div>
      </div>
    `).join("");
  }

  let behaviorHtml = "";
  if (sig.behavioral_warnings && sig.behavioral_warnings.length > 0) {
    behaviorHtml = sig.behavioral_warnings.map(w => `
      <div style="background:#f59e0b05; border: 1px solid #f59e0b22; color:#b45309; font-size:11px; padding:6px 10px; border-radius:4px; margin-top:6px; display:flex; align-items:flex-start; gap:6px; line-height: 1.4">
        <span>⚠️</span> <div><strong>행동 가드 감지:</strong> ${escapeHtml(w.replace('⚠️ ', ''))}</div>
      </div>
    `).join("");
  }

  let costHtml = "";
  if (sig.cost_analysis && sig.cost_analysis.warning_msg) {
    costHtml = `
      <div style="background:#eab30805; border: 1px solid #eab30822; color:#854d0e; font-size:11px; padding:6px 10px; border-radius:4px; margin-top:6px; display:flex; align-items:flex-start; gap:6px; line-height: 1.4">
        <span>💵</span> <div><strong>비용 분석 (비중 ${sig.cost_analysis.cost_to_gain_ratio_pct}%):</strong> ${escapeHtml(sig.cost_analysis.warning_msg.replace('⚠️ ', '').replace('ℹ️ ', ''))}</div>
      </div>
    `;
  }

  return `
    <div class="hub-ticker-card" style="border-top:3px solid ${d.color}">
      <div class="hub-ticker-header">
        <div class="hub-ticker-name">
          <strong>${renderTicker(item.ticker)}</strong>
          <span class="hub-data-quality" style="color:${dqColor}" title="데이터 품질">●</span>
        </div>
        <div class="hub-ticker-price">
          <span class="hub-price">${price}</span>
          <span class="hub-change ${chgClass}">${chg}</span>
          ${renderSourceLabel(priceSource, "data-source-inline hub-price-source")}
        </div>
        <div style="display:flex; align-items:center; flex-wrap:wrap; gap:4px; justify-content:flex-end">
          ${hubSignalBadge(sigKey)}
          ${extraBadges}
        </div>
      </div>
      ${keyMetrics}
      ${renderSourceCaption(metricSource)}
      ${reasons || cautions ? `
      <div class="hub-ticker-reasons">
        <ul class="hub-reason-list">${reasons}${cautions}</ul>
      </div>` : ""}
      ${sig.stop_loss_ref ? `<div class="hub-stop-loss">📍 참고 손절가: <strong>$${Number(sig.stop_loss_ref).toFixed(2)}</strong> <small>(ATR × 1.5 기준)</small></div>` : ""}
      ${playbookHtml}
      ${behaviorHtml}
      ${costHtml}
      ${renderSourceCaption(signalSource)}
    </div>`;
}

function hubMetricSource(tab) {
  return {
    short_term: "Yahoo Finance OHLCV · derived RSI(2)/ATR/volume ratio",
    swing: "Yahoo Finance OHLCV · derived RSI(14)/MACD/EMA",
    long_term: "Yahoo Finance OHLCV · derived EMA200/52-week range",
    dividend: "Yahoo Finance info.dividendYield · info.exDividendDate · derived EMA200",
  }[tab] || "Yahoo Finance OHLCV · portfolio_hub.py derived indicators";
}

function hubSummaryCard(label, value, color, source) {
  const colorStyle = color ? ` style="color:${color}"` : "";
  const borderStyle = color ? ` style="border-top:3px solid ${color}"` : "";
  return `
    <div class="hub-stat-card"${borderStyle}>
      <div class="hub-stat-num"${colorStyle}>${escapeHtml(String(value))}</div>
      <div class="hub-stat-label">${escapeHtml(label)}</div>
      ${renderSourceLabel(source, "data-source-inline hub-source-inline")}
    </div>`;
}

function renderHubDividendCashflow(cashflow) {
  const data = cashflow || {};
  const summary = data.summary || {};
  const rows = data.rows || [];
  const status = data.status || "not_evaluated";
  const source = data.source || "Yahoo Finance info.dividendYield · info.exDividendDate · latest close";
  const money = (value) => value != null && !Number.isNaN(Number(value))
    ? `$${Number(value).toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "미계산";
  const pct = (value) => value != null && !Number.isNaN(Number(value)) ? `${formatNumber(value, 2)}%` : "미확인";
  const dayLabel = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "일정 미확인";
    const n = Number(value);
    if (n === 0) return "오늘 배당락";
    if (n > 0) return `${n}일 남음`;
    return `${Math.abs(n)}일 지남`;
  };
  const metricCards = [
    { label: "배당 종목", value: formatNumber(summary.ticker_count || 0, 0), detail: `${formatNumber(summary.calculable_count || 0, 0)}개 계산 가능` },
    { label: "평균 배당수익률", value: pct(summary.average_yield_pct), detail: "Yahoo dividendYield 기준" },
    { label: "1주 기준 연 추정 현금흐름", value: money(summary.estimated_annual_income_per_share_total), detail: "보유수량 미반영 합계" },
    { label: "배당락 임박", value: formatNumber(summary.upcoming_ex_dividend_count || 0, 0), detail: "45일 이내" },
  ].map((item) => `
    <div class="hub-dividend-metric">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <small>${escapeHtml(item.detail)}</small>
    </div>
  `).join("");
  const rowHtml = rows.length ? rows.map((row) => `
    <article class="hub-dividend-row status-${statusClass(row.status || "not_evaluated")}">
      <div class="hub-dividend-row-main">
        <strong>${renderTicker(row.ticker)}</strong>
        ${statusBadge(row.status || "not_evaluated")}
      </div>
      <div class="hub-dividend-row-metrics">
        <span><b>${pct(row.dividend_yield_pct)}</b><small>배당수익률</small></span>
        <span><b>${money(row.annual_income_per_share)}</b><small>1주 연 추정</small></span>
        <span><b>${escapeHtml(row.ex_dividend_date || "미확인")}</b><small>${escapeHtml(dayLabel(row.days_to_ex))}</small></span>
      </div>
      ${(row.notes || []).length ? `<div class="hub-dividend-notes">${row.notes.map((note) => `<span>${escapeHtml(note)}</span>`).join("")}</div>` : ""}
      ${renderSourceCaption(row.source || source)}
    </article>
  `).join("") : `<div class="hub-empty">배당 타입 종목이 없어 현금흐름을 계산하지 않았습니다.</div>`;

  return `
    <section class="hub-dividend-cashflow">
      <div class="hub-dividend-head">
        <div>
          <h2>배당 현금흐름 추정</h2>
          <p>${escapeHtml(summary.message || "배당 타입 종목의 1주 기준 현금흐름을 점검합니다.")}</p>
        </div>
        ${statusBadge(status)}
      </div>
      <div class="hub-dividend-metrics">${metricCards}</div>
      <p class="hub-dividend-note">${escapeHtml(summary.unit_note || "실제 계좌 현금흐름은 보유수량 연동 후 계산해야 합니다.")}</p>
      ${renderSourceCaption(source)}
      <div class="hub-dividend-list">${rowHtml}</div>
    </section>
  `;
}

function renderHubTabContent(data, tab) {
  const meta = data.portfolio_type_meta?.[tab] || {};
  const summary = data.type_summaries?.[tab] || {};
  const items = data.type_buckets?.[tab] || [];
  const c = PORTFOLIO_TYPE_COLORS[tab] || {};

  const typeDesc = `
    <div class="hub-type-card" style="border-left:4px solid ${c.border};background:${c.bg}">
      <div class="hub-type-header">
        <span style="font-size:22px">${meta.emoji || ""}</span>
        <div>
          <strong style="color:${c.text}">${meta.label || tab}</strong>
          <span class="hub-type-period">${meta.holding_period || ""}</span>
          <span class="hub-type-risk" style="color:${c.text}">위험도: ${meta.risk_level || ""}</span>
        </div>
      </div>
      <p style="margin:6px 0;font-size:13px;color:#475569">${escapeHtml(meta.description || "")}</p>
      <div class="hub-type-metrics">
        <strong style="font-size:11px;color:#64748b">핵심 지표:</strong>
        ${(meta.focus_metrics || []).map(m => `<span class="hub-metric-chip">${escapeHtml(m)}</span>`).join("")}
      </div>
      ${(meta.checklist || []).length ? `
      <div class="hub-type-checklist">
        <strong style="font-size:11px;color:#64748b">오늘 점검 사항:</strong>
        <ul>${meta.checklist.map(c => `<li>${escapeHtml(c)}</li>`).join("")}</ul>
      </div>` : ""}
      ${renderSourceCaption("portfolio_hub.py portfolio type meta · portfolio_mapping.json portfolio_types")}
    </div>`;

  const summaryCards = `
    <div class="hub-summary-row">
      ${hubSummaryCard("종목 수", summary.ticker_count || 0, "", "portfolio_mapping.json portfolio_types")}
      ${hubSummaryCard("매수 후보", summary.buy_candidate_count || 0, "#22c55e", "portfolio_hub.py signal rules · Yahoo Finance indicators")}
      ${hubSummaryCard("매도 후보", summary.sell_candidate_count || 0, "#ef4444", "portfolio_hub.py signal rules · Yahoo Finance indicators")}
      ${hubSummaryCard("점검 필요", summary.caution_count || 0, "#f59e0b", "portfolio_hub.py signal rules · Yahoo Finance indicators")}
    </div>`;
  const dividendCashflow = tab === "dividend" ? renderHubDividendCashflow(data.dividend_cashflow) : "";

  if (!items.length) {
    return typeDesc + summaryCards + dividendCashflow + `<div class="hub-empty">이 탭에 배정된 종목이 없습니다.<br><small>portfolio_mapping.json에서 portfolio_types에 <code>${tab}</code>을 추가하거나 위 입력창에 종목을 입력하세요.</small></div>`;
  }

  const ticker_rows = items.map(item => renderHubTickerCard(tab, item)).join("");

  return typeDesc + summaryCards + dividendCashflow + `<div class="hub-ticker-grid">${ticker_rows}</div>`;
}

function renderHubKeyMetrics(info, tab) {
  const fmt = (v, d = 2) => v != null ? Number(v).toFixed(d) : "—";
  const fmtPct = (v) => v != null ? `${v >= 0 ? "+" : ""}${Number(v).toFixed(1)}%` : "—";
  const rsiColor = (v) => {
    if (v == null) return "#94a3b8";
    if (v >= 70) return "#ef4444";
    if (v <= 30) return "#22c55e";
    return "#475569";
  };

  let metrics = [];
  if (tab === "short_term") {
    metrics = [
      { label: "RSI(2)", value: fmt(info.rsi2, 1), color: rsiColor(info.rsi2), tip: "2일 RSI: 10 이하→과매도, 90 이상→과매수" },
      { label: "ATR(14)", value: fmt(info.atr), tip: "14일 평균 변동폭" },
      { label: "거래량비율", value: info.volume_ratio != null ? `${fmt(info.volume_ratio, 1)}배` : "—", tip: "오늘 거래량 / 20일 평균" },
      { label: "당일등락", value: fmtPct(info.change_pct), color: (info.change_pct || 0) >= 0 ? "#22c55e" : "#ef4444", tip: "전일 대비 등락률" },
    ];
  } else if (tab === "swing") {
    metrics = [
      { label: "RSI(14)", value: fmt(info.rsi14, 1), color: rsiColor(info.rsi14), tip: "14일 RSI: 70↑ 과매수, 30↓ 과매도" },
      { label: "EMA20", value: fmt(info.ema20), tip: "20일 지수이동평균" },
      { label: "EMA50", value: fmt(info.ema50), tip: "50일 지수이동평균" },
      { label: "MACD", value: info.macd_hist != null ? (info.macd_hist >= 0 ? "+" : "") + fmt(info.macd_hist, 4) : "—", color: (info.macd_hist || 0) >= 0 ? "#22c55e" : "#ef4444", tip: "MACD 히스토그램: 양수→상승, 음수→하락" },
    ];
  } else if (tab === "long_term") {
    const regime = info.ema200 && info.latest_price
      ? (info.latest_price > info.ema200 * 1.02 ? "강세장" : info.latest_price < info.ema200 * 0.98 ? "약세장" : "횡보")
      : "—";
    const regimeColor = { "강세장": "#22c55e", "약세장": "#ef4444", "횡보": "#f59e0b" }[regime] || "#94a3b8";
    metrics = [
      { label: "EMA(200)", value: fmt(info.ema200), tip: "200일 지수이동평균 — 장기 추세 기준선" },
      { label: "레짐", value: regime, color: regimeColor, tip: "강세장: 가격 > EMA200×1.02, 약세장: 가격 < EMA200×0.98" },
      { label: "52주 수익률", value: fmtPct(info.change_52w_pct), color: (info.change_52w_pct || 0) >= 0 ? "#22c55e" : "#ef4444", tip: "1년간 주가 변화율" },
      { label: "52주 위치", value: info.near_52w_high ? "고점 근처" : info.near_52w_low ? "저점 근처" : "중간", tip: "현재 가격의 52주 고저 대비 위치" },
    ];
  } else if (tab === "dividend") {
    metrics = [
      { label: "배당수익률", value: info.dividend_yield != null ? `${fmt(info.dividend_yield, 1)}%` : "—", tip: "현재 주가 대비 연간 배당 비율" },
      { label: "배당락일", value: info.ex_dividend_date || "정보 없음", tip: "배당락일: 이 날짜 전 보유 시 배당 수령 가능" },
      { label: "EMA(200)", value: fmt(info.ema200), tip: "장기 추세 — 원금 보전 여부 확인용" },
      { label: "52주 수익률", value: fmtPct(info.change_52w_pct), color: (info.change_52w_pct || 0) >= 0 ? "#22c55e" : "#ef4444", tip: "" },
    ];
  }

  return `<div class="hub-key-metrics">${metrics.map(m => `
    <div class="hub-metric-item">
      <div class="hub-metric-label">${renderTooltip(m.label)}</div>
      <div class="hub-metric-value" style="${m.color ? `color:${m.color}` : ""}">${escapeHtml(String(m.value))}</div>
    </div>`).join("")}</div>`;
}

const INDICATOR_EXPLANATIONS = {
  "RSI": "상대강도지수(RSI): 14일간의 상승폭และ 하락폭 비율입니다. 30 이하면 과매도(반등 가능성), 70 이상이면 과매수(하락 가능성)로 봅니다.",
  "RSI(14)": "14일 상대강도지수: 30 이하면 과매도, 70 이상이면 과매수 상태를 의미합니다.",
  "RSI(2)": "2일 상대강도지수: 초단기 과매도/과매수 지표입니다. 10 이하면 극단적 과매도, 90 이상이면 극단적 과매수를 뜻합니다.",
  "EMA20": "20일 지수이동평균(단기): 최근 20일간의 가격 흐름입니다. 주가가 이 선 위에 있으면 단기 상승세입니다.",
  "EMA50": "50일 지수이동평균(중기): 최근 50일간의 가격 흐름입니다. 중기적인 추세 지지선 역할을 합니다.",
  "EMA(200)": "200일 지수이동평균(장기): 주식의 장기적인 대세 상승/하락을 판단하는 가장 중요한 기준선입니다.",
  "EMA200": "200일 지수이동평균(장기): 장기 추세 지지/저항선입니다.",
  "Volatility": "변동성(20일): 최근 주가 등락의 험난한 정도입니다. 수치가 높을수록 단기 급등락 위험이 큽니다.",
  "변동성": "최근 20일간 주가 변동성입니다. 높을수록 급등락 위험이 큽니다.",
  "MACD": "MACD: 단기 이동평균선과 장기 이동평균선의 차이입니다. 양수면 상승, 음수면 하락 추세를 의미합니다.",
  "Dividend Yield": "배당 수익률: 1년 동안 지급될 예상 배당금을 현재 주가로 나눈 비율입니다.",
  "배당수익률": "현재 주가 대비 연간 배당금의 비율(%)입니다.",
  "Payout Ratio": "배당 성향: 회사가 벌어들인 순이익 중 몇 %를 배당으로 지급하는지 나타냅니다. 100%가 넘으면 빚내서 배당하는 것일 수 있습니다.",
  "배당락일": "이 날짜 전날까지 주식을 매수해야 배당금을 받을 수 있습니다."
};

function renderTooltip(label, indicatorKey) {
  const key = indicatorKey || label;
  const backendExp = state.portfolioHub?.indicator_explanations?.[key];
  const explanation = backendExp 
    ? (backendExp.description || backendExp)
    : INDICATOR_EXPLANATIONS[key];
    
  if (!explanation) return escapeHtml(label);
  
  return `
    <span class="with-tooltip">
      ${escapeHtml(label)}
      <i class="tooltip-icon">i</i>
      <span class="tooltip-popup">${escapeHtml(explanation)}</span>
    </span>
  `;
}

function renderOverviewPortfolioHub(hubData) {
  if (!hubData) return "";

  const summaries = hubData.type_summaries || {};
  const checklist = hubData.today_checklist || {};

  const typeCards = PORTFOLIO_TYPE_ORDER_HUB.map(pt => {
    const c = PORTFOLIO_TYPE_COLORS[pt] || {};
    const sum = summaries[pt] || {};
    const count = sum.ticker_count || 0;
    const buys = sum.buy_candidate_count || 0;
    const cautions = sum.caution_count || 0;

    return `
      <div class="ov-hub-card" style="border-left: 3px solid ${c.border}">
        <div class="ov-hub-card-title" style="color:${c.text}">${c.label}</div>
        <div class="ov-hub-card-stats">
          <span>총 ${count}종목</span>
          ${buys > 0 ? `<span style="color:#22c55e">매수 ${buys}</span>` : ""}
          ${cautions > 0 ? `<span style="color:#f59e0b">점검 ${cautions}</span>` : ""}
        </div>
      </div>
    `;
  }).join("");

  return `
    <section class="ov-hub-section">
      <div class="panel-header" style="margin-bottom:12px;padding:0;">
        <div>
          <h2>포트폴리오 허브 요약</h2>
          <p>4가지 투자 타입별 현재 상태와 오늘 꼭 확인해야 할 종목입니다.</p>
        </div>
        <button class="button button-small" data-go="portfolio-hub">허브로 이동</button>
      </div>
      <div class="ov-hub-grid">
        ${typeCards}
      </div>
      ${renderHubTodayChecklist(checklist)}
    </section>
  `;
}
