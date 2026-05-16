/**
 * frontend/modules/ui/dom.js
 *
 * Purpose:
 * This module is the town registry for the dashboard. It resolves every known UI
 * landmark exactly once so the rest of the app can speak in terms of the desk,
 * the vault, and the town square instead of scattering raw DOM lookups across
 * the cathedral.
 */

function element(id) {
  return document.getElementById(id);
}

/**
 * Stable DOM references for every dashboard surface touched by the front-end.
 *
 * @type {Record<string, HTMLElement | HTMLInputElement | HTMLButtonElement | null>}
 */
export const ui = {
  rosterBody: element("roster-body"),
  detailTitle: element("detail-title"),
  detailContent: element("detail-content"),
  shortlist: element("shortlist"),
  overviewStats: element("overview-stats"),
  setupFilter: element("setup-filter"),
  urgencyFilter: element("urgency-filter"),
  searchInput: element("search-input"),
  triggerFilter: element("trigger-filter"),
  confidenceFilter: element("confidence-filter"),
  confidenceValue: element("confidence-value"),
  csvInput: element("csv-input"),
  syncTime: element("sync-time"),
  sheetUrlInput: element("sheet-url-input"),
  googleClientIdInput: element("google-client-id-input"),
  sheetAuthSyncButton: element("sheet-auth-sync-button"),
  sheetPublicSyncButton: element("sheet-public-sync-button"),
  sheetRevokeButton: element("sheet-revoke-button"),
  sheetStatus: element("sheet-status"),
  sheetOauthHint: element("sheet-oauth-hint"),
  copyOauthOriginButton: element("copy-oauth-origin-button"),
  copyOauthPageButton: element("copy-oauth-page-button"),
  signalRibbon: element("signal-ribbon"),
  playMap: element("play-map"),
  overviewSummary: element("overview-summary"),
  engineRules: element("engine-rules"),
  engineCandidates: element("engine-candidates"),
  longTermSummary: element("longterm-summary"),
  longTermCandidatesEl: element("longterm-candidates"),
  campaignSummary: element("campaign-summary"),
  campaignStats: element("campaign-stats"),
  questBoard: element("quest-board"),
  townActors: element("town-actors"),
  executionSummary: element("execution-summary"),
  executionCandidates: element("execution-candidates"),
  townSummary: element("town-summary"),
  townMap: element("town-map"),
  districtFocus: element("district-focus"),
  townDialogue: element("town-dialogue"),
  lootVault: element("loot-vault"),
  briefPreview: element("brief-preview"),
  briefStatus: element("brief-status"),
  opsGrid: element("ops-grid"),
  opsFeed: element("ops-feed"),
  forgeSnapshotButton: element("forge-snapshot-button"),
  sendBriefButton: element("send-brief-button"),
  testSmtpButton: element("test-smtp-button"),
  copyBriefButton: element("copy-brief-button"),
  emailBriefButton: element("email-brief-button"),
  copyTicketsButton: element("copy-tickets-button"),
};
