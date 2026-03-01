// ============================================
// EF ANALYST — AI Chat Widget
// Edge Factor Elite — chat-widget.js
// ============================================
(function () {
  'use strict';

  // ── Section A: Constants & State ──────────────────────────────────
  const WORKER_URL = 'https://ef-chat-proxy.vesperkicks.workers.dev';
  const RAW_BASE = 'https://raw.githubusercontent.com/mtlusa01/mattev-sports/main/';
  const DATA_URLS = {
    results:            RAW_BASE + 'results.json',
    nhl_results:        RAW_BASE + 'nhl_results.json',
    ncaab_results:      RAW_BASE + 'ncaab_results.json',
    projections:        RAW_BASE + 'projections.json',
    game_projections:   RAW_BASE + 'game_projections.json',
    nhl_game_projections: RAW_BASE + 'nhl_game_projections.json',
    ncaab_projections:  RAW_BASE + 'ncaab_projections.json',
  };

  let chatOpen = false;
  let messages = [];
  let cachedData = null;
  let chatUser = null;
  let chatProfile = null;
  let isLoading = false;
  const MAX_FREE_MESSAGES = 20;
  const RATE_KEY_PREFIX = 'ef_chat_count_';

  // DOM refs filled by buildDOM
  let els = {};

  // ── Section B: Inject Styles ──────────────────────────────────────
  function injectStyles() {
    const css = `
      .ef-chat-fab {
        position: fixed; bottom: 24px; right: 24px; width: 56px; height: 56px;
        border-radius: 50%; border: none; cursor: pointer; z-index: 10000;
        background: linear-gradient(135deg, #00d4ff, #0ea5e9);
        box-shadow: 0 4px 20px rgba(0,212,255,0.35);
        display: flex; align-items: center; justify-content: center;
        transition: transform 0.2s, box-shadow 0.2s;
        animation: ef-chat-pulse 2.5s ease-in-out infinite;
      }
      .ef-chat-fab:hover {
        transform: scale(1.08);
        box-shadow: 0 6px 28px rgba(0,212,255,0.5);
      }
      .ef-chat-fab svg { width: 26px; height: 26px; fill: #080c14; }
      .ef-chat-fab .ef-chat-badge {
        position: absolute; top: 6px; right: 6px; width: 10px; height: 10px;
        border-radius: 50%; background: #22c55e; border: 2px solid #080c14;
      }
      @keyframes ef-chat-pulse {
        0%, 100% { box-shadow: 0 4px 20px rgba(0,212,255,0.35); }
        50% { box-shadow: 0 4px 28px rgba(0,212,255,0.55); }
      }

      .ef-chat-panel {
        position: fixed; bottom: 92px; right: 24px; width: 400px;
        max-height: 70vh; border-radius: 14px; z-index: 10001;
        background: #0c1220; border: 1px solid rgba(0,212,255,0.18);
        box-shadow: 0 8px 40px rgba(0,0,0,0.5), 0 0 20px rgba(0,212,255,0.08);
        display: flex; flex-direction: column;
        transform: translateY(20px); opacity: 0; pointer-events: none;
        transition: transform 0.25s ease, opacity 0.25s ease;
      }
      .ef-chat-panel.open {
        transform: translateY(0); opacity: 1; pointer-events: auto;
      }

      .ef-chat-header {
        display: flex; align-items: center; gap: 10px;
        padding: 14px 16px; border-bottom: 1px solid rgba(148,163,184,0.1);
        background: #111827; border-radius: 14px 14px 0 0;
      }
      .ef-chat-avatar {
        width: 32px; height: 32px; border-radius: 50%;
        background: linear-gradient(135deg, #00d4ff, #0ea5e9);
        display: flex; align-items: center; justify-content: center;
        font-size: 14px; font-weight: 700; color: #080c14; flex-shrink: 0;
      }
      .ef-chat-header-title {
        flex: 1; font-family: 'DM Sans', sans-serif;
        font-weight: 600; font-size: 15px; color: #f1f5f9;
      }
      .ef-chat-header-sub {
        font-size: 11px; color: #64748b; font-weight: 400;
      }
      .ef-chat-close {
        background: none; border: none; cursor: pointer;
        color: #64748b; font-size: 20px; padding: 4px 8px; line-height: 1;
        border-radius: 6px; transition: color 0.15s, background 0.15s;
      }
      .ef-chat-close:hover { color: #f1f5f9; background: rgba(148,163,184,0.1); }

      .ef-chat-messages {
        flex: 1; overflow-y: auto; padding: 16px;
        display: flex; flex-direction: column; gap: 12px;
        min-height: 180px; max-height: calc(70vh - 150px);
      }
      .ef-chat-messages::-webkit-scrollbar { width: 5px; }
      .ef-chat-messages::-webkit-scrollbar-track { background: transparent; }
      .ef-chat-messages::-webkit-scrollbar-thumb {
        background: rgba(148,163,184,0.15); border-radius: 10px;
      }

      .ef-chat-msg {
        max-width: 85%; padding: 10px 14px; border-radius: 12px;
        font-family: 'DM Sans', sans-serif; font-size: 13.5px;
        line-height: 1.55; word-wrap: break-word;
      }
      .ef-chat-msg.user {
        align-self: flex-end; background: rgba(0,212,255,0.12);
        color: #e2e8f0; border-bottom-right-radius: 4px;
      }
      .ef-chat-msg.assistant {
        align-self: flex-start; background: #111827;
        color: #e2e8f0; border-left: 3px solid #00d4ff;
        border-bottom-left-radius: 4px;
      }
      .ef-chat-msg.assistant strong { color: #00d4ff; }
      .ef-chat-msg.assistant code {
        background: rgba(0,212,255,0.08); padding: 1px 5px;
        border-radius: 4px; font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
      }
      .ef-chat-msg.assistant ul, .ef-chat-msg.assistant ol {
        margin: 6px 0; padding-left: 18px;
      }
      .ef-chat-msg.assistant li { margin-bottom: 3px; }
      .ef-chat-msg.system {
        align-self: center; background: rgba(0,212,255,0.06);
        color: #94a3b8; font-size: 12px; text-align: center;
        border-radius: 8px; max-width: 95%;
      }

      .ef-chat-typing {
        align-self: flex-start; display: none; align-items: center;
        gap: 5px; padding: 12px 16px; background: #111827;
        border-radius: 12px; border-left: 3px solid #00d4ff;
      }
      .ef-chat-typing.active { display: flex; }
      .ef-chat-typing span {
        width: 7px; height: 7px; border-radius: 50%; background: #00d4ff;
        animation: ef-dot-pulse 1.2s ease-in-out infinite;
      }
      .ef-chat-typing span:nth-child(2) { animation-delay: 0.15s; }
      .ef-chat-typing span:nth-child(3) { animation-delay: 0.3s; }
      @keyframes ef-dot-pulse {
        0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
        30% { opacity: 1; transform: scale(1); }
      }

      .ef-chat-suggestions {
        display: flex; gap: 8px; padding: 8px 16px;
        overflow-x: auto; flex-wrap: nowrap;
      }
      .ef-chat-suggestions::-webkit-scrollbar { height: 0; }
      .ef-chat-suggestion {
        flex-shrink: 0; padding: 6px 12px; border-radius: 20px;
        background: rgba(0,212,255,0.08); border: 1px solid rgba(0,212,255,0.15);
        color: #94a3b8; font-family: 'DM Sans', sans-serif; font-size: 12px;
        cursor: pointer; white-space: nowrap; transition: all 0.15s;
      }
      .ef-chat-suggestion:hover {
        background: rgba(0,212,255,0.15); color: #00d4ff;
        border-color: rgba(0,212,255,0.3);
      }

      .ef-chat-input-row {
        display: flex; gap: 8px; padding: 12px 16px;
        border-top: 1px solid rgba(148,163,184,0.1);
        background: #111827; border-radius: 0 0 14px 14px;
      }
      .ef-chat-input {
        flex: 1; background: rgba(148,163,184,0.06); border: 1px solid rgba(148,163,184,0.1);
        border-radius: 10px; padding: 10px 14px; color: #f1f5f9;
        font-family: 'DM Sans', sans-serif; font-size: 13.5px;
        outline: none; transition: border-color 0.15s;
      }
      .ef-chat-input::placeholder { color: #475569; }
      .ef-chat-input:focus { border-color: rgba(0,212,255,0.3); }
      .ef-chat-send {
        background: linear-gradient(135deg, #00d4ff, #0ea5e9);
        border: none; border-radius: 10px; width: 40px; cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        transition: opacity 0.15s;
      }
      .ef-chat-send:disabled { opacity: 0.4; cursor: default; }
      .ef-chat-send svg { width: 18px; height: 18px; fill: #080c14; }

      @media (max-width: 600px) {
        .ef-chat-panel {
          bottom: 0; right: 0; left: 0; width: 100%;
          max-height: 100vh; height: 100vh;
          border-radius: 0; transform: translateY(100%);
        }
        .ef-chat-panel.open { transform: translateY(0); }
        .ef-chat-header { border-radius: 0; }
        .ef-chat-input-row { border-radius: 0; }
        .ef-chat-messages { max-height: calc(100vh - 150px); }
        .ef-chat-fab { bottom: 16px; right: 16px; }
      }
    `;
    var style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
  }

  // ── Section C: Build DOM ──────────────────────────────────────────
  var SUGGESTIONS = [
    'How did I do this week?',
    'Which model is performing best?',
    "Analyze today's top picks",
    "What's my ROI this month?",
    'Show my win rate by sport',
    'Which confidence level hits most?',
  ];

  function buildDOM() {
    // FAB
    var fab = document.createElement('button');
    fab.className = 'ef-chat-fab';
    fab.style.display = 'none';
    fab.setAttribute('aria-label', 'Open EF Analyst chat');
    fab.innerHTML =
      '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/><path d="M7 9h2v2H7zm4 0h2v2h-2zm4 0h2v2h-2z"/></svg>' +
      '<span class="ef-chat-badge"></span>';

    // Panel
    var panel = document.createElement('div');
    panel.className = 'ef-chat-panel';
    panel.innerHTML =
      '<div class="ef-chat-header">' +
        '<div class="ef-chat-avatar">EF</div>' +
        '<div><div class="ef-chat-header-title">EF Analyst</div>' +
        '<div class="ef-chat-header-sub">AI-powered betting assistant</div></div>' +
        '<button class="ef-chat-close">&times;</button>' +
      '</div>' +
      '<div class="ef-chat-messages"></div>' +
      '<div class="ef-chat-typing"><span></span><span></span><span></span></div>' +
      '<div class="ef-chat-suggestions">' +
        SUGGESTIONS.map(function (s) {
          return '<button class="ef-chat-suggestion">' + s + '</button>';
        }).join('') +
      '</div>' +
      '<div class="ef-chat-input-row">' +
        '<input class="ef-chat-input" placeholder="Ask about your picks, stats, or strategy..." />' +
        '<button class="ef-chat-send" disabled><svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>' +
      '</div>';

    document.body.appendChild(fab);
    document.body.appendChild(panel);

    els.fab = fab;
    els.panel = panel;
    els.msgArea = panel.querySelector('.ef-chat-messages');
    els.typing = panel.querySelector('.ef-chat-typing');
    els.suggestions = panel.querySelector('.ef-chat-suggestions');
    els.input = panel.querySelector('.ef-chat-input');
    els.send = panel.querySelector('.ef-chat-send');
    els.close = panel.querySelector('.ef-chat-close');

    // Events
    fab.addEventListener('click', togglePanel);
    els.close.addEventListener('click', togglePanel);
    els.send.addEventListener('click', handleSend);
    els.input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
    });
    els.input.addEventListener('input', function () {
      els.send.disabled = !els.input.value.trim();
    });
    panel.querySelectorAll('.ef-chat-suggestion').forEach(function (btn) {
      btn.addEventListener('click', function () { handleSuggestionClick(btn.textContent); });
    });
  }

  // ── Section D: Auth Wiring ────────────────────────────────────────
  function wireAuth() {
    var poll = setInterval(function () {
      if (typeof firebase !== 'undefined' && firebase.auth) {
        clearInterval(poll);
        firebase.auth().onAuthStateChanged(function (user) {
          if (user) {
            chatUser = user;
            chatProfile = (typeof userProfile !== 'undefined' && userProfile) ? userProfile : null;
            els.fab.style.display = 'flex';
            // If profile not ready yet, poll briefly
            if (!chatProfile) {
              var pp = setInterval(function () {
                if (typeof userProfile !== 'undefined' && userProfile) {
                  chatProfile = userProfile;
                  clearInterval(pp);
                }
              }, 200);
              setTimeout(function () { clearInterval(pp); }, 5000);
            }
            loadChatHistory();
          } else {
            chatUser = null;
            chatProfile = null;
            els.fab.style.display = 'none';
            if (chatOpen) togglePanel();
          }
        });
      }
    }, 100);
    setTimeout(function () { clearInterval(poll); }, 10000);
  }

  // ── Section E: Context Gathering ──────────────────────────────────
  function fetchAllData() {
    if (cachedData) return Promise.resolve(cachedData);
    var bust = '?v=' + Date.now();
    var keys = Object.keys(DATA_URLS);
    var fetches = keys.map(function (k) {
      return fetch(DATA_URLS[k] + bust).then(function (r) {
        return r.ok ? r.json() : null;
      }).catch(function () { return null; });
    });
    return Promise.all(fetches).then(function (results) {
      cachedData = {};
      keys.forEach(function (k, i) { cachedData[k] = results[i]; });
      return cachedData;
    });
  }

  // ── Section F: System Prompt Builder ──────────────────────────────
  function buildSystemPrompt() {
    var today = new Date().toISOString().slice(0, 10);
    var parts = [];

    // Identity
    parts.push(
      'You are EF Analyst, the AI assistant for Edge Factor Elite — a sports betting analytics platform. ' +
      'You help users understand their betting performance, analyze today\'s model picks, and discuss strategy. ' +
      'Be concise, data-driven, and confident. Use the data provided below as your knowledge base. ' +
      'Do not make up statistics — only reference numbers from the data provided. ' +
      'If you don\'t have data for something, say so. Today is ' + today + '.'
    );

    // User profile
    if (chatProfile && chatProfile.settings) {
      var s = chatProfile.settings;
      var profileParts = [];
      if (s.bankroll) profileParts.push('Bankroll: $' + s.bankroll);
      if (s.unitSize) profileParts.push('Unit size: $' + s.unitSize);
      if (s.riskTolerance) profileParts.push('Risk tolerance: ' + s.riskTolerance);
      if (s.kellyFraction) profileParts.push('Kelly fraction: ' + s.kellyFraction);
      if (s.monthlyTarget) profileParts.push('Monthly target: $' + s.monthlyTarget);
      if (s.defaultSport) profileParts.push('Default sport: ' + s.defaultSport.toUpperCase());
      if (s.minConfidence) profileParts.push('Min confidence: ' + s.minConfidence + '%');
      if (profileParts.length) {
        parts.push('\n## User Settings\n' + profileParts.join(' | '));
      }
    }

    if (!cachedData) return parts.join('\n');

    // Platform performance
    var perfLines = [];
    var sportResults = [
      { key: 'results', label: 'NBA' },
      { key: 'nhl_results', label: 'NHL' },
      { key: 'ncaab_results', label: 'NCAAB' },
    ];
    sportResults.forEach(function (sr) {
      var d = cachedData[sr.key];
      if (!d || !d.allTime) return;
      var cats = Object.keys(d.allTime);
      var lines = cats.map(function (c) {
        var o = d.allTime[c];
        return c + ': ' + o.wins + '-' + o.losses + ' (' + o.pct + '%) ROI ' + o.roi + '%';
      });
      perfLines.push(sr.label + ' — ' + lines.join(', '));
    });
    if (perfLines.length) {
      parts.push('\n## Platform Performance (All-Time)\n' + perfLines.join('\n'));
    }

    // Yesterday's record
    var nbaRes = cachedData.results;
    if (nbaRes && nbaRes.days && nbaRes.days.length) {
      var yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
      var yd = nbaRes.days.find(function (d) { return d.date === yesterday; });
      if (yd) {
        var ydParts = [];
        ['props', 'spreads', 'totals', 'moneylines'].forEach(function (c) {
          if (yd[c] && yd[c].record) ydParts.push(c + ': ' + yd[c].record);
        });
        if (ydParts.length) {
          parts.push('\n## Yesterday\'s Record (' + yesterday + ')\n' + ydParts.join(' | '));
        }
      }
    }

    // Today's picks summary
    var proj = cachedData.projections;
    if (proj && proj.projections && proj.projections.length) {
      var sorted = proj.projections.slice().sort(function (a, b) { return (b.ev || 0) - (a.ev || 0); });
      var top = sorted.slice(0, 8);
      var pickLines = top.map(function (p) {
        return p.player + ' ' + p.prop + ' ' + p.direction + ' ' + p.line +
          ' (proj: ' + p.projection + ', conf: ' + p.confidence + '%, EV: ' + p.ev + ')';
      });
      parts.push(
        '\n## Today\'s Props (' + proj.projections.length + ' total)\nTop by EV:\n' +
        pickLines.join('\n')
      );
    }

    // Game picks
    var gp = cachedData.game_projections;
    if (gp && gp.games && gp.games.length) {
      var notable = gp.games.filter(function (g) {
        return g.spread_conf > 60 || g.total_conf > 60 || (g.ml_conf && g.ml_conf > 60);
      });
      if (notable.length) {
        var gpLines = notable.slice(0, 6).map(function (g) {
          var p = [];
          if (g.spread_conf > 55) p.push('Spread: ' + g.spread_pick + ' (' + g.spread_conf + '%)');
          if (g.total_conf > 55) p.push('Total: ' + g.total_pick + ' (' + g.total_conf + '%)');
          if (g.ml_pick && g.ml_conf > 55) p.push('ML: ' + g.ml_pick + ' (' + g.ml_conf + '%)');
          return g.away_team + ' @ ' + g.home_team + ' — ' + p.join(', ');
        });
        parts.push('\n## Notable NBA Games Today\n' + gpLines.join('\n'));
      }
    }

    // NHL game picks
    var nhlGp = cachedData.nhl_game_projections;
    if (nhlGp && nhlGp.games && nhlGp.games.length) {
      var nhlNotable = nhlGp.games.filter(function (g) {
        return g.spread_conf > 58 || g.total_conf > 58 || (g.ml_conf && g.ml_conf > 58);
      });
      if (nhlNotable.length) {
        var nhlLines = nhlNotable.slice(0, 5).map(function (g) {
          var p = [];
          if (g.spread_pick) p.push('Puck: ' + g.spread_pick + ' (' + (g.spread_conf || '') + '%)');
          if (g.total_pick) p.push('Total: ' + g.total_pick + ' (' + (g.total_conf || '') + '%)');
          if (g.ml_pick) p.push('ML: ' + g.ml_pick + ' (' + (g.ml_conf || '') + '%)');
          return g.away_team + ' @ ' + g.home_team + ' — ' + p.join(', ');
        });
        parts.push('\n## Notable NHL Games Today\n' + nhlLines.join('\n'));
      }
    }

    // NCAAB picks
    var ncaabP = cachedData.ncaab_projections;
    if (ncaabP && ncaabP.games && ncaabP.games.length) {
      var ncaabNotable = ncaabP.games.filter(function (g) {
        return g.spread_conf > 62 || g.total_conf > 62;
      });
      if (ncaabNotable.length) {
        var ncaabLines = ncaabNotable.slice(0, 5).map(function (g) {
          var p = [];
          if (g.spread_pick) p.push('Spread: ' + g.spread_pick + ' (' + (g.spread_conf || '') + '%)');
          if (g.total_pick) p.push('Total: ' + g.total_pick + ' (' + (g.total_conf || '') + '%)');
          return g.away_team + ' @ ' + g.home_team + ' — ' + p.join(', ');
        });
        parts.push('\n## Notable NCAAB Games Today\n' + ncaabLines.join('\n'));
      }
    }

    // Tracked bets
    try {
      var raw = localStorage.getItem('efe_tracked_bets');
      if (raw) {
        var bets = JSON.parse(raw);
        if (Array.isArray(bets) && bets.length) {
          var pending = bets.filter(function (b) { return b.result === 'pending' || !b.result; });
          var wins = bets.filter(function (b) { return b.result === 'win'; });
          var losses = bets.filter(function (b) { return b.result === 'loss'; });
          parts.push(
            '\n## User\'s Tracked Bets\nTotal: ' + bets.length +
            ' | Pending: ' + pending.length +
            ' | Won: ' + wins.length + ' | Lost: ' + losses.length
          );
        }
      }
    } catch (e) { /* ignore */ }

    return parts.join('\n');
  }

  // ── Section G: Auto-Insight ───────────────────────────────────────
  function computeAutoInsight() {
    var today = new Date().toISOString().slice(0, 10);
    var key = 'ef_chat_insight_date';
    if (localStorage.getItem(key) === today) return null;
    localStorage.setItem(key, today);

    if (!cachedData) return null;
    var lines = [];

    // Yesterday's combined record
    var yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    var totalW = 0, totalL = 0;
    ['results', 'nhl_results', 'ncaab_results'].forEach(function (k) {
      var d = cachedData[k];
      if (!d || !d.days || !d.days.length) return;
      var yd = d.days.find(function (day) { return day.date === yesterday; });
      if (!yd) return;
      ['props', 'spreads', 'totals', 'moneylines'].forEach(function (c) {
        if (yd[c]) { totalW += (yd[c].wins || 0); totalL += (yd[c].losses || 0); }
      });
    });
    if (totalW + totalL > 0) {
      var pct = ((totalW / (totalW + totalL)) * 100).toFixed(1);
      lines.push('Yesterday: **' + totalW + '-' + totalL + '** (' + pct + '%) across all sports');
    }

    // Today's pick count
    var pickCount = 0;
    if (cachedData.projections && cachedData.projections.projections)
      pickCount += cachedData.projections.projections.length;
    ['game_projections', 'nhl_game_projections', 'ncaab_projections'].forEach(function (k) {
      if (cachedData[k] && cachedData[k].games) pickCount += cachedData[k].games.length;
    });
    if (pickCount > 0) lines.push('Today: **' + pickCount + ' picks** loaded across all models');

    // Top model streak
    var bestModel = null, bestROI = -999;
    ['results', 'nhl_results', 'ncaab_results'].forEach(function (k) {
      var d = cachedData[k];
      if (!d || !d.allTime) return;
      var label = k === 'results' ? 'NBA' : k === 'nhl_results' ? 'NHL' : 'NCAAB';
      Object.keys(d.allTime).forEach(function (c) {
        var o = d.allTime[c];
        if (o.roi > bestROI) { bestROI = o.roi; bestModel = label + ' ' + c; }
      });
    });
    if (bestModel && bestROI > 0) {
      lines.push('Top model: **' + bestModel + '** at ' + bestROI + '% ROI');
    }

    return lines.length ? lines.join('\n') : null;
  }

  // ── Section H: Rate Limiting ──────────────────────────────────────
  function getRateKey() {
    return RATE_KEY_PREFIX + new Date().toISOString().slice(0, 10);
  }

  function checkRateLimit() {
    if (chatProfile && chatProfile.role === 'admin') return true;
    var count = parseInt(localStorage.getItem(getRateKey()) || '0', 10);
    return count < MAX_FREE_MESSAGES;
  }

  function getRateCount() {
    return parseInt(localStorage.getItem(getRateKey()) || '0', 10);
  }

  function incrementRateCount() {
    var count = getRateCount() + 1;
    localStorage.setItem(getRateKey(), String(count));
    updatePlaceholder();
  }

  function updatePlaceholder() {
    if (chatProfile && chatProfile.role === 'admin') return;
    var remaining = MAX_FREE_MESSAGES - getRateCount();
    if (remaining <= 5 && remaining > 0) {
      els.input.placeholder = remaining + ' messages remaining today...';
    } else if (remaining <= 0) {
      els.input.placeholder = 'Daily limit reached. Resets tomorrow.';
      els.input.disabled = true;
      els.send.disabled = true;
    }
  }

  // ── Section I: API Call ───────────────────────────────────────────
  function sendToAPI(userMessage) {
    if (!checkRateLimit()) {
      return Promise.resolve('You\'ve reached your daily message limit (' + MAX_FREE_MESSAGES + '). Your limit resets tomorrow.');
    }

    return fetchAllData().then(function () {
      var apiMessages = messages.filter(function (m) {
        return m.role === 'user' || m.role === 'assistant';
      }).map(function (m) {
        return { role: m.role, content: m.content };
      });

      var body = {
        model: 'claude-sonnet-4-20250514',
        max_tokens: 1024,
        system: buildSystemPrompt(),
        messages: apiMessages,
      };

      return fetch(WORKER_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(function (r) {
        if (!r.ok) throw new Error('API error: ' + r.status);
        return r.json();
      }).then(function (data) {
        incrementRateCount();
        if (data.content && data.content[0] && data.content[0].text) {
          return data.content[0].text;
        }
        throw new Error('Unexpected response format');
      });
    }).catch(function (err) {
      console.error('EF Chat error:', err);
      return 'Sorry, I couldn\'t process that request. Please try again in a moment.';
    });
  }

  // ── Section J: Markdown Renderer ──────────────────────────────────
  function renderMarkdown(text) {
    if (!text) return '';
    var html = text
      // Escape HTML
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      // Code (before bold/italic)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      // Bold
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // Italic
      .replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Lists — process line by line
    var lines = html.split('\n');
    var result = [];
    var inUl = false, inOl = false;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var ulMatch = line.match(/^[\-\*]\s+(.+)/);
      var olMatch = line.match(/^\d+\.\s+(.+)/);
      if (ulMatch) {
        if (!inUl) { result.push('<ul>'); inUl = true; }
        result.push('<li>' + ulMatch[1] + '</li>');
      } else if (olMatch) {
        if (!inOl) { result.push('<ol>'); inOl = true; }
        result.push('<li>' + olMatch[1] + '</li>');
      } else {
        if (inUl) { result.push('</ul>'); inUl = false; }
        if (inOl) { result.push('</ol>'); inOl = false; }
        result.push(line);
      }
    }
    if (inUl) result.push('</ul>');
    if (inOl) result.push('</ol>');

    return result.join('<br>').replace(/<br><ul>/g, '<ul>').replace(/<\/ul><br>/g, '</ul>')
      .replace(/<br><ol>/g, '<ol>').replace(/<\/ol><br>/g, '</ol>')
      .replace(/<br><li>/g, '<li>').replace(/<\/li><br>/g, '</li>');
  }

  // ── Section K: UI Actions ─────────────────────────────────────────
  function togglePanel() {
    chatOpen = !chatOpen;
    if (chatOpen) {
      els.panel.classList.add('open');
      els.input.focus();
      // Auto-insight on first open of the day
      fetchAllData().then(function () {
        var insight = computeAutoInsight();
        if (insight) {
          appendMessage('assistant', insight, true);
        }
        // Hide suggestions if there are existing messages
        if (messages.length > 0) {
          els.suggestions.style.display = 'none';
        }
      });
    } else {
      els.panel.classList.remove('open');
      saveChatHistory();
    }
  }

  function appendMessage(role, content, skipPush) {
    var div = document.createElement('div');
    div.className = 'ef-chat-msg ' + role;
    if (role === 'assistant' || role === 'system') {
      div.innerHTML = renderMarkdown(content);
    } else {
      div.textContent = content;
    }
    els.msgArea.appendChild(div);
    els.msgArea.scrollTop = els.msgArea.scrollHeight;

    if (!skipPush) {
      messages.push({ role: role, content: content });
    }

    // Hide suggestions after first message
    els.suggestions.style.display = 'none';
  }

  function showTyping() {
    els.typing.classList.add('active');
    els.msgArea.appendChild(els.typing);
    els.msgArea.scrollTop = els.msgArea.scrollHeight;
  }

  function hideTyping() {
    els.typing.classList.remove('active');
  }

  function handleSend() {
    var text = els.input.value.trim();
    if (!text || isLoading) return;

    appendMessage('user', text);
    els.input.value = '';
    els.send.disabled = true;
    isLoading = true;
    showTyping();

    sendToAPI(text).then(function (response) {
      hideTyping();
      isLoading = false;
      appendMessage('assistant', response);
    });
  }

  function handleSuggestionClick(text) {
    els.input.value = text;
    els.send.disabled = false;
    handleSend();
  }

  // ── Section L: Chat History Persistence ───────────────────────────
  function saveChatHistory() {
    if (!chatUser || messages.length === 0) return;
    try {
      var today = new Date().toISOString().slice(0, 10);
      var db = firebase.firestore();
      db.collection('users').doc(chatUser.uid)
        .collection('chatHistory').doc(today)
        .set({
          messages: messages,
          updatedAt: firebase.firestore.FieldValue.serverTimestamp(),
        })
        .catch(function () { /* silent */ });
    } catch (e) { /* silent */ }
  }

  function loadChatHistory() {
    if (!chatUser) return;
    try {
      var today = new Date().toISOString().slice(0, 10);
      var db = firebase.firestore();
      db.collection('users').doc(chatUser.uid)
        .collection('chatHistory').doc(today)
        .get()
        .then(function (doc) {
          if (doc.exists && doc.data().messages && doc.data().messages.length) {
            messages = doc.data().messages;
            messages.forEach(function (m) {
              appendMessage(m.role, m.content, true);
            });
            els.suggestions.style.display = 'none';
          }
        })
        .catch(function () { /* silent */ });
    } catch (e) { /* silent */ }
  }

  // ── Section M: Initialization ─────────────────────────────────────
  function init() {
    injectStyles();
    buildDOM();
    wireAuth();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
