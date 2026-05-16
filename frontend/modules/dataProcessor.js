/**
 * frontend/modules/dataProcessor.js
 *
 * Purpose:
 * This module is the conviction engine for diablotrading. It enriches raw tracker
 * rows into demonic market entities, assigns temperature and bias, and turns flat
 * spreadsheet cells into the living data the town, desks, and quest systems use.
 */

import { clamp, round } from "./utils.js";

/**
 * The current ruleset for the conviction gate.
 *
 * Exported as data so the desk, renderers, and future simulations can all read
 * the same thresholds without leaking hard-coded globals.
 *
 * @type {{minReadiness:number,minConfidence:number,maxDaysUntilEarnings:number,requireTrigger:boolean,bannedSetups:string[]}}
 */
export const convictionConfig = {
  minReadiness: 72,
  minConfidence: 2,
  maxDaysUntilEarnings: 21,
  requireTrigger: true,
  bannedSetups: ["Avoid"],
};

/**
 * Creature taxonomy used to personify market heat.
 *
 * @type {{hot:{key:string,name:string,miniFace:string,label:string,role:string,hint:string},wild:{key:string,name:string,miniFace:string,label:string,role:string,hint:string},cold:{key:string,name:string,miniFace:string,label:string,role:string,hint:string}}}
 */
export const creatureGuide = {
  hot: {
    key: "hot",
    name: "Ashen Revenant",
    miniFace: ">:)",
    label: "Hellbound",
    role: "A market revenant fed by pain, momentum, and names that refuse to die quietly.",
    hint: "These are the killers. They usually show up when readiness is high and the trigger is already breathing fire.",
  },
  wild: {
    key: "wild",
    name: "Chain Wraith",
    miniFace: "o:o",
    label: "Tormented",
    role: "A screaming wraith dragged by volatility, squeeze, and unfinished conviction.",
    hint: "These can become monsters fast. Watch them when volatility is loud but structure still needs form.",
  },
  cold: {
    key: "cold",
    name: "Grave Bishop",
    miniFace: "x_x",
    label: "Buried",
    role: "A priest of dead setups, fake conviction, and numbers that smell rich but move poor.",
    hint: "Good for discipline. Not everything deserves capital just because it promises salvation.",
  },
};

const enrichRowCache = new Map();

/**
 * Convert a raw sub-score into a percent-style contribution.
 *
 * @param {number} value - Raw score component.
 * @param {number} [ceiling=2.5] - Practical max for the component.
 * @returns {number} Normalized contribution from 0-100.
 */
export function scoreToPercent(value, ceiling = 2.5) {
  return clamp((value / ceiling) * 100, 0, 100);
}

/**
 * Weight option structure into the readiness engine.
 *
 * Vertical calls get the strongest directional edge, straddles remain highly
 * favored for earnings volatility, and avoid names are actively penalized.
 *
 * @param {string} setupRec - Setup recommendation string.
 * @returns {number} Readiness weight contribution.
 */
export function setupWeight(setupRec) {
  const lowered = String(setupRec).toLowerCase();
  if (lowered.includes("vertical")) {
    return 13;
  }
  if (lowered.includes("straddle")) {
    return 11;
  }
  if (lowered.includes("condor")) {
    return 8;
  }
  if (lowered.includes("avoid")) {
    return -10;
  }
  return 0;
}

/**
 * Weight urgency labels into the readiness engine.
 *
 * @param {string} urgency - Urgency label from the tracker.
 * @returns {number} Readiness weight contribution.
 */
export function urgencyWeight(urgency) {
  const lowered = String(urgency).toLowerCase();
  if (lowered.includes("urgent")) {
    return 18;
  }
  if (lowered.includes("watch")) {
    return 8;
  }
  if (lowered.includes("avoid")) {
    return -16;
  }
  return 0;
}

/**
 * Translate readiness into a coarse desk state.
 *
 * @param {number} readiness - Final readiness score.
 * @returns {"Ready"|"Watch"|"Avoid"} Status label.
 */
export function readinessLabel(readiness) {
  if (readiness >= 72) {
    return "Ready";
  }
  if (readiness >= 48) {
    return "Watch";
  }
  return "Avoid";
}

/**
 * Find the score family doing the heaviest lifting.
 *
 * @param {{valueScore:number,momentumScore:number,squeezeScore:number,readyScore:number}} row - Scored row.
 * @returns {[string, number]} Leading score label and value.
 */
export function dominantScore(row) {
  const entries = [
    ["Value", row.valueScore],
    ["Momentum", row.momentumScore],
    ["Squeeze", row.squeezeScore],
    ["Ready", row.readyScore],
  ];
  return entries.sort((a, b) => b[1] - a[1])[0] || ["Value", 0];
}

/**
 * Small valuation bonus for long-term accumulation scoring.
 *
 * Lower PE names receive a modest tailwind, but expensive names are only gently
 * penalized so valuation does not completely dominate quality and structure.
 *
 * @param {number|null} pe - Price/earnings ratio.
 * @returns {number} Long-term valuation adjustment.
 */
export function valuationBonus(pe) {
  if (!Number.isFinite(pe) || pe <= 0) {
    return 0;
  }
  if (pe <= 20) {
    return 0.55;
  }
  if (pe <= 35) {
    return 0.35;
  }
  if (pe <= 50) {
    return 0.12;
  }
  return -0.18;
}

/**
 * Build a short-term action posture from readiness and score stack.
 *
 * @param {Record<string, any>} row - Enriched or partially enriched row.
 * @param {number} priority - Composite priority stack.
 * @returns {{label:string,tone:string,note:string}} Action bias object.
 */
export function buildActionBias(row, priority) {
  if (
    row.signalTrigger &&
    row.readyScore >= 1 &&
    row.momentumScore >= 0.8 &&
    row.confidence >= 2 &&
    row.daysUntilEarnings <= 21 &&
    priority >= 3
  ) {
    return {
      label: "Make A Move",
      tone: "hot",
      note: "Trigger, timing, and score stack are all lined up.",
    };
  }

  if (
    priority >= 2.2 ||
    row.squeezeScore >= 1.1 ||
    row.valueScore >= 1.2 ||
    row.momentumScore >= 1
  ) {
    return {
      label: "Stalk It",
      tone: "wild",
      note: "There is real edge here, but it still wants cleaner confirmation or timing.",
    };
  }

  return {
    label: "Wait",
    tone: "cold",
    note: "The sheet sees something, but not enough to commit capital yet.",
  };
}

/**
 * Build the long-term accumulation posture.
 *
 * @param {number} score - Long-term accumulation score.
 * @returns {{label:string,tone:string,note:string}} Accumulation bias object.
 */
export function buildAccumulationBias(score) {
  if (score >= 4.4) {
    return {
      label: "Accumulate",
      tone: "hot",
      note: "Conviction is high and the name is calm enough to buy without chasing it.",
    };
  }

  if (score >= 3.2) {
    return {
      label: "Nibble",
      tone: "wild",
      note: "The name is worth building slowly, but the discount is not screaming yet.",
    };
  }

  return {
    label: "Wait For Weakness",
    tone: "cold",
    note: "You may want the company, but the price still does not deserve urgency.",
  };
}

/**
 * Build short narrative reasons for long-term accumulation.
 *
 * @param {Record<string, any>} row - Enriched or partially enriched row.
 * @returns {string[]} Up to three reasons supporting a long-term nibble.
 */
export function buildAccumulationReasons(row) {
  const reasons = [];
  if (row.valueScore >= 1) {
    reasons.push("value stack is still doing real work");
  }
  if (row.squeezeScore >= 1) {
    reasons.push("the name is compressed instead of euphoric");
  }
  if (row.momentumScore <= 0.35) {
    reasons.push("the move is not already extended");
  }
  if (row.readiness <= 68) {
    reasons.push("it is not in full chase mode");
  }
  if (row.eps > 0) {
    reasons.push("the business is still printing earnings");
  }
  if (Number.isFinite(row.pe) && row.pe > 0 && row.pe <= 35) {
    reasons.push("valuation still lives in a sane range");
  }
  return reasons.length ? reasons.slice(0, 3) : ["conviction is intact, but price heat is still restrained"];
}

/**
 * Build a conservative proxy for relative volume when the tracker does not
 * carry a dedicated RVOL field yet.
 *
 * If a future pipeline writes a true `rvol` reading, this helper will respect
 * it and only fall back to the proxy for older snapshots or CSV imports.
 *
 * @param {Record<string, any>} row - Raw or enriched tracker row.
 * @returns {number} Relative-volume style multiplier.
 */
export function relativeVolumeProxy(row) {
  if (Number.isFinite(row.rvol)) {
    return round(row.rvol, 2);
  }
  if (Number.isFinite(row.marketContext?.rvol)) {
    return round(row.marketContext.rvol, 2);
  }

  const proxy =
    1 +
    clamp(row.atrZScore ?? 0, -2, 3) * 0.22 +
    clamp(row.momentumScore ?? 0, 0, 2.5) * 0.18 +
    (row.signalTrigger ? 0.22 : 0) +
    (String(row.urgency || "").toLowerCase().includes("urgent") ? 0.12 : 0);
  return round(clamp(proxy, 0.55, 3.6), 2);
}

/**
 * Infer a simple trend label for the detail console.
 *
 * @param {Record<string, any>} row - Raw or enriched tracker row.
 * @returns {{label:string,tone:string}} Trend descriptor.
 */
export function buildTrendDescriptor(row) {
  const explicitTrend = row.trend || row.marketContext?.trend;
  if (explicitTrend && typeof explicitTrend === "object") {
    return {
      label: explicitTrend.label || "Neutral",
      tone: explicitTrend.tone || "wild",
    };
  }
  if (typeof explicitTrend === "string" && explicitTrend.trim()) {
    const label = explicitTrend.trim();
    const lowered = label.toLowerCase();
    return {
      label,
      tone:
        lowered === "bullish" || lowered === "uptrend"
          ? "hot"
          : lowered === "bearish" || lowered === "downtrend"
            ? "cold"
            : "wild",
    };
  }
  if (String(row.setupRec || "").toLowerCase().includes("avoid")) {
    return { label: "Bearish", tone: "cold" };
  }
  if ((row.momentumScore ?? 0) >= 1.1 && row.signalTrigger) {
    return { label: "Bullish", tone: "hot" };
  }
  if ((row.valueScore ?? 0) >= 1 && (row.momentumScore ?? 0) <= 0.45) {
    return { label: "Basing", tone: "wild" };
  }
  if ((row.momentumScore ?? 0) >= 0.55) {
    return { label: "Uptrend", tone: "hot" };
  }
  return { label: "Neutral", tone: "wild" };
}

/**
 * Derive a structure range around price for support/resistance readouts.
 *
 * We use 20-day ATR when available and fall back to ATR% so the right-rail
 * measurements remain stable across sheet sync, CSV imports, and cached sample
 * data.
 *
 * @param {Record<string, any>} row - Raw or enriched tracker row.
 * @returns {{support:number,resistance:number,rangeWidth:number}} Price structure levels.
 */
export function buildSupportResistance(row) {
  const explicitSupport = Number(row.support ?? row.marketContext?.support);
  const explicitResistance = Number(row.resistance ?? row.marketContext?.resistance);
  if (Number.isFinite(explicitSupport) && Number.isFinite(explicitResistance)) {
    return {
      support: round(explicitSupport, 2),
      resistance: round(explicitResistance, 2),
      rangeWidth: round(Math.max(0, explicitResistance - explicitSupport), 2),
    };
  }

  const price = Number(row.price) || 0;
  const atrFromPercent = price * ((Number(row.atrPercent) || 0) / 100);
  const rangeWidth = Math.max(Number(row.atr20Day) || 0, atrFromPercent, price * 0.02);
  return {
    support: round(Math.max(0, price - rangeWidth), 2),
    resistance: round(price + rangeWidth, 2),
    rangeWidth: round(rangeWidth, 2),
  };
}

/**
 * Build confirmation measurements for the right-side readout.
 *
 * This gives the detail console a consistent set of bias-confirmation stats now
 * while leaving room for true market-feed replacements later.
 *
 * @param {Record<string, any>} row - Raw or enriched tracker row.
 * @returns {Record<string, any>} Market-context block.
 */
export function buildMarketContext(row) {
  const rvol = Number(relativeVolumeProxy(row));
  const trend = buildTrendDescriptor(row);
  const { support, resistance, rangeWidth } = buildSupportResistance(row);
  const price = Number(row.price) || 0;
  const explicitSupportDistance = Number(row.distanceToSupportPct ?? row.marketContext?.distanceToSupportPct);
  const explicitResistanceDistance = Number(row.distanceToResistancePct ?? row.marketContext?.distanceToResistancePct);
  const distanceToSupportPct = Number.isFinite(explicitSupportDistance)
    ? round(explicitSupportDistance, 2)
    : price > 0
      ? round(((price - Number(support)) / price) * 100, 2)
      : "0.00";
  const distanceToResistancePct = Number.isFinite(explicitResistanceDistance)
    ? round(explicitResistanceDistance, 2)
    : price > 0
      ? round(((Number(resistance) - price) / price) * 100, 2)
      : "0.00";
  const triggerBias = row.signalTrigger ? "Confirmed" : "Waiting";
  const alignmentScore =
    clamp(
      (rvol - 1) * 18 +
      clamp(row.momentumScore ?? 0, 0, 2.5) * 22 +
      clamp(row.readyScore ?? 0, 0, 2.5) * 14 +
      (row.signalTrigger ? 14 : 0),
      0,
      100,
    );
  const alignmentLabel = alignmentScore >= 72 ? "Aligned" : alignmentScore >= 48 ? "Developing" : "Fragile";

  return {
    rvol: round(rvol, 2),
    trend,
    triggerBias,
    atrExpansion: round(row.atrZScore ?? 0, 2),
    ivImpulse: round(row.ivRankChange ?? 0, 3),
    support,
    resistance,
    rangeWidth,
    distanceToSupportPct,
    distanceToResistancePct,
    alignmentScore: round(alignmentScore, 1),
    alignmentLabel,
  };
}

/**
 * Assign a temperature creature to a row.
 *
 * @param {Record<string, any>} row - Enriched row.
 * @returns {{key:string,name:string,miniFace:string,label:string,role:string,hint:string}} Creature descriptor.
 */
export function describeTemperature(row) {
  if (
    row.readiness >= 78 ||
    (row.signalTrigger && row.momentumScore >= 1.65) ||
    (row.status === "Ready" && row.setupRec !== "Avoid")
  ) {
    return creatureGuide.hot;
  }

  if (
    row.setupRec === "Avoid" ||
    row.readiness <= 42 ||
    (!row.signalTrigger && row.confidence <= 1)
  ) {
    return creatureGuide.cold;
  }

  return creatureGuide.wild;
}

function enrichRowCacheKey(row) {
  return [
    row.ticker,
    row.atrPercent,
    row.ivRank,
    row.nextEarnings,
    row.price,
    row.eps,
    row.pe,
    row.daysUntilEarnings,
    row.setupRec,
    row.urgency,
    row.signalTrigger,
    row.confidence,
    row.ivRankChange,
    row.atrZScore,
    row.atr20Day,
    row.rec1,
    row.rec2,
    row.valueScore,
    row.momentumScore,
    row.squeezeScore,
    row.readyScore,
    row.priority,
    row.rvol,
    row.trend,
    row.support,
    row.resistance,
    row.distanceToSupportPct,
    row.distanceToResistancePct,
    row.marketContext?.rvol,
    row.marketContext?.trend?.label || row.marketContext?.trend,
  ].join("|");
}

/**
 * Enrich a raw tracker row into the full dashboard model.
 *
 * This function is memoized because it is used heavily during imports, rendering,
 * filtering, and snapshot rebuilds. We cache by stable row signature so repeated
 * enrichment passes on identical source data do not keep recomputing the same
 * readiness and long-term stack.
 *
 * @param {Record<string, any>} row - Raw tracker row.
 * @returns {Record<string, any>} Enriched row for the desk.
 */
export function enrichRow(row) {
  const cacheKey = enrichRowCacheKey(row);
  const cached = enrichRowCache.get(cacheKey);
  if (cached) {
    return cached;
  }

  // Earnings timing gets the largest event weight inside the hot zone, but we
  // still give mid-window names enough score so they can survive on quality.
  const timingScore =
    row.daysUntilEarnings <= 7
      ? 16
      : row.daysUntilEarnings <= 21
        ? 20
        : row.daysUntilEarnings <= 35
          ? 17
          : 9;
  const triggerScore = row.signalTrigger ? 14 : 0;
  const confidenceScore = (row.confidence / 3) * 24;

  // IV rank change is scaled aggressively because a five-day IV expansion is one
  // of the clearest signs that the market is starting to care about the event.
  const ivMomentumScore = clamp(row.ivRankChange * 65, -8, 10);

  // ATR% and IV rank both represent tradable energy. We blend them so the desk
  // rewards setups with enough movement potential but avoids infinite volatility.
  const volatilityScore = clamp((row.ivRank / 50) * 12 + (row.atrPercent / 10) * 10, 0, 20);

  // The score blend lets your manually maintained sheet signals matter, but only
  // as one layer of the readiness stack rather than the whole throne.
  const scoreBlend =
    scoreToPercent(row.readyScore) * 0.28 +
    scoreToPercent(row.squeezeScore) * 0.18 +
    scoreToPercent(row.momentumScore) * 0.18 +
    scoreToPercent(row.valueScore) * 0.12;

  const readiness = clamp(
    timingScore +
      triggerScore +
      confidenceScore +
      ivMomentumScore +
      volatilityScore +
      setupWeight(row.setupRec) +
      urgencyWeight(row.urgency) +
      scoreBlend * 0.32,
    8,
    99,
  );

  const priorityValue = Number.isFinite(row.priority)
    ? row.priority
    : row.valueScore + row.momentumScore + row.squeezeScore + row.readyScore;
  const priority = round(priorityValue, 2);
  const [scoreLeader, scoreLeaderValue] = dominantScore(row);
  const actionBias = buildActionBias(row, priority);
  const readinessValue = Math.round(readiness);

  // Long-term score intentionally rewards value and compression while subtracting
  // points from already-hot momentum so discount buys stay disciplined.
  const longTermScoreValue = clamp(
    row.valueScore * 1.9 +
      row.squeezeScore * 1.1 +
      clamp(1.6 - row.momentumScore, 0, 1.6) +
      clamp((78 - readinessValue) / 30, 0, 1.2) +
      (row.daysUntilEarnings >= 10 ? 0.45 : row.daysUntilEarnings >= 5 ? 0.1 : -0.25) +
      (row.eps > 0 ? 0.35 : -0.2) +
      valuationBonus(row.pe) +
      (row.signalTrigger ? -0.18 : 0.15) +
      (row.setupRec === "Avoid" ? -0.35 : 0),
    0,
    9.99,
  );

  const longTermScore = round(longTermScoreValue, 2);
  const accumulationBias = buildAccumulationBias(longTermScoreValue);
  const discountReasons = buildAccumulationReasons({
    ...row,
    readiness: readinessValue,
  });
  const marketContext = buildMarketContext({
    ...row,
    ...(row.marketContext || {}),
    readiness: readinessValue,
  });

  const enriched = {
    ...row,
    priority,
    scoreLeader,
    scoreLeaderValue: round(scoreLeaderValue, 2),
    actionBias,
    longTermScore,
    accumulationBias,
    discountReasons,
    marketContext,
    readiness: readinessValue,
    status: readinessLabel(readiness),
  };

  enrichRowCache.set(cacheKey, enriched);
  return enriched;
}

/**
 * Parse CSV text into a 2D cell grid.
 *
 * @param {string} text - Raw CSV text.
 * @returns {string[][]} Parsed cells by row.
 */
export function parseCSV(text) {
  const rows = [];
  let current = "";
  let row = [];
  let insideQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const nextChar = text[index + 1];

    if (char === '"' && insideQuotes && nextChar === '"') {
      current += '"';
      index += 1;
      continue;
    }

    if (char === '"') {
      insideQuotes = !insideQuotes;
      continue;
    }

    if (char === "," && !insideQuotes) {
      row.push(current);
      current = "";
      continue;
    }

    if ((char === "\n" || char === "\r") && !insideQuotes) {
      if (char === "\r" && nextChar === "\n") {
        index += 1;
      }
      if (current || row.length) {
        row.push(current);
        rows.push(row);
      }
      row = [];
      current = "";
      continue;
    }

    current += char;
  }

  if (current || row.length) {
    row.push(current);
    rows.push(row);
  }

  return rows;
}

/**
 * Convert a tracker cell into a numeric value or null.
 *
 * @param {string|number|null|undefined} value - Raw cell value.
 * @returns {number|null} Parsed numeric value or null.
 */
export function numberOrNull(value) {
  const cleaned = String(value ?? "")
    .replace(/\$/g, "")
    .replace(/,/g, "")
    .trim();
  if (!cleaned || cleaned.toUpperCase() === "N/A" || cleaned === "#N/A") {
    return null;
  }
  const parsed = Number.parseFloat(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Normalize raw sheet/CSV rows into enriched dashboard rows.
 *
 * @param {string[][]} rawRows - Raw header + body rows.
 * @returns {Record<string, any>[]} Enriched tracker rows.
 */
export function normalizeCSVRows(rawRows) {
  if (rawRows.length < 2) {
    return [];
  }

  const headers = rawRows[0].map((header) => header.trim());
  const indexMap = Object.fromEntries(headers.map((header, index) => [header, index]));

  return rawRows.slice(1).map((cells) => {
    const read = (header) => cells[indexMap[header]] ?? "";
    const triggerValue = String(read("Signal Trigger")).trim();
    const nextEarningsRaw = read("Next Earnings").trim();
    const parsedDate = nextEarningsRaw ? new Date(nextEarningsRaw) : null;
    const normalizedDate = parsedDate && !Number.isNaN(parsedDate.getTime())
      ? parsedDate.toISOString().slice(0, 10)
      : "2026-05-01";

    return enrichRow({
      ticker: read("Ticker").trim().toUpperCase(),
      atrPercent: numberOrNull(read("ATR%")) ?? 0,
      ivRank: numberOrNull(read("IV Rank")) ?? 0,
      nextEarnings: normalizedDate,
      price: numberOrNull(read("Price")) ?? 0,
      eps: numberOrNull(read("EPS")) ?? 0,
      pe: numberOrNull(read("PE")),
      daysUntilEarnings: numberOrNull(read("Days until earnings")) ?? 0,
      setupRec: read("Setup Rec").trim() || "Watchlist",
      urgency: read('"Urgency"').trim() || "Watchlist",
      signalTrigger: triggerValue === "1" || triggerValue.toLowerCase().includes("true") || triggerValue.includes("✅"),
      confidence: numberOrNull(read("Confidence (3 MAX)")) ?? 0,
      ivRankChange: numberOrNull(read("IV Rank Change (5-day delta)")) ?? 0,
      atrZScore: numberOrNull(read("ATR% Z-Score")) ?? 0,
      atr20Day: numberOrNull(read("20 Day ATR")),
      rec1: read("REC 1-13").trim() || "N/A",
      rec2: read("Rec2").trim() || "N/A",
      valueScore: numberOrNull(read("Value Score")) ?? 0,
      momentumScore: numberOrNull(read("Momentum Score")) ?? 0,
      squeezeScore: numberOrNull(read("Squeeze Score")) ?? 0,
      readyScore: numberOrNull(read("Ready Score")) ?? 0,
      priority: numberOrNull(read("Priority")),
      rvol: numberOrNull(read("$RVOL")),
      trend: read("Trend").trim(),
      support: numberOrNull(read("Support")),
      resistance: numberOrNull(read("Resistance")),
      distanceToSupportPct: numberOrNull(read("% To Support")),
      distanceToResistancePct: numberOrNull(read("% To Resistance")),
    });
  }).filter((row) => row.ticker);
}
