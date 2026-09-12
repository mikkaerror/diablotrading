GIANT_TICKERS = {'NVDA', 'AVGO', 'AMD', 'ASML', 'QCOM', 'ARM', 'AMZN', 'GOOG', 'GOOGL', 'META', 'MSFT', 'ORCL', 'TSM', 'TXN'}

SLEEPER_HINTS = {'MRVL', 'VRT', 'SMCI', 'DELL', 'HPE', 'MOD', 'ETN', 'PWR', 'GLW', 'LITE', 'FN', 'COHR', 'GDS', 'VNET', 'AEHR', 'AAOI'}

CATEGORY_OVERRIDES = {'MOD': 'Data Center Power/Cooling', 'VRT': 'Data Center Power/Cooling', 'ETN': 'Data Center Power/Cooling', 'PWR': 'Data Center Power/Cooling', 'DELL': 'AI Server OEM', 'SMCI': 'AI Server OEM', 'HPE': 'AI Server OEM', 'MRVL': 'AI Networking Silicon', 'GLW': 'Optical/Data Center Materials', 'LITE': 'Optical/Data Center Materials', 'FN': 'Optical/Data Center Materials', 'COHR': 'Optical/Data Center Materials', 'AEHR': 'Semi Test Equipment', 'AAOI': 'Optical/Data Center Materials', 'GDS': 'Data Center Operator', 'VNET': 'Data Center Operator'}

CATEGORY_THEME_SCORES = {'Data Center Power/Cooling': 88.0, 'AI Server OEM': 86.0, 'AI Networking Silicon': 94.0, 'Optical/Data Center Materials': 82.0, 'Semi Test Equipment': 84.0, 'Data Center Operator': 78.0}

def numeric_input(value: Any) -> dict[str, Any]:
    """Keep absent and invalid observations distinct from a valid zero."""
    if value is None or (isinstance(value, str) and (not value.strip())):
        return {'value': None, 'status': 'missing'}
    try:
        parsed = float(str(value).replace('$', '').replace(',', '').replace('%', ''))
    except (TypeError, ValueError):
        return {'value': None, 'status': 'invalid'}
    if isinstance(value, bool) or not math.isfinite(parsed):
        return {'value': None, 'status': 'invalid'}
    return {'value': parsed, 'status': 'observed'}

def number(value: Any, default: float=0.0) -> float:
    """Parse a finite numeric observation, retaining the existing default."""
    parsed = numeric_input(value)['value']
    return parsed if parsed is not None else default

def market_numeric_input(row: dict[str, Any], key: str, fallback_key: str | None=None) -> dict[str, Any]:
    """Use tracker fallback only when context is absent, never for zero/invalid."""
    raw = context(row).get(key)
    parsed = numeric_input(raw)
    source = f'marketContext.{key}'
    if parsed['status'] == 'missing':
        source = fallback_key or key
        parsed = numeric_input(row.get(source))
    return {**parsed, 'source': source}

def tracker_pe_context(row: dict[str, Any]) -> dict[str, Any]:
    """A nonpositive earnings multiple cannot measure cheapness."""
    parsed = numeric_input(row.get('pe'))
    if parsed['value'] is not None:
        parsed['status'] = 'meaningful' if parsed['value'] > 0 else 'not-meaningful'
        if parsed['value'] <= 0:
            parsed['value'] = None
    return {**parsed, 'source': 'pe'}

def earnings_timing_context(row: dict[str, Any]) -> dict[str, Any]:
    """Validate the supplied offset without asserting issuer confirmation."""
    parsed = numeric_input(row.get('daysUntilEarnings'))
    days = parsed['value']
    return {'days': days, 'status': ('past' if days < 0 else 'upcoming') if days is not None else parsed['status']}

def within_earnings_window(row: dict[str, Any], maximum: float) -> bool:
    """Keep past and invalid events outside a forward-looking research list."""
    days = earnings_timing_context(row)['days']
    return days is not None and 0 <= days <= maximum

def clamp(value: float, low: float=0.0, high: float=100.0) -> float:
    """Clamp a score to a stable 0-100 band."""
    return max(low, min(high, value))

def sweet_spot(value: float, *, center: float, width: float) -> float:
    """Score proximity to a desired center point.

    Used for IV rank and support/resistance distances where extremes are less
    useful than a controlled middle zone.
    """
    return clamp(100.0 - abs(value - center) / max(width, 0.0001) * 100.0)

def load_snapshot_rows(rows: list[dict[str, Any]] | None=None) -> list[dict[str, Any]]:
    """Load tracker rows unless a test supplied rows directly."""
    if rows is not None:
        return rows
    snapshot = load_json_file(SNAPSHOT_FILE) or {}
    loaded = snapshot.get('rows') or []
    return loaded if isinstance(loaded, list) else []

def load_edge_map(edge_research: dict[str, Any] | None=None) -> dict[str, dict[str, Any]]:
    """Index the existing edge-research artifact by ticker."""
    payload = edge_research if edge_research is not None else load_json_file(EDGE_RESEARCH_FILE) or {}
    ranked = payload.get('ranked') if isinstance(payload, dict) else []
    edge_map: dict[str, dict[str, Any]] = {}
    for item in ranked or []:
        ticker = str(item.get('ticker') or '').upper()
        if ticker:
            edge_map[ticker] = item
    return edge_map

def context(row: dict[str, Any]) -> dict[str, Any]:
    """Return normalized market context from a tracker row."""
    payload = row.get('marketContext')
    return payload if isinstance(payload, dict) else {}

def watchlist_technical_research(row: dict[str, Any]) -> dict[str, Any]:
    """Return normalized technical discovery context without changing conviction gates."""
    pulse = context(row).get('watchlistPulse') or row.get('watchlistPulse')
    return watchlist_technical_research_from_pulse(pulse)

def trend_score(row: dict[str, Any]) -> float:
    """Score trend tone without pretending trend alone is edge."""
    trend = str((context(row).get('trend') or {}).get('label') or row.get('trend') or 'Neutral').lower()
    if 'bull' in trend or 'uptrend' in trend:
        return 100.0
    if 'base' in trend:
        return 74.0
    if 'neutral' in trend:
        return 55.0
    if 'bear' in trend:
        return 18.0
    return 45.0

def timing_score(row: dict[str, Any]) -> float:
    """Score catalyst timing from readiness, confidence, trigger, and earnings window."""
    days = number(row.get('daysUntilEarnings'), 999)
    if 0 <= days <= 14:
        window = 100.0
    elif 15 <= days <= 30:
        window = 78.0
    elif 31 <= days <= 60:
        window = 52.0
    else:
        window = 25.0
    return round(number(row.get('readiness')) * 0.35 + clamp(number(row.get('priority')) / 10.0 * 100.0) * 0.18 + clamp(number(row.get('confidence')) / 3.0 * 100.0) * 0.17 + (100.0 if row.get('signalTrigger') else 0.0) * 0.15 + window * 0.15, 2)

def options_score(row: dict[str, Any]) -> float:
    """Score whether the options setup has enough volatility context to respect."""
    setup = str(row.get('setupRec') or '').lower()
    iv_rank = number(row.get('ivRank'), 50.0)
    iv_impulse = number(row.get('ivRankChange'))
    atr_z = number(row.get('atrZScore'))
    atr_percent = number(row.get('atrPercent'))
    iv_impulse_score = clamp((iv_impulse + 0.35) / 1.25 * 100.0)
    atr_z_score = clamp((atr_z + 1.0) / 3.0 * 100.0)
    atr_percent_score = clamp(atr_percent / 7.0 * 100.0)
    if 'vertical' in setup:
        iv_score = sweet_spot(iv_rank, center=42.0, width=45.0)
        return round(iv_score * 0.35 + atr_z_score * 0.25 + atr_percent_score * 0.15 + iv_impulse_score * 0.25, 2)
    if 'straddle' in setup:
        iv_score = sweet_spot(iv_rank, center=55.0, width=40.0)
        return round(iv_score * 0.2 + atr_z_score * 0.35 + atr_percent_score * 0.2 + iv_impulse_score * 0.25, 2)
    if 'condor' in setup:
        calm_score = sweet_spot(iv_rank, center=62.0, width=35.0)
        low_expansion = clamp(100.0 - atr_z_score * 0.65)
        return round(calm_score * 0.5 + low_expansion * 0.3 + trend_score(row) * 0.2, 2)
    return round(sweet_spot(iv_rank, center=50.0, width=45.0) * 0.4 + atr_z_score * 0.35 + iv_impulse_score * 0.25, 2)

def structure_score(row: dict[str, Any]) -> float:
    """Score market structure from trend, RVOL, ATR expansion, and room to resistance."""
    ctx = context(row)
    rvol = number(market_numeric_input(row, 'rvol')['value'], 1.0)
    atr_expansion = number(market_numeric_input(row, 'atrExpansion', 'atrZScore')['value'])
    resistance_room = number(market_numeric_input(row, 'distanceToResistancePct')['value'], 0.0)
    support_distance = number(market_numeric_input(row, 'distanceToSupportPct')['value'], 999.0)
    alignment = number(ctx.get('alignmentScore'), 50.0)
    rvol_score = 100.0 if rvol >= 1.35 else 78.0 if rvol >= 1.0 else 48.0 if rvol >= 0.5 else 28.0
    expansion_score = clamp((atr_expansion + 1.0) / 3.0 * 100.0)
    resistance_score = clamp(resistance_room / 8.0 * 100.0)
    support_score = clamp(100.0 - support_distance / 15.0 * 100.0)
    return round(trend_score(row) * 0.24 + rvol_score * 0.18 + expansion_score * 0.18 + resistance_score * 0.18 + support_score * 0.12 + alignment * 0.1, 2)

def theme_score(row: dict[str, Any], edge: dict[str, Any] | None) -> float:
    """Score how tightly the name maps to the current AI/data-center bull cycle."""
    ticker = str(row.get('ticker') or '').upper()
    if ticker in CATEGORY_OVERRIDES:
        return CATEGORY_THEME_SCORES.get(CATEGORY_OVERRIDES[ticker], 80.0)
    if edge:
        scores = edge.get('scores') or {}
        thesis = number(scores.get('thesisScore'), number(edge.get('edgeScore'), 50.0))
        category = str(edge.get('category') or '')
        category_bonus = 8.0 if category in {'AI/Compute Picks', 'Semiconductor Supply Chain', 'Cloud/Data Rails'} else 0.0
        return clamp(thesis + category_bonus)
    if ticker in GIANT_TICKERS:
        return 92.0
    if ticker in SLEEPER_HINTS:
        return 82.0
    return 45.0

def quality_score(row: dict[str, Any], edge: dict[str, Any] | None) -> float:
    """Use edge-research quality when available, otherwise use tracker proxies."""
    if edge:
        score = number((edge.get('scores') or {}).get('qualityScore'), -1.0)
        if score >= 0:
            return score
    value = clamp(number(row.get('valueScore')) / 10.0 * 100.0)
    pe = number(tracker_pe_context(row)['value'], 999.0)
    pe_score = 100.0 if 0 < pe <= 25 else 72.0 if pe <= 50 else 42.0 if pe <= 100 else 18.0
    return round(value * 0.55 + pe_score * 0.45, 2)

def valuation_score(row: dict[str, Any], edge: dict[str, Any] | None) -> float:
    """Score valuation and discount discipline."""
    if edge:
        score = number((edge.get('scores') or {}).get('valuationRiskScore'), -1.0)
        if score >= 0:
            return score
    long_term = clamp(number(row.get('longTermScore')) / 10.0 * 100.0)
    pe = number(tracker_pe_context(row)['value'], 999.0)
    pe_score = 100.0 if 0 < pe <= 25 else 75.0 if pe <= 45 else 45.0 if pe <= 90 else 15.0
    return round(long_term * 0.6 + pe_score * 0.4, 2)

def evidence_score(row: dict[str, Any], edge: dict[str, Any] | None) -> float:
    """Score source-status and shared-input agreement, not independent evidence."""
    source_status = str(context(row).get('sourceStatus') or '').lower()
    source = 55.0 if source_status == 'fallback' else 85.0 if source_status else 65.0
    edge_agreement = number(edge.get('edgeScore'), 50.0) if edge else 45.0
    confidence = clamp(number(row.get('confidence')) / 3.0 * 100.0)
    return round(source * 0.3 + edge_agreement * 0.4 + confidence * 0.3, 2)

def long_term_score(row: dict[str, Any], edge: dict[str, Any] | None) -> float:
    """Score long-term accumulation attractiveness."""
    support_distance = number(market_numeric_input(row, 'distanceToSupportPct')['value'], 999.0)
    buy_zone = clamp(100.0 - support_distance / 14.0 * 100.0)
    return round(theme_score(row, edge) * 0.22 + quality_score(row, edge) * 0.22 + valuation_score(row, edge) * 0.22 + clamp(number(row.get('longTermScore')) / 10.0 * 100.0) * 0.22 + buy_zone * 0.12, 2)

def gut_check_score(row: dict[str, Any], edge: dict[str, Any] | None) -> float:
    """Combine overlapping research pillars into an uncalibrated rank score."""
    return round(theme_score(row, edge) * 0.18 + timing_score(row) * 0.2 + options_score(row) * 0.17 + structure_score(row) * 0.16 + quality_score(row, edge) * 0.13 + valuation_score(row, edge) * 0.09 + evidence_score(row, edge) * 0.07, 2)

def core_pillar_values(pillars: dict[str, float]) -> list[float]:
    """Return the near-term pillars used to measure breadth."""
    return [number(pillars.get('theme')), number(pillars.get('timing')), number(pillars.get('options')), number(pillars.get('structure')), number(pillars.get('quality')), number(pillars.get('valuation')), number(pillars.get('evidence'))]

def pillar_balance_score(pillars: dict[str, float]) -> float:
    """Score how evenly conviction is distributed across independent pillars.

    A one-pillar wonder should not outrank a broad, boring compounder. The
    geometric/arithmetic mean ratio punishes lopsided rows while leaving
    balanced rows close to 100. The epsilon prevents log(0)-style blowups when
    a pillar is missing or truly weak.
    """
    values = [clamp(value, 0.0, 100.0) for value in core_pillar_values(pillars)]
    if not values:
        return 0.0
    arithmetic = sum(values) / len(values)
    if arithmetic <= 0:
        return 0.0
    product = 1.0
    for value in values:
        product *= max(value, 1.0)
    geometric = product ** (1.0 / len(values))
    return round(clamp(geometric / arithmetic * 100.0), 2)

def uncertainty_penalty(row: dict[str, Any], edge: dict[str, Any] | None, pillars: dict[str, float], flags: list[str]) -> float:
    """Quantify how much to haircut the gut score for fragile evidence.

    This is intentionally conservative. Missing source quality, unclassified
    themes, and risk flags do not forbid research, but they reduce trust in the
    score until the operator or data pipeline resolves the uncertainty.
    """
    ticker = str(row.get('ticker') or '').upper()
    penalty = 0.0
    if str(context(row).get('sourceStatus') or '').lower() == 'fallback':
        penalty += 8.0
    if edge is None and ticker not in GIANT_TICKERS and (ticker not in CATEGORY_OVERRIDES):
        penalty += 6.0
    if not row.get('signalTrigger'):
        penalty += 4.0
    if number(pillars.get('evidence')) < 55:
        penalty += 4.0
    if number(pillars.get('structure')) < 45:
        penalty += 3.0
    penalty += min(len(flags), 4) * 1.75
    if 'high PE' in flags:
        penalty += 2.5
    if 'near resistance' in flags and 'far from support' in flags:
        penalty += 3.0
    return round(clamp(penalty, 0.0, 32.0), 2)

def conviction_adjusted_score(gut: float, pillars: dict[str, float], penalty: float) -> float:
    """Blend gut score, pillar breadth, and evidence quality after haircuts."""
    balance = pillar_balance_score(pillars)
    evidence = number(pillars.get('evidence'))
    adjusted = gut * 0.74 + balance * 0.16 + evidence * 0.1 - penalty
    return round(clamp(adjusted), 2)

def evidence_grade(adjusted: float, balance: float, penalty: float) -> str:
    """Turn adjusted conviction into a plain-English quality grade."""
    if adjusted >= 78 and balance >= 78 and (penalty <= 8):
        return 'A'
    if adjusted >= 68 and balance >= 68 and (penalty <= 14):
        return 'B'
    if adjusted >= 56 and penalty <= 22:
        return 'C'
    return 'D'

def research_action(row: dict[str, Any], adjusted: float, long_term: float, flags: list[str]) -> str:
    """Suggest the next research workflow without authorising a trade."""
    if adjusted >= 72 and row.get('signalTrigger') and (len(flags) <= 2):
        return 'prioritize paper evidence'
    if long_term >= 72:
        return 'inventory watchlist'
    if adjusted >= 62:
        return 'manual thesis review'
    if row.get('signalTrigger'):
        return 'shadow only'
    return 'watch only'

def reason_codes(row: dict[str, Any], edge: dict[str, Any] | None, pillars: dict[str, float], flags: list[str]) -> list[str]:
    """Emit short machine-readable reasons for why a row scored where it did."""
    ticker = str(row.get('ticker') or '').upper()
    reasons: list[str] = []
    if ticker in GIANT_TICKERS:
        reasons.append('behemoth')
    if ticker in SLEEPER_HINTS:
        reasons.append('sleeper')
    if number(pillars.get('theme')) >= 82:
        reasons.append('theme-aligned')
    if number(pillars.get('timing')) >= 75:
        reasons.append('timing-live')
    if number(pillars.get('options')) >= 62:
        reasons.append('options-aligned')
    if number(pillars.get('structure')) >= 62:
        reasons.append('structure-clean')
    if number(pillars.get('valuation')) >= 70:
        reasons.append('valuation-respectable')
    if edge:
        reasons.append('edge-research-linked')
    if flags:
        reasons.append('risk-flagged')
    return reasons[:8]

def archetype(row: dict[str, Any], edge: dict[str, Any] | None, score: float) -> str:
    """Classify the name for operator psychology: giant, sleeper, winner, or wait."""
    ticker = str(row.get('ticker') or '').upper()
    if ticker in GIANT_TICKERS:
        return 'behemoth'
    if ticker in SLEEPER_HINTS and score >= 58:
        return 'sleeper'
    if score >= 76 and row.get('signalTrigger') and (number(row.get('readiness')) >= 85):
        return 'winner'
    if long_term_score(row, edge) >= 70:
        return 'compounder'
    return 'watch'

def risk_flags(row: dict[str, Any], edge: dict[str, Any] | None) -> list[str]:
    """Surface reasons not to blindly trust a hot name."""
    flags: list[str] = []
    ctx = context(row)
    if str(ctx.get('sourceStatus') or '').lower() == 'fallback':
        flags.append('market context fallback')
    if number(row.get('pe'), 0.0) > 90:
        flags.append('high PE')
    if number(market_numeric_input(row, 'distanceToResistancePct')['value'], 99.0) < 3:
        flags.append('near resistance')
    if number(market_numeric_input(row, 'distanceToSupportPct')['value'], 0.0) > 18:
        flags.append('far from support')
    if options_score(row) < 45:
        flags.append('options setup thin')
    if edge and number(edge.get('edgeScore')) < 60:
        flags.append('theme edge weak')
    if not row.get('signalTrigger'):
        flags.append('trigger not live')
    return flags[:4]

def build_row(row: dict[str, Any], edge: dict[str, Any] | None) -> dict[str, Any]:
    """Build one enriched conviction row."""
    ticker = str(row.get('ticker') or '').upper()
    gut = gut_check_score(row, edge)
    long_term = long_term_score(row, edge)
    technical = watchlist_technical_research(row)
    pillars = {'theme': round(theme_score(row, edge), 2), 'timing': timing_score(row), 'options': options_score(row), 'structure': structure_score(row), 'quality': round(quality_score(row, edge), 2), 'valuation': round(valuation_score(row, edge), 2), 'evidence': evidence_score(row, edge), 'longTerm': long_term}
    flags = risk_flags(row, edge)
    balance = pillar_balance_score(pillars)
    penalty = uncertainty_penalty(row, edge, pillars, flags)
    adjusted = conviction_adjusted_score(gut, pillars, penalty)
    return {'ticker': ticker, 'archetype': archetype(row, edge, gut), 'category': CATEGORY_OVERRIDES.get(ticker) or (edge or {}).get('category') or ('AI/Data Center Giant' if ticker in GIANT_TICKERS else 'Unclassified'), 'gutCheckScore': gut, 'convictionAdjustedScore': adjusted, 'pillarBalanceScore': balance, 'uncertaintyPenalty': penalty, 'evidenceGrade': evidence_grade(adjusted, balance, penalty), 'inputDiagnostics': {'trackerPE': tracker_pe_context(row), 'peUsedByFallbackPillars': {key: numeric_input(((edge or {}).get('scores') or {}).get(score))['value'] is None or number(((edge or {}).get('scores') or {}).get(score), -1.0) < 0 for key, score in (('quality', 'qualityScore'), ('valuation', 'valuationRiskScore'))}, 'earningsTiming': earnings_timing_context(row), 'structure': {key: market_numeric_input(row, key, fallback) for key, fallback in (('rvol', None), ('atrExpansion', 'atrZScore'), ('distanceToResistancePct', None), ('distanceToSupportPct', None))}}, 'longTermConvictionScore': long_term, 'researchAction': research_action(row, adjusted, long_term, flags), 'readiness': row.get('readiness'), 'daysUntilEarnings': row.get('daysUntilEarnings'), 'setupRec': row.get('setupRec'), 'signalTrigger': bool(row.get('signalTrigger')), 'price': row.get('price'), 'support': ctx_value(row, 'support'), 'resistance': ctx_value(row, 'resistance'), 'rvol': ctx_value(row, 'rvol'), 'trend': (context(row).get('trend') or {}).get('label') or row.get('trend'), 'ivRank': row.get('ivRank'), 'atrZScore': row.get('atrZScore'), 'technicalResearch': technical, 'technicalResearchScore': technical.get('score'), 'pillars': pillars, 'riskFlags': flags, 'reasonCodes': reason_codes(row, edge, pillars, flags), 'thesis': conviction_thesis(row, edge, gut, long_term)}

def ctx_value(row: dict[str, Any], key: str) -> Any:
    """Read numeric market context with the same precedence as scoring."""
    return market_numeric_input(row, key)['value']

def conviction_thesis(row: dict[str, Any], edge: dict[str, Any] | None, gut: float, long_term: float) -> str:
    """Write a concise thesis line for a conviction row."""
    ticker = str(row.get('ticker') or '').upper()
    category = CATEGORY_OVERRIDES.get(ticker) or (edge or {}).get('category') or 'theme'
    if gut >= 78:
        return f'{ticker} has aligned research scores in {category}; shared inputs are not independent confirmation.'
    if long_term >= 72:
        return f'{ticker} merits ownership research; test milestones, valuation and portfolio fit before considering additions.'
    if ticker in SLEEPER_HINTS:
        return f'{ticker} is a possible sleeper; demand cleaner evidence before upgrading it.'
    if ticker in GIANT_TICKERS:
        return f'{ticker} is a behemoth, but the desk still needs entry discipline.'
    return f'{ticker} stays on watch until more pillars line up.'

def rank_rows(rows: list[dict[str, Any]], edge_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank all snapshot rows into conviction rows."""
    ranked = [build_row(row, edge_map.get(str(row.get('ticker') or '').upper())) for row in rows if row.get('ticker')]
    return sorted(ranked, key=lambda item: item['gutCheckScore'], reverse=True)

def top_filter(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool], limit: int=10, key: str='gutCheckScore') -> list[dict[str, Any]]:
    """Return top rows matching a predicate."""
    return sorted([row for row in rows if predicate(row)], key=lambda item: item.get(key, 0), reverse=True)[:limit]

def coverage_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize full tracker coverage without turning it into an allocation list.

    The tracker is the operator-maintained research universe. Every scored row
    stays in the artifact so DCA and concentration research can inspect the
    full set; the short named sections are a readable digest, not an implicit
    exclusion list or a funding instruction.
    """
    action_counts = Counter((str(row.get('researchAction') or 'watch only') for row in rows))
    grade_counts = Counter((str(row.get('evidenceGrade') or 'unknown') for row in rows))
    long_term_qualified = sum((1 for row in rows if number(row.get('longTermConvictionScore')) >= 66 and number(row.get('support')) > 0))
    return {'retainedRankedRows': len(rows), 'researchActionCounts': dict(sorted(action_counts.items())), 'evidenceGradeCounts': dict(sorted(grade_counts.items())), 'longTermResearchQualified': long_term_qualified, 'fullTrackerRetained': True}

def build_conviction_research(rows: list[dict[str, Any]] | None=None, edge_research: dict[str, Any] | None=None, limit: int=12) -> dict[str, Any]:
    """Build the full research-only conviction map."""
    snapshot_rows = load_snapshot_rows(rows)
    edge_map = load_edge_map(edge_research)
    ranked = rank_rows(snapshot_rows, edge_map)
    behemoths = top_filter(ranked, lambda item: item['ticker'] in GIANT_TICKERS, limit=limit)
    sleepers = top_filter(ranked, lambda item: item['ticker'] in SLEEPER_HINTS and item['ticker'] not in GIANT_TICKERS, limit=limit)
    near_term = top_filter(ranked, lambda item: item['signalTrigger'] and number(item['readiness']) >= 85 and within_earnings_window(item, 30), limit=limit)
    options_watch = top_filter(ranked, lambda item: item['pillars']['options'] >= 62 and within_earnings_window(item, 45), limit=limit)
    technical_leaders = top_filter(ranked, lambda item: (item.get('technicalResearch') or {}).get('status') == 'complete', limit=limit, key='technicalResearchScore')
    balanced = top_filter(ranked, lambda item: item['evidenceGrade'] in {'A', 'B', 'C'}, limit=limit, key='convictionAdjustedScore')
    long_term_buy_zone = top_filter(ranked, lambda item: item['longTermConvictionScore'] >= 66 and number(item.get('support'), 0) > 0, limit=limit, key='longTermConvictionScore')
    contradictions = top_filter(ranked, lambda item: number(item['readiness']) >= 85 and bool(item['riskFlags']), limit=limit)
    coverage = coverage_summary(ranked)
    return {'generatedAt': local_now().isoformat(), 'stage': 'conviction-research-only', 'researchOnly': True, 'promotable': False, 'mathVersion': 'conviction-v3-input-semantics', 'authorityChanged': False, 'brokerSubmitAllowed': False, 'liveTradingAllowed': False, 'trackedRows': len(snapshot_rows), 'scoredRows': len(ranked), 'coverage': coverage, 'regimeThesis': 'AI infrastructure demand is a research hypothesis to test through funded delivery, cash generation and value per share; the dated references below are not a current regime check.', 'regimeReferences': list(REGIME_REFERENCES), 'strategyReferences': list(STRATEGY_REFERENCES), 'metricsThatMatter': ['gutCheckScore = theme, timing, options, structure, quality, valuation, and evidence agreement', 'longTermConvictionScore = theme, quality, valuation, long-term score, and buy-zone discipline', 'options pillar = IV rank sweet spot, IV impulse, ATR pressure, and setup type', 'structure pillar = trend, RVOL, ATR expansion, support distance, resistance headroom, and alignment', 'convictionAdjustedScore = gut score blended with pillar balance and evidence, then haircut by uncertainty', 'pillarBalanceScore = geometric/arithmetic mean ratio across the seven near-term pillars', 'uncertaintyPenalty = fallback data, missing edge research, weak evidence, dead trigger, and risk-flag haircuts', 'riskFlags = fallback data, high valuation, near resistance, far from support, weak options, weak theme, or dead trigger', 'technicalResearchScore = normalized watchlist RVOL, price momentum, and close-location discovery context; uncalibrated and excluded from gates'], 'behemoths': behemoths, 'sleepers': sleepers, 'nearTermWinners': near_term, 'optionsWatch': options_watch, 'technicalDiscoveryLeaders': technical_leaders, 'bestBalanced': balanced, 'longTermBuyZone': long_term_buy_zone, 'contradictions': contradictions, 'ranked': ranked, 'safety': ['Research-only; never changes approval, broker, or authority state.', 'Scores and letter grades are uncalibrated heuristics, not probabilities or independent evidence. Missing inputs can still use legacy scoring defaults; inputDiagnostics exposes the reviewed fields.', 'Strong theme is not a trade. A trade still needs paper evidence, strike gates, and explicit confirmation.', 'Use sleepers for investigation, not blind size.']}

def render_section(title: str, items: list[dict[str, Any]], *, score_key: str='gutCheckScore') -> list[str]:
    """Render a ranked section for the text report."""
    lines = ['', f'{title}:']
    if not items:
        lines.append('- none')
        return lines
    for index, item in enumerate(items, start=1):
        flags = ', '.join(item.get('riskFlags') or []) or 'none'
        lines.append(f"{index}. {item.get('ticker')} | {item.get('category')} | {score_key} {item.get(score_key)} | adj {item.get('convictionAdjustedScore')} | grade {item.get('evidenceGrade')} | ready {item.get('readiness')} | {item.get('setupRec')} | {item.get('daysUntilEarnings')}d | technical {item.get('technicalResearchScore', 'N/A')} ({(item.get('technicalResearch') or {}).get('posture', 'unavailable')})")
        lines.append(f"   {item.get('thesis')} R/S {item.get('resistance')}/{item.get('support')} | action: {item.get('researchAction')} | flags: {flags}")
    return lines

def conviction_research_text(report: dict[str, Any]) -> str:
    """Render the conviction report."""
    lines = ['Inferno Conviction Research', '', f"Generated: {report.get('generatedAt')}", f"Stage: {report.get('stage')}", f"Tracked rows: {report.get('trackedRows')} | scored rows: {report.get('scoredRows')}", f"Regime thesis: {report.get('regimeThesis')}", '', 'Full tracker coverage:', f"- retained in durable ranking: {(report.get('coverage') or {}).get('retainedRankedRows', 0)}", f"- long-term research-qualified: {(report.get('coverage') or {}).get('longTermResearchQualified', 0)}", '- named sections below are a digest; the JSON artifact retains every tracked row.', '', 'Metrics that matter:']
    for metric in report.get('metricsThatMatter') or []:
        lines.append(f'- {metric}')
    lines.extend(render_section('Behemoths / giants', report.get('behemoths') or []))
    lines.extend(render_section('Sleepers to investigate', report.get('sleepers') or []))
    lines.extend(render_section('Near-term catalyst research', report.get('nearTermWinners') or []))
    lines.extend(render_section('Options watch', report.get('optionsWatch') or []))
    lines.extend(render_section('Technical discovery leaders (uncalibrated; no gate change)', report.get('technicalDiscoveryLeaders') or [], score_key='technicalResearchScore'))
    lines.extend(render_section('Best balanced conviction', report.get('bestBalanced') or [], score_key='convictionAdjustedScore'))
    lines.extend(render_section('Long-term buy-zone candidates', report.get('longTermBuyZone') or [], score_key='longTermConvictionScore'))
    lines.extend(render_section('Contradictions / gut checks', report.get('contradictions') or []))
    lines.extend(['', 'Research references:'])
    for ref in report.get('strategyReferences') or []:
        tag = f"[{ref.get('theoryTag')}] " if ref.get('theoryTag') else ''
        lines.append(f"- {tag}{ref.get('name')} ({ref.get('researcher')}): {ref.get('deskUse')} Source: {ref.get('source')}")
    lines.extend(['', 'Regime references:'])
    for ref in report.get('regimeReferences') or []:
        tag = f"[{ref.get('theoryTag')}] " if ref.get('theoryTag') else ''
        lines.append(f"- {tag}{ref.get('name')}: {ref.get('metric')} Source: {ref.get('source')}")
    lines.extend(['', 'Safety:'])
    for item in report.get('safety') or []:
        lines.append(f'- {item}')
    return '\n'.join(lines).rstrip() + '\n'

def save_conviction_research(report: dict[str, Any]) -> None:
    """Persist conviction research artifacts."""
    ensure_dirs()
    atomic_write_json(CONVICTION_RESEARCH_FILE, report)
    atomic_write_text(CONVICTION_RESEARCH_TEXT_FILE, conviction_research_text(report))

def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description='Build research-only conviction map.')
    parser.add_argument('command', nargs='?', default='build', choices=['build', 'status'])
    parser.add_argument('--limit', type=int, default=12)
    return parser.parse_args()

def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    if args.command == 'status' and CONVICTION_RESEARCH_TEXT_FILE.exists():
        print(CONVICTION_RESEARCH_TEXT_FILE.read_text(encoding='utf-8'))
        return 0
    report = build_conviction_research(limit=args.limit)
    save_conviction_research(report)
    print(conviction_research_text(report))
    return 0
