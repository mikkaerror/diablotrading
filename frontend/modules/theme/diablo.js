/**
 * frontend/modules/theme/diablo.js
 *
 * Purpose:
 * This module is the infernal art direction layer for diablotrading. It turns
 * enriched market rows into Diablo-flavored heat chips, boss bars, town voices,
 * district lore, and mascot narration without leaking UI globals into the rest
 * of the app. The dashboard render shells can stay thin while this module owns
 * the demonic personality of the desk.
 */

export const ENABLE_DIABLO_FX = true;

import { describeTemperature } from "../dataProcessor.js";
import { clamp, formatBackendDate, round } from "../utils.js";

const TEMPERATURE_STYLE_ID = "diablo-temperature-fx-style";
const HAZE_CLASS = "diablo-heat-haze";
const TEMPERATURE_HAZE_THRESHOLD = 80;
const MARKET_DRAG_MIME = "application/x-inferno-market-row";
const INVENTORY_DRAG_MIME = "application/x-inferno-inventory-item";

let hottestHeatSeenThisFrame = 0;
let heatHazeFlushHandle = null;
let voiceLineMachine = null;

const ACTOR_TONE_LABELS = Object.freeze({
  hot: "Armed",
  wild: "Watching",
  cold: "Quiet",
});

const DIALOGUE_TONE_LABELS = Object.freeze({
  hot: "Burning",
  wild: "Restless",
  cold: "Quiet",
});

const LOOT_TONE_LABELS = Object.freeze({
  hot: "Lit",
  wild: "Live",
  cold: "Dormant",
});

/**
 * Runtime voice settings for the infernal narrator.
 *
 * These values stay simple on purpose so the effect can be tuned without
 * changing the state machine itself.
 */
export const VOICE_LINE_CONFIG = Object.freeze({
  enabled: ENABLE_DIABLO_FX,
  volume: 0.76,
  rate: 0.9,
  pitch: 0.72,
  globalCooldownMs: 1600,
  eventCooldownMs: Object.freeze({
    snapshot: 6000,
    approval: 2200,
    drop: 1400,
    heat: 5200,
    campaign: 9000,
    town: 9000,
  }),
});

const VOICE_LINE_POOLS = Object.freeze({
  snapshot: Object.freeze([
    "The trade is sealed in blood.",
    "Another chronicle is branded into the archive.",
    "The ledger drinks fresh ash and remembers.",
  ]),
  approval: Object.freeze({
    approved: Object.freeze([
      "{ticker} is worthy. Let the legion mark it.",
      "A worthy soul joins the warband: {ticker}.",
      "The gate opens for {ticker}. Spend the risk with intent.",
    ]),
    rejected: Object.freeze([
      "{ticker} is cast back into the pit.",
      "Bury {ticker}. The market has not earned our blood.",
      "{ticker} is denied. Let weaker souls rot outside the gate.",
    ]),
    pending: Object.freeze([
      "{ticker} returns to judgment.",
      "The writ for {ticker} is reset. The gatekeeper waits.",
      "{ticker} stands in ash and silence until conviction returns.",
    ]),
  }),
  drop: Object.freeze({
    market: Object.freeze([
      "{ticker} falls into the soul-bound vault.",
      "A fresh relic takes form: {ticker}.",
      "{ticker} is bound in ember and iron.",
    ]),
    inventory: Object.freeze([
      "The relics shift within the vault.",
      "The soul-bound grid accepts a new arrangement.",
      "The vault groans as the loot is moved.",
    ]),
  }),
  heat: Object.freeze([
    "The fires of Hell stir around {ticker}.",
    "{ticker} is running hot. The chamber can feel it.",
    "The air bends around {ticker}. Something violent is waking.",
  ]),
  campaign: Object.freeze({
    "Raid Night": Object.freeze([
      "Raid night rises. Sharpen the steel and quiet the doubt.",
      "The town smells blood. The raid board is awake.",
      "The war drums begin again. Conviction must now survive contact.",
    ]),
    "Night Market": Object.freeze([
      "The merchants whisper tonight. Discounts deserve patient gold.",
      "The market lanterns are lit. Buy the bargain, not the chase.",
      "Nyra smiles. Real value is finally stalking the stalls.",
    ]),
    "Ashen Curfew": Object.freeze([
      "Hold the line. No false raids tonight.",
      "Curfew stands. Patience is the only clean weapon left.",
      "Let the town stay quiet. The weak setups deserve no ceremony.",
    ]),
  }),
  town: Object.freeze([
    "The town boards shift. Every district has a new rumor.",
    "The village murmurs. Something in the campaign has changed.",
    "The streets trade whispers before the next bell tolls.",
  ]),
});

/**
 * Lightweight state machine for infernal speech effects.
 *
 * The machine rate-limits itself aggressively so the dashboard feels alive
 * instead of noisy. When the browser speech APIs are missing or blocked, it
 * safely falls back to console logging.
 */
export class VoiceLineStateMachine {
  /**
   * @param {typeof VOICE_LINE_CONFIG} config - Voice playback and cooldown settings.
   */
  constructor(config) {
    this.config = config;
    this.lastGlobalAt = 0;
    this.lastEventAt = new Map();
    this.lastSignatureByEvent = new Map();
    this.lastLineByEvent = new Map();
    this.lastHeatByTicker = new Map();
    this.runtimeInstalled = false;
  }

  /**
   * Seed an event signature without speaking.
   *
   * This prevents stale existing UI state from being treated like a brand-new
   * event the first time the dashboard paints.
   *
   * @param {string} eventType - Event family.
   * @param {string} signature - Signature to remember.
   * @returns {boolean} True when the signature was primed instead of spoken.
   */
  primeSignature(eventType, signature) {
    if (!signature || this.lastSignatureByEvent.has(eventType)) {
      return false;
    }

    this.lastSignatureByEvent.set(eventType, signature);
    this.lastEventAt.set(eventType, Date.now());
    return true;
  }

  /**
   * Decide whether a new event is allowed to speak right now.
   *
   * @param {string} eventType - Logical event family.
   * @param {string} signature - Deduplication signature for the event.
   * @returns {boolean} Whether the event should emit a voice line.
   */
  canSpeak(eventType, signature) {
    const now = Date.now();
    const eventCooldown = this.config.eventCooldownMs[eventType] ?? this.config.globalCooldownMs;
    const lastEventAt = this.lastEventAt.get(eventType) || 0;
    const lastSignature = this.lastSignatureByEvent.get(eventType);

    if (signature && lastSignature === signature && now - lastEventAt < eventCooldown) {
      return false;
    }

    if (now - this.lastGlobalAt < this.config.globalCooldownMs) {
      return false;
    }

    if (now - lastEventAt < eventCooldown) {
      return false;
    }

    return true;
  }

  /**
   * Choose a randomized line while trying not to repeat the last one for the
   * same event family back-to-back.
   *
   * @param {string} eventType - Logical event family.
   * @param {string[]} lines - Candidate line pool.
   * @returns {string} Chosen line.
   */
  chooseLine(eventType, lines) {
    if (!lines.length) {
      return "";
    }

    const previous = this.lastLineByEvent.get(eventType);
    const pool = lines.length > 1 ? lines.filter((line) => line !== previous) : lines;
    const line = pool[Math.floor(Math.random() * pool.length)] || lines[0];
    this.lastLineByEvent.set(eventType, line);
    return line;
  }

  /**
   * Speak or log a line for the requested event.
   *
   * @param {string} eventType - Event family.
   * @param {string[]} lines - Candidate phrases.
   * @param {string} signature - Dedupe signature.
   * @param {Record<string, string|number>} [tokens={}] - Placeholder values for templating.
   * @returns {void}
   */
  speak(eventType, lines, signature, tokens = {}) {
    if (!this.config.enabled || !lines?.length || !this.canSpeak(eventType, signature)) {
      return;
    }

    const template = this.chooseLine(eventType, lines);
    const line = template.replace(/\{(\w+)\}/g, (_, token) => String(tokens[token] ?? ""));
    const now = Date.now();
    this.lastGlobalAt = now;
    this.lastEventAt.set(eventType, now);
    this.lastSignatureByEvent.set(eventType, signature);

    if (typeof window !== "undefined" && "speechSynthesis" in window && typeof SpeechSynthesisUtterance !== "undefined") {
      const utterance = new SpeechSynthesisUtterance(line);
      utterance.volume = this.config.volume;
      utterance.rate = this.config.rate;
      utterance.pitch = this.config.pitch;
      utterance.lang = "en-US";
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
      return;
    }

    // Console fallback keeps the feature safe in locked-down browsers and local
    // verification contexts where speech synthesis is unavailable.
    console.log(`[Inferno Voice:${eventType}] ${line}`);
  }
}

/**
 * Resolve the singleton infernal voice machine.
 *
 * @returns {VoiceLineStateMachine|null} Active machine or null when FX are disabled.
 */
function getVoiceLineMachine() {
  if (!ENABLE_DIABLO_FX || typeof window === "undefined") {
    return null;
  }

  if (!voiceLineMachine) {
    voiceLineMachine = new VoiceLineStateMachine(VOICE_LINE_CONFIG);
  }

  return voiceLineMachine;
}

/**
 * Install global DOM listeners that map live UI interactions to infernal
 * voice-line events.
 */
function ensureVoiceLineRuntime() {
  const machine = getVoiceLineMachine();
  if (!machine || typeof document === "undefined" || machine.runtimeInstalled) {
    return;
  }

  machine.runtimeInstalled = true;

  document.addEventListener(
    "click",
    (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const approvalButton = target?.closest?.("[data-approval-ticker]");
      if (!approvalButton) {
        return;
      }

      machine.speak(
        "approval",
        VOICE_LINE_POOLS.approval[approvalButton.dataset.approvalStatus] || VOICE_LINE_POOLS.approval.pending,
        `${approvalButton.dataset.approvalTicker}:${approvalButton.dataset.approvalStatus}`,
        { ticker: approvalButton.dataset.approvalTicker || "This soul" },
      );
    },
    true,
  );

  document.addEventListener(
    "drop",
    (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target?.closest?.("[data-slot]") || !event.dataTransfer) {
        return;
      }

      const marketPayload = event.dataTransfer.getData(MARKET_DRAG_MIME) || event.dataTransfer.getData("text/plain");
      if (marketPayload) {
        try {
          const payload = JSON.parse(marketPayload);
          machine.speak("drop", VOICE_LINE_POOLS.drop.market, `market:${payload.ticker}`, {
            ticker: payload.ticker || "Unknown relic",
          });
          return;
        } catch {
          // Ignore malformed payloads and fall through to inventory moves.
        }
      }

      const inventoryPayload = event.dataTransfer.getData(INVENTORY_DRAG_MIME);
      if (!inventoryPayload) {
        return;
      }

      try {
        const payload = JSON.parse(inventoryPayload);
        machine.speak("drop", VOICE_LINE_POOLS.drop.inventory, `inventory:${payload.id || payload.slot || "move"}`);
      } catch {
        // Ignore malformed vault payloads to keep the runtime safe.
      }
    },
    true,
  );
}

/**
 * Announce a new sealed snapshot when the machine archive timestamp changes.
 *
 * @param {string|null|undefined} timestamp - Fresh snapshot timestamp.
 */
function announceSnapshotSeal(timestamp) {
  const machine = getVoiceLineMachine();
  if (!machine || !timestamp) {
    return;
  }

  if (machine.primeSignature("snapshot", String(timestamp))) {
    return;
  }

  machine.speak("snapshot", VOICE_LINE_POOLS.snapshot, String(timestamp));
}

/**
 * Announce a meaningful temperature swing for a live name.
 *
 * @param {Record<string, any>} row - Enriched trading row.
 * @param {number} heat - Current heat score.
 * @param {ReturnType<typeof describeTemperature>} creature - Current temperature descriptor.
 */
function announceTemperatureSwing(row, heat, creature) {
  const machine = getVoiceLineMachine();
  if (!machine || !row?.ticker) {
    return;
  }

  const previous = machine.lastHeatByTicker.get(row.ticker);
  machine.lastHeatByTicker.set(row.ticker, {
    heat,
    label: creature.label,
  });

  if (!previous) {
    return;
  }

  const delta = Math.abs(heat - previous.heat);
  const crossedBand = previous.label !== creature.label;
  if (delta < 18 && !crossedBand) {
    return;
  }

  if (Math.max(previous.heat, heat) < 70) {
    return;
  }

  machine.speak("heat", VOICE_LINE_POOLS.heat, `${row.ticker}:${creature.label}:${Math.round(heat / 10)}`, {
    ticker: row.ticker,
  });
}

/**
 * Announce a campaign-board state shift when the village mood changes.
 *
 * @param {string} moodTitle - Current town mood title.
 * @param {number} readyCount - Broker-ready raid count.
 * @param {string} topTicker - Lead ticker for the current mood.
 */
function announceCampaignUpdate(moodTitle, readyCount, topTicker) {
  const machine = getVoiceLineMachine();
  if (!machine || !moodTitle) {
    return;
  }

  const signature = `${moodTitle}:${readyCount}:${topTicker || "none"}`;
  if (machine.primeSignature("campaign", signature)) {
    return;
  }

  const lines = VOICE_LINE_POOLS.campaign[moodTitle] || VOICE_LINE_POOLS.campaign["Ashen Curfew"];
  machine.speak("campaign", lines, signature, {
    ticker: topTicker || "the town",
  });
}

/**
 * Announce town-board shifts when the live speaker roster changes.
 *
 * @param {string} signature - Dedupe signature built from current town state.
 */
function announceTownBoardUpdate(signature) {
  const machine = getVoiceLineMachine();
  if (!machine || !signature) {
    return;
  }

  if (machine.primeSignature("town", signature)) {
    return;
  }

  machine.speak("town", VOICE_LINE_POOLS.town, signature);
}

/**
 * Install the reusable temperature FX stylesheet exactly once.
 *
 * The style sheet stays local to the theme module so this upgrade remains
 * reversible and does not depend on global stylesheet edits.
 */
function ensureTemperatureFxStyles() {
  if (!ENABLE_DIABLO_FX || typeof document === "undefined" || document.getElementById(TEMPERATURE_STYLE_ID)) {
    return;
  }

  const style = document.createElement("style");
  style.id = TEMPERATURE_STYLE_ID;
  style.textContent = `
    .diablo-temp-chip {
      position: relative;
      overflow: hidden;
      transform: scale(var(--diablo-temp-scale, 1));
      filter: saturate(calc(1 + var(--diablo-temp-saturation, 0.15))) brightness(calc(1 + var(--diablo-temp-brightness, 0.04)));
      box-shadow:
        inset 0 0 0 1px hsla(var(--diablo-temp-hue, 16), 90%, 64%, 0.22),
        0 0 calc(6px + var(--diablo-temp-glow, 10px)) hsla(var(--diablo-temp-hue, 16), 96%, 60%, 0.18);
      animation: diablo-ember-pulse calc(3.1s - var(--diablo-temp-speed, 0s)) ease-in-out infinite;
      transform-origin: center;
      will-change: transform, filter, box-shadow;
    }
    .diablo-temp-chip::after {
      content: "";
      position: absolute;
      inset: -15%;
      background:
        radial-gradient(circle at 25% 35%, hsla(var(--diablo-temp-hue, 16), 98%, 72%, 0.16), transparent 34%),
        radial-gradient(circle at 72% 68%, hsla(var(--diablo-temp-hue, 16), 98%, 64%, 0.1), transparent 42%);
      pointer-events: none;
      mix-blend-mode: screen;
      opacity: 0.75;
    }
    .diablo-temp-bar {
      position: relative;
      background:
        linear-gradient(
          90deg,
          hsla(calc(var(--diablo-temp-hue, 16) + 26), 88%, 70%, 0.92),
          hsla(var(--diablo-temp-hue, 16), 94%, 56%, 0.98) 62%,
          hsla(calc(var(--diablo-temp-hue, 16) - 10), 96%, 44%, 0.98)
        );
      filter: saturate(calc(1 + var(--diablo-temp-saturation, 0.2))) brightness(calc(1 + var(--diablo-temp-brightness, 0.05)));
      box-shadow:
        0 0 calc(8px + var(--diablo-temp-glow, 10px)) hsla(var(--diablo-temp-hue, 16), 95%, 58%, 0.22),
        inset 0 0 14px rgba(255, 255, 255, 0.08);
      animation: diablo-ember-pulse calc(2.6s - var(--diablo-temp-speed, 0s)) ease-in-out infinite;
      transform-origin: left center;
      will-change: transform, filter, box-shadow;
    }
    .diablo-temp-bar::after {
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, transparent 0%, rgba(255, 255, 255, 0.18) 42%, transparent 76%);
      opacity: 0.55;
      mix-blend-mode: screen;
      animation: diablo-ember-sheen calc(3.8s - var(--diablo-temp-speed, 0s)) linear infinite;
    }
    body.${HAZE_CLASS}::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 2;
      background:
        radial-gradient(circle at 15% 20%, rgba(255, 106, 54, calc(0.03 + var(--diablo-haze-opacity, 0.05))) 0%, transparent 28%),
        radial-gradient(circle at 82% 28%, rgba(255, 82, 38, calc(0.02 + var(--diablo-haze-opacity, 0.04))) 0%, transparent 32%),
        radial-gradient(circle at 48% 78%, rgba(255, 148, 84, calc(0.02 + var(--diablo-haze-opacity, 0.03))) 0%, transparent 34%);
      mix-blend-mode: screen;
      filter: blur(calc(10px + var(--diablo-haze-blur, 10px))) saturate(1.04);
      opacity: calc(0.16 + var(--diablo-haze-opacity, 0.08));
      animation: diablo-heat-haze 6s ease-in-out infinite alternate;
    }
    @keyframes diablo-ember-pulse {
      0%, 100% {
        transform: scale(var(--diablo-temp-scale, 1));
        filter: saturate(calc(1 + var(--diablo-temp-saturation, 0.15))) brightness(calc(1 + var(--diablo-temp-brightness, 0.04)));
      }
      50% {
        transform: scale(calc(var(--diablo-temp-scale, 1) + 0.016));
        filter: saturate(calc(1.08 + var(--diablo-temp-saturation, 0.15))) brightness(calc(1.08 + var(--diablo-temp-brightness, 0.04)));
      }
    }
    @keyframes diablo-ember-sheen {
      0% { transform: translateX(-130%); }
      100% { transform: translateX(150%); }
    }
    @keyframes diablo-heat-haze {
      0% { transform: translate3d(0, 0, 0) scale(1); }
      100% { transform: translate3d(0, -0.6%, 0) scale(1.018); }
    }
  `;
  document.head.append(style);
}

/**
 * Convert a row's existing conviction metrics into a 0-100 infernal heat score.
 *
 * We intentionally reuse live scoring ingredients that already matter to the
 * desk instead of inventing a disconnected visual number. Readiness does most
 * of the work, while momentum and squeeze intensify the effect for names that
 * are actually moving.
 *
 * @param {Record<string, any>} row - Enriched trading row.
 * @returns {number} Heat intensity from 0 to 100.
 */
function getHeatIntensity(row) {
  const readiness = Number(row?.readiness || 0);
  const momentum = Number(row?.momentumScore || 0);
  const squeeze = Number(row?.squeezeScore || 0);
  const triggerBonus = row?.signalTrigger ? 8 : 0;
  return clamp(readiness * 0.68 + momentum * 14 + squeeze * 10 + triggerBonus, 0, 100);
}

/**
 * Convert a heat score into CSS custom properties for ember animation.
 *
 * The hue travels from icy blue to blood red while glow, brightness, and speed
 * intensify with heat.
 *
 * @param {number} heat - Heat intensity from 0 to 100.
 * @returns {{hue:number,glow:number,brightness:number,saturation:number,scale:number,speed:number}} CSS-ready FX values.
 */
function buildTemperatureFx(heat) {
  const normalized = clamp(heat, 0, 100) / 100;
  return {
    hue: round(205 - normalized * 203, 2),
    glow: round(8 + normalized * 18, 2),
    brightness: round(0.03 + normalized * 0.24, 3),
    saturation: round(0.08 + normalized * 0.46, 3),
    scale: round(1 + normalized * 0.025, 3),
    speed: round(normalized * 1.2, 3),
  };
}

/**
 * Serialize the FX object into inline CSS custom properties.
 *
 * @param {ReturnType<typeof buildTemperatureFx>} fx - FX values.
 * @returns {string} Inline style string.
 */
function buildTemperatureFxStyle(fx) {
  return [
    `--diablo-temp-hue:${fx.hue}`,
    `--diablo-temp-glow:${fx.glow}px`,
    `--diablo-temp-brightness:${fx.brightness}`,
    `--diablo-temp-saturation:${fx.saturation}`,
    `--diablo-temp-scale:${fx.scale}`,
    `--diablo-temp-speed:${fx.speed}s`,
  ].join(";");
}

/**
 * Record the hottest name seen during the current render frame and update the
 * optional global heat haze overlay.
 *
 * @param {number} heat - Row heat score.
 */
function registerHeatHaze(heat) {
  if (!ENABLE_DIABLO_FX || typeof document === "undefined") {
    return;
  }

  ensureTemperatureFxStyles();
  hottestHeatSeenThisFrame = Math.max(hottestHeatSeenThisFrame, heat);

  if (heatHazeFlushHandle !== null) {
    return;
  }

  heatHazeFlushHandle = window.requestAnimationFrame(() => {
    const body = document.body;
    if (!body) {
      hottestHeatSeenThisFrame = 0;
      heatHazeFlushHandle = null;
      return;
    }

    if (hottestHeatSeenThisFrame > TEMPERATURE_HAZE_THRESHOLD) {
      const overshoot = (hottestHeatSeenThisFrame - TEMPERATURE_HAZE_THRESHOLD) / (100 - TEMPERATURE_HAZE_THRESHOLD);
      body.classList.add(HAZE_CLASS);
      body.style.setProperty("--diablo-haze-opacity", round(0.04 + overshoot * 0.18, 3));
      body.style.setProperty("--diablo-haze-blur", `${round(10 + overshoot * 10, 2)}px`);
    } else {
      body.classList.remove(HAZE_CLASS);
      body.style.removeProperty("--diablo-haze-opacity");
      body.style.removeProperty("--diablo-haze-blur");
    }

    hottestHeatSeenThisFrame = 0;
    heatHazeFlushHandle = null;
  });
}

/**
 * Build a compact district glyph from a district or NPC name.
 *
 * @param {string} name - Human-readable district or actor name.
 * @returns {string} Two-letter glyph used by the themed UI.
 */
export function buildDistrictGlyph(name) {
  return String(name)
    .split(" ")
    .map((part) => part[0] || "")
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

/**
 * Convert a tone key into the actor-state label used on the campaign board.
 *
 * @param {"hot"|"wild"|"cold"|string} tone - Theme tone key.
 * @returns {string} Short Diablo-flavored state label.
 */
export function toneToActorStateLabel(tone) {
  return ACTOR_TONE_LABELS[tone] || ACTOR_TONE_LABELS.cold;
}

/**
 * Convert a tone key into the town-dialogue chip label.
 *
 * @param {"hot"|"wild"|"cold"|string} tone - Theme tone key.
 * @returns {string} Dialogue-state label.
 */
export function toneToDialogueStateLabel(tone) {
  return DIALOGUE_TONE_LABELS[tone] || DIALOGUE_TONE_LABELS.cold;
}

/**
 * Convert a tone key into the loot-state label.
 *
 * @param {"hot"|"wild"|"cold"|string} tone - Theme tone key.
 * @returns {string} Loot-state label.
 */
export function toneToLootStateLabel(tone) {
  return LOOT_TONE_LABELS[tone] || LOOT_TONE_LABELS.cold;
}

/**
 * Render the compact temperature chip used across roster, detail, and shortlist views.
 *
 * @param {Record<string, any>} row - Enriched trading row.
 * @returns {string} HTML snippet for the temperature chip.
 */
export function renderTempChip(row) {
  const creature = describeTemperature(row);
  if (!ENABLE_DIABLO_FX) {
    return `
      <span class="temp-chip ${creature.key}">
        <span class="mini-face">${creature.miniFace}</span>
        <span>${creature.name}</span>
      </span>
    `;
  }

  ensureVoiceLineRuntime();
  const heat = getHeatIntensity(row);
  const fx = buildTemperatureFx(heat);
  registerHeatHaze(heat);
  announceTemperatureSwing(row, heat, creature);
  return `
    <span class="temp-chip ${creature.key} diablo-temp-chip" style="${buildTemperatureFxStyle(fx)}" data-heat="${Math.round(heat)}">
      <span class="mini-face">${creature.miniFace}</span>
      <span>${creature.name}</span>
    </span>
  `;
}

/**
 * Render the Diablo-flavored boss bar used for readiness / ascension.
 *
 * @param {Record<string, any>} row - Enriched trading row.
 * @param {"full"|"mini"} [mode="full"] - Layout variant.
 * @returns {string} HTML snippet for the readiness bar.
 */
export function renderBossBar(row, mode = "full") {
  const creature = describeTemperature(row);
  // Readiness can drift outside the expected band in malformed input, so we clamp
  // the width defensively to keep the fill from breaking layout.
  const width = clamp(row.readiness, 0, 100);
  if (!ENABLE_DIABLO_FX) {
    if (mode === "mini") {
      return `
        <div class="mini-bar">
          <div class="mini-track">
            <div class="mini-fill ${creature.key}" style="width: ${width}%"></div>
          </div>
        </div>
      `;
    }

    return `
      <div class="boss-bar">
        <div class="boss-label">
          <span>Ascension Meter</span>
          <span>${row.readiness}%</span>
        </div>
        <div class="boss-track">
          <div class="boss-fill ${creature.key}" style="width: ${width}%"></div>
        </div>
      </div>
    `;
  }

  ensureVoiceLineRuntime();
  const heat = getHeatIntensity(row);
  const fx = buildTemperatureFx(heat);
  registerHeatHaze(heat);
  announceTemperatureSwing(row, heat, creature);

  if (mode === "mini") {
    return `
      <div class="mini-bar">
        <div class="mini-track">
          <div class="mini-fill ${creature.key} diablo-temp-bar" style="width: ${width}%; ${buildTemperatureFxStyle(fx)}" data-heat="${Math.round(heat)}"></div>
        </div>
      </div>
    `;
  }

  return `
    <div class="boss-bar">
      <div class="boss-label">
        <span>Ascension Meter</span>
        <span>${row.readiness}%</span>
      </div>
      <div class="boss-track">
        <div class="boss-fill ${creature.key} diablo-temp-bar" style="width: ${width}%; ${buildTemperatureFxStyle(fx)}" data-heat="${Math.round(heat)}"></div>
      </div>
    </div>
  `;
}

/**
 * Build the town-actor cards that narrate the desk state at a glance.
 *
 * @param {Object} params - Theme inputs from the orchestration layer.
 * @param {Record<string, any>} [params.queue={}] - Execution queue payload.
 * @param {Record<string, any>|null} [params.opsStatus=null] - Ops status payload.
 * @param {Record<string, any>|null} [params.watchdogStatus=null] - Watchdog status payload.
 * @param {Record<string, any>|null} [params.topLongTerm=null] - Best long-term candidate.
 * @param {number|null} [params.pendingCount=null] - Pending approval count override.
 * @param {string|null} [params.lastSnapshotAt=null] - Last snapshot timestamp.
 * @returns {Array<Record<string, any>>} Actor cards for the campaign panel.
 */
export function buildTownActors({
  queue = {},
  opsStatus = null,
  watchdogStatus = null,
  topLongTerm = null,
  pendingCount = null,
  lastSnapshotAt = null,
} = {}) {
  ensureVoiceLineRuntime();
  const resolvedPendingCount = pendingCount ?? queue.pendingCount ?? 0;
  const freeRiskUnits = round((queue.dailyRiskBudget || 0) - (queue.stagedRiskUnits || 0), 2);
  const totalRiskUnits = round(queue.dailyRiskBudget || 0, 2);
  const chronicleAt = opsStatus?.generatedAt || lastSnapshotAt;
  announceSnapshotSeal(chronicleAt);

  return [
    {
      glyph: "GK",
      name: "Gatekeeper",
      status: resolvedPendingCount ? `${resolvedPendingCount} writs awaiting approval` : "No names crowding the gate",
      note: resolvedPendingCount
        ? "Approve only the names you would actually route in the real world."
        : "The gate is clear. No forced decisions are needed right now.",
      tone: resolvedPendingCount ? "wild" : "cold",
    },
    {
      glyph: "QM",
      name: "Quartermaster",
      status: `${freeRiskUnits} / ${totalRiskUnits} risk units free`,
      note:
        (queue.activeReadyCount || 0) > 0
          ? `${queue.activeReadyCount} raids are armed for broker review. The rest stay sheathed.`
          : "Nothing is over-armed right now. The treasury still has room, but the desk is behaving.",
      tone: (queue.activeReadyCount || 0) > 0 ? "hot" : "wild",
    },
    {
      glyph: "MT",
      name: "Merchant",
      status: topLongTerm ? `${topLongTerm.ticker} leads the discount lane` : "No quality bargains on the table",
      note: topLongTerm
        ? `${topLongTerm.discountReasons.join(", ")}. Buy the business, not the adrenaline.`
        : "The vault stays patient when names are expensive or overheated.",
      tone: topLongTerm ? topLongTerm.accumulationBias.tone : "cold",
    },
    {
      glyph: "AR",
      name: "Archivist",
      status: opsStatus?.ok && watchdogStatus?.ok ? "Briefs, logs, and patrols intact" : "Records need operator review",
      note: chronicleAt
        ? `Last machine heartbeat: ${formatBackendDate(chronicleAt)}.`
        : "No fresh records were found yet.",
      tone: opsStatus?.ok && watchdogStatus?.ok ? "hot" : "cold",
    },
  ];
}

/**
 * Build the village-wide mood state from the current campaign state.
 *
 * @param {Object} campaign - Campaign summary object.
 * @param {number} [campaign.readyCount=0] - Number of broker-ready raids.
 * @param {Record<string, any>|null} [campaign.topMerchant=null] - Best long-term candidate.
 * @returns {{title:string,note:string}} Town mood payload.
 */
export function buildTownMood({ readyCount = 0, topMerchant = null } = {}) {
  if (readyCount > 0) {
    announceCampaignUpdate("Raid Night", readyCount, "");
    return {
      title: "Raid Night",
      note: "The forge is lit, the gate is awake, and the town is arguing over which names deserve blood and risk.",
    };
  }

  if (topMerchant) {
    announceCampaignUpdate("Night Market", readyCount, topMerchant.ticker || "");
    return {
      title: "Night Market",
      note: `${topMerchant.ticker} has the merchants whispering. The village feels patient, watchful, and a little greedy in the best way.`,
    };
  }

  announceCampaignUpdate("Ashen Curfew", readyCount, "");
  return {
    title: "Ashen Curfew",
    note: "No one is rushing. The town is alive, but it is choosing patience over chaos tonight.",
  };
}

/**
 * Build the themed district metadata used by the town map and district focus panel.
 *
 * @param {Object} params - Theme inputs from the orchestration layer.
 * @param {Record<string, any>} params.campaign - Campaign summary object.
 * @param {Record<string, any>} [params.queue={}] - Execution queue payload.
 * @param {Record<string, any>|null} [params.merchant=null] - Best long-term candidate.
 * @param {Array<Record<string, any>>} [params.scouts=[]] - Scout candidates.
 * @param {Record<string, any>|null} [params.raidLead=null] - Top raid candidate.
 * @param {Record<string, any>|null} [params.opsStatus=null] - Ops status payload.
 * @param {Record<string, any>|null} [params.watchdogStatus=null] - Watchdog status payload.
 * @returns {Array<Record<string, any>>} District descriptors.
 */
export function buildTownDistricts({
  campaign,
  queue = {},
  merchant = null,
  scouts = [],
  raidLead = null,
  opsStatus = null,
  watchdogStatus = null,
} = {}) {
  return [
    {
      key: "gate",
      name: "Hellgate",
      face: "Raid Queue",
      tone: campaign.readyCount > 0 ? "hot" : campaign.pendingCount > 0 ? "wild" : "cold",
      status:
        campaign.readyCount > 0
          ? `${campaign.readyCount} raid${campaign.readyCount === 1 ? "" : "s"} armed`
          : campaign.pendingCount > 0
            ? `${campaign.pendingCount} writs awaiting judgment`
            : "Gate stands quiet",
      resident: "Gatekeeper Sereth",
      focusTicker: raidLead?.ticker || "",
      note: raidLead
        ? `${raidLead.ticker} is the champion closest to the wall. Approvals turn waiting names into marching orders here.`
        : "When conviction rises, this is where short-term raid quests gather before they earn a writ.",
      x: 66,
      y: 208,
    },
    {
      key: "hall",
      name: "War Hall",
      face: "Conviction Board",
      tone: campaign.openQuests >= 5 ? "hot" : campaign.openQuests >= 3 ? "wild" : "cold",
      status: `${campaign.openQuests} active quests`,
      resident: "The War Council",
      focusTicker: raidLead?.ticker || merchant?.ticker || "",
      note: "This is the strategy room. It decides whether the town is raiding, scouting, or hoarding patience.",
      x: 238,
      y: 108,
    },
    {
      key: "market",
      name: "Ash Market",
      face: "Long-Term Lane",
      tone: merchant ? merchant.accumulationBias.tone : "cold",
      status: merchant ? `${merchant.ticker} leads the bargain stalls` : "No real bargains today",
      resident: "Merchant Nyra",
      focusTicker: merchant?.ticker || "",
      note: merchant
        ? `${merchant.ticker} is today's best discount story. This stall is for conviction buys, not adrenaline buys.`
        : "The market waits for real discounts instead of inventing cheapness where none exists.",
      x: 438,
      y: 208,
    },
    {
      key: "forge",
      name: "Broker Forge",
      face: "Execution Desk",
      tone: (queue.activeReadyCount || 0) > 0 ? "hot" : (queue.pendingCount || 0) > 0 ? "wild" : "cold",
      status:
        (queue.activeReadyCount || 0) > 0
          ? `${queue.activeReadyCount} ticket${queue.activeReadyCount === 1 ? "" : "s"} can be reviewed`
          : `${queue.pendingCount || 0} still blocked by approval`,
      resident: "Quartermaster Varo",
      focusTicker: queue.readyTickers?.[0] || raidLead?.ticker || "",
      note:
        (queue.activeReadyCount || 0) > 0
          ? "This forge is hot. Ready names can be turned into broker-review tickets here."
          : "The forge stays cautious until a name clears approval, trigger, and risk budget.",
      x: 604,
      y: 122,
    },
    {
      key: "archive",
      name: "Bone Archive",
      face: "Ops Record",
      tone: opsStatus?.ok && watchdogStatus?.ok ? "hot" : "cold",
      status: opsStatus?.generatedAt ? `Last chronicle ${formatBackendDate(opsStatus.generatedAt)}` : "No chronicle yet",
      resident: "Archivist Malek",
      focusTicker: "",
      note:
        opsStatus?.ok && watchdogStatus?.ok
          ? "The records are clean and the machine chorus is behaving."
          : "This hall remembers every broken relay and missing dawn cycle.",
      x: 694,
      y: 278,
    },
    {
      key: "watchtower",
      name: "Watchtower",
      face: "Scouts and patrols",
      tone: scouts.length ? "wild" : "cold",
      status: scouts.length ? `${scouts[0].ticker} is under watch` : "No scouts are circling",
      resident: "Scout Ilya",
      focusTicker: scouts[0]?.ticker || "",
      note: scouts.length
        ? `${scouts[0].ticker} is the cleanest unfinished story in the hills.`
        : "The watchtower is quiet when nothing deserves partial attention.",
      x: 494,
      y: 62,
    },
  ];
}

/**
 * Build the voice-line roster for the town dialogue cards.
 *
 * @param {Object} params - Theme inputs from the orchestration layer.
 * @param {Record<string, any>} [params.queue={}] - Execution queue payload.
 * @param {Record<string, any>|null} [params.raidLead=null] - Top raid candidate.
 * @param {Record<string, any>|null} [params.merchant=null] - Top merchant candidate.
 * @param {Array<Record<string, any>>} [params.scouts=[]] - Scout candidate list.
 * @param {Array<Record<string, any>>} [params.approvalQueue=[]] - Approval queue entries.
 * @param {Record<string, any>|null} [params.opsStatus=null] - Ops status payload.
 * @param {Record<string, any>|null} [params.watchdogStatus=null] - Watchdog status payload.
 * @returns {Array<Record<string, any>>} Voice-line cards.
 */
export function buildTownDialogue({
  queue = {},
  raidLead = null,
  merchant = null,
  scouts = [],
  approvalQueue = [],
  opsStatus = null,
  watchdogStatus = null,
} = {}) {
  ensureVoiceLineRuntime();
  // Pending approvals are treated like a "voice trigger" because they change how
  // the gate speaks: one blocked raid should make the whole town sound tense.
  const pendingCount = approvalQueue.filter((item) => item.approvalStatus === "pending").length;
  announceTownBoardUpdate(
    [
      queue.activeReadyCount || 0,
      pendingCount,
      raidLead?.ticker || "",
      merchant?.ticker || "",
      scouts[0]?.ticker || "",
      opsStatus?.ok ? "ops-ready" : "ops-cold",
      watchdogStatus?.ok ? "watchdog-ready" : "watchdog-cold",
    ].join("|"),
  );

  return [
    {
      name: "Gatekeeper Sereth",
      districtKey: "gate",
      tone: pendingCount ? "wild" : "cold",
      ticker: raidLead?.ticker || "",
      line: pendingCount
        ? `${pendingCount} names still stand outside the gate. ${raidLead ? `${raidLead.ticker} is first in line.` : "No champion has stepped forward yet."}`
        : "The gate is clear. No approvals are rotting in the queue tonight.",
    },
    {
      name: "Quartermaster Varo",
      districtKey: "forge",
      tone: (queue.activeReadyCount || 0) > 0 ? "hot" : "wild",
      ticker: queue.readyTickers?.[0] || raidLead?.ticker || "",
      line:
        (queue.activeReadyCount || 0) > 0
          ? `${queue.readyTickers[0]} is armed for broker review. ${round(queue.stagedRiskUnits || 0, 2)} risk units are already spoken for.`
          : `${round((queue.dailyRiskBudget || 0) - (queue.stagedRiskUnits || 0), 2)} risk units remain. Spend them only on names you would defend in daylight.`,
    },
    {
      name: "Merchant Nyra",
      districtKey: "market",
      tone: merchant ? merchant.accumulationBias.tone : "cold",
      ticker: merchant?.ticker || "",
      line: merchant
        ? `${merchant.ticker} is the cleanest bargain in the market. ${merchant.discountReasons[0] || "The price has cooled without killing conviction."}`
        : "The stalls are full of overpriced junk. Keep your gold in your pocket.",
    },
    {
      name: "Archivist Malek",
      districtKey: "archive",
      tone: opsStatus?.ok && watchdogStatus?.ok ? "hot" : "cold",
      ticker: "",
      line: opsStatus?.generatedAt
        ? `The last chronicle was written ${formatBackendDate(opsStatus.generatedAt)}. The machine remembers what the flesh forgets.`
        : "No chronicle has been sealed yet. The archive waits for the first run.",
    },
    {
      name: "Scout Ilya",
      districtKey: "watchtower",
      tone: scouts.length ? "wild" : "cold",
      ticker: scouts[0]?.ticker || "",
      line: scouts.length
        ? `${scouts[0].ticker} is moving in the outskirts. Not ready for a raid, but too alive to ignore.`
        : "The hills are quiet. No side quests deserve the party's time right now.",
    },
  ];
}

/**
 * Build the Diablo-flavored loot shelf from current desk state.
 *
 * @param {Object} params - Theme inputs from the orchestration layer.
 * @param {Record<string, any>} [params.queue={}] - Execution queue payload.
 * @param {Record<string, any>|null} [params.raid=null] - Top raid candidate.
 * @param {Record<string, any>|null} [params.merchant=null] - Top merchant candidate.
 * @param {Record<string, any>|null} [params.scout=null] - Top scout candidate.
 * @param {Record<string, any>|null} [params.opsStatus=null] - Ops status payload.
 * @param {Record<string, any>|null} [params.watchdogStatus=null] - Watchdog status payload.
 * @returns {Array<Record<string, any>>} Loot descriptors for the vault.
 */
export function buildLootDrops({
  queue = {},
  raid = null,
  merchant = null,
  scout = null,
  opsStatus = null,
  watchdogStatus = null,
} = {}) {
  const ready = (queue.items || []).find((item) => item.intentStatus === "approval-ready");
  const opsHealthy = opsStatus?.ok && watchdogStatus?.ok;

  return [
    {
      type: "Raid Writ",
      rarity: raid ? "Legendary" : "Dormant",
      tone: raid ? "hot" : "cold",
      ticker: raid?.ticker || "",
      name: raid ? `${raid.ticker} Bloodseal` : "Unclaimed Bloodseal",
      note: raid ? `Primary route ${raid.rec1}. ${raid.actionBias.note}` : "No full-conviction raid trophy has dropped yet.",
    },
    {
      type: "Merchant Relic",
      rarity: merchant ? "Rare" : "Dormant",
      tone: merchant ? merchant.accumulationBias.tone : "cold",
      ticker: merchant?.ticker || "",
      name: merchant ? `${merchant.ticker} Ash Coin` : "Empty Coin Purse",
      note: merchant ? merchant.discountReasons.join(" | ") : "No long-term bargain deserves a purchase ritual today.",
    },
    {
      type: "Scout Totem",
      rarity: scout ? "Uncommon" : "Dormant",
      tone: scout ? "wild" : "cold",
      ticker: scout?.ticker || "",
      name: scout ? `${scout.ticker} Watch Totem` : "Extinguished Totem",
      note: scout ? `${scout.daysUntilEarnings}d to earnings | ${scout.confidence} / 3 confidence` : "No worthy scout signal is circling the town.",
    },
    {
      type: "Forge Sigil",
      rarity: ready ? "Legendary" : "Common",
      tone: ready ? "hot" : "wild",
      ticker: ready?.ticker || "",
      name: ready ? `${ready.ticker} Broker Sigil` : "Dormant Forge Sigil",
      note: ready ? ready.nextStep : "The forge is lit, but no ticket is fully armed for review.",
    },
    {
      type: "Machine Charm",
      rarity: opsHealthy ? "Rare" : "Cracked",
      tone: opsHealthy ? "hot" : "cold",
      ticker: "",
      name: opsHealthy ? "Watchdog Lantern" : "Cracked Relay Charm",
      note: opsHealthy ? "Automation patrols are alive and the dawn relay is holding." : "Something in the machine chorus needs attention.",
    },
  ];
}

/**
 * Render the detailed creature card for the selected ticker.
 *
 * @param {Record<string, any>} row - Selected enriched row.
 * @param {ReturnType<typeof describeTemperature>} [creature=describeTemperature(row)] - Temperature creature.
 * @returns {string} HTML snippet for the mascot card.
 */
export function renderMascotCard(row, creature = describeTemperature(row)) {
  return `
    <div class="mascot-card">
      <div class="mascot-header">
        <div>
          <p class="eyebrow">Signal Demon</p>
          <strong>${creature.name}</strong>
          <p class="mascot-subcopy">${creature.role}</p>
        </div>
        <span class="temp-chip ${creature.key}">
          <span class="mini-face">${creature.miniFace}</span>
          <span>${creature.label}</span>
        </span>
      </div>
      <div class="mascot-stage">
        <div class="mascot-portrait ${creature.key}">
          <div class="mascot-head"></div>
          <div class="mascot-mouth"></div>
        </div>
        <div class="mascot-lines">
          <div class="mascot-line">
            <span>Reads</span>
            <p>${row.signalTrigger ? "The seal is broken and the demon is pacing the arena." : "Still locked below the floorboards, waiting for confirmation."}</p>
          </div>
          <div class="mascot-line">
            <span>Behavior</span>
            <p>${creature.hint}</p>
          </div>
          <div class="mascot-line">
            <span>Loot</span>
            <p>${row.status === "Ready" ? "A live setup with blood in it and momentum behind it." : row.setupRec === "Avoid" ? "Information only. Keep your capital out of the fire." : "Watchlist material. Could mutate into a real winner fast."}</p>
          </div>
        </div>
      </div>
    </div>
  `;
}

/**
 * Build the Diablo-flavored narrative paragraph for a recommendation.
 *
 * @param {Record<string, any>} row - Enriched trading row.
 * @returns {string} Narrative thesis text.
 */
export function buildNarrative(row) {
  const timing =
    row.daysUntilEarnings <= 10
      ? "The catalyst window is almost here, so precision matters more than panic and greed."
      : row.daysUntilEarnings <= 30
        ? "The event sits in the strike zone, where disciplined names start separating from the pretenders."
        : "This one is still earlier in the cycle, so it feels more like stalking prey than swinging the blade.";

  const signal = row.signalTrigger
    ? "Your signal trigger is already active, which means the market has stopped whispering and started confessing."
    : "The trigger has not fired yet, so this stays chained until price action proves it belongs in the arena.";

  const setup =
    row.setupRec === "Avoid"
      ? "The setup recommendation is defensive, so treat the name like a cursed relic: study it, but do not worship it."
      : `The current setup bias favors ${row.setupRec.toLowerCase()} structures.`;

  return `${timing} ${signal} ${setup}`;
}
