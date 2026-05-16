/**
 * frontend/modules/ui/detail.js
 *
 * Purpose:
 * This module renders the close-up reading surfaces: the roster, the infernal
 * readout, and the shortlist. It is the codex table where a single name gets
 * examined before you let it touch capital.
 */

export const ENABLE_DIABLO_FX = true;

import { describeTemperature } from "../dataProcessor.js";
import { buildNarrative, renderBossBar, renderMascotCard, renderTempChip } from "../theme/diablo.js";
import { formatCurrency, formatDate, round } from "../utils.js";
import { renderScoreRow, renderScoreSigils, renderScoreTile } from "./scorecards.js";

const MARKET_DRAG_MIME = "application/x-inferno-market-row";

function toneClass(tone) {
  if (tone === "hot") {
    return "status-ready";
  }
  if (tone === "cold") {
    return "status-risk";
  }
  return "status-caution";
}

function formatSigned(value, places = 2, suffix = "") {
  const numeric = Number(value) || 0;
  return `${numeric >= 0 ? "+" : ""}${round(numeric, places)}${suffix}`;
}

function renderConfirmationCard(label, value, meta, tone = "wild") {
  return `
    <div class="metric-card confirmation-card">
      <span>${label}</span>
      <strong class="${toneClass(tone)}">${value}</strong>
      <small>${meta}</small>
    </div>
  `;
}

/**
 * Build the transferable drag payload for a market candidate.
 *
 * The payload stays intentionally small and JSON-safe so the portfolio vault can
 * reconstruct a soul-bound relic without leaking live DOM references.
 *
 * @param {Record<string, any>} row - Enriched market row.
 * @returns {string} Serialized drag payload.
 */
function buildMarketDragPayload(row) {
  return JSON.stringify({
    ticker: row.ticker,
    setupRec: row.setupRec,
    daysUntilEarnings: row.daysUntilEarnings,
    readiness: row.readiness,
    priority: row.priority,
    confidence: row.confidence,
    ivRank: row.ivRank,
    atrPercent: row.atrPercent,
    nextEarnings: row.nextEarnings,
    price: row.price,
    rec1: row.rec1,
    rec2: row.rec2,
    urgency: row.urgency,
    scoreLeader: row.scoreLeader,
    actionBias: row.actionBias,
    accumulationBias: row.accumulationBias,
    signalTrigger: row.signalTrigger,
    status: row.status,
  });
}

/**
 * Attach the drag-start / drag-end hooks that let roster and shortlist entries
 * fly into the portfolio vault.
 *
 * @param {HTMLElement[]} elements - Draggable source nodes.
 * @param {Map<string, Record<string, any>>} rowByTicker - Market rows keyed by ticker.
 */
function bindMarketDragSources(elements, rowByTicker) {
  if (!ENABLE_DIABLO_FX) {
    return;
  }

  elements.forEach((element) => {
    const ticker = element.dataset.ticker;
    const row = rowByTicker.get(ticker);
    if (!row) {
      return;
    }

    element.setAttribute("draggable", "true");
    element.classList.add("inferno-draggable-source");
    element.title = "Drag this name into the soul-bound inventory vault.";

    element.addEventListener("dragstart", (event) => {
      const payload = buildMarketDragPayload(row);
      event.dataTransfer.effectAllowed = "copy";
      event.dataTransfer.setData(MARKET_DRAG_MIME, payload);
      // `text/plain` keeps the flow resilient in browsers that ignore custom
      // MIME types during HTML5 drag sessions.
      event.dataTransfer.setData("text/plain", payload);
      element.classList.add("dragging-soul");
      document.body.classList.add("inferno-drag-active");
    });

    element.addEventListener("dragend", () => {
      element.classList.remove("dragging-soul");
      document.body.classList.remove("inferno-drag-active");
    });
  });
}

/**
 * Render the main roster table.
 *
 * @param {{ui:Record<string, any>,rows:Record<string, any>[],selectedTicker:string|null,onSelectTicker:(ticker:string)=>void}} context - Rendering context.
 */
export function renderRoster({ ui, rows, selectedTicker, onSelectTicker }) {
  if (!rows.length) {
    ui.rosterBody.innerHTML = `
      <tr>
        <td colspan="11">No targets match the current filters.</td>
      </tr>
    `;
    return;
  }

  ui.rosterBody.innerHTML = rows
    .map((row) => {
      const activeClass = row.ticker === selectedTicker ? "active" : "";
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

  ui.rosterBody.querySelectorAll("tr[data-ticker]").forEach((rowElement) => {
    rowElement.addEventListener("click", () => {
      onSelectTicker(rowElement.dataset.ticker);
    });
  });

  bindMarketDragSources(
    [...ui.rosterBody.querySelectorAll("tr[data-ticker]")],
    new Map(rows.map((row) => [row.ticker, row])),
  );
}

/**
 * Render the infernal readout panel for the selected name.
 *
 * @param {{ui:Record<string, any>,rows:Record<string, any>[],selectedTicker:string|null}} context - Rendering context.
 */
export function renderDetail({ ui, rows, selectedTicker }) {
  const row = rows.find((item) => item.ticker === selectedTicker);

  if (!row) {
    ui.detailTitle.textContent = "No Active Selection";
    ui.detailContent.innerHTML = "<p>Adjust filters or import a CSV to populate the detail console.</p>";
    return;
  }

  ui.detailTitle.textContent = `${row.ticker} Infernal Readout`;
  const creature = describeTemperature(row);
  const statusClass =
    row.status === "Ready" ? "status-ready" : row.status === "Watch" ? "status-caution" : "status-risk";
  const statusPillClass = row.status === "Ready" ? "" : row.status === "Watch" ? "warn" : "risk";
  const context = row.marketContext || {};

  ui.detailContent.innerHTML = `
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
        ${
          ENABLE_DIABLO_FX
            ? '<p class="muted detail-drag-hint">Drag this vessel from the roster into the soul-bound inventory vault to bind it as a tracked relic.</p>'
            : ""
        }
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

    <div class="score-breakout detail-confirmation">
      <div class="score-breakout-head">
        <p class="eyebrow">Bias Confirmation</p>
        <strong>${context.alignmentLabel || "Developing"} | ${context.alignmentScore || "0.0"} stack</strong>
      </div>
      <div class="detail-confirmation-grid">
        ${renderConfirmationCard("$RVOL", `${context.rvol || "0.00"}x`, row.signalTrigger ? "volume is helping the move" : "confirmation still forming", Number(context.rvol) >= 1.3 ? "hot" : Number(context.rvol) >= 0.95 ? "wild" : "cold")}
        ${renderConfirmationCard("Trend", context.trend?.label || "Neutral", row.signalTrigger ? "trigger agrees with the slope" : "watch for cleaner alignment", context.trend?.tone || "wild")}
        ${renderConfirmationCard("ATR Expand", formatSigned(context.atrExpansion, 2), Number(context.atrExpansion) >= 1 ? "range is opening up" : "expansion is still muted", Number(context.atrExpansion) >= 1 ? "hot" : Number(context.atrExpansion) >= 0 ? "wild" : "cold")}
        ${renderConfirmationCard("IV Impulse", formatSigned(context.ivImpulse, 3), Number(context.ivImpulse) >= 0 ? "options market is leaning in" : "volatility is fading", Number(context.ivImpulse) >= 0.05 ? "hot" : Number(context.ivImpulse) >= -0.02 ? "wild" : "cold")}
        ${renderConfirmationCard("Support", formatCurrency(context.support || 0), `${context.distanceToSupportPct || "0.00"}% below spot`, "wild")}
        ${renderConfirmationCard("Resistance", formatCurrency(context.resistance || 0), `${context.distanceToResistancePct || "0.00"}% above spot`, "wild")}
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

/**
 * Render the shortlist rail.
 *
 * @param {{ui:Record<string, any>,rows:Record<string, any>[],onSelectTicker:(ticker:string)=>void}} context - Rendering context.
 */
export function renderShortlist({ ui, rows, onSelectTicker }) {
  ui.shortlist.innerHTML = rows
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

  ui.shortlist.querySelectorAll("button[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      onSelectTicker(button.dataset.ticker);
    });
  });

  bindMarketDragSources(
    [...ui.shortlist.querySelectorAll("button[data-ticker]")],
    new Map(rows.slice(0, 5).map((row) => [row.ticker, row])),
  );
}
