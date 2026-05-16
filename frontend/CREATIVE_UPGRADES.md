# CREATIVE UPGRADES

Status legend:
- `implemented` = live in module code
- `ready` = designed and queued

## Module: `frontend/modules/utils.js`
1. Add a tiny `formatRiskUnits` helper that renders staged risk as ember pips for the execution forge.
2. Add a `formatRelativeBattleTime` helper so logs read like "3 hours since the last raid" instead of plain timestamps.

## Module: `frontend/modules/dataProcessor.js`
1. Add a `hellTemperature` scalar derived from readiness + IV expansion so later modules can animate subtle glow intensity without recalculating score logic in the UI.
2. Add a `creatureRarity` tier that promotes especially strong names into mini-boss status for inventory loot, quest banners, and battle resolution.

## Module: `frontend/modules/state.js`
Status: `implemented` for soul-bound snapshot history, `ready` for the remaining ideas.

Implemented:
1. Soul-bound snapshot history now keeps the last 7 vault states with ember timestamps and immutable portfolio snapshots.
2. Reverting to a prior vault state now seals a fresh history entry instead of destroying the current one.

Still queued:
1. Add a `graveyard` lane for failed trades so the town can remember losses as tombstones instead of pretending only victories matter.
2. Add a `merchant ledger` streak system that turns disciplined accumulation into village prosperity, not just one-off loot drops.

## Module: `frontend/modules/theme/diablo.js`
Status: `implemented` for the animated temperature gauge and voice-line state machine, `ready` for the remaining ideas.

Implemented:
1. `renderTempChip` and `renderBossBar` now pulse with ember animation, dynamic ice-blue to blood-red color shift, and glow intensity derived from live conviction heat.
2. A screen-wide heat haze overlay now activates when rendered names cross the high-heat threshold, giving the whole cathedral a subtle infernal shimmer.
3. `VoiceLineStateMachine` now powers randomized Diablo-style voice lines for snapshot seals, approval actions, vault drops, temperature surges, and town/campaign shifts.
4. Speech uses the browser Web Speech API when available and falls back to `console.log` safely when speech playback is blocked or unsupported.

Still queued:
1. Add district aura pulse tiers so Hellgate, Forge, and Archive visibly intensify when pending approvals, broker-ready raids, or machine warnings spike.
2. Tie town-wide aura turbulence to a future dedicated `hellTemperature` scalar once that value exists in the data layer.

## Module: `frontend/modules/ui/landscapes.js`
Status: `implemented` for the first inventory upgrade and soul-bound timeline, `ready` for the remaining ideas.

Implemented:
1. Draggable Diablo-style inventory grid now lives inside the town loot vault with a 5x8 soul-bound grid, rarity borders, slot swapping, hell-rift glow, and soul-flame drop bursts.
2. Double-clicking an inventory relic now opens a codex-style modal with live enrich-row stats when the ticker is still active.
3. The inventory vault now renders an ember timeline of recent soul-bound states with one-click guarded reverts.

Still queued:
1. Cinematic hover cards that feel like codex entries when you move over names, districts, and creatures.
2. A village weather system that darkens or brightens based on the current readiness average.

## Module: `frontend/modules/ui/strategy.js`
1. Add a quest-difficulty tier that turns the raid lane into Normal / Nightmare / Hell based on conviction and broker readiness.
2. Add a true long-term drawdown model so merchant quests react to 3-month and 6-month damage, not just current value proxies.

## Module: `frontend/modules/ui/desks.js`
1. Add forge sparks and sealing wax effects when a name moves from pending to approval-ready in the execution desk.
2. Add a battle standard summary on the morning brief that shows which score family ruled the day across the top three names.

## Module: `frontend/modules/ui/detail.js`
Status: `implemented` for the first drag-source upgrade, `ready` for the remaining ideas.

Implemented:
1. Roster rows and shortlist cards now act as Diablo-flavored drag sources for the soul-bound inventory vault.
2. The infernal readout now surfaces a drag hint so the upgrade is discoverable without retraining the user.

Still queued:
1. Add a codex flip animation when changing selected tickers so the infernal readout feels like turning pages in a bestiary.
2. Add “scar notes” and “victory notes” when portfolio relics arrive so the detail panel can compare live setups with past wins and losses.

## Module: `frontend/modules/ui/sheetControls.js`
1. Add a ritual timeline that shows OAuth, sync, forge, and email events as a small operator log instead of flat status text.
2. Add a fallback “campfire mode” that lets the hosted site stay useful with cached snapshots even when Google auth is temporarily misconfigured.
