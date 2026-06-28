const state = {
  page: localStorage.getItem("jayu.dashboard.activePage") || "overview",
  runId: "latest",
  runs: [],
  failurePatterns: null,
  decision: null,
  overview: null,
  dataQuality: null,
  dataTrust: null,
  unifiedQualityPolicy: null,
  tossFreshnessLedger: null,
  decisionInbox: null,
  investmentDecisionGraph: null,
  risk: null,
  signals: null,
  traderLens: null,
  promotion: null,
  settingsValidation: null,
  featureInventory: null,
  tossStatus: null,
  tossAccounts: null,
  tossMarket: null,
  tossPortfolio: null,
  tossReconciliation: null,
  tossOrderPlan: null,
  tossSubTab: localStorage.getItem("jayu.toss.subTab") || "overview",
  orderHistoryQuality: null,
  tossOrderIntegrity: null,
  tradeHistoryAnalytics: null,
  realizedPnlReconciliation: null,
  stockTradeLifecycle: null,
  tradeBehaviorReview: null,
  orderHistorySummary: null,
  apiMonitoring: null,
  tossAccountRegion: localStorage.getItem("jayu.toss.accountRegion") || "ALL",
  selectedTossAccount: localStorage.getItem("jayu.toss.selectedAccount") || "",
  apiMonitoringRefreshSec: localStorage.getItem("jayu.apiMonitoring.refresh") || "off",
  autoRefreshTimer: null,
  analysis: null,
  analysisTicker: localStorage.getItem("jayu.analysis.ticker") || "SOXL",
  analysisMacro: localStorage.getItem("jayu.analysis.macro") || "FEDFUNDS",
  analysisPeriod: localStorage.getItem("jayu.analysis.period") || "1y",
  analysisTab: "market",
  analysisMarketOverview: null,
  analysisTechnical: null,
  analysisCompare: null,
  analysisPortfolio: null,
  analysisCalendar: null,
  // 포트폴리오 허브
  portfolioHub: null,
  portfolioHubTab: localStorage.getItem("jayu.hub.tab") || "short_term",
  portfolioHubTickers: localStorage.getItem("jayu.hub.tickers") || "",
  // 자동매매 준비
  autotradingStatus: null,
  // 시뮬레이션 로그
  simulationLog: null,
  simulationStatus: "idle",
  permissionMode: "read_only",
  // 개인 투자 관리
  investmentGoals: null,
  cashflows: null,
  cashflowSettings: null,
  tossOrders: [],
  tossOrdersMeta: null,
  tossOrderDetails: {},
  selectedTossOrderId: "",
  dividendSim: null,
  dividendDashboard: null,
  behaviorInsights: null,
  portfolioDiet: null,
  investCalendar: null,
  benchmarkComparison: null,
  goalFormVisible: false,
  cashflowFormVisible: false,
};

const els = {
  root: document.querySelector("#page-root"),
  loading: document.querySelector("#loading-state"),
  error: document.querySelector("#error-state"),
  errorMessage: document.querySelector("#error-message"),
  liveRegion: document.querySelector("#live-region"),
  runSelector: document.querySelector("#run-selector"),
  modeBadge: document.querySelector("#mode-badge"),
  runTime: document.querySelector("#run-time"),
  hashSummary: document.querySelector("#hash-summary"),
  accountSummary: document.querySelector("#account-summary"),
  permissionModeSelector: document.querySelector("#permission-mode-selector"),
};

function reconcileSelectedTossAccount() {
  const accounts = state.tossAccounts?.accounts || [];
  if (!state.selectedTossAccount && state.tossAccounts?.auto_select_account_seq) {
    setSelectedTossAccount(state.tossAccounts.auto_select_account_seq, false);
    return;
  }
  if (
    state.selectedTossAccount &&
    accounts.length &&
    !accounts.some((account) => account.account_seq === state.selectedTossAccount)
  ) {
    setSelectedTossAccount("", false);
  }
}

function setSelectedTossAccount(accountSeq, announce = true) {
  state.selectedTossAccount = accountSeq || "";
  if (state.selectedTossAccount) {
    localStorage.setItem("jayu.toss.selectedAccount", state.selectedTossAccount);
  } else {
    localStorage.removeItem("jayu.toss.selectedAccount");
  }
  if (els.accountSummary) {
    els.accountSummary.textContent = selectedTossAccountLabel();
  }
  if (announce) {
    els.liveRegion.textContent = state.selectedTossAccount
      ? `Toss 계좌 ${selectedTossAccountLabel()}를 선택했습니다.`
      : "Toss 계좌 선택을 해제했습니다.";
  }
}

function selectedTossAccountLabel() {
  const account = (state.tossAccounts?.accounts || []).find(
    (item) => item.account_seq === state.selectedTossAccount
  );
  if (account) {
    return `${account.display_name || "Toss"} ${account.masked_account_no || ""}`.trim();
  }
  return state.selectedTossAccount ? `선택됨 ${state.selectedTossAccount.slice(-4)}` : "미선택";
}

async function api(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return response.json();
}

const RUN_CONTEXT_OPTIONAL_PAGES = new Set(["analysis", "portfolio-hub", "autotrading", "goal-planner", "cashflow", "dividend", "investor-coach", "invest-calendar"]);
const ORDER_HISTORY_CONTEXT_PAGES = new Set(["overview", "signals", "risk", "portfolio-hub", "investor-coach", "autotrading", "goal-planner"]);
const TERMINAL_RUN_STATUSES = new Set(["success", "failed", "error", "cancelled", "canceled"]);

function isCompletedRun(run) {
  const status = String(run?.status || "").toLowerCase();
  return Boolean(run?.is_complete || run?.finished_at || TERMINAL_RUN_STATUSES.has(status));
}

async function loadRuns() {
  const payload = await api("/api/v1/runs");
  state.runs = payload.runs || [];
  state.failurePatterns = payload.failure_patterns || null;
  
  const sliceCount = 7;
  const recentRuns = state.runs.slice(0, sliceCount);
  
  // Ensure currently selected runId is visible in the select box even if it's older
  const isIdInRecent = recentRuns.some(run => run.run_id === state.runId);
  if (state.runId && state.runId !== "latest" && !isIdInRecent) {
    const currentRunObj = state.runs.find(run => run.run_id === state.runId);
    if (currentRunObj) {
      recentRuns.push(currentRunObj);
    }
  }
  
  let options = [];
  if (recentRuns.length) {
    options = recentRuns.map(
      (run) =>
        `<option value="${escapeHtml(run.run_id)}">${escapeHtml(run.run_id)} · ${escapeHtml(
          String(run.mode || "unknown").toUpperCase()
        )} · ${escapeHtml(run.status)}</option>`
    );
  } else {
    options = ['<option value="latest">완료된 실행 없음</option>'];
  }
  options.push('<option value="go-to-history">🕒 실행 이력 전체 보기...</option>');
  els.runSelector.innerHTML = options.join("");
  
  if (state.runId === "latest" && state.runs[0]) {
    const defaultRun = state.runs.find(isCompletedRun) || state.runs[0];
    state.runId = defaultRun.run_id;
  }
  els.runSelector.value = state.runId;
}

async function loadPage() {
  setLoading(true);
  try {
    await loadPermissionMode();
    if (!state.runs.length) await loadRuns();
    
    try {
      const stockNames = await api("/api/v1/toss/stock-names");
      if (stockNames && typeof stockNames === "object") {
        Object.assign(TOSS_TICKER_NAMES, stockNames);
      }
    } catch (e) {
      console.warn("Failed to load stock name mappings", e);
    }

    try {
      state.tossSecurityMaster = await api("/api/v1/toss/security-master");
    } catch (e) {
      console.warn("Failed to load security master", e);
      state.tossSecurityMaster = {};
    }

    const run = encodeURIComponent(state.runId);
    if (RUN_CONTEXT_OPTIONAL_PAGES.has(state.page)) {
      try {
        state.decision = await api(`/api/v1/decision?run_id=${run}`);
        state.overview = await api(`/api/v1/overview?run_id=${run}`);
      } catch (err) {
        console.warn("Run context is unavailable; rendering standalone page", err);
        state.decision = state.decision || null;
        state.overview = state.overview || null;
      }
    } else {
      state.decision = await api(`/api/v1/decision?run_id=${run}`);
      state.overview = await api(`/api/v1/overview?run_id=${run}`);
    }
    if (state.page === "overview") {
      try {
        state.nextCommand = await api("/api/v1/recommender/next");
      } catch (err) {
        console.warn("Failed to load next command recommendation", err);
        state.nextCommand = null;
      }
      try {
        state.personalScore = await api("/api/v1/personal-investment-score");
      } catch (err) {
        console.warn("Failed to load personal investment score", err);
        state.personalScore = null;
      }
      try {
        state.investmentGoals = await api("/api/v1/investment-goals");
      } catch (err) {
        console.warn("Failed to load goals for overview page", err);
        state.investmentGoals = null;
      }
      try {
        state.decisionInbox = await api(`/api/v1/decision-inbox?run_id=${run}&limit=12`);
      } catch (err) {
        console.warn("Failed to load decision inbox", err);
        state.decisionInbox = null;
      }
    }
    if (!state.portfolioHub) {
      try {
        state.portfolioHub = await api("/api/v1/portfolio-hub");
      } catch (err) {
        console.warn("Failed to auto-load portfolio hub data", err);
      }
    }
    if (ORDER_HISTORY_CONTEXT_PAGES.has(state.page)) {
      try {
        const orderHistoryParams = new URLSearchParams();
        orderHistoryParams.set("run_id", state.runId || "latest");
        if (state.selectedTossAccount) orderHistoryParams.set("account", state.selectedTossAccount);
        state.orderHistorySummary = await api(`/api/v1/order-history-summary?${orderHistoryParams.toString()}`);
      } catch (err) {
        console.warn("Failed to load order history summary", err);
        state.orderHistorySummary = null;
      }
    } else if (state.page !== "toss-account") {
      state.orderHistorySummary = null;
    }
    if (state.page === "data-quality") {
      const [dataQuality, dataTrust, unifiedQualityPolicy, tossFreshnessLedger] = await Promise.all([
        api(`/api/v1/runs/${run}/data-quality`),
        api(`/api/v1/data-trust-score?run_id=${run}`),
        api(`/api/v1/unified-quality-policy?run_id=${run}`),
        api("/api/v1/toss/freshness-ledger")
      ]);
      state.dataQuality = dataQuality;
      state.dataTrust = dataTrust;
      state.unifiedQualityPolicy = unifiedQualityPolicy;
      state.tossFreshnessLedger = tossFreshnessLedger;
    }
    if (state.page === "risk") {
      state.risk = await api(`/api/v1/runs/${run}/risk`);
      try {
        state.strategyBudgets = await api("/api/v1/strategy/budgets");
      } catch (err) {
        console.warn("Failed to load strategy budgets", err);
        state.strategyBudgets = null;
      }
    }
    if (state.page === "signals") {
      state.signals = await api(`/api/v1/runs/${run}/signals`);
      try {
        state.approvalHistory = await api("/api/v1/approvals");
      } catch (err) {
        console.warn("Failed to load approval history", err);
        state.approvalHistory = { history: [] };
      }
      if (!state.portfolioHub) {
        try {
          state.portfolioHub = await api("/api/v1/portfolio-hub");
        } catch (err) {
          console.warn("Failed to load portfolio hub for signals page", err);
        }
      }
    }
    if (state.page === "trader-lens") {
      state.traderLens = await api(`/api/v1/runs/${run}/trader-lens`);
    }
    if (state.page === "promotion") {
      state.promotion = await api("/api/v1/promotion");
    }
    if (state.page === "settings") {
      const mode = encodeURIComponent(state.overview?.run?.mode || "shadow");
      state.settingsValidation = await api(`/api/v1/settings/validation?mode=${mode}`);
      try {
        state.backups = await api("/api/v1/backup/list");
      } catch (err) {
        console.warn("Failed to load backup list", err);
        state.backups = null;
      }
      try {
        state.events = await api("/api/v1/events");
      } catch (err) {
        console.warn("Failed to load events list", err);
        state.events = null;
      }
      try {
        state.securityQuality = await api("/api/v1/toss/security-quality");
      } catch (err) {
        console.warn("Failed to load security quality & reconciliation", err);
        state.securityQuality = null;
      }
      try {
        state.experiments = await api("/api/v1/experiments");
      } catch (err) {
        console.warn("Failed to load experiments list", err);
        state.experiments = null;
      }
      try {
        state.featureInventory = await api("/api/v1/features");
      } catch (err) {
        console.warn("Failed to load feature inventory", err);
        state.featureInventory = null;
      }
      try {
        state.orderHistoryQuality = await api("/api/v1/toss/order-quality");
      } catch (err) {
        console.warn("Failed to load order history quality", err);
        state.orderHistoryQuality = null;
      }
      try {
        state.tossOrderIntegrity = await api("/api/v1/toss/order-integrity");
      } catch (err) {
        console.warn("Failed to load Toss order integrity", err);
        state.tossOrderIntegrity = null;
      }
    }
    if (state.page === "toss") {
      state.tossStatus = await api("/api/v1/toss/status");
      state.tossAccounts = await api("/api/v1/toss/accounts");
      reconcileSelectedTossAccount();
    }
    if (state.page === "api-monitoring") {
      state.apiMonitoring = await api("/api/v1/api-monitoring");
    }
    if (state.page === "analysis") {
      try { state.journals = await api("/api/v1/investment-journals"); } catch(e) { state.journals = { journals: [] }; }
    }
    if (state.page === "portfolio-hub") {
      try {
        state.portfolioPurposeTags = await api("/api/v1/portfolio-purpose-tags");
      } catch (err) {
        console.warn("Failed to load purpose tags", err);
        state.portfolioPurposeTags = {};
      }
      try {
        state.securityExposure = await api("/api/v1/toss/security-exposure");
      } catch (err) {
        console.warn("Failed to load security exposure", err);
        state.securityExposure = null;
      }
    }
    if (state.page === "autotrading") {
      state.autotradingStatus = await api("/api/v1/autotrading-status");
    }
    if (state.page === "simulation-log") {
      const res = await api("/api/v1/simulation/log");
      state.simulationLog = res.logs || "";
      state.simulationStatus = res.status || "idle";
    }
    const isPersonalPage = ["goal-planner", "cashflow", "dividend", "investor-coach", "invest-calendar"].includes(state.page);
    if (isPersonalPage) {
      try {
        const orderParams = new URLSearchParams();
        if (state.selectedTossAccount) orderParams.set("account", state.selectedTossAccount);
        const ordersPath = `/api/v1/toss/orders${orderParams.toString() ? `?${orderParams.toString()}` : ""}`;
        const [resOrders, resCfSettings] = await Promise.all([
          api(ordersPath),
          api("/api/v1/cashflows/settings")
        ]);
        state.tossOrders = resOrders.orders || [];
        state.tossOrdersMeta = resOrders;
        state.cashflowSettings = resCfSettings || { default_salary_krw: 6500000.0 };
      } catch (e) {
        state.tossOrders = [];
        state.tossOrdersMeta = null;
        state.cashflowSettings = { default_salary_krw: 6500000.0 };
      }
    }

    if (state.page === "goal-planner") {
      try { state.investmentGoals = await api("/api/v1/investment-goals"); } catch(e) { state.investmentGoals = { goals: [] }; }
      try { state.lossRecovery = await api("/api/v1/loss-recovery-planner?loss_pct=0.20"); } catch(e) { state.lossRecovery = null; }
    }
    if (state.page === "cashflow") {
      try { state.cashflows = await api("/api/v1/cashflows"); } catch(e) { state.cashflows = { entries: [], budget: {} }; }
    }
    if (state.page === "dividend") {
      try { state.dividendDashboard = await api("/api/v1/dividend-dashboard"); } catch(e) { state.dividendDashboard = null; }
    }
    if (state.page === "investor-coach") {
      try { state.behaviorInsights = await api("/api/v1/behavior-insights"); } catch(e) { state.behaviorInsights = null; }
      try { state.portfolioDiet = await api("/api/v1/portfolio-diet"); } catch(e) { state.portfolioDiet = null; }
      try { state.personalScore = await api("/api/v1/personal-investment-score"); } catch(e) { state.personalScore = null; }
      try { state.tradeBehaviorReview = await api("/api/v1/trade-behavior-review"); } catch(e) { state.tradeBehaviorReview = null; }
      try { state.journals = await api("/api/v1/investment-journals"); } catch(e) { state.journals = { journals: [] }; }
    }
    if (state.page === "invest-calendar") {
      try { state.investCalendar = await api("/api/v1/investment-calendar"); } catch(e) { state.investCalendar = null; }
    }
    if (state.page === "toss-account") {
      const params = new URLSearchParams();
      if (state.selectedTossAccount) params.set("account", state.selectedTossAccount);
      
      const [
        portfolio,
        reconciliation,
        orderPlan,
        taxLots,
        taxLotsReconcile,
        tradeHistoryAnalytics,
        orderHistoryQuality,
        tossOrderIntegrity,
        realizedPnlReconciliation,
        stockTradeLifecycle,
        orderHistorySummary
      ] = await Promise.all([
        api(`/api/v1/toss/portfolio${params.toString() ? `?${params.toString()}` : ""}`),
        api(`/api/v1/toss/reconciliation${params.toString() ? `?${params.toString()}` : ""}`),
        api("/api/v1/toss/order-plan"),
        api("/api/v1/tax-lots"),
        api("/api/v1/tax-lots/reconcile"),
        api("/api/v1/toss/trade-history-analytics"),
        api("/api/v1/toss/order-quality"),
        api("/api/v1/toss/order-integrity"),
        api(`/api/v1/toss/realized-pnl-reconciliation${params.toString() ? `?${params.toString()}` : ""}`),
        api(`/api/v1/toss/stock-trade-lifecycle${params.toString() ? `?${params.toString()}` : ""}`),
        api(`/api/v1/order-history-summary${params.toString() ? `?${params.toString()}` : ""}`)
      ]);

      state.tossPortfolio = portfolio;
      state.tossReconciliation = reconciliation;
      state.tossOrderPlan = orderPlan;
      state.taxLots = taxLots.lots || [];
      state.taxLotsReconcile = taxLotsReconcile || {};
      state.tradeHistoryAnalytics = tradeHistoryAnalytics || null;
      state.orderHistoryQuality = orderHistoryQuality || null;
      state.tossOrderIntegrity = tossOrderIntegrity || null;
      state.realizedPnlReconciliation = realizedPnlReconciliation || null;
      state.stockTradeLifecycle = stockTradeLifecycle || null;
      state.orderHistorySummary = orderHistorySummary || null;

      state.tossAccounts = {
        status: state.tossPortfolio.status,
        accounts: state.tossPortfolio.accounts || [],
        auto_select_account_seq: state.tossPortfolio.auto_select_account_seq,
      };
      if (state.tossPortfolio.auto_select_account_seq) {
        setSelectedTossAccount(state.tossPortfolio.auto_select_account_seq, false);
      }
    }
    updateContext();
    render();
    setupApiMonitoringRefreshTimer();
    setLoading(false);
    els.liveRegion.textContent = `${pageTitle(state.page)} 화면을 갱신했습니다.`;
  } catch (error) {
    showError(error);
  }
}

function setLoading(loading) {
  els.loading.hidden = !loading;
  els.error.hidden = true;
  els.root.hidden = loading;
}

function showError(error) {
  els.loading.hidden = true;
  els.root.hidden = true;
  els.error.hidden = false;
  els.errorMessage.textContent = error.message || "잠시 후 다시 시도하세요.";
}

function updateContext() {
  const run = state.overview?.run || {};
  els.modeBadge.textContent = String(run.mode || "unknown").toUpperCase();
  els.runTime.textContent = formatDate(run.finished_at);
  els.hashSummary.textContent = `${shortHash(run.config_hash)} / ${shortHash(run.data_hash)}`;
  els.hashSummary.title = `config: ${run.config_hash || "-"}\ndata: ${run.data_hash || "-"}`;
  if (els.accountSummary) {
    els.accountSummary.textContent = selectedTossAccountLabel();
  }
}

function pageTitle(page) {
  return {
    overview: "개요",
    "data-quality": "데이터 품질",
    risk: "리스크 게이트",
    signals: "신호",
    "trader-lens": "Trader Lens",
    promotion: "Shadow 승격",
    settings: "설정 검증",
    "toss-account": "Toss Account",
    toss: "Toss Market",
    "api-monitoring": "API 모니터링",
    analysis: "주식 & 경제 분석",
    "portfolio-hub": "포트폴리오 허브",
    autotrading: "자동매매 준비",
    "simulation-log": "시뮬레이션 로그",
    "run-history": "실행 이력 & 로그",
    "goal-planner": "투자 목표 & 계획",
    cashflow: "현금흐름 배분",
    "dividend": "배당 관리",
    "investor-coach": "투자 코치 & 다이어트",
    "invest-calendar": "투자 캘린더",
  }[page] || page;
}

function render() {
  els.root.hidden = false;
  if (state.page === "data-quality") renderDataQuality();
  else if (state.page === "risk") {
    renderRisk();
    loadAndRenderStrategyCards();
  }
  else if (state.page === "signals") renderSignals();
  else if (state.page === "trader-lens") renderTraderLens();
  else if (state.page === "promotion") renderPromotion();
  else if (state.page === "settings") renderSettingsValidation();
  else if (state.page === "toss-account") renderTossAccountDashboard();
  else if (state.page === "toss") renderTossMarket();
  else if (state.page === "api-monitoring") renderApiMonitoring();
  else if (state.page === "analysis") renderAnalysis();
  else if (state.page === "portfolio-hub") renderPortfolioHub();
  else if (state.page === "autotrading") renderAutotrading();
  else if (state.page === "simulation-log") renderSimulationLog();
  else if (state.page === "run-history") renderRunHistory();
  else if (state.page === "ask-jayu") renderAskJayu();
  else if (state.page === "goal-planner") renderGoalPlanner();
  else if (state.page === "cashflow") renderCashflow();
  else if (state.page === "dividend") renderDividendPage();
  else if (state.page === "investor-coach") renderInvestorCoach();
  else if (state.page === "invest-calendar") renderInvestCalendar();
  else renderOverview();
  bindPageActions();
}

function bindPageActions() {
  document.querySelectorAll("[data-go]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.go));
  });
  document.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", async () => {
      const command = button.dataset.command;
      const feedback = document.querySelector("#command-feedback");
      try {
        await navigator.clipboard.writeText(command);
        feedback.textContent = `명령을 복사했습니다: ${command}`;
      } catch {
        feedback.textContent = `실행 명령: ${command}`;
      }
      feedback.hidden = false;
      els.liveRegion.textContent = feedback.textContent;
    });
  });
  document.querySelectorAll("[data-toss-account]").forEach((button) => {
    button.addEventListener("click", () => {
      setSelectedTossAccount(button.dataset.tossAccount || "");
      if (state.page === "toss-account") {
        state.tossPortfolio = null;
        state.realizedPnlReconciliation = null;
        state.stockTradeLifecycle = null;
        loadPage();
        return;
      }
      renderTossMarket();
      bindPageActions();
    });
  });
  document.querySelectorAll("[data-toss-region]").forEach((button) => {
    button.addEventListener("click", () => {
      state.tossAccountRegion = button.dataset.tossRegion || "ALL";
      localStorage.setItem("jayu.toss.accountRegion", state.tossAccountRegion);
      renderTossAccountDashboard();
      bindPageActions();
    });
  });
  document.querySelectorAll("[data-toss-subtab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.tossSubTab = button.dataset.tossSubtab || "overview";
      localStorage.setItem("jayu.toss.subTab", state.tossSubTab);
      renderTossAccountDashboard();
      bindPageActions();
    });
  });
  document.querySelectorAll("[data-toss-order-detail]").forEach((button) => {
    button.addEventListener("click", async () => {
      const orderId = button.dataset.tossOrderDetail || "";
      if (!orderId) return;
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = "상세 조회 중...";
      try {
        const params = new URLSearchParams();
        if (state.selectedTossAccount) params.set("account", state.selectedTossAccount);
        const path = `/api/v1/toss/orders/${encodeURIComponent(orderId)}${params.toString() ? `?${params.toString()}` : ""}`;
        const detail = await api(path);
        state.tossOrderDetails = { ...(state.tossOrderDetails || {}), [orderId]: detail };
        state.selectedTossOrderId = orderId;
        els.liveRegion.textContent = `Toss 주문 상세를 조회했습니다: ${orderId}`;
        render();
      } catch (error) {
        button.disabled = false;
        button.textContent = originalText;
        els.liveRegion.textContent = error.message || "Toss 주문 상세 조회에 실패했습니다.";
      }
    });
  });
  const tossForm = document.querySelector("#toss-market-form");
  if (tossForm) {
    tossForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const feedback = document.querySelector("#toss-feedback");
      const symbol = document.querySelector("#toss-symbol-input")?.value || "";
      const account = document.querySelector("#toss-account-input")?.value || state.selectedTossAccount || "";
      const includeAccount = document.querySelector("#toss-include-account")?.checked || false;
      if (account) {
        setSelectedTossAccount(account, false);
      }
      const params = new URLSearchParams({ symbol });
      if (account) params.set("account", account);
      if (includeAccount) params.set("include_account", "true");
      feedback.hidden = false;
      feedback.textContent = "Toss Market Data를 조회하는 중입니다.";
      try {
        state.tossMarket = await api(`/api/v1/toss/market?${params.toString()}`);
        feedback.textContent = "Toss Market Data 조회가 완료되었습니다.";
        renderTossMarket();
        bindPageActions();
      } catch (error) {
        feedback.textContent = error.message || "Toss Market Data 조회에 실패했습니다.";
      }
      els.liveRegion.textContent = feedback.textContent;
    });
  }

  // API Connection Test action
  document.querySelectorAll("[data-test-provider]").forEach((button) => {
    button.addEventListener("click", async () => {
      const provider = button.dataset.testProvider;
      const resultSpan = document.querySelector(`#test-result-${provider}`);
      if (!resultSpan) return;
      button.disabled = true;
      resultSpan.className = "pmc-test-result";
      resultSpan.textContent = "테스트 중...";
      try {
        const res = await fetch("/api/v1/api-monitoring/test-connection", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider }),
        });
        const data = await res.json();
        if (data.status === "success") {
          resultSpan.className = "pmc-test-result success";
          resultSpan.textContent = `✓ 연결 성공 (${data.latency_ms}ms)`;
        } else {
          resultSpan.className = "pmc-test-result failed";
          resultSpan.textContent = `✗ 실패 (${data.latency_ms}ms): ${data.message || "오류"}`;
        }
      } catch (err) {
        resultSpan.className = "pmc-test-result failed";
        resultSpan.textContent = `✗ 에러: ${err.message}`;
      } finally {
        button.disabled = false;
      }
    });
  });

  // Clear Cache action
  document.querySelectorAll("[data-clear-cache]").forEach((button) => {
    button.addEventListener("click", async () => {
      const cacheType = button.dataset.clearCache;
      const confirmMsg = cacheType === "all"
        ? "정말로 모든 API 캐시를 삭제하시겠습니까?"
        : `정말로 ${cacheType} 캐시를 삭제하시겠습니까?`;
      if (!confirm(confirmMsg)) return;
      button.disabled = true;
      try {
        const res = await fetch("/api/v1/api-monitoring/clear-cache", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cache_type: cacheType }),
        });
        const data = await res.json();
        if (data.status === "success") {
          alert(data.message);
          // Reload the page data to update stats
          state.apiMonitoring = null;
          loadPage();
        } else {
          alert(`캐시 삭제 실패: ${data.message}`);
        }
      } catch (err) {
        alert(`캐시 삭제 에러: ${err.message}`);
      } finally {
        button.disabled = false;
      }
    });
  });

  // Copy Env Template action
  const btnCopyTemplate = document.querySelector("#btn-copy-env-template");
  if (btnCopyTemplate) {
    btnCopyTemplate.addEventListener("click", async () => {
      const templatePre = document.querySelector("#env-template-text");
      if (!templatePre) return;
      try {
        await navigator.clipboard.writeText(templatePre.textContent);
        btnCopyTemplate.textContent = "복사 완료 ✓";
        setTimeout(() => { btnCopyTemplate.textContent = "템플릿 복사"; }, 2000);
      } catch (err) {
        alert(`복사 실패: ${err.message}`);
      }
    });
  }

  // Auto refresh select change
  const selectAutoRefresh = document.querySelector("#select-auto-refresh");
  if (selectAutoRefresh) {
    selectAutoRefresh.addEventListener("change", () => {
      const val = selectAutoRefresh.value;
      state.apiMonitoringRefreshSec = val;
      localStorage.setItem("jayu.apiMonitoring.refresh", val);
      setupApiMonitoringRefreshTimer();
    });
  }

  // Ping All action
  const btnPingAll = document.querySelector("#btn-ping-all");
  if (btnPingAll) {
    btnPingAll.addEventListener("click", async () => {
      btnPingAll.disabled = true;
      btnPingAll.textContent = "연결 테스트 중...";
      const buttons = Array.from(document.querySelectorAll("[data-test-provider]"));

      const promises = buttons.map(async (btn) => {
        const provider = btn.dataset.testProvider;
        const resultSpan = document.querySelector(`#test-result-${provider}`);
        if (!resultSpan) return;
        btn.disabled = true;
        resultSpan.className = "pmc-test-result";
        resultSpan.textContent = "테스트 중...";
        try {
          const res = await fetch("/api/v1/api-monitoring/test-connection", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ provider }),
          });
          const data = await res.json();
          if (data.status === "success") {
            resultSpan.className = "pmc-test-result success";
            resultSpan.textContent = `✓ 연결 성공 (${data.latency_ms}ms)`;
          } else {
            resultSpan.className = "pmc-test-result failed";
            resultSpan.textContent = `✗ 실패 (${data.latency_ms}ms): ${data.message || "오류"}`;
          }
        } catch (err) {
          resultSpan.className = "pmc-test-result failed";
          resultSpan.textContent = `✗ 에러: ${err.message}`;
        } finally {
          btn.disabled = false;
        }
      });
      await Promise.all(promises);
      btnPingAll.disabled = false;
      btnPingAll.textContent = "모든 API 연결 테스트";
    });
  }

  // Logs filtering
  const logSearchInput = document.querySelector("#log-search-input");
  const logLevelFilter = document.querySelector("#log-level-filter");
  const filteredLogCount = document.querySelector("#filtered-log-count");
  if (logSearchInput && logLevelFilter) {
    const filterLogs = () => {
      const query = logSearchInput.value.toLowerCase().trim();
      const level = logLevelFilter.value;
      let visibleCount = 0;
      const rows = document.querySelectorAll("#api-logs-table tbody .log-row");
      rows.forEach((row) => {
        const rowLevel = row.dataset.level || "";
        const eventText = row.querySelector(".log-event-cell")?.textContent.toLowerCase() || "";
        const messageText = row.querySelector(".log-message-cell")?.textContent.toLowerCase() || "";

        const matchLevel = (level === "ALL") ||
                           (level === "ERROR" && (rowLevel === "ERROR" || rowLevel === "CRITICAL")) ||
                           (level === "WARNING" && rowLevel === "WARNING");
        const matchSearch = !query || eventText.includes(query) || messageText.includes(query);

        if (matchLevel && matchSearch) {
          row.style.display = "";
          visibleCount++;
        } else {
          row.style.display = "none";
        }
      });
      if (filteredLogCount) {
        filteredLogCount.textContent = `${visibleCount}건`;
      }
    };
    logSearchInput.addEventListener("input", filterLogs);
    logLevelFilter.addEventListener("change", filterLogs);
  }

  // Portfolio sync action
  const syncButtons = document.querySelectorAll("#btn-sync-portfolio, #btn-sync-portfolio-banner");
  syncButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const confirmMsg = "현재 토스 실계좌 보유 종목 정보를 가져와서 로컬 portfolio.csv 파일을 갱신하시겠습니까?";
      if (!confirm(confirmMsg)) return;

      btn.disabled = true;
      const originalText = btn.textContent;
      btn.textContent = "동기화 진행 중...";

      try {
        const payload = {};
        if (state.selectedTossAccount) {
          payload.account = state.selectedTossAccount;
        }

        const res = await fetch("/api/v1/toss/reconciliation/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.status === "success") {
          alert(data.message || "성공적으로 동기화되었습니다.");
          // Clear cached portfolio and reconciliation data so they are re-fetched
          state.tossPortfolio = null;
          state.tossReconciliation = null;
          state.realizedPnlReconciliation = null;
          state.stockTradeLifecycle = null;
          loadPage();
        } else {
          alert(`동기화 실패: ${data.message || "오류가 발생했습니다."}`);
        }
      } catch (err) {
        alert(`동기화 에러: ${err.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    });
  });

  // ── Analysis Tab Switching ─────────────────────────────────────────────────
  document.querySelectorAll("[data-analysis-tab]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.analysisTab = btn.dataset.analysisTab;
      renderAnalysis();
      bindPageActions();
    });
  });

  // ── Market Overview ────────────────────────────────────────────────────────
  const btnLoadMarket = document.querySelector("#btn-load-market");
  if (btnLoadMarket) {
    btnLoadMarket.addEventListener("click", async () => {
      btnLoadMarket.disabled = true;
      btnLoadMarket.textContent = "⏳ 로딩 중...";
      try {
        state.analysisMarketOverview = await api("/api/v1/analysis/market-overview");
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("시장 데이터 조회 실패: " + (err.message || "오류"));
      } finally {
        btnLoadMarket.disabled = false;
        btnLoadMarket.textContent = "🔄 시장 데이터 새로고침";
      }
    });
    // Auto-load market data on tab entry if not loaded yet
    if (!state.analysisMarketOverview && state.analysisTab === "market") {
      btnLoadMarket.click();
    }
  }

  // ── Basic Analysis Fetch ───────────────────────────────────────────────────
  const btnAnalysisFetch = document.querySelector("#btn-analysis-fetch");
  if (btnAnalysisFetch) {
    btnAnalysisFetch.addEventListener("click", async () => {
      const ticker = document.querySelector("#analysis-ticker")?.value || state.analysisTicker || "SOXL";
      const macro = document.querySelector("#analysis-macro")?.value || state.analysisMacro || "FEDFUNDS";
      const period = document.querySelector("#analysis-period")?.value || state.analysisPeriod || "1y";
      state.analysisTicker = ticker;
      state.analysisMacro = macro;
      state.analysisPeriod = period;
      localStorage.setItem("jayu.analysis.ticker", ticker);
      localStorage.setItem("jayu.analysis.macro", macro);
      localStorage.setItem("jayu.analysis.period", period);
      state.analysis = null;
      btnAnalysisFetch.disabled = true;
      btnAnalysisFetch.textContent = "⏳ 조회 중...";
      try {
        state.analysis = await api(`/api/v1/analysis?ticker=${encodeURIComponent(ticker)}&macro_series=${encodeURIComponent(macro)}&period=${encodeURIComponent(period)}`);
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("분석 조회 실패: " + (err.message || "오류"));
      } finally {
        btnAnalysisFetch.disabled = false;
        btnAnalysisFetch.textContent = "📊 조회";
      }
    });
  }

  // ── Technical Indicators Fetch ─────────────────────────────────────────────
  const btnTechFetch = document.querySelector("#btn-tech-fetch");
  if (btnTechFetch) {
    btnTechFetch.addEventListener("click", async () => {
      const ticker = document.querySelector("#tech-ticker")?.value || state.analysisTicker || "SOXL";
      const period = document.querySelector("#tech-period")?.value || state.analysisPeriod || "1y";
      state.analysisTicker = ticker;
      state.analysisPeriod = period;
      btnTechFetch.disabled = true;
      btnTechFetch.textContent = "⏳ 계산 중...";
      try {
        state.analysisTechnical = await api(`/api/v1/analysis/technical?ticker=${encodeURIComponent(ticker)}&period=${encodeURIComponent(period)}`);
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("기술적 지표 조회 실패: " + (err.message || "오류"));
      } finally {
        btnTechFetch.disabled = false;
        btnTechFetch.textContent = "📊 조회";
      }
    });
  }

  // ── Multi-Compare Fetch ────────────────────────────────────────────────────
  const btnCompareFetch = document.querySelector("#btn-compare-fetch");
  if (btnCompareFetch) {
    btnCompareFetch.addEventListener("click", async () => {
      const rawTickers = document.querySelector("#compare-tickers")?.value || "SOXL,TQQQ,NVDA,QQQ,SPY";
      const period = document.querySelector("#compare-period")?.value || state.analysisPeriod || "1y";
      state.analysisPeriod = period;
      btnCompareFetch.disabled = true;
      btnCompareFetch.textContent = "⏳ 비교 중...";
      try {
        const tickers = rawTickers.split(",").map(t => t.trim()).filter(Boolean).join(",");
        state.analysisCompare = await api(`/api/v1/analysis/multi-compare?tickers=${encodeURIComponent(tickers)}&period=${encodeURIComponent(period)}`);
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("비교 조회 실패: " + (err.message || "오류"));
      } finally {
        btnCompareFetch.disabled = false;
        btnCompareFetch.textContent = "📊 비교";
      }
    });
  }

  // ── Portfolio Stats Fetch ──────────────────────────────────────────────────
  const btnPortfolioFetch = document.querySelector("#btn-portfolio-fetch");
  if (btnPortfolioFetch) {
    btnPortfolioFetch.addEventListener("click", async () => {
      btnPortfolioFetch.disabled = true;
      btnPortfolioFetch.textContent = "⏳ 로딩 중...";
      try {
        const run = state.runId ? `?run_id=${encodeURIComponent(state.runId)}` : "";
        state.analysisPortfolio = await api(`/api/v1/analysis/portfolio-stats${run}`);
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("포트폴리오 성과 조회 실패: " + (err.message || "오류"));
      } finally {
        btnPortfolioFetch.disabled = false;
        btnPortfolioFetch.textContent = "📊 실행 데이터 조회";
      }
    });
    // Auto-load if not loaded yet
    if (!state.analysisPortfolio && state.analysisTab === "portfolio") {
      btnPortfolioFetch.click();
    }
  }

  // ── Economic Calendar Fetch ────────────────────────────────────────────────
  const btnCalendarFetch = document.querySelector("#btn-calendar-fetch");
  if (btnCalendarFetch) {
    btnCalendarFetch.addEventListener("click", async () => {
      btnCalendarFetch.disabled = true;
      btnCalendarFetch.textContent = "⏳ 로딩 중...";
      try {
        state.analysisCalendar = await api("/api/v1/analysis/economic-calendar");
        renderAnalysis();
        bindPageActions();
      } catch (err) {
        alert("경제 캘린더 조회 실패: " + (err.message || "오류"));
      } finally {
        btnCalendarFetch.disabled = false;
        btnCalendarFetch.textContent = "📅 캘린더 로드";
      }
    });
    // Auto-load if not loaded yet
    if (!state.analysisCalendar && state.analysisTab === "calendar") {
      btnCalendarFetch.click();
    }
  }

  // ── Portfolio Hub Actions ──────────────────────────────────────────────────
  if (state.page === "portfolio-hub") {
    bindPortfolioHubActions();
  }

  // ── Simulation Log Actions ─────────────────────────────────────────────────
  if (state.page === "simulation-log") {
    bindSimulationLogActions();
  }

  // ── User Approval Actions (Signals Page) ───────────────────────────────────
  if (state.page === "signals") {
    document.querySelectorAll(".btn-decide").forEach(btn => {
      btn.addEventListener("click", async () => {
        const decision = btn.dataset.decision;
        const ticker = btn.dataset.ticker;
        const action = btn.dataset.action;
        const runId = btn.dataset.runId;
        const recVerdict = btn.dataset.recVerdict;
        
        const decisionLabel = { approve: "승인", hold: "보류", ignore: "무시" }[decision];
        const rationale = prompt(`[${ticker}] 신호 ${action.toUpperCase()}에 대한 ${decisionLabel} 사유를 입력하세요 (선택 사항):`, "");
        if (rationale === null) return; // User cancelled the prompt
        
        btn.disabled = true;
        try {
          const res = await fetch("/api/v1/approvals", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              run_id: runId,
              ticker: ticker,
              action: action,
              rec_verdict: recVerdict,
              user_decision: decision,
              rationale: rationale
            })
          });
          const data = await res.json();
          if (data.status === "success") {
            const run = encodeURIComponent(state.runId);
            state.signals = await api(`/api/v1/runs/${run}/signals`);
            state.approvalHistory = await api("/api/v1/approvals");
            renderSignals();
            bindPageActions();
          } else {
            alert(`의사결정 등록 실패: ${data.message || "오류가 발생했습니다."}`);
          }
        } catch (err) {
          alert(`에러: ${err.message}`);
        } finally {
          btn.disabled = false;
        }
      });
    });

    document.querySelectorAll(".btn-change-decision").forEach(btn => {
      btn.addEventListener("click", () => {
        const ticker = btn.dataset.ticker;
        const action = btn.dataset.action;
        const runId = btn.dataset.runId;
        const recVerdict = btn.dataset.recVerdict;
        
        const decision = prompt(`[${ticker}] 신호를 어떻게 변경하시겠습니까?\n(approve = 승인, hold = 보류, ignore = 무시):`, "approve");
        if (!decision) return;
        const decisionLower = decision.toLowerCase().trim();
        if (!["approve", "hold", "ignore"].includes(decisionLower)) {
          alert("올바르지 않은 결정 코드입니다. (approve, hold, ignore 중 하나 입력)");
          return;
        }
        
        const rationale = prompt(`변경 사유를 입력하세요 (선택 사항):`, "");
        if (rationale === null) return;
        
        (async () => {
          btn.disabled = true;
          try {
            const res = await fetch("/api/v1/approvals", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                run_id: runId,
                ticker: ticker,
                action: action,
                rec_verdict: recVerdict,
                user_decision: decisionLower,
                rationale: rationale
              })
            });
            const data = await res.json();
            if (data.status === "success") {
              const run = encodeURIComponent(state.runId);
              state.signals = await api(`/api/v1/runs/${run}/signals`);
              state.approvalHistory = await api("/api/v1/approvals");
              renderSignals();
              bindPageActions();
            } else {
              alert(`의사결정 변경 실패: ${data.message || "오류가 발생했습니다."}`);
            }
          } catch (err) {
            alert(`에러: ${err.message}`);
          } finally {
            btn.disabled = false;
          }
        })();
      });
    });
  }

  // ── Tax Lot Actions (Toss Account Page) ────────────────────────────────────
  if (state.page === "toss-account" && state.tossSubTab === "reconciliation") {
    const btnAddTaxLot = document.querySelector("#btn-add-tax-lot");
    if (btnAddTaxLot) {
      btnAddTaxLot.addEventListener("click", async () => {
        const ticker = prompt("종목 코드를 입력하세요 (예: SOXL):");
        if (!ticker) return;
        const quantityStr = prompt("매수 수량을 입력하세요:");
        if (!quantityStr) return;
        const priceStr = prompt("매수 단가 (USD)를 입력하세요:");
        if (!priceStr) return;
        const fxStr = prompt("적용 환율 (KRW, 기본값 1350)을 입력하세요:", "1350");
        if (!fxStr) return;
        const commStr = prompt("수수료 (USD, 기본값 0)를 입력하세요:", "0");
        
        const quantity = parseFloat(quantityStr);
        const unit_price = parseFloat(priceStr);
        const fx_rate = parseFloat(fxStr);
        const commission = parseFloat(commStr || "0");
        
        if (isNaN(quantity) || quantity <= 0 || isNaN(unit_price) || unit_price <= 0 || isNaN(fx_rate) || fx_rate <= 0) {
          alert("올바르지 않은 입력값입니다.");
          return;
        }
        
        btnAddTaxLot.disabled = true;
        try {
          const res = await fetch("/api/v1/tax-lots/buy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ticker: ticker.toUpperCase(),
              quantity,
              unit_price,
              fx_rate,
              currency: "USD",
              commission
            })
          });
          const data = await res.json();
          if (data.status === "success") {
            alert(`신규 세금 Lot이 성공적으로 기록되었습니다:\nID: ${data.lot.lot_id}`);
            state.tossPortfolio = null;
            state.realizedPnlReconciliation = null;
            loadPage();
          } else {
            alert(`기록 실패: ${data.message || "오류가 발생했습니다."}`);
          }
        } catch (err) {
          alert(`에러: ${err.message}`);
        } finally {
          btnAddTaxLot.disabled = false;
        }
      });
    }

    const btnSellTaxLot = document.querySelector("#btn-sell-tax-lot");
    if (btnSellTaxLot) {
      btnSellTaxLot.addEventListener("click", async () => {
        const ticker = prompt("매도할 종목 코드를 입력하세요 (예: SOXL):");
        if (!ticker) return;
        const quantityStr = prompt("매도 수량을 입력하세요:");
        if (!quantityStr) return;
        const priceStr = prompt("매도 단가 (USD)를 입력하세요:");
        if (!priceStr) return;
        const fxStr = prompt("적용 환율 (KRW, 기본값 1350)을 입력하세요:", "1350");
        if (!fxStr) return;
        const commStr = prompt("수수료 (USD, 기본값 0)를 입력하세요:", "0");
        
        const quantity = parseFloat(quantityStr);
        const sell_price = parseFloat(priceStr);
        const sell_fx_rate = parseFloat(fxStr);
        const commission = parseFloat(commStr || "0");
        
        if (isNaN(quantity) || quantity <= 0 || isNaN(sell_price) || sell_price <= 0 || isNaN(sell_fx_rate) || sell_fx_rate <= 0) {
          alert("올바르지 않은 입력값입니다.");
          return;
        }
        
        btnSellTaxLot.disabled = true;
        try {
          const res = await fetch("/api/v1/tax-lots/sell", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ticker: ticker.toUpperCase(),
              quantity,
              sell_price,
              sell_fx_rate,
              commission
            })
          });
          const data = await res.json();
          if (data.status === "success") {
            alert(`FIFO 매도 처리가 완료되었습니다.\n실현 손익: ${formatCurrency(data.realized_pnl, "KRW")}`);
            state.tossPortfolio = null;
            state.realizedPnlReconciliation = null;
            loadPage();
          } else {
            alert(`매도 처리 실패: ${data.message || "오류가 발생했습니다."}`);
          }
        } catch (err) {
          alert(`에러: ${err.message}`);
        } finally {
          btnSellTaxLot.disabled = false;
        }
      });
    }
  }
}

function clearApiMonitoringRefreshTimer() {
  if (state.autoRefreshTimer) {
    clearInterval(state.autoRefreshTimer);
    state.autoRefreshTimer = null;
  }
}

function setupApiMonitoringRefreshTimer() {
  clearApiMonitoringRefreshTimer();
  if (state.page !== "api-monitoring") return;
  const refreshSec = state.apiMonitoringRefreshSec || "off";
  if (refreshSec === "off") return;

  const sec = parseInt(refreshSec, 10);
  if (Number.isNaN(sec)) return;

  state.autoRefreshTimer = setInterval(async () => {
    if (state.page === "api-monitoring") {
      try {
        const run = encodeURIComponent(state.runId);
        state.decision = await api(`/api/v1/decision?run_id=${run}`);
        state.overview = await api(`/api/v1/overview?run_id=${run}`);
        state.apiMonitoring = await api("/api/v1/api-monitoring");
        updateContext();
        render();
      } catch (err) {
        console.error("Auto refresh failed", err);
      }
    }
  }, sec * 1000);
}

function navigate(page) {
  if (![
    "overview", "data-quality", "risk", "signals", "trader-lens", "promotion",
    "settings", "toss-account", "toss", "api-monitoring", "analysis",
    "portfolio-hub", "autotrading", "simulation-log", "run-history", "ask-jayu",
    "goal-planner", "cashflow", "dividend", "investor-coach", "invest-calendar"
  ].includes(page)) return;
  clearApiMonitoringRefreshTimer();
  state.page = page;
  localStorage.setItem("jayu.dashboard.activePage", page);
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.page === page);
  });
  expandActiveNavGroup();
  loadPage();
}

function expandActiveNavGroup() {
  const activeItem = document.querySelector(`.nav-item[data-page="${state.page}"]`);
  if (activeItem) {
    const activeGroup = activeItem.closest(".nav-group");
    if (activeGroup) {
      activeGroup.classList.remove("is-collapsed");
    }
  }
}

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => navigate(item.dataset.page));
});

els.runSelector.addEventListener("change", () => {
  const val = els.runSelector.value;
  if (val === "go-to-history") {
    els.runSelector.value = state.runId;
    navigate("run-history");
    return;
  }
  state.runId = val;
  state.decision = null;
  state.overview = null;
  state.dataQuality = null;
  state.dataTrust = null;
  state.risk = null;
  state.signals = null;
  state.traderLens = null;
  state.promotion = null;
  state.settingsValidation = null;
  state.tossStatus = null;
  state.tossAccounts = null;
  state.tossMarket = null;
  state.tossPortfolio = null;
  state.realizedPnlReconciliation = null;
  state.stockTradeLifecycle = null;
  state.apiMonitoring = null;
  loadPage();
});

document.querySelector("#refresh-button").addEventListener("click", async () => {
  state.runs = [];
  state.decision = null;
  state.overview = null;
  state.dataTrust = null;
  state.traderLens = null;
  state.tossStatus = null;
  state.tossAccounts = null;
  state.tossMarket = null;
  state.tossPortfolio = null;
  state.realizedPnlReconciliation = null;
  state.stockTradeLifecycle = null;
  state.apiMonitoring = null;
  await loadPage();
});

document.querySelector("#retry-button").addEventListener("click", loadPage);

const expSelector = document.querySelector("#explanation-level-selector");
if (expSelector) {
  expSelector.addEventListener("change", async () => {
    const lvl = expSelector.value;
    try {
      await api(`/api/v1/set-explanation-level?level=${lvl}`);
      state.portfolioHub = null;
      await loadPage();
    } catch (err) {
      alert("설명 수준 변경 실패: " + err.message);
    }
  });
}

async function loadPermissionMode() {
  try {
    const res = await api("/api/v1/permission-mode");
    state.permissionMode = res.mode;
    if (els.permissionModeSelector) {
      els.permissionModeSelector.value = res.mode;
    }
  } catch (err) {
    console.warn("Failed to load permission mode", err);
  }
}

if (els.permissionModeSelector) {
  els.permissionModeSelector.addEventListener("change", async (e) => {
    const mode = e.target.value;
    try {
      const response = await fetch("/api/v1/permission-mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode })
      });
      const res = await response.json();
      if (res.status === "success") {
        state.permissionMode = res.mode;
        els.liveRegion.textContent = `권한 모드가 ${res.mode}로 전환되었습니다.`;
        await loadPage();
      } else {
        alert(`권한 모드 변경 실패: ${res.message}`);
      }
    } catch (err) {
      alert(`권한 모드 변경 오류: ${err.message}`);
    }
  });
}

function renderAskJayu() {
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>Ask Jayu (AI 자연어 질의 & RAG 센터)</h1>
        <p>프로젝트 문서, 실시간 신호 결과, 일별 리스크 심사 보고서를 검색하여 한국어 근거 기반 답변을 얻습니다.</p>
      </div>
    </div>
    
    <div class="grid-2col" style="display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; margin-top: 1.5rem;">
      <section class="panel">
        <div class="panel-header">
          <h2>💬 AI 자연어 질의 (Local RAG)</h2>
        </div>
        <div class="panel-body" style="padding-top: 1rem;">
          <div style="display: flex; gap: 0.5rem; margin-bottom: 1rem;">
            <input type="text" id="rag-query" placeholder="예: 어제 SOXL이 왜 리스크 게이트에서 차단되었어?" 
                   style="flex: 1; padding: 0.75rem; border: 1px solid var(--border); border-radius: 6px; font-size: 0.95rem; background: var(--surface); color: var(--text);">
            <button class="button button-primary" id="btn-ask-rag" type="button">질문하기</button>
          </div>
          
          <div id="rag-response-container" style="background: var(--neutral-bg, #f8fafc); border: 1px solid var(--border); border-radius: 6px; padding: 1.2rem; min-height: 200px; display: flex; flex-direction: column;">
            <span class="muted" style="margin: auto; text-align: center;">여기에 질문을 입력하고 질문하기 버튼을 클릭해 주세요.</span>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <h2>📊 대화형 시나리오 스트레스 테스터</h2>
        </div>
        <div class="panel-body" style="padding-top: 1rem; display: flex; flex-direction: column; gap: 1.2rem;">
          <div>
            <label for="slider-fx" style="font-weight: bold; display: block; margin-bottom: 0.5rem;">💵 원/달러 환율 변동 (%)</label>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              <input type="range" id="slider-fx" min="-10" max="10" value="0" step="0.5" style="flex: 1;">
              <span id="val-fx" style="font-weight: bold; min-width: 3rem; text-align: right;">0.0%</span>
            </div>
          </div>

          <div>
            <label for="slider-nasdaq" style="font-weight: bold; display: block; margin-bottom: 0.5rem;">📈 나스닥 100 지수 변동 (%)</label>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              <input type="range" id="slider-nasdaq" min="-15" max="15" value="0" step="0.5" style="flex: 1;">
              <span id="val-nasdaq" style="font-weight: bold; min-width: 3rem; text-align: right;">0.0%</span>
            </div>
          </div>

          <div style="border-top: 1px solid var(--border); padding-top: 1rem; margin-top: 0.5rem;">
            <h3 style="font-size: 1rem; margin-bottom: 0.75rem;">🔮 가상 스트레스 시뮬레이션 결과</h3>
            <div style="display: flex; flex-direction: column; gap: 0.6rem;">
              <div style="display: flex; justify-content: space-between;">
                <span class="muted">예상 포트폴리오 평가 영향액:</span>
                <strong id="stress-portfolio-impact" style="color: var(--text);">0원 (0.00%)</strong>
              </div>
              <div style="display: flex; justify-content: space-between;">
                <span class="muted">리스크 경고 상태:</span>
                <strong id="stress-risk-verdict" style="color: #10b981;">✅ 안전 (정상 범주)</strong>
              </div>
              <p style="font-size: 0.8rem; color: var(--muted); margin: 0; line-height: 1.4;">
                * 설정된 원화/외화 현금 비중 및 자산 배분 비중을 기초로 연산된 가상 스트레스 테스트 결과입니다.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  `;

  const btnAsk = document.querySelector("#btn-ask-rag");
  const inputQuery = document.querySelector("#rag-query");
  const container = document.querySelector("#rag-response-container");

  btnAsk.addEventListener("click", async () => {
    const query = inputQuery.value.trim();
    if (!query) return;

    container.innerHTML = `
      <div style="margin: auto; text-align: center; display: flex; flex-direction: column; gap: 0.5rem;">
        <div class="loading-line" style="width: 200px; margin: auto;"></div>
        <span class="muted">로컬 지식 베이스 검색 및 답변 생성 중...</span>
      </div>
    `;

    try {
      const response = await fetch("/api/v1/ask-jayu", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query })
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();

      let formattedAnswer = escapeHtml(data.answer)
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/### (.*?)\n/g, "<h3 style='margin-top: 1rem; margin-bottom: 0.5rem;'>$1</h3>")
        .replace(/`([^`]+)`/g, "<code style='background: rgba(0,0,0,0.05); padding: 2px 4px; border-radius: 4px;'>$1</code>")
        .replace(/\n/g, "<br>");

      let sourcesHtml = "";
      if (data.sources && data.sources.length) {
        sourcesHtml = `
          <div style="margin-top: 1.5rem; border-top: 1px solid var(--border); padding-top: 0.8rem; font-size: 0.85rem;">
            <strong class="muted" style="display: block; margin-bottom: 0.4rem;">🔗 근거 출처 문서:</strong>
            ${data.sources.map(s => `<span class="status-badge" style="display: inline-block; margin-right: 0.4rem; background: var(--neutral-bg); border: 1px solid var(--border); padding: 2px 6px; border-radius: 4px; font-family: monospace;">${escapeHtml(s)}</span>`).join("")}
          </div>
        `;
      }

      container.innerHTML = `
        <div style="font-size: 0.95rem; line-height: 1.6; color: var(--text); overflow-y: auto;">
          ${formattedAnswer}
        </div>
        ${sourcesHtml}
      `;
    } catch (e) {
      container.innerHTML = `
        <span style="color: #ef4444; margin: auto; text-align: center;">답변 요청에 실패했습니다: ${escapeHtml(e.message)}</span>
      `;
    }
  });

  inputQuery.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      btnAsk.click();
    }
  });

  const sliderFx = document.querySelector("#slider-fx");
  const sliderNasdaq = document.querySelector("#slider-nasdaq");
  const valFx = document.querySelector("#val-fx");
  const valNasdaq = document.querySelector("#val-nasdaq");
  const impactText = document.querySelector("#stress-portfolio-impact");
  const riskVerdict = document.querySelector("#stress-risk-verdict");

  const updateStress = () => {
    const fx = parseFloat(sliderFx.value);
    const nasdaq = parseFloat(sliderNasdaq.value);
    
    valFx.textContent = (fx >= 0 ? "+" : "") + fx.toFixed(1) + "%";
    valNasdaq.textContent = (nasdaq >= 0 ? "+" : "") + nasdaq.toFixed(1) + "%";

    const totalAsset = 100000000;
    const foreignRatio = 0.60;
    
    const beta = 1.4; 
    const foreignImpact = foreignRatio * (nasdaq * beta / 100);
    const fxImpact = foreignRatio * (fx / 100) * (1 + nasdaq * beta / 100);
    const totalImpactPct = foreignImpact + fxImpact;
    const totalImpactKrw = totalAsset * totalImpactPct;

    const formattedImpactKrw = Math.round(totalImpactKrw).toLocaleString() + "원";
    const formattedImpactPct = (totalImpactPct >= 0 ? "+" : "") + (totalImpactPct * 100).toFixed(2) + "%";
    
    impactText.textContent = `${formattedImpactKrw} (${formattedImpactPct})`;
    if (totalImpactPct >= 0) {
      impactText.style.color = "#10b981";
    } else {
      impactText.style.color = "#ef4444";
    }

    if (totalImpactPct < -0.05) {
      riskVerdict.innerHTML = "⚠️ 위험 (평가 손실 5% 초과 감지)";
      riskVerdict.style.color = "#ef4444";
    } else if (totalImpactPct < -0.02) {
      riskVerdict.innerHTML = "🟡 주의 (손실 변동성 경보)";
      riskVerdict.style.color = "#f59e0b";
    } else {
      riskVerdict.innerHTML = "✅ 안전 (정상 범주)";
      riskVerdict.style.color = "#10b981";
    }
  };

  sliderFx.addEventListener("input", updateStress);
  sliderNasdaq.addEventListener("input", updateStress);
  
  updateStress();
}

// Bind collapsible navigation headers
document.querySelectorAll(".nav-group-header").forEach((header) => {
  header.addEventListener("click", () => {
    const group = header.closest(".nav-group");
    if (group) {
      group.classList.toggle("is-collapsed");
    }
  });
});

// Initialize active sidebar menu item from state on load
document.querySelectorAll(".nav-item").forEach((item) => {
  item.classList.toggle("is-active", item.dataset.page === state.page);
});
expandActiveNavGroup();

loadPage();
