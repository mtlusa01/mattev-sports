// ============================================
// BET STORAGE — Unified data access layer
// Firestore as primary (logged in), localStorage as cache/fallback
// ============================================

const BetStorage = {
  LS_KEY: 'efe_tracked_bets',
  _cache: null,
  _syncTimer: null,
  _syncing: false,

  /** Synchronous read — returns cached/localStorage bets */
  getBets() {
    if (this._cache !== null) return this._cache;
    try { this._cache = JSON.parse(localStorage.getItem(this.LS_KEY)) || []; }
    catch (e) { this._cache = []; }
    return this._cache;
  },

  /** Write bets — updates cache + localStorage + Firestore (debounced) */
  saveBets(bets, opts) {
    opts = opts || {};
    this._cache = bets;
    localStorage.setItem(this.LS_KEY, JSON.stringify(bets));
    if (!opts.skipSync) this._debouncedSync();
  },

  /** Add a single bet (avoids duplicates by ID) */
  addBet(bet) {
    var bets = this.getBets();
    if (!bet.id) bet.id = 'bet_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    if (!bets.some(function(b) { return b.id === bet.id; })) {
      bets.push(bet);
      this.saveBets(bets);
    }
    return bet;
  },

  /** Remove a bet by ID */
  removeBet(betId) {
    var bets = this.getBets().filter(function(b) { return b.id !== betId; });
    this.saveBets(bets);
    return bets;
  },

  /** Update a bet by ID (merge fields) */
  updateBet(betId, updates) {
    var bets = this.getBets();
    var bet = bets.find(function(b) { return b.id === betId; });
    if (bet) {
      Object.assign(bet, updates);
      this.saveBets(bets);
    }
    return bet;
  },

  /** Clear all bets (account delete / data reset) */
  clearAll() {
    this._cache = [];
    localStorage.removeItem(this.LS_KEY);
    this._syncToCloud();
  },

  // ── Cloud Sync ──────────────────────────────

  _debouncedSync() {
    if (this._syncTimer) clearTimeout(this._syncTimer);
    this._syncTimer = setTimeout(function() { BetStorage._syncToCloud(); }, 1500);
  },

  _syncToCloud: async function() {
    var user = (typeof firebase !== 'undefined') && firebase.auth().currentUser;
    if (!user || this._syncing) return;
    this._syncing = true;
    try {
      var bets = this.getBets();
      // Ensure all bets have IDs
      for (var i = 0; i < bets.length; i++) {
        if (!bets[i].id) bets[i].id = 'bet_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
      }
      await firebase.firestore().collection('users').doc(user.uid).update({
        trackedBets: bets,
        lastBetSync: firebase.firestore.FieldValue.serverTimestamp()
      });
      console.log('[BetStorage] Synced', bets.length, 'bets to cloud');
    } catch (err) {
      // Retry with set+merge if update fails (field doesn't exist yet)
      try {
        await firebase.firestore().collection('users').doc(user.uid).set({
          trackedBets: this.getBets(),
          lastBetSync: firebase.firestore.FieldValue.serverTimestamp()
        }, { merge: true });
        console.log('[BetStorage] Synced (retry)', this.getBets().length, 'bets to cloud');
      } catch (retryErr) {
        console.error('[BetStorage] Sync failed:', retryErr);
      }
    } finally {
      this._syncing = false;
    }
  },

  /** Pull bets from Firestore, merge with local, update cache.
   *  Called once on auth state change (login). */
  pullFromCloud: async function() {
    var user = (typeof firebase !== 'undefined') && firebase.auth().currentUser;
    if (!user) return;
    try {
      var doc = await firebase.firestore().collection('users').doc(user.uid).get();
      if (!doc.exists) return;
      var cloudBets = doc.data().trackedBets || [];

      // Migration: check for old subcollection
      try {
        var oldRef = firebase.firestore().collection('users').doc(user.uid).collection('bets');
        var oldSnap = await oldRef.get();
        if (!oldSnap.empty) {
          var oldBets = [];
          oldSnap.forEach(function(d) { oldBets.push(d.data()); });
          cloudBets = cloudBets.concat(oldBets);
          // Delete old subcollection
          var batch = firebase.firestore().batch();
          oldSnap.forEach(function(d) { batch.delete(d.ref); });
          await batch.commit();
          console.log('[BetStorage] Migrated', oldBets.length, 'bets from old subcollection');
        }
      } catch (e) { /* no old bets or no permission — OK */ }

      // Merge: cloud wins for same ID, keep unique locals
      var local = this.getBets();
      var merged = this._mergeBets(local, cloudBets);
      this.saveBets(merged, { skipSync: false });
      this._cache = merged;
      console.log('[BetStorage] Pulled from cloud:', cloudBets.length, 'cloud +', local.length, 'local =', merged.length, 'merged');
    } catch (err) {
      console.error('[BetStorage] Pull failed:', err);
    }
  },

  /** Merge two bet arrays by ID (second array wins on conflict) */
  _mergeBets: function(primary, secondary) {
    var map = new Map();
    var i;
    for (i = 0; i < primary.length; i++) {
      if (primary[i].id) map.set(primary[i].id, primary[i]);
    }
    for (i = 0; i < secondary.length; i++) {
      if (secondary[i].id) map.set(secondary[i].id, secondary[i]);
    }
    // Include bets without IDs from both
    var noId = primary.concat(secondary).filter(function(b) { return !b.id; });
    return Array.from(map.values()).concat(noId);
  }
};
