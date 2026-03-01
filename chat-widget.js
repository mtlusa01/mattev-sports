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
  const MAX_API_MESSAGES = 20;

  let chatOpen = false;
  let messages = [];
  let cachedData = null;
  let chatUser = null;
  let chatProfile = null;
  let isLoading = false;
  let historyLoaded = false;
  let viewingPastSession = false;
  const MAX_FREE_MESSAGES = 20;
  const RATE_KEY_PREFIX = 'ef_chat_count_';

  // Tool definitions for Claude function calling
  var TOOLS = [
    {
      name: 'add_bet',
      description: 'Add a bet to the user\'s tracked bets in Firestore. Call this when the user asks to add, lock in, or track a specific pick.',
      input_schema: {
        type: 'object',
        properties: {
          sport: { type: 'string', enum: ['NBA', 'NCAAB', 'NHL'], description: 'Sport league' },
          type: { type: 'string', enum: ['spread', 'total', 'ml', 'prop'], description: 'Bet type' },
          matchup: { type: 'string', description: 'Game matchup e.g. "NOP @ LAC"' },
          pick: { type: 'string', description: 'The pick e.g. "UNDER 238.5" or "LAC -5.5"' },
          player: { type: 'string', description: 'Player name for props, null for game bets' },
          statType: { type: 'string', description: 'Stat type for props e.g. "Points", "PRA", null for game bets' },
          line: { type: 'number', description: 'The line value' },
          confidence: { type: 'number', description: 'Model confidence percentage' },
          odds: { type: 'number', description: 'American odds e.g. -110' }
        },
        required: ['sport', 'type', 'matchup', 'pick', 'line', 'confidence']
      }
    },
    {
      name: 'remove_bet',
      description: 'Remove a bet from the user\'s tracked bets. Call this when the user asks to remove or cancel a tracked bet.',
      input_schema: {
        type: 'object',
        properties: {
          matchup: { type: 'string', description: 'Game matchup to identify the bet' },
          pick: { type: 'string', description: 'The specific pick to remove' }
        },
        required: ['matchup', 'pick']
      }
    },
    {
      name: 'get_tracked_bets',
      description: 'Get the user\'s currently tracked/pending bets. Call this when the user asks about their bets, bankroll, or tracked picks.',
      input_schema: {
        type: 'object',
        properties: {
          date: { type: 'string', description: 'Optional date filter YYYY-MM-DD, defaults to today' }
        }
      }
    }
  ];

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
      .ef-chat-header-info { flex: 1; min-width: 0; }
      .ef-chat-header-title {
        font-family: 'DM Sans', sans-serif;
        font-weight: 600; font-size: 15px; color: #f1f5f9;
      }
      .ef-chat-header-sub {
        font-size: 11px; color: #64748b; font-weight: 400;
      }
      .ef-chat-session-info {
        font-size: 10px; color: #475569; font-family: 'DM Sans', sans-serif;
        margin-top: 1px;
      }
      .ef-chat-header-actions { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
      .ef-chat-hdr-btn {
        background: none; border: none; cursor: pointer;
        color: #64748b; font-size: 15px; padding: 4px 6px; line-height: 1;
        border-radius: 6px; transition: color 0.15s, background 0.15s;
      }
      .ef-chat-hdr-btn:hover { color: #f1f5f9; background: rgba(148,163,184,0.1); }
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
        position: relative;
      }
      .ef-chat-messages::-webkit-scrollbar { width: 5px; }
      .ef-chat-messages::-webkit-scrollbar-track { background: transparent; }
      .ef-chat-messages::-webkit-scrollbar-thumb {
        background: rgba(148,163,184,0.15); border-radius: 10px;
      }

      .ef-chat-loading {
        display: flex; flex-direction: column; align-items: center;
        justify-content: center; gap: 10px; padding: 40px 20px;
        color: #64748b; font-family: 'DM Sans', sans-serif; font-size: 13px;
      }
      .ef-chat-loading-spinner {
        width: 24px; height: 24px; border: 2px solid rgba(0,212,255,0.15);
        border-top-color: #00d4ff; border-radius: 50%;
        animation: ef-spin 0.7s linear infinite;
      }
      @keyframes ef-spin { to { transform: rotate(360deg); } }

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

      /* Sessions overlay */
      .ef-chat-sessions {
        position: absolute; top: 0; left: 0; right: 0; bottom: 0;
        background: #0c1220; z-index: 5; border-radius: 14px;
        display: none; flex-direction: column;
      }
      .ef-chat-sessions.open { display: flex; }
      .ef-chat-sessions-header {
        display: flex; align-items: center; gap: 10px;
        padding: 14px 16px; border-bottom: 1px solid rgba(148,163,184,0.1);
        background: #111827; border-radius: 14px 14px 0 0;
      }
      .ef-chat-sessions-back {
        background: none; border: none; cursor: pointer;
        color: #94a3b8; font-size: 18px; padding: 2px 6px;
        border-radius: 6px; transition: color 0.15s;
      }
      .ef-chat-sessions-back:hover { color: #00d4ff; }
      .ef-chat-sessions-title {
        font-family: 'DM Sans', sans-serif; font-weight: 600;
        font-size: 14px; color: #f1f5f9;
      }
      .ef-chat-session-list {
        flex: 1; overflow-y: auto; padding: 12px;
        display: flex; flex-direction: column; gap: 6px;
      }
      .ef-chat-session-item {
        display: flex; align-items: center; justify-content: space-between;
        padding: 10px 14px; border-radius: 10px; cursor: pointer;
        background: rgba(148,163,184,0.04); border: 1px solid rgba(148,163,184,0.08);
        font-family: 'DM Sans', sans-serif; transition: all 0.15s;
      }
      .ef-chat-session-item:hover {
        background: rgba(0,212,255,0.06); border-color: rgba(0,212,255,0.15);
      }
      .ef-chat-session-item.active {
        background: rgba(0,212,255,0.1); border-color: rgba(0,212,255,0.25);
      }
      .ef-chat-session-date { font-size: 13px; color: #f1f5f9; font-weight: 500; }
      .ef-chat-session-count { font-size: 11px; color: #64748b; }
      .ef-chat-session-empty {
        text-align: center; color: #475569; font-size: 13px;
        font-family: 'DM Sans', sans-serif; padding: 40px 20px;
      }

      /* Past session banner */
      .ef-chat-past-banner {
        display: none; align-items: center; justify-content: space-between;
        padding: 8px 16px; background: rgba(245,158,11,0.08);
        border-bottom: 1px solid rgba(245,158,11,0.15);
        font-family: 'DM Sans', sans-serif; font-size: 12px; color: #f59e0b;
      }
      .ef-chat-past-banner.active { display: flex; }
      .ef-chat-past-banner button {
        background: rgba(0,212,255,0.12); border: 1px solid rgba(0,212,255,0.2);
        color: #00d4ff; font-size: 11px; padding: 3px 10px; border-radius: 6px;
        cursor: pointer; font-family: 'DM Sans', sans-serif;
      }
      .ef-chat-past-banner button:hover { background: rgba(0,212,255,0.2); }

      /* Confirm dialog */
      .ef-chat-confirm {
        position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
        background: #111827; border: 1px solid rgba(148,163,184,0.15);
        border-radius: 12px; padding: 20px; z-index: 10;
        box-shadow: 0 8px 30px rgba(0,0,0,0.5); text-align: center;
        font-family: 'DM Sans', sans-serif; display: none; width: 260px;
      }
      .ef-chat-confirm.open { display: block; }
      .ef-chat-confirm p { color: #e2e8f0; font-size: 14px; margin: 0 0 16px; }
      .ef-chat-confirm-btns { display: flex; gap: 10px; justify-content: center; }
      .ef-chat-confirm-btns button {
        padding: 6px 18px; border-radius: 8px; font-size: 13px;
        cursor: pointer; font-family: 'DM Sans', sans-serif; border: none;
      }
      .ef-chat-confirm-cancel { background: rgba(148,163,184,0.1); color: #94a3b8; }
      .ef-chat-confirm-cancel:hover { background: rgba(148,163,184,0.2); }
      .ef-chat-confirm-yes { background: #ef4444; color: #fff; }
      .ef-chat-confirm-yes:hover { background: #dc2626; }

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
        .ef-chat-sessions { border-radius: 0; }
        .ef-chat-sessions-header { border-radius: 0; }
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
        '<div class="ef-chat-header-info">' +
          '<div class="ef-chat-header-title">EF Analyst</div>' +
          '<div class="ef-chat-header-sub">AI-powered betting assistant</div>' +
          '<div class="ef-chat-session-info"></div>' +
        '</div>' +
        '<div class="ef-chat-header-actions">' +
          '<button class="ef-chat-hdr-btn ef-chat-history-btn" title="Previous sessions">&#128339;</button>' +
          '<button class="ef-chat-hdr-btn ef-chat-clear-btn" title="Clear chat">&#128465;</button>' +
          '<button class="ef-chat-close" title="Close">&times;</button>' +
        '</div>' +
      '</div>' +
      '<div class="ef-chat-past-banner">' +
        '<span class="ef-chat-past-label">Viewing past session</span>' +
        '<button class="ef-chat-past-resume">Back to today</button>' +
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
      '</div>' +
      // Sessions overlay
      '<div class="ef-chat-sessions">' +
        '<div class="ef-chat-sessions-header">' +
          '<button class="ef-chat-sessions-back">&larr;</button>' +
          '<span class="ef-chat-sessions-title">Previous Sessions</span>' +
        '</div>' +
        '<div class="ef-chat-session-list"></div>' +
      '</div>' +
      // Confirm dialog
      '<div class="ef-chat-confirm">' +
        '<p>Clear today\'s conversation?</p>' +
        '<div class="ef-chat-confirm-btns">' +
          '<button class="ef-chat-confirm-cancel">Cancel</button>' +
          '<button class="ef-chat-confirm-yes">Clear</button>' +
        '</div>' +
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
    els.sessionInfo = panel.querySelector('.ef-chat-session-info');
    els.historyBtn = panel.querySelector('.ef-chat-history-btn');
    els.clearBtn = panel.querySelector('.ef-chat-clear-btn');
    els.sessions = panel.querySelector('.ef-chat-sessions');
    els.sessionList = panel.querySelector('.ef-chat-session-list');
    els.sessionsBack = panel.querySelector('.ef-chat-sessions-back');
    els.pastBanner = panel.querySelector('.ef-chat-past-banner');
    els.pastResume = panel.querySelector('.ef-chat-past-resume');
    els.confirm = panel.querySelector('.ef-chat-confirm');
    els.confirmCancel = panel.querySelector('.ef-chat-confirm-cancel');
    els.confirmYes = panel.querySelector('.ef-chat-confirm-yes');

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
    els.historyBtn.addEventListener('click', showSessions);
    els.sessionsBack.addEventListener('click', closeSessions);
    els.clearBtn.addEventListener('click', function () { els.confirm.classList.add('open'); });
    els.confirmCancel.addEventListener('click', function () { els.confirm.classList.remove('open'); });
    els.confirmYes.addEventListener('click', clearChat);
    els.pastResume.addEventListener('click', resumeToday);
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
            if (!chatProfile) {
              var pp = setInterval(function () {
                if (typeof userProfile !== 'undefined' && userProfile) {
                  chatProfile = userProfile;
                  clearInterval(pp);
                }
              }, 200);
              setTimeout(function () { clearInterval(pp); }, 5000);
            }
            // Preload history on auth
            loadChatHistory();
          } else {
            chatUser = null;
            chatProfile = null;
            historyLoaded = false;
            messages = [];
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
      'If you don\'t have data for something, say so. Today is ' + today + '.\n\n' +
      'You have tools to add_bet, remove_bet, and get_tracked_bets. ' +
      'ALWAYS use the add_bet tool when the user asks to track, add, or lock in a pick — do not just say you added it, actually call the tool. ' +
      'Use get_tracked_bets when the user asks about their current bets or tracked picks. ' +
      'When confirming an action, reference the tool result to show it was actually saved.\n\n' +
      'You have access to the most recent messages in this conversation. Earlier messages may have been trimmed for efficiency.'
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

    var pickCount = 0;
    if (cachedData.projections && cachedData.projections.projections)
      pickCount += cachedData.projections.projections.length;
    ['game_projections', 'nhl_game_projections', 'ncaab_projections'].forEach(function (k) {
      if (cachedData[k] && cachedData[k].games) pickCount += cachedData[k].games.length;
    });
    if (pickCount > 0) lines.push('Today: **' + pickCount + ' picks** loaded across all models');

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

  // ── Section I-1: Tool Execution ─────────────────────────────────
  async function executeToolLocally(toolName, input) {
    console.log('[EF Tool] Executing:', toolName, JSON.stringify(input));
    var uid = chatUser && chatUser.uid;
    if (!uid) {
      console.error('[EF Tool] No authenticated user');
      return { success: false, error: 'Not authenticated' };
    }
    var fsDb = firebase.firestore();

    if (toolName === 'add_bet') {
      try {
        var unitSize = (chatProfile && chatProfile.settings && chatProfile.settings.unitSize) || 10;
        var betData = {
          sport: input.sport || 'NBA',
          type: input.type || 'prop',
          matchup: input.matchup || '',
          pick: input.pick || '',
          player: input.player || null,
          statType: input.statType || null,
          line: input.line || 0,
          confidence: input.confidence || 0,
          odds: input.odds || -110,
          date: new Date().toISOString().split('T')[0],
          stake: unitSize,
          units: 1.0,
          result: null,
          payout: null,
          graded: false,
          gradedAt: null,
          source: 'chat_analyst',
          createdAt: firebase.firestore.FieldValue.serverTimestamp()
        };
        console.log('[EF Tool] Writing bet to Firestore:', JSON.stringify(betData));
        var betRef = await fsDb.collection('users').doc(uid).collection('bets').add(betData);
        console.log('[EF Tool] Bet saved, id:', betRef.id);
        return { success: true, betId: betRef.id, message: 'Added bet: ' + input.pick + ' on ' + input.matchup };
      } catch (e) {
        console.error('[EF Tool] add_bet FAILED:', e.code, e.message);
        return { success: false, error: e.code + ': ' + e.message };
      }
    }

    if (toolName === 'remove_bet') {
      try {
        var snap = await fsDb.collection('users').doc(uid).collection('bets')
          .where('matchup', '==', input.matchup)
          .where('pick', '==', input.pick)
          .limit(1).get();
        if (snap.empty) return { success: false, error: 'No matching bet found for ' + input.matchup + ' ' + input.pick };
        await snap.docs[0].ref.delete();
        console.log('[EF Tool] Bet removed');
        return { success: true, message: 'Removed bet: ' + input.pick + ' on ' + input.matchup };
      } catch (e) {
        console.error('[EF Tool] remove_bet FAILED:', e.code, e.message);
        return { success: false, error: e.code + ': ' + e.message };
      }
    }

    if (toolName === 'get_tracked_bets') {
      try {
        var query = fsDb.collection('users').doc(uid).collection('bets');
        var dateFilter = input.date || new Date().toISOString().split('T')[0];
        query = query.where('date', '==', dateFilter);
        var betsSnap = await query.get();
        var bets = [];
        betsSnap.forEach(function (doc) {
          var d = doc.data();
          bets.push({
            id: doc.id, sport: d.sport, type: d.type, matchup: d.matchup,
            pick: d.pick, player: d.player, line: d.line, confidence: d.confidence,
            odds: d.odds, stake: d.stake, result: d.result, source: d.source
          });
        });
        console.log('[EF Tool] get_tracked_bets returned', bets.length, 'bets');
        return { success: true, count: bets.length, bets: bets };
      } catch (e) {
        console.error('[EF Tool] get_tracked_bets FAILED:', e.code, e.message);
        return { success: false, error: e.code + ': ' + e.message };
      }
    }

    return { success: false, error: 'Unknown tool: ' + toolName };
  }

  // ── Section I-2: API Call ─────────────────────────────────────────
  async function sendToAPI(userMessage) {
    if (!checkRateLimit()) {
      return 'You\'ve reached your daily message limit (' + MAX_FREE_MESSAGES + '). Your limit resets tomorrow.';
    }

    try {
      await fetchAllData();

      // Only send last MAX_API_MESSAGES for cost efficiency
      var relevantMessages = messages.filter(function (m) {
        return m.role === 'user' || m.role === 'assistant';
      });
      var apiMessages = relevantMessages.slice(-MAX_API_MESSAGES).map(function (m) {
        return { role: m.role, content: m.content };
      });

      var body = {
        model: 'claude-sonnet-4-20250514',
        max_tokens: 1024,
        system: buildSystemPrompt(),
        messages: apiMessages,
        tools: TOOLS,
      };

      var r = await fetch(WORKER_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error('API error: ' + r.status);
      var data = await r.json();
      if (data.type === 'error') throw new Error(data.error && data.error.message || 'API error');

      // Tool use loop (max 5 rounds)
      var toolRounds = 0;
      while (data.stop_reason === 'tool_use' && toolRounds < 5) {
        toolRounds++;
        var toolUse = data.content.find(function (c) { return c.type === 'tool_use'; });
        if (!toolUse) break;
        console.log('[EF Chat] Tool use requested:', toolUse.name, 'id:', toolUse.id);

        // Push assistant's tool_use response to history (not rendered)
        messages.push({ role: 'assistant', content: data.content });
        saveMessage('assistant', data.content);

        // Execute the tool locally
        var toolResult = await executeToolLocally(toolUse.name, toolUse.input);
        console.log('[EF Chat] Tool result:', JSON.stringify(toolResult));

        // Push tool result to history (not rendered)
        var toolResultContent = [{ type: 'tool_result', tool_use_id: toolUse.id, content: JSON.stringify(toolResult) }];
        messages.push({ role: 'user', content: toolResultContent });
        saveMessage('user', toolResultContent);

        // Re-call API with updated conversation
        relevantMessages = messages.filter(function (m) {
          return m.role === 'user' || m.role === 'assistant';
        });
        apiMessages = relevantMessages.slice(-MAX_API_MESSAGES).map(function (m) {
          return { role: m.role, content: m.content };
        });
        body.messages = apiMessages;

        r = await fetch(WORKER_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error('API error: ' + r.status);
        data = await r.json();
        if (data.type === 'error') throw new Error(data.error && data.error.message || 'API error');
      }

      incrementRateCount();

      var textBlock = data.content && data.content.find(function (c) { return c.type === 'text'; });
      if (textBlock) return textBlock.text;
      if (data.content && data.content[0] && data.content[0].text) return data.content[0].text;
      throw new Error('Unexpected response format');
    } catch (err) {
      console.error('EF Chat error:', err);
      return 'Sorry, I couldn\'t process that request. Please try again in a moment.';
    }
  }

  // ── Section J: Markdown Renderer ──────────────────────────────────
  function renderMarkdown(text) {
    if (!text) return '';
    var html = text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>');

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
      // If history wasn't loaded yet (edge case), show loading
      if (!historyLoaded && chatUser) {
        showLoadingState();
        loadChatHistory().then(function () {
          hideLoadingState();
          triggerAutoInsight();
        });
      } else {
        triggerAutoInsight();
      }
    } else {
      els.panel.classList.remove('open');
      // Close sub-panels
      els.sessions.classList.remove('open');
      els.confirm.classList.remove('open');
    }
  }

  function triggerAutoInsight() {
    fetchAllData().then(function () {
      var insight = computeAutoInsight();
      if (insight) {
        appendMessage('assistant', insight, false, true); // save=false, skipPersist for auto-insight
      }
      if (messages.length > 0) {
        els.suggestions.style.display = 'none';
      }
    });
  }

  function showLoadingState() {
    els.msgArea.innerHTML = '<div class="ef-chat-loading"><div class="ef-chat-loading-spinner"></div>Loading conversation...</div>';
  }

  function hideLoadingState() {
    var loader = els.msgArea.querySelector('.ef-chat-loading');
    if (loader) loader.remove();
  }

  function appendMessage(role, content, skipPush, skipPersist) {
    // Only render human-readable messages (string content)
    if (typeof content === 'string') {
      var div = document.createElement('div');
      div.className = 'ef-chat-msg ' + role;
      if (role === 'assistant' || role === 'system') {
        div.innerHTML = renderMarkdown(content);
      } else {
        div.textContent = content;
      }
      els.msgArea.appendChild(div);
      els.msgArea.scrollTop = els.msgArea.scrollHeight;
    }

    if (!skipPush) {
      messages.push({ role: role, content: content });
      if (!skipPersist) {
        saveMessage(role, content);
      }
      updateSessionInfo();
    }

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
    if (viewingPastSession) return;
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
    if (viewingPastSession) return;
    els.input.value = text;
    els.send.disabled = false;
    handleSend();
  }

  // ── Section L: Chat Persistence ───────────────────────────────────
  function getToday() {
    return new Date().toISOString().slice(0, 10);
  }

  function getChatCollection() {
    if (!chatUser) return null;
    return firebase.firestore().collection('users').doc(chatUser.uid).collection('chatMessages');
  }

  // Save a single message to Firestore (fire-and-forget)
  function saveMessage(role, content) {
    var col = getChatCollection();
    if (!col) return;
    col.add({
      role: role,
      content: content,
      sessionDate: getToday(),
      ts: Date.now(),
      timestamp: firebase.firestore.FieldValue.serverTimestamp()
    }).catch(function () { /* silent */ });
  }

  // Load today's messages from Firestore
  async function loadChatHistory() {
    if (!chatUser || historyLoaded) return;
    try {
      var col = getChatCollection();
      if (!col) return;
      var today = getToday();
      var snap = await col.where('sessionDate', '==', today).get();

      var docs = [];
      snap.forEach(function (doc) {
        var d = doc.data();
        docs.push({ id: doc.id, role: d.role, content: d.content, ts: d.ts || 0 });
      });
      docs.sort(function (a, b) { return a.ts - b.ts; });

      if (docs.length > 0) {
        messages = docs.map(function (d) { return { role: d.role, content: d.content }; });
        // Render only string-content messages
        docs.forEach(function (d) {
          if (typeof d.content === 'string') {
            renderMessageBubble(d.role, d.content);
          }
        });
        els.suggestions.style.display = 'none';
      }
      historyLoaded = true;
      updateSessionInfo();
    } catch (e) {
      console.error('EF Chat: failed to load history', e);
      historyLoaded = true;
    }
  }

  // Render a message bubble without pushing to messages array
  function renderMessageBubble(role, content) {
    if (typeof content !== 'string') return;
    var div = document.createElement('div');
    div.className = 'ef-chat-msg ' + role;
    if (role === 'assistant' || role === 'system') {
      div.innerHTML = renderMarkdown(content);
    } else {
      div.textContent = content;
    }
    els.msgArea.appendChild(div);
    els.msgArea.scrollTop = els.msgArea.scrollHeight;
  }

  // Update session info in header
  function updateSessionInfo() {
    var visibleCount = messages.filter(function (m) { return typeof m.content === 'string'; }).length;
    if (visibleCount > 0) {
      var label = viewingPastSession ? 'Past session' : "Today's session";
      els.sessionInfo.textContent = label + ' \u00B7 ' + visibleCount + ' message' + (visibleCount !== 1 ? 's' : '');
    } else {
      els.sessionInfo.textContent = '';
    }
  }

  // ── Section L-2: Session Management ───────────────────────────────
  async function showSessions() {
    els.sessions.classList.add('open');
    els.sessionList.innerHTML = '<div class="ef-chat-loading"><div class="ef-chat-loading-spinner"></div>Loading sessions...</div>';

    try {
      var col = getChatCollection();
      if (!col) return;
      // Get recent messages, extract unique dates
      var snap = await col.orderBy('ts', 'desc').limit(200).get();
      var dateCounts = {};
      snap.forEach(function (doc) {
        var d = doc.data();
        if (!d.sessionDate) return;
        // Only count visible messages
        if (typeof d.content !== 'string') return;
        dateCounts[d.sessionDate] = (dateCounts[d.sessionDate] || 0) + 1;
      });
      var dates = Object.keys(dateCounts).sort().reverse();

      if (dates.length === 0) {
        els.sessionList.innerHTML = '<div class="ef-chat-session-empty">No previous sessions found.</div>';
        return;
      }

      var today = getToday();
      els.sessionList.innerHTML = dates.map(function (date) {
        var isToday = date === today;
        var label = isToday ? 'Today (' + date + ')' : formatDateLabel(date);
        return '<div class="ef-chat-session-item' + (isToday && !viewingPastSession ? ' active' : '') +
          '" data-date="' + date + '">' +
          '<span class="ef-chat-session-date">' + label + '</span>' +
          '<span class="ef-chat-session-count">' + dateCounts[date] + ' msg' + (dateCounts[date] !== 1 ? 's' : '') + '</span>' +
          '</div>';
      }).join('');

      // Click handlers
      els.sessionList.querySelectorAll('.ef-chat-session-item').forEach(function (item) {
        item.addEventListener('click', function () {
          var date = item.getAttribute('data-date');
          if (date === today) {
            resumeToday();
          } else {
            loadPastSession(date);
          }
          closeSessions();
        });
      });
    } catch (e) {
      els.sessionList.innerHTML = '<div class="ef-chat-session-empty">Failed to load sessions.</div>';
    }
  }

  function formatDateLabel(dateStr) {
    try {
      var parts = dateStr.split('-');
      var d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
      var days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
      var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return days[d.getDay()] + ', ' + months[d.getMonth()] + ' ' + d.getDate();
    } catch (e) { return dateStr; }
  }

  function closeSessions() {
    els.sessions.classList.remove('open');
  }

  async function loadPastSession(date) {
    viewingPastSession = true;
    els.pastBanner.classList.add('active');
    els.pastBanner.querySelector('.ef-chat-past-label').textContent = 'Viewing: ' + formatDateLabel(date);
    els.input.disabled = true;
    els.send.disabled = true;
    els.input.placeholder = 'Read-only — viewing past session';

    // Clear current display
    els.msgArea.innerHTML = '';
    showLoadingState();

    try {
      var col = getChatCollection();
      var snap = await col.where('sessionDate', '==', date).get();
      var docs = [];
      snap.forEach(function (doc) {
        var d = doc.data();
        docs.push({ role: d.role, content: d.content, ts: d.ts || 0 });
      });
      docs.sort(function (a, b) { return a.ts - b.ts; });

      hideLoadingState();
      docs.forEach(function (d) {
        if (typeof d.content === 'string') {
          renderMessageBubble(d.role, d.content);
        }
      });
      // Temporarily replace messages for display count
      var tempMessages = docs.map(function (d) { return { role: d.role, content: d.content }; });
      var savedMessages = messages;
      messages = tempMessages;
      updateSessionInfo();
      messages = savedMessages;
    } catch (e) {
      hideLoadingState();
      renderMessageBubble('system', 'Failed to load session.');
    }
  }

  function resumeToday() {
    viewingPastSession = false;
    els.pastBanner.classList.remove('active');
    els.input.disabled = false;
    els.send.disabled = !els.input.value.trim();
    els.input.placeholder = 'Ask about your picks, stats, or strategy...';
    updatePlaceholder();

    // Re-render today's messages
    els.msgArea.innerHTML = '';
    messages.forEach(function (m) {
      if (typeof m.content === 'string') {
        renderMessageBubble(m.role, m.content);
      }
    });
    updateSessionInfo();

    if (messages.length === 0) {
      els.suggestions.style.display = 'flex';
    }
  }

  // ── Section L-3: Clear Chat ───────────────────────────────────────
  async function clearChat() {
    els.confirm.classList.remove('open');
    if (!chatUser) return;

    try {
      var col = getChatCollection();
      var today = getToday();
      var snap = await col.where('sessionDate', '==', today).get();
      var batch = firebase.firestore().batch();
      snap.forEach(function (doc) { batch.delete(doc.ref); });
      await batch.commit();
    } catch (e) { /* best effort */ }

    // Reset local state
    messages = [];
    els.msgArea.innerHTML = '';
    els.suggestions.style.display = 'flex';
    els.input.placeholder = 'Ask about your picks, stats, or strategy...';
    els.input.disabled = false;
    els.send.disabled = true;
    updateSessionInfo();
    updatePlaceholder();

    // Reset auto-insight so it can fire again
    localStorage.removeItem('ef_chat_insight_date');
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
