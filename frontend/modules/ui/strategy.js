/**
 * frontend/modules/ui/strategy.js
 *
 * Purpose:
 * This module models the town's decisions without touching the DOM. It decides
 * who earns a raid, who belongs in the market lane, and how the morning brief
 * reads, so the visual layer stays focused on display instead of hidden scoring
 * rituals.
 */

import { convictionConfig } from "../dataProcessor.js";
import { buildNarrative } from "../theme/diablo.js";
import { clamp, formatBackendDate, round } from "../utils.js";

/**
 * Translate the live campaign score into a story-state label.
 *
 * @param {number} score - Campaign score from 0 to 100.
 * @param {number} readyCount - Broker-ready raid count.
 * @param {number} openQuests - Total live quest count.
 * @returns {{label:string,tone:string,note:string}} Campaign rank metadata.
 */
export function buildCampaignRank(score, readyCount, openQuests) {
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

/**
 * Evaluate all conviction gates for a row.
 *
 * @param {Record<string, any>} row - Enriched dashboard row.
 * @returns {{readiness:boolean,confidence:boolean,timing:boolean,trigger:boolean,setup:boolean}} Gate result map.
 */
export function gateChecks(row) {
  return {
    readiness: row.readiness >= convictionConfig.minReadiness,
    confidence: row.confidence >= convictionConfig.minConfidence,
    timing: row.daysUntilEarnings <= convictionConfig.maxDaysUntilEarnings,
    trigger: convictionConfig.requireTrigger ? row.signalTrigger : true,
    setup: !convictionConfig.bannedSetups.includes(row.setupRec),
  };
}

/**
 * Produce human-readable failure reasons for a row's conviction gates.
 *
 * @param {Record<string, any>} row - Enriched dashboard row.
 * @returns {string[]} Failure reasons.
 */
export function gateFailures(row) {
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

/**
 * Return the rows that satisfy every raid gate.
 *
 * @param {Record<string, any>[]} rows - Enriched dashboard rows.
 * @returns {Record<string, any>[]} Eligible raid rows.
 */
export function getEligibleCandidates(rows) {
  return rows.filter((row) => gateFailures(row).length === 0);
}

/**
 * Return long-term accumulation candidates ranked by the current heuristic.
 *
 * @param {Record<string, any>[]} rows - Enriched dashboard rows.
 * @returns {Record<string, any>[]} Long-term candidates.
 */
export function getLongTermCandidates(rows) {
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

/**
 * Build the long-term merchant brief copy.
 *
 * @param {Record<string, any>[]} rows - Enriched dashboard rows.
 * @returns {{text:string,candidates:Record<string, any>[]}} Brief text and ranked candidates.
 */
export function buildLongTermBrief(rows) {
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

/**
 * Assemble the meta-state for the town campaign layer.
 *
 * @param {Record<string, any>[]} rows - Enriched dashboard rows.
 * @param {Record<string, any>} [backendState={}] - Backend state slice.
 * @returns {Record<string, any>} Campaign state descriptor.
 */
export function buildCampaignState(rows, backendState = {}) {
  const eligible = getEligibleCandidates(rows);
  const longTerm = getLongTermCandidates(rows);
  const queue = backendState.executionQueue || {};
  const ops = backendState.opsStatus;
  const watchdog = backendState.watchdogStatus;
  const approvalQueue = backendState.approvalQueue || {};
  const pendingCount =
    queue.pendingCount ??
    (approvalQueue.items?.filter((item) => item.approvalStatus === "pending").length || 0);
  const rejectedCount =
    queue.rejectedCount ??
    (approvalQueue.items?.filter((item) => item.approvalStatus === "rejected").length || 0);
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
  if (backendState.smtpConfigured) {
    score += 5;
  }

  // Reward active opportunity density, but cap the boost so the score doesn't
  // become a runaway proxy for "just more names."
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
    lastUpdate: formatBackendDate(queue.updatedAt || queue.generatedAt || ops?.generatedAt || backendState.lastSnapshotAt),
  };
}

/**
 * Build a single campaign quest card model.
 *
 * @param {Record<string, any>} row - Enriched dashboard row.
 * @param {"raid"|"merchant"|"scout"} type - Quest family.
 * @param {number} rank - Display rank within the family.
 * @param {Record<string, any>|undefined} executionItem - Matching execution queue item.
 * @returns {Record<string, any>} Quest card data.
 */
export function buildQuestForRow(row, type, rank, executionItem) {
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

/**
 * Build the displayed quest stack for the campaign board.
 *
 * @param {Record<string, any>[]} rows - Enriched dashboard rows.
 * @param {Record<string, any>} [backendState={}] - Backend state slice.
 * @returns {Record<string, any>[]} Quest descriptors.
 */
export function buildCampaignQuests(rows, backendState = {}) {
  const executionByTicker = Object.fromEntries(
    (backendState.executionQueue?.items || []).map((item) => [item.ticker, item]),
  );
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

/**
 * Return scout-lane candidates that are not already in raid or merchant lanes.
 *
 * @param {Record<string, any>[]} rows - Enriched dashboard rows.
 * @returns {Record<string, any>[]} Scout candidates.
 */
export function getScoutCandidates(rows) {
  const eligibleTickers = new Set(getEligibleCandidates(rows).map((row) => row.ticker));
  const longTermTickers = new Set(getLongTermCandidates(rows).map((row) => row.ticker));
  return rows
    .filter((row) => !eligibleTickers.has(row.ticker) && !longTermTickers.has(row.ticker))
    .filter((row) => row.readiness >= 56 || row.confidence >= 2 || row.signalTrigger)
    .slice(0, 3);
}

/**
 * Build the morning brief text and ranked subsets.
 *
 * @param {Record<string, any>[]} rows - Enriched dashboard rows.
 * @returns {{text:string,eligible:Record<string, any>[],recommended:Record<string, any>[],longTermCandidates:Record<string, any>[],longTermText:string}} Brief model.
 */
export function buildMorningBrief(rows) {
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

/**
 * Build simulated paper tickets from the current raid-eligible set.
 *
 * @param {Record<string, any>[]} rows - Enriched dashboard rows.
 * @returns {string} Multi-ticket plain-text block.
 */
export function buildPaperTickets(rows) {
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

/**
 * Build the payload persisted to the local command server when forging a brief.
 *
 * @param {Record<string, any>[]} rows - Active filtered rows.
 * @param {Record<string, any>} sourceState - Live dashboard state.
 * @returns {Record<string, any>} Snapshot payload.
 */
export function buildSnapshotPayload(rows, sourceState) {
  const longTerm = buildLongTermBrief(rows);
  return {
    generatedAt: new Date().toISOString(),
    sourceLabel: sourceState.sourceLabel,
    brief: sourceState.latestBrief,
    tickets: sourceState.latestTickets,
    longTermBrief: longTerm.text,
    eligibleTickers: getEligibleCandidates(rows).map((row) => row.ticker),
    longTermTickers: longTerm.candidates.map((row) => row.ticker),
    longTermRows: longTerm.candidates,
    executionQueue: sourceState.backend.executionQueue,
    rows,
  };
}
