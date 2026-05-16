/**
 * frontend/modules/ui/sheetControls.js
 *
 * Purpose:
 * This module owns the connector ritual: Google auth, sheet sync, backend
 * status refresh, snapshot forging, and the static dashboard control bindings.
 * It keeps the entry point focused on orchestration while the control tower
 * handles networked side effects and operator feedback.
 */

import { normalizeCSVRows, parseCSV } from "../dataProcessor.js";
import {
  accessTokenIsFresh,
  BACKEND_REFRESH_INTERVAL_MS,
  clearAuthToken,
  clearBackendStatus,
  DEFAULT_SHEET_URL,
  getFilteredRows,
  getUniqueOptions,
  loadPersistedSheetConnection,
  patchBackend,
  persistSheetConnection,
  saveSnapshotCache,
  setAuthToken,
  setBackendStatus,
  setRows,
  setSourceLabel,
  state,
  updateFilter,
} from "../state.js";
import { buildSnapshotPayload } from "./strategy.js";

const GOOGLE_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly";

/**
 * Set the sheet connector status message.
 *
 * @param {Record<string, any>} ui - Shared DOM refs.
 * @param {string} message - Human-readable status text.
 * @param {string} [tone="muted"] - Tone class suffix.
 */
export function setSheetStatus(ui, message, tone = "muted") {
  ui.sheetStatus.textContent = message;
  ui.sheetStatus.className = `connector-status ${tone}`;
}

/**
 * Return the current dashboard origin.
 *
 * @returns {string} Browser origin or empty string for file URLs.
 */
export function getDashboardOrigin() {
  if (window.location.protocol === "file:") {
    return "";
  }

  return window.location.origin;
}

/**
 * Return the fully qualified dashboard page URL.
 *
 * @returns {string} Browser page URL or empty string for file URLs.
 */
export function getDashboardPageUrl() {
  if (window.location.protocol === "file:") {
    return "";
  }

  return `${window.location.origin}${window.location.pathname}`;
}

/**
 * Check whether the current dashboard is running from GitHub Pages.
 *
 * @returns {boolean} True when hosted on github.io.
 */
export function isHostedDashboard() {
  return Boolean(window.location.hostname?.endsWith("github.io"));
}

/**
 * Render the OAuth setup helper copy.
 *
 * @param {Record<string, any>} ui - Shared DOM refs.
 */
export function renderOAuthGuide(ui) {
  if (!ui.sheetOauthHint) {
    return;
  }

  const origin = getDashboardOrigin();
  const pageUrl = getDashboardPageUrl();

  if (!origin) {
    ui.sheetOauthHint.textContent =
      "Google OAuth only works from a real origin like http://localhost:8000 or your GitHub Pages URL.";
  } else if (isHostedDashboard()) {
    ui.sheetOauthHint.textContent =
      `Hosted sync uses ${origin} as the required Google OAuth origin. If Google still says redirect_uri_mismatch, also allow ${pageUrl} in the same Web client and retry.`;
  } else {
    ui.sheetOauthHint.textContent = `Local sync uses ${origin} as the required Google OAuth origin.`;
  }

  if (ui.copyOauthOriginButton) {
    ui.copyOauthOriginButton.disabled = !origin;
  }
  if (ui.copyOauthPageButton) {
    ui.copyOauthPageButton.disabled = !pageUrl;
  }
}

/**
 * Translate raw Google auth failures into operator-friendly guidance.
 *
 * @param {string|Error} message - Raw error payload.
 * @returns {{tone:string,text:string}} UI status payload.
 */
export function buildGoogleAuthFailureMessage(message) {
  const rawMessage = String(message || "Unknown Google auth error");
  const normalized = rawMessage.toLowerCase();
  const origin = getDashboardOrigin();
  const pageUrl = getDashboardPageUrl();

  if (
    normalized.includes("popup_closed") ||
    normalized.includes("access_denied") ||
    normalized.includes("user_cancel")
  ) {
    return {
      tone: "status-caution",
      text: "Google authorization was canceled before the sheet finished syncing.",
    };
  }

  if (
    normalized.includes("redirect_uri_mismatch") ||
    normalized.includes("origin_mismatch") ||
    normalized.includes("timed out") ||
    normalized.includes("popup_failed_to_open")
  ) {
    if (isHostedDashboard()) {
      return {
        tone: "status-risk",
        text:
          `Hosted Google auth is not configured for this site yet. Add ${origin} to Authorized JavaScript origins for this OAuth Web client. ` +
          `If Google still reports redirect_uri_mismatch, also add ${pageUrl} to Authorized redirect URIs, then retry.`,
      };
    }

    if (origin) {
      return {
        tone: "status-risk",
        text: `Google auth is not configured for ${origin}. Add that origin to your Google OAuth Web client and retry.`,
      };
    }
  }

  return {
    tone: "status-risk",
    text: `Private sheet sync failed. ${rawMessage}`,
  };
}

/**
 * Populate the filter dropdowns from the current row set.
 *
 * @param {Record<string, any>} ui - Shared DOM refs.
 */
export function populateFilters(ui) {
  ui.setupFilter.innerHTML = getUniqueOptions("setupRec")
    .map((value) => `<option value="${value}">${value === "all" ? "All" : value}</option>`)
    .join("");

  ui.urgencyFilter.innerHTML = getUniqueOptions("urgency")
    .map((value) => `<option value="${value}">${value === "all" ? "All" : value}</option>`)
    .join("");
}

/**
 * Update the sync/source label in the header.
 *
 * @param {Record<string, any>} ui - Shared DOM refs.
 * @param {string} [label=state.sourceLabel] - Source label text.
 */
export function updateSyncLabel(ui, label = state.sourceLabel) {
  ui.syncTime.textContent = label;
}

/**
 * Hydrate the sheet connection controls from local storage.
 *
 * @param {Record<string, any>} ui - Shared DOM refs.
 */
export function hydratePersistedControls(ui) {
  const persistedConnection = loadPersistedSheetConnection();
  ui.sheetUrlInput.value = persistedConnection.sheetUrl || DEFAULT_SHEET_URL;
  ui.googleClientIdInput.value = persistedConnection.clientId || "";
  ui.confidenceValue.textContent = `${state.filters.minConfidence} / 3`;
}

/**
 * Check whether Google Identity Services is ready.
 *
 * @returns {boolean} True when the GIS token client exists.
 */
export function isGoogleReady() {
  return Boolean(window.google?.accounts?.oauth2);
}

/**
 * Wait for the Google Identity Services library to finish loading.
 *
 * @param {number} [timeoutMs=10000] - Maximum wait time.
 * @returns {Promise<void>} Resolves when GIS is ready.
 */
export function waitForGoogleIdentity(timeoutMs = 10000) {
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

/**
 * Parse a Google Sheets URL into its spreadsheet and gid identifiers.
 *
 * @param {string} sheetUrl - Google Sheets URL.
 * @returns {{spreadsheetId:string,gid:string}|null} Parsed identifiers or null.
 */
export function parseGoogleSheetUrl(sheetUrl) {
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

/**
 * Normalize a Google visualization cell into a plain value.
 *
 * @param {Record<string, any>|null|undefined} cell - Gviz cell payload.
 * @returns {string} Plain cell value.
 */
export function googleValue(cell) {
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

/**
 * Load Google Sheets public visualization data.
 *
 * @param {string} sheetUrl - Google Sheets URL.
 * @returns {Promise<string[][]>} Raw tabular values including headers.
 */
export function loadGoogleSheetTable(sheetUrl) {
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
      const rows = response.table.rows.map((entry) => entry.c.map((cell) => googleValue(cell)));

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

/**
 * Sync a publicly readable sheet into local state.
 *
 * @param {{ui:Record<string, any>,sheetUrl:string,render:()=>void}} context - Control context.
 */
export async function syncGoogleSheetPublic({ ui, sheetUrl, render }) {
  const parsed = parseGoogleSheetUrl(sheetUrl);
  if (!parsed) {
    setSheetStatus(ui, "That link does not look like a Google Sheet.", "status-risk");
    return;
  }

  setSheetStatus(ui, "Attempting public sheet sync...", "muted");
  ui.sheetPublicSyncButton.disabled = true;

  try {
    const rawRows = await loadGoogleSheetTable(sheetUrl);
    const parsedRows = normalizeCSVRows(rawRows);

    if (!parsedRows.length) {
      throw new Error("Connected, but the expected tracker columns were not found");
    }

    setRows(parsedRows, {
      selectedTicker: parsedRows[0]?.ticker ?? null,
      sourceLabel: `Live Sheet | gid ${parsed.gid}`,
    });
    persistSheetConnection({
      sheetUrl,
      clientId: ui.googleClientIdInput.value.trim(),
    });
    populateFilters(ui);
    setSheetStatus(ui, `Live sync complete: ${parsedRows.length} rows loaded.`, "status-ready");
    render();
    await forgeSnapshot(ui, false);
  } catch {
    setSourceLabel("Sample cache");
    updateSyncLabel(ui);
    setSheetStatus(
      ui,
      "Public sync is blocked. Use Google authorization for private sheets instead.",
      "status-risk",
    );
  } finally {
    ui.sheetPublicSyncButton.disabled = false;
  }
}

/**
 * Ensure a fresh Google OAuth access token exists.
 *
 * @param {string} clientId - Google OAuth Web Client ID.
 * @returns {Promise<string>} Access token.
 */
export async function ensureGoogleToken(clientId) {
  if (!clientId) {
    throw new Error("Missing Google OAuth client ID");
  }

  await waitForGoogleIdentity();

  if (accessTokenIsFresh()) {
    return state.auth.accessToken;
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    const timeoutId = window.setTimeout(() => {
      if (settled) {
        return;
      }

      settled = true;
      reject(new Error("Google authorization timed out before a token returned"));
    }, 20000);

    function rejectOnce(error) {
      if (settled) {
        return;
      }

      settled = true;
      window.clearTimeout(timeoutId);
      reject(error instanceof Error ? error : new Error(String(error)));
    }

    function resolveOnce(token) {
      if (settled) {
        return;
      }

      settled = true;
      window.clearTimeout(timeoutId);
      resolve(token);
    }

    const tokenClient = window.google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: GOOGLE_SHEETS_SCOPE,
      callback: (response) => {
        if (response?.error) {
          rejectOnce(new Error(response.error));
          return;
        }

        setAuthToken(response.access_token, response.expires_in || 0);
        resolveOnce(response.access_token);
      },
      error_callback: (error) => {
        rejectOnce(new Error(error?.type || error?.message || "google_auth_failed"));
      },
    });

    try {
      tokenClient.requestAccessToken({
        prompt: "consent",
      });
    } catch (error) {
      rejectOnce(error);
    }
  });
}

/**
 * Run an authenticated Google API request.
 *
 * @param {string} url - Google API URL.
 * @param {string} accessToken - Bearer token.
 * @returns {Promise<Record<string, any>>} Parsed JSON response.
 */
export async function googleApiFetch(url, accessToken) {
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

/**
 * Load private sheet rows via the Google Sheets API.
 *
 * @param {string} sheetUrl - Google Sheets URL.
 * @param {string} accessToken - Bearer token.
 * @returns {Promise<string[][]>} Raw row values.
 */
export async function loadPrivateSheetRows(sheetUrl, accessToken) {
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

/**
 * Sync a private sheet into local state using Google OAuth.
 *
 * @param {{ui:Record<string, any>,render:()=>void}} context - Control context.
 */
export async function syncGoogleSheetPrivate({ ui, render }) {
  const sheetUrl = ui.sheetUrlInput.value.trim();
  const clientId = ui.googleClientIdInput.value.trim();

  if (!sheetUrl) {
    setSheetStatus(ui, "Paste a Google Sheets link first.", "status-caution");
    return;
  }

  if (!clientId) {
    setSheetStatus(ui, "Paste your Google OAuth Web Client ID first.", "status-caution");
    return;
  }

  if (window.location.protocol === "file:") {
    setSheetStatus(ui, "Google OAuth requires a real origin like http://localhost:8000, not a file URL.", "status-risk");
    return;
  }

  setSheetStatus(ui, "Opening Google consent flow...", "muted");
  ui.sheetAuthSyncButton.disabled = true;

  try {
    const accessToken = await ensureGoogleToken(clientId);
    const rawRows = await loadPrivateSheetRows(sheetUrl, accessToken);
    const parsedRows = normalizeCSVRows(rawRows);

    if (!parsedRows.length) {
      throw new Error("Connected, but the expected tracker columns were not found");
    }

    persistSheetConnection({
      sheetUrl,
      clientId,
    });
    setRows(parsedRows, {
      selectedTicker: parsedRows[0]?.ticker ?? null,
      sourceLabel: "Private Google Sheet",
    });
    populateFilters(ui);
    setSheetStatus(ui, `Private sheet sync complete: ${parsedRows.length} rows loaded.`, "status-ready");
    render();
    await forgeSnapshot(ui, false);
  } catch (error) {
    const authMessage = buildGoogleAuthFailureMessage(error.message || error);
    setSheetStatus(ui, authMessage.text, authMessage.tone);
  } finally {
    ui.sheetAuthSyncButton.disabled = false;
  }
}

/**
 * Revoke the current in-browser Google token.
 *
 * @param {Record<string, any>} ui - Shared DOM refs.
 */
export function revokeGoogleAccess(ui) {
  if (window.google?.accounts?.oauth2 && state.auth.accessToken) {
    window.google.accounts.oauth2.revoke(state.auth.accessToken, () => {
      clearAuthToken();
      setSheetStatus(ui, "Google access revoked for this dashboard session.", "status-caution");
    });
    return;
  }

  clearAuthToken();
  setSheetStatus(ui, "No active Google token was stored in this session.", "status-caution");
}

/**
 * Copy arbitrary text and report the result through a status element.
 *
 * @param {{statusElement:HTMLElement|null,text:string,successMessage:string}} payload - Copy payload.
 */
export async function copyTextWithStatus({ statusElement, text, successMessage }) {
  try {
    await navigator.clipboard.writeText(text);
    statusElement.textContent = successMessage;
  } catch {
    statusElement.textContent = "Clipboard access failed. Your browser may require a secure context or manual copy.";
  }
}

/**
 * Copy a prepared execution ticket.
 *
 * @param {Record<string, any>} ui - Shared DOM refs.
 * @param {Record<string, any>} item - Execution queue item.
 */
export async function copyExecutionTicket(ui, item) {
  try {
    await navigator.clipboard.writeText(item.ticketText);
    ui.executionSummary.textContent = `${item.ticker} ticket blueprint copied for broker review.`;
  } catch {
    ui.executionSummary.textContent = `Clipboard access failed while copying ${item.ticker}.`;
  }
}

/**
 * Run a JSON API request against the local command server.
 *
 * @param {string} path - API path.
 * @param {RequestInit} [options={}] - Fetch options.
 * @returns {Promise<Record<string, any>>} Parsed JSON response.
 */
export async function apiRequest(path, options = {}) {
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

/**
 * Update one approval record and patch backend state.
 *
 * @param {string} ticker - Target ticker.
 * @param {string} status - New approval status.
 */
export async function updateApprovalStatus(ticker, status) {
  const result = await apiRequest("/api/approval", {
    method: "POST",
    body: JSON.stringify({
      ticker,
      status,
      action: "set",
    }),
  });
  patchBackend({
    approvalQueue: result.approvalQueue || null,
    executionQueue: result.executionQueue || null,
  });
}

/**
 * Reset the approval desk and patch backend state.
 */
export async function resetApprovalQueue() {
  const result = await apiRequest("/api/approval", {
    method: "POST",
    body: JSON.stringify({
      action: "reset",
    }),
  });
  patchBackend({
    approvalQueue: result.approvalQueue || null,
    executionQueue: result.executionQueue || null,
  });
}

/**
 * Refresh backend status from the local command server.
 */
export async function refreshBackendStatus() {
  try {
    const status = await apiRequest("/api/status", {
      method: "GET",
      headers: {},
    });
    setBackendStatus(status);
  } catch {
    clearBackendStatus();
  }
}

/**
 * Start the backend heartbeat loop.
 *
 * @param {() => Promise<void>|void} onTick - Callback to run after each refresh.
 */
export function startBackendHeartbeat(onTick) {
  window.setInterval(async () => {
    if (document.visibilityState === "hidden") {
      return;
    }
    await refreshBackendStatus();
    await onTick();
  }, BACKEND_REFRESH_INTERVAL_MS);
}

/**
 * Forge the current filtered desk snapshot and optionally send email.
 *
 * @param {Record<string, any>} ui - Shared DOM refs.
 * @param {boolean} [sendEmail=false] - Whether to attempt SMTP delivery.
 */
export async function forgeSnapshot(ui, sendEmail = false) {
  const rows = getFilteredRows();
  if (!rows.length) {
    ui.briefStatus.textContent = "No rows are loaded, so there is nothing to forge.";
    return;
  }

  if (!state.backend.available) {
    ui.briefStatus.textContent = "Local command server is offline. Run python3 server.py to enable snapshots and SMTP delivery.";
    return;
  }

  try {
    const snapshotPayload = buildSnapshotPayload(rows, state);
    const result = await apiRequest("/api/briefing", {
      method: "POST",
      body: JSON.stringify({
        ...snapshotPayload,
        sendEmail,
      }),
    });

    saveSnapshotCache(snapshotPayload);
    patchBackend({
      available: true,
      smtpConfigured: Boolean(result.smtpConfigured),
      lastSnapshotAt: result.generatedAt || new Date().toISOString(),
    });
    ui.briefStatus.textContent = sendEmail
      ? result.emailSent
        ? `Brief emailed and snapshot forged at ${result.snapshotPath}.`
        : `Snapshot forged at ${result.snapshotPath}, but SMTP is not configured.`
      : `Snapshot forged at ${result.snapshotPath}.`;
  } catch (error) {
    ui.briefStatus.textContent = `Snapshot forge failed. ${error.message}`;
  }
}

/**
 * Send a standalone SMTP test email through the local command server.
 *
 * @param {Record<string, any>} ui - Shared DOM refs.
 */
export async function testSmtpDelivery(ui) {
  if (!state.backend.available) {
    ui.briefStatus.textContent = "Local command server is offline. Run python3 server.py first.";
    return;
  }

  try {
    const result = await apiRequest("/api/test-email", {
      method: "POST",
      body: JSON.stringify({}),
    });
    patchBackend({
      smtpConfigured: Boolean(result.smtpConfigured),
    });
    ui.briefStatus.textContent = result.message || "SMTP test email sent.";
  } catch (error) {
    ui.briefStatus.textContent = `SMTP test failed. ${error.message}`;
  }
}

/**
 * Copy one of the OAuth helper values and report the outcome through the sheet status.
 *
 * @param {Record<string, any>} ui - Shared DOM refs.
 * @param {string} text - Text to copy.
 * @param {string} successMessage - Success message.
 */
export async function copyConnectorText(ui, text, successMessage) {
  if (!text) {
    setSheetStatus(ui, "There was nothing to copy for this OAuth helper.", "status-caution");
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    setSheetStatus(ui, successMessage, "status-caution");
  } catch {
    setSheetStatus(ui, "Clipboard access failed. Copy the OAuth helper values manually.", "status-risk");
  }
}

/**
 * Bind static dashboard controls outside the dynamically rendered panels.
 *
 * @param {{ui:Record<string, any>,render:()=>void}} context - Control context.
 */
export function bindControlEvents({ ui, render }) {
  ui.searchInput?.addEventListener("input", (event) => {
    updateFilter("search", event.target.value.trim().toLowerCase());
    render();
  });

  ui.setupFilter?.addEventListener("change", (event) => {
    updateFilter("setup", event.target.value);
    render();
  });

  ui.urgencyFilter?.addEventListener("change", (event) => {
    updateFilter("urgency", event.target.value);
    render();
  });

  ui.triggerFilter?.addEventListener("change", (event) => {
    updateFilter("trigger", event.target.value);
    render();
  });

  ui.confidenceFilter?.addEventListener("input", (event) => {
    updateFilter("minConfidence", Number.parseInt(event.target.value, 10));
    ui.confidenceValue.textContent = `${state.filters.minConfidence} / 3`;
    render();
  });

  ui.csvInput?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    const text = await file.text();
    const parsed = normalizeCSVRows(parseCSV(text));

    if (parsed.length) {
      setRows(parsed, {
        selectedTicker: parsed[0].ticker,
        sourceLabel: `${file.name} imported`,
      });
      populateFilters(ui);
      setSheetStatus(ui, "CSV imported into local dashboard state.", "status-caution");
      render();
      await forgeSnapshot(ui, false);
    }
  });

  ui.sheetAuthSyncButton?.addEventListener("click", () => {
    syncGoogleSheetPrivate({ ui, render });
  });

  ui.sheetPublicSyncButton?.addEventListener("click", () => {
    const sheetUrl = ui.sheetUrlInput.value.trim();
    if (!sheetUrl) {
      setSheetStatus(ui, "Paste a Google Sheets link first.", "status-caution");
      return;
    }
    syncGoogleSheetPublic({ ui, sheetUrl, render });
  });

  ui.sheetRevokeButton?.addEventListener("click", () => {
    revokeGoogleAccess(ui);
  });

  ui.copyOauthOriginButton?.addEventListener("click", () => {
    copyConnectorText(ui, getDashboardOrigin(), `OAuth origin copied: ${getDashboardOrigin()}`);
  });

  ui.copyOauthPageButton?.addEventListener("click", () => {
    copyConnectorText(ui, getDashboardPageUrl(), `Page URL copied: ${getDashboardPageUrl()}`);
  });

  ui.forgeSnapshotButton?.addEventListener("click", () => {
    forgeSnapshot(ui, false);
  });

  ui.sendBriefButton?.addEventListener("click", () => {
    forgeSnapshot(ui, true);
  });

  ui.testSmtpButton?.addEventListener("click", () => {
    testSmtpDelivery(ui);
  });

  ui.copyBriefButton?.addEventListener("click", () => {
    if (!state.latestBrief) {
      ui.briefStatus.textContent = "No brief is loaded yet.";
      return;
    }
    copyTextWithStatus({
      statusElement: ui.briefStatus,
      text: state.latestBrief,
      successMessage: "Morning brief copied to clipboard.",
    });
  });

  ui.emailBriefButton?.addEventListener("click", () => {
    if (!state.latestBrief) {
      ui.briefStatus.textContent = "No brief is loaded yet.";
      return;
    }

    const subject = encodeURIComponent("Morning Conviction Brief");
    const body = encodeURIComponent(state.latestBrief);
    window.location.href = `mailto:?subject=${subject}&body=${body}`;
    ui.briefStatus.textContent = "Email draft opened with the current morning brief.";
  });

  ui.copyTicketsButton?.addEventListener("click", () => {
    if (!state.latestTickets) {
      ui.briefStatus.textContent = "No paper tickets are loaded yet.";
      return;
    }
    copyTextWithStatus({
      statusElement: ui.briefStatus,
      text: state.latestTickets,
      successMessage: "Paper trade tickets copied to clipboard.",
    });
  });
}
