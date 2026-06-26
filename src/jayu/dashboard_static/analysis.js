// ─── Analysis Page ────────────────────────────────────────────────────────────

const ANALYSIS_TABS = [
  { id: "market",    label: "🌐 시장 현황",       key: "analysisMarketOverview" },
  { id: "basic",     label: "📊 기본 분석",        key: "analysis" },
  { id: "technical", label: "📈 기술적 지표",      key: "analysisTechnical" },
  { id: "compare",   label: "⚖️ 멀티 비교",       key: "analysisCompare" },
  { id: "portfolio", label: "🏆 포트폴리오 성과", key: "analysisPortfolio" },
  { id: "calendar",  label: "📅 경제 캘린더",      key: "analysisCalendar" },
];

const TICKER_OPTIONS = ["SOXL","TQQQ","TSLA","AAPL","NVDA","NVDL","IONQ","QBTS","QQQ","SPY","MSFT","GOOGL","AMZN","META","AMD"];
const MACRO_OPTIONS = [
  { id: "FEDFUNDS",  label: "기준금리 (Fed Funds)" },
  { id: "CPIAUCSL",  label: "소비자물가지수 (CPI)" },
  { id: "UNRATE",    label: "실업률" },
  { id: "T10Y2Y",    label: "10년-2년 국채 스프레드" },
  { id: "GDPC1",     label: "실질 GDP" },
  { id: "M2SL",      label: "M2 통화량" },
  { id: "BAMLH0A0HYM2", label: "하이일드 스프레드" },
];
const PERIOD_OPTIONS = [
  { id: "3m", label: "3개월" }, { id: "6m", label: "6개월" },
  { id: "1y", label: "1년" }, { id: "2y", label: "2년" },
  { id: "5y", label: "5년" },
];

// ── formatters ─────────────────────────────────────────────────────────────
const _$ = (v, d = 2) => v == null ? "-" : `$${Number(v).toFixed(d)}`;
const _pct = (v, d = 2) => v == null ? "-" : `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(d)}%`;
const _num = (v, d = 2) => v == null ? "-" : Number(v).toFixed(d);
const _chgCls = (v) => Number(v) > 0 ? "analysis-positive" : Number(v) < 0 ? "analysis-negative" : "";
const _score = (v, d = 2) => v == null ? "-" : Number(v).toFixed(d);
const _volume = (v) => {
  if (v == null || Number.isNaN(Number(v))) return "-";
  const n = Number(v);
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
};
const _signalToneColor = (tone) => tone === "buy" ? "#16a34a" : tone === "sell" ? "#dc2626" : "#64748b";
const _statusForAction = (action) => action === "buy" ? "success" : action === "sell" ? "failed" : "warning";
const _statusForTone = (tone) => tone === "buy" ? "success" : tone === "sell" ? "failed" : tone === "warning" ? "warning" : "not-evaluated";

// ── SVG helpers ────────────────────────────────────────────────────────────
function _svgScale(vals, h, pad = 0.08) {
  const clean = vals.filter(v => v != null && !isNaN(v));
  if (!clean.length) return { min: 0, max: 1, toY: () => h / 2 };
  const mn = Math.min(...clean), mx = Math.max(...clean);
  const p = (mx - mn) * pad || Math.abs(mn) * 0.05 || 1;
  const lo = mn - p, hi = mx + p;
  return { min: lo, max: hi, toY: (v) => h - ((v - lo) / (hi - lo)) * h };
}
function _svgLine(pts, stroke, sw = 1.8, dash = "") {
  if (!pts.length) return "";
  return `<polyline fill="none" stroke="${stroke}" stroke-width="${sw}" stroke-linejoin="round" stroke-linecap="round" ${dash ? `stroke-dasharray="${dash}"` : ""} points="${pts.join(" ")}"/>`;
}
function _svgArea(pts, fill) {
  if (pts.length < 2) return "";
  const first = pts[0].split(","), last = pts[pts.length - 1].split(",");
  return `<polygon fill="${fill}" points="${pts.join(" ")} ${last[0]},9999 ${first[0]},9999"/>`;
}

function _renderTradingViewDetailsPanel(details, { compact = false } = {}) {
  if (!details || details.status !== "ok") {
    return details?.error ? `
      <section class="panel" style="margin-bottom:14px">
        <div class="panel-header"><div><h2>TradingView 상세 스냅샷</h2><p>${escapeHtml(details.error)}</p></div></div>
      </section>` : "";
  }

  const profile = details.profile || {};
  const quote = details.quote || {};
  const performance = details.performance || {};
  const volume = details.volume || {};
  const fund = details.fund || {};
  const derivatives = details.derivatives || {};
  const recommendation = quote.recommendation || {};
  const nav = fund.nav_discount_premium;
  const hasDerivativeData = ["open_interest", "iv", "delta", "gamma", "theta", "vega", "theo_price"].some((key) => derivatives[key] != null);
  const perfRows = [
    ["1주", performance.week],
    ["1개월", performance.one_month],
    ["3개월", performance.three_month],
    ["6개월", performance.six_month],
    ["YTD", performance.year_to_date],
    ["1년", performance.one_year],
  ];

  return `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div>
          <h2>TradingView 상세 스냅샷</h2>
          <p>${escapeHtml(details.symbol || "-")} · ${escapeHtml(profile.market || "-")} · ${escapeHtml(profile.country || "-")}</p>
        </div>
        <span class="status-badge status-${_statusForAction(recommendation.action)}">${escapeHtml(recommendation.label || "-")}</span>
      </div>
      <div class="panel-body">
        <section class="metric-grid" style="margin-bottom:12px">
          <div class="metric-card">
            <span class="metric-label">섹터 / 국가</span>
            <span class="metric-value" style="font-size:15px">${escapeHtml(profile.sector || "-")}</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">${escapeHtml(profile.country_code_fund || profile.country || "-")}</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
          <div class="metric-card">
            <span class="metric-label">52주 범위</span>
            <span class="metric-value" style="font-size:15px">${_$(quote.price_52_week_low)} - ${_$(quote.price_52_week_high)}</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">TradingView right-details</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
          <div class="metric-card">
            <span class="metric-label">1개월 범위</span>
            <span class="metric-value" style="font-size:15px">${_$(quote.low_1m)} - ${_$(quote.high_1m)}</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">고가/저가</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
          <div class="metric-card">
            <span class="metric-label">평균 거래량</span>
            <span class="metric-value" style="font-size:15px">${_volume(volume.average_10d)} / ${_volume(volume.average_30d)}</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">10일 / 30일</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
          <div class="metric-card">
            <span class="metric-label">NAV 프리미엄</span>
            <span class="metric-value ${_chgCls(nav)}" style="font-size:15px">${_pct(nav)}</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">ETF 괴리율</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
          <div class="metric-card">
            <span class="metric-label">추천 점수</span>
            <span class="metric-value" style="font-size:15px;color:${_signalToneColor(recommendation.tone)}">${_score(quote.recommend_all)}</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">${escapeHtml(recommendation.label || "-")}</span>
            ${renderSourceLabel("TradingView scanner right-details")}
          </div>
        </section>
        ${compact ? "" : `
        <div style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:13px">
            <thead><tr style="border-bottom:2px solid var(--border)">
              <th style="text-align:left;padding:7px 10px">성과</th>
              ${perfRows.map(([label]) => `<th style="text-align:right;padding:7px 10px">${label}</th>`).join("")}
            </tr></thead>
            <tbody>
              <tr style="border-bottom:1px solid var(--border)">
                <td style="padding:7px 10px;font-weight:700">수익률</td>
                ${perfRows.map(([, value]) => `<td class="${_chgCls(value)}" style="text-align:right;padding:7px 10px;font-weight:700">${_pct(value)}</td>`).join("")}
              </tr>
            </tbody>
          </table>
        </div>
        ${renderSourceCaption("TradingView scanner right-details performance fields")}
        ${hasDerivativeData ? `
        <div style="margin-top:10px;color:var(--muted);font-size:12px">
          옵션성 지표: OI ${_volume(derivatives.open_interest)} · IV ${_pct(derivatives.iv)} · Δ ${_score(derivatives.delta)} · Θ ${_score(derivatives.theta)} · Theo ${_$(derivatives.theo_price)}
          ${renderSourceLabel("TradingView scanner right-details derivative fields")}
        </div>` : ""}`}
      </div>
    </section>`;
}

function _renderTradingViewNewsFlow(newsFlow, { compact = false } = {}) {
  const source = "TradingView news-mediator news-flow";
  if (!newsFlow || !newsFlow.status) return "";
  if (newsFlow.status === "unavailable") {
    return newsFlow.error ? `
      <section class="panel" style="margin-bottom:14px">
        <div class="panel-header"><div><h2>TradingView 뉴스 플로우</h2><p>${escapeHtml(newsFlow.error)}</p></div></div>
        <div class="panel-body">${renderSourceCaption(source)}</div>
      </section>` : "";
  }

  const items = Array.isArray(newsFlow.items) ? newsFlow.items : [];
  const related = Array.isArray(newsFlow.related_symbols) ? newsFlow.related_symbols : [];
  const visibleItems = items.slice(0, compact ? 4 : 8);
  const visibleRelated = related.slice(0, compact ? 8 : 12);
  const context = newsFlow.news_context || {};
  const themes = Array.isArray(context.theme_counts) ? context.theme_counts : [];
  const dominantTheme = context.dominant_theme || themes[0] || {};
  const notes = Array.isArray(context.context_notes) ? context.context_notes : [];
  const providerCounts = newsFlow.provider_counts || {};
  const providers = Object.entries(providerCounts)
    .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
    .slice(0, 3)
    .map(([name, count]) => `${escapeHtml(name)} ${escapeHtml(count)}`);
  const themeToneClass = (tone) => ({
    buy: "is-buy",
    sell: "is-sell",
    warning: "is-warning",
  }[tone] || "is-neutral");
  const themeSymbols = (theme) => Array.isArray(theme?.symbols) ? theme.symbols.filter(Boolean).slice(0, 4).join(" · ") : "";
  const contextHtml = themes.length || notes.length ? `
    <section class="tv-news-context">
      <div class="tv-news-dominant ${themeToneClass(dominantTheme.tone)}">
        <span>주요 뉴스 맥락</span>
        <strong>${escapeHtml(dominantTheme.label || "테마 미분류")}</strong>
        <small>${escapeHtml(themeSymbols(dominantTheme) || "연관 심볼 없음")} · ${escapeHtml(dominantTheme.mention_count ?? 0)}회</small>
        ${renderSourceLabel(context.source || "TradingView news-mediator relatedSymbols · derived role map")}
      </div>
      <div class="tv-news-theme-list">
        ${themes.slice(0, compact ? 4 : 6).map((theme) => `
          <span class="tv-news-theme ${themeToneClass(theme.tone)}" title="${escapeHtml(theme.description || "")}">
            <strong>${escapeHtml(theme.label || "-")}</strong>
            <small>${escapeHtml(theme.mention_count ?? 0)}회 · ${escapeHtml(theme.symbol_count ?? 0)}종목</small>
          </span>`).join("")}
      </div>
      ${notes.length ? `
        <div class="tv-news-context-notes">
          ${notes.map((note) => `<span class="status-badge status-${_statusForTone(note.tone)}">${escapeHtml(note.text || "")}</span>`).join("")}
        </div>` : ""}
    </section>` : "";
  const relatedHtml = visibleRelated.length ? `
    <div class="tv-related-symbols">
      ${visibleRelated.map((row) => `
        <span class="tv-related-symbol" title="${escapeHtml(row.latest_title || "")}">
          <strong>${escapeHtml(row.symbol || "-")}</strong>
          <small>${escapeHtml(row.count ?? 0)}건 · ${escapeHtml(row.role?.label || "기타")}</small>
        </span>`).join("")}
    </div>
    ${renderSourceCaption("TradingView news-mediator relatedSymbols")}` : `
    <p style="margin:0;color:var(--muted);font-size:12px">연관 심볼 데이터가 없습니다.</p>
    ${renderSourceCaption("TradingView news-mediator relatedSymbols")}`;

  const newsHtml = visibleItems.length ? visibleItems.map((item) => {
    const provider = item.provider || {};
    const relatedSymbols = Array.isArray(item.related_symbols) ? item.related_symbols.filter((row) => !row.is_primary).slice(0, 7) : [];
    const relatedLine = relatedSymbols.length ? `
      <div class="tv-news-related-line">
        ${relatedSymbols.map((row) => `<span title="${escapeHtml(row.role?.label || "")}">${escapeHtml(row.symbol || "-")}</span>`).join("")}
      </div>` : "";
    return `
      <article class="analysis-news-item tv-news-item">
        <div class="analysis-news-meta">
          <span class="analysis-badge-neu">urgency ${escapeHtml(item.urgency ?? "-")}</span>
          <span class="analysis-news-source">${escapeHtml(provider.name || provider.id || "-")}</span>
          ${renderSourceLabel(source)}
          <span class="analysis-news-date">${formatDate(item.published_at)}</span>
        </div>
        <a class="analysis-news-title" href="${escapeHtml(item.url || "#")}" target="_blank" rel="noopener">${escapeHtml(item.title || "제목 없음")}</a>
        ${relatedLine}
      </article>`;
  }).join("") : `<p style="color:var(--muted);padding:10px 0">TradingView 뉴스 플로우 항목이 없습니다.</p>`;

  return `
    <section class="panel tv-news-panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div>
          <h2>TradingView 뉴스 플로우</h2>
          <p>${escapeHtml(newsFlow.symbol || "-")} · 최신 ${formatDate(newsFlow.latest_published_at)}${providers.length ? ` · ${providers.join(" · ")}` : ""}</p>
        </div>
        <span class="status-badge status-${items.length ? "success" : "not-evaluated"}">${escapeHtml(items.length)}건</span>
      </div>
      <div class="panel-body">
        ${contextHtml}
        <div class="tv-news-grid">
          <section>
            <h3>동반 언급 심볼</h3>
            ${relatedHtml}
          </section>
          <section>
            <h3>최근 뉴스</h3>
            <div class="analysis-news-list">${newsHtml}</div>
            ${renderSourceCaption(source)}
          </section>
        </div>
      </div>
    </section>`;
}

// ── Tab render coordinator ─────────────────────────────────────────────────
function renderAnalysis() {
  const tab = state.analysisTab || "market";
  const ticker = state.analysisTicker || "SOXL";
  const period = state.analysisPeriod || "1y";
  const macro = state.analysisMacro || "FEDFUNDS";

  const tabBar = `
    <div class="analysis-tab-bar">
      ${ANALYSIS_TABS.map(t => `
        <button class="analysis-tab-btn ${t.id === tab ? "is-active" : ""}"
          data-analysis-tab="${t.id}" type="button">${t.label}</button>
      `).join("")}
    </div>`;

  const pageHead = `
    <div class="page-heading" style="margin-bottom:12px">
      <div><h1>📈 주식 & 경제 분석</h1>
        <p>Yahoo Finance · FRED · 기술적 지표 · 섹터 현황을 통합 분석합니다.</p>
      </div>
    </div>`;

  els.root.innerHTML = pageHead + renderDataSourceNote("analysis") + tabBar + `<div id="analysis-tab-content"></div>`;

  const content = document.querySelector("#analysis-tab-content");

  if (tab === "market") {
    renderAnalysisMarket(content);
  } else if (tab === "basic") {
    renderAnalysisBasic(content, ticker, macro, period);
  } else if (tab === "technical") {
    renderAnalysisTechnical(content, ticker, period);
  } else if (tab === "compare") {
    renderAnalysisCompare(content, period);
  } else if (tab === "portfolio") {
    renderAnalysisPortfolio(content);
  } else if (tab === "calendar") {
    renderAnalysisCalendar(content);
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1: 시장 현황
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisMarket(container) {
  const data = state.analysisMarketOverview || {};

  if (!data.indices) {
    container.innerHTML = renderDataSourceNote("analysis", ["Yahoo Finance index/sector ETFs", "VIX proxy"]) + `<div class="analysis-loading">⏳ 시장 데이터를 불러오는 중... <button id="btn-load-market" class="button button-primary" style="margin-left:12px">조회</button></div>`;
    return;
  }

  const indices = data.indices || [];
  const sectors = data.sectors || [];
  const fg = data.fear_greed || { value: 50, label: "중립", vix: 20 };

  // Fear & Greed gauge (SVG semicircle)
  const fgAngle = (fg.value / 100) * 180 - 90; // -90 to 90 degrees
  const r = 54, cx = 70, cy = 68;
  const toRad = (deg) => (deg * Math.PI) / 180;
  const needle = {
    x: cx + r * 0.85 * Math.cos(toRad(fgAngle)),
    y: cy + r * 0.85 * Math.sin(toRad(fgAngle)),
  };
  const fgColor = fg.value >= 70 ? "#22c55e" : fg.value >= 55 ? "#84cc16" : fg.value >= 40 ? "#eab308" : fg.value >= 25 ? "#f97316" : "#ef4444";

  const fgGauge = `
    <svg viewBox="0 0 140 80" style="width:140px;height:80px" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="fgGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#ef4444"/>
          <stop offset="40%" stop-color="#f97316"/>
          <stop offset="60%" stop-color="#eab308"/>
          <stop offset="80%" stop-color="#84cc16"/>
          <stop offset="100%" stop-color="#22c55e"/>
        </linearGradient>
      </defs>
      <path d="M16,68 A54,54 0 0,1 124,68" fill="none" stroke="url(#fgGrad)" stroke-width="10" stroke-linecap="round"/>
      <line x1="${cx}" y1="${cy}" x2="${needle.x.toFixed(1)}" y2="${needle.y.toFixed(1)}" stroke="#1e293b" stroke-width="2.5" stroke-linecap="round"/>
      <circle cx="${cx}" cy="${cy}" r="4" fill="#1e293b"/>
      <text x="${cx}" y="${cy + 14}" text-anchor="middle" font-size="10" font-weight="700" fill="${fgColor}">${fg.label}</text>
      <text x="${cx}" y="${cy + 25}" text-anchor="middle" font-size="9" fill="#64748b">${fg.value} / 100</text>
    </svg>`;

  // Sparkline SVG
  const sparkSvg = (vals, positive) => {
    if (!vals || vals.length < 2) return `<svg width="60" height="20"></svg>`;
    const s = _svgScale(vals, 16, 0.05);
    const pts = vals.map((v, i) => `${(i / (vals.length - 1) * 58 + 1).toFixed(1)},${(s.toY(v) + 2).toFixed(1)}`);
    const col = positive ? "#22c55e" : "#ef4444";
    return `<svg width="60" height="20" xmlns="http://www.w3.org/2000/svg" style="overflow:visible">${_svgLine(pts, col, 1.5)}</svg>`;
  };

  // Sector heatmap
  const sectorHeatmap = sectors.map(s => {
    const pct = s.change_pct || 0;
    const intensity = Math.min(Math.abs(pct) / 3, 1);
    const bg = pct > 0
      ? `rgba(34,197,94,${0.15 + intensity * 0.45})`
      : `rgba(239,68,68,${0.15 + intensity * 0.45})`;
    const textColor = pct > 0 ? "#14532d" : "#7f1d1d";
    return `<div class="sector-cell" style="background:${bg};color:${textColor}">
      <span class="sector-name">${s.name}</span>
      <span class="sector-sym">${s.symbol}</span>
      <span class="sector-pct">${_pct(pct)}</span>
    </div>`;
  }).join("");

  container.innerHTML = `
    ${renderDataSourceNote("analysis", ["Yahoo Finance index/sector ETFs", "VIX proxy"])}
    <div class="analysis-market-grid">
      <!-- Fear & Greed + VIX -->
      <section class="panel analysis-fg-panel">
        <div class="panel-header"><div><h2>🎯 공포 & 탐욕 지수</h2><p>VIX 기반 시장 심리 추정</p></div></div>
        <div class="panel-body" style="display:flex;align-items:center;gap:20px;flex-wrap:wrap">
          ${fgGauge}
          <div>
            <div style="font-size:28px;font-weight:800;color:${fgColor}">${fg.value}</div>
            <div style="font-size:13px;font-weight:600;color:${fgColor}">${fg.label}</div>
            <div style="font-size:12px;color:var(--muted);margin-top:4px">VIX = ${_num(fg.vix)}</div>
            ${renderSourceLabel("Yahoo Finance VIX proxy")}
          </div>
        </div>
      </section>

      <!-- Reload button -->
      <div style="grid-column:1/-1;display:flex;justify-content:flex-end;margin-bottom:-6px">
        <button id="btn-load-market" class="button button-primary" type="button">🔄 시장 데이터 새로고침</button>
      </div>

      <!-- Major Indices -->
      <section class="panel" style="grid-column:1/-1">
        <div class="panel-header"><div><h2>📊 주요 지수 & 자산</h2></div></div>
        <div class="panel-body" style="overflow-x:auto">
          <div class="analysis-index-grid">
            ${indices.map(idx => {
              const up = idx.change_pct >= 0;
              return `<div class="analysis-index-card ${up ? "up" : "down"}">
                <div class="idx-name">${escapeHtml(idx.name)}</div>
                <div class="idx-price">${_num(idx.price, idx.price > 1000 ? 0 : 2)}</div>
                <div class="idx-chg ${_chgCls(idx.change_pct)}">${_pct(idx.change_pct)}</div>
                <div class="idx-spark">${sparkSvg(idx.sparkline, up)}</div>
                ${renderSourceLabel("Yahoo Finance quote/history")}
              </div>`;
            }).join("")}
          </div>
        </div>
      </section>

      <!-- Sector Heatmap -->
      <section class="panel" style="grid-column:1/-1">
        <div class="panel-header"><div><h2>🗺️ 섹터 히트맵</h2><p>전일 대비 섹터 ETF 등락률</p></div></div>
        <div class="panel-body">
          <div class="sector-heatmap">${sectorHeatmap}</div>
          ${renderSourceCaption("Yahoo Finance sector ETF daily change")}
        </div>
      </section>
    </div>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2: 기본 분석
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisBasic(container, ticker, macro, period) {
  const data = state.analysis || {};
  const stock = data.stock || {};
  const macroData = data.macro || {};
  const news = data.news || [];
  const toss = data.toss || {};
  const tvDetails = data.tradingview_details || {};
  const tvNews = data.tradingview_news || {};

  const macroLabel = MACRO_OPTIONS.find(m => m.id === macro)?.label || macro;

  const controlPanel = `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>조회 설정</h2></div></div>
      <div class="panel-body">
        <div class="analysis-controls">
          <div class="analysis-control-group">
            <label>종목 (Ticker)</label>
            <select id="analysis-ticker" class="analysis-select">
              ${TICKER_OPTIONS.map(t => `<option value="${t}" ${t===ticker?"selected":""}>${t}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group">
            <label>경제 지표 (FRED)</label>
            <select id="analysis-macro" class="analysis-select">
              ${MACRO_OPTIONS.map(s => `<option value="${s.id}" ${s.id===macro?"selected":""}>${s.label}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group">
            <label>기간</label>
            <select id="analysis-period" class="analysis-select">
              ${PERIOD_OPTIONS.map(p => `<option value="${p.id}" ${p.id===period?"selected":""}>${p.label}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group" style="align-self:flex-end">
            <button id="btn-analysis-fetch" class="button button-primary" type="button" style="height:38px">📊 조회</button>
          </div>
        </div>
      </div>
      ${renderSourceCaption("Yahoo Finance OHLCV/news · FRED series · TradingView right-details · TradingView news-mediator · Toss holdings")}
    </section>`;

  if (!data.stock) {
    container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance OHLCV/news", "FRED series", "TradingView right-details", "TradingView news-mediator", "Toss holdings"]) + `<div class="analysis-loading">종목, 지표, 기간을 선택 후 조회 버튼을 누르세요.</div>`;
    return;
  }

  const sentimentBadge = (s) => {
    if (s === "Positive") return `<span class="analysis-badge-pos">▲ 긍정</span>`;
    if (s === "Negative") return `<span class="analysis-badge-neg">▼ 부정</span>`;
    return `<span class="analysis-badge-neu">— 중립</span>`;
  };

  const newsHtml = news.length ? news.slice(0, 10).map(n => `
    <article class="analysis-news-item">
      <div class="analysis-news-meta">
        ${sentimentBadge(n.sentiment)}
        <span class="analysis-news-source">${escapeHtml(n.source||"-")}</span>
        <span class="analysis-news-date">${n.published_at?n.published_at.slice(0,10):"-"}</span>
      </div>
      <a class="analysis-news-title" href="${escapeHtml(n.url||"#")}" target="_blank" rel="noopener">${escapeHtml(n.headline||"제목 없음")}</a>
    </article>`).join("") : `<p style="color:var(--muted);padding:10px 0">Finnhub 또는 Alpha Vantage API 키가 설정되어 있지 않습니다.</p>`;

  const chartHtml = _renderDualAxisChart(stock.history || [], macroData.history || []);
  const tradingViewDetailsHtml = _renderTradingViewDetailsPanel(tvDetails);
  const tradingViewNewsHtml = _renderTradingViewNewsFlow(tvNews);

  let tossHtml = "";
  if (toss.positions?.length) {
    tossHtml = `<section class="panel" style="margin-top:14px">
      <div class="panel-header"><div><h2>📂 Toss 보유 종목</h2><p>${escapeHtml(toss.account_no||"")}</p></div></div>
      <div class="panel-body" style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead><tr style="border-bottom:2px solid var(--border)">
            <th style="text-align:left;padding:7px 10px">종목</th><th style="text-align:right;padding:7px 10px">수량</th>
            <th style="text-align:right;padding:7px 10px">매수가</th><th style="text-align:right;padding:7px 10px">현재가</th>
            <th style="text-align:right;padding:7px 10px">손익</th><th style="text-align:right;padding:7px 10px">수익률</th>
          </tr></thead>
          <tbody>${toss.positions.map(pos => {
            const plr = parseFloat(pos.profit_loss_rate||0);
            const c = plr>=0?"color:var(--success)":"color:var(--failed)";
            return `<tr style="border-bottom:1px solid var(--border)">
              <td style="padding:6px 10px;font-weight:600">${escapeHtml(pos.symbol||"-")}</td>
              <td style="text-align:right;padding:6px 10px">${pos.qty??"-"}</td>
              <td style="text-align:right;padding:6px 10px">${_$(pos.buy_price)}</td>
              <td style="text-align:right;padding:6px 10px">${_$(pos.current_price)}</td>
              <td style="text-align:right;padding:6px 10px;${c}">${_num(pos.profit_loss)}</td>
              <td style="text-align:right;padding:6px 10px;font-weight:600;${c}">${_pct(plr)}</td>
            </tr>`;
          }).join("")}</tbody>
        </table>
        ${renderSourceCaption("Toss Open API holdings GET")}
      </div>
    </section>`;
  }

  container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance OHLCV/news", "FRED series", "TradingView right-details", "TradingView news-mediator", "Toss holdings"]) + `
    <section class="metric-grid" style="margin-bottom:14px">
      <div class="metric-card">
        <span class="metric-label">현재가</span>
        <span class="metric-value" style="font-size:22px">${_$(stock.latest_price)}</span>
        <span class="metric-sub">${escapeHtml(stock.ticker||ticker)}</span>
        ${renderSourceLabel("Yahoo Finance OHLCV")}
      </div>
      <div class="metric-card">
        <span class="metric-label">전일 대비</span>
        <span class="metric-value ${_chgCls(stock.change_pct)}" style="font-size:22px">${_pct(stock.change_pct)}</span>
        <span class="metric-sub">일간 수익률</span>
        ${renderSourceLabel("Yahoo Finance OHLCV")}
      </div>
      <div class="metric-card">
        <span class="metric-label">기간 최고가</span>
        <span class="metric-value">${_$(stock.fifty_two_week_high)}</span>
        <span class="metric-sub">구간 내 최고</span>
        ${renderSourceLabel("Yahoo Finance OHLCV")}
      </div>
      <div class="metric-card">
        <span class="metric-label">기간 최저가</span>
        <span class="metric-value">${_$(stock.fifty_two_week_low)}</span>
        <span class="metric-sub">구간 내 최저</span>
        ${renderSourceLabel("Yahoo Finance OHLCV")}
      </div>
      ${!macroData.error ? `
      <div class="metric-card">
        <span class="metric-label">${escapeHtml((macroData.name||macro).slice(0,32))}</span>
        <span class="metric-value">${_num(macroData.latest_value,2)}</span>
        <span class="metric-sub">${escapeHtml(macroData.latest_date||"-")}</span>
        ${renderSourceLabel("FRED series")}
      </div>
      <div class="metric-card">
        <span class="metric-label">지표 변화</span>
        <span class="metric-value ${_chgCls(macroData.change)}">${macroData.change!=null?(macroData.change>=0?"+":"")+_num(macroData.change,3):"-"}</span>
        <span class="metric-sub">전기 대비</span>
        ${renderSourceLabel("FRED series")}
      </div>` : ""}
    </section>
    ${tradingViewDetailsHtml}
    ${tradingViewNewsHtml}
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>가격 & ${macroLabel} 차트</h2></div></div>
      <div class="panel-body" style="padding:0 4px">${chartHtml}${renderSourceCaption("Yahoo Finance OHLCV · FRED series")}</div>
    </section>
    ${tossHtml}
    <section class="panel" style="margin-top:14px">
      <div class="panel-header"><div><h2>📰 뉴스 & 감성 분석</h2></div></div>
      <div class="panel-body"><div class="analysis-news-list">${newsHtml}</div>${renderSourceCaption("Finnhub / Alpha Vantage news providers")}</div>
    </section>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3: 기술적 지표
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisTechnical(container, ticker, period) {
  const data = state.analysisTechnical || {};

  const controlPanel = `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>기술적 지표 설정</h2></div></div>
      <div class="panel-body">
        <div class="analysis-controls">
          <div class="analysis-control-group">
            <label>종목</label>
            <select id="tech-ticker" class="analysis-select">
              ${TICKER_OPTIONS.map(t => `<option value="${t}" ${t===ticker?"selected":""}>${t}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group">
            <label>기간</label>
            <select id="tech-period" class="analysis-select">
              ${PERIOD_OPTIONS.map(p => `<option value="${p.id}" ${p.id===period?"selected":""}>${p.label}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group" style="align-self:flex-end">
            <button id="btn-tech-fetch" class="button button-primary" style="height:38px">📊 조회</button>
          </div>
        </div>
      </div>
      ${renderSourceCaption("Yahoo Finance OHLCV · TradingView scanner popup-technicals · TradingView right-details · TradingView news-mediator")}
    </section>`;

  if (!data.records) {
    container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance OHLCV", "TradingView scanner popup-technicals", "TradingView right-details", "TradingView news-mediator"]) + `<div class="analysis-loading">종목을 선택하고 조회 버튼을 누르세요.</div>`;
    return;
  }

  const recs = data.records || [];
  const regime = data.latest_regime || "unknown";
  const regimeColor = regime === "bull" ? "#22c55e" : regime === "bear" ? "#ef4444" : "#eab308";
  const regimeLabel = regime === "bull" ? "🐂 강세장 (Bull)" : regime === "bear" ? "🐻 약세장 (Bear)" : "↔️ 횡보장 (Sideways)";

  // Summary cards
  const rsi = data.latest_rsi;
  const rsiColor = rsi == null ? "" : rsi > 70 ? "#ef4444" : rsi < 30 ? "#22c55e" : "#3b82f6";
  const rsiLabel = rsi == null ? "-" : rsi > 70 ? "과매수" : rsi < 30 ? "과매도" : "중립";
  const tv = data.tradingview || {};
  const tvConsensus = tv.consensus || {};
  const tvScore = (score) => score == null ? "-" : Number(score).toFixed(2);
  const tvSignalLabel = (row) => escapeHtml(row?.recommendation?.label || "데이터 없음");
  const tvRows = Array.isArray(tv.timeframes) ? tv.timeframes : [];
  const tradingViewDetailsHtml = _renderTradingViewDetailsPanel(data.tradingview_details || {}, { compact: true });
  const tradingViewNewsHtml = _renderTradingViewNewsFlow(data.tradingview_news || {}, { compact: true });
  const tvErrors = Array.isArray(tv.errors) ? tv.errors : [];
  const tvDetail = tvRows.find(row => row.timeframe === "1") || tvRows[tvRows.length - 1] || {};
  const tvOsc = tvDetail.oscillators || {};
  const tvMas = tvDetail.moving_averages || {};
  const tvNearest = tvDetail.nearest_pivots || {};
  const pivotLabel = (level) => level ? `${escapeHtml(level.family || "-")} ${escapeHtml(String(level.level || "").toUpperCase())} ${_$(level.value)} (${_pct(level.distance_pct)})` : "-";
  const rationaleHtml = Array.isArray(tvDetail.rationale) && tvDetail.rationale.length
    ? tvDetail.rationale.map(note => `<span class="status-badge status-${_statusForAction(note.tone)}" style="margin:0 6px 6px 0">${escapeHtml(note.text || "")}</span>`).join("")
    : `<span style="color:var(--muted)">세부 근거 없음</span>`;
  const tvDetailHtml = tvDetail.timeframe ? `
    <section style="margin-top:14px;border-top:1px solid var(--border);padding-top:12px">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
        <h3 style="margin:0;font-size:15px">초단기 상세 진단 · ${escapeHtml(tvDetail.label || tvDetail.timeframe)}</h3>
        <span class="status-badge status-${_statusForAction(tvDetail?.recommendation?.action)}">${escapeHtml(tvDetail?.recommendation?.label || "-")}</span>
      </div>
      <div class="metric-grid" style="margin-bottom:10px">
        <div class="metric-card">
          <span class="metric-label">RSI / Stoch</span>
          <span class="metric-value" style="font-size:15px">${_num(tvOsc.rsi)} / ${_num(tvOsc.stoch_k)}</span>
          <span class="metric-sub" style="font-size:11px;color:var(--muted)">D ${_num(tvOsc.stoch_d)} · Stoch RSI ${_num(tvOsc.stoch_rsi_k)}</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
        <div class="metric-card">
          <span class="metric-label">ADX 방향성</span>
          <span class="metric-value" style="font-size:15px">${_num(tvOsc.adx)}</span>
          <span class="metric-sub" style="font-size:11px;color:var(--muted)">+DI ${_num(tvOsc.adx_plus_di)} / -DI ${_num(tvOsc.adx_minus_di)}</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
        <div class="metric-card">
          <span class="metric-label">MACD / Momentum</span>
          <span class="metric-value" style="font-size:15px">${_score(tvOsc.macd)} / ${_score(tvOsc.macd_signal)}</span>
          <span class="metric-sub" style="font-size:11px;color:var(--muted)">Mom ${_score(tvOsc.mom)} · AO ${_score(tvOsc.ao)}</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
        <div class="metric-card">
          <span class="metric-label">이평선 위치</span>
          <span class="metric-value" style="font-size:15px">${_$(tvDetail.close)}</span>
          <span class="metric-sub" style="font-size:11px;color:var(--muted)">EMA20 ${_$(tvMas.ema20)} · EMA200 ${_$(tvMas.ema200)}</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
        <div class="metric-card">
          <span class="metric-label">근접 지지</span>
          <span class="metric-value" style="font-size:13px">${pivotLabel(tvNearest.support)}</span>
          <span class="metric-sub" style="font-size:11px;color:var(--muted)">월간 피벗 기준</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
        <div class="metric-card">
          <span class="metric-label">근접 저항</span>
          <span class="metric-value" style="font-size:13px">${pivotLabel(tvNearest.resistance)}</span>
          <span class="metric-sub" style="font-size:11px;color:var(--muted)">월간 피벗 기준</span>
          ${renderSourceLabel("TradingView scanner popup-technicals")}
        </div>
      </div>
      <div>${rationaleHtml}${renderSourceCaption("TradingView scanner popup-technicals · derived rationale")}</div>
    </section>` : "";
  const tradingViewHtml = (tv.status === "ok" || tv.status === "partial") && tvRows.length ? `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div>
          <h2>TradingView 기술적 매매 신호</h2>
          <p>${escapeHtml(tv.symbol || data.ticker || ticker)} scanner consensus${tv.status === "partial" ? " · 일부 시간대 실패" : ""}</p>
        </div>
        <span class="status-badge status-${_statusForAction(tvConsensus.action)}">${escapeHtml(tvConsensus.label || "-")}</span>
      </div>
      <div class="panel-body">
        <div class="metric-grid" style="margin-bottom:12px">
          <div class="metric-card">
            <span class="metric-label">최종 액션</span>
            <span class="metric-value" style="font-size:22px;color:${_signalToneColor(tvConsensus.tone)}">${escapeHtml(tvConsensus.label || "-")}</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">평균 점수 ${tvScore(tv.consensus_score)}</span>
            ${renderSourceLabel("TradingView scanner popup-technicals")}
          </div>
          <div class="metric-card">
            <span class="metric-label">신뢰도</span>
            <span class="metric-value">${Math.round((tv.confidence || 0) * 100)}%</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">점수 절대값 기반</span>
            ${renderSourceLabel("TradingView scanner popup-technicals")}
          </div>
          <div class="metric-card">
            <span class="metric-label">강한 신호</span>
            <span class="metric-value">${tv.strong_signal_count || 0}</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">강한 매수/매도 시간대</span>
            ${renderSourceLabel("TradingView scanner popup-technicals")}
          </div>
        </div>
        <div style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="border-bottom:2px solid var(--border)">
                <th style="text-align:left;padding:7px 10px">시간대</th>
                <th style="text-align:left;padding:7px 10px">신호</th>
                <th style="text-align:right;padding:7px 10px">종합</th>
                <th style="text-align:right;padding:7px 10px">MA</th>
                <th style="text-align:right;padding:7px 10px">Osc</th>
                <th style="text-align:right;padding:7px 10px">${renderTooltip("RSI")}</th>
                <th style="text-align:right;padding:7px 10px">${renderTooltip("MACD")}</th>
                <th style="text-align:right;padding:7px 10px">Close</th>
              </tr>
            </thead>
            <tbody>
              ${tvRows.map(row => `
                <tr style="border-bottom:1px solid var(--border)">
                  <td style="padding:7px 10px;font-weight:700">${escapeHtml(row.label || row.timeframe || "-")}</td>
                  <td style="padding:7px 10px;color:${_signalToneColor(row?.recommendation?.tone)};font-weight:700">${tvSignalLabel(row)}</td>
                  <td style="text-align:right;padding:7px 10px">${tvScore(row.recommend_all)}</td>
                  <td style="text-align:right;padding:7px 10px">${tvScore(row.recommend_ma)}</td>
                  <td style="text-align:right;padding:7px 10px">${tvScore(row.recommend_other)}</td>
                  <td style="text-align:right;padding:7px 10px">${_num(row.rsi)}</td>
                  <td style="text-align:right;padding:7px 10px">${tvScore(row.macd)}</td>
                  <td style="text-align:right;padding:7px 10px">${_$(row.close)}</td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>
        ${renderSourceCaption("TradingView scanner popup-technicals by timeframe")}
        ${tvErrors.length ? `<p style="margin:10px 0 0;color:var(--muted);font-size:12px">일부 시간대 실패: ${tvErrors.map(err => escapeHtml(err.label || err.timeframe || "-")).join(", ")}</p>` : ""}
        ${tvDetailHtml}
      </div>
    </section>` : `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>TradingView 기술적 매매 신호</h2><p>${escapeHtml(tv.error || "scanner 데이터를 불러오지 못했습니다.")}</p></div></div>
    </section>`;

  // Generate charts
  const dates = recs.map(r => r.date);
  const chartHtml = _renderTechnicalCharts(recs, dates);

  container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance OHLCV", "TradingView scanner popup-technicals", "TradingView right-details", "TradingView news-mediator"]) + `
    <section class="metric-grid" style="margin-bottom:14px">
      <div class="metric-card">
        <span class="metric-label">현재가</span>
        <span class="metric-value" style="font-size:22px">${_$(data.latest_price)}</span>
        <span class="metric-sub ${_chgCls(data.change_pct)}">${_pct(data.change_pct)} 전일 대비</span>
        ${renderSourceLabel("Yahoo Finance OHLCV")}
      </div>
      <div class="metric-card">
        <span class="metric-label">시장 레짐</span>
        <span class="metric-value" style="font-size:16px;color:${regimeColor}">${regimeLabel}</span>
        <span class="metric-sub" style="font-size:11px;color:var(--muted)">EMA200 기준</span>
        ${renderSourceLabel("Yahoo Finance OHLCV · derived EMA200")}
      </div>
      <div class="metric-card">
        <span class="metric-label">RSI(14)</span>
        <span class="metric-value" style="color:${rsiColor}">${_num(rsi)}</span>
        <span class="metric-sub" style="color:${rsiColor};font-size:11px">${rsiLabel}</span>
        ${renderSourceLabel("Yahoo Finance OHLCV · derived RSI")}
      </div>
      <div class="metric-card">
        <span class="metric-label">EMA 20 / 50 / 200</span>
        <span class="metric-value" style="font-size:13px">${_$(data.latest_ema20,2)} / ${_$(data.latest_ema50,2)}</span>
        <span class="metric-sub" style="font-size:11px;color:var(--muted)">EMA200 = ${_$(data.latest_ema200,2)}</span>
        ${renderSourceLabel("Yahoo Finance OHLCV · derived EMA")}
      </div>
      <div class="metric-card">
        <span class="metric-label">ATR(14) 일간 변동성</span>
        <span class="metric-value">${_$(data.latest_atr)}</span>
        <span class="metric-sub" style="font-size:11px;color:var(--muted)">±${data.latest_atr && data.latest_price ? _num(data.latest_atr/data.latest_price*100)+"%" : "-"}</span>
        ${renderSourceLabel("Yahoo Finance OHLCV · derived ATR")}
      </div>
    </section>
    ${tradingViewHtml}
    ${tradingViewNewsHtml}
    ${tradingViewDetailsHtml}
    <section class="panel">
      <div class="panel-header"><div><h2>기술적 지표 차트</h2><p>가격·볼린저·EMA / MACD / RSI / 거래량</p></div></div>
      <div class="panel-body" style="padding:0 4px">${chartHtml}${renderSourceCaption("Yahoo Finance OHLCV · derived Bollinger/EMA/MACD/RSI/volume")}</div>
    </section>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4: 멀티 비교
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisCompare(container, period) {
  const data = state.analysisCompare || {};
  const COMPARE_COLORS = ["#6366f1","#f59e0b","#22c55e","#ef4444","#06b6d4","#d946ef"];

  const defaultTickers = "SOXL,TQQQ,NVDA,QQQ,SPY";

  const controlPanel = `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>멀티 종목 비교</h2><p>최대 6개 종목의 정규화 수익률 (시작=100)</p></div></div>
      <div class="panel-body">
        <div class="analysis-controls">
          <div class="analysis-control-group" style="flex:3;min-width:220px">
            <label>종목 (쉼표로 구분, 최대 6개)</label>
            <input id="compare-tickers" class="analysis-select" type="text" value="${escapeHtml(data.tickers?.join(",")||defaultTickers)}" placeholder="SOXL,TQQQ,NVDA,QQQ,SPY"/>
          </div>
          <div class="analysis-control-group">
            <label>기간</label>
            <select id="compare-period" class="analysis-select">
              ${PERIOD_OPTIONS.map(p => `<option value="${p.id}" ${p.id===period?"selected":""}>${p.label}</option>`).join("")}
            </select>
          </div>
          <div class="analysis-control-group" style="align-self:flex-end">
            <button id="btn-compare-fetch" class="button button-primary" style="height:38px">📊 비교</button>
          </div>
        </div>
      </div>
      ${renderSourceCaption("Yahoo Finance adjusted close series")}
    </section>`;

  if (!data.dates) {
    container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance adjusted close series"]) + `<div class="analysis-loading">종목과 기간을 설정하고 비교 버튼을 누르세요.</div>`;
    return;
  }

  const dates = data.dates || [];
  const tickers = data.tickers || [];
  const series = data.series || {};
  const summary = data.summary || [];

  // Multi-line chart
  const W = 900, H = 260, PL = 55, PR = 20, PT = 20, PB = 38;
  const innerW = W - PL - PR, innerH = H - PT - PB;
  const allVals = tickers.flatMap(t => (series[t]||[]).filter(v=>v!=null));
  const sc = _svgScale(allVals, innerH, 0.05);

  const dateToX = (i) => PL + (i / Math.max(dates.length - 1, 1)) * innerW;
  const valToY = (v) => PT + sc.toY(v);

  const lines = tickers.map((t, ti) => {
    const pts = (series[t]||[]).map((v,i) => v!=null ? `${dateToX(i).toFixed(1)},${valToY(v).toFixed(1)}` : null).filter(Boolean);
    return _svgLine(pts, COMPARE_COLORS[ti % COMPARE_COLORS.length], 2);
  });

  // Baseline 100 line
  const baseY = valToY(100);

  // X-axis labels
  let xLabels = "";
  const step = Math.max(1, Math.floor(dates.length / 5));
  for (let i = 0; i < dates.length; i += step) {
    xLabels += `<text x="${dateToX(i).toFixed(1)}" y="${PT+innerH+14}" font-size="10" fill="#94a3b8" text-anchor="middle">${dates[i].slice(0,7)}</text>`;
  }

  // Y-axis labels
  let yLabels = "";
  for (let i = 0; i <= 4; i++) {
    const v = sc.min + (i / 4) * (sc.max - sc.min);
    const y = PT + sc.toY(v);
    yLabels += `<text x="${PL-5}" y="${y.toFixed(1)}" font-size="10" fill="#94a3b8" text-anchor="end" dominant-baseline="middle">${v.toFixed(0)}</text>`;
  }

  // Legend
  const legend = tickers.map((t, ti) => `
    <span style="display:inline-flex;align-items:center;gap:5px;margin-right:14px;font-size:12px;font-weight:600;color:${COMPARE_COLORS[ti]}">
      <span style="width:18px;height:2px;display:inline-block;background:${COMPARE_COLORS[ti]};border-radius:1px"></span>${t}
    </span>`).join("");

  container.innerHTML = controlPanel + renderDataSourceNote("analysis", ["Yahoo Finance adjusted close series"]) + `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>정규화 수익률 차트 (시작 = 100)</h2></div></div>
      <div class="panel-body" style="padding:4px">
        <div style="margin-bottom:8px">${legend}</div>
        <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-height:280px;display:block">
          <rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}" fill="#fafbfc" rx="4"/>
          <line x1="${PL}" y1="${baseY.toFixed(1)}" x2="${PL+innerW}" y2="${baseY.toFixed(1)}" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="4,3"/>
          ${[0,1,2,3,4].map(i => {
            const v = sc.min + (i/4)*(sc.max-sc.min);
            const y = PT + sc.toY(v);
            return `<line x1="${PL}" y1="${y.toFixed(1)}" x2="${PL+innerW}" y2="${y.toFixed(1)}" stroke="#e2e8f0" stroke-width="0.7"/>`;
          }).join("")}
          <clipPath id="compareClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}"/></clipPath>
          <g clip-path="url(#compareClip)">${lines.join("")}</g>
          <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
          <line x1="${PL}" y1="${PT+innerH}" x2="${PL+innerW}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
          ${yLabels}${xLabels}
        </svg>
        ${renderSourceCaption("Yahoo Finance adjusted close series")}
      </div>
    </section>
    <section class="panel">
      <div class="panel-header"><div><h2>기간 수익률 순위</h2></div></div>
      <div class="panel-body" style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <thead><tr style="border-bottom:2px solid var(--border)">
            <th style="text-align:left;padding:8px 10px">순위</th>
            <th style="text-align:left;padding:8px 10px">종목</th>
            <th style="text-align:right;padding:8px 10px">정규화 현재값</th>
            <th style="text-align:right;padding:8px 10px">기간 수익률</th>
            <th style="padding:8px 10px;min-width:120px">게이지</th>
          </tr></thead>
          <tbody>
            ${summary.map((s, i) => {
              const ret = s.total_return_pct;
              const pct100 = Math.max(Math.min(Math.abs(ret||0)/50*100, 100), 0);
              const barColor = ret >= 0 ? "#22c55e" : "#ef4444";
              const color = COMPARE_COLORS[tickers.indexOf(s.ticker) % COMPARE_COLORS.length];
              return `<tr style="border-bottom:1px solid var(--border)">
                <td style="padding:7px 10px;color:var(--muted)">#${i+1}</td>
                <td style="padding:7px 10px;font-weight:700;color:${color}">${escapeHtml(s.ticker)}</td>
                <td style="text-align:right;padding:7px 10px">${_num(s.latest_norm,2)}</td>
                <td style="text-align:right;padding:7px 10px;font-weight:700;${ret>=0?"color:#15803d":"color:#b91c1c"}">${_pct(ret)}</td>
                <td style="padding:7px 10px">
                  <div style="background:#e2e8f0;border-radius:4px;height:8px;overflow:hidden">
                    <div style="height:100%;width:${pct100}%;background:${barColor};border-radius:4px;transition:width 0.5s"></div>
                  </div>
                </td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
        ${renderSourceCaption("Yahoo Finance adjusted close series · normalized return calculation")}
      </div>
    </section>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 5: 포트폴리오 성과
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisPortfolio(container) {
  const data = state.analysisPortfolio || {};
  const agg = data.aggregate || {};
  const runs = data.runs || [];
  const curve = data.equity_curve || [];
  const diagnostics = data.diagnostics || {};
  const skippedRuns = diagnostics.skipped_runs || [];
  const statusCounts = diagnostics.status_counts || {};

  const loadBtn = `<div style="display:flex;justify-content:flex-end;margin-bottom:10px">
    <button id="btn-portfolio-fetch" class="button button-primary" type="button">📊 실행 데이터 조회</button>
  </div>`;
  const portfolioSourceNote = renderDataSourceNote("analysis", ["runs/*/manifest.json", "trades.json", "equity curve artifacts"]);

  if (!data.aggregate) {
    container.innerHTML = loadBtn + portfolioSourceNote + `<div class="analysis-loading">전략 실행 성과 데이터를 불러옵니다.</div>`;
    return;
  }
  const emptyPortfolioHtml = !runs.length ? `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header">
        <div>
          <h2>성과 산출 가능한 실행 없음</h2>
          <p>${escapeHtml(diagnostics.empty_reason || "최근 실행에서 매매 결과를 찾지 못했습니다.")}</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="metric-grid" style="margin-bottom:12px">
          <div class="metric-card">
            <span class="metric-label">검사한 실행</span>
            <span class="metric-value">${diagnostics.checked_run_count ?? 0}</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">최근 실행 기준</span>
            ${renderSourceLabel("runs/*/manifest.json")}
          </div>
          <div class="metric-card">
            <span class="metric-label">성과 가능 실행</span>
            <span class="metric-value">${diagnostics.performance_run_count ?? 0}</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">trades.json 포함</span>
            ${renderSourceLabel("trades.json discovery")}
          </div>
          <div class="metric-card">
            <span class="metric-label">실패 실행</span>
            <span class="metric-value">${statusCounts.failed ?? 0}</span>
            <span class="metric-sub" style="font-size:11px;color:var(--muted)">최근 검사 범위</span>
            ${renderSourceLabel("runs/*/manifest.json status")}
          </div>
        </div>
        <p style="margin:0 0 10px;color:var(--muted);font-size:13px">
          현재 최근 실행은 매매 로그가 생성되기 전에 중단되었습니다. 실패 코드를 먼저 해결한 뒤 simulate를 다시 실행하면 Sharpe, Sortino, MDD가 채워집니다.
        </p>
        ${skippedRuns.length ? `
        <div style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:12px">
            <thead><tr style="border-bottom:2px solid var(--border)">
              <th style="text-align:left;padding:6px 8px">실행 ID</th>
              <th style="text-align:left;padding:6px 8px">상태</th>
              <th style="text-align:left;padding:6px 8px">실패 코드</th>
              <th style="text-align:left;padding:6px 8px">건너뛴 이유</th>
            </tr></thead>
            <tbody>
              ${skippedRuns.map(r => `<tr style="border-bottom:1px solid var(--border)">
                <td style="padding:5px 8px;font-family:monospace;font-size:11px">${escapeHtml(String(r.run_id || "").slice(-24))}</td>
                <td style="padding:5px 8px">${statusBadge(r.status || "unknown")}</td>
                <td style="padding:5px 8px;font-family:monospace;font-size:11px">${escapeHtml(r.failure_code || "-")}</td>
                <td style="padding:5px 8px;color:var(--muted)">${escapeHtml(r.error || r.reason || "-")}</td>
              </tr>`).join("")}
            </tbody>
          </table>
        </div>` : ""}
      </div>
    </section>` : "";

  // Equity curve chart
  let eqChart = "<p style='color:var(--muted);font-size:13px'>에쿼티 커브 데이터 없음</p>";
  if (curve.length > 1) {
    const W = 900, H = 180, PL = 70, PR = 20, PT = 10, PB = 30;
    const innerW = W - PL - PR, innerH = H - PT - PB;
    const eqVals = curve.map(r => r.equity).filter(v => v!=null);
    const sc = _svgScale(eqVals, innerH, 0.05);
    const pts = curve.map((r,i) =>
      r.equity != null ? `${(PL + i/(curve.length-1)*innerW).toFixed(1)},${(PT+sc.toY(r.equity)).toFixed(1)}` : null
    ).filter(Boolean);
    const areaPts = [...pts, `${PL+innerW},${PT+innerH}`, `${PL},${PT+innerH}`].join(" ");
    const step = Math.max(1, Math.floor(curve.length / 5));
    let xL = "", yL = "";
    for (let i = 0; i < curve.length; i += step) {
      const x = PL + i/(curve.length-1)*innerW;
      const d = curve[i].date?.slice(0,10)||"";
      xL += `<text x="${x.toFixed(1)}" y="${PT+innerH+14}" font-size="10" fill="#94a3b8" text-anchor="middle">${d.slice(0,7)}</text>`;
    }
    for (let i = 0; i <= 4; i++) {
      const v = sc.min + (i/4)*(sc.max-sc.min);
      const y = PT + sc.toY(v);
      yL += `<text x="${PL-5}" y="${y.toFixed(1)}" font-size="10" fill="#94a3b8" text-anchor="end" dominant-baseline="middle">$${(v/1000).toFixed(0)}K</text>`;
    }
    eqChart = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-height:200px;display:block">
      <defs>
        <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#6366f1" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="#6366f1" stop-opacity="0"/>
        </linearGradient>
        <clipPath id="eqClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}"/></clipPath>
      </defs>
      <rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}" fill="#fafbfc" rx="4"/>
      <g clip-path="url(#eqClip)">
        <polygon fill="url(#eqGrad)" points="${areaPts}"/>
        ${_svgLine(pts, "#6366f1", 2)}
      </g>
      <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
      <line x1="${PL}" y1="${PT+innerH}" x2="${PL+innerW}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
      ${yL}${xL}
    </svg>`;
  }

  container.innerHTML = loadBtn + portfolioSourceNote + `
    <section class="metric-grid" style="margin-bottom:14px">
      <div class="metric-card">
        <span class="metric-label">분석 실행 수</span>
        <span class="metric-value" style="font-size:24px">${agg.run_count??"-"}</span>
        <span class="metric-sub" style="font-size:11px;color:var(--muted)">최근 10개 기준</span>
        ${renderSourceLabel("runs/*/manifest.json · trades.json")}
      </div>
      <div class="metric-card">
        <span class="metric-label">평균 Sharpe 비율</span>
        <span class="metric-value ${_chgCls(agg.avg_sharpe)}">${_num(agg.avg_sharpe)}</span>
        <span class="metric-sub" style="font-size:11px;color:var(--muted)">연환산 일간</span>
        ${renderSourceLabel("trades.json · equity curve artifacts")}
      </div>
      <div class="metric-card">
        <span class="metric-label">평균 Sortino 비율</span>
        <span class="metric-value ${_chgCls(agg.avg_sortino)}">${_num(agg.avg_sortino)}</span>
        <span class="metric-sub" style="font-size:11px;color:var(--muted)">하방 표준편차 기준</span>
        ${renderSourceLabel("trades.json · equity curve artifacts")}
      </div>
      <div class="metric-card">
        <span class="metric-label">평균 승률</span>
        <span class="metric-value">${_num(agg.avg_win_rate)}%</span>
        <span class="metric-sub" style="font-size:11px;color:var(--muted)">전체 매매 기준</span>
        ${renderSourceLabel("trades.json")}
      </div>
      <div class="metric-card">
        <span class="metric-label">평균 MDD</span>
        <span class="metric-value analysis-negative">-${_num(agg.avg_max_drawdown)}%</span>
        <span class="metric-sub" style="font-size:11px;color:var(--muted)">최대 낙폭</span>
        ${renderSourceLabel("equity curve artifacts")}
      </div>
      <div class="metric-card">
        <span class="metric-label">평균 수익률</span>
        <span class="metric-value ${_chgCls(agg.avg_total_return)}">${_pct(agg.avg_total_return)}</span>
        <span class="metric-sub" style="font-size:11px;color:var(--muted)">누적 기준</span>
        ${renderSourceLabel("trades.json · final capital")}
      </div>
    </section>
    ${emptyPortfolioHtml}
    ${curve.length > 1 ? `
    <section class="panel" style="margin-bottom:14px">
      <div class="panel-header"><div><h2>에쿼티 커브</h2><p>최근 실행 자본금 추이</p></div></div>
      <div class="panel-body" style="padding:0 4px">${eqChart}${renderSourceCaption("equity curve artifacts from completed runs")}</div>
    </section>` : ""}
    <section class="panel">
      <div class="panel-header"><div><h2>실행 이력</h2></div></div>
      <div class="panel-body" style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:12px">
          <thead><tr style="border-bottom:2px solid var(--border)">
            <th style="text-align:left;padding:6px 8px">실행 ID</th>
            <th style="text-align:right;padding:6px 8px">매매수</th>
            <th style="text-align:right;padding:6px 8px">Sharpe</th>
            <th style="text-align:right;padding:6px 8px">Sortino</th>
            <th style="text-align:right;padding:6px 8px">승률</th>
            <th style="text-align:right;padding:6px 8px">MDD</th>
            <th style="text-align:right;padding:6px 8px">누적수익</th>
            <th style="text-align:right;padding:6px 8px">최종자본</th>
          </tr></thead>
          <tbody>
            ${runs.map(r => `<tr style="border-bottom:1px solid var(--border)">
              <td style="padding:5px 8px;font-family:monospace;font-size:11px">${escapeHtml((r.run_id||"").slice(-12))}</td>
              <td style="text-align:right;padding:5px 8px">${r.total_trades??"-"}</td>
              <td style="text-align:right;padding:5px 8px;${_chgCls(r.sharpe)?`color:${r.sharpe>0?"var(--success)":"var(--failed)"}`:"color:var(--muted)"}">${_num(r.sharpe)}</td>
              <td style="text-align:right;padding:5px 8px">${_num(r.sortino)}</td>
              <td style="text-align:right;padding:5px 8px">${_num(r.win_rate)}%</td>
              <td style="text-align:right;padding:5px 8px;color:var(--failed)">-${_num(r.max_drawdown)}%</td>
              <td style="text-align:right;padding:5px 8px;font-weight:600;${r.total_return>=0?"color:var(--success)":"color:var(--failed)"}">${_pct(r.total_return)}</td>
              <td style="text-align:right;padding:5px 8px">${_$(r.final_capital,0)}</td>
            </tr>`).join("")}
          </tbody>
        </table>
        ${renderSourceCaption("runs/*/manifest.json · trades.json")}
      </div>
    </section>`;
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 6: 경제 캘린더
// ══════════════════════════════════════════════════════════════════════════════
function renderAnalysisCalendar(container) {
  const data = state.analysisCalendar || {};
  const events = data.events || [];

  const loadBtn = `<div style="display:flex;justify-content:flex-end;margin-bottom:10px">
    <button id="btn-calendar-fetch" class="button button-primary" type="button">📅 캘린더 로드</button>
  </div>`;
  const calendarSourceNote = renderDataSourceNote("analysis", ["FRED economic series", "release cadence estimates"]);

  if (!events.length) {
    container.innerHTML = loadBtn + calendarSourceNote + `<div class="analysis-loading">FRED 경제 지표 발표 일정을 불러옵니다.</div>`;
    return;
  }

  const today = new Date().toISOString().slice(0, 10);

  const rows = events.map(ev => {
    const upcoming = ev.is_upcoming;
    const change = ev.change;
    const changeColor = change == null ? "" : change > 0 ? "color:var(--success)" : change < 0 ? "color:var(--failed)" : "color:var(--muted)";

    return `<div class="calendar-event ${upcoming ? "calendar-upcoming" : ""}">
      <div class="calendar-icon">${ev.icon}</div>
      <div class="calendar-main">
        <div class="calendar-name">${escapeHtml(ev.name)}</div>
        <div class="calendar-meta">
          <span class="calendar-freq">${ev.frequency}</span>
          <span class="calendar-series">${ev.series_id}</span>
        </div>
      </div>
      <div class="calendar-values">
        <div>최근: <strong>${ev.latest_value != null ? _num(ev.latest_value, 3) : "-"}</strong>
          ${change != null ? `<span style="${changeColor};font-size:11px;margin-left:4px">(${change >= 0 ? "+" : ""}${_num(change, 3)})</span>` : ""}
        </div>
        <div style="font-size:11px;color:var(--muted)">${ev.latest_date || "-"}</div>
      </div>
      <div class="calendar-next ${upcoming ? "is-upcoming" : ""}">
        <div style="font-size:11px;font-weight:600">${upcoming ? "⏳ 예정" : "📆 추정"}</div>
        <div style="font-size:13px;font-weight:700">${ev.next_estimated || "-"}</div>
      </div>
    </div>`;
  }).join("");

  container.innerHTML = loadBtn + calendarSourceNote + `
    <section class="panel">
      <div class="panel-header"><div><h2>📅 주요 경제 지표 발표 일정</h2><p>기준일: ${today} | FRED 최신 데이터 기반, 다음 발표일은 추정치입니다.</p></div></div>
      <div class="panel-body">
        <div class="calendar-list">${rows}</div>
        ${renderSourceCaption("FRED economic series · release cadence estimates")}
      </div>
    </section>`;
}

// ── SVG Chart Helpers ────────────────────────────────────────────────────────

function _renderDualAxisChart(stockHistory, macroHistory) {
  const W = 900, H = 260, PL = 60, PR = 65, PT = 20, PB = 40;
  const innerW = W - PL - PR, innerH = H - PT - PB;

  if (!stockHistory.length) return `<div style="height:200px;display:flex;align-items:center;justify-content:center;color:var(--muted)">데이터 없음</div>`;

  const stockDates = stockHistory.map(d => d.date);
  const allDates = [...new Set([...stockDates, ...macroHistory.map(d => d.date)])].sort();
  const xMin = allDates[0], xMax = allDates[allDates.length - 1];
  const dtX = (d) => { const t = d >= xMax ? 1 : d <= xMin ? 0 : d.localeCompare(xMin) / xMax.localeCompare(xMin); return PL + t * innerW; };

  const sVals = stockHistory.map(d => d.close).filter(v => v!=null && !isNaN(v));
  const sc = _svgScale(sVals, innerH, 0.08);
  const sToY = (v) => PT + sc.toY(v);

  const sPts = stockHistory.filter(d => d.close!=null).map(d => `${dtX(d.date).toFixed(1)},${sToY(d.close).toFixed(1)}`);
  const sAreaPts = [...sPts, `${(PL+innerW).toFixed(1)},${(PT+innerH).toFixed(1)}`, `${PL},${(PT+innerH).toFixed(1)}`].join(" ");

  let macroLine = "", macroAxis = "";
  const mVals = macroHistory.map(d => d.value).filter(v => v!=null && !isNaN(v));
  if (mVals.length > 1) {
    const msc = _svgScale(mVals, innerH, 0.08);
    const mToY = (v) => PT + msc.toY(v);
    const mPts = macroHistory.filter(d => d.value!=null && !isNaN(d.value) && d.date>=xMin && d.date<=xMax)
      .map(d => `${dtX(d.date).toFixed(1)},${mToY(d.value).toFixed(1)}`);
    if (mPts.length) macroLine = _svgLine(mPts, "#f59e0b", 2, "5,3");
    for (let i = 0; i <= 4; i++) {
      const v = msc.min + (i/4)*(msc.max-msc.min);
      macroAxis += `<text x="${W-PR+7}" y="${(PT+msc.toY(v)).toFixed(1)}" font-size="10" fill="#f59e0b" dominant-baseline="middle">${v.toFixed(2)}</text>`;
    }
    macroAxis += `<line x1="${W-PR}" y1="${PT}" x2="${W-PR}" y2="${PT+innerH}" stroke="#f59e0b" stroke-width="0.5" opacity="0.4"/>`;
  }

  let leftAxis = "";
  for (let i = 0; i <= 4; i++) {
    const v = sc.min + (i/4)*(sc.max-sc.min);
    leftAxis += `<text x="${PL-5}" y="${(PT+sc.toY(v)).toFixed(1)}" font-size="10" fill="#6366f1" text-anchor="end" dominant-baseline="middle">$${v.toFixed(0)}</text>`;
  }
  let xAxis = "";
  const xStep = Math.max(1, Math.floor(allDates.length/5));
  for (let i = 0; i < allDates.length; i += xStep) {
    const d = allDates[i];
    xAxis += `<text x="${dtX(d).toFixed(1)}" y="${PT+innerH+14}" font-size="10" fill="#94a3b8" text-anchor="middle">${d.slice(0,7)}</text>`;
  }

  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-height:280px;display:block" preserveAspectRatio="xMidYMid meet">
    <defs>
      <linearGradient id="sGrad2" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#6366f1" stop-opacity="0.25"/><stop offset="100%" stop-color="#6366f1" stop-opacity="0"/>
      </linearGradient>
      <clipPath id="dualClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}"/></clipPath>
    </defs>
    <rect x="${PL}" y="${PT}" width="${innerW}" height="${innerH}" fill="#fafbfc" rx="4"/>
    ${[0,1,2,3,4].map(i => { const v=sc.min+(i/4)*(sc.max-sc.min); const y=PT+sc.toY(v); return `<line x1="${PL}" y1="${y.toFixed(1)}" x2="${PL+innerW}" y2="${y.toFixed(1)}" stroke="#e2e8f0" stroke-width="1"/>`; }).join("")}
    <g clip-path="url(#dualClip)">
      <polygon fill="url(#sGrad2)" points="${sAreaPts}"/>
      ${_svgLine(sPts, "#6366f1", 2.2)}
      ${macroLine}
    </g>
    <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
    <line x1="${PL}" y1="${PT+innerH}" x2="${PL+innerW}" y2="${PT+innerH}" stroke="#cbd5e1" stroke-width="1"/>
    ${leftAxis}${macroAxis}${xAxis}
    <text x="${PL+8}" y="${PT+14}" font-size="11" font-weight="600" fill="#6366f1">● 주가 (좌축)</text>
    ${mVals.length>1?`<text x="${PL+110}" y="${PT+14}" font-size="11" font-weight="600" fill="#f59e0b">--- 경제 지표 (우축)</text>`:""}
  </svg>`;
}

function _renderTechnicalCharts(recs, dates) {
  if (!recs.length) return `<div style="color:var(--muted);padding:16px">데이터 없음</div>`;

  const W = 900;
  const PL = 62, PR = 10, PT = 10, PB = 24;
  const innerW = W - PL - PR;

  const dtX = (i) => PL + (i / Math.max(dates.length - 1, 1)) * innerW;

  // ── Panel 1: Price + Bollinger + EMA ─────────────────────
  const H1 = 220;
  const closes = recs.map(r => r.close);
  const bbU = recs.map(r => r.bb_upper);
  const bbL = recs.map(r => r.bb_lower);
  const ema20 = recs.map(r => r.ema20);
  const ema50 = recs.map(r => r.ema50);
  const ema200 = recs.map(r => r.ema200);

  const allP1 = [...closes, ...bbU.filter(v=>v!=null), ...bbL.filter(v=>v!=null)].filter(v=>v!=null);
  const sc1 = _svgScale(allP1, H1 - PT - PB, 0.03);
  const toY1 = (v) => PT + sc1.toY(v);

  const pricePts = closes.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);
  const bbUPts = bbU.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);
  const bbLPts = bbL.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);
  const ema20Pts = ema20.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);
  const ema50Pts = ema50.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);
  const ema200Pts = ema200.map((v,i) => v!=null?`${dtX(i).toFixed(1)},${toY1(v).toFixed(1)}`:null).filter(Boolean);

  let yL1 = "";
  for (let i = 0; i <= 4; i++) {
    const v = sc1.min + (i/4)*(sc1.max-sc1.min);
    yL1 += `<text x="${PL-5}" y="${toY1(v).toFixed(1)}" font-size="10" fill="#94a3b8" text-anchor="end" dominant-baseline="middle">$${v.toFixed(0)}</text>`;
  }

  // Regime color bars
  const regimeBars = recs.map((r,i) => {
    const col = r.regime==="bull"?"rgba(34,197,94,0.12)":r.regime==="bear"?"rgba(239,68,68,0.12)":"rgba(234,179,8,0.08)";
    const x = dtX(i), nx = dtX(i+1);
    return `<rect x="${x.toFixed(1)}" y="${PT}" width="${(nx-x).toFixed(1)}" height="${H1-PT-PB}" fill="${col}" opacity="0.7"/>`;
  }).join("");

  const chart1 = `<svg viewBox="0 0 ${W} ${H1}" style="width:100%;display:block;margin-bottom:4px">
    <defs>
      <linearGradient id="p1Grad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#6366f1" stop-opacity="0.2"/><stop offset="100%" stop-color="#6366f1" stop-opacity="0"/>
      </linearGradient>
      <clipPath id="p1Clip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${H1-PT-PB}"/></clipPath>
    </defs>
    <rect x="${PL}" y="${PT}" width="${innerW}" height="${H1-PT-PB}" fill="#fafbfc" rx="4"/>
    <g clip-path="url(#p1Clip)">
      ${regimeBars}
      ${_svgLine(bbUPts,"#94a3b8",1,"3,3")}
      ${_svgLine(bbLPts,"#94a3b8",1,"3,3")}
      ${_svgArea(pricePts,"url(#p1Grad)")}
      ${_svgLine(pricePts,"#6366f1",2)}
      ${_svgLine(ema20Pts,"#f59e0b",1.5)}
      ${_svgLine(ema50Pts,"#22c55e",1.5)}
      ${_svgLine(ema200Pts,"#ef4444",1.5,"6,3")}
    </g>
    <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${H1-PB}" stroke="#cbd5e1" stroke-width="1"/>
    <line x1="${PL}" y1="${H1-PB}" x2="${PL+innerW}" y2="${H1-PB}" stroke="#cbd5e1" stroke-width="1"/>
    ${yL1}
    <text x="${PL+6}" y="${PT+13}" font-size="10" font-weight="600" fill="#6366f1">● 가격</text>
    <text x="${PL+55}" y="${PT+13}" font-size="10" font-weight="600" fill="#f59e0b">EMA20</text>
    <text x="${PL+100}" y="${PT+13}" font-size="10" font-weight="600" fill="#22c55e">EMA50</text>
    <text x="${PL+148}" y="${PT+13}" font-size="10" font-weight="600" fill="#ef4444">EMA200</text>
    <text x="${PL+200}" y="${PT+13}" font-size="10" fill="#94a3b8">--- 볼린저 밴드</text>
  </svg>`;

  // ── Panel 2: MACD ───────────────────────────────────────
  const H2 = 100;
  const macdL = recs.map(r => r.macd_line);
  const macdS = recs.map(r => r.macd_signal);
  const macdH = recs.map(r => r.macd_hist);
  const allM = [...macdL,...macdS,...macdH].filter(v=>v!=null&&!isNaN(v));
  const sc2 = _svgScale(allM, H2 - PT - PB, 0.15);
  const toY2 = (v) => PT + sc2.toY(v);
  const zero2 = toY2(0);

  const macdLPts = macdL.map((v,i)=>v!=null?`${dtX(i).toFixed(1)},${toY2(v).toFixed(1)}`:null).filter(Boolean);
  const macdSPts = macdS.map((v,i)=>v!=null?`${dtX(i).toFixed(1)},${toY2(v).toFixed(1)}`:null).filter(Boolean);
  const macdBars = macdH.map((v,i)=>{
    if (v==null) return "";
    const x=dtX(i), bw=Math.max(innerW/dates.length-1,1), y=Math.min(toY2(v),zero2), h=Math.abs(toY2(v)-zero2);
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(h,0.5).toFixed(1)}" fill="${v>=0?"#22c55e":"#ef4444"}" opacity="0.7"/>`;
  }).join("");

  const chart2 = `<svg viewBox="0 0 ${W} ${H2}" style="width:100%;display:block;margin-bottom:4px">
    <defs><clipPath id="macdClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${H2-PT-PB}"/></clipPath></defs>
    <rect x="${PL}" y="${PT}" width="${innerW}" height="${H2-PT-PB}" fill="#fafbfc" rx="4"/>
    <line x1="${PL}" y1="${zero2.toFixed(1)}" x2="${PL+innerW}" y2="${zero2.toFixed(1)}" stroke="#cbd5e1" stroke-width="0.8" stroke-dasharray="3,2"/>
    <g clip-path="url(#macdClip)">
      ${macdBars}
      ${_svgLine(macdLPts,"#6366f1",1.5)}
      ${_svgLine(macdSPts,"#f59e0b",1.5)}
    </g>
    <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${H2-PB}" stroke="#cbd5e1" stroke-width="1"/>
    <text x="${PL+6}" y="${PT+13}" font-size="10" font-weight="600" fill="#1e293b">MACD</text>
    <text x="${PL+46}" y="${PT+13}" font-size="10" fill="#6366f1">MACD(12,26)</text>
    <text x="${PL+120}" y="${PT+13}" font-size="10" fill="#f59e0b">Signal(9)</text>
  </svg>`;

  // ── Panel 3: RSI ────────────────────────────────────────
  const H3 = 100;
  const rsi14 = recs.map(r => r.rsi14);
  const sc3 = { min: 0, max: 100, toY: (v) => (H3-PT-PB) * (1 - v/100) };
  const toY3 = (v) => PT + sc3.toY(v);
  const rsiPts = rsi14.map((v,i)=>v!=null?`${dtX(i).toFixed(1)},${toY3(v).toFixed(1)}`:null).filter(Boolean);
  const ob = toY3(70), os = toY3(30);

  const chart3 = `<svg viewBox="0 0 ${W} ${H3}" style="width:100%;display:block;margin-bottom:4px">
    <defs><clipPath id="rsiClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${H3-PT-PB}"/></clipPath></defs>
    <rect x="${PL}" y="${PT}" width="${innerW}" height="${H3-PT-PB}" fill="#fafbfc" rx="4"/>
    <rect x="${PL}" y="${ob.toFixed(1)}" width="${innerW}" height="${(os-ob).toFixed(1)}" fill="rgba(99,102,241,0.04)"/>
    <line x1="${PL}" y1="${ob.toFixed(1)}" x2="${PL+innerW}" y2="${ob.toFixed(1)}" stroke="#ef4444" stroke-width="0.8" stroke-dasharray="4,3"/>
    <line x1="${PL}" y1="${os.toFixed(1)}" x2="${PL+innerW}" y2="${os.toFixed(1)}" stroke="#22c55e" stroke-width="0.8" stroke-dasharray="4,3"/>
    <g clip-path="url(#rsiClip)">${_svgLine(rsiPts,"#6366f1",1.8)}</g>
    <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${H3-PB}" stroke="#cbd5e1" stroke-width="1"/>
    <text x="${PL+6}" y="${PT+13}" font-size="10" font-weight="600" fill="#1e293b">RSI(14)</text>
    <text x="${PL-5}" y="${ob.toFixed(1)}" font-size="9" fill="#ef4444" text-anchor="end">70</text>
    <text x="${PL-5}" y="${os.toFixed(1)}" font-size="9" fill="#22c55e" text-anchor="end">30</text>
  </svg>`;

  // ── Panel 4: Volume ─────────────────────────────────────
  const H4 = 80;
  const vols = recs.map(r => r.volume);
  const volMA = recs.map(r => r.vol_ma20);
  const maxVol = Math.max(...vols.filter(v=>v!=null));
  const toY4 = (v) => PT + (H4-PT-PB) * (1 - v/maxVol);
  const bw4 = Math.max(innerW/dates.length-0.5, 1);
  const volBars = vols.map((v,i)=>v!=null?`<rect x="${dtX(i).toFixed(1)}" y="${toY4(v).toFixed(1)}" width="${bw4.toFixed(1)}" height="${(H4-PB-toY4(v)).toFixed(1)}" fill="#6366f1" opacity="0.35"/>` : "").join("");
  const volMAPts = volMA.map((v,i)=>v!=null?`${dtX(i).toFixed(1)},${toY4(v).toFixed(1)}`:null).filter(Boolean);

  // X-axis labels (shared)
  const step = Math.max(1, Math.floor(dates.length/5));
  let xL = "";
  for (let i = 0; i < dates.length; i += step) {
    xL += `<text x="${dtX(i).toFixed(1)}" y="${H4-PB+14}" font-size="10" fill="#94a3b8" text-anchor="middle">${dates[i].slice(0,7)}</text>`;
  }

  const chart4 = `<svg viewBox="0 0 ${W} ${H4}" style="width:100%;display:block">
    <defs><clipPath id="volClip"><rect x="${PL}" y="${PT}" width="${innerW}" height="${H4-PT-PB}"/></clipPath></defs>
    <rect x="${PL}" y="${PT}" width="${innerW}" height="${H4-PT-PB}" fill="#fafbfc" rx="4"/>
    <g clip-path="url(#volClip)">
      ${volBars}
      ${_svgLine(volMAPts,"#f59e0b",1.5)}
    </g>
    <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${H4-PB}" stroke="#cbd5e1" stroke-width="1"/>
    <line x1="${PL}" y1="${H4-PB}" x2="${PL+innerW}" y2="${H4-PB}" stroke="#cbd5e1" stroke-width="1"/>
    <text x="${PL+6}" y="${PT+13}" font-size="10" font-weight="600" fill="#1e293b">Volume</text>
    <text x="${PL+60}" y="${PT+13}" font-size="10" fill="#f59e0b">MA20</text>
    ${xL}
  </svg>`;

  return chart1 + chart2 + chart3 + chart4;
}
