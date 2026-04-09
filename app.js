const sampleData = [
  {
    ticker: "AAPL",
    atrPercent: 3.92,
    ivRank: 16.11,
    nextEarnings: "2026-04-30",
    price: 257.52,
    eps: 7.9,
    pe: 32.54,
    daysUntilEarnings: 22,
    setupRec: "Straddle",
    urgency: "Watchlist",
    signalTrigger: true,
    confidence: 1,
    ivRankChange: 0.1434,
    atrZScore: -0.7786,
    atr20Day: null,
    rec1: "Vertical (10)",
    rec2: "Straddle (3.0)",
    valueScore: 1.28,
    momentumScore: 0.8,
    squeezeScore: 1.26,
    readyScore: 0,
  },
  {
    ticker: "AMD",
    atrPercent: 3.61,
    ivRank: 20.13,
    nextEarnings: "2026-05-05",
    price: 232.66,
    eps: 2.61,
    pe: 88.82,
    daysUntilEarnings: 27,
    setupRec: "Avoid",
    urgency: "Watchlist",
    signalTrigger: false,
    confidence: 2,
    ivRankChange: -0.1362,
    atrZScore: 1.0061,
    atr20Day: null,
    rec1: "Vertical (10)",
    rec2: "Straddle (5.8)",
    valueScore: 0.62,
    momentumScore: 0.94,
    squeezeScore: 0.82,
    readyScore: 0.6,
  },
  {
    ticker: "ANET",
    atrPercent: 3.32,
    ivRank: 32.58,
    nextEarnings: "2026-05-05",
    price: 144.49,
    eps: 2.75,
    pe: 52.4,
    daysUntilEarnings: 27,
    setupRec: "Vertical Call",
    urgency: "Watchlist",
    signalTrigger: true,
    confidence: 2,
    ivRankChange: -0.323,
    atrZScore: 0.6842,
    atr20Day: null,
    rec1: "Vertical (11)",
    rec2: "Iron Condor (3.8)",
    valueScore: 1.32,
    momentumScore: 1.54,
    squeezeScore: 0.66,
    readyScore: 1.4,
  },
  {
    ticker: "ASML",
    atrPercent: 3.43,
    ivRank: 21.48,
    nextEarnings: "2026-04-15",
    price: 1424.4,
    eps: 28.65,
    pe: 49.48,
    daysUntilEarnings: 7,
    setupRec: "Avoid",
    urgency: "Urgent Straddle",
    signalTrigger: false,
    confidence: 2,
    ivRankChange: -0.185,
    atrZScore: 1.5375,
    atr20Day: null,
    rec1: "Vertical (11)",
    rec2: "Straddle (3.9)",
    valueScore: 0.71,
    momentumScore: 1.12,
    squeezeScore: 1.45,
    readyScore: 2.2,
  },
  {
    ticker: "AZZ",
    atrPercent: 4.36,
    ivRank: 23.78,
    nextEarnings: "2026-04-22",
    price: 134.46,
    eps: 10.64,
    pe: 12.58,
    daysUntilEarnings: 14,
    setupRec: "Avoid",
    urgency: "Watchlist",
    signalTrigger: false,
    confidence: 2,
    ivRankChange: -0.1735,
    atrZScore: -1.8524,
    atr20Day: null,
    rec1: "Vertical (10)",
    rec2: "Straddle (6.0)",
    valueScore: 1.66,
    momentumScore: 0.58,
    squeezeScore: 0.6,
    readyScore: 0.7,
  },
  {
    ticker: "CCOI",
    atrPercent: 3.66,
    ivRank: 28.94,
    nextEarnings: "2026-05-07",
    price: 19.95,
    eps: -3.8,
    pe: null,
    daysUntilEarnings: 29,
    setupRec: "Straddle",
    urgency: "Watchlist",
    signalTrigger: true,
    confidence: 2,
    ivRankChange: 0.0331,
    atrZScore: -1.7457,
    atr20Day: null,
    rec1: "Vertical (11)",
    rec2: "Straddle (4.9)",
    valueScore: 0.94,
    momentumScore: 1.26,
    squeezeScore: 1.64,
    readyScore: 1.8,
  },
  {
    ticker: "CEG",
    atrPercent: 3.48,
    ivRank: 33.82,
    nextEarnings: "2026-05-11",
    price: 283.43,
    eps: 7.39,
    pe: 38.5,
    daysUntilEarnings: 33,
    setupRec: "Straddle",
    urgency: "Watchlist",
    signalTrigger: false,
    confidence: 3,
    ivRankChange: 0.0858,
    atrZScore: 1.557,
    atr20Day: null,
    rec1: "Straddle (14)",
    rec2: "Straddle (5.1)",
    valueScore: 1.14,
    momentumScore: 1.62,
    squeezeScore: 1.42,
    readyScore: 1.7,
  },
  {
    ticker: "CRM",
    atrPercent: 3.18,
    ivRank: 32.69,
    nextEarnings: "2026-05-27",
    price: 179.14,
    eps: 7.8,
    pe: 22.97,
    daysUntilEarnings: 49,
    setupRec: "Vertical Call",
    urgency: "Watchlist",
    signalTrigger: true,
    confidence: 3,
    ivRankChange: -0.1588,
    atrZScore: -1.6627,
    atr20Day: null,
    rec1: "Vertical (11)",
    rec2: "Straddle (4.6)",
    valueScore: 1.5,
    momentumScore: 1.78,
    squeezeScore: 0.92,
    readyScore: 1.2,
  },
  {
    ticker: "DELL",
    atrPercent: 3.04,
    ivRank: 35.3,
    nextEarnings: "2026-05-28",
    price: 185.38,
    eps: 8.68,
    pe: 21.29,
    daysUntilEarnings: 50,
    setupRec: "Vertical Call",
    urgency: "Watchlist",
    signalTrigger: true,
    confidence: 3,
    ivRankChange: -0.0436,
    atrZScore: 0.2735,
    atr20Day: null,
    rec1: "Vertical (11)",
    rec2: "Iron Condor (5.0)",
    valueScore: 1.46,
    momentumScore: 1.35,
    squeezeScore: 0.86,
    readyScore: 1.1,
  },
  {
    ticker: "ENPH",
    atrPercent: 3.49,
    ivRank: 22.95,
    nextEarnings: "2026-04-28",
    price: 32.89,
    eps: 1.28,
    pe: 25.55,
    daysUntilEarnings: 20,
    setupRec: "Straddle",
    urgency: "Watchlist",
    signalTrigger: true,
    confidence: 2,
    ivRankChange: 0.0818,
    atrZScore: 2.2508,
    atr20Day: null,
    rec1: "Straddle (14)",
    rec2: "Iron Condor (3.8)",
    valueScore: 1.08,
    momentumScore: 0.92,
    squeezeScore: 2.18,
    readyScore: 2.1,
  },
  {
    ticker: "FIX",
    atrPercent: 10.49,
    ivRank: 28.17,
    nextEarnings: "2026-04-23",
    price: 1544.25,
    eps: 28.88,
    pe: 53.13,
    daysUntilEarnings: 15,
    setupRec: "Avoid",
    urgency: "Watchlist",
    signalTrigger: false,
    confidence: 2,
    ivRankChange: -0.1031,
    atrZScore: 0.4,
    atr20Day: null,
    rec1: "Vertical (10)",
    rec2: "Straddle (3.7)",
    valueScore: 0.72,
    momentumScore: 1.28,
    squeezeScore: 1.84,
    readyScore: 1.4,
  },
  {
    ticker: "HUBB",
    atrPercent: 6.0,
    ivRank: 25.28,
    nextEarnings: "2026-04-30",
    price: 527.84,
    eps: 16.55,
    pe: 31.84,
    daysUntilEarnings: 22,
    setupRec: "Avoid",
    urgency: "Watchlist",
    signalTrigger: false,
    confidence: 2,
    ivRankChange: -0.2855,
    atrZScore: -0.7267,
    atr20Day: 17.58,
    rec1: "Vertical (10)",
    rec2: "Straddle (3.4)",
    valueScore: 0.91,
    momentumScore: 1.21,
    squeezeScore: 1.02,
    readyScore: 0.9,
  },
  {
    ticker: "IRM",
    atrPercent: 5.66,
    ivRank: 17.05,
    nextEarnings: "2026-04-30",
    price: 107.27,
    eps: 0.49,
    pe: 220.95,
    daysUntilEarnings: 22,
    setupRec: "Straddle",
    urgency: "Watchlist",
    signalTrigger: true,
    confidence: 1,
    ivRankChange: 0.2021,
    atrZScore: -0.1317,
    atr20Day: null,
    rec1: "Vertical (10)",
    rec2: "Straddle (3.0)",
    valueScore: 0.88,
    momentumScore: 1.34,
    squeezeScore: 1.21,
    readyScore: 1.5,
  },
  {
    ticker: "LITE",
    atrPercent: 4.12,
    ivRank: 25.81,
    nextEarnings: "2026-05-05",
    price: 895.57,
    eps: 3.27,
    pe: 273.23,
    daysUntilEarnings: 27,
    setupRec: "Avoid",
    urgency: "Watchlist",
    signalTrigger: false,
    confidence: 2,
    ivRankChange: -0.2472,
    atrZScore: 0.1594,
    atr20Day: null,
    rec1: "Vertical (10)",
    rec2: "Straddle (8.1)",
    valueScore: 0.52,
    momentumScore: 0.88,
    squeezeScore: 1.18,
    readyScore: 0.5,
  },
  {
    ticker: "MRVL",
    atrPercent: 5.64,
    ivRank: 33.35,
    nextEarnings: "2026-05-28",
    price: 114.85,
    eps: 3.07,
    pe: 37.43,
    daysUntilEarnings: 50,
    setupRec: "Vertical Call",
    urgency: "Watchlist",
    signalTrigger: true,
    confidence: 3,
    ivRankChange: -0.203,
    atrZScore: -0.1196,
    atr20Day: null,
    rec1: "Vertical (11)",
    rec2: "Straddle (5.1)",
    valueScore: 1.42,
    momentumScore: 1.67,
    squeezeScore: 1.05,
    readyScore: 1.3,
  },
  {
    ticker: "NVDA",
    atrPercent: 5.57,
    ivRank: 42.95,
    nextEarnings: "2026-05-20",
    price: 181.7,
    eps: 4.9,
    pe: 37.08,
    daysUntilEarnings: 42,
    setupRec: "Vertical Call",
    urgency: "Watchlist",
    signalTrigger: true,
    confidence: 3,
    ivRankChange: 0.1378,
    atrZScore: -1.8443,
    atr20Day: null,
    rec1: "Straddle (14)",
    rec2: "Straddle (4.0)",
    valueScore: 1.6,
    momentumScore: 2.22,
    squeezeScore: 1.08,
    readyScore: 1.7,
  },
];

const DEFAULT_SHEET_URL = "";
const SHEET_STORAGE_KEY = "pipboy-earnings-sheet-url";
const GOOGLE_CLIENT_ID_STORAGE_KEY = "pipboy-google-client-id";
const GOOGLE_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly";

const state = {
  rows: sampleData.map(enrichRow),
  selectedTicker: null,
  sourceLabel: "Sample cache",
  latestBrief: "",
  latestTickets: "",
  backend: {
    available: false,
    smtpConfigured: false,
    lastSnapshotAt: null,
    opsStatus: null,
    watchdogStatus: null,
    approvalQueue: null,
  },
  auth: {
    accessToken: null,
    tokenExpiresAt: 0,
  },
  filters: {
    search: "",
    setup: "all",
    urgency: "all",
    trigger: "all",
    minConfidence: 0,
  },
};

const rosterBody = document.getElementById("roster-body");
const detailTitle = document.getElementById("detail-title");
const detailContent = document.getElementById("detail-content");
const shortlist = document.getElementById("shortlist");
const overviewStats = document.getElementById("overview-stats");
const setupFilter = document.getElementById("setup-filter");
const urgencyFilter = document.getElementById("urgency-filter");
const searchInput = document.getElementById("search-input");
const triggerFilter = document.getElementById("trigger-filter");
const confidenceFilter = document.getElementById("confidence-filter");
const confidenceValue = document.getElementById("confidence-value");
const csvInput = document.getElementById("csv-input");
const syncTime = document.getElementById("sync-time");
const sheetUrlInput = document.getElementById("sheet-url-input");
const googleClientIdInput = document.getElementById("google-client-id-input");
const sheetAuthSyncButton = document.getElementById("sheet-auth-sync-button");
const sheetPublicSyncButton = document.getElementById("sheet-public-sync-button");
const sheetRevokeButton = document.getElementById("sheet-revoke-button");
const sheetStatus = document.getElementById("sheet-status");
const signalRibbon = document.getElementById("signal-ribbon");
const playMap = document.getElementById("play-map");
const overviewSummary = document.getElementById("overview-summary");
const engineRules = document.getElementById("engine-rules");
const engineCandidates = document.getElementById("engine-candidates");
const briefPreview = document.getElementById("brief-preview");
const briefStatus = document.getElementById("brief-status");
const opsGrid = document.getElementById("ops-grid");
const opsFeed = document.getElementById("ops-feed");
const forgeSnapshotButton = document.getElementById("forge-snapshot-button");
const sendBriefButton = document.getElementById("send-brief-button");
const testSmtpButton = document.getElementById("test-smtp-button");
const copyBriefButton = document.getElementById("copy-brief-button");
const emailBriefButton = document.getElementById("email-brief-button");
const copyTicketsButton = document.getElementById("copy-tickets-button");

const convictionConfig = {
  minReadiness: 72,
  minConfidence: 2,
  maxDaysUntilEarnings: 21,
  requireTrigger: true,
  bannedSetups: ["Avoid"],
};

const creatureGuide = {
  hot: {
    key: "hot",
    name: "Ashen Revenant",
    miniFace: ">:)",
    label: "Hellbound",
    role: "A market revenant fed by pain, momentum, and names that refuse to die quietly.",
    hint: "These are the killers. They usually show up when readiness is high and the trigger is already breathing fire.",
  },
  wild: {
    key: "wild",
    name: "Chain Wraith",
    miniFace: "o:o",
    label: "Tormented",
    role: "A screaming wraith dragged by volatility, squeeze, and unfinished conviction.",
    hint: "These can become monsters fast. Watch them when volatility is loud but structure still needs form.",
  },
  cold: {
    key: "cold",
    name: "Grave Bishop",
    miniFace: "x_x",
    label: "Buried",
    role: "A priest of dead setups, fake conviction, and numbers that smell rich but move poor.",
    hint: "Good for discipline. Not everything deserves capital just because it promises salvation.",
  },
};

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function round(value, places = 1) {
  return Number.parseFloat(value).toFixed(places);
}

function formatCurrency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatDate(value) {
  const date = new Date(`${value}T12:00:00`);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function setSheetStatus(message, tone = "muted") {
  sheetStatus.textContent = message;
  sheetStatus.className = `connector-status ${tone}`;
}

function describeTemperature(row) {
  if (
    row.readiness >= 78 ||
    (row.signalTrigger && row.momentumScore >= 1.65) ||
    (row.status === "Ready" && row.setupRec !== "Avoid")
  ) {
    return creatureGuide.hot;
  }

  if (
    row.setupRec === "Avoid" ||
    row.readiness <= 42 ||
    (!row.signalTrigger && row.confidence <= 1)
  ) {
    return creatureGuide.cold;
  }

  return creatureGuide.wild;
}

function renderTempChip(row) {
  const creature = describeTemperature(row);
  return `
    <span class="temp-chip ${creature.key}">
      <span class="mini-face">${creature.miniFace}</span>
      <span>${creature.name}</span>
    </span>
  `;
}

function renderBossBar(row, mode = "full") {
  const creature = describeTemperature(row);
  const width = clamp(row.readiness, 0, 100);

  if (mode === "mini") {
    return `
      <div class="mini-bar">
        <div class="mini-track">
          <div class="mini-fill ${creature.key}" style="width: ${width}%"></div>
        </div>
      </div>
    `;
  }

  return `
    <div class="boss-bar">
      <div class="boss-label">
        <span>Ascension Meter</span>
        <span>${row.readiness}%</span>
      </div>
      <div class="boss-track">
        <div class="boss-fill ${creature.key}" style="width: ${width}%"></div>
      </div>
    </div>
  `;
}

function scoreToPercent(value, ceiling = 2.5) {
  return clamp((value / ceiling) * 100, 0, 100);
}

function setupWeight(setupRec) {
  const lowered = String(setupRec).toLowerCase();
  if (lowered.includes("vertical")) {
    return 13;
  }
  if (lowered.includes("straddle")) {
    return 11;
  }
  if (lowered.includes("condor")) {
    return 8;
  }
  if (lowered.includes("avoid")) {
    return -10;
  }
  return 0;
}

function urgencyWeight(urgency) {
  const lowered = String(urgency).toLowerCase();
  if (lowered.includes("urgent")) {
    return 18;
  }
  if (lowered.includes("watch")) {
    return 8;
  }
  if (lowered.includes("avoid")) {
    return -16;
  }
  return 0;
}

function readinessLabel(readiness) {
  if (readiness >= 72) {
    return "Ready";
  }
  if (readiness >= 48) {
    return "Watch";
  }
  return "Avoid";
}

function dominantScore(row) {
  const entries = [
    ["Value", row.valueScore],
    ["Momentum", row.momentumScore],
    ["Squeeze", row.squeezeScore],
    ["Ready", row.readyScore],
  ];
  return entries.sort((a, b) => b[1] - a[1])[0] || ["Value", 0];
}

function buildActionBias(row, priority) {
  if (
    row.signalTrigger &&
    row.readyScore >= 1 &&
    row.momentumScore >= 0.8 &&
    row.confidence >= 2 &&
    row.daysUntilEarnings <= 21 &&
    priority >= 3
  ) {
    return {
      label: "Make A Move",
      tone: "hot",
      note: "Trigger, timing, and score stack are all lined up.",
    };
  }

  if (
    priority >= 2.2 ||
    row.squeezeScore >= 1.1 ||
    row.valueScore >= 1.2 ||
    row.momentumScore >= 1
  ) {
    return {
      label: "Stalk It",
      tone: "wild",
      note: "There is real edge here, but it still wants cleaner confirmation or timing.",
    };
  }

  return {
    label: "Wait",
    tone: "cold",
    note: "The sheet sees something, but not enough to commit capital yet.",
  };
}

function enrichRow(row) {
  const timingScore =
    row.daysUntilEarnings <= 7
      ? 16
      : row.daysUntilEarnings <= 21
        ? 20
        : row.daysUntilEarnings <= 35
          ? 17
          : 9;
  const triggerScore = row.signalTrigger ? 14 : 0;
  const confidenceScore = (row.confidence / 3) * 24;
  const ivMomentumScore = clamp(row.ivRankChange * 65, -8, 10);
  const volatilityScore = clamp((row.ivRank / 50) * 12 + (row.atrPercent / 10) * 10, 0, 20);
  const scoreBlend =
    scoreToPercent(row.readyScore) * 0.28 +
    scoreToPercent(row.squeezeScore) * 0.18 +
    scoreToPercent(row.momentumScore) * 0.18 +
    scoreToPercent(row.valueScore) * 0.12;
  const readiness = clamp(
    timingScore +
      triggerScore +
      confidenceScore +
      ivMomentumScore +
      volatilityScore +
      setupWeight(row.setupRec) +
      urgencyWeight(row.urgency) +
      scoreBlend * 0.32,
    8,
    99,
  );
  const priority = round(
    Number.isFinite(row.priority)
      ? row.priority
      : row.valueScore + row.momentumScore + row.squeezeScore + row.readyScore,
    2,
  );
  const [scoreLeader, scoreLeaderValue] = dominantScore(row);
  const actionBias = buildActionBias(row, priority);

  return {
    ...row,
    priority,
    scoreLeader,
    scoreLeaderValue: round(scoreLeaderValue, 2),
    actionBias,
    readiness: Math.round(readiness),
    status: readinessLabel(readiness),
  };
}

function getUniqueOptions(key) {
  return ["all", ...new Set(state.rows.map((row) => row[key]).filter(Boolean))];
}

function populateFilters() {
  setupFilter.innerHTML = getUniqueOptions("setupRec")
    .map((value) => `<option value="${value}">${value === "all" ? "All" : value}</option>`)
    .join("");

  urgencyFilter.innerHTML = getUniqueOptions("urgency")
    .map((value) => `<option value="${value}">${value === "all" ? "All" : value}</option>`)
    .join("");
}

function updateSyncLabel(label = state.sourceLabel) {
  syncTime.textContent = label;
}

function formatBackendDate(value) {
  if (!value) {
    return "Never";
  }
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function isGoogleReady() {
  return Boolean(window.google?.accounts?.oauth2);
}

function waitForGoogleIdentity(timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const startTime = Date.now();

    function check() {
      if (isGoogleReady()) {
        resolve();
        return;
      }

      if (Date.now() - startTime > timeoutMs) {
        reject(new Error("Google Identity Services did not finish loading"));
        return;
      }

      window.setTimeout(check, 120);
    }

    check();
  });
}

function accessTokenIsFresh() {
  return Boolean(state.auth.accessToken && Date.now() < state.auth.tokenExpiresAt - 15000);
}

function getFilteredRows() {
  return state.rows
    .filter((row) => row.ticker.toLowerCase().includes(state.filters.search))
    .filter((row) => state.filters.setup === "all" || row.setupRec === state.filters.setup)
    .filter((row) => state.filters.urgency === "all" || row.urgency === state.filters.urgency)
    .filter((row) => state.filters.trigger === "all" || String(row.signalTrigger) === state.filters.trigger)
    .filter((row) => row.confidence >= state.filters.minConfidence)
    .sort((a, b) => b.readiness - a.readiness || b.priority - a.priority || a.daysUntilEarnings - b.daysUntilEarnings);
}

function renderOverview(rows) {
  const readyCount = rows.filter((row) => row.status === "Ready").length;
  const triggerCount = rows.filter((row) => row.signalTrigger).length;
  const hotWindowCount = rows.filter((row) => row.daysUntilEarnings <= 14).length;
  const avgReadiness = rows.length
    ? Math.round(rows.reduce((sum, row) => sum + row.readiness, 0) / rows.length)
    : 0;
  const avgPriority = rows.length ? round(rows.reduce((sum, row) => sum + row.priority, 0) / rows.length, 2) : 0;

  overviewStats.innerHTML = [
    { label: "Signals Tracked", value: rows.length },
    { label: "Hot Window (< 14d)", value: hotWindowCount },
    { label: "Triggered", value: triggerCount },
    { label: "Avg Readiness", value: `${avgReadiness}%` },
    { label: "Ready Now", value: readyCount },
    { label: "Avg Priority", value: avgPriority },
    { label: "Avg IV Rank", value: rows.length ? round(rows.reduce((sum, row) => sum + row.ivRank, 0) / rows.length, 1) : "0.0" },
    { label: "Avg ATR%", value: rows.length ? round(rows.reduce((sum, row) => sum + row.atrPercent, 0) / rows.length, 1) : "0.0" },
    { label: "Urgent Names", value: rows.filter((row) => row.urgency.toLowerCase().includes("urgent")).length },
  ]
    .map(
      (item) => `
        <div class="stat-card">
          <span>${item.label}</span>
          <strong>${item.value}</strong>
        </div>
      `,
    )
    .join("");

  const topPlay = rows[0];
  if (!topPlay) {
    overviewSummary.textContent = "No active names in the circle right now. Adjust your filters to summon fresh plays.";
    playMap.innerHTML = "";
    return;
  }

  const immediateKillers = rows.filter((row) => row.readiness >= 72).length;
  const triggerLive = rows.filter((row) => row.signalTrigger).length;
  overviewSummary.textContent = `${topPlay.ticker} leads the altar at ${topPlay.readiness}% readiness with a ${topPlay.priority} priority stack driven by ${topPlay.scoreLeader.toLowerCase()}. ${immediateKillers} names are in true striking range and ${triggerLive} already have their trigger lit.`;
  renderPlayMap(rows);
}

function renderOpsWatch() {
  const ops = state.backend.opsStatus;
  const watchdog = state.backend.watchdogStatus;
  const dawnOk = ops?.ok;
  const watchdogOk = watchdog?.ok;
  const cards = [
    {
      label: "Dawn Cycle",
      value: dawnOk === undefined ? "Unknown" : dawnOk ? "Armed" : "Fault",
      tone: dawnOk ? "status-ready" : "status-risk",
    },
    {
      label: "SMTP Relay",
      value: state.backend.smtpConfigured ? "Armed" : "Offline",
      tone: state.backend.smtpConfigured ? "status-ready" : "status-risk",
    },
    {
      label: "Last Auto Run",
      value: formatBackendDate(ops?.generatedAt || state.backend.lastSnapshotAt),
      tone: "status-caution",
    },
    {
      label: "Watchdog",
      value: watchdogOk === undefined ? "Unknown" : watchdogOk ? "Watching" : "Barking",
      tone: watchdogOk ? "status-ready" : "status-risk",
    },
    {
      label: "Approval Desk",
      value: state.backend.approvalQueue?.count ?? 0,
      tone: (state.backend.approvalQueue?.count ?? 0) > 0 ? "status-caution" : "status-ready",
    },
    {
      label: "Paper Journal",
      value: ops?.paperTradeCount ?? 0,
      tone: (ops?.paperTradeCount ?? 0) > 0 ? "status-caution" : "status-ready",
    },
  ];

  opsGrid.innerHTML = cards
    .map(
      (card) => `
        <div class="metric-card ops-card">
          <span>${card.label}</span>
          <strong class="${card.tone}">${card.value}</strong>
        </div>
      `,
    )
    .join("");

  const messages = [];
  if (ops?.topTickers?.length) {
    messages.push(`Dawn leaders: ${ops.topTickers.join(", ")}`);
  }
  if (state.backend.approvalQueue?.items?.length) {
    messages.push(
      `Approval desk waiting on: ${state.backend.approvalQueue.items
        .map((item) => `${item.ticker} (${item.approvalStatus})`)
        .join(", ")}`,
    );
  }
  if (ops?.repair?.repaired) {
    messages.push("Column R needed self-healing after the external R job.");
  }
  if (watchdog?.reasons?.length) {
    messages.push(`Watchdog notes: ${watchdog.reasons.join("; ")}`);
  } else if (watchdogOk) {
    messages.push("Watchdog sees no faults in the latest automation cycle.");
  } else {
    messages.push("Watchdog standing by for its first patrol.");
  }

  opsFeed.innerHTML = messages.map((message) => `<div class="brief-card">${message}</div>`).join("");
}

function renderPlayMap(rows) {
  const candidates = rows.slice(0, 8);
  const width = 560;
  const height = 300;
  const centerX = 280;
  const centerY = 150;
  const circles = [34, 68, 102];

  const plotted = candidates.map((row, index) => {
    const creature = describeTemperature(row);
    const angle = ((row.daysUntilEarnings % 34) / 34) * Math.PI * 2 - Math.PI / 2 + index * 0.22;
    const readinessPull = clamp(1 - row.readiness / 100, 0.18, 0.94);
    const radius = 40 + readinessPull * 82;
    const x = centerX + Math.cos(angle) * radius;
    const y = centerY + Math.sin(angle) * (radius * 0.76);
    return { row, creature, x, y };
  });

  const left = plotted.filter((item) => item.x < centerX).sort((a, b) => a.y - b.y);
  const right = plotted.filter((item) => item.x >= centerX).sort((a, b) => a.y - b.y);

  function laneY(index, total) {
    if (total <= 1) {
      return centerY;
    }
    const start = 78;
    const end = height - 54;
    return start + ((end - start) * index) / (total - 1);
  }

  function renderLabeledSide(items, side) {
    const boxWidth = 142;
    const boxHeight = 34;
    const boxX = side === "left" ? 16 : width - boxWidth - 16;
    const elbowX = side === "left" ? 158 : width - 158;
    const textX = side === "left" ? boxX + 10 : boxX + 10;

    return items
      .map((item, index) => {
        const y = laneY(index, items.length);
        const boxY = y - boxHeight / 2;
        const liveText = item.row.signalTrigger ? "LIVE" : "WAIT";

        return `
          <line class="node-line" x1="${centerX}" y1="${centerY}" x2="${item.x}" y2="${item.y}" />
          <path class="leader" d="M ${item.x} ${item.y} L ${elbowX} ${y} L ${side === "left" ? boxX + boxWidth : boxX} ${y}" />
          <circle class="node ${item.creature.key}" cx="${item.x}" cy="${item.y}" r="${8 + item.row.confidence}"></circle>
          <rect class="label-box ${item.creature.key}" x="${boxX}" y="${boxY}" width="${boxWidth}" height="${boxHeight}"></rect>
          <text class="label" x="${textX}" y="${boxY + 14}" text-anchor="start">${item.row.ticker}</text>
          <text class="sub-label" x="${textX}" y="${boxY + 26}" text-anchor="start">${item.row.readiness}% | ${item.row.daysUntilEarnings}d | ${liveText}</text>
        `;
      })
      .join("");
  }

  playMap.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Conviction Circle play map">
      <line class="cross" x1="${centerX}" y1="20" x2="${centerX}" y2="${height - 20}" />
      <line class="cross" x1="24" y1="${centerY}" x2="${width - 24}" y2="${centerY}" />
      ${circles.map((ring) => `<circle class="ring" cx="${centerX}" cy="${centerY}" r="${ring}"></circle>`).join("")}
      <circle class="altar" cx="${centerX}" cy="${centerY}" r="18"></circle>
      <circle class="altar-core" cx="${centerX}" cy="${centerY}" r="7"></circle>
      <text class="zone-label" x="${centerX}" y="${centerY - 42}" text-anchor="middle">INNER ALTAR</text>
      <text class="sub-label" x="${centerX}" y="${centerY + 42}" text-anchor="middle">high conviction / near action</text>
      <text class="zone-label" x="30" y="34" text-anchor="start">BUILD WATCH</text>
      <text class="zone-label" x="${width - 30}" y="34" text-anchor="end">STRIKE NOW</text>
      ${renderLabeledSide(left, "left")}
      ${renderLabeledSide(right, "right")}
    </svg>
  `;
}

function gateChecks(row) {
  return {
    readiness: row.readiness >= convictionConfig.minReadiness,
    confidence: row.confidence >= convictionConfig.minConfidence,
    timing: row.daysUntilEarnings <= convictionConfig.maxDaysUntilEarnings,
    trigger: convictionConfig.requireTrigger ? row.signalTrigger : true,
    setup: !convictionConfig.bannedSetups.includes(row.setupRec),
  };
}

function gateFailures(row) {
  const checks = gateChecks(row);
  return Object.entries(checks)
    .filter(([, passed]) => !passed)
    .map(([key]) => {
      switch (key) {
        case "readiness":
          return "readiness below threshold";
        case "confidence":
          return "confidence too low";
        case "timing":
          return "too far from earnings";
        case "trigger":
          return "trigger not live";
        case "setup":
          return "setup blocked";
        default:
          return key;
      }
    });
}

function getEligibleCandidates(rows) {
  return rows.filter((row) => gateFailures(row).length === 0);
}

function renderConvictionEngine(rows) {
  const eligible = getEligibleCandidates(rows).slice(0, 5);
  const gateRows = [
    {
      label: "Readiness Gate",
      value: `>= ${convictionConfig.minReadiness}%`,
      status: `${rows.filter((row) => gateChecks(row).readiness).length} pass`,
    },
    {
      label: "Confidence Gate",
      value: `>= ${convictionConfig.minConfidence} / 3`,
      status: `${rows.filter((row) => gateChecks(row).confidence).length} pass`,
    },
    {
      label: "Timing Gate",
      value: `<= ${convictionConfig.maxDaysUntilEarnings} days`,
      status: `${rows.filter((row) => gateChecks(row).timing).length} pass`,
    },
    {
      label: "Trigger Gate",
      value: convictionConfig.requireTrigger ? "must be live" : "optional",
      status: `${rows.filter((row) => gateChecks(row).trigger).length} pass`,
    },
  ];

  engineRules.innerHTML = gateRows
    .map(
      (rule, index) => `
        <div class="rule-card">
          <div class="rule-glyph">${index + 1}</div>
          <div>
            <p><strong>${rule.label}</strong></p>
            <p class="muted">${rule.value}</p>
          </div>
          <div>${rule.status}</div>
        </div>
      `,
    )
    .join("");

  if (!eligible.length) {
    engineCandidates.innerHTML = `
      <div class="candidate-card">
        <p><strong>No names have earned full conviction yet.</strong></p>
        <p class="muted">The engine is doing its job. Better no trade than fake conviction.</p>
      </div>
    `;
    return;
  }

  engineCandidates.innerHTML = eligible
    .map((row, index) => `
      <div class="candidate-card">
        <div class="candidate-head">
          <div>
            <p><strong>#${index + 1} ${row.ticker}</strong></p>
            <p class="candidate-meta">${row.setupRec} | ${row.daysUntilEarnings}d | ${row.readiness}% readiness</p>
            <p class="candidate-meta">Priority ${row.priority} | ${row.scoreLeader} lead</p>
          </div>
          ${renderTempChip(row)}
        </div>
        <div class="candidate-tags">
          <span class="pill action-${row.actionBias.tone}">${row.actionBias.label}</span>
          <span class="pill">${row.signalTrigger ? "Trigger Live" : "Trigger Waiting"}</span>
          <span class="pill">${row.confidence} / 3 confidence</span>
          <span class="pill">${row.rec1}</span>
        </div>
        ${renderScoreSigils(row)}
        <p class="candidate-note">${row.actionBias.note}</p>
        ${renderBossBar(row, "mini")}
      </div>
    `)
    .join("");
}

function buildMorningBrief(rows) {
  const eligible = getEligibleCandidates(rows);
  const headline = eligible[0]
    ? `${eligible[0].ticker} leads the board at ${eligible[0].readiness}% readiness.`
    : "No full-conviction names passed every gate today.";

  const lines = [
    "Morning Brief",
    `${headline}`,
    "",
    `Total tracked: ${rows.length}`,
    `Eligible now: ${eligible.length}`,
    `Triggered names: ${rows.filter((row) => row.signalTrigger).length}`,
    "",
    "Top recommendations:",
  ];

  const recommended = eligible.length ? eligible.slice(0, 5) : rows.slice(0, 3);
  recommended.forEach((row, index) => {
    const failureText = eligible.includes(row) ? "all gates clear" : gateFailures(row).join(", ");
    lines.push(
      `${index + 1}. ${row.ticker} | ${row.setupRec} | ${row.readiness}% | ${row.daysUntilEarnings}d | ${row.signalTrigger ? "trigger live" : "waiting"} | ${failureText}`,
    );
  });

  lines.push("");
  lines.push("Prime thesis:");
  recommended.slice(0, 3).forEach((row) => {
    lines.push(`- ${row.ticker}: ${buildNarrative(row)}`);
  });

  return {
    text: lines.join("\n"),
    eligible,
    recommended,
  };
}

function buildPaperTickets(rows) {
  const picks = getEligibleCandidates(rows).slice(0, 5);
  if (!picks.length) {
    return "No paper tickets generated. No names passed every conviction gate.";
  }

  return picks
    .map((row, index) => {
      return [
        `Ticket ${index + 1}: ${row.ticker}`,
        `Setup: ${row.setupRec}`,
        `Readiness: ${row.readiness}%`,
        `Timing: ${row.daysUntilEarnings} days to earnings`,
        `Trigger: ${row.signalTrigger ? "LIVE" : "WAIT"}`,
        `Primary route: ${row.rec1}`,
        `Secondary route: ${row.rec2}`,
        `Risk note: paper trade only until live execution rules are proven.`,
      ].join("\n");
    })
    .join("\n\n");
}

function renderMorningBrief(rows) {
  const brief = buildMorningBrief(rows);
  const backendText = state.backend.available
    ? state.backend.smtpConfigured
      ? "Local command server online. SMTP is armed."
      : "Local command server online. Snapshot saves work; SMTP is not configured yet."
    : "Static mode. Run python3 server.py to save snapshots and unlock SMTP delivery.";
  briefStatus.textContent = `${brief.eligible.length} names currently pass the full conviction engine. ${backendText}`;
  briefPreview.innerHTML = `
    <div class="brief-card">${brief.text}</div>
  `;
  state.latestBrief = brief.text;
  state.latestTickets = buildPaperTickets(rows);
}

async function copyTextWithStatus(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text);
    briefStatus.textContent = successMessage;
  } catch {
    briefStatus.textContent = "Clipboard access failed. Your browser may require a secure context or manual copy.";
  }
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`Request failed with ${response.status}`);
  }

  return response.json();
}

function buildSnapshotPayload(rows) {
  return {
    generatedAt: new Date().toISOString(),
    sourceLabel: state.sourceLabel,
    brief: state.latestBrief,
    tickets: state.latestTickets,
    eligibleTickers: getEligibleCandidates(rows).map((row) => row.ticker),
    rows,
  };
}

async function refreshBackendStatus() {
  try {
    const status = await apiRequest("/api/status", {
      method: "GET",
      headers: {},
    });
    state.backend.available = true;
    state.backend.smtpConfigured = Boolean(status.smtpConfigured);
    state.backend.lastSnapshotAt = status.lastSnapshotAt || null;
    state.backend.opsStatus = status.opsStatus || null;
    state.backend.watchdogStatus = status.watchdogStatus || null;
    state.backend.approvalQueue = status.approvalQueue || null;
  } catch {
    state.backend.available = false;
    state.backend.smtpConfigured = false;
    state.backend.lastSnapshotAt = null;
    state.backend.opsStatus = null;
    state.backend.watchdogStatus = null;
    state.backend.approvalQueue = null;
  }
}

async function forgeSnapshot(sendEmail = false) {
  const rows = getFilteredRows();
  if (!rows.length) {
    briefStatus.textContent = "No rows are loaded, so there is nothing to forge.";
    return;
  }

  if (!state.backend.available) {
    briefStatus.textContent = "Local command server is offline. Run python3 server.py to enable snapshots and SMTP delivery.";
    return;
  }

  try {
    const result = await apiRequest("/api/briefing", {
      method: "POST",
      body: JSON.stringify({
        ...buildSnapshotPayload(rows),
        sendEmail,
      }),
    });

    state.backend.available = true;
    state.backend.smtpConfigured = Boolean(result.smtpConfigured);
    state.backend.lastSnapshotAt = result.generatedAt || new Date().toISOString();
    briefStatus.textContent = sendEmail
      ? result.emailSent
        ? `Brief emailed and snapshot forged at ${result.snapshotPath}.`
        : `Snapshot forged at ${result.snapshotPath}, but SMTP is not configured.`
      : `Snapshot forged at ${result.snapshotPath}.`;
  } catch (error) {
    briefStatus.textContent = `Snapshot forge failed. ${error.message}`;
  }
}

async function testSmtpDelivery() {
  if (!state.backend.available) {
    briefStatus.textContent = "Local command server is offline. Run python3 server.py first.";
    return;
  }

  try {
    const result = await apiRequest("/api/test-email", {
      method: "POST",
      body: JSON.stringify({}),
    });
    state.backend.smtpConfigured = Boolean(result.smtpConfigured);
    briefStatus.textContent = result.message || "SMTP test email sent.";
  } catch (error) {
    briefStatus.textContent = `SMTP test failed. ${error.message}`;
  }
}

function renderSignalRibbon(rows) {
  if (!rows.length) {
    signalRibbon.innerHTML = `<div class="ribbon-card wild"><p class="eyebrow">Standby</p><p>No encounters match the current filter stack.</p></div>`;
    return;
  }

  signalRibbon.innerHTML = rows
    .slice(0, 4)
    .map((row) => {
      const creature = describeTemperature(row);
      return `
        <button class="ribbon-card ${creature.key}" data-ticker="${row.ticker}" type="button">
          <p class="eyebrow">${creature.label}</p>
          <p><strong>${row.ticker}</strong> | ${creature.name}</p>
          <p class="muted">${row.setupRec} | ${row.daysUntilEarnings}d | ${row.readiness}% ready</p>
          <p>${row.signalTrigger ? "Trigger lit. Let it feed." : "Still in the pit, waiting to break loose."}</p>
          ${renderBossBar(row, "mini")}
        </button>
      `;
    })
    .join("");

  signalRibbon.querySelectorAll("button[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTicker = button.dataset.ticker;
      render();
    });
  });
}

function renderRoster(rows) {
  if (!rows.length) {
    rosterBody.innerHTML = `
      <tr>
        <td colspan="11">No targets match the current filters.</td>
      </tr>
    `;
    return;
  }

  if (!state.selectedTicker || !rows.some((row) => row.ticker === state.selectedTicker)) {
    state.selectedTicker = rows[0].ticker;
  }

  rosterBody.innerHTML = rows
    .map((row) => {
      const activeClass = row.ticker === state.selectedTicker ? "active" : "";
      const triggerGlyph = row.signalTrigger ? "YES" : "WAIT";
      const creature = describeTemperature(row);
      const statusClass =
        row.status === "Ready" ? "status-ready" : row.status === "Watch" ? "status-caution" : "status-risk";

      return `
        <tr data-ticker="${row.ticker}" class="${activeClass} temp-${creature.key}">
          <td class="ticker-cell">
            <strong>${row.ticker}</strong>
            <span>${formatDate(row.nextEarnings)}</span>
          </td>
          <td>${renderTempChip(row)}</td>
          <td>${row.setupRec}</td>
          <td>${row.daysUntilEarnings}</td>
          <td>${triggerGlyph}</td>
          <td>${row.confidence} / 3</td>
          <td>${round(row.ivRank, 1)}</td>
          <td>${round(row.atrPercent, 1)}</td>
          <td>${row.priority}</td>
          <td><span class="move-chip ${row.actionBias.tone}">${row.actionBias.label}</span></td>
          <td class="${statusClass}">
            ${renderBossBar(row, "mini")}
            <div>${row.readiness}%</div>
          </td>
        </tr>
      `;
    })
    .join("");

  rosterBody.querySelectorAll("tr[data-ticker]").forEach((rowElement) => {
    rowElement.addEventListener("click", () => {
      state.selectedTicker = rowElement.dataset.ticker;
      render();
    });
  });
}

function renderDetail(rows) {
  const row = rows.find((item) => item.ticker === state.selectedTicker);

  if (!row) {
    detailTitle.textContent = "No Active Selection";
    detailContent.innerHTML = "<p>Adjust filters or import a CSV to populate the detail console.</p>";
    return;
  }

  detailTitle.textContent = `${row.ticker} Infernal Readout`;
  const creature = describeTemperature(row);
  const statusClass =
    row.status === "Ready" ? "status-ready" : row.status === "Watch" ? "status-caution" : "status-risk";
  const statusPillClass = row.status === "Ready" ? "" : row.status === "Watch" ? "warn" : "risk";

  detailContent.innerHTML = `
    <div class="detail-top">
      <div>
        <div class="detail-meta">
          <span class="pill ${statusPillClass}">${row.status}</span>
          <span class="pill">${row.setupRec}</span>
          <span class="pill">${row.signalTrigger ? "Trigger Live" : "Waiting"}</span>
          ${renderTempChip(row)}
        </div>
        <p class="price">${formatCurrency(row.price)}</p>
        <p class="muted">${formatDate(row.nextEarnings)} | ${row.daysUntilEarnings} days to earnings</p>
        ${renderBossBar(row)}
      </div>
      <div class="metric-card">
        <span>Readiness Index</span>
        <strong class="${statusClass}">${row.readiness}%</strong>
      </div>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <span>IV Rank</span>
        <strong>${round(row.ivRank, 1)}</strong>
      </div>
      <div class="metric-card">
        <span>ATR%</span>
        <strong>${round(row.atrPercent, 1)}</strong>
      </div>
      <div class="metric-card">
        <span>Confidence</span>
        <strong>${row.confidence} / 3</strong>
      </div>
      <div class="metric-card">
        <span>IV Rank Delta</span>
        <strong>${round(row.ivRankChange, 3)}</strong>
      </div>
      <div class="metric-card">
        <span>Priority Stack</span>
        <strong>${row.priority}</strong>
      </div>
      <div class="metric-card">
        <span>Move Bias</span>
        <strong class="${row.actionBias.tone === "hot" ? "status-ready" : row.actionBias.tone === "wild" ? "status-caution" : "status-risk"}">${row.actionBias.label}</strong>
      </div>
    </div>

    <div class="score-breakout">
      <div class="score-breakout-head">
        <p class="eyebrow">Conviction Mix</p>
        <strong>${row.scoreLeader} is doing the heavy lifting</strong>
      </div>
      <div class="score-tiles">
        ${renderScoreTile("Value", row.valueScore)}
        ${renderScoreTile("Momentum", row.momentumScore)}
        ${renderScoreTile("Squeeze", row.squeezeScore)}
        ${renderScoreTile("Ready", row.readyScore)}
      </div>
    </div>

    <div class="score-stack">
      ${renderScoreRow("Value", row.valueScore)}
      ${renderScoreRow("Momentum", row.momentumScore)}
      ${renderScoreRow("Squeeze", row.squeezeScore)}
      ${renderScoreRow("Ready", row.readyScore)}
      ${renderScoreRow("Priority", row.priority, 8)}
    </div>

    <div class="detail-bottom">
      ${renderMascotCard(row, creature)}
      <div class="playbook">
        <p><strong>Primary path:</strong> ${row.rec1}</p>
        <p><strong>Secondary path:</strong> ${row.rec2}</p>
        <p><strong>Urgency:</strong> ${row.urgency}</p>
        <p><strong>Move bias:</strong> ${row.actionBias.label} | ${row.actionBias.note}</p>
        <p><strong>Interpretation:</strong> ${buildNarrative(row)}</p>
      </div>
    </div>
  `;
}

function renderMascotCard(row, creature) {
  return `
    <div class="mascot-card">
      <div class="mascot-header">
        <div>
          <p class="eyebrow">Signal Demon</p>
          <strong>${creature.name}</strong>
          <p class="mascot-subcopy">${creature.role}</p>
        </div>
        <span class="temp-chip ${creature.key}">
          <span class="mini-face">${creature.miniFace}</span>
          <span>${creature.label}</span>
        </span>
      </div>
      <div class="mascot-stage">
        <div class="mascot-portrait ${creature.key}">
          <div class="mascot-head"></div>
          <div class="mascot-mouth"></div>
        </div>
        <div class="mascot-lines">
          <div class="mascot-line">
            <span>Reads</span>
            <p>${row.signalTrigger ? "The seal is broken and the demon is pacing the arena." : "Still locked below the floorboards, waiting for confirmation."}</p>
          </div>
          <div class="mascot-line">
            <span>Behavior</span>
            <p>${creature.hint}</p>
          </div>
          <div class="mascot-line">
            <span>Loot</span>
            <p>${row.status === "Ready" ? "A live setup with blood in it and momentum behind it." : row.setupRec === "Avoid" ? "Information only. Keep your capital out of the fire." : "Watchlist material. Could mutate into a real winner fast."}</p>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderScoreRow(label, value, ceiling = 2.5) {
  const percent = scoreToPercent(value, ceiling);
  return `
    <div class="score-row">
      <span>${label}</span>
      <div class="score-bar">
        <div class="score-fill" style="width: ${percent}%"></div>
      </div>
      <strong>${round(value, 2)}</strong>
    </div>
  `;
}

function renderScoreTile(label, value) {
  const percent = scoreToPercent(value);
  return `
    <div class="score-tile">
      <span>${label}</span>
      <strong>${round(value, 2)}</strong>
      <div class="score-bar">
        <div class="score-fill" style="width: ${percent}%"></div>
      </div>
    </div>
  `;
}

function renderScoreSigils(row) {
  const entries = [
    ["VAL", row.valueScore],
    ["MOM", row.momentumScore],
    ["SQZ", row.squeezeScore],
    ["RDY", row.readyScore],
  ];
  return `
    <div class="score-sigils">
      ${entries
        .map(([label, value]) => {
          const percent = scoreToPercent(value);
          return `
            <div class="score-sigil">
              <span>${label}</span>
              <div class="mini-track">
                <div class="mini-fill" style="width: ${percent}%"></div>
              </div>
              <strong>${round(value, 2)}</strong>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function buildNarrative(row) {
  const timing =
    row.daysUntilEarnings <= 10
      ? "The catalyst window is almost here, so precision matters more than panic and greed."
      : row.daysUntilEarnings <= 30
        ? "The event sits in the strike zone, where disciplined names start separating from the pretenders."
        : "This one is still earlier in the cycle, so it feels more like stalking prey than swinging the blade.";

  const signal = row.signalTrigger
    ? "Your signal trigger is already active, which means the market has stopped whispering and started confessing."
    : "The trigger has not fired yet, so this stays chained until price action proves it belongs in the arena.";

  const setup =
    row.setupRec === "Avoid"
      ? "The setup recommendation is defensive, so treat the name like a cursed relic: study it, but do not worship it."
      : `The current setup bias favors ${row.setupRec.toLowerCase()} structures.`;

  return `${timing} ${signal} ${setup}`;
}

function renderShortlist(rows) {
  shortlist.innerHTML = rows
    .slice(0, 5)
    .map((row, index) => {
      const creature = describeTemperature(row);
      return `
        <button class="short-card" data-ticker="${row.ticker}" type="button">
          <strong>#${index + 1}</strong>
          <div>
            <p>${row.ticker} | ${row.setupRec}</p>
            <p class="muted">${row.daysUntilEarnings}d | ${row.rec2}</p>
            <p class="muted">Priority ${row.priority} | ${row.actionBias.label}</p>
            ${renderTempChip(row)}
          </div>
          <strong class="${creature.key === "hot" ? "status-ready" : creature.key === "wild" ? "status-caution" : "status-risk"}">${row.readiness}%</strong>
        </button>
      `;
    })
    .join("");

  shortlist.querySelectorAll("button[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTicker = button.dataset.ticker;
      render();
    });
  });
}

function render() {
  const rows = getFilteredRows();
  updateSyncLabel(state.sourceLabel);
  renderOverview(rows);
  renderOpsWatch();
  renderSignalRibbon(rows);
  renderConvictionEngine(rows);
  renderMorningBrief(rows);
  renderRoster(rows);
  renderDetail(rows);
  renderShortlist(rows);
}

function parseCSV(text) {
  const rows = [];
  let current = "";
  let row = [];
  let insideQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const nextChar = text[index + 1];

    if (char === '"' && insideQuotes && nextChar === '"') {
      current += '"';
      index += 1;
      continue;
    }

    if (char === '"') {
      insideQuotes = !insideQuotes;
      continue;
    }

    if (char === "," && !insideQuotes) {
      row.push(current);
      current = "";
      continue;
    }

    if ((char === "\n" || char === "\r") && !insideQuotes) {
      if (char === "\r" && nextChar === "\n") {
        index += 1;
      }
      if (current || row.length) {
        row.push(current);
        rows.push(row);
      }
      row = [];
      current = "";
      continue;
    }

    current += char;
  }

  if (current || row.length) {
    row.push(current);
    rows.push(row);
  }

  return rows;
}

function numberOrNull(value) {
  const cleaned = String(value ?? "")
    .replace(/\$/g, "")
    .replace(/,/g, "")
    .trim();
  if (!cleaned || cleaned.toUpperCase() === "N/A" || cleaned === "#N/A") {
    return null;
  }
  const parsed = Number.parseFloat(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeCSVRows(rawRows) {
  if (rawRows.length < 2) {
    return [];
  }

  const headers = rawRows[0].map((header) => header.trim());
  const indexMap = Object.fromEntries(headers.map((header, index) => [header, index]));

  return rawRows.slice(1).map((cells) => {
    const read = (header) => cells[indexMap[header]] ?? "";
    const triggerValue = String(read("Signal Trigger")).trim();
    const nextEarningsRaw = read("Next Earnings").trim();
    const parsedDate = nextEarningsRaw ? new Date(nextEarningsRaw) : null;
    const normalizedDate = parsedDate && !Number.isNaN(parsedDate.getTime())
      ? parsedDate.toISOString().slice(0, 10)
      : "2026-05-01";

    return enrichRow({
      ticker: read("Ticker").trim().toUpperCase(),
      atrPercent: numberOrNull(read("ATR%")) ?? 0,
      ivRank: numberOrNull(read("IV Rank")) ?? 0,
      nextEarnings: normalizedDate,
      price: numberOrNull(read("Price")) ?? 0,
      eps: numberOrNull(read("EPS")) ?? 0,
      pe: numberOrNull(read("PE")),
      daysUntilEarnings: numberOrNull(read("Days until earnings")) ?? 0,
      setupRec: read("Setup Rec").trim() || "Watchlist",
      urgency: read('"Urgency"').trim() || "Watchlist",
      signalTrigger: triggerValue === "1" || triggerValue.toLowerCase().includes("true") || triggerValue.includes("✅"),
      confidence: numberOrNull(read("Confidence (3 MAX)")) ?? 0,
      ivRankChange: numberOrNull(read("IV Rank Change (5-day delta)")) ?? 0,
      atrZScore: numberOrNull(read("ATR% Z-Score")) ?? 0,
      atr20Day: numberOrNull(read("20 Day ATR")),
      rec1: read("REC 1-13").trim() || "N/A",
      rec2: read("Rec2").trim() || "N/A",
      valueScore: numberOrNull(read("Value Score")) ?? 0,
      momentumScore: numberOrNull(read("Momentum Score")) ?? 0,
      squeezeScore: numberOrNull(read("Squeeze Score")) ?? 0,
      readyScore: numberOrNull(read("Ready Score")) ?? 0,
      priority: numberOrNull(read("Priority")),
    });
  }).filter((row) => row.ticker);
}

function parseGoogleSheetUrl(sheetUrl) {
  try {
    const parsed = new URL(sheetUrl);
    const match = parsed.pathname.match(/\/spreadsheets\/d\/([a-zA-Z0-9-_]+)/);
    const spreadsheetId = match?.[1];
    const gid = parsed.searchParams.get("gid") || parsed.hash.match(/gid=(\d+)/)?.[1] || "0";

    if (!spreadsheetId) {
      return null;
    }

    return { spreadsheetId, gid };
  } catch {
    return null;
  }
}

function googleValue(cell) {
  if (!cell) {
    return "";
  }
  if (cell.f !== null && cell.f !== undefined) {
    return cell.f;
  }
  if (cell.v === null || cell.v === undefined) {
    return "";
  }
  return String(cell.v);
}

function loadGoogleSheetTable(sheetUrl) {
  const parsed = parseGoogleSheetUrl(sheetUrl);

  if (!parsed) {
    return Promise.reject(new Error("Invalid Google Sheets URL"));
  }

  return new Promise((resolve, reject) => {
    const callbackName = `__pipboySheet_${Date.now()}_${Math.floor(Math.random() * 10000)}`;
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error("Timed out loading sheet data"));
    }, 12000);

    const script = document.createElement("script");
    const query = new URLSearchParams({
      gid: parsed.gid,
      headers: "1",
      tqx: `out:json;responseHandler:${callbackName}`,
    });

    function cleanup() {
      window.clearTimeout(timeout);
      delete window[callbackName];
      script.remove();
    }

    window[callbackName] = (response) => {
      cleanup();

      if (!response?.table) {
        reject(new Error("Sheet response did not include tabular data"));
        return;
      }

      const headers = response.table.cols.map((column) => column.label?.trim() || column.id?.trim() || "");
      const rows = response.table.rows.map((entry) =>
        entry.c.map((cell) => googleValue(cell)),
      );

      resolve([headers, ...rows]);
    };

    script.onerror = () => {
      cleanup();
      reject(new Error("Could not load the Google Sheets endpoint"));
    };

    script.src = `https://docs.google.com/spreadsheets/d/${parsed.spreadsheetId}/gviz/tq?${query.toString()}`;
    document.body.appendChild(script);
  });
}

async function syncGoogleSheetPublic(sheetUrl) {
  const parsed = parseGoogleSheetUrl(sheetUrl);
  if (!parsed) {
    setSheetStatus("That link does not look like a Google Sheet.", "status-risk");
    return;
  }

  setSheetStatus("Attempting public sheet sync...", "muted");
  sheetPublicSyncButton.disabled = true;

  try {
    const rawRows = await loadGoogleSheetTable(sheetUrl);
    const parsedRows = normalizeCSVRows(rawRows);

    if (!parsedRows.length) {
      throw new Error("Connected, but the expected tracker columns were not found");
    }

    state.rows = parsedRows;
    state.selectedTicker = parsedRows[0]?.ticker ?? null;
    state.sourceLabel = `Live Sheet | gid ${parsed.gid}`;
    localStorage.setItem(SHEET_STORAGE_KEY, sheetUrl);
    populateFilters();
    setSheetStatus(`Live sync complete: ${parsedRows.length} rows loaded.`, "status-ready");
    render();
    forgeSnapshot(false);
  } catch (error) {
    state.sourceLabel = "Sample cache";
    updateSyncLabel();
    setSheetStatus(
      "Public sync is blocked. Use Google authorization for private sheets instead.",
      "status-risk",
    );
  } finally {
    sheetPublicSyncButton.disabled = false;
  }
}

async function ensureGoogleToken(clientId) {
  if (!clientId) {
    throw new Error("Missing Google OAuth client ID");
  }

  await waitForGoogleIdentity();

  if (accessTokenIsFresh()) {
    return state.auth.accessToken;
  }

  return new Promise((resolve, reject) => {
    const tokenClient = window.google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: GOOGLE_SHEETS_SCOPE,
      callback: (response) => {
        if (response?.error) {
          reject(new Error(response.error));
          return;
        }

        state.auth.accessToken = response.access_token;
        state.auth.tokenExpiresAt = Date.now() + Number(response.expires_in || 0) * 1000;
        resolve(response.access_token);
      },
    });

    tokenClient.requestAccessToken({
      prompt: "consent",
    });
  });
}

async function googleApiFetch(url, accessToken) {
  const response = await fetch(url, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  });

  if (!response.ok) {
    throw new Error(`Google API request failed with ${response.status}`);
  }

  return response.json();
}

async function loadPrivateSheetRows(sheetUrl, accessToken) {
  const parsed = parseGoogleSheetUrl(sheetUrl);

  if (!parsed) {
    throw new Error("That link does not look like a Google Sheet");
  }

  const metadata = await googleApiFetch(
    `https://sheets.googleapis.com/v4/spreadsheets/${parsed.spreadsheetId}?fields=sheets.properties(sheetId,title)`,
    accessToken,
  );
  const sheet = metadata.sheets?.find(
    (entry) => String(entry.properties?.sheetId) === String(parsed.gid),
  );

  if (!sheet?.properties?.title) {
    throw new Error("Could not resolve the tab name from the sheet link");
  }

  const escapedTitle = sheet.properties.title.replace(/'/g, "''");
  const range = `'${escapedTitle}'!A:ZZ`;
  const values = await googleApiFetch(
    `https://sheets.googleapis.com/v4/spreadsheets/${parsed.spreadsheetId}/values/${encodeURIComponent(range)}?majorDimension=ROWS`,
    accessToken,
  );

  return values.values || [];
}

async function syncGoogleSheetPrivate() {
  const sheetUrl = sheetUrlInput.value.trim();
  const clientId = googleClientIdInput.value.trim();

  if (!sheetUrl) {
    setSheetStatus("Paste a Google Sheets link first.", "status-caution");
    return;
  }

  if (!clientId) {
    setSheetStatus("Paste your Google OAuth Web Client ID first.", "status-caution");
    return;
  }

  if (window.location.protocol === "file:") {
    setSheetStatus("Google OAuth requires a real origin like http://localhost:8000, not a file URL.", "status-risk");
    return;
  }

  setSheetStatus("Opening Google consent flow...", "muted");
  sheetAuthSyncButton.disabled = true;

  try {
    const accessToken = await ensureGoogleToken(clientId);
    const rawRows = await loadPrivateSheetRows(sheetUrl, accessToken);
    const parsedRows = normalizeCSVRows(rawRows);

    if (!parsedRows.length) {
      throw new Error("Connected, but the expected tracker columns were not found");
    }

    localStorage.setItem(SHEET_STORAGE_KEY, sheetUrl);
    localStorage.setItem(GOOGLE_CLIENT_ID_STORAGE_KEY, clientId);
    state.rows = parsedRows;
    state.selectedTicker = parsedRows[0]?.ticker ?? null;
    state.sourceLabel = "Private Google Sheet";
    populateFilters();
    setSheetStatus(`Private sheet sync complete: ${parsedRows.length} rows loaded.`, "status-ready");
    render();
    forgeSnapshot(false);
  } catch (error) {
    const message = String(error.message || error);
    const authClosed =
      message.includes("popup_closed") ||
      message.includes("access_denied") ||
      message.includes("user_cancel");

    setSheetStatus(
      authClosed
        ? "Google authorization was canceled before the sheet finished syncing."
        : `Private sheet sync failed. ${message}`,
      "status-risk",
    );
  } finally {
    sheetAuthSyncButton.disabled = false;
  }
}

function revokeGoogleAccess() {
  if (window.google?.accounts?.oauth2 && state.auth.accessToken) {
    window.google.accounts.oauth2.revoke(state.auth.accessToken, () => {
      state.auth.accessToken = null;
      state.auth.tokenExpiresAt = 0;
      setSheetStatus("Google access revoked for this dashboard session.", "status-caution");
    });
    return;
  }

  state.auth.accessToken = null;
  state.auth.tokenExpiresAt = 0;
  setSheetStatus("No active Google token was stored in this session.", "status-caution");
}

searchInput.addEventListener("input", (event) => {
  state.filters.search = event.target.value.trim().toLowerCase();
  render();
});

setupFilter.addEventListener("change", (event) => {
  state.filters.setup = event.target.value;
  render();
});

urgencyFilter.addEventListener("change", (event) => {
  state.filters.urgency = event.target.value;
  render();
});

triggerFilter.addEventListener("change", (event) => {
  state.filters.trigger = event.target.value;
  render();
});

confidenceFilter.addEventListener("input", (event) => {
  state.filters.minConfidence = Number.parseInt(event.target.value, 10);
  confidenceValue.textContent = `${state.filters.minConfidence} / 3`;
  render();
});

csvInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) {
    return;
  }

  const text = await file.text();
  const parsed = normalizeCSVRows(parseCSV(text));

  if (parsed.length) {
    state.rows = parsed;
    state.selectedTicker = parsed[0].ticker;
    state.sourceLabel = `${file.name} imported`;
    populateFilters();
    setSheetStatus("CSV imported into local dashboard state.", "status-caution");
    render();
    forgeSnapshot(false);
  }
});

sheetAuthSyncButton.addEventListener("click", () => {
  syncGoogleSheetPrivate();
});

sheetPublicSyncButton.addEventListener("click", () => {
  const sheetUrl = sheetUrlInput.value.trim();
  if (!sheetUrl) {
    setSheetStatus("Paste a Google Sheets link first.", "status-caution");
    return;
  }
  syncGoogleSheetPublic(sheetUrl);
});

sheetRevokeButton.addEventListener("click", () => {
  revokeGoogleAccess();
});

forgeSnapshotButton.addEventListener("click", () => {
  forgeSnapshot(false);
});

sendBriefButton.addEventListener("click", () => {
  forgeSnapshot(true);
});

testSmtpButton.addEventListener("click", () => {
  testSmtpDelivery();
});

copyBriefButton.addEventListener("click", () => {
  if (!state.latestBrief) {
    briefStatus.textContent = "No brief is loaded yet.";
    return;
  }
  copyTextWithStatus(state.latestBrief, "Morning brief copied to clipboard.");
});

emailBriefButton.addEventListener("click", () => {
  if (!state.latestBrief) {
    briefStatus.textContent = "No brief is loaded yet.";
    return;
  }

  const subject = encodeURIComponent("Morning Conviction Brief");
  const body = encodeURIComponent(state.latestBrief);
  window.location.href = `mailto:?subject=${subject}&body=${body}`;
  briefStatus.textContent = "Email draft opened with the current morning brief.";
});

copyTicketsButton.addEventListener("click", () => {
  if (!state.latestTickets) {
    briefStatus.textContent = "No paper tickets are loaded yet.";
    return;
  }
  copyTextWithStatus(state.latestTickets, "Paper trade tickets copied to clipboard.");
});

populateFilters();
sheetUrlInput.value = localStorage.getItem(SHEET_STORAGE_KEY) || DEFAULT_SHEET_URL;
googleClientIdInput.value = localStorage.getItem(GOOGLE_CLIENT_ID_STORAGE_KEY) || "";
state.selectedTicker = getFilteredRows()[0]?.ticker ?? null;
setSheetStatus("Using sample cache until Google authorization succeeds.", "muted");
refreshBackendStatus().finally(() => {
  render();
});
