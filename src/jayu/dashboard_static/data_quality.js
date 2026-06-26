function renderDataQuality() {
  const data = state.dataQuality;
  const summary = data.summary;
  const gates = data.gates || {};
  
  els.root.innerHTML = `
    <div class="page-heading">
      <div>
        <h1>데이터 품질 & 계보</h1>
        <p>수집된 OHLCV 가격 데이터의 유효성을 검증하고, 여러 제공자의 데이터가 일치하는지 비교 검사한 결과입니다.</p>
      </div>
      ${statusBadge(summary.status)}
    </div>
    ${renderDataSourceNote("data-quality")}
    <section class="decision-grid" aria-label="오늘 결론">
      <article class="decision-card status-${statusClass(summary.status)}">
        <div class="decision-eyebrow">${statusBadge(summary.status)} <span>수집 및 정합성 검증</span></div>
        <h2>가격 교차 검증 결과</h2>
        <p>${escapeHtml(dataQualityHeadline(summary))}</p>
        <div class="decision-meta">
          <span>성공 ${summary.success_source_count} / 실패 ${summary.failed_source_count}</span>
          <span>불일치 ${summary.disagreement_count}건</span>
        </div>
      </article>
    </section>
    ${renderDataLineageGraph(data.lineage)}
    <section class="metric-grid" aria-label="데이터 품질 핵심 메트릭">
      ${metricCard("검증 성공률", formatPercent(summary.success_rate), summary.status, `전체 ${summary.total_source_count}개 소스`)}
      ${metricCard("Provider 수", summary.total_providers || 0, "success", `수집 성공 ${summary.success_providers || 0}`)}
      ${metricCard("불일치", `${summary.disagreement_count || 0}건`, summary.disagreement_count ? "warning" : "success", "허용 오차 초과 건수")}
      ${metricCard("차단 ticker", (summary.blocked_tickers || []).length, summary.blocked_tickers?.length ? "blocked" : "success", summary.blocked_tickers?.join(", ") || "없음")}
    </section>
    ${renderMetricDictionaryStrip(data.metric_dictionary?.["data-quality"], "데이터 품질 지표 쉬운 설명")}
    <section class="panel">
      <div class="panel-header">
        <div><h2>수집 상태 상세 (Provider Sources)</h2><p>각 제공자(Yahoo Finance, Tiingo, Massive)로부터 종목별 데이터를 수집한 결과입니다.</p></div>
        <span class="muted">${(data.sources || []).length}건</span>
      </div>
      ${renderSourcesTable(data.sources)}
      ${renderSourceCaption("data_sources.json in latest run")}
    </section>
    <section class="panel">
      <div class="panel-header">
        <div><h2>교차 검증 불일치 상세 (Disagreements)</h2><p>동일한 종목의 특정 날짜 OHLCV 데이터가 제공자 간에 한도(Threshold)를 초과하여 차이가 난 내역입니다.</p></div>
        <span class="muted">${(data.disagreements || []).length}건</span>
      </div>
      ${renderMismatchTable(data.disagreements)}
      ${renderSourceCaption("provider_disagreement_report.json in latest run")}
    </section>
    <div id="provider-trend-container" style="margin-top:20px;">
      <div style="text-align:center; padding: 20px; color:#cbd5e1; font-size:12px;">⏳ 제공자 신뢰도 추세 분석을 로드하는 중...</div>
    </div>
  `;
  
  setTimeout(loadProviderTrend, 50);
}

function renderDataLineageGraph(lineage) {
  const data = lineage || {};
  const nodes = data.nodes || [];
  const edges = data.edges || [];
  const source = data.source || "data_lineage.json";
  if (!nodes.length) return "";
  
  // Group nodes by category to show layers
  const providers = nodes.filter(n => n.category === "provider");
  const rawData = nodes.filter(n => n.category === "raw_data");
  const processed = nodes.filter(n => n.category === "processed");
  const signals = nodes.filter(n => n.category === "signal");
  const gates = nodes.filter(n => n.category === "gate" || n.category === "process");
  
  return `
    <section class="data-lineage-graph data-lineage-panel" aria-label="데이터 계보 흐름도">
      <div class="data-lineage-graph-head">
        <strong>데이터 계보 흐름도 (Data Lineage Graph)</strong>
        <span>수집 소스부터 최종 판단 게이트까지의 데이터 연결고리입니다.</span>
      </div>
      <div class="lineage-layers">
        <div class="lineage-layer">
          <div class="layer-title">1. 데이터 제공처 (Providers)</div>
          <div class="layer-nodes">${providers.map(n => renderDataLineageChip(n, source)).join("")}</div>
        </div>
        <div class="lineage-layer">
          <div class="layer-title">2. 수집 원천 파일 (Raw Data)</div>
          <div class="layer-nodes">${rawData.map(n => renderDataLineageChip(n, source)).join("")}</div>
        </div>
        <div class="lineage-layer">
          <div class="layer-title">3. 가공 및 정합성 검증 (Processed)</div>
          <div class="layer-nodes">${processed.map(n => renderDataLineageChip(n, source)).join("")}</div>
        </div>
        <div class="lineage-layer">
          <div class="layer-title">4. 투자 신호 생성 (Signals)</div>
          <div class="layer-nodes">${signals.map(n => renderDataLineageChip(n, source)).join("")}</div>
        </div>
        <div class="lineage-layer">
          <div class="layer-title">5. 리스크 및 안전 게이트 (Gates)</div>
          <div class="layer-nodes">${gates.map(n => renderDataLineageChip(n, source)).join("")}</div>
        </div>
      </div>
      ${renderSourceCaption(source)}
    </section>
  `;
}

function renderDataLineageChip(node, fallbackSource) {
  const meta = [
    node.path ? `파일: ${node.path}` : "",
    node.sizeBytes ? `크기: ${formatNumber(node.sizeBytes, 0)}B` : "",
    node.rowCount != null ? `행 수: ${formatNumber(node.rowCount, 0)}` : "",
    node.lastModified ? `갱신: ${formatDate(node.lastModified)}` : "",
  ].filter(Boolean);
  
  return `
    <div class="lineage-node status-${statusClass(node.status || "not_evaluated")}" 
      title="${escapeHtml(meta.join("\n") || node.label || node.id)}">
      <strong>${escapeHtml(node.label || node.id)}</strong>
      ${node.status ? statusBadge(node.status) : ""}
      ${renderSourceLabel(node.source || fallbackSource)}
    </div>
  `;
}

function renderSourcesTable(rows) {
  if (!rows?.length) return emptyTable("Provider 수집 기록이 없습니다.", "비교 대상이 없으므로 검증 성공으로 간주하지 않습니다.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>Provider</th><th>종목</th><th>상태</th><th class="numeric">행 수</th><th>첫 날짜</th><th>마지막 날짜</th><th>Hash</th><th>오류</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td>${escapeHtml(row.provider || "-")}</td>
          <td class="ticker-cell">${renderTicker(row.ticker || row.symbol)}</td>
          <td>${statusBadge(row.status === "success" ? "success" : "failed")}</td>
          <td class="numeric">${formatNumber(row.rows, 0)}</td>
          <td class="nowrap">${escapeHtml(row.first_date || "-")}</td>
          <td class="nowrap">${escapeHtml(row.last_date || "-")}</td>
          <td class="code" title="${escapeHtml(row.hash || "")}">${escapeHtml(shortHash(row.hash))}</td>
          <td>${escapeHtml(row.error || "-")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

function renderMismatchTable(rows) {
  if (!rows?.length) return emptyTable("임계값 초과 불일치가 없습니다.", "Provider 비교가 실행되지 않았다면 상단 상태는 미검증으로 유지됩니다.");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>종목</th><th>날짜</th><th>필드</th><th>Providers</th><th>값 / 누락</th><th class="numeric">차이</th><th class="numeric">한도</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td class="ticker-cell">${renderTicker(row.ticker)}</td>
          <td class="nowrap">${escapeHtml(row.date || "-")}</td>
          <td>${escapeHtml(row.field || "-")}</td>
          <td>${escapeHtml([row.baseline, row.candidate].filter(Boolean).join(" / ") || "-")}</td>
          <td class="code">${escapeHtml(row.kind === "date" ? `missing: ${(row.missing_in || []).join(", ")}` : Object.entries(row.values || {}).map(([key, value]) => `${key}=${value}`).join(" / "))}</td>
          <td class="numeric">${row.relative_delta == null ? "-" : formatPercent(row.relative_delta, 3)}</td>
          <td class="numeric">${row.threshold == null ? "-" : formatPercent(row.threshold, 3)}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}

async function loadProviderTrend() {
  const container = document.querySelector("#provider-trend-container");
  if (!container) return;
  try {
    const trend = await api("/api/v1/provider-trend?limit=10");
    container.innerHTML = renderProviderTrendTable(trend);
  } catch (err) {
    container.innerHTML = `
      <section class="panel">
        <div class="panel-header"><h2>제공자 신뢰도 추세 분석 (최근 10회)</h2></div>
        <div style="color:#ef4444; font-size:12px; padding: 20px;">추세 데이터를 불러올 수 없습니다: ${err.message}</div>
      </section>
    `;
  }
}

function renderProviderTrendTable(trend) {
  const providers = Object.values(trend.providers || {});
  
  let rowsHtml = "";
  if (!providers.length) {
    rowsHtml = `
      <tr>
        <td colspan="7" style="text-align:center; padding: 20px; color:#64748b;">
          누적된 데이터 제공자 추세 기록이 없습니다.
        </td>
      </tr>
    `;
  } else {
    rowsHtml = providers.map(p => {
      const isExcellent = p.success_rate === 100;
      const isGood = p.success_rate >= 95;
      
      let statusBadge = "";
      if (isExcellent) {
        statusBadge = `<span style="background:#d1fae5; color:#065f46; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:bold;">우수</span>`;
      } else if (isGood) {
        statusBadge = `<span style="background:#e0f2fe; color:#0369a1; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:bold;">안정</span>`;
      } else {
        statusBadge = `<span style="background:#fee2e2; color:#991b1b; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:bold;">주의</span>`;
      }
      
      // 성공률 프로그레스 바 배경색 결정
      const barColor = isExcellent ? "#10b981" : isGood ? "#3b82f6" : "#f59e0b";
      
      const blockedList = p.blocked_tickers.join(", ") || "없음";

      return `
        <tr>
          <td style="font-weight:bold; color:#1e293b;">${escapeHtml(String(p.provider).toUpperCase())}</td>
          <td style="text-align:center;">${p.total_attempts}회</td>
          <td style="text-align:center;">${p.success_count}회</td>
          <td style="text-align:center;">${p.failure_count}회</td>
          <td style="vertical-align:middle;">
            <div style="display:flex; align-items:center; gap:8px;">
              <div style="flex:1; background:#e2e8f0; height:8px; border-radius:4px; overflow:hidden; min-width:80px;">
                <div style="background:${barColor}; width:${p.success_rate}%; height:100%;"></div>
              </div>
              <span style="font-weight:bold; min-width:35px; text-align:right;">${p.success_rate}%</span>
            </div>
          </td>
          <td style="text-align:center; color:${p.disagreement_count > 0 ? '#ef4444' : '#64748b'}; font-weight:${p.disagreement_count > 0 ? 'bold' : 'normal'};">
            ${p.disagreement_count}회
          </td>
          <td style="color:${p.blocked_ticker_count > 0 ? '#ef4444' : '#64748b'}; font-weight:${p.blocked_ticker_count > 0 ? 'bold' : 'normal'};" title="${escapeHtml(blockedList)}">
            ${p.blocked_ticker_count}개 (${blockedList})
          </td>
          <td style="text-align:center;">${statusBadge}</td>
        </tr>
      `;
    }).join("");
  }

  return `
    <section class="panel">
      <div class="panel-header" style="background:#f8fafc; border-bottom:1px solid #e2e8f0;">
        <div>
          <h2 style="font-size:14px; margin:0;">제공자 신뢰도 추세 분석 (최근 ${trend.runs_analyzed || 0}회 실행 기준)</h2>
          <p style="margin:2px 0 0 0; font-size:11px; color:#64748b;">각 가격 제공사(Yahoo, Tiingo, Massive)의 역사적 수집 성공률, 불일치율 및 실제 매매 차단 영향 추세를 추적합니다.</p>
        </div>
      </div>
      <div class="table-wrap">
        <table class="table" style="width:100%; border-collapse: collapse; font-size:13px; margin:0;">
          <thead>
            <tr style="background:#f8fafc; border-bottom:1px solid #cbd5e1;">
              <th style="padding: 8px; text-align:left; color:#475569;">제공사 (Provider)</th>
              <th style="padding: 8px; text-align:center; color:#475569; width:10%;">수집 시도</th>
              <th style="padding: 8px; text-align:center; color:#475569; width:10%;">수집 성공</th>
              <th style="padding: 8px; text-align:center; color:#475569; width:10%;">수집 실패</th>
              <th style="padding: 8px; text-align:left; color:#475569; width:25%;">수집 성공률</th>
              <th style="padding: 8px; text-align:center; color:#475569; width:10%;">교차 불일치</th>
              <th style="padding: 8px; text-align:left; color:#475569; width:20%;">차단 영향 종목</th>
              <th style="padding: 8px; text-align:center; color:#475569; width:10%;">종합 상태</th>
            </tr>
          </thead>
          <tbody style="color:#334155;">
            ${rowsHtml}
          </tbody>
        </table>
      </div>
    </section>
  `;
}
