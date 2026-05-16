/**
 * frontend/modules/ui/scorecards.js
 *
 * Purpose:
 * This module renders the small infernal score artifacts used across the desk.
 * It keeps bars, tiles, and sigils consistent so every panel reads like part of
 * the same Diablo-flavored codex instead of a stitched-together spreadsheet.
 */

import { scoreToPercent } from "../dataProcessor.js";
import { round } from "../utils.js";

/**
 * Render a labeled score row with a horizontal ember bar.
 *
 * @param {string} label - Human-readable score name.
 * @param {number} value - Score magnitude.
 * @param {number} [ceiling=2.5] - Visual normalization ceiling.
 * @returns {string} HTML markup string.
 */
export function renderScoreRow(label, value, ceiling = 2.5) {
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

/**
 * Render a compact score tile with a mini bar.
 *
 * @param {string} label - Score label.
 * @param {number} value - Score value.
 * @returns {string} HTML markup string.
 */
export function renderScoreTile(label, value) {
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

/**
 * Render the four infernal stat sigils used on candidate cards.
 *
 * @param {Record<string, any>} row - Enriched dashboard row.
 * @returns {string} HTML markup string.
 */
export function renderScoreSigils(row) {
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
