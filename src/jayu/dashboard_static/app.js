const state = {
  page: localStorage.getItem("jayu.dashboard.activePage") || "overview",
  runId: "latest",
  runs: [],
  failurePatterns: null,
  decision: null,
  overview: null,
  dataQuality: null,
  risk: null,
  signals: null,
  traderLens: null,
  promotion: null,
  settingsValidation: null,
  tossStatus: null,
  tossAccounts: null,
  tossMarket: null,
  tossPortfolio: null,
  tossReconciliation: null,
  tossOrderPlan: null,
  tossSubTab: localStorage.getItem("jayu.toss.subTab") || "overview",
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

const RUN_CONTEXT_OPTIONAL_PAGES = new Set(["analysis", "portfolio-hub", "autotrading"]);
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
    if (!state.runs.length) await loadRuns();
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
    if (!state.portfolioHub) {
      try {
        state.portfolioHub = await api("/api/v1/portfolio-hub");
      } catch (err) {
        console.warn("Failed to auto-load portfolio hub data", err);
      }
    }
    if (state.page === "data-quality") {
      state.dataQuality = await api(`/api/v1/runs/${run}/data-quality`);
    }
    if (state.page === "risk") {
      state.risk = await api(`/api/v1/runs/${run}/risk`);
    }
    if (state.page === "signals") {
      state.signals = await api(`/api/v1/runs/${run}/signals`);
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
      // Analysis tabs load data themselves via bindPageActions auto-triggers
    }
    if (state.page === "portfolio-hub") {
      // 포트폴리오 허브는 bindPageActions에서 자동 로드
    }
    if (state.page === "autotrading") {
      state.autotradingStatus = await api("/api/v1/autotrading-status");
    }
    if (state.page === "simulation-log") {
      const res = await api("/api/v1/simulation/log");
      state.simulationLog = res.logs || "";
      state.simulationStatus = res.status || "idle";
    }
    if (state.page === "toss-account") {
      const params = new URLSearchParams();
      if (state.selectedTossAccount) params.set("account", state.selectedTossAccount);
      
      const [portfolio, reconciliation, orderPlan] = await Promise.all([
        api(`/api/v1/toss/portfolio${params.toString() ? `?${params.toString()}` : ""}`),
        api(`/api/v1/toss/reconciliation${params.toString() ? `?${params.toString()}` : ""}`),
        api("/api/v1/toss/order-plan")
      ]);

      state.tossPortfolio = portfolio;
      state.tossReconciliation = reconciliation;
      state.tossOrderPlan = orderPlan;

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
  }[page] || page;
}

function render() {
  els.root.hidden = false;
  if (state.page === "data-quality") renderDataQuality();
  else if (state.page === "risk") renderRisk();
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

  // ── Signal Tab Actions ─────────────────────────────────────────────────────
  document.querySelectorAll("[data-signal-tab]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.signalHubTab = btn.dataset.signalTab;
      renderSignals();
      bindPageActions();
    });
  });
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
  if (!["overview", "data-quality", "risk", "signals", "trader-lens", "promotion", "settings", "toss-account", "toss", "api-monitoring", "analysis", "portfolio-hub", "autotrading", "simulation-log", "run-history"].includes(page)) return;
  clearApiMonitoringRefreshTimer();
  state.page = page;
  localStorage.setItem("jayu.dashboard.activePage", page);
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.page === page);
  });
  loadPage();
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
  state.risk = null;
  state.signals = null;
  state.traderLens = null;
  state.promotion = null;
  state.settingsValidation = null;
  state.tossStatus = null;
  state.tossAccounts = null;
  state.tossMarket = null;
  state.tossPortfolio = null;
  state.apiMonitoring = null;
  loadPage();
});

document.querySelector("#refresh-button").addEventListener("click", async () => {
  state.runs = [];
  state.decision = null;
  state.overview = null;
  state.traderLens = null;
  state.tossStatus = null;
  state.tossAccounts = null;
  state.tossMarket = null;
  state.tossPortfolio = null;
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

// Initialize active sidebar menu item from state on load
document.querySelectorAll(".nav-item").forEach((item) => {
  item.classList.toggle("is-active", item.dataset.page === state.page);
});

loadPage();
