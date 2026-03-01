/**
 * Kelly Criterion Calculator
 * Calculates optimal bet size based on edge, bankroll, and user risk settings.
 * Reads settings from Firestore (via auth.js userProfile) with localStorage fallback.
 */

const KellyCalculator = {

  /** Get user's investment settings, merging Firestore + defaults */
  getSettings() {
    const defaults = {
      bankroll: 1000,
      unitSize: 10,
      kellyFraction: 'half',
      maxBetPct: 5,
      riskTolerance: 'moderate',
      minConfidence: 55,
    };
    // userProfile is set by auth.js onAuthStateChanged
    // profile.html saves bankroll/unitSize/kelly settings to investmentProfile, so check both
    const s = (typeof userProfile !== 'undefined' && userProfile?.settings) || {};
    const ip = (typeof userProfile !== 'undefined' && userProfile?.investmentProfile) || {};
    // investmentProfile takes priority over settings (newer save location)
    return { ...defaults, ...s, ...ip };
  },

  /** Convert American odds to decimal */
  toDecimal(odds) {
    const n = parseInt(odds);
    if (isNaN(n)) return 1.91; // default -110
    return n > 0 ? (n / 100) + 1 : (100 / Math.abs(n)) + 1;
  },

  /**
   * Calculate recommended bet size for a single pick.
   * @param {number} confidence  Model confidence (0-100)
   * @param {number|string} odds American odds (-110, +150, etc)
   * @returns {{ amount: number, units: number, method: string, edge: number, ev: number }}
   */
  calculate(confidence, odds) {
    const s = this.getSettings();

    // If Kelly is off or no bankroll, use fixed unit sizing
    if (s.kellyFraction === 'off' || !s.bankroll) {
      return { amount: s.unitSize, units: 1, method: 'fixed', edge: 0, ev: 0 };
    }

    const decOdds = this.toDecimal(odds);
    const impliedProb = 1 / decOdds;
    const ourProb = confidence / 100;
    const edge = ourProb - impliedProb;

    // No positive edge — return zero-bet
    if (edge <= 0) {
      return { amount: 0, units: 0, method: 'no-edge', edge: edge * 100, ev: 0 };
    }

    // Kelly formula: f* = (bp - q) / b
    const b = decOdds - 1;
    const kellyPct = (b * ourProb - (1 - ourProb)) / b;

    // Apply fraction
    const fractions = { quarter: 0.25, half: 0.5, full: 1.0 };
    const frac = fractions[s.kellyFraction] || 0.5;
    let betPct = kellyPct * frac;

    // Cap at maxBetPct
    betPct = Math.min(betPct, s.maxBetPct / 100);

    // Calculate dollar amount
    let amount = Math.round(s.bankroll * betPct);
    amount = Math.max(amount, 5); // minimum $5
    amount = Math.ceil(amount / 5) * 5; // round up to $5

    const units = parseFloat((amount / s.unitSize).toFixed(1));

    // Expected value per bet
    const toWin = amount * b;
    const ev = (ourProb * toWin) - ((1 - ourProb) * amount);

    return {
      amount,
      units,
      method: s.kellyFraction,
      edge: edge * 100,
      ev: parseFloat(ev.toFixed(2)),
    };
  },

  /**
   * Get sizing tier label for display.
   * @returns {'strong'|'good'|'lean'|'skip'}
   */
  tier(confidence, edge) {
    if (confidence >= 70 && edge >= 5) return 'strong';
    if (confidence >= 60 && edge >= 2) return 'good';
    if (confidence >= 55 && edge > 0) return 'lean';
    return 'skip';
  },
};
