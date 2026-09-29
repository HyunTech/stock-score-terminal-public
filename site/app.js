const state = {
  stocks: [],
  filtered: [],
  selectedId: null,
  selectedRecommendationId: null,
  viewSize: 100,
  payload: null,
  recommendations: [],
  research: null,
};

const els = {
  generatedAt: document.getElementById("generatedAt"),
  coverage: document.getElementById("coverage"),
  universe: document.getElementById("universe"),
  searchInput: document.getElementById("searchInput"),
  marketFilter: document.getElementById("marketFilter"),
  sortSelect: document.getElementById("sortSelect"),
  minScore: document.getElementById("minScore"),
  minScoreLabel: document.getElementById("minScoreLabel"),
  resultCount: document.getElementById("resultCount"),
  rankBody: document.getElementById("rankBody"),
  krTopBody: document.getElementById("krTopBody"),
  krTopCount: document.getElementById("krTopCount"),
  researchSummary: document.getElementById("researchSummary"),
  researchDate: document.getElementById("researchDate"),
  researchIssueCount: document.getElementById("researchIssueCount"),
  researchStockCount: document.getElementById("researchStockCount"),
  researchDocCount: document.getElementById("researchDocCount"),
  researchIssues: document.getElementById("researchIssues"),
  researchStocks: document.getElementById("researchStocks"),
  researchDocs: document.getElementById("researchDocs"),
  askForm: document.getElementById("askForm"),
  askInput: document.getElementById("askInput"),
  askButton: document.getElementById("askButton"),
  askAnswer: document.getElementById("askAnswer"),
  recommendationSelect: document.getElementById("recommendationSelect"),
  recommendationMeta: document.getElementById("recommendationMeta"),
  recommendationCount: document.getElementById("recommendationCount"),
  recommendationBody: document.getElementById("recommendationBody"),
  detailMarket: document.getElementById("detailMarket"),
  detailSymbol: document.getElementById("detailSymbol"),
  detailName: document.getElementById("detailName"),
  detailScore: document.getElementById("detailScore"),
  sparkCanvas: document.getElementById("sparkCanvas"),
  lastClose: document.getElementById("lastClose"),
  lastDate: document.getElementById("lastDate"),
  rowCount: document.getElementById("rowCount"),
  source: document.getElementById("source"),
  componentBars: document.getElementById("componentBars"),
  modelWeights: document.getElementById("modelWeights"),
  r1m: document.getElementById("r1m"),
  r3m: document.getElementById("r3m"),
  r6m: document.getElementById("r6m"),
  r12m: document.getElementById("r12m"),
};

const sorters = {
  score: (row) => row.score,
  ret12m: (row) => row.returns["12m"] ?? -9999,
  ret6m: (row) => row.returns["6m"] ?? -9999,
  stability: (row) => row.components.stability,
  liquidity: (row) => row.components.liquidity,
  drawdown: (row) => row.components.drawdown,
};

const numberFormats = new Map();
const compactFormat = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 2 });

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (!numberFormats.has(digits)) {
    numberFormats.set(digits, new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }));
  }
  return numberFormats.get(digits).format(Number(value));
}

function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const cls = value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
  const sign = value > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${fmt(value)}%</span>`;
}

function compact(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return compactFormat.format(value);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function dateLabel(value) {
  const text = String(value || "");
  if (text.length !== 8) return text || "-";
  return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}`;
}

function populateMarkets() {
  const current = els.marketFilter.value;
  const markets = [...new Set(state.stocks.map((row) => row.market || row.exchange).filter(Boolean))].sort();
  els.marketFilter.innerHTML = `<option value="ALL">All</option>${markets
    .map((market) => `<option value="${escapeHtml(market)}">${escapeHtml(market)}</option>`)
    .join("")}`;
  if (markets.includes(current)) els.marketFilter.value = current;
}

function applyFilters() {
  const query = els.searchInput.value.trim().toLowerCase();
  const market = els.marketFilter.value;
  const minScore = Number(els.minScore.value);
  els.minScoreLabel.textContent = minScore;

  const sorter = sorters[els.sortSelect.value] || sorters.score;
  state.filtered = state.stocks
    .filter((row) => {
      if (row.score < minScore) return false;
      if (market !== "ALL" && row.market !== market && row.exchange !== market) return false;
      if (!query) return true;
      return `${row.symbol} ${row.displaySymbol} ${row.name} ${row.market}`.toLowerCase().includes(query);
    })
    .sort((a, b) => sorter(b) - sorter(a));

  renderTable();
  if (!state.filtered.some((row) => row.id === state.selectedId)) selectStock(state.filtered[0]);
}

function renderTable() {
  const rows = state.filtered.slice(0, state.viewSize);
  els.resultCount.textContent = `${state.filtered.length.toLocaleString()} matches, showing ${rows.length.toLocaleString()}`;
  els.rankBody.innerHTML = rows
    .map(
      (row) => `
      <tr data-id="${escapeHtml(row.id)}" class="${row.id === state.selectedId ? "selected" : ""}">
        <td>${row.rank}</td>
        <td><span class="score-pill">${fmt(row.score, 1)}</span></td>
        <td><div class="symbol-cell"><strong>${escapeHtml(row.displaySymbol)}</strong><span>${escapeHtml(row.name)}</span></div></td>
        <td>${escapeHtml(row.country)} / ${escapeHtml(row.market || row.exchange || "-")}</td>
        <td>${fmtPct(row.returns["1m"])}</td>
        <td>${fmtPct(row.returns["3m"])}</td>
        <td>${fmtPct(row.returns["6m"])}</td>
        <td>${fmtPct(row.returns["12m"])}</td>
        <td>${fmt(row.metrics.volatility)}%</td>
        <td>${fmtPct(row.metrics.maxDrawdown)}</td>
        <td>${compact(row.metrics.liquidity)}</td>
      </tr>`
    )
    .join("");
}

function topRows(country) {
  return state.stocks.filter((row) => row.country === country).sort((a, b) => b.score - a.score).slice(0, 100);
}

function renderTopRows(target, rows) {
  target.innerHTML = rows
    .map(
      (row, index) => `
      <tr data-id="${escapeHtml(row.id)}" class="${row.id === state.selectedId ? "selected" : ""}">
        <td>${index + 1}</td>
        <td><span class="score-pill">${fmt(row.score, 1)}</span></td>
        <td><div class="symbol-cell"><strong>${escapeHtml(row.displaySymbol)}</strong><span>${escapeHtml(row.name)}</span></div></td>
        <td>${fmt(row.lastClose, 4)}</td>
        <td>${fmtPct(row.returns["3m"])}</td>
        <td>${fmtPct(row.returns["12m"])}</td>
      </tr>`
    )
    .join("");
}

function renderTopLists() {
  const krRows = topRows("KR");
  els.krTopCount.textContent = `${krRows.length} names`;
  renderTopRows(els.krTopBody, krRows);
}

function crossLabel(date, daysAgo) {
  const dayText = Number(daysAgo) === 0 ? "오늘" : `${daysAgo}일 전`;
  return `${dateLabel(date)} <small>${dayText}</small>`;
}

function recommendationSignal(row, fallbackDate, fallbackDaysAgo) {
  if (row) return escapeHtml(row);
  if (fallbackDate !== undefined) return crossLabel(fallbackDate, fallbackDaysAgo);
  return "-";
}

function populateRecommendations() {
  state.recommendations = state.payload?.recommendations || [];
  if (!els.recommendationSelect) return;
  const technicalThemes = state.recommendations.filter((item) => !String(item.id || "").startsWith("kr_bci_"));
  const bciThemes = state.recommendations.filter((item) => String(item.id || "").startsWith("kr_bci_"));
  const renderOptions = (items) => items.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.title)}</option>`).join("");
  els.recommendationSelect.innerHTML = [
    technicalThemes.length ? `<optgroup label="기술적 테마">${renderOptions(technicalThemes)}</optgroup>` : "",
    bciThemes.length ? `<optgroup label="BCI 공시/뉴스 테마">${renderOptions(bciThemes)}</optgroup>` : "",
  ].join("");
  state.selectedRecommendationId = state.recommendations[0]?.id || null;
  if (state.selectedRecommendationId) els.recommendationSelect.value = state.selectedRecommendationId;
  renderRecommendations();
}

function renderRecommendations() {
  if (!els.recommendationBody) return;
  const recommendation = state.recommendations.find((item) => item.id === state.selectedRecommendationId) || state.recommendations[0];
  if (!recommendation) {
    els.recommendationMeta.textContent = "No recommendation themes available.";
    els.recommendationCount.textContent = "0 names";
    els.recommendationBody.innerHTML = "";
    return;
  }

  const rows = recommendation.items || [];
  const settings = recommendation.settings || {};
  const lookbackText = settings.lookbackTradingDays ? ` (${settings.lookbackTradingDays}거래일)` : "";
  els.recommendationMeta.textContent = `${recommendation.description || ""}${lookbackText}`;
  els.recommendationCount.textContent = `${rows.length} names`;
  if (!rows.length) {
    els.recommendationBody.innerHTML = `<tr><td colspan="8" class="empty-row">아직 조건을 만족한 종목이 없습니다. BCI 테마는 DART/Naver API 캐시가 있어야 채워집니다.</td></tr>`;
    return;
  }
  els.recommendationBody.innerHTML = rows
    .map(
      (row) => `
      <tr data-id="${escapeHtml(row.id)}" class="${row.id === state.selectedId ? "selected" : ""}">
        <td>${row.recommendationRank}</td>
        <td><span class="score-pill signal-score">${fmt(row.recommendationScore, 1)}</span></td>
        <td><div class="symbol-cell"><strong>${escapeHtml(row.displaySymbol || row.symbol)}</strong><span>${escapeHtml(row.name)}</span></div></td>
        <td>${fmt(row.lastClose, 4)}</td>
        <td>${recommendationSignal(row.primarySignal, row.macdCrossDate, row.macdDaysAgo)}</td>
        <td>${recommendationSignal(row.secondarySignal, row.rsiCrossDate, row.rsiDaysAgo)}</td>
        <td>${escapeHtml(row.metricLabel || `${fmt(row.rsi, 2)} / ${fmt(row.rsiSignal, 2)}`)}</td>
        <td>${fmt(row.baseScore, 1)}</td>
      </tr>`
    )
    .join("");
}

function renderResearch() {
  const research = state.research || {};
  const issues = research.issues || [];
  const stocks = research.stocks || [];
  const docs = research.documents || [];

  els.researchDate.textContent = research.date || "-";
  els.researchSummary.textContent = research.marketSummary || "아직 수집된 리서치 자료가 없습니다.";
  els.researchIssueCount.textContent = `${issues.length}`;
  els.researchStockCount.textContent = `${stocks.length}`;
  els.researchDocCount.textContent = `${docs.length}`;
  els.researchIssues.innerHTML = issues.length
    ? issues
        .slice(0, 6)
        .map(
          (item) => `
        <article class="issue-item">
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(item.summary)}</span>
          <small>${escapeHtml((item.relatedTickers || []).join(", ") || "관련 종목 없음")}</small>
        </article>`
        )
        .join("")
    : `<div class="empty-box">오늘 감지된 핵심 이슈가 없습니다.</div>`;

  els.researchStocks.innerHTML = stocks.length
    ? stocks
        .slice(0, 10)
        .map(
          (item) => `
        <button type="button" class="research-stock" data-symbol="${escapeHtml(item.ticker)}">
          <span><strong>${escapeHtml(item.ticker)}</strong> ${escapeHtml(item.name)}</span>
          <small>언급 ${fmt(item.mentions || 0, 0)}회 · ${escapeHtml(item.sentiment)} · ${escapeHtml((item.themes || []).join(", ") || "theme n/a")}</small>
        </button>`
        )
        .join("")
    : `<div class="empty-box">언급 종목이 없습니다.</div>`;

  els.researchDocs.innerHTML = docs.length
    ? docs
        .slice(0, 8)
        .map((item) => {
          const title = escapeHtml(item.title || item.type || "자료");
          const preview = escapeHtml(item.preview || "");
          const type = escapeHtml(item.type || "source");
          const url = item.url ? escapeHtml(item.url) : "";
          return `<article class="doc-item"><strong>${url ? `<a href="${url}" target="_blank" rel="noreferrer">${title}</a>` : title}</strong><span>${preview}</span><small>${type}</small></article>`;
        })
        .join("")
    : `<div class="empty-box">수집된 자료가 없습니다.</div>`;
}

function renderBars(target, values, mode = "score") {
  target.innerHTML = Object.entries(values)
    .map(([name, value]) => {
      const pct = Math.max(0, Math.min(100, Number(value) || 0));
      return `<div class="bar-row"><span>${escapeHtml(labelize(name))}</span><div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div><strong>${mode === "weight" ? `${fmt(pct)}%` : fmt(pct, 1)}</strong></div>`;
    })
    .join("");
}

function labelize(value) {
  return value.replace(/([A-Z])/g, " $1").replace(/^./, (char) => char.toUpperCase());
}

function drawSpark(row) {
  const canvas = els.sparkCanvas;
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.max(320, Math.floor(rect.width * scale));
  canvas.height = Math.max(180, Math.floor(rect.height * scale));

  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  const width = canvas.width / scale;
  const height = canvas.height / scale;
  ctx.clearRect(0, 0, width, height);

  const values = row?.spark || [];
  if (values.length < 2) return;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = 18;
  const span = max - min || 1;

  ctx.strokeStyle = "#263138";
  ctx.lineWidth = 1;
  for (let i = 1; i <= 3; i += 1) {
    const y = pad + ((height - pad * 2) * i) / 4;
    ctx.beginPath();
    ctx.moveTo(pad, y);
    ctx.lineTo(width - pad, y);
    ctx.stroke();
  }

  ctx.strokeStyle = values[values.length - 1] >= values[0] ? "#46d68c" : "#ff6f6f";
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = pad + (index / (values.length - 1)) * (width - pad * 2);
    const y = height - pad - ((value - min) / span) * (height - pad * 2);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = "#99a6a3";
  ctx.font = "11px Segoe UI, Arial";
  ctx.fillText(fmt(max, 2), pad, 14);
  ctx.fillText(fmt(min, 2), pad, height - 6);
}

function selectStock(row) {
  if (!row) return;
  state.selectedId = row.id;
  els.detailMarket.textContent = `${row.country} / ${row.market || row.exchange || "-"}`;
  els.detailSymbol.textContent = row.displaySymbol;
  els.detailName.textContent = row.name;
  els.detailScore.textContent = fmt(row.score, 1);
  els.lastClose.textContent = fmt(row.lastClose, 4);
  els.lastDate.textContent = dateLabel(row.lastDate);
  els.rowCount.textContent = fmt(row.rows, 0);
  els.source.textContent = row.source || "-";
  els.r1m.innerHTML = fmtPct(row.returns["1m"]);
  els.r3m.innerHTML = fmtPct(row.returns["3m"]);
  els.r6m.innerHTML = fmtPct(row.returns["6m"]);
  els.r12m.innerHTML = fmtPct(row.returns["12m"]);
  renderBars(els.componentBars, row.components);
  drawSpark(row);
  document.querySelectorAll("tr[data-id]").forEach((element) => {
    element.classList.toggle("selected", element.dataset.id === state.selectedId);
  });
}

function renderModel() {
  const weights = state.payload?.model?.weights || {};
  const pctWeights = Object.fromEntries(Object.entries(weights).map(([key, value]) => [key, Number(value) * 100]));
  renderBars(els.modelWeights, pctWeights, "weight");
}

function localResearchAnswer(question) {
  const research = state.research || {};
  const issues = research.issues || [];
  const stocks = research.stocks || [];
  const docs = research.documents || [];
  const query = question.toLowerCase();

  if (!issues.length && !stocks.length && !docs.length) {
    return "아직 수집된 리서치 자료가 없습니다. 일일 업데이트가 리포트나 텔레그램 자료를 수집한 뒤 답변 근거가 채워집니다.";
  }

  const stockMatch = stocks.find((item) => {
    const text = `${item.ticker || ""} ${item.name || ""}`.toLowerCase();
    return query.includes(String(item.ticker || "").toLowerCase()) || (item.name && query.includes(String(item.name).toLowerCase())) || text.includes(query);
  });
  if (stockMatch) {
    const sources = (stockMatch.sources || []).slice(0, 3).map((item) => item.title).filter(Boolean).join(", ");
    return `${stockMatch.ticker} ${stockMatch.name}는 현재 리서치에서 ${stockMatch.mentions || 0}회 언급됐습니다. 감성은 ${stockMatch.sentiment || "neutral"}이고 관련 테마는 ${(stockMatch.themes || []).join(", ") || "없음"}입니다.${sources ? ` 근거 자료는 ${sources}입니다.` : ""} 이 답변은 저장된 리서치 데이터만 요약한 것이며 투자 조언은 아닙니다.`;
  }

  if (query.includes("이슈") || query.includes("테마") || query.includes("섹터")) {
    const issueText = issues
      .slice(0, 5)
      .map((item) => `${item.title}(${item.mentionCount || 0}건)`)
      .join(", ");
    return `현재 리서치에서 많이 잡힌 이슈는 ${issueText || "없음"}입니다. 관련 종목은 각 이슈 카드의 종목코드를 기준으로 확인하면 됩니다.`;
  }

  if (query.includes("리포트") || query.includes("자료") || query.includes("문서")) {
    const docText = docs
      .slice(0, 5)
      .map((item) => item.title)
      .filter(Boolean)
      .join(", ");
    return `현재 반영된 주요 리포트는 ${docText || "없음"}입니다. 원문은 자료 목록의 링크에서 확인할 수 있고, 사이트에는 원문 전문이 아니라 요약과 출처만 표시합니다.`;
  }

  const topStocks = stocks
    .slice(0, 5)
    .map((item) => `${item.ticker} ${item.name}`)
    .join(", ");
  const topIssues = issues
    .slice(0, 4)
    .map((item) => item.title)
    .join(", ");
  return `현재 저장된 리서치 기준 상위 언급 종목은 ${topStocks || "없음"}입니다. 주요 이슈는 ${topIssues || "없음"}입니다. 합성 예제 데이터를 요약한 답변이며 실제 시장 정보가 아닙니다.`;
}

function askResearch(question) {
  els.askAnswer.textContent = question.length > 2000
    ? "질문은 2,000자 이하로 입력해주세요."
    : localResearchAnswer(question);
}

function bindEvents() {
  els.searchInput.addEventListener("input", applyFilters);
  els.minScore.addEventListener("input", applyFilters);
  els.marketFilter.addEventListener("change", applyFilters);
  els.sortSelect.addEventListener("change", applyFilters);
  if (els.recommendationSelect) {
    els.recommendationSelect.addEventListener("change", () => {
      state.selectedRecommendationId = els.recommendationSelect.value;
      renderRecommendations();
    });
  }
  if (els.askForm) {
    els.askForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const question = els.askInput.value.trim();
      if (question) askResearch(question);
    });
  }

  document.querySelectorAll("[data-view-size]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-view-size]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      state.viewSize = Number(button.dataset.viewSize);
      renderTable();
    });
  });

  [els.rankBody, els.krTopBody, els.recommendationBody].forEach((body) => {
    body?.addEventListener("click", (event) => {
      const rowEl = event.target.closest("tr");
      if (rowEl) selectStock(state.stocks.find((row) => row.id === rowEl.dataset.id));
    });
  });
  els.researchStocks.addEventListener("click", (event) => {
    const button = event.target.closest("[data-symbol]");
    if (!button) return;
    const stock = state.stocks.find((row) => row.symbol === button.dataset.symbol);
    if (stock) selectStock(stock);
  });
  window.addEventListener("resize", () => {
    drawSpark(state.stocks.find((row) => row.id === state.selectedId));
  });
}

async function loadResearch() {
  try {
    const response = await fetch("./demo-data/research/latest.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.research = await response.json();
  } catch {
    state.research = {
      date: "-",
      marketSummary: "아직 리서치 분석 파일이 생성되지 않았습니다.",
      issues: [],
      stocks: [],
      documents: [],
    };
  }
  renderResearch();
}

async function boot() {
  bindEvents();
  const response = await fetch("./demo-data/scores.json");
  state.payload = await response.json();
  state.stocks = state.payload.stocks || [];

  const counts = state.payload.counts || {};
  els.generatedAt.textContent = new Date(state.payload.generatedAt).toLocaleString();
  els.coverage.textContent = `${fmt(counts.scored, 0)} / ${fmt(counts.inputFiles, 0)}`;
  els.universe.textContent = `KR ${fmt(counts.kr, 0)}`;

  populateMarkets();
  renderModel();
  renderTopLists();
  populateRecommendations();
  applyFilters();
  await loadResearch();
}

boot().catch((error) => {
  els.resultCount.textContent = `Failed to load data: ${error.message}`;
});
