# MIGRATION CHECKLIST

## Source Snapshot
- Original migration source: `<repo-root>/frontend/app.js.bak.20260411-001150`
- Goal: verify 100% function coverage during the ES module split with zero behavior loss.

## Phase 1A: Utility + Data Processor Split

| Status | Symbol / Function | Original Line | New Location | Notes |
|---|---|---:|---|---|
| moved | `clamp` | 494 | `frontend/modules/utils.js` | Pure math helper |
| moved | `round` | 498 | `frontend/modules/utils.js` | Historical fixed-string formatter retained |
| moved | `formatCurrency` | 502 | `frontend/modules/utils.js` | Shared presentation utility |
| moved | `formatDate` | 510 | `frontend/modules/utils.js` | Noon-safe date renderer |
| moved | `formatBackendDate` | 926 | `frontend/modules/utils.js` | Backend status timestamp formatter |
| moved | `convictionConfig` | 459 | `frontend/modules/dataProcessor.js` | Shared conviction thresholds |
| moved | `creatureGuide` | 467 | `frontend/modules/dataProcessor.js` | Creature taxonomy |
| moved | `describeTemperature` | 626 | `frontend/modules/dataProcessor.js` | Heat assignment |
| moved | `scoreToPercent` | 683 | `frontend/modules/dataProcessor.js` | Readiness sub-score normalization |
| moved | `setupWeight` | 687 | `frontend/modules/dataProcessor.js` | Setup weight |
| moved | `urgencyWeight` | 704 | `frontend/modules/dataProcessor.js` | Urgency weight |
| moved | `readinessLabel` | 718 | `frontend/modules/dataProcessor.js` | Status mapping |
| moved | `dominantScore` | 728 | `frontend/modules/dataProcessor.js` | Primary score family |
| moved | `valuationBonus` | 738 | `frontend/modules/dataProcessor.js` | Long-term bias helper |
| moved | `buildActionBias` | 754 | `frontend/modules/dataProcessor.js` | Short-term action posture |
| moved | `buildAccumulationBias` | 790 | `frontend/modules/dataProcessor.js` | Long-term accumulation posture |
| moved | `buildAccumulationReasons` | 814 | `frontend/modules/dataProcessor.js` | Long-term narrative reasons |
| moved | `enrichRow` | 837 | `frontend/modules/dataProcessor.js` | Memoized enrichment engine |
| moved | `parseCSV` | 2852 | `frontend/modules/dataProcessor.js` | CSV parser |
| moved | `numberOrNull` | 2903 | `frontend/modules/dataProcessor.js` | Cell coercion helper |
| moved | `normalizeCSVRows` | 2915 | `frontend/modules/dataProcessor.js` | Raw sheet → enriched rows |

## Phase 1B: State Spine Split

| Status | Symbol / Function | Original Line | New Location | Notes |
|---|---|---:|---|---|
| moved | `DEFAULT_SHEET_URL` | 388 | `frontend/modules/state.js` | Default sheet connection constant |
| moved | `SHEET_STORAGE_KEY` | 389 | `frontend/modules/state.js` | Persisted sheet URL key |
| moved | `GOOGLE_CLIENT_ID_STORAGE_KEY` | 390 | `frontend/modules/state.js` | Persisted OAuth client key |
| moved | `BACKEND_REFRESH_INTERVAL_MS` | 391 | `frontend/modules/state.js` | Backend heartbeat interval |
| moved | `state` | 393 | `frontend/modules/state.js` | Central live desk state |
| moved | `getUniqueOptions` | 616 | `frontend/modules/state.js` | Filter option builder |
| moved | `accessTokenIsFresh` | 660 | `frontend/modules/state.js` | OAuth freshness gate |
| moved | `getFilteredRows` | 664 | `frontend/modules/state.js` | Ranked filtered desk rows |
| new | `SAMPLE_PORTFOLIO` | n/a | `frontend/modules/state.js` | Seeded closed-trade relics for future inventory |
| new | `SNAPSHOT_STORAGE_KEY` | n/a | `frontend/modules/state.js` | Local snapshot cache key |
| new | `PORTFOLIO_STORAGE_KEY` | n/a | `frontend/modules/state.js` | Portfolio cache key |
| new | `initializeState` | n/a | `frontend/modules/state.js` | Seeds exported state from sample rows |
| new | `loadPersistedSheetConnection` | n/a | `frontend/modules/state.js` | Loads sheet URL + OAuth client |
| new | `persistSheetConnection` | n/a | `frontend/modules/state.js` | Saves sheet URL + OAuth client |
| new | `loadSnapshotCache` | n/a | `frontend/modules/state.js` | Loads local snapshot payload |
| new | `saveSnapshotCache` | n/a | `frontend/modules/state.js` | Saves local snapshot payload |
| new | `loadPortfolio` | n/a | `frontend/modules/state.js` | Loads stored portfolio or seeded relics |
| new | `savePortfolio` | n/a | `frontend/modules/state.js` | Persists portfolio immutably |
| new | `setPortfolio` | n/a | `frontend/modules/state.js` | Replaces portfolio immutably |
| new | `addPortfolioItem` | n/a | `frontend/modules/state.js` | Adds a new relic to the portfolio |
| new | `applyStatePatch` | n/a | `frontend/modules/state.js` | Immutable state patch engine |
| new | `setRows` | n/a | `frontend/modules/state.js` | Immutable rows + source update |
| new | `setSelectedTicker` | n/a | `frontend/modules/state.js` | Selection helper |
| new | `setSelectedDistrict` | n/a | `frontend/modules/state.js` | District helper for later UI split |
| new | `setSourceLabel` | n/a | `frontend/modules/state.js` | Source label helper |
| new | `setLatestArtifacts` | n/a | `frontend/modules/state.js` | Brief/tickets/long-term artifact helper |
| new | `patchBackend` | n/a | `frontend/modules/state.js` | Backend partial patch helper |
| new | `setBackendStatus` | n/a | `frontend/modules/state.js` | `/api/status` to backend state adapter |
| new | `clearBackendStatus` | n/a | `frontend/modules/state.js` | Offline backend reset |
| new | `setAuthToken` | n/a | `frontend/modules/state.js` | OAuth token persistence in state |
| new | `clearAuthToken` | n/a | `frontend/modules/state.js` | OAuth token reset helper |
| new | `updateFilter` | n/a | `frontend/modules/state.js` | Immutable filter updates |

## Phase 1C: Diablo Theme Split

| Status | Symbol / Function | Original Line | New Location | Notes |
|---|---|---:|---|---|
| moved | `renderTempChip` | 646 | `frontend/modules/theme/diablo.js` | Creature temperature chip renderer |
| moved | `renderBossBar` | 656 | `frontend/modules/theme/diablo.js` | Ascension / readiness bar renderer |
| moved | `buildTownActors` | 1267 | `frontend/modules/theme/diablo.js` | Campaign-town actor flavor cards |
| moved | `buildTownDistricts` | 1407 | `frontend/modules/theme/diablo.js` | Themed district metadata |
| moved | `buildTownMood` | 1512 | `frontend/modules/theme/diablo.js` | Village mood narrator |
| moved | `buildTownDialogue` | 1700 | `frontend/modules/theme/diablo.js` | NPC voice-line triggers |
| moved | `buildLootDrops` | 1761 | `frontend/modules/theme/diablo.js` | Loot vault flavor generation |
| moved | `renderMascotCard` | 2696 | `frontend/modules/theme/diablo.js` | Signal demon profile card |
| moved | `buildNarrative` | 2787 | `frontend/modules/theme/diablo.js` | Diablo-style thesis narration |
| new | `buildDistrictGlyph` | n/a | `frontend/modules/theme/diablo.js` | District / actor initials helper |
| new | `toneToActorStateLabel` | n/a | `frontend/modules/theme/diablo.js` | Actor-chip tone helper |
| new | `toneToDialogueStateLabel` | n/a | `frontend/modules/theme/diablo.js` | Dialogue-chip tone helper |
| new | `toneToLootStateLabel` | n/a | `frontend/modules/theme/diablo.js` | Loot-chip tone helper |

## Phase 1D: UI + Control Tower Final Split

| Status | Symbol / Function | Original Line | New Location | Notes |
|---|---|---:|---|---|
| moved | `sampleData` | 1 | `frontend/modules/sampleData.js` | Seeded starter encounter deck |
| moved | `UI DOM bindings` | 408-457 | `frontend/modules/ui/dom.js` | Centralized DOM registry for all dashboard landmarks |
| moved | `GOOGLE_SHEETS_SCOPE` | 375 | `frontend/modules/ui/sheetControls.js` | Google Sheets readonly scope |
| moved | `setSheetStatus` | 519 | `frontend/modules/ui/sheetControls.js` | Connector status helper |
| moved | `getDashboardOrigin` | 524 | `frontend/modules/ui/sheetControls.js` | OAuth origin helper |
| moved | `getDashboardPageUrl` | 532 | `frontend/modules/ui/sheetControls.js` | Hosted page URL helper |
| moved | `isHostedDashboard` | 540 | `frontend/modules/ui/sheetControls.js` | GitHub Pages check |
| moved | `renderOAuthGuide` | 544 | `frontend/modules/ui/sheetControls.js` | OAuth helper copy |
| moved | `buildGoogleAuthFailureMessage` | 566 | `frontend/modules/ui/sheetControls.js` | OAuth error translation |
| moved | `populateFilters` | 912 | `frontend/modules/ui/sheetControls.js` | Filter dropdown hydration |
| moved | `updateSyncLabel` | 922 | `frontend/modules/ui/sheetControls.js` | Source label updater |
| moved | `isGoogleReady` | 942 | `frontend/modules/ui/sheetControls.js` | GIS readiness gate |
| moved | `waitForGoogleIdentity` | 946 | `frontend/modules/ui/sheetControls.js` | GIS load waiter |
| moved | `copyTextWithStatus` | 2349 | `frontend/modules/ui/sheetControls.js` | Clipboard helper for brief controls |
| moved | `copyExecutionTicket` | 2358 | `frontend/modules/ui/sheetControls.js` | Execution ticket clipboard helper |
| moved | `apiRequest` | 2367 | `frontend/modules/ui/sheetControls.js` | Local command server request helper |
| moved | `updateApprovalStatus` | 2383 | `frontend/modules/ui/sheetControls.js` | Approval queue mutation |
| moved | `resetApprovalQueue` | 2396 | `frontend/modules/ui/sheetControls.js` | Approval desk reset |
| moved | `refreshBackendStatus` | 2423 | `frontend/modules/ui/sheetControls.js` | `/api/status` refresh |
| moved | `startBackendHeartbeat` | 2447 | `frontend/modules/ui/sheetControls.js` | Visibility-aware heartbeat |
| moved | `forgeSnapshot` | 2457 | `frontend/modules/ui/sheetControls.js` | Snapshot + optional email |
| moved | `testSmtpDelivery` | 2491 | `frontend/modules/ui/sheetControls.js` | SMTP test trigger |
| moved | `parseGoogleSheetUrl` | 2959 | `frontend/modules/ui/sheetControls.js` | URL → spreadsheet/gid parser |
| moved | `googleValue` | 2976 | `frontend/modules/ui/sheetControls.js` | Gviz cell normalizer |
| moved | `loadGoogleSheetTable` | 2989 | `frontend/modules/ui/sheetControls.js` | Public Google sheet loader |
| moved | `syncGoogleSheetPublic` | 3042 | `frontend/modules/ui/sheetControls.js` | Public sheet sync path |
| moved | `ensureGoogleToken` | 3080 | `frontend/modules/ui/sheetControls.js` | OAuth token acquisition |
| moved | `googleApiFetch` | 3150 | `frontend/modules/ui/sheetControls.js` | Authenticated Google API fetch |
| moved | `loadPrivateSheetRows` | 3164 | `frontend/modules/ui/sheetControls.js` | Private sheet values loader |
| moved | `syncGoogleSheetPrivate` | 3193 | `frontend/modules/ui/sheetControls.js` | Private sheet sync path |
| moved | `revokeGoogleAccess` | 3241 | `frontend/modules/ui/sheetControls.js` | OAuth token revocation |
| moved | `static control event listeners` | 3256-3377 | `frontend/modules/ui/sheetControls.js` | Search, filters, CSV import, connector buttons, brief controls |
| moved | `buildCampaignRank` | 1113 | `frontend/modules/ui/strategy.js` | Campaign score → act label |
| moved | `buildCampaignState` | 1142 | `frontend/modules/ui/strategy.js` | Campaign state model |
| moved | `buildQuestForRow` | 1192 | `frontend/modules/ui/strategy.js` | Quest descriptor builder |
| moved | `buildCampaignQuests` | 1236 | `frontend/modules/ui/strategy.js` | Quest list model |
| moved | `getScoutCandidates` | 1398 | `frontend/modules/ui/strategy.js` | Scout-lane candidate picker |
| moved | `gateChecks` | 1952 | `frontend/modules/ui/strategy.js` | Conviction gate evaluation |
| moved | `gateFailures` | 1962 | `frontend/modules/ui/strategy.js` | Conviction gate reason builder |
| moved | `getEligibleCandidates` | 1984 | `frontend/modules/ui/strategy.js` | Raid-eligible set |
| moved | `getLongTermCandidates` | 2063 | `frontend/modules/ui/strategy.js` | Long-term lane ranking |
| moved | `buildLongTermBrief` | 2078 | `frontend/modules/ui/strategy.js` | Merchant-lane brief |
| moved | `buildMorningBrief` | 2268 | `frontend/modules/ui/strategy.js` | Daily brief model |
| moved | `buildPaperTickets` | 2311 | `frontend/modules/ui/strategy.js` | Paper ticket builder |
| moved | `buildSnapshotPayload` | 2407 | `frontend/modules/ui/strategy.js` | Snapshot payload builder |
| moved | `renderOverview` | 982 | `frontend/modules/ui/landscapes.js` | Sanctum overview renderer |
| moved | `renderCampaignBoard` | 1319 | `frontend/modules/ui/landscapes.js` | Campaign board renderer |
| moved | `renderDistrictFocus` | 1532 | `frontend/modules/ui/landscapes.js` | District focus renderer |
| moved | `renderTownMap` | 1564 | `frontend/modules/ui/landscapes.js` | Interactive village map renderer |
| moved | `renderTownBoard` | 1813 | `frontend/modules/ui/landscapes.js` | Town dialogue/loot renderer |
| moved | `renderPlayMap` | 1880 | `frontend/modules/ui/landscapes.js` | Conviction circle renderer |
| moved | `renderSignalRibbon` | 2509 | `frontend/modules/ui/landscapes.js` | Encounter ribbon renderer |
| moved | `renderOpsWatch` | 1025 | `frontend/modules/ui/desks.js` | Ops monitor renderer |
| moved | `renderConvictionEngine` | 1988 | `frontend/modules/ui/desks.js` | Conviction gate renderer |
| moved | `renderAccumulationDesk` | 2105 | `frontend/modules/ui/desks.js` | Long-term lane renderer |
| moved | `renderExecutionDesk` | 2152 | `frontend/modules/ui/desks.js` | Approval + broker-review renderer |
| moved | `renderMorningBrief` | 2333 | `frontend/modules/ui/desks.js` | Morning brief renderer |
| moved | `renderScoreRow` | 2734 | `frontend/modules/ui/scorecards.js` | Detail score row renderer |
| moved | `renderScoreTile` | 2747 | `frontend/modules/ui/scorecards.js` | Detail score tile renderer |
| moved | `renderScoreSigils` | 2760 | `frontend/modules/ui/scorecards.js` | Candidate sigil renderer |
| moved | `renderRoster` | 2539 | `frontend/modules/ui/detail.js` | Main roster renderer |
| moved | `renderDetail` | 2593 | `frontend/modules/ui/detail.js` | Infernal readout renderer |
| moved | `renderShortlist` | 2807 | `frontend/modules/ui/detail.js` | Shortlist rail renderer |
| retained | `render` | 2835 | `frontend/app.js` | Reduced to orchestration-only `renderDashboard` |
| retained | `startup bootstrap` | 3379-3384 | `frontend/app.js` | Minimal entry-point hydration + heartbeat wiring |

## Final Module Map

| Status | Area | Target Module | Notes |
|---|---|---|---|
| completed | Seed data | `frontend/modules/sampleData.js` | Starter encounter deck |
| completed | State and persistence | `frontend/modules/state.js` | Central state object, filters, snapshot/portfolio persistence |
| completed | Diablo theme helpers | `frontend/modules/theme/diablo.js` | Voice lines, visual flavor helpers, temperature visuals |
| completed | DOM registry | `frontend/modules/ui/dom.js` | Stable DOM lookups |
| completed | Strategic UI models | `frontend/modules/ui/strategy.js` | Campaign, brief, quest, and gate modeling |
| completed | Scenic renderers | `frontend/modules/ui/landscapes.js` | Overview, campaign, town, and ribbon surfaces |
| completed | Desk renderers | `frontend/modules/ui/desks.js` | Ops, conviction, accumulation, execution, brief |
| completed | Score helpers | `frontend/modules/ui/scorecards.js` | Shared score/tile/sigil rendering |
| completed | Detail renderers | `frontend/modules/ui/detail.js` | Roster, readout, shortlist |
| completed | Control tower | `frontend/modules/ui/sheetControls.js` | Google sync, backend, snapshots, event wiring |

## Verification Notes
- This checklist should be updated after every module split.
- Original line references always point back to the frozen backup snapshot, not the edited file.

## Phase 2A: Creative Upgrade - Draggable Diablo Inventory Grid

| Status | Area | File | Notes |
|---|---|---|---|
| implemented | Drag source layer | `frontend/modules/ui/detail.js` | Roster rows and shortlist cards now publish HTML5 drag payloads with Diablo FX toggle support |
| implemented | Inventory vault + loot panel | `frontend/modules/ui/landscapes.js` | 5x8 soul-bound grid, drag/drop handling, slot swapping, particle burst, codex modal, injected FX styles |
| verified | Safety toggle | `frontend/modules/ui/detail.js`, `frontend/modules/ui/landscapes.js` | `ENABLE_DIABLO_FX` keeps legacy behavior intact when disabled |

## Phase 2B: Creative Upgrade - Animated Hell-Temperature Gauge

| Status | Area | File | Notes |
|---|---|---|---|
| implemented | Gauge FX toggle | `frontend/modules/theme/diablo.js` | `ENABLE_DIABLO_FX` now gates all animated temperature effects |
| implemented | Ember pulse + color shift | `frontend/modules/theme/diablo.js` | `renderTempChip` and `renderBossBar` now derive dynamic FX from live heat intensity |
| implemented | Screen-wide heat haze | `frontend/modules/theme/diablo.js` | Global haze overlay activates only when a rendered name exceeds the heat threshold |
| verified | Legacy fallback path | `frontend/modules/theme/diablo.js` | Chip and bar return their pre-upgrade HTML when FX are disabled |

## Phase 2C: Creative Upgrade - Voice-Line State Machine

| Status | Area | File | Notes |
|---|---|---|---|
| implemented | Voice-line runtime + config | `frontend/modules/theme/diablo.js` | `VoiceLineStateMachine` now manages cooldowns, randomized lines, and SpeechSynthesis / console fallback |
| implemented | Approval + relic drop triggers | `frontend/modules/theme/diablo.js` | DOM click/drop listeners now react to approval desk actions and inventory vault drops |
| implemented | Snapshot + board update triggers | `frontend/modules/theme/diablo.js` | Snapshot seal, campaign mood shifts, and town-board state changes now emit voice lines |
| implemented | High-volatility swing trigger | `frontend/modules/theme/diablo.js` | Temperature rendering now announces meaningful heat jumps without spamming every render |
| verified | Legacy fallback path | `frontend/modules/theme/diablo.js` | No speech runtime, listeners, or logs fire when `ENABLE_DIABLO_FX` is disabled |

## Phase 2D: Creative Upgrade - Soul-Bound Portfolio Snapshot History

| Status | Area | File | Notes |
|---|---|---|---|
| implemented | Immutable portfolio history stack | `frontend/modules/state.js` | Portfolio updates now seal soul-bound history entries with ember timestamps and deduped signatures |
| implemented | History persistence + revert | `frontend/modules/state.js` | History stack persists to local storage and supports one-click revert to prior vault states |
| implemented | Ember timeline UI | `frontend/modules/ui/landscapes.js` | Inventory vault now renders a soul-flame timeline with current-state marker and revert controls |
| implemented | Revert confirmation flow | `frontend/modules/ui/landscapes.js` | Reverting uses guarded confirmation before overwriting the active binding layout |
| verified | Legacy fallback path | `frontend/modules/ui/landscapes.js` | Timeline stays out of the way when `ENABLE_DIABLO_FX` is disabled, while core portfolio persistence remains intact |
