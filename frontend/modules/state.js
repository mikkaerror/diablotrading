/**
 * frontend/modules/state.js
 *
 * Purpose:
 * This module is the keep beneath the trading cathedral. It owns the living desk
 * state, preserves relics in local storage, and updates the dashboard with
 * immutable patch flows so the rest of the app can act like systems inside one
 * coherent Diablo-flavored world instead of a pile of globals.
 */

/**
 * Default local sheet URL used when nothing has been persisted yet.
 *
 * @type {string}
 */
export const DEFAULT_SHEET_URL = "";

/**
 * Local storage key for the connected Google Sheet URL.
 *
 * @type {string}
 */
export const SHEET_STORAGE_KEY = "pipboy-earnings-sheet-url";

/**
 * Local storage key for the Google OAuth Web client ID.
 *
 * @type {string}
 */
export const GOOGLE_CLIENT_ID_STORAGE_KEY = "pipboy-google-client-id";

/**
 * Local storage key for the latest forged snapshot payload.
 *
 * @type {string}
 */
export const SNAPSHOT_STORAGE_KEY = "inferno-snapshot-cache";

/**
 * Local storage key for the simulated trade portfolio / loot relics.
 *
 * @type {string}
 */
export const PORTFOLIO_STORAGE_KEY = "inferno-portfolio-cache";

/**
 * Local storage key for soul-bound portfolio history snapshots.
 *
 * @type {string}
 */
export const PORTFOLIO_HISTORY_STORAGE_KEY = "inferno-portfolio-history-cache";

/**
 * Maximum number of soul-bound history states kept in local storage.
 *
 * @type {number}
 */
export const MAX_PORTFOLIO_HISTORY = 7;

/**
 * Heartbeat cadence for backend state refresh.
 *
 * @type {number}
 */
export const BACKEND_REFRESH_INTERVAL_MS = 60_000;

/**
 * Default filter state.
 *
 * @type {{search:string,setup:string,urgency:string,trigger:string,minConfidence:number}}
 */
export const DEFAULT_FILTERS = Object.freeze({
  search: "",
  setup: "all",
  urgency: "all",
  trigger: "all",
  minConfidence: 0,
});

/**
 * Sample closed trades used to seed future inventory and relic systems.
 *
 * These are intentionally stable so the desk has deterministic starter loot until
 * real journaled trades replace them.
 *
 * @type {ReadonlyArray<Record<string, any>>}
 */
export const SAMPLE_PORTFOLIO = Object.freeze([
  { id: "relic-enph-01", ticker: "ENPH", side: "long", setup: "Straddle", outcome: "win", rarity: "orange", pnlPercent: 18.4, closedAt: "2026-03-18", lore: "Solar blood moon payout." },
  { id: "relic-nvda-02", ticker: "NVDA", side: "long", setup: "Vertical Call", outcome: "win", rarity: "purple", pnlPercent: 11.1, closedAt: "2026-03-07", lore: "Boss raid survived volatility." },
  { id: "relic-tt-03", ticker: "TT", side: "long", setup: "Vertical Call", outcome: "win", rarity: "blue", pnlPercent: 6.3, closedAt: "2026-02-25", lore: "Quiet forge profit." },
  { id: "relic-fslr-04", ticker: "FSLR", side: "long", setup: "Straddle", outcome: "loss", rarity: "green", pnlPercent: -4.6, closedAt: "2026-02-13", lore: "The sun dimmed early." },
  { id: "relic-ge-05", ticker: "GE", side: "long", setup: "Vertical Call", outcome: "win", rarity: "purple", pnlPercent: 9.2, closedAt: "2026-01-30", lore: "Forge smoke turned to gold." },
  { id: "relic-sbac-06", ticker: "SBAC", side: "long", setup: "Vertical Call", outcome: "win", rarity: "blue", pnlPercent: 7.1, closedAt: "2026-01-12", lore: "Tower tribute collected." },
  { id: "relic-tsla-07", ticker: "TSLA", side: "long", setup: "Straddle", outcome: "loss", rarity: "white", pnlPercent: -2.8, closedAt: "2025-12-20", lore: "Fire too loud, edge too thin." },
  { id: "relic-hubb-08", ticker: "HUBB", side: "long", setup: "Long-Term", outcome: "win", rarity: "orange", pnlPercent: 13.9, closedAt: "2025-11-28", lore: "A merchant relic worth defending." },
]);

const DEFAULT_BACKEND_STATE = Object.freeze({
  available: false,
  smtpConfigured: false,
  lastSnapshotAt: null,
  opsStatus: null,
  watchdogStatus: null,
  approvalQueue: null,
  executionQueue: null,
  liveAccountSync: null,
  livePositionReview: null,
  modelCommandCenter: null,
  centralCommand: null,
});

const DEFAULT_AUTH_STATE = Object.freeze({
  accessToken: null,
  tokenExpiresAt: 0,
});

/**
 * The live exported state object.
 *
 * We keep the binding stable for ES module consumers and replace the object
 * contents immutably via helper functions.
 *
 * @type {Record<string, any>}
 */
export const state = {};

function cloneBackendState() {
  return { ...DEFAULT_BACKEND_STATE };
}

function cloneAuthState() {
  return { ...DEFAULT_AUTH_STATE };
}

function readStorage(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage can fail in private contexts or browser-restricted environments.
  }
}

function removeStorage(key) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Ignore storage cleanup failures to avoid breaking the UI layer.
  }
}

function parseStoredJson(key, fallback) {
  const raw = readStorage(key);
  if (!raw) {
    return fallback;
  }

  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function clonePortfolioItems(portfolio) {
  return Array.isArray(portfolio) ? portfolio.map((item) => ({ ...item })) : [];
}

function buildPortfolioHistorySignature(portfolio) {
  return JSON.stringify(
    clonePortfolioItems(portfolio)
      .map((item) => Object.keys(item).sort().reduce((accumulator, key) => {
        accumulator[key] = item[key];
        return accumulator;
      }, {}))
      .sort((left, right) => String(left.id || left.ticker || "").localeCompare(String(right.id || right.ticker || ""))),
  );
}

/**
 * Create an immutable soul-bound portfolio snapshot entry.
 *
 * @param {Record<string, any>[]} portfolio - Current vault state.
 * @param {string} [reason="Vault reshaped"] - Human-readable snapshot reason.
 * @returns {Record<string, any>} Persistable history entry.
 */
function buildPortfolioHistoryEntry(portfolio, reason = "Vault reshaped") {
  const soulFlameAt = new Date().toISOString();
  const safePortfolio = clonePortfolioItems(portfolio);
  return {
    id: `soul-history-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    reason,
    savedAt: soulFlameAt,
    soulFlameAt,
    portfolio: safePortfolio,
    relicCount: safePortfolio.length,
    signature: buildPortfolioHistorySignature(safePortfolio),
  };
}

function appendPortfolioHistory(history, entry) {
  const safeHistory = Array.isArray(history) ? history.map((item) => ({ ...item, portfolio: clonePortfolioItems(item.portfolio) })) : [];
  const latest = safeHistory[0];
  if (latest?.signature === entry.signature) {
    return safeHistory;
  }
  return [entry, ...safeHistory].slice(0, MAX_PORTFOLIO_HISTORY);
}

function replaceState(nextState) {
  Object.keys(state).forEach((key) => {
    delete state[key];
  });
  Object.assign(state, nextState);
  return state;
}

/**
 * Load persisted sheet connection details.
 *
 * @returns {{sheetUrl:string,clientId:string}} Sheet URL and client ID.
 */
export function loadPersistedSheetConnection() {
  return {
    sheetUrl: readStorage(SHEET_STORAGE_KEY) || DEFAULT_SHEET_URL,
    clientId: readStorage(GOOGLE_CLIENT_ID_STORAGE_KEY) || "",
  };
}

/**
 * Persist the active sheet connection.
 *
 * @param {{sheetUrl?:string,clientId?:string}} connection - Persisted OAuth values.
 * @returns {{sheetUrl:string,clientId:string}} Normalized connection object.
 */
export function persistSheetConnection(connection = {}) {
  const normalized = {
    sheetUrl: connection.sheetUrl || DEFAULT_SHEET_URL,
    clientId: connection.clientId || "",
  };

  if (normalized.sheetUrl) {
    writeStorage(SHEET_STORAGE_KEY, normalized.sheetUrl);
  } else {
    removeStorage(SHEET_STORAGE_KEY);
  }

  if (normalized.clientId) {
    writeStorage(GOOGLE_CLIENT_ID_STORAGE_KEY, normalized.clientId);
  } else {
    removeStorage(GOOGLE_CLIENT_ID_STORAGE_KEY);
  }

  return normalized;
}

/**
 * Remove persisted sheet connection details.
 */
export function clearPersistedSheetConnection() {
  removeStorage(SHEET_STORAGE_KEY);
  removeStorage(GOOGLE_CLIENT_ID_STORAGE_KEY);
}

/**
 * Load the locally cached snapshot payload.
 *
 * @returns {Record<string, any>|null} Cached snapshot payload or null.
 */
export function loadSnapshotCache() {
  return parseStoredJson(SNAPSHOT_STORAGE_KEY, null);
}

/**
 * Persist a snapshot payload locally.
 *
 * @param {Record<string, any>} snapshot - Snapshot payload to cache.
 * @returns {Record<string, any>} The same snapshot payload.
 */
export function saveSnapshotCache(snapshot) {
  writeStorage(SNAPSHOT_STORAGE_KEY, JSON.stringify(snapshot));
  applyStatePatch({ snapshotCache: snapshot });
  return snapshot;
}

/**
 * Load the stored portfolio, falling back to seeded relics.
 *
 * @returns {Record<string, any>[]} Persisted or seeded portfolio entries.
 */
export function loadPortfolio() {
  const stored = parseStoredJson(PORTFOLIO_STORAGE_KEY, null);
  if (Array.isArray(stored) && stored.length) {
    return stored;
  }
  return SAMPLE_PORTFOLIO.map((item) => ({ ...item }));
}

/**
 * Load the persisted soul-bound portfolio history stack.
 *
 * If no history exists yet, we seed one from the current portfolio so the vault
 * always has a founding ember to return to.
 *
 * @param {Record<string, any>[]} [portfolio=loadPortfolio()] - Current vault state.
 * @returns {Record<string, any>[]} Persisted or seeded history entries.
 */
export function loadPortfolioHistory(portfolio = loadPortfolio()) {
  const stored = parseStoredJson(PORTFOLIO_HISTORY_STORAGE_KEY, null);
  if (Array.isArray(stored) && stored.length) {
    return stored.map((entry) => ({
      ...entry,
      portfolio: clonePortfolioItems(entry.portfolio),
    }));
  }

  const seededHistory = [buildPortfolioHistoryEntry(portfolio, "Founding ember")];
  writeStorage(PORTFOLIO_HISTORY_STORAGE_KEY, JSON.stringify(seededHistory));
  return seededHistory;
}

/**
 * Persist the portfolio to local storage.
 *
 * @param {Record<string, any>[]} [portfolio=state.portfolio] - Portfolio entries.
 * @returns {Record<string, any>[]} Persisted portfolio copy.
 */
export function savePortfolio(portfolio = state.portfolio) {
  const safePortfolio = clonePortfolioItems(portfolio);
  writeStorage(PORTFOLIO_STORAGE_KEY, JSON.stringify(safePortfolio));
  return safePortfolio;
}

/**
 * Persist the soul-bound portfolio history stack.
 *
 * @param {Record<string, any>[]} [history=state.portfolioHistory] - History entries.
 * @returns {Record<string, any>[]} Persisted history copy.
 */
export function savePortfolioHistory(history = state.portfolioHistory) {
  const safeHistory = Array.isArray(history)
    ? history.map((entry) => ({
        ...entry,
        portfolio: clonePortfolioItems(entry.portfolio),
      }))
    : [];
  writeStorage(PORTFOLIO_HISTORY_STORAGE_KEY, JSON.stringify(safeHistory));
  return safeHistory;
}

/**
 * Replace the portfolio with an immutable update and persist it.
 *
 * @param {Record<string, any>[]} portfolio - New portfolio list.
 * @param {{reason?:string}} [options={}] - Optional history metadata for the snapshot stack.
 * @returns {Record<string, any>[]} Updated portfolio.
 */
export function setPortfolio(portfolio, options = {}) {
  const nextPortfolio = clonePortfolioItems(portfolio);
  const currentSignature = buildPortfolioHistorySignature(state.portfolio || []);
  const nextSignature = buildPortfolioHistorySignature(nextPortfolio);
  if (currentSignature === nextSignature) {
    return state.portfolio;
  }

  const historyReason = options.reason || "Vault reshaped";
  const nextHistory = appendPortfolioHistory(
    state.portfolioHistory || [],
    buildPortfolioHistoryEntry(nextPortfolio, historyReason),
  );

  applyStatePatch({
    portfolio: nextPortfolio,
    portfolioHistory: nextHistory,
  });
  savePortfolio(nextPortfolio);
  savePortfolioHistory(nextHistory);
  return state.portfolio;
}

/**
 * Add a closed-trade relic to the portfolio.
 *
 * @param {Record<string, any>} item - Portfolio entry.
 * @returns {Record<string, any>[]} Updated portfolio.
 */
export function addPortfolioItem(item) {
  return setPortfolio([...(state.portfolio || []), { ...item }], {
    reason: `${item?.ticker || "Unknown"} soul-bound`,
  });
}

/**
 * Revert the live vault to a prior soul-bound snapshot.
 *
 * The revert itself becomes a new history entry so the player can undo the
 * undo if needed.
 *
 * @param {string} historyId - Snapshot entry identifier.
 * @returns {Record<string, any>[]} Updated live portfolio.
 */
export function revertPortfolioHistory(historyId) {
  const entry = (state.portfolioHistory || []).find((item) => item.id === historyId);
  if (!entry) {
    return state.portfolio;
  }

  return setPortfolio(entry.portfolio, {
    reason: `Reverted to ${entry.reason || "prior ember"}`,
  });
}

/**
 * Build the initial application state.
 *
 * @param {{sampleRows?:Record<string, any>[]}} [options={}] - Seed rows for the desk.
 * @returns {Record<string, any>} Fresh state object.
 */
export function createInitialState(options = {}) {
  const sampleRows = Array.isArray(options.sampleRows) ? [...options.sampleRows] : [];
  const snapshotCache = loadSnapshotCache();
  const portfolio = loadPortfolio();
  const portfolioHistory = loadPortfolioHistory(portfolio);

  return {
    rows: sampleRows,
    selectedTicker: null,
    selectedDistrict: "hall",
    sourceLabel: "Sample cache",
    latestBrief: snapshotCache?.brief || "",
    latestTickets: snapshotCache?.tickets || "",
    latestLongTerm: snapshotCache?.longTermBrief || "",
    snapshotCache,
    portfolio,
    portfolioHistory,
    backend: cloneBackendState(),
    auth: cloneAuthState(),
    filters: { ...DEFAULT_FILTERS },
  };
}

/**
 * Initialize the shared state object.
 *
 * @param {{sampleRows?:Record<string, any>[]}} [options={}] - Startup options.
 * @returns {Record<string, any>} The live exported state object.
 */
export function initializeState(options = {}) {
  return replaceState(createInitialState(options));
}

/**
 * Apply an immutable patch to the exported state object.
 *
 * @param {Record<string, any>} patch - Partial state update.
 * @returns {Record<string, any>} Updated live state.
 */
export function applyStatePatch(patch) {
  const hasRows = Object.prototype.hasOwnProperty.call(patch, "rows");
  const hasPortfolio = Object.prototype.hasOwnProperty.call(patch, "portfolio");
  const hasPortfolioHistory = Object.prototype.hasOwnProperty.call(patch, "portfolioHistory");
  const hasBackend = Object.prototype.hasOwnProperty.call(patch, "backend");
  const hasAuth = Object.prototype.hasOwnProperty.call(patch, "auth");
  const hasFilters = Object.prototype.hasOwnProperty.call(patch, "filters");

  const nextState = {
    ...state,
    ...patch,
    backend: hasBackend ? { ...state.backend, ...patch.backend } : state.backend,
    auth: hasAuth ? { ...state.auth, ...patch.auth } : state.auth,
    filters: hasFilters ? { ...state.filters, ...patch.filters } : state.filters,
    rows: hasRows ? [...patch.rows] : state.rows,
    portfolio: hasPortfolio ? clonePortfolioItems(patch.portfolio) : state.portfolio,
    portfolioHistory: hasPortfolioHistory
      ? patch.portfolioHistory.map((entry) => ({ ...entry, portfolio: clonePortfolioItems(entry.portfolio) }))
      : state.portfolioHistory,
  };
  return replaceState(nextState);
}

/**
 * Replace the desk rows and optionally update related selection metadata.
 *
 * @param {Record<string, any>[]} rows - Enriched desk rows.
 * @param {{selectedTicker?:string|null,sourceLabel?:string}} [options={}] - Coupled row metadata.
 * @returns {Record<string, any>[]} Updated rows.
 */
export function setRows(rows, options = {}) {
  applyStatePatch({
    rows,
    selectedTicker: options.selectedTicker ?? state.selectedTicker,
    sourceLabel: options.sourceLabel ?? state.sourceLabel,
  });
  return state.rows;
}

/**
 * Update the selected ticker.
 *
 * @param {string|null} ticker - Active ticker.
 * @returns {string|null} Selected ticker.
 */
export function setSelectedTicker(ticker) {
  applyStatePatch({ selectedTicker: ticker });
  return state.selectedTicker;
}

/**
 * Update the selected town district.
 *
 * @param {string} district - Active district key.
 * @returns {string} Selected district.
 */
export function setSelectedDistrict(district) {
  applyStatePatch({ selectedDistrict: district });
  return state.selectedDistrict;
}

/**
 * Update the dashboard source label.
 *
 * @param {string} sourceLabel - Human-readable source label.
 * @returns {string} Updated source label.
 */
export function setSourceLabel(sourceLabel) {
  applyStatePatch({ sourceLabel });
  return state.sourceLabel;
}

/**
 * Update the sheet/brief artifacts kept in memory.
 *
 * @param {{brief?:string,tickets?:string,longTerm?:string}} payload - Artifact strings.
 * @returns {{latestBrief:string,latestTickets:string,latestLongTerm:string}} Current artifact set.
 */
export function setLatestArtifacts(payload = {}) {
  applyStatePatch({
    latestBrief: payload.brief ?? state.latestBrief,
    latestTickets: payload.tickets ?? state.latestTickets,
    latestLongTerm: payload.longTerm ?? state.latestLongTerm,
  });
  return {
    latestBrief: state.latestBrief,
    latestTickets: state.latestTickets,
    latestLongTerm: state.latestLongTerm,
  };
}

/**
 * Apply a partial backend patch.
 *
 * @param {Record<string, any>} patch - Backend state patch.
 * @returns {Record<string, any>} Updated backend state.
 */
export function patchBackend(patch) {
  applyStatePatch({ backend: patch });
  return state.backend;
}

/**
 * Overwrite backend state from the `/api/status` payload shape.
 *
 * @param {Record<string, any>} status - Backend status payload.
 * @returns {Record<string, any>} Updated backend state.
 */
export function setBackendStatus(status) {
  applyStatePatch({
    backend: {
      available: true,
      smtpConfigured: Boolean(status.smtpConfigured),
      lastSnapshotAt: status.lastSnapshotAt || null,
      opsStatus: status.opsStatus || null,
      watchdogStatus: status.watchdogStatus || null,
      approvalQueue: status.approvalQueue || null,
      executionQueue: status.executionQueue || null,
      liveAccountSync: status.liveAccountSync || null,
      livePositionReview: status.livePositionReview || null,
      modelCommandCenter: status.modelCommandCenter || null,
      centralCommand: status.centralCommand || null,
    },
  });
  return state.backend;
}

/**
 * Reset backend state to an offline posture.
 *
 * @returns {Record<string, any>} Updated backend state.
 */
export function clearBackendStatus() {
  applyStatePatch({
    backend: cloneBackendState(),
  });
  return state.backend;
}

/**
 * Persist the current Google OAuth access token metadata.
 *
 * @param {string|null} accessToken - Active OAuth token.
 * @param {number} expiresInSeconds - Lifetime in seconds.
 * @returns {Record<string, any>} Updated auth state.
 */
export function setAuthToken(accessToken, expiresInSeconds) {
  applyStatePatch({
    auth: {
      accessToken,
      tokenExpiresAt: Date.now() + Number(expiresInSeconds || 0) * 1000,
    },
  });
  return state.auth;
}

/**
 * Clear any active OAuth token.
 *
 * @returns {Record<string, any>} Updated auth state.
 */
export function clearAuthToken() {
  applyStatePatch({
    auth: cloneAuthState(),
  });
  return state.auth;
}

/**
 * Check whether the current token is still fresh enough to reuse.
 *
 * The 15-second buffer avoids using a token that will expire mid-request.
 *
 * @param {Record<string, any>} [sourceState=state] - Optional alternate state object.
 * @returns {boolean} True when the token is still fresh.
 */
export function accessTokenIsFresh(sourceState = state) {
  return Boolean(sourceState.auth.accessToken && Date.now() < sourceState.auth.tokenExpiresAt - 15000);
}

/**
 * Update a single filter value immutably.
 *
 * @param {keyof typeof DEFAULT_FILTERS} name - Filter field name.
 * @param {string|number} value - Next filter value.
 * @returns {Record<string, any>} Updated filter state.
 */
export function updateFilter(name, value) {
  applyStatePatch({
    filters: {
      [name]: value,
    },
  });
  return state.filters;
}

/**
 * Get unique filter options from the current desk rows.
 *
 * @param {string} key - Row property to inspect.
 * @param {Record<string, any>} [sourceState=state] - Optional alternate state object.
 * @returns {string[]} Filter option list beginning with `all`.
 */
export function getUniqueOptions(key, sourceState = state) {
  return ["all", ...new Set((sourceState.rows || []).map((row) => row[key]).filter(Boolean))];
}

/**
 * Return the currently filtered row set.
 *
 * @param {Record<string, any>} [sourceState=state] - Optional alternate state object.
 * @returns {Record<string, any>[]} Filtered and ranked rows.
 */
export function getFilteredRows(sourceState = state) {
  return (sourceState.rows || [])
    .filter((row) => row.ticker.toLowerCase().includes(sourceState.filters.search))
    .filter((row) => sourceState.filters.setup === "all" || row.setupRec === sourceState.filters.setup)
    .filter((row) => sourceState.filters.urgency === "all" || row.urgency === sourceState.filters.urgency)
    .filter((row) => sourceState.filters.trigger === "all" || String(row.signalTrigger) === sourceState.filters.trigger)
    .filter((row) => row.confidence >= sourceState.filters.minConfidence)
    .sort((a, b) => b.readiness - a.readiness || b.priority - a.priority || a.daysUntilEarnings - b.daysUntilEarnings);
}
