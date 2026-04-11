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
const BACKEND_REFRESH_INTERVAL_MS = 60_000;

const state = {
  rows: sampleData.map(enrichRow),
  selectedTicker: null,
  selectedDistrict: "hall",
  sourceLabel: "Sample cache",
  latestBrief: "",
  latestTickets: "",
  latestLongTerm: "",
  backend: {
    available: false,
    smtpConfigured: false,
    lastSnapshotAt: null,
    opsStatus: null,
    watchdogStatus: null,
    approvalQueue: null,
    executionQueue: null,
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
const longTermSummary = document.getElementById("longterm-summary");
const longTermCandidatesEl = document.getElementById("longterm-candidates");
const campaignSummary = document.getElementById("campaign-summary");
const campaignStats = document.getElementById("campaign-stats");
const questBoard = document.getElementById("quest-board");
const townActors = document.getElementById("town-actors");
const executionSummary = document.getElementById("execution-summary");
const executionCandidates = document.getElementById("execution-candidates");
const townSummary = document.getElementById("town-summary");
const townMap = document.getElementById("town-map");
const districtFocus = document.getElementById("district-focus");
const townDialogue = document.getElementById("town-dialogue");
const lootVault = document.getElementById("loot-vault");
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

function valuationBonus(pe) {
  if (!Number.isFinite(pe) || pe <= 0) {
    return 0;
  }
  if (pe <= 20) {
    return 0.55;
  }
  if (pe <= 35) {
    return 0.35;
  }
  if (pe <= 50) {
    return 0.12;
  }
  return -0.18;
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

function buildAccumulationBias(score) {
  if (score >= 4.4) {
    return {
      label: "Accumulate",
      tone: "hot",
      note: "Conviction is high and the name is calm enough to buy without chasing it.",
    };
  }

  if (score >= 3.2) {
    return {
      label: "Nibble",
      tone: "wild",
      note: "The name is worth building slowly, but the discount is not screaming yet.",
    };
  }

  return {
    label: "Wait For Weakness",
    tone: "cold",
    note: "You may want the company, but the price still does not deserve urgency.",
  };
}

function buildAccumulationReasons(row) {
  const reasons = [];
  if (row.valueScore >= 1) {
    reasons.push("value stack is still doing real work");
  }
  if (row.squeezeScore >= 1) {
    reasons.push("the name is compressed instead of euphoric");
  }
  if (row.momentumScore <= 0.35) {
    reasons.push("the move is not already extended");
  }
  if (row.readiness <= 68) {
    reasons.push("it is not in full chase mode");
  }
  if (row.eps > 0) {
    reasons.push("the business is still printing earnings");
  }
  if (Number.isFinite(row.pe) && row.pe > 0 && row.pe <= 35) {
    reasons.push("valuation still lives in a sane range");
  }
  return reasons.length ? reasons.slice(0, 3) : ["conviction is intact, but price heat is still restrained"];
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
  const priorityValue = Number.isFinite(row.priority)
    ? row.priority
    : row.valueScore + row.momentumScore + row.squeezeScore + row.readyScore;
  const priority = round(priorityValue, 2);
  const [scoreLeader, scoreLeaderValue] = dominantScore(row);
  const actionBias = buildActionBias(row, priority);
  const readinessValue = Math.round(readiness);
  const longTermScoreValue = clamp(
    row.valueScore * 1.9 +
      row.squeezeScore * 1.1 +
      clamp(1.6 - row.momentumScore, 0, 1.6) +
      clamp((78 - readinessValue) / 30, 0, 1.2) +
      (row.daysUntilEarnings >= 10 ? 0.45 : row.daysUntilEarnings >= 5 ? 0.1 : -0.25) +
      (row.eps > 0 ? 0.35 : -0.2) +
      valuationBonus(row.pe) +
      (row.signalTrigger ? -0.18 : 0.15) +
      (row.setupRec === "Avoid" ? -0.35 : 0),
    0,
    9.99,
  );
  const longTermScore = round(longTermScoreValue, 2);
  const accumulationBias = buildAccumulationBias(longTermScoreValue);
  const discountReasons = buildAccumulationReasons({
    ...row,
    readiness: readinessValue,
  });

  return {
    ...row,
    priority,
    scoreLeader,
    scoreLeaderValue: round(scoreLeaderValue, 2),
    actionBias,
    longTermScore,
    accumulationBias,
    discountReasons,
    readiness: readinessValue,
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
  const executionQueue = state.backend.executionQueue;
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
      label: "Execution Ready",
      value: executionQueue?.activeReadyCount ?? 0,
      tone: (executionQueue?.activeReadyCount ?? 0) > 0 ? "status-ready" : "status-caution",
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
  if (executionQueue?.items?.length) {
    messages.push(
      `Execution desk: ${executionQueue.activeReadyCount} ready, ${round(executionQueue.stagedRiskUnits || 0, 2)} / ${round(executionQueue.dailyRiskBudget || 0, 2)} risk units staged.`,
    );
    if (executionQueue.readyTickers?.length) {
      messages.push(`Broker review queue: ${executionQueue.readyTickers.join(", ")}`);
    }
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

function buildCampaignRank(score, readyCount, openQuests) {
  if (readyCount > 0 && score >= 82) {
    return {
      label: "Act IV: Siege Window",
      tone: "hot",
      note: "Broker-ready raids exist. This is a review-and-route posture, not a dreaming posture.",
    };
  }
  if (openQuests >= 4 && score >= 70) {
    return {
      label: "Act III: War Council",
      tone: "wild",
      note: "The board is crowded with real quests. Prioritization matters more than more ideas.",
    };
  }
  if (score >= 55) {
    return {
      label: "Act II: Ember Patrol",
      tone: "wild",
      note: "The town has movement, but most names still need proof, patience, or a cleaner lane.",
    };
  }
  return {
    label: "Act I: Quiet Vigil",
    tone: "cold",
    note: "The machine is healthy, but conviction is still in scouting mode. Better that than forcing a fight.",
  };
}

function buildCampaignState(rows) {
  const eligible = getEligibleCandidates(rows);
  const longTerm = getLongTermCandidates(rows);
  const queue = state.backend.executionQueue || {};
  const ops = state.backend.opsStatus;
  const watchdog = state.backend.watchdogStatus;
  const pendingCount =
    queue.pendingCount ??
    (state.backend.approvalQueue?.items?.filter((item) => item.approvalStatus === "pending").length || 0);
  const rejectedCount =
    queue.rejectedCount ??
    (state.backend.approvalQueue?.items?.filter((item) => item.approvalStatus === "rejected").length || 0);
  const readyCount = queue.activeReadyCount || 0;
  const openQuests = eligible.length + longTerm.length;

  let score = 28;
  if (ops?.ok) {
    score += 18;
  } else if (ops) {
    score -= 12;
  }
  if (watchdog?.ok) {
    score += 12;
  } else if (watchdog) {
    score -= 8;
  }
  if (state.backend.smtpConfigured) {
    score += 5;
  }
  score += Math.min(eligible.length * 4, 18);
  score += Math.min(readyCount * 10, 20);
  score += Math.min(longTerm.length * 3, 12);
  score -= Math.min(rejectedCount * 2, 8);
  score = clamp(Math.round(score), 0, 100);

  return {
    score,
    rank: buildCampaignRank(score, readyCount, openQuests),
    readyCount,
    pendingCount,
    rejectedCount,
    openQuests,
    warChest: round((queue.dailyRiskBudget || 0) - (queue.stagedRiskUnits || 0), 2),
    riskBudget: round(queue.dailyRiskBudget || 0, 2),
    topRaid: eligible[0] || rows[0] || null,
    topMerchant: longTerm[0] || null,
    lastUpdate: formatBackendDate(queue.updatedAt || queue.generatedAt || ops?.generatedAt || state.backend.lastSnapshotAt),
  };
}

function buildQuestForRow(row, type, rank, executionItem) {
  if (type === "raid") {
    const status =
      executionItem?.intentStatus === "approval-ready"
        ? { label: "At Gate", tone: "hot" }
        : executionItem?.approvalStatus === "rejected"
          ? { label: "Buried", tone: "cold" }
          : row.signalTrigger
            ? { label: "Await Writ", tone: "wild" }
            : { label: "Need Trigger", tone: "cold" };
    return {
      ticker: row.ticker,
      type: "Raid Quest",
      glyph: `R${rank}`,
      status,
      meta: `${row.setupRec} | ${row.daysUntilEarnings}d | ${row.readiness}% readiness`,
      reward: `Priority ${row.priority} | ${row.rec1}`,
      note: executionItem?.nextStep || row.actionBias.note,
    };
  }

  if (type === "merchant") {
    return {
      ticker: row.ticker,
      type: "Merchant Quest",
      glyph: `M${rank}`,
      status: { label: "Discount Watch", tone: row.accumulationBias.tone },
      meta: `Long-term ${row.longTermScore} | Value ${round(row.valueScore, 2)} | Heat ${round(row.momentumScore, 2)}`,
      reward: row.discountReasons.join(" | "),
      note: row.accumulationBias.note,
    };
  }

  return {
    ticker: row.ticker,
    type: "Scout Quest",
    glyph: `S${rank}`,
    status: row.signalTrigger ? { label: "Track Closely", tone: "wild" } : { label: "Scout Only", tone: "cold" },
    meta: `${row.setupRec} | ${row.daysUntilEarnings}d | confidence ${row.confidence} / 3`,
    reward: `IV ${round(row.ivRank, 1)} | ATR ${round(row.atrPercent, 1)}`,
    note: row.actionBias.note,
  };
}

function buildCampaignQuests(rows) {
  const executionByTicker = Object.fromEntries((state.backend.executionQueue?.items || []).map((item) => [item.ticker, item]));
  const quests = [];
  const seen = new Set();

  getEligibleCandidates(rows)
    .slice(0, 3)
    .forEach((row, index) => {
      seen.add(row.ticker);
      quests.push(buildQuestForRow(row, "raid", index + 1, executionByTicker[row.ticker]));
    });

  getLongTermCandidates(rows)
    .filter((row) => !seen.has(row.ticker))
    .slice(0, 2)
    .forEach((row, index) => {
      seen.add(row.ticker);
      quests.push(buildQuestForRow(row, "merchant", index + 1, executionByTicker[row.ticker]));
    });

  rows
    .filter((row) => !seen.has(row.ticker))
    .filter((row) => row.readiness >= 62 || row.confidence >= 2)
    .slice(0, 2)
    .forEach((row, index) => {
      quests.push(buildQuestForRow(row, "scout", index + 1, executionByTicker[row.ticker]));
    });

  return quests.slice(0, 6);
}

function buildTownActors(rows) {
  const queue = state.backend.executionQueue || {};
  const ops = state.backend.opsStatus;
  const watchdog = state.backend.watchdogStatus;
  const longTerm = getLongTermCandidates(rows);
  const topLongTerm = longTerm[0];
  const pendingCount =
    queue.pendingCount ??
    (state.backend.approvalQueue?.items?.filter((item) => item.approvalStatus === "pending").length || 0);

  return [
    {
      glyph: "GK",
      name: "Gatekeeper",
      status: pendingCount ? `${pendingCount} writs awaiting approval` : "No names crowding the gate",
      note: pendingCount
        ? "Approve only the names you would actually route in the real world."
        : "The gate is clear. No forced decisions are needed right now.",
      tone: pendingCount ? "wild" : "cold",
    },
    {
      glyph: "QM",
      name: "Quartermaster",
      status: `${round((queue.dailyRiskBudget || 0) - (queue.stagedRiskUnits || 0), 2)} / ${round(queue.dailyRiskBudget || 0, 2)} risk units free`,
      note:
        (queue.activeReadyCount || 0) > 0
          ? `${queue.activeReadyCount} raids are armed for broker review. The rest stay sheathed.`
          : "Nothing is over-armed right now. The treasury still has room, but the desk is behaving.",
      tone: (queue.activeReadyCount || 0) > 0 ? "hot" : "wild",
    },
    {
      glyph: "MT",
      name: "Merchant",
      status: topLongTerm ? `${topLongTerm.ticker} leads the discount lane` : "No quality bargains on the table",
      note: topLongTerm
        ? `${topLongTerm.discountReasons.join(", ")}. Buy the business, not the adrenaline.`
        : "The vault stays patient when names are expensive or overheated.",
      tone: topLongTerm ? topLongTerm.accumulationBias.tone : "cold",
    },
    {
      glyph: "AR",
      name: "Archivist",
      status: ops?.ok && watchdog?.ok ? "Briefs, logs, and patrols intact" : "Records need operator review",
      note:
        ops?.generatedAt || state.backend.lastSnapshotAt
          ? `Last machine heartbeat: ${formatBackendDate(ops?.generatedAt || state.backend.lastSnapshotAt)}.`
          : "No fresh records were found yet.",
      tone: ops?.ok && watchdog?.ok ? "hot" : "cold",
    },
  ];
}

function renderCampaignBoard(rows) {
  const stateView = buildCampaignState(rows);
  const quests = buildCampaignQuests(rows);
  const actors = buildTownActors(rows);
  const raidLead = stateView.topRaid ? `${stateView.topRaid.ticker} is the current raid leader.` : "No raid leader is active.";
  const merchantLead = stateView.topMerchant
    ? `${stateView.topMerchant.ticker} is the cleanest discount merchant target.`
    : "No merchant target has earned a discount posture yet.";

  campaignSummary.textContent = `${stateView.rank.label}. Campaign score ${stateView.score}/100. ${stateView.openQuests} open quests are on the board, ${stateView.readyCount} raids are broker-ready, and the town still has ${stateView.warChest} risk units free. ${raidLead} ${merchantLead} ${stateView.rank.note}`;
  campaignStats.innerHTML = [
    { label: "Campaign Score", value: `${stateView.score}/100` },
    { label: "Open Quests", value: stateView.openQuests },
    { label: "Raids Armed", value: stateView.readyCount },
    { label: "War Chest", value: `${stateView.warChest} RU` },
  ]
    .map(
      (item) => `
        <div class="metric-card">
          <span>${item.label}</span>
          <strong>${item.value}</strong>
        </div>
      `,
    )
    .join("");

  questBoard.innerHTML = quests.length
    ? quests
        .map(
          (quest) => `
            <button class="quest-card" data-ticker="${quest.ticker}" type="button">
              <div class="quest-head">
                <span class="quest-rank">${quest.glyph}</span>
                <div>
                  <p class="quest-type">${quest.type}</p>
                  <p><strong>${quest.ticker}</strong></p>
                  <p class="quest-meta">${quest.meta}</p>
                </div>
                <span class="move-chip ${quest.status.tone}">${quest.status.label}</span>
              </div>
              <p class="quest-reward">${quest.reward}</p>
              <p class="candidate-note">${quest.note}</p>
            </button>
          `,
        )
        .join("")
    : `
      <div class="quest-card">
        <p><strong>No open quests under the current filter stack.</strong></p>
        <p class="candidate-note">The town is quiet for a reason. Ease the filters or wait for the tape to offer a real fight.</p>
      </div>
    `;

  townActors.innerHTML = actors
    .map(
      (actor) => `
        <div class="actor-card">
          <div class="actor-head">
            <span class="actor-glyph">${actor.glyph}</span>
            <div>
              <p class="quest-type">${actor.name}</p>
              <p><strong>${actor.status}</strong></p>
            </div>
            <span class="move-chip ${actor.tone}">${actor.tone === "hot" ? "Armed" : actor.tone === "wild" ? "Watching" : "Quiet"}</span>
          </div>
          <p class="actor-note">${actor.note}</p>
        </div>
      `,
    )
    .join("");

  questBoard.querySelectorAll("button[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTicker = button.dataset.ticker;
      render();
    });
  });
}

function getScoutCandidates(rows) {
  const eligibleTickers = new Set(getEligibleCandidates(rows).map((row) => row.ticker));
  const longTermTickers = new Set(getLongTermCandidates(rows).map((row) => row.ticker));
  return rows
    .filter((row) => !eligibleTickers.has(row.ticker) && !longTermTickers.has(row.ticker))
    .filter((row) => row.readiness >= 56 || row.confidence >= 2 || row.signalTrigger)
    .slice(0, 3);
}

function buildTownDistricts(rows) {
  const campaign = buildCampaignState(rows);
  const queue = state.backend.executionQueue || {};
  const merchant = campaign.topMerchant;
  const scouts = getScoutCandidates(rows);
  const raidLead = campaign.topRaid;
  const ops = state.backend.opsStatus;
  const watchdog = state.backend.watchdogStatus;

  return [
    {
      key: "gate",
      name: "Hellgate",
      face: "Raid Queue",
      tone: campaign.readyCount > 0 ? "hot" : campaign.pendingCount > 0 ? "wild" : "cold",
      status:
        campaign.readyCount > 0
          ? `${campaign.readyCount} raid${campaign.readyCount === 1 ? "" : "s"} armed`
          : campaign.pendingCount > 0
            ? `${campaign.pendingCount} writs awaiting judgment`
            : "Gate stands quiet",
      resident: "Gatekeeper Sereth",
      focusTicker: raidLead?.ticker || "",
      note: raidLead
        ? `${raidLead.ticker} is the champion closest to the wall. Approvals turn waiting names into marching orders here.`
        : "When conviction rises, this is where short-term raid quests gather before they earn a writ.",
      x: 66,
      y: 208,
    },
    {
      key: "hall",
      name: "War Hall",
      face: "Conviction Board",
      tone: campaign.openQuests >= 5 ? "hot" : campaign.openQuests >= 3 ? "wild" : "cold",
      status: `${campaign.openQuests} active quests`,
      resident: "The War Council",
      focusTicker: raidLead?.ticker || merchant?.ticker || "",
      note: "This is the strategy room. It decides whether the town is raiding, scouting, or hoarding patience.",
      x: 238,
      y: 108,
    },
    {
      key: "market",
      name: "Ash Market",
      face: "Long-Term Lane",
      tone: merchant ? merchant.accumulationBias.tone : "cold",
      status: merchant ? `${merchant.ticker} leads the bargain stalls` : "No real bargains today",
      resident: "Merchant Nyra",
      focusTicker: merchant?.ticker || "",
      note: merchant
        ? `${merchant.ticker} is today's best discount story. This stall is for conviction buys, not adrenaline buys.`
        : "The market waits for real discounts instead of inventing cheapness where none exists.",
      x: 438,
      y: 208,
    },
    {
      key: "forge",
      name: "Broker Forge",
      face: "Execution Desk",
      tone: (queue.activeReadyCount || 0) > 0 ? "hot" : (queue.pendingCount || 0) > 0 ? "wild" : "cold",
      status:
        (queue.activeReadyCount || 0) > 0
          ? `${queue.activeReadyCount} ticket${queue.activeReadyCount === 1 ? "" : "s"} can be reviewed`
          : `${queue.pendingCount || 0} still blocked by approval`,
      resident: "Quartermaster Varo",
      focusTicker: queue.readyTickers?.[0] || raidLead?.ticker || "",
      note:
        (queue.activeReadyCount || 0) > 0
          ? "This forge is hot. Ready names can be turned into broker-review tickets here."
          : "The forge stays cautious until a name clears approval, trigger, and risk budget.",
      x: 604,
      y: 122,
    },
    {
      key: "archive",
      name: "Bone Archive",
      face: "Ops Record",
      tone: ops?.ok && watchdog?.ok ? "hot" : "cold",
      status: ops?.generatedAt ? `Last chronicle ${formatBackendDate(ops.generatedAt)}` : "No chronicle yet",
      resident: "Archivist Malek",
      focusTicker: "",
      note:
        ops?.ok && watchdog?.ok
          ? "The records are clean and the machine chorus is behaving."
          : "This hall remembers every broken relay and missing dawn cycle.",
      x: 694,
      y: 278,
    },
    {
      key: "watchtower",
      name: "Watchtower",
      face: "Scouts and patrols",
      tone: scouts.length ? "wild" : "cold",
      status: scouts.length ? `${scouts[0].ticker} is under watch` : "No scouts are circling",
      resident: "Scout Ilya",
      focusTicker: scouts[0]?.ticker || "",
      note: scouts.length
        ? `${scouts[0].ticker} is the cleanest unfinished story in the hills.`
        : "The watchtower is quiet when nothing deserves partial attention.",
      x: 494,
      y: 62,
    },
  ];
}

function buildTownMood(rows) {
  const campaign = buildCampaignState(rows);
  if (campaign.readyCount > 0) {
    return {
      title: "Raid Night",
      note: "The forge is lit, the gate is awake, and the town is arguing over which names deserve blood and risk.",
    };
  }
  if (campaign.topMerchant) {
    return {
      title: "Night Market",
      note: `${campaign.topMerchant.ticker} has the merchants whispering. The village feels patient, watchful, and a little greedy in the best way.`,
    };
  }
  return {
    title: "Ashen Curfew",
    note: "No one is rushing. The town is alive, but it is choosing patience over chaos tonight.",
  };
}

function renderDistrictFocus(rows, districts) {
  const district = districts.find((item) => item.key === state.selectedDistrict) || districts[1] || districts[0];
  const mood = buildTownMood(rows);
  districtFocus.innerHTML = `
    <div class="actor-card district-focus-card">
      <div class="actor-head">
        <span class="actor-glyph">${district.name.split(" ").map((part) => part[0]).slice(0, 2).join("")}</span>
        <div>
          <p class="quest-type">${district.name}</p>
          <p><strong>${district.status}</strong></p>
          <p class="actor-meta">${district.face} | ${district.resident}</p>
        </div>
        <span class="move-chip ${district.tone}">${mood.title}</span>
      </div>
      <p class="actor-note">${district.note}</p>
      <p class="actor-note"><strong>Town mood:</strong> ${mood.note}</p>
      ${
        district.focusTicker
          ? `<button class="approval-button ticket-copy-button district-jump-button" data-ticker="${district.focusTicker}" type="button">Inspect ${district.focusTicker}</button>`
          : ""
      }
    </div>
  `;

  districtFocus.querySelectorAll("[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTicker = button.dataset.ticker;
      render();
    });
  });
}

function renderTownMap(rows, districts) {
  const mood = buildTownMood(rows);
  const eligible = getEligibleCandidates(rows);
  const longTerm = getLongTermCandidates(rows);
  const scouts = getScoutCandidates(rows);
  const sprites = [
    {
      key: "raid",
      tone: eligible[0] ? "hot" : "wild",
      label: eligible[0]?.ticker || "RAID",
      start: 0,
      dur: "14s",
      path: "M 120 248 C 196 208, 224 176, 272 156 C 348 124, 416 180, 470 248",
    },
    {
      key: "merchant",
      tone: longTerm[0] ? longTerm[0].accumulationBias.tone : "wild",
      label: longTerm[0]?.ticker || "MERC",
      start: "2s",
      dur: "18s",
      path: "M 272 156 C 356 130, 408 166, 470 248 C 544 256, 590 212, 634 170",
    },
    {
      key: "scout",
      tone: scouts[0] ? "wild" : "cold",
      label: scouts[0]?.ticker || "SCOUT",
      start: "4s",
      dur: "12s",
      path: "M 516 96 C 560 112, 602 136, 634 170 C 666 206, 694 248, 714 314",
    },
  ];
  const stars = [
    [86, 58, 1.8],
    [126, 42, 1.3],
    [196, 72, 1.5],
    [284, 48, 1.6],
    [356, 76, 1.2],
    [448, 42, 1.7],
    [532, 64, 1.4],
    [664, 52, 1.3],
    [744, 74, 1.9],
  ];
  const roads = [
    { x1: 120, y1: 248, x2: 272, y2: 156 },
    { x1: 272, y1: 156, x2: 470, y2: 248 },
    { x1: 470, y1: 248, x2: 634, y2: 170 },
    { x1: 634, y1: 170, x2: 714, y2: 314 },
    { x1: 516, y1: 96, x2: 634, y2: 170 },
  ];

  townMap.innerHTML = `
    <svg viewBox="0 0 820 360" role="img" aria-label="Inferno town map">
      <defs>
        <linearGradient id="townSky" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#24133b" />
          <stop offset="48%" stop-color="#3b1f2e" />
          <stop offset="100%" stop-color="#1e0d0e" />
        </linearGradient>
        <linearGradient id="roadGlow" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="rgba(199, 160, 106, 0.08)" />
          <stop offset="100%" stop-color="rgba(255, 106, 61, 0.18)" />
        </linearGradient>
      </defs>
      <rect class="town-sky" x="14" y="22" width="792" height="112" rx="18"></rect>
      <circle class="town-moon" cx="706" cy="80" r="22"></circle>
      ${stars
        .map(
          ([x, y, r]) => `
            <circle class="town-star" cx="${x}" cy="${y}" r="${r}">
              <animate attributeName="opacity" values="0.4;0.95;0.5" dur="${6 + r}s" repeatCount="indefinite"></animate>
            </circle>
          `,
        )
        .join("")}
      <rect class="town-ground" x="14" y="22" width="792" height="320" rx="18"></rect>
      <g class="town-garden">
        <rect x="334" y="254" width="92" height="38" rx="10"></rect>
        <path d="M 346 286 L 350 264 M 364 286 L 368 262 M 382 286 L 386 260 M 400 286 L 404 264" />
      </g>
      <path class="town-river" d="M 26 300 C 150 256, 236 338, 356 296 S 560 226, 794 284"></path>
      ${roads
        .map(
          (road) => `
            <path class="town-road" d="M ${road.x1} ${road.y1} C ${(road.x1 + road.x2) / 2} ${road.y1 - 14}, ${(road.x1 + road.x2) / 2} ${road.y2 + 16}, ${road.x2} ${road.y2}"></path>
          `,
        )
        .join("")}
      ${districts
        .map((district) => {
          const roofPoints = `${district.x - 32},${district.y} ${district.x},${district.y - 28} ${district.x + 32},${district.y}`;
          return `
            <g class="town-district ${district.tone} ${state.selectedDistrict === district.key ? "selected" : ""}" data-district="${district.key}" role="button" tabindex="0" aria-label="${district.name}">
              <circle class="district-aura ${district.tone}" cx="${district.x}" cy="${district.y + 6}" r="42"></circle>
              <rect class="district-wall ${district.tone}" x="${district.x - 28}" y="${district.y}" width="56" height="38" rx="8"></rect>
              <polygon class="district-roof ${district.tone}" points="${roofPoints}"></polygon>
              <rect class="district-door" x="${district.x - 7}" y="${district.y + 16}" width="14" height="22" rx="4"></rect>
              <circle class="district-lantern ${district.tone}" cx="${district.x + 22}" cy="${district.y + 14}" r="4"></circle>
              <text class="district-label" x="${district.x}" y="${district.y + 56}" text-anchor="middle">${district.name}</text>
              <text class="district-sub-label" x="${district.x}" y="${district.y + 70}" text-anchor="middle">${district.face}</text>
            </g>
          `;
        })
        .join("")}
      ${sprites
        .map(
          (sprite) => `
            <g class="villager-sprite ${sprite.tone}">
              <circle r="7"></circle>
              <text y="-13" text-anchor="middle">${sprite.label}</text>
              <animateMotion dur="${sprite.dur}" begin="${sprite.start}" repeatCount="indefinite" rotate="auto">
                <mpath href="#${sprite.key}-path"></mpath>
              </animateMotion>
            </g>
            <path id="${sprite.key}-path" class="hidden-path" d="${sprite.path}"></path>
          `,
        )
        .join("")}
      <text class="town-mood-label" x="48" y="56">${mood.title}</text>
    </svg>
  `;

  townMap.querySelectorAll("[data-district]").forEach((districtNode) => {
    const selectDistrict = () => {
      state.selectedDistrict = districtNode.dataset.district;
      render();
    };
    districtNode.addEventListener("click", selectDistrict);
    districtNode.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectDistrict();
      }
    });
  });
}

function buildTownDialogue(rows) {
  const queue = state.backend.executionQueue || {};
  const eligible = getEligibleCandidates(rows);
  const longTerm = getLongTermCandidates(rows);
  const scouts = getScoutCandidates(rows);
  const merchant = longTerm[0];
  const raidLead = eligible[0];
  const approvalQueue = state.backend.approvalQueue?.items || [];
  const pendingCount = approvalQueue.filter((item) => item.approvalStatus === "pending").length;

  return [
    {
      name: "Gatekeeper Sereth",
      districtKey: "gate",
      tone: pendingCount ? "wild" : "cold",
      ticker: raidLead?.ticker || "",
      line: pendingCount
        ? `${pendingCount} names still stand outside the gate. ${raidLead ? `${raidLead.ticker} is first in line.` : "No champion has stepped forward yet."}`
        : "The gate is clear. No approvals are rotting in the queue tonight.",
    },
    {
      name: "Quartermaster Varo",
      districtKey: "forge",
      tone: (queue.activeReadyCount || 0) > 0 ? "hot" : "wild",
      ticker: queue.readyTickers?.[0] || raidLead?.ticker || "",
      line:
        (queue.activeReadyCount || 0) > 0
          ? `${queue.readyTickers[0]} is armed for broker review. ${round(queue.stagedRiskUnits || 0, 2)} risk units are already spoken for.`
          : `${round((queue.dailyRiskBudget || 0) - (queue.stagedRiskUnits || 0), 2)} risk units remain. Spend them only on names you would defend in daylight.`,
    },
    {
      name: "Merchant Nyra",
      districtKey: "market",
      tone: merchant ? merchant.accumulationBias.tone : "cold",
      ticker: merchant?.ticker || "",
      line: merchant
        ? `${merchant.ticker} is the cleanest bargain in the market. ${merchant.discountReasons[0] || "The price has cooled without killing conviction."}`
        : "The stalls are full of overpriced junk. Keep your gold in your pocket.",
    },
    {
      name: "Archivist Malek",
      districtKey: "archive",
      tone: state.backend.opsStatus?.ok && state.backend.watchdogStatus?.ok ? "hot" : "cold",
      ticker: "",
      line:
        state.backend.opsStatus?.generatedAt
          ? `The last chronicle was written ${formatBackendDate(state.backend.opsStatus.generatedAt)}. The machine remembers what the flesh forgets.`
          : "No chronicle has been sealed yet. The archive waits for the first run.",
    },
    {
      name: "Scout Ilya",
      districtKey: "watchtower",
      tone: scouts.length ? "wild" : "cold",
      ticker: scouts[0]?.ticker || "",
      line: scouts.length
        ? `${scouts[0].ticker} is moving in the outskirts. Not ready for a raid, but too alive to ignore.`
        : "The hills are quiet. No side quests deserve the party's time right now.",
    },
  ];
}

function buildLootDrops(rows) {
  const queue = state.backend.executionQueue || {};
  const raid = getEligibleCandidates(rows)[0];
  const merchant = getLongTermCandidates(rows)[0];
  const scout = getScoutCandidates(rows)[0];
  const ready = (queue.items || []).find((item) => item.intentStatus === "approval-ready");
  const opsHealthy = state.backend.opsStatus?.ok && state.backend.watchdogStatus?.ok;

  return [
    {
      type: "Raid Writ",
      rarity: raid ? "Legendary" : "Dormant",
      tone: raid ? "hot" : "cold",
      ticker: raid?.ticker || "",
      name: raid ? `${raid.ticker} Bloodseal` : "Unclaimed Bloodseal",
      note: raid ? `Primary route ${raid.rec1}. ${raid.actionBias.note}` : "No full-conviction raid trophy has dropped yet.",
    },
    {
      type: "Merchant Relic",
      rarity: merchant ? "Rare" : "Dormant",
      tone: merchant ? merchant.accumulationBias.tone : "cold",
      ticker: merchant?.ticker || "",
      name: merchant ? `${merchant.ticker} Ash Coin` : "Empty Coin Purse",
      note: merchant ? merchant.discountReasons.join(" | ") : "No long-term bargain deserves a purchase ritual today.",
    },
    {
      type: "Scout Totem",
      rarity: scout ? "Uncommon" : "Dormant",
      tone: scout ? "wild" : "cold",
      ticker: scout?.ticker || "",
      name: scout ? `${scout.ticker} Watch Totem` : "Extinguished Totem",
      note: scout ? `${scout.daysUntilEarnings}d to earnings | ${scout.confidence} / 3 confidence` : "No worthy scout signal is circling the town.",
    },
    {
      type: "Forge Sigil",
      rarity: ready ? "Legendary" : "Common",
      tone: ready ? "hot" : "wild",
      ticker: ready?.ticker || "",
      name: ready ? `${ready.ticker} Broker Sigil` : "Dormant Forge Sigil",
      note: ready ? ready.nextStep : "The forge is lit, but no ticket is fully armed for review.",
    },
    {
      type: "Machine Charm",
      rarity: opsHealthy ? "Rare" : "Cracked",
      tone: opsHealthy ? "hot" : "cold",
      ticker: "",
      name: opsHealthy ? "Watchdog Lantern" : "Cracked Relay Charm",
      note: opsHealthy ? "Automation patrols are alive and the dawn relay is holding." : "Something in the machine chorus needs attention.",
    },
  ];
}

function renderTownBoard(rows) {
  const campaign = buildCampaignState(rows);
  const districts = buildTownDistricts(rows);
  const dialogues = buildTownDialogue(rows);
  const loot = buildLootDrops(rows);
  const mood = buildTownMood(rows);

  townSummary.textContent = `${campaign.rank.label}. ${mood.title} has settled over the village. ${campaign.readyCount} raids are near the gate, ${campaign.pendingCount} still need writs, and the market ${campaign.topMerchant ? `is whispering about ${campaign.topMerchant.ticker}` : "is not offering a true bargain yet"}.`;
  renderTownMap(rows, districts);
  renderDistrictFocus(rows, districts);

  townDialogue.innerHTML = dialogues
    .map(
      (actor) => `
        <button class="actor-card" ${actor.ticker ? `data-ticker="${actor.ticker}"` : ""} data-district="${actor.districtKey}" type="button">
          <div class="actor-head">
            <span class="actor-glyph">${actor.name.split(" ").map((part) => part[0]).slice(0, 2).join("")}</span>
            <div>
              <p class="quest-type">${actor.name}</p>
              <p><strong>${actor.line}</strong></p>
            </div>
            <span class="move-chip ${actor.tone}">${actor.tone === "hot" ? "Burning" : actor.tone === "wild" ? "Restless" : "Quiet"}</span>
          </div>
        </button>
      `,
    )
    .join("");

  lootVault.innerHTML = loot
    .map(
      (item) => `
        <button class="quest-card loot-card" ${item.ticker ? `data-ticker="${item.ticker}"` : ""} type="button">
          <div class="quest-head">
            <span class="quest-rank">${item.rarity.slice(0, 2).toUpperCase()}</span>
            <div>
              <p class="quest-type">${item.type}</p>
              <p><strong>${item.name}</strong></p>
              <p class="quest-meta">${item.rarity}</p>
            </div>
            <span class="move-chip ${item.tone}">${item.tone === "hot" ? "Lit" : item.tone === "wild" ? "Live" : "Dormant"}</span>
          </div>
          <p class="candidate-note">${item.note}</p>
        </button>
      `,
    )
    .join("");

  townDialogue.querySelectorAll(".actor-card").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.ticker) {
        state.selectedTicker = button.dataset.ticker;
      }
      if (button.dataset.district) {
        state.selectedDistrict = button.dataset.district;
      }
      render();
    });
  });

  lootVault.querySelectorAll("[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTicker = button.dataset.ticker;
      render();
    });
  });
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

function getLongTermCandidates(rows) {
  return rows
    .filter((row) => Number(row.longTermScore) >= 2.8)
    .filter((row) => row.valueScore >= 0.75)
    .filter((row) => row.eps > 0 || Number(row.priority) >= 3.6)
    .sort(
      (a, b) =>
        Number(b.longTermScore) - Number(a.longTermScore) ||
        b.valueScore - a.valueScore ||
        a.readiness - b.readiness ||
        a.daysUntilEarnings - b.daysUntilEarnings,
    )
    .slice(0, 5);
}

function buildLongTermBrief(rows) {
  const candidates = getLongTermCandidates(rows);
  const lines = ["Long-Term Accumulation Lane", ""];

  if (!candidates.length) {
    lines.push("No names are cheap enough in the current stack to justify a conviction buy today.");
    return {
      text: lines.join("\n"),
      candidates,
    };
  }

  candidates.forEach((row, index) => {
    lines.push(
      `${index + 1}. ${row.ticker} | ${row.accumulationBias.label} | score ${row.longTermScore} | ${row.discountReasons.join("; ")}`,
    );
  });
  lines.push("");
  lines.push("Rule:");
  lines.push("Only add here if you would still want to own the name if the market did nothing for the next six to twelve months.");

  return {
    text: lines.join("\n"),
    candidates,
  };
}

function renderAccumulationDesk(rows) {
  const candidates = getLongTermCandidates(rows);
  if (!candidates.length) {
    longTermSummary.textContent = "No long-term names are calm enough and cheap enough to deserve accumulation right now.";
    longTermCandidatesEl.innerHTML = `
      <div class="candidate-card accumulation-card">
        <p><strong>No accumulation buys earned conviction yet.</strong></p>
        <p class="muted">That is a feature, not a bug. This lane exists to stop you from buying quality names at bad prices.</p>
      </div>
    `;
    return;
  }

  longTermSummary.textContent = `${candidates[0].ticker} is the cleanest discount candidate right now at a ${candidates[0].longTermScore} accumulation score. This lane rewards value, compression, and names that are not already in full chase mode.`;
  longTermCandidatesEl.innerHTML = candidates
    .map((row, index) => `
      <button class="candidate-card accumulation-card" data-ticker="${row.ticker}" type="button">
        <div class="candidate-head">
          <div>
            <p><strong>#${index + 1} ${row.ticker}</strong></p>
            <p class="candidate-meta">Long-term score ${row.longTermScore} | Value ${round(row.valueScore, 2)} | Heat ${round(row.momentumScore, 2)}</p>
            <p class="candidate-meta">${row.daysUntilEarnings}d to earnings | ${row.signalTrigger ? "trigger live" : "calm tape"} | priority ${row.priority}</p>
          </div>
          <span class="move-chip ${row.accumulationBias.tone}">${row.accumulationBias.label}</span>
        </div>
        <div class="candidate-tags">
          <span class="pill">${row.setupRec}</span>
          <span class="pill">${row.eps > 0 ? "Positive EPS" : "Speculative EPS"}</span>
          <span class="pill">${Number.isFinite(row.pe) && row.pe > 0 ? `PE ${round(row.pe, 1)}` : "PE N/A"}</span>
        </div>
        ${renderScoreSigils(row)}
        <p class="candidate-note">${row.accumulationBias.note}</p>
        <div class="reason-list">
          ${row.discountReasons.map((reason) => `<span class="reason-pill">${reason}</span>`).join("")}
        </div>
      </button>
    `)
    .join("");

  longTermCandidatesEl.querySelectorAll("button[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTicker = button.dataset.ticker;
      render();
    });
  });
}

function renderExecutionDesk() {
  const queue = state.backend.executionQueue;
  if (!queue?.items?.length) {
    executionSummary.textContent = "No execution intents are staged yet. The clerk is waiting on a fresh approval queue.";
    executionCandidates.innerHTML = `
      <div class="candidate-card">
        <p><strong>No order intents are armed.</strong></p>
        <p class="muted">The desk is still behaving safely. Nothing should touch a broker surface until approval, trigger, and risk budget all line up.</p>
      </div>
    `;
    return;
  }

  executionSummary.textContent = `${queue.activeReadyCount} intents are broker-ready inside a ${queue.dailyRiskBudget} risk-unit day. ${queue.pendingCount || 0} still need human approval, ${queue.rejectedCount || 0} are buried, and the staged risk stack is ${round(queue.stagedRiskUnits || 0, 2)} units. Last clerk update: ${formatBackendDate(queue.updatedAt || queue.generatedAt)}.`;
  executionCandidates.innerHTML = `
    <div class="execution-actions">
      <button id="approval-reset-button" type="button">Reset Approval Desk</button>
    </div>
    <div class="execution-stats">
      <div class="metric-card">
        <span>Ready</span>
        <strong class="status-ready">${queue.activeReadyCount}</strong>
      </div>
      <div class="metric-card">
        <span>Pending</span>
        <strong class="status-caution">${queue.pendingCount || 0}</strong>
      </div>
      <div class="metric-card">
        <span>Rejected</span>
        <strong class="status-risk">${queue.rejectedCount || 0}</strong>
      </div>
      <div class="metric-card">
        <span>Risk Staged</span>
        <strong>${round(queue.stagedRiskUnits || 0, 2)} / ${round(queue.dailyRiskBudget || 0, 2)}</strong>
      </div>
    </div>
    ${queue.items
    .map((item) => {
      const tone =
        item.intentStatus === "approval-ready"
          ? "hot"
          : item.approvalStatus === "approved"
            ? "wild"
            : "cold";
      const blockText = item.intentBlocks?.length ? item.intentBlocks.join("; ") : "all checks clear";
      return `
        <div class="candidate-card">
          <div class="candidate-head">
            <div>
              <p><strong>#${item.rank} ${item.ticker}</strong></p>
              <p class="candidate-meta">${item.setupRec} | ${item.routeFamily} | tier ${item.convictionTier}</p>
              <p class="candidate-meta">Risk ${item.riskUnits} | ${item.daysUntilEarnings}d | ${item.signalTrigger ? "trigger live" : "trigger wait"}</p>
            </div>
            <span class="move-chip ${tone}">${item.intentStatus}</span>
          </div>
          <div class="candidate-tags">
            <span class="pill">${item.approvalStatus}</span>
            <span class="pill">${item.primaryRoute}</span>
            <span class="pill">${item.secondaryRoute}</span>
          </div>
          <p class="candidate-note"><strong>Next step:</strong> ${item.nextStep}</p>
          <div class="candidate-actions">
            <button class="approval-button approve" data-approval-ticker="${item.ticker}" data-approval-status="approved" type="button" ${item.approvalStatus === "approved" ? "disabled" : ""}>Approve</button>
            <button class="approval-button reject" data-approval-ticker="${item.ticker}" data-approval-status="rejected" type="button" ${item.approvalStatus === "rejected" ? "disabled" : ""}>Reject</button>
            <button class="approval-button pending" data-approval-ticker="${item.ticker}" data-approval-status="pending" type="button" ${item.approvalStatus === "pending" ? "disabled" : ""}>Reset</button>
            <button class="approval-button ticket-copy-button" data-ticket-index="${item.rank - 1}" type="button">Copy Ticket</button>
          </div>
          <p class="candidate-note">${blockText}</p>
        </div>
      `;
    })
    .join("")}
  `;

  const resetButton = document.getElementById("approval-reset-button");
  if (resetButton) {
    resetButton.addEventListener("click", async () => {
      executionSummary.textContent = "Resetting approval desk...";
      try {
        await resetApprovalQueue();
        await refreshBackendStatus();
        render();
      } catch {
        executionSummary.textContent = "Could not reset the approval desk.";
      }
    });
  }

  executionCandidates.querySelectorAll("[data-approval-ticker]").forEach((button) => {
    button.addEventListener("click", async () => {
      const ticker = button.dataset.approvalTicker;
      const status = button.dataset.approvalStatus;
      executionSummary.textContent = `Updating ${ticker} to ${status}...`;
      try {
        await updateApprovalStatus(ticker, status);
        await refreshBackendStatus();
        render();
      } catch {
        executionSummary.textContent = `Could not update ${ticker}.`;
      }
    });
  });

  executionCandidates.querySelectorAll("[data-ticket-index]").forEach((button) => {
    button.addEventListener("click", async () => {
      const index = Number(button.dataset.ticketIndex);
      const item = queue.items[index];
      if (!item?.ticketText) {
        executionSummary.textContent = "Ticket blueprint was unavailable for that name.";
        return;
      }
      await copyExecutionTicket(item);
    });
  });
}

function buildMorningBrief(rows) {
  const eligible = getEligibleCandidates(rows);
  const longTerm = buildLongTermBrief(rows);
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
  lines.push("");
  lines.push(...longTerm.text.split("\n"));

  return {
    text: lines.join("\n"),
    eligible,
    recommended,
    longTermCandidates: longTerm.candidates,
    longTermText: longTerm.text,
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
  state.latestLongTerm = brief.longTermText;
}

async function copyTextWithStatus(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text);
    briefStatus.textContent = successMessage;
  } catch {
    briefStatus.textContent = "Clipboard access failed. Your browser may require a secure context or manual copy.";
  }
}

async function copyExecutionTicket(item) {
  try {
    await navigator.clipboard.writeText(item.ticketText);
    executionSummary.textContent = `${item.ticker} ticket blueprint copied for broker review.`;
  } catch {
    executionSummary.textContent = `Clipboard access failed while copying ${item.ticker}.`;
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

async function updateApprovalStatus(ticker, status) {
  const result = await apiRequest("/api/approval", {
    method: "POST",
    body: JSON.stringify({
      ticker,
      status,
      action: "set",
    }),
  });
  state.backend.approvalQueue = result.approvalQueue || null;
  state.backend.executionQueue = result.executionQueue || null;
}

async function resetApprovalQueue() {
  const result = await apiRequest("/api/approval", {
    method: "POST",
    body: JSON.stringify({
      action: "reset",
    }),
  });
  state.backend.approvalQueue = result.approvalQueue || null;
  state.backend.executionQueue = result.executionQueue || null;
}

function buildSnapshotPayload(rows) {
  const longTerm = buildLongTermBrief(rows);
  return {
    generatedAt: new Date().toISOString(),
    sourceLabel: state.sourceLabel,
    brief: state.latestBrief,
    tickets: state.latestTickets,
    longTermBrief: longTerm.text,
    eligibleTickers: getEligibleCandidates(rows).map((row) => row.ticker),
    longTermTickers: longTerm.candidates.map((row) => row.ticker),
    longTermRows: longTerm.candidates,
    executionQueue: state.backend.executionQueue,
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
    state.backend.executionQueue = status.executionQueue || null;
  } catch {
    state.backend.available = false;
    state.backend.smtpConfigured = false;
    state.backend.lastSnapshotAt = null;
    state.backend.opsStatus = null;
    state.backend.watchdogStatus = null;
    state.backend.approvalQueue = null;
    state.backend.executionQueue = null;
  }
}

function startBackendHeartbeat() {
  window.setInterval(async () => {
    if (document.visibilityState === "hidden") {
      return;
    }
    await refreshBackendStatus();
    render();
  }, BACKEND_REFRESH_INTERVAL_MS);
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
      <div class="metric-card">
        <span>Long-Term Score</span>
        <strong>${row.longTermScore}</strong>
      </div>
      <div class="metric-card">
        <span>Accumulation Bias</span>
        <strong class="${row.accumulationBias.tone === "hot" ? "status-ready" : row.accumulationBias.tone === "wild" ? "status-caution" : "status-risk"}">${row.accumulationBias.label}</strong>
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
  renderCampaignBoard(rows);
  renderTownBoard(rows);
  renderSignalRibbon(rows);
  renderConvictionEngine(rows);
  renderAccumulationDesk(rows);
  renderExecutionDesk();
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
startBackendHeartbeat();
