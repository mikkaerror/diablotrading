/**
 * frontend/modules/ui/landscapes.js
 *
 * Purpose:
 * This module paints the world outside the spreadsheet: the altar, the quest
 * board, the town streets, and the signal ribbon. It is the scenic layer of the
 * simulation where raw conviction turns into a Diablo-flavored campaign map.
 */

export const ENABLE_DIABLO_FX = true;

import { describeTemperature } from "../dataProcessor.js";
import { revertPortfolioHistory, setPortfolio, state } from "../state.js";
import {
  buildDistrictGlyph,
  buildLootDrops,
  buildTownActors,
  buildTownDialogue,
  buildTownDistricts,
  buildTownMood,
  renderBossBar,
  renderTempChip,
  toneToActorStateLabel,
  toneToDialogueStateLabel,
  toneToLootStateLabel,
} from "../theme/diablo.js";
import { clamp, round } from "../utils.js";
import {
  buildCampaignQuests,
  buildCampaignState,
  getEligibleCandidates,
  getLongTermCandidates,
  getScoutCandidates,
} from "./strategy.js";

const MARKET_DRAG_MIME = "application/x-inferno-market-row";
const INVENTORY_DRAG_MIME = "application/x-inferno-inventory-item";
const INVENTORY_STYLE_ID = "diablo-inventory-fx-style";
const INVENTORY_SLOT_COUNT = 40;
const INVENTORY_COLUMNS = 5;
const HISTORY_ENTRIES_SHOWN = 6;

const RARITY_LABELS = Object.freeze({
  white: "Common",
  green: "Uncommon",
  blue: "Rare",
  purple: "Epic",
  orange: "Legendary",
});

/**
 * Escape freeform text before embedding it into HTML strings.
 *
 * @param {string|number|null|undefined} value - Display value.
 * @returns {string} Escaped string.
 */
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/**
 * Install the inventory FX stylesheet exactly once.
 *
 * We inject the classes here so the creative layer stays self-contained inside
 * the requested UI modules and can be disabled by the feature flag without
 * touching the global stylesheet.
 */
function ensureInventoryFxStyles() {
  if (!ENABLE_DIABLO_FX || document.getElementById(INVENTORY_STYLE_ID)) {
    return;
  }

  const style = document.createElement("style");
  style.id = INVENTORY_STYLE_ID;
  style.textContent = `
    .inferno-inventory-shell {
      position: relative;
      display: grid;
      gap: 1rem;
      padding: 1rem;
      border: 1px solid rgba(199, 160, 106, 0.22);
      background:
        radial-gradient(circle at top, rgba(255, 126, 61, 0.18), transparent 40%),
        linear-gradient(180deg, rgba(45, 15, 13, 0.96), rgba(19, 6, 6, 0.96));
      box-shadow: inset 0 0 0 1px rgba(255, 149, 91, 0.08);
      overflow: hidden;
    }
    .inferno-inventory-shell::before {
      content: "";
      position: absolute;
      inset: 0;
      background: radial-gradient(circle at center, rgba(255, 110, 58, 0.1), transparent 58%);
      pointer-events: none;
      opacity: 0.75;
    }
    .inferno-inventory-shell.hell-rift-active {
      box-shadow:
        inset 0 0 0 1px rgba(255, 174, 107, 0.26),
        0 0 24px rgba(255, 82, 40, 0.22),
        0 0 48px rgba(255, 114, 54, 0.12);
      animation: inferno-rift-pulse 1s ease-in-out infinite;
    }
    body.inferno-drag-active .inferno-inventory-shell {
      box-shadow:
        inset 0 0 0 1px rgba(255, 174, 107, 0.18),
        0 0 24px rgba(255, 82, 40, 0.14);
    }
    .inferno-inventory-header {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      align-items: flex-start;
    }
    .inferno-inventory-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }
    .inferno-inventory-grid {
      display: grid;
      grid-template-columns: repeat(${INVENTORY_COLUMNS}, minmax(0, 1fr));
      gap: 0.55rem;
      position: relative;
      z-index: 1;
    }
    .inferno-slot {
      position: relative;
      min-height: 88px;
      border: 1px dashed rgba(199, 160, 106, 0.22);
      background:
        linear-gradient(180deg, rgba(33, 11, 9, 0.96), rgba(18, 5, 5, 0.96));
      border-radius: 10px;
      overflow: hidden;
      transition: border-color 140ms ease, transform 140ms ease, box-shadow 140ms ease;
    }
    .inferno-slot::after {
      content: attr(data-slot-label);
      position: absolute;
      top: 0.35rem;
      right: 0.45rem;
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      color: rgba(255, 204, 173, 0.42);
    }
    .inferno-slot.drop-hover {
      border-color: rgba(255, 154, 92, 0.7);
      box-shadow: 0 0 18px rgba(255, 100, 44, 0.26);
      transform: translateY(-2px);
    }
    .inferno-slot.filled {
      border-style: solid;
    }
    .inventory-item {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 0.45rem;
      width: 100%;
      padding: 0.6rem;
      border: 0;
      color: #f8e7d0;
      background:
        linear-gradient(180deg, rgba(72, 22, 18, 0.96), rgba(29, 8, 8, 0.98));
      text-align: left;
      cursor: pointer;
      transition: transform 140ms ease, box-shadow 140ms ease, filter 140ms ease;
    }
    .inventory-item:hover {
      transform: translateY(-2px);
      filter: brightness(1.04);
    }
    .inventory-item.dragging-soul {
      box-shadow:
        0 0 0 1px rgba(255, 194, 128, 0.42),
        0 0 18px rgba(255, 94, 46, 0.32),
        0 0 34px rgba(255, 114, 54, 0.2);
      animation: inferno-rift-pulse 0.9s ease-in-out infinite;
    }
    .inventory-item.rarity-white { box-shadow: inset 0 0 0 1px rgba(230, 220, 212, 0.28); }
    .inventory-item.rarity-green { box-shadow: inset 0 0 0 1px rgba(102, 214, 133, 0.4); }
    .inventory-item.rarity-blue { box-shadow: inset 0 0 0 1px rgba(90, 161, 255, 0.42); }
    .inventory-item.rarity-purple { box-shadow: inset 0 0 0 1px rgba(177, 112, 255, 0.42); }
    .inventory-item.rarity-orange { box-shadow: inset 0 0 0 1px rgba(255, 151, 74, 0.46); }
    .inventory-item-head {
      display: flex;
      justify-content: space-between;
      gap: 0.6rem;
      align-items: flex-start;
    }
    .inventory-item-title {
      display: grid;
      gap: 0.18rem;
    }
    .inventory-item-title strong {
      font-size: 1rem;
    }
    .inventory-item-title span {
      font-size: 0.78rem;
      color: rgba(255, 222, 194, 0.78);
    }
    .inventory-item-value {
      font-size: 0.78rem;
      color: rgba(255, 222, 194, 0.78);
    }
    .inventory-item-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      font-size: 0.72rem;
    }
    .inventory-empty {
      display: grid;
      place-items: center;
      height: 100%;
      color: rgba(255, 219, 190, 0.24);
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .inventory-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }
    .soul-history-timeline {
      display: grid;
      gap: 0.65rem;
      padding: 0.9rem 1rem;
      border: 1px solid rgba(199, 160, 106, 0.14);
      background: linear-gradient(180deg, rgba(31, 9, 9, 0.94), rgba(20, 6, 6, 0.92));
      box-shadow: inset 0 0 0 1px rgba(255, 161, 91, 0.05);
    }
    .soul-history-head {
      display: flex;
      justify-content: space-between;
      gap: 0.8rem;
      align-items: baseline;
    }
    .soul-history-head p,
    .soul-history-head h4,
    .soul-history-head span {
      margin: 0;
    }
    .soul-history-list {
      display: grid;
      gap: 0.55rem;
    }
    .soul-history-entry {
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 0.75rem;
      align-items: center;
      padding: 0.7rem 0.8rem;
      border: 1px solid rgba(196, 132, 78, 0.16);
      background:
        linear-gradient(90deg, rgba(255, 108, 54, 0.05), transparent 32%),
        rgba(27, 9, 9, 0.92);
      transition: border-color 120ms ease, transform 120ms ease, box-shadow 120ms ease;
    }
    .soul-history-entry:hover {
      border-color: rgba(255, 164, 103, 0.28);
      transform: translateY(-1px);
      box-shadow: 0 10px 24px rgba(0, 0, 0, 0.18);
    }
    .soul-history-flame {
      width: 1.1rem;
      height: 1.1rem;
      border-radius: 999px;
      background:
        radial-gradient(circle at 35% 35%, rgba(255, 223, 159, 0.88) 0%, rgba(255, 150, 76, 0.95) 35%, rgba(182, 42, 20, 0.98) 72%, rgba(61, 12, 10, 0.94) 100%);
      box-shadow:
        0 0 0 1px rgba(255, 183, 125, 0.18),
        0 0 16px rgba(255, 104, 47, 0.34);
      animation: inferno-soul-flame 2.6s ease-in-out infinite alternate;
    }
    .soul-history-copy {
      display: grid;
      gap: 0.18rem;
    }
    .soul-history-copy p {
      margin: 0;
    }
    .soul-history-meta {
      color: rgba(240, 213, 184, 0.68);
      font-size: 0.74rem;
    }
    .soul-history-empty {
      padding: 0.75rem 0;
      color: rgba(240, 213, 184, 0.68);
    }
    .soul-history-action {
      min-width: 6.5rem;
      justify-self: end;
    }
    .inventory-relic-feed {
      display: grid;
      gap: 0.75rem;
    }
    .inventory-drop-hint {
      margin: 0;
      color: rgba(255, 223, 196, 0.72);
    }
    .inferno-particle-burst {
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 3;
      overflow: hidden;
    }
    .inferno-particle {
      position: absolute;
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(255, 228, 173, 0.95), rgba(255, 110, 58, 0.72) 60%, transparent 70%);
      box-shadow: 0 0 12px rgba(255, 107, 47, 0.42);
      animation: inferno-particle-burst 900ms ease-out forwards;
    }
    .inferno-detail-modal {
      position: absolute;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 1rem;
      background: rgba(8, 4, 6, 0.76);
      backdrop-filter: blur(3px);
      z-index: 4;
    }
    .inferno-detail-modal.open {
      display: flex;
    }
    .inferno-detail-card {
      width: min(100%, 420px);
      display: grid;
      gap: 0.85rem;
      padding: 1rem;
      border: 1px solid rgba(199, 160, 106, 0.28);
      background:
        radial-gradient(circle at top, rgba(255, 112, 52, 0.16), transparent 38%),
        linear-gradient(180deg, rgba(52, 18, 15, 0.98), rgba(20, 7, 7, 0.98));
      box-shadow: 0 0 30px rgba(0, 0, 0, 0.34);
    }
    .inferno-detail-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.55rem;
    }
    .inferno-detail-grid .metric-card {
      min-height: auto;
    }
    .inferno-detail-actions {
      display: flex;
      justify-content: flex-end;
      gap: 0.5rem;
    }
    .inventory-ghost-pill {
      opacity: 0.65;
    }
    @keyframes inferno-rift-pulse {
      0%, 100% { box-shadow: inset 0 0 0 1px rgba(255, 174, 107, 0.18), 0 0 18px rgba(255, 82, 40, 0.16); }
      50% { box-shadow: inset 0 0 0 1px rgba(255, 204, 147, 0.38), 0 0 28px rgba(255, 88, 36, 0.26), 0 0 48px rgba(255, 114, 54, 0.18); }
    }
    @keyframes inferno-particle-burst {
      0% { transform: translate3d(0, 0, 0) scale(1); opacity: 1; }
      100% { transform: translate3d(var(--dx), var(--dy), 0) scale(0.12); opacity: 0; }
    }
    @keyframes inferno-soul-flame {
      0% {
        transform: scale(0.96);
        filter: saturate(1) brightness(0.98);
      }
      100% {
        transform: scale(1.06) translateY(-1px);
        filter: saturate(1.08) brightness(1.08);
      }
    }
  `;
  document.head.append(style);
}

/**
 * Choose a Diablo rarity tier from live conviction strength.
 *
 * @param {Record<string, any>} row - Enriched market row.
 * @returns {"white"|"green"|"blue"|"purple"|"orange"} Rarity key.
 */
function buildRarityFromRow(row) {
  if (row.readiness >= 90 || row.priority >= 6) {
    return "orange";
  }
  if (row.readiness >= 80 || row.priority >= 5) {
    return "purple";
  }
  if (row.readiness >= 70 || row.priority >= 4) {
    return "blue";
  }
  if (row.readiness >= 55 || row.priority >= 3) {
    return "green";
  }
  return "white";
}

/**
 * Normalize portfolio items into stable 5x8 grid slots without mutating source state.
 *
 * @param {Array<Record<string, any>>} portfolio - Persisted portfolio entries.
 * @returns {Array<Record<string, any>>} Slot-assigned copy.
 */
function normalizePortfolioSlots(portfolio) {
  const taken = new Set();
  return (portfolio || []).map((item) => {
    let slot = Number.isInteger(item.slot) && item.slot >= 0 && item.slot < INVENTORY_SLOT_COUNT && !taken.has(item.slot)
      ? item.slot
      : null;

    if (slot === null) {
      slot = [...Array(INVENTORY_SLOT_COUNT).keys()].find((index) => !taken.has(index)) ?? 0;
    }

    taken.add(slot);
    return { ...item, slot };
  });
}

/**
 * Find the first empty slot in the current 5x8 grid.
 *
 * @param {Array<Record<string, any>>} portfolio - Slotted portfolio entries.
 * @param {number[]} [exclude=[]] - Slots to ignore during the search.
 * @returns {number|null} First free slot or null when the vault is full.
 */
function findFirstFreeSlot(portfolio, exclude = []) {
  const used = new Set([...(portfolio || []).map((item) => item.slot), ...exclude]);
  return [...Array(INVENTORY_SLOT_COUNT).keys()].find((slot) => !used.has(slot)) ?? null;
}

/**
 * Spawn a small soul-flame burst at the drop target.
 *
 * @param {HTMLElement} mount - Inventory shell root.
 * @param {HTMLElement} target - Slot node receiving the relic.
 */
function spawnSoulFlameBurst(mount, target) {
  if (!ENABLE_DIABLO_FX) {
    return;
  }

  const layer = mount.querySelector("[data-inventory-burst]");
  if (!layer) {
    return;
  }

  const mountRect = mount.getBoundingClientRect();
  const targetRect = target.getBoundingClientRect();
  const originX = targetRect.left - mountRect.left + targetRect.width / 2;
  const originY = targetRect.top - mountRect.top + targetRect.height / 2;

  for (let index = 0; index < 12; index += 1) {
    const particle = document.createElement("span");
    particle.className = "inferno-particle";
    particle.style.left = `${originX}px`;
    particle.style.top = `${originY}px`;
    particle.style.setProperty("--dx", `${Math.cos((Math.PI * 2 * index) / 12) * (18 + Math.random() * 28)}px`);
    particle.style.setProperty("--dy", `${Math.sin((Math.PI * 2 * index) / 12) * (18 + Math.random() * 28)}px`);
    particle.addEventListener("animationend", () => particle.remove(), { once: true });
    layer.append(particle);
  }
}

/**
 * Build a soul-bound relic from a live market row after a drag drop.
 *
 * @param {Record<string, any>} row - Enriched market row.
 * @param {number} slot - Destination slot index.
 * @returns {Record<string, any>} Persistable portfolio relic.
 */
function buildPortfolioRelicFromRow(row, slot) {
  const creature = describeTemperature(row);
  return {
    id: `soul-${row.ticker}-${Date.now()}`,
    ticker: row.ticker,
    side: "watch",
    setup: row.setupRec,
    outcome: "pending",
    rarity: buildRarityFromRow(row),
    pnlPercent: 0,
    closedAt: new Date().toISOString().slice(0, 10),
    lore: `${creature.name} bound at ${row.readiness}% readiness. ${row.actionBias.note}`,
    source: "market-drag",
    slot,
    price: row.price,
    readiness: row.readiness,
    priority: row.priority,
    confidence: row.confidence,
    rec1: row.rec1,
    rec2: row.rec2,
    scoreLeader: row.scoreLeader,
    signalTrigger: row.signalTrigger,
  };
}

/**
 * Format a soul-flame snapshot timestamp for the ember timeline.
 *
 * @param {string|null|undefined} value - ISO snapshot timestamp.
 * @returns {string} Human-readable flame time.
 */
function formatSoulFlameTimestamp(value) {
  if (!value) {
    return "timestamp lost in ash";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "timestamp lost in ash";
  }

  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Render the soul-bound snapshot timeline for the current vault.
 *
 * @returns {string} Timeline HTML.
 */
function renderSoulBoundTimeline() {
  const history = (state.portfolioHistory || []).slice(0, HISTORY_ENTRIES_SHOWN);
  if (!history.length) {
    return `
      <div class="soul-history-timeline">
        <div class="soul-history-head">
          <div>
            <p class="eyebrow">Soul History</p>
            <h4>Ember Timeline</h4>
          </div>
          <span class="pill">0 echoes</span>
        </div>
        <p class="soul-history-empty">No soul-bound echoes have been sealed yet.</p>
      </div>
    `;
  }

  return `
    <div class="soul-history-timeline">
      <div class="soul-history-head">
        <div>
          <p class="eyebrow">Soul History</p>
          <h4>Ember Timeline</h4>
        </div>
        <span class="pill">${history.length} echoes</span>
      </div>
      <div class="soul-history-list">
        ${history
          .map(
            (entry, index) => `
              <div class="soul-history-entry">
                <span class="soul-history-flame" aria-hidden="true"></span>
                <div class="soul-history-copy">
                  <p><strong>${escapeHtml(entry.reason || "Vault reshaped")}</strong></p>
                  <p class="soul-history-meta">${entry.relicCount || 0} relics | ${formatSoulFlameTimestamp(entry.soulFlameAt || entry.savedAt)}</p>
                </div>
                <button
                  class="approval-button pending soul-history-action"
                  data-history-id="${escapeHtml(entry.id)}"
                  type="button"
                  ${index === 0 ? "disabled" : ""}
                  title="${index === 0 ? "Current vault state" : "Revert to this ember"}"
                >
                  ${index === 0 ? "Current" : "Revert"}
                </button>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

/**
 * Open the codex-style modal for one inventory relic.
 *
 * @param {{mount:HTMLElement,item:Record<string, any>,row:Record<string, any>|null,onSelectTicker:(ticker:string)=>void}} params - Modal parameters.
 */
function openInventoryDetailModal({ mount, item, row, onSelectTicker }) {
  const modal = mount.querySelector("[data-inventory-modal]");
  if (!modal) {
    return;
  }

  const rarityLabel = RARITY_LABELS[item.rarity] || "Relic";
  const creature = row ? describeTemperature(row) : null;
  const flavor = row
    ? `${creature.name} clings to ${item.ticker}. ${row.actionBias.note}`
    : item.lore || "This relic remembers an older fight the town has already survived.";

  modal.innerHTML = `
    <div class="inferno-detail-card" role="dialog" aria-modal="true" aria-label="${escapeHtml(item.ticker)} relic detail">
      <div class="actor-head">
        <span class="actor-glyph">${escapeHtml(item.ticker.slice(0, 2))}</span>
        <div>
          <p class="quest-type">${escapeHtml(rarityLabel)} Relic</p>
          <p><strong>${escapeHtml(item.ticker)}</strong> | ${escapeHtml(item.setup || row?.setupRec || "Unknown path")}</p>
        </div>
        <span class="move-chip ${row?.actionBias?.tone || "wild"}">${escapeHtml(item.outcome || row?.status || "bound")}</span>
      </div>
      <p class="candidate-note">${escapeHtml(flavor)}</p>
      <div class="inferno-detail-grid">
        <div class="metric-card"><span>Price</span><strong>${row ? `$${round(row.price, 2)}` : item.price ? `$${round(item.price, 2)}` : "N/A"}</strong></div>
        <div class="metric-card"><span>Readiness</span><strong>${row ? `${row.readiness}%` : item.readiness ? `${item.readiness}%` : "N/A"}</strong></div>
        <div class="metric-card"><span>Priority</span><strong>${row ? row.priority : item.priority ?? "N/A"}</strong></div>
        <div class="metric-card"><span>Confidence</span><strong>${row ? `${row.confidence} / 3` : item.confidence ? `${item.confidence} / 3` : "N/A"}</strong></div>
        <div class="metric-card"><span>Primary Path</span><strong>${escapeHtml(row?.rec1 || item.rec1 || "None")}</strong></div>
        <div class="metric-card"><span>Secondary Path</span><strong>${escapeHtml(row?.rec2 || item.rec2 || "None")}</strong></div>
      </div>
      ${
        row
          ? `<div class="score-stack">
              ${renderBossBar(row, "mini")}
              ${renderTempChip(row)}
            </div>`
          : ""
      }
      <div class="inferno-detail-actions">
        ${
          row
            ? `<button class="approval-button" data-modal-ticker="${escapeHtml(item.ticker)}" type="button">Inspect In Readout</button>`
            : ""
        }
        <button class="approval-button pending" data-close-inventory-modal type="button">Close</button>
      </div>
    </div>
  `;
  modal.classList.add("open");

  modal.querySelector("[data-close-inventory-modal]")?.addEventListener("click", () => {
    modal.classList.remove("open");
  });

  modal.querySelector("[data-modal-ticker]")?.addEventListener("click", () => {
    onSelectTicker(item.ticker);
    modal.classList.remove("open");
  });

  modal.onclick = (event) => {
    if (event.target === modal) {
      modal.classList.remove("open");
    }
  };
}

/**
 * Render the upgraded inventory vault and wire drag/drop behavior.
 *
 * @param {{ui:Record<string, any>,rows:Record<string, any>[],loot:Array<Record<string, any>>,onSelectTicker:(ticker:string)=>void}} params - Vault render parameters.
 */
function renderInventoryVault({ ui, rows, loot, onSelectTicker }) {
  if (!ENABLE_DIABLO_FX) {
    ui.lootVault.innerHTML = loot
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
              <span class="move-chip ${item.tone}">${toneToLootStateLabel(item.tone)}</span>
            </div>
            <p class="candidate-note">${item.note}</p>
          </button>
        `,
      )
      .join("");

    ui.lootVault.querySelectorAll("[data-ticker]").forEach((button) => {
      button.addEventListener("click", () => {
        onSelectTicker(button.dataset.ticker);
      });
    });
    return;
  }

  ensureInventoryFxStyles();
  const rowByTicker = new Map(rows.map((row) => [row.ticker, row]));
  const slottedPortfolio = normalizePortfolioSlots(state.portfolio);
  const portfolioBySlot = new Map(slottedPortfolio.map((item) => [item.slot, item]));
  const pendingRelics = slottedPortfolio.filter((item) => item.outcome === "pending").length;

  ui.lootVault.innerHTML = `
    <div class="inferno-inventory-shell" data-inventory-shell>
      <div class="inferno-particle-burst" data-inventory-burst></div>
      <div class="inferno-detail-modal" data-inventory-modal></div>
      <div class="inferno-inventory-header">
        <div>
          <p class="eyebrow">Soul-Bound Vault</p>
          <h3>Inventory Grid</h3>
          <p class="inventory-drop-hint">Drag names from the roster or shortlist into the vault. Double-click a relic to crack open the codex.</p>
        </div>
        <div class="inferno-inventory-meta">
          <span class="pill">${slottedPortfolio.length} relics</span>
          <span class="pill ${pendingRelics ? "warn" : ""}">${pendingRelics} active binds</span>
          <span class="pill inventory-ghost-pill">${INVENTORY_COLUMNS} x ${INVENTORY_SLOT_COUNT / INVENTORY_COLUMNS} grid</span>
        </div>
      </div>
      <div class="inventory-legend">
        <span class="pill">Common</span>
        <span class="pill status-ready">Uncommon</span>
        <span class="pill status-caution">Rare</span>
        <span class="pill warn">Epic</span>
        <span class="pill risk">Legendary</span>
      </div>
      ${renderSoulBoundTimeline()}
      <div class="inferno-inventory-grid" data-inventory-grid>
        ${[...Array(INVENTORY_SLOT_COUNT).keys()]
          .map((slotIndex) => {
            const item = portfolioBySlot.get(slotIndex);
            const row = item ? rowByTicker.get(item.ticker) || null : null;
            if (!item) {
              return `
                <div class="inferno-slot" data-slot="${slotIndex}" data-slot-label="${slotIndex + 1}">
                  <div class="inventory-empty">Empty</div>
                </div>
              `;
            }

            const rarity = item.rarity || "white";
            const rarityLabel = RARITY_LABELS[rarity] || "Relic";
            const temperature = row ? describeTemperature(row) : null;
            return `
              <div class="inferno-slot filled" data-slot="${slotIndex}" data-slot-label="${slotIndex + 1}">
                <button
                  class="inventory-item rarity-${rarity}"
                  data-item-id="${escapeHtml(item.id)}"
                  data-slot="${slotIndex}"
                  data-ticker="${escapeHtml(item.ticker)}"
                  type="button"
                  draggable="true"
                  title="${escapeHtml(`${item.ticker} | ${rarityLabel} | ${item.lore || "Soul-bound relic"}`)}"
                >
                  <div class="inventory-item-head">
                    <div class="inventory-item-title">
                      <strong>${escapeHtml(item.ticker)}</strong>
                      <span>${escapeHtml(item.setup || row?.setupRec || rarityLabel)}</span>
                    </div>
                    <span class="move-chip ${row?.actionBias?.tone || (item.outcome === "win" ? "hot" : item.outcome === "loss" ? "cold" : "wild")}">${escapeHtml(rarityLabel)}</span>
                  </div>
                  <div class="inventory-item-tags">
                    <span class="pill">${escapeHtml(item.outcome || "bound")}</span>
                    <span class="pill">${row ? `${row.readiness}% ready` : item.readiness ? `${item.readiness}% ready` : "legacy"}</span>
                    <span class="pill">${temperature ? temperature.label : "Relic"}</span>
                  </div>
                  <div class="inventory-item-value">${row ? `${row.priority} priority` : item.pnlPercent ? `${round(item.pnlPercent, 1)}%` : "Pending"}</div>
                </button>
              </div>
            `;
          })
          .join("")}
      </div>
    </div>
    <div class="inventory-relic-feed">
      ${loot
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
                <span class="move-chip ${item.tone}">${toneToLootStateLabel(item.tone)}</span>
              </div>
              <p class="candidate-note">${item.note}</p>
            </button>
          `,
        )
        .join("")}
    </div>
  `;

  const shell = ui.lootVault.querySelector("[data-inventory-shell]");
  const slots = [...ui.lootVault.querySelectorAll("[data-slot]")];
  const itemButtons = [...ui.lootVault.querySelectorAll(".inventory-item")];

  slots.forEach((slotNode) => {
    slotNode.addEventListener("dragover", (event) => {
      event.preventDefault();
      slotNode.classList.add("drop-hover");
      shell.classList.add("hell-rift-active");
      event.dataTransfer.dropEffect = "copy";
    });

    slotNode.addEventListener("dragleave", () => {
      slotNode.classList.remove("drop-hover");
      shell.classList.remove("hell-rift-active");
    });

    slotNode.addEventListener("drop", (event) => {
      event.preventDefault();
      slotNode.classList.remove("drop-hover");
      shell.classList.remove("hell-rift-active");
      const targetSlot = Number(slotNode.dataset.slot);

      const inventoryPayloadRaw = event.dataTransfer.getData(INVENTORY_DRAG_MIME);
      if (inventoryPayloadRaw) {
        try {
          const inventoryPayload = JSON.parse(inventoryPayloadRaw);
          const activePortfolio = normalizePortfolioSlots(state.portfolio);
          const nextPortfolio = activePortfolio.map((entry) => ({ ...entry }));
          const sourceIndex = nextPortfolio.findIndex((entry) => entry.id === inventoryPayload.id);
          const targetIndex = nextPortfolio.findIndex((entry) => entry.slot === targetSlot);
          if (sourceIndex >= 0) {
            const sourceSlot = nextPortfolio[sourceIndex].slot;
            nextPortfolio[sourceIndex].slot = targetSlot;
            if (targetIndex >= 0 && targetIndex !== sourceIndex) {
              nextPortfolio[targetIndex].slot = sourceSlot;
            }
            setPortfolio(nextPortfolio, {
              reason: "Vault relics rearranged",
            });
            spawnSoulFlameBurst(shell, slotNode);
            renderInventoryVault({ ui, rows, loot, onSelectTicker });
          }
        } catch {
          // Ignore malformed inventory drops and leave the vault state untouched.
        }
        return;
      }

      const marketPayloadRaw = event.dataTransfer.getData(MARKET_DRAG_MIME) || event.dataTransfer.getData("text/plain");
      if (!marketPayloadRaw) {
        return;
      }

      try {
        const payload = JSON.parse(marketPayloadRaw);
        const liveRow = rowByTicker.get(payload.ticker);
        if (!liveRow) {
          return;
        }

        const activePortfolio = normalizePortfolioSlots(state.portfolio);
        const existingIndex = activePortfolio.findIndex(
          (entry) => entry.ticker === liveRow.ticker && entry.source === "market-drag",
        );

        if (existingIndex >= 0) {
          const nextPortfolio = activePortfolio.map((entry) => ({ ...entry }));
          const occupantIndex = nextPortfolio.findIndex((entry) => entry.slot === targetSlot);
          const sourceSlot = nextPortfolio[existingIndex].slot;
          nextPortfolio[existingIndex].slot = targetSlot;
          if (occupantIndex >= 0 && occupantIndex !== existingIndex) {
            nextPortfolio[occupantIndex].slot = sourceSlot;
          }
          setPortfolio(nextPortfolio, {
            reason: `${liveRow.ticker} reforged in the vault`,
          });
        } else {
          const nextPortfolio = activePortfolio.map((entry) => ({ ...entry }));
          const occupantIndex = nextPortfolio.findIndex((entry) => entry.slot === targetSlot);
          if (occupantIndex >= 0) {
            const freeSlot = findFirstFreeSlot(nextPortfolio, [targetSlot]);
            if (freeSlot === null) {
              return;
            }
            nextPortfolio[occupantIndex].slot = freeSlot;
          }
          nextPortfolio.push(buildPortfolioRelicFromRow(liveRow, targetSlot));
          setPortfolio(nextPortfolio, {
            reason: `${liveRow.ticker} soul-bound`,
          });
        }

        spawnSoulFlameBurst(shell, slotNode);
        renderInventoryVault({ ui, rows, loot, onSelectTicker });
      } catch {
        // Ignore malformed market payloads to keep the existing dashboard flow safe.
      }
    });
  });

  itemButtons.forEach((button) => {
    button.addEventListener("dragstart", (event) => {
      const item = slottedPortfolio.find((entry) => entry.id === button.dataset.itemId);
      if (!item) {
        return;
      }
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData(
        INVENTORY_DRAG_MIME,
        JSON.stringify({
          id: item.id,
          slot: item.slot,
        }),
      );
      button.classList.add("dragging-soul");
      document.body.classList.add("inferno-drag-active");
      shell.classList.add("hell-rift-active");
    });

    button.addEventListener("dragend", () => {
      button.classList.remove("dragging-soul");
      document.body.classList.remove("inferno-drag-active");
      shell.classList.remove("hell-rift-active");
      slots.forEach((slotNode) => slotNode.classList.remove("drop-hover"));
    });

    button.addEventListener("click", () => {
      const ticker = button.dataset.ticker;
      if (ticker) {
        onSelectTicker(ticker);
      }
    });

    button.addEventListener("dblclick", () => {
      const item = slottedPortfolio.find((entry) => entry.id === button.dataset.itemId);
      if (!item) {
        return;
      }
      openInventoryDetailModal({
        mount: shell,
        item,
        row: rowByTicker.get(item.ticker) || null,
        onSelectTicker,
      });
    });
  });

  ui.lootVault.querySelectorAll(".loot-card[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      onSelectTicker(button.dataset.ticker);
    });
  });

  ui.lootVault.querySelectorAll("[data-history-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const historyId = button.dataset.historyId;
      if (!historyId) {
        return;
      }

      const entry = (state.portfolioHistory || []).find((item) => item.id === historyId);
      if (!entry) {
        return;
      }

      const shouldRevert = window.confirm(
        `Return the vault to "${entry.reason || "a prior ember"}" from ${formatSoulFlameTimestamp(entry.soulFlameAt || entry.savedAt)}? This will overwrite the current binding arrangement, but the revert itself will be sealed as a fresh soul-bound state.`,
      );
      if (!shouldRevert) {
        return;
      }

      revertPortfolioHistory(historyId);
      renderInventoryVault({ ui, rows, loot, onSelectTicker });
    });
  });
}

/**
 * Render the top-line sanctum metrics and play-map summary.
 *
 * @param {{ui:Record<string, any>,rows:Record<string, any>[]}} context - UI rendering context.
 */
export function renderOverview({ ui, rows }) {
  const readyCount = rows.filter((row) => row.status === "Ready").length;
  const triggerCount = rows.filter((row) => row.signalTrigger).length;
  const hotWindowCount = rows.filter((row) => row.daysUntilEarnings <= 14).length;
  const avgReadiness = rows.length
    ? Math.round(rows.reduce((sum, row) => sum + row.readiness, 0) / rows.length)
    : 0;
  const avgPriority = rows.length ? round(rows.reduce((sum, row) => sum + row.priority, 0) / rows.length, 2) : 0;

  ui.overviewStats.innerHTML = [
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
    ui.overviewSummary.textContent = "No active names in the circle right now. Adjust your filters to summon fresh plays.";
    ui.playMap.innerHTML = "";
    return;
  }

  const immediateKillers = rows.filter((row) => row.readiness >= 72).length;
  const triggerLive = rows.filter((row) => row.signalTrigger).length;
  ui.overviewSummary.textContent = `${topPlay.ticker} leads the altar at ${topPlay.readiness}% readiness with a ${topPlay.priority} priority stack driven by ${topPlay.scoreLeader.toLowerCase()}. ${immediateKillers} names are in true striking range and ${triggerLive} already have their trigger lit.`;
  renderPlayMap({ ui, rows });
}

/**
 * Render the campaign board and active town actors.
 *
 * @param {{ui:Record<string, any>,rows:Record<string, any>[],backendState:Record<string, any>,onSelectTicker:(ticker:string)=>void}} context - UI rendering context.
 */
export function renderCampaignBoard({ ui, rows, backendState, onSelectTicker }) {
  const stateView = buildCampaignState(rows, backendState);
  const quests = buildCampaignQuests(rows, backendState);
  const actors = buildTownActors({
    queue: backendState.executionQueue || {},
    opsStatus: backendState.opsStatus,
    watchdogStatus: backendState.watchdogStatus,
    topLongTerm: stateView.topMerchant,
    pendingCount: stateView.pendingCount,
    lastSnapshotAt: backendState.lastSnapshotAt,
  });
  const raidLead = stateView.topRaid ? `${stateView.topRaid.ticker} is the current raid leader.` : "No raid leader is active.";
  const merchantLead = stateView.topMerchant
    ? `${stateView.topMerchant.ticker} is the cleanest discount merchant target.`
    : "No merchant target has earned a discount posture yet.";

  ui.campaignSummary.textContent = `${stateView.rank.label}. Campaign score ${stateView.score}/100. ${stateView.openQuests} open quests are on the board, ${stateView.readyCount} raids are broker-ready, and the town still has ${stateView.warChest} risk units free. ${raidLead} ${merchantLead} ${stateView.rank.note}`;
  ui.campaignStats.innerHTML = [
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

  ui.questBoard.innerHTML = quests.length
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

  ui.townActors.innerHTML = actors
    .map(
      (actor) => `
        <div class="actor-card">
          <div class="actor-head">
            <span class="actor-glyph">${actor.glyph}</span>
            <div>
              <p class="quest-type">${actor.name}</p>
              <p><strong>${actor.status}</strong></p>
            </div>
            <span class="move-chip ${actor.tone}">${toneToActorStateLabel(actor.tone)}</span>
          </div>
          <p class="actor-note">${actor.note}</p>
        </div>
      `,
    )
    .join("");

  ui.questBoard.querySelectorAll("button[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      onSelectTicker(button.dataset.ticker);
    });
  });
}

/**
 * Render the full town board: map, dialogue, loot, and district focus.
 *
 * @param {{ui:Record<string, any>,rows:Record<string, any>[],backendState:Record<string, any>,selectedDistrict:string,onSelectTicker:(ticker:string)=>void,onSelectDistrict:(district:string)=>void}} context - UI rendering context.
 */
export function renderTownBoard({ ui, rows, backendState, selectedDistrict, onSelectTicker, onSelectDistrict }) {
  const campaign = buildCampaignState(rows, backendState);
  const queue = backendState.executionQueue || {};
  const scouts = getScoutCandidates(rows);
  const raidLead = getEligibleCandidates(rows)[0] || null;
  const merchant = getLongTermCandidates(rows)[0] || null;
  const districts = buildTownDistricts({
    campaign,
    queue,
    merchant,
    scouts,
    raidLead,
    opsStatus: backendState.opsStatus,
    watchdogStatus: backendState.watchdogStatus,
  });
  const dialogues = buildTownDialogue({
    queue,
    raidLead,
    merchant,
    scouts,
    approvalQueue: backendState.approvalQueue?.items || [],
    opsStatus: backendState.opsStatus,
    watchdogStatus: backendState.watchdogStatus,
  });
  const loot = buildLootDrops({
    queue,
    raid: raidLead,
    merchant,
    scout: scouts[0] || null,
    opsStatus: backendState.opsStatus,
    watchdogStatus: backendState.watchdogStatus,
  });
  const mood = buildTownMood(campaign);

  ui.townSummary.textContent = `${campaign.rank.label}. ${mood.title} has settled over the village. ${campaign.readyCount} raids are near the gate, ${campaign.pendingCount} still need writs, and the market ${campaign.topMerchant ? `is whispering about ${campaign.topMerchant.ticker}` : "is not offering a true bargain yet"}.`;
  renderTownMap({ ui, rows, districts, selectedDistrict, onSelectDistrict, campaign });
  renderDistrictFocus({ ui, rows, districts, selectedDistrict, onSelectTicker, campaign });

  ui.townDialogue.innerHTML = dialogues
    .map(
      (actor) => `
        <button class="actor-card" ${actor.ticker ? `data-ticker="${actor.ticker}"` : ""} data-district="${actor.districtKey}" type="button">
          <div class="actor-head">
            <span class="actor-glyph">${buildDistrictGlyph(actor.name)}</span>
            <div>
              <p class="quest-type">${actor.name}</p>
              <p><strong>${actor.line}</strong></p>
            </div>
            <span class="move-chip ${actor.tone}">${toneToDialogueStateLabel(actor.tone)}</span>
          </div>
        </button>
      `,
    )
    .join("");
  renderInventoryVault({ ui, rows, loot, onSelectTicker });

  ui.townDialogue.querySelectorAll(".actor-card").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.ticker) {
        onSelectTicker(button.dataset.ticker);
        return;
      }
      if (button.dataset.district) {
        onSelectDistrict(button.dataset.district);
      }
    });
  });
}

/**
 * Render the top encounter ribbon.
 *
 * @param {{ui:Record<string, any>,rows:Record<string, any>[],onSelectTicker:(ticker:string)=>void}} context - UI rendering context.
 */
export function renderSignalRibbon({ ui, rows, onSelectTicker }) {
  if (!rows.length) {
    ui.signalRibbon.innerHTML = `<div class="ribbon-card wild"><p class="eyebrow">Standby</p><p>No encounters match the current filter stack.</p></div>`;
    return;
  }

  ui.signalRibbon.innerHTML = rows
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

  ui.signalRibbon.querySelectorAll("button[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      onSelectTicker(button.dataset.ticker);
    });
  });
}

function renderDistrictFocus({ ui, rows, districts, selectedDistrict, onSelectTicker, campaign }) {
  const district = districts.find((item) => item.key === selectedDistrict) || districts[1] || districts[0];
  const mood = buildTownMood(campaign || buildCampaignState(rows, {}));
  ui.districtFocus.innerHTML = `
    <div class="actor-card district-focus-card">
      <div class="actor-head">
        <span class="actor-glyph">${buildDistrictGlyph(district.name)}</span>
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

  ui.districtFocus.querySelectorAll("[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      onSelectTicker(button.dataset.ticker);
    });
  });
}

function renderTownMap({ ui, rows, districts, selectedDistrict, onSelectDistrict, campaign }) {
  const mood = buildTownMood(campaign);
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

  ui.townMap.innerHTML = `
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
            <g class="town-district ${district.tone} ${selectedDistrict === district.key ? "selected" : ""}" data-district="${district.key}" role="button" tabindex="0" aria-label="${district.name}">
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

  ui.townMap.querySelectorAll("[data-district]").forEach((districtNode) => {
    const selectDistrict = () => {
      onSelectDistrict(districtNode.dataset.district);
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

function renderPlayMap({ ui, rows }) {
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
    const textX = boxX + 10;

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

  ui.playMap.innerHTML = `
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
