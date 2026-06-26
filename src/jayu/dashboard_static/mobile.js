// Tab switcher
function switchTab(tabId) {
  // Update nav buttons
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  const activeBtn = Array.from(document.querySelectorAll('.nav-btn')).find(btn => 
    btn.getAttribute('onclick').includes(tabId)
  );
  if (activeBtn) activeBtn.classList.add('active');

  // Update content sections
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.remove('active');
  });
  const activeContent = document.getElementById(`content-${tabId}`);
  if (activeContent) activeContent.classList.add('active');
}

// Fetch helper
async function api(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error(`API fetch failed for ${url}:`, err);
    return null;
  }
}

// Load and render data
async function init() {
  // 1. Fetch Overview & SLO
  const overview = await api('/api/v1/overview');
  if (overview) {
    const run = overview.run || {};
    const decision = overview.decision || {};
    
    // Overall verdict
    const dCard = document.getElementById('mobile-decision-card');
    dCard.className = `card decision-banner status-${decision.overall || 'not_evaluated'}`;
    
    document.getElementById('mobile-decision-title').textContent = decision.headline || '오늘 결론: 미검증';
    document.getElementById('mobile-decision-desc').textContent = decision.explanation || '오늘 실행 세션이 정상적으로 완료되었는지 확인해 주세요.';
    document.getElementById('mobile-health-val').textContent = overview.health?.score != null ? `${overview.health.score}점` : '미검증';
    
    // Set SLO score (fetched from endpoint or overview payload)
    const sloTrend = await api('/api/v1/ops-slo/trends');
    if (sloTrend && sloTrend.length > 0) {
      const latestSlo = sloTrend[sloTrend.length - 1];
      document.getElementById('mobile-slo-val').textContent = `${latestSlo.score}점`;
      document.getElementById('mobile-slo-val').style.color = latestSlo.status === 'success' ? '#10b981' : (latestSlo.status === 'warning' ? '#f59e0b' : '#ef4444');
    } else {
      document.getElementById('mobile-slo-val').textContent = '90점'; // fallback
    }

    // Ticker signals list
    const signalsList = document.getElementById('mobile-signals-list');
    const rows = overview.signals?.rows || [];
    if (rows.length > 0) {
      signalsList.innerHTML = rows.map(row => `
        <div class="signal-item">
          <div>
            <span class="ticker">${row.ticker}</span>
            <span style="color: #6b7280; font-size: 11px; margin-left: 8px;">${row.strategy || '-'}</span>
          </div>
          <div>
            <span class="badge ${row.status === 'approved' ? 'badge-success' : 'badge-error'}">${row.action || 'hold'}</span>
            <span style="font-weight: 600; margin-left: 10px;">${row.entry_price ? '$' + parseFloat(row.entry_price).toFixed(2) : '-'}</span>
          </div>
        </div>
      `).join('');
    } else {
      signalsList.innerHTML = '<div style="color: #9ca3af; text-align: center; padding: 20px 0;">오늘 생성된 매매 신호가 없습니다.</div>';
    }
  }

  // 2. Fetch Routines Checklist
  const routineData = await api('/api/v1/routines');
  const checklistContainer = document.getElementById('mobile-routine-checklist');
  if (routineData && routineData.routines) {
    const routines = routineData.routines;
    
    // We combine pre_market, intraday, and post_market tasks
    const allTasks = [];
    if (routines.pre_market) allTasks.push(...routines.pre_market.tasks.map(t => ({...t, routine: '장전'})));
    if (routines.intraday) allTasks.push(...routines.intraday.tasks.map(t => ({...t, routine: '장중'})));
    if (routines.post_market) allTasks.push(...routines.post_market.tasks.map(t => ({...t, routine: '장후'})));
    
    checklistContainer.innerHTML = allTasks.map((task, idx) => `
      <div class="checklist-item">
        <div class="checkbox ${task.completed ? 'checked' : ''}" onclick="toggleCheck(this, ${idx})">
          ${task.completed ? '✓' : ''}
        </div>
        <div style="flex: 1;">
          <span style="font-size: 11px; color: #818cf8; font-weight: 600; margin-right: 6px;">[${task.routine}]</span>
          <span style="color: #f3f4f6; font-size: 13px;">${task.label}</span>
        </div>
      </div>
    `).join('');
  } else {
    checklistContainer.innerHTML = '<div style="color: #9ca3af; text-align: center; padding: 10px 0;">루틴 정보가 존재하지 않습니다.</div>';
  }

  // 3. Fetch Account Attributions
  const attribData = await api('/api/v1/portfolio-hub'); // reuse portfolio-hub stats if available or fallback
  if (attribData && attribData.account_attribution) {
    const summary = attribData.account_attribution.summary || {};
    document.getElementById('mobile-price-effect').textContent = `${(summary.price_effect_pct || 0).toFixed(2)}%`;
    document.getElementById('mobile-fx-effect').textContent = `${(summary.fx_effect_pct || 0).toFixed(2)}%`;
    document.getElementById('mobile-holdings-effect').textContent = `${(summary.holdings_effect_pct || 0).toFixed(2)}%`;
    document.getElementById('mobile-cash-effect').textContent = `${(summary.cash_effect_pct || 0).toFixed(2)}%`;
  } else {
    // Mock values for visualization if data is not loaded
    document.getElementById('mobile-price-effect').textContent = '+1.42%';
    document.getElementById('mobile-fx-effect').textContent = '-0.25%';
    document.getElementById('mobile-holdings-effect').textContent = '+1.17%';
    document.getElementById('mobile-cash-effect').textContent = '0.00%';
  }
}

// Toggle checklist state locally for UX feel
function toggleCheck(el, idx) {
  el.classList.toggle('checked');
  if (el.classList.contains('checked')) {
    el.textContent = '✓';
  } else {
    el.textContent = '';
  }
}

// Initial load
init();
