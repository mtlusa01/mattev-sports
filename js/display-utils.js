// ============================================
// DISPLAY FORMATTER — Global display mode utility
// Formats monetary values as dollars, units, or both
// ============================================

var DisplayFormatter = {
  mode: 'dollars',   // 'dollars' | 'units' | 'both'
  unitSize: 10,

  /** Initialize from user profile → localStorage → defaults */
  init: function() {
    // Unit size: profile → localStorage → default
    if (typeof userProfile !== 'undefined' && userProfile &&
        userProfile.investmentProfile && userProfile.investmentProfile.unitSize) {
      this.unitSize = userProfile.investmentProfile.unitSize;
    } else if (typeof userProfile !== 'undefined' && userProfile &&
               userProfile.settings && userProfile.settings.unitSize) {
      this.unitSize = userProfile.settings.unitSize;
    } else {
      this.unitSize = this._lsUnitSize();
    }

    // Display mode: profile → localStorage → default
    if (typeof userProfile !== 'undefined' && userProfile &&
        userProfile.investmentProfile && userProfile.investmentProfile.displayMode) {
      this.mode = userProfile.investmentProfile.displayMode;
    } else {
      this.mode = this._lsDisplayMode();
    }
  },

  // ── Public formatters ──

  /**
   * Absolute amounts (bankroll, portfolio, goals).
   * opts.alwaysDollars: true → ignores mode, always shows dollars.
   */
  money: function(dollars, opts) {
    opts = opts || {};
    if (opts.alwaysDollars || this.mode === 'dollars') {
      return this._fmtDollar(dollars);
    }
    if (this.mode === 'units') {
      return this._fmtUnit(this._toUnits(dollars));
    }
    // both
    return this._fmtDollar(dollars) + ' (' + this._fmtUnit(this._toUnits(dollars)) + ')';
  },

  /** Bet sizing: $50 / 5.0u / $50 (5.0u) */
  stake: function(dollars) {
    if (this.mode === 'dollars') return this._fmtDollar(dollars);
    if (this.mode === 'units') return this._fmtUnit(this._toUnits(dollars));
    return this._fmtDollar(dollars) + ' (' + this._fmtUnit(this._toUnits(dollars)) + ')';
  },

  /** Signed P&L: +$500 / +50.00u / +$500 (+50.00u) */
  pnl: function(dollars) {
    if (this.mode === 'dollars') return this._fmtSignedDollar(dollars);
    if (this.mode === 'units') return this._fmtSignedUnit(this._toUnits(dollars));
    return this._fmtSignedDollar(dollars) + ' (' + this._fmtSignedUnit(this._toUnits(dollars)) + ')';
  },

  /** Compact P&L for tight spaces (calendar cells). Returns {text, title}. */
  compactPnl: function(dollars) {
    var primary, alt;
    if (this.mode === 'dollars') {
      primary = this._fmtSignedDollar(dollars);
      alt = this._fmtSignedUnit(this._toUnits(dollars));
    } else if (this.mode === 'units') {
      primary = this._fmtSignedUnit(this._toUnits(dollars));
      alt = this._fmtSignedDollar(dollars);
    } else {
      // both: show dollars as primary, units as tooltip
      primary = this._fmtSignedDollar(dollars);
      alt = this._fmtSignedUnit(this._toUnits(dollars));
    }
    return { text: primary, title: alt };
  },

  /** Compact unsigned for tight spaces. Returns {text, title}. */
  compact: function(dollars) {
    var primary, alt;
    if (this.mode === 'dollars') {
      primary = this._fmtDollar(dollars);
      alt = this._fmtUnit(this._toUnits(dollars));
    } else if (this.mode === 'units') {
      primary = this._fmtUnit(this._toUnits(dollars));
      alt = this._fmtDollar(dollars);
    } else {
      primary = this._fmtDollar(dollars);
      alt = this._fmtUnit(this._toUnits(dollars));
    }
    return { text: primary, title: alt };
  },

  // ── Private helpers ──

  _toUnits: function(dollars) {
    return this.unitSize > 0 ? dollars / this.unitSize : 0;
  },

  _fmtDollar: function(amount) {
    var rounded = Math.round(amount * 100) / 100;
    var abs = Math.abs(rounded);
    if (abs >= 100) return '$' + Math.round(abs).toLocaleString();
    return '$' + abs.toFixed(2);
  },

  _fmtSignedDollar: function(amount) {
    var rounded = Math.round(amount * 100) / 100;
    var abs = Math.abs(rounded);
    var val = abs >= 100 ? Math.round(abs).toLocaleString() : abs.toFixed(2);
    return (rounded >= 0 ? '+$' : '-$') + val;
  },

  _fmtUnit: function(units) {
    return Math.abs(units).toFixed(2) + 'u';
  },

  _fmtSignedUnit: function(units) {
    var rounded = Math.round(units * 100) / 100;
    return (rounded >= 0 ? '+' : '-') + Math.abs(rounded).toFixed(2) + 'u';
  },

  _lsUnitSize: function() {
    try {
      var s = JSON.parse(localStorage.getItem('efe_user_settings'));
      return (s && s.unit_size) ? s.unit_size : 10;
    } catch (e) { return 10; }
  },

  _lsDisplayMode: function() {
    try {
      var s = JSON.parse(localStorage.getItem('efe_user_settings'));
      return (s && s.display_mode) ? s.display_mode : 'dollars';
    } catch (e) { return 'dollars'; }
  }
};
