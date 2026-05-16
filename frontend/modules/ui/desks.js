/**
 * frontend/modules/ui/desks.js
 *
 * Purpose:
 * This module runs the working surfaces inside town: ops watch, conviction
 * gates, accumulation lane, execution desk, and morning brief. It is where the
 * simulation behaves like an actual trading desk instead of just a scenic map.
 */

import { convictionConfig } from "../dataProcessor.js";
import { renderBossBar, renderTempChip } from "../theme/diablo.js";
import { formatBackendDate, round } from "../utils.js";
import { renderScoreSigils } from "./scorecards.js";
import {
  buildMorningBrief,
  buildPaperTickets,
  gateChecks,
  getEligibleCandidates,
  getLongTermCandidates,
} from "./strategy.js";

function verdictTone(verdict) {
  const normalized = String(verdict || "").toLowerCase();
  if (["healthy", "ready", "ready-for-pilot", "ready-live-readonly", "armed", "supported"].includes(normalized)) {
    return "status-ready";
  }
  if (["review", "approval-bottleneck", "paper-evidence-only", "attention", "constructive"].includes(normalized)) {
    return "status-caution";
  }
  return "status-risk";
}

function verdictLabel(verdict, fallback = "Unknown") {
  return String(verdict || fallback)
    .replaceAll("-", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

/**
 * Render the live operations watch grid and feed.
 *
 * @param {{ui:Record<string, any>,backendState:Record<string, any>}} context - Rendering context.
 */
export function renderOpsWatch({ ui, backendState }) {
  const ops = backendState.opsStatus;
  const watchdog = backendState.watchdogStatus;
  const executionQueue = backendState.executionQueue;
  const liveSync = backendState.liveAccountSync;
  const liveReview = backendState.livePositionReview;
  const commandCenter = backendState.modelCommandCenter;
  const centralCommand = backendState.centralCommand;
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
      value: backendState.smtpConfigured ? "Armed" : "Offline",
      tone: backendState.smtpConfigured ? "status-ready" : "status-risk",
    },
    {
      label: "Last Auto Run",
      value: formatBackendDate(ops?.generatedAt || backendState.lastSnapshotAt),
      tone: "status-caution",
    },
    {
      label: "Watchdog",
      value: watchdogOk === undefined ? "Unknown" : watchdogOk ? "Watching" : "Barking",
      tone: watchdogOk ? "status-ready" : "status-risk",
    },
    {
      label: "Approval Desk",
      value: backendState.approvalQueue?.count ?? 0,
      tone: (backendState.approvalQueue?.count ?? 0) > 0 ? "status-caution" : "status-ready",
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
    {
      label: "Live Book",
      value: verdictLabel(liveReview?.verdict || liveSync?.verdict, liveSync ? "Review" : "Unknown"),
      tone: verdictTone(liveReview?.verdict || liveSync?.verdict),
    },
    {
      label: "Shared Brain",
      value: verdictLabel(centralCommand?.verdict || commandCenter?.status, commandCenter ? "Ready" : "Offline"),
      tone: verdictTone(centralCommand?.verdict || commandCenter?.status),
    },
  ];

  ui.opsGrid.innerHTML = cards
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
  if (backendState.approvalQueue?.items?.length) {
    messages.push(
      `Approval desk waiting on: ${backendState.approvalQueue.items
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
  if (liveSync?.message) {
    const syncCounts = liveSync.counts || {};
    messages.push(
      `Live account lane: ${liveSync.message}. Positions ${syncCounts.positions ?? 0}, matched ${syncCounts.matchedPositions ?? 0}, suffix ${liveSync.matchedSuffix || "unverified"}.`,
    );
  }
  if (liveReview?.counts) {
    const reviewCounts = liveReview.counts || {};
    messages.push(
      `Live posture: ${verdictLabel(liveReview.verdict)}. Supported ${reviewCounts.supported ?? 0}, review ${reviewCounts.review ?? 0}, fragile ${reviewCounts.fragile ?? 0}.`,
    );
  }
  if (centralCommand?.recommendedNextMove) {
    messages.push(`Central command: ${centralCommand.recommendedNextMove}`);
  } else if (commandCenter?.nextActions?.length) {
    messages.push(`Shared brain next move: ${commandCenter.nextActions[0]}`);
  }
  if (commandCenter?.activeMissions?.length) {
    messages.push(
      `Mission queue: ${commandCenter.activeMissions
        .slice(0, 3)
        .map((mission) => `${mission.owner}: ${mission.title}`)
        .join(" | ")}`,
    );
  }
  if (watchdog?.reasons?.length) {
    messages.push(`Watchdog notes: ${watchdog.reasons.join("; ")}`);
  } else if (watchdogOk) {
    messages.push("Watchdog sees no faults in the latest automation cycle.");
  } else {
    messages.push("Watchdog standing by for its first patrol.");
  }

  ui.opsFeed.innerHTML = messages.map((message) => `<div class="brief-card">${message}</div>`).join("");
}

/**
 * Render the conviction gate panel.
 *
 * @param {{ui:Record<string, any>,rows:Record<string, any>[]}} context - Rendering context.
 */
export function renderConvictionEngine({ ui, rows }) {
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

  ui.engineRules.innerHTML = gateRows
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
    ui.engineCandidates.innerHTML = `
      <div class="candidate-card">
        <p><strong>No names have earned full conviction yet.</strong></p>
        <p class="muted">The engine is doing its job. Better no trade than fake conviction.</p>
      </div>
    `;
    return;
  }

  ui.engineCandidates.innerHTML = eligible
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

/**
 * Render the long-term accumulation lane.
 *
 * @param {{ui:Record<string, any>,rows:Record<string, any>[],onSelectTicker:(ticker:string)=>void}} context - Rendering context.
 */
export function renderAccumulationDesk({ ui, rows, onSelectTicker }) {
  const candidates = getLongTermCandidates(rows);
  if (!candidates.length) {
    ui.longTermSummary.textContent = "No long-term names are calm enough and cheap enough to deserve accumulation right now.";
    ui.longTermCandidatesEl.innerHTML = `
      <div class="candidate-card accumulation-card">
        <p><strong>No accumulation buys earned conviction yet.</strong></p>
        <p class="muted">That is a feature, not a bug. This lane exists to stop you from buying quality names at bad prices.</p>
      </div>
    `;
    return;
  }

  ui.longTermSummary.textContent = `${candidates[0].ticker} is the cleanest discount candidate right now at a ${candidates[0].longTermScore} accumulation score. This lane rewards value, compression, and names that are not already in full chase mode.`;
  ui.longTermCandidatesEl.innerHTML = candidates
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

  ui.longTermCandidatesEl.querySelectorAll("button[data-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      onSelectTicker(button.dataset.ticker);
    });
  });
}

/**
 * Render the execution desk and wire broker-review actions.
 *
 * @param {{ui:Record<string, any>,backendState:Record<string, any>,onUpdateApprovalStatus:(ticker:string,status:string)=>Promise<void>,onResetApprovalQueue:()=>Promise<void>,onCopyExecutionTicket:(item:Record<string, any>)=>Promise<void>}} context - Rendering context.
 */
export function renderExecutionDesk({
  ui,
  backendState,
  onUpdateApprovalStatus,
  onResetApprovalQueue,
  onCopyExecutionTicket,
}) {
  const queue = backendState.executionQueue;
  if (!queue?.items?.length) {
    ui.executionSummary.textContent = "No execution intents are staged yet. The clerk is waiting on a fresh approval queue.";
    ui.executionCandidates.innerHTML = `
      <div class="candidate-card">
        <p><strong>No order intents are armed.</strong></p>
        <p class="muted">The desk is still behaving safely. Nothing should touch a broker surface until approval, trigger, and risk budget all line up.</p>
      </div>
    `;
    return;
  }

  ui.executionSummary.textContent = `${queue.activeReadyCount} intents are broker-ready inside a ${queue.dailyRiskBudget} risk-unit day. ${queue.pendingCount || 0} still need human approval, ${queue.rejectedCount || 0} are buried, and the staged risk stack is ${round(queue.stagedRiskUnits || 0, 2)} units. Last clerk update: ${formatBackendDate(queue.updatedAt || queue.generatedAt)}.`;
  ui.executionCandidates.innerHTML = `
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
      ui.executionSummary.textContent = "Resetting approval desk...";
      try {
        await onResetApprovalQueue();
      } catch {
        ui.executionSummary.textContent = "Could not reset the approval desk.";
      }
    });
  }

  ui.executionCandidates.querySelectorAll("[data-approval-ticker]").forEach((button) => {
    button.addEventListener("click", async () => {
      const ticker = button.dataset.approvalTicker;
      const status = button.dataset.approvalStatus;
      ui.executionSummary.textContent = `Updating ${ticker} to ${status}...`;
      try {
        await onUpdateApprovalStatus(ticker, status);
      } catch {
        ui.executionSummary.textContent = `Could not update ${ticker}.`;
      }
    });
  });

  ui.executionCandidates.querySelectorAll("[data-ticket-index]").forEach((button) => {
    button.addEventListener("click", async () => {
      const index = Number(button.dataset.ticketIndex);
      const item = queue.items[index];
      if (!item?.ticketText) {
        ui.executionSummary.textContent = "Ticket blueprint was unavailable for that name.";
        return;
      }
      await onCopyExecutionTicket(item);
    });
  });
}

/**
 * Render the morning brief panel and return the current artifact strings.
 *
 * @param {{ui:Record<string, any>,rows:Record<string, any>[],backendState:Record<string, any>}} context - Rendering context.
 * @returns {{brief:string,tickets:string,longTerm:string}} Latest rendered artifacts.
 */
export function renderMorningBrief({ ui, rows, backendState }) {
  const brief = buildMorningBrief(rows);
  const liveSync = backendState.liveAccountSync;
  const liveReview = backendState.livePositionReview;
  const commandCenter = backendState.modelCommandCenter;
  const centralCommand = backendState.centralCommand;
  const backendText = backendState.available
    ? backendState.smtpConfigured
      ? "Local command server online. SMTP is armed."
      : "Local command server online. Snapshot saves work; SMTP is not configured yet."
    : "Static mode. Run python3 server.py to save snapshots and unlock SMTP delivery.";
  ui.briefStatus.textContent = `${brief.eligible.length} names currently pass the full conviction engine. ${backendText}`;
  const missionCount = commandCenter?.activeMissions?.length || commandCenter?.missionCount || 0;
  const noteCount = commandCenter?.recentNotes?.length || commandCenter?.noteCount || 0;
  const liveSyncCounts = liveSync?.counts || {};
  const liveReviewCounts = liveReview?.counts || {};
  ui.briefPreview.innerHTML = `
    <div class="brief-subgrid">
      <div class="brief-card brief-supervisor-card">
        <p class="eyebrow">Central Command</p>
        <strong class="${verdictTone(centralCommand?.verdict || commandCenter?.status)}">${verdictLabel(centralCommand?.verdict || commandCenter?.status, "Offline")}</strong>
        <p>${centralCommand?.recommendedNextMove || commandCenter?.nextActions?.[0] || "No command-center action recorded yet."}</p>
        <div class="brief-statline">
          <span>Missions ${missionCount}</span>
          <span>Notes ${noteCount}</span>
          <span>Fragile ${commandCenter?.headlineMetrics?.liveFragile ?? liveReviewCounts.fragile ?? 0}</span>
        </div>
      </div>
      <div class="brief-card brief-supervisor-card">
        <p class="eyebrow">Live Book</p>
        <strong class="${verdictTone(liveReview?.verdict || liveSync?.verdict)}">${verdictLabel(liveReview?.verdict || liveSync?.verdict, "Unverified")}</strong>
        <p>${liveReview?.message || liveSync?.message || "Live account sync has not checked in yet."}</p>
        <div class="brief-statline">
          <span>Positions ${liveSyncCounts.positions ?? 0}</span>
          <span>Matched ${liveSyncCounts.matchedPositions ?? 0}</span>
          <span>Suffix ${liveSync?.matchedSuffix || "n/a"}</span>
        </div>
      </div>
    </div>
    <div class="brief-card">${brief.text}</div>
  `;

  return {
    brief: brief.text,
    tickets: buildPaperTickets(rows),
    longTerm: brief.longTermText,
  };
}
