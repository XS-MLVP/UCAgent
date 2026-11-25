(function(){
  var STORAGE_KEY = 'ucagent.theme';
  var META_REFRESH_MS = 30000;
  var listeners = [];
  var metaState = {
    version: 'unknown',
    startedAt: null,
    uptimeS: null,
    product: 'UCAgent'
  };
  var THEMES = {
    dark: {
      '--bg': '#0f1117',
      '--surface': '#1a1d26',
      '--surface2': '#22263a',
      '--surface3': '#171a21',
      '--bg2': '#1a1d25',
      '--bg3': '#22262f',
      '--bg4': '#2a2e3a',
      '--border': '#2e3248',
      '--text': '#e2e8f0',
      '--text-dim': '#8892a4',
      '--text-bright': '#f8fafc',
      '--accent': '#6366f1',
      '--accent-hover': '#818cf8',
      '--accent2': '#4f46e5',
      '--online': '#22c55e',
      '--offline': '#ef4444',
      '--ok': '#22c55e',
      '--err': '#ef4444',
      '--warn': '#f59e0b',
      '--green': '#36d399',
      '--red': '#f87272',
      '--yellow': '#fbbd23',
      '--orange': '#f97316',
      '--terminal-bg': '#0f1117',
      '--terminal-fg': '#c8cdd6',
      '--terminal-cursor': '#4f8ef7',
      '--terminal-selection': 'rgba(79,142,247,0.30)',
      '--theme-color': '#0f1117'
    },
    light: {
      '--bg': '#f4f7fb',
      '--surface': '#ffffff',
      '--surface2': '#eef3f9',
      '--surface3': '#e8eef6',
      '--bg2': '#ffffff',
      '--bg3': '#eef3f9',
      '--bg4': '#dde7f2',
      '--border': '#ccd7e6',
      '--text': '#182432',
      '--text-dim': '#5f738a',
      '--text-bright': '#0f172a',
      '--accent': '#2563eb',
      '--accent-hover': '#1d4ed8',
      '--accent2': '#1d4ed8',
      '--online': '#15803d',
      '--offline': '#dc2626',
      '--ok': '#16a34a',
      '--err': '#dc2626',
      '--warn': '#d97706',
      '--green': '#16a34a',
      '--red': '#dc2626',
      '--yellow': '#d97706',
      '--orange': '#ea580c',
      '--terminal-bg': '#f6f8fc',
      '--terminal-fg': '#1f2937',
      '--terminal-cursor': '#2563eb',
      '--terminal-selection': 'rgba(37,99,235,0.18)',
      '--theme-color': '#f4f7fb'
    },
    graphite: {
      '--bg': '#151a20',
      '--surface': '#202730',
      '--surface2': '#293341',
      '--surface3': '#1b222b',
      '--bg2': '#202730',
      '--bg3': '#293341',
      '--bg4': '#344154',
      '--border': '#3a4658',
      '--text': '#d7dee8',
      '--text-dim': '#95a4b8',
      '--text-bright': '#f3f6fb',
      '--accent': '#38bdf8',
      '--accent-hover': '#7dd3fc',
      '--accent2': '#0284c7',
      '--online': '#34d399',
      '--offline': '#f87171',
      '--ok': '#34d399',
      '--err': '#f87171',
      '--warn': '#fbbf24',
      '--green': '#34d399',
      '--red': '#f87171',
      '--yellow': '#fbbf24',
      '--orange': '#fb923c',
      '--terminal-bg': '#151a20',
      '--terminal-fg': '#d6dce5',
      '--terminal-cursor': '#38bdf8',
      '--terminal-selection': 'rgba(56,189,248,0.24)',
      '--theme-color': '#151a20'
    }
  };

  function themeNames(){
    return Object.keys(THEMES);
  }

  function getStoredTheme(){
    try {
      var stored = localStorage.getItem(STORAGE_KEY);
      if (stored && THEMES[stored]) return stored;
    } catch (err) {}
    return 'dark';
  }

  function ensureThemeMeta(){
    var meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = 'theme-color';
      document.head.appendChild(meta);
    }
    return meta;
  }

  function ensureFavicon(){
    var link = document.querySelector('link[rel="icon"]');
    if (!link) {
      link = document.createElement('link');
      link.rel = 'icon';
      document.head.appendChild(link);
    }
    link.type = 'image/svg+xml';
    link.href = '/static/share/ucagent-favicon.svg';
  }

  function applyTheme(name, persist){
    var theme = THEMES[name] || THEMES.dark;
    var root = document.documentElement;
    Object.keys(theme).forEach(function(key){
      root.style.setProperty(key, theme[key]);
    });
    root.dataset.theme = THEMES[name] ? name : 'dark';
    ensureThemeMeta().setAttribute('content', theme['--theme-color'] || theme['--bg']);
    ensureFavicon();
    if (persist !== false) {
      try { localStorage.setItem(STORAGE_KEY, root.dataset.theme); } catch (err) {}
    }
    listeners.slice().forEach(function(listener){
      try { listener(root.dataset.theme, theme); } catch (err) {}
    });
    updateThemeToggleUI();
    return root.dataset.theme;
  }

  function getTheme(){
    return document.documentElement.dataset.theme || getStoredTheme();
  }

  function onThemeChange(listener){
    if (typeof listener === 'function') listeners.push(listener);
  }

  function formatDuration(seconds){
    if (seconds == null || !isFinite(seconds) || seconds < 0) return 'unavailable';
    seconds = Math.max(0, Math.floor(seconds));
    var days = Math.floor(seconds / 86400);
    var hours = Math.floor((seconds % 86400) / 3600);
    var minutes = Math.floor((seconds % 3600) / 60);
    var secs = seconds % 60;
    if (days > 0) return days + 'd ' + String(hours).padStart(2, '0') + 'h ' + String(minutes).padStart(2, '0') + 'm';
    if (hours > 0) return hours + 'h ' + String(minutes).padStart(2, '0') + 'm ' + String(secs).padStart(2, '0') + 's';
    return minutes + 'm ' + String(secs).padStart(2, '0') + 's';
  }

  function renderFooterText(){
    var footer = document.getElementById('uc-shell-footer');
    if (!footer) return;
    var uptimeText = metaState.startedAt
      ? formatDuration((Date.now() / 1000) - metaState.startedAt)
      : formatDuration(metaState.uptimeS);
    footer.innerHTML =
      '<strong>' + escapeHtml(metaState.product || 'UCAgent') + '</strong>' +
      ' <span>v' + escapeHtml(metaState.version || 'unknown') + '</span>' +
      ' <span>|</span> <span>Uptime ' + escapeHtml(uptimeText) + '</span>';
  }

  function escapeHtml(value){
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function createThemeToggle(){
    var wrap = document.createElement('div');
    wrap.className = 'uc-theme-toggle';
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Theme switcher');
    themeNames().forEach(function(name){
      var button = document.createElement('button');
      button.type = 'button';
      button.dataset.theme = name;
      button.textContent = name.charAt(0).toUpperCase() + name.slice(1);
      button.addEventListener('click', function(){
        applyTheme(name, true);
      });
      wrap.appendChild(button);
    });
    return wrap;
  }

  function updateThemeToggleUI(){
    var current = getTheme();
    document.querySelectorAll('.uc-theme-toggle button').forEach(function(button){
      button.classList.toggle('active', button.dataset.theme === current);
    });
  }

  function mountThemeToggle(selector){
    if (!selector) return;
    var host = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (!host) return;
    host.classList.add('uc-shell-actions');
    if (host.querySelector('.uc-theme-toggle')) return;
    host.appendChild(createThemeToggle());
    updateThemeToggleUI();
  }

  function fetchMeta(url){
    if (!url) return;
    fetch(url, { credentials: 'same-origin' })
      .then(function(resp){
        if (!resp.ok) throw new Error('meta fetch failed');
        return resp.json();
      })
      .then(function(payload){
        var data = payload && payload.data ? payload.data : payload || {};
        metaState.product = data.product || 'UCAgent';
        metaState.version = data.version || 'unknown';
        metaState.startedAt = typeof data.started_at === 'number' ? data.started_at : metaState.startedAt;
        metaState.uptimeS = typeof data.uptime_s === 'number' ? data.uptime_s : metaState.uptimeS;
        renderFooterText();
      })
      .catch(function(){
        renderFooterText();
      });
  }

  function init(options){
    options = options || {};
    document.body.classList.add('uc-shell-page');
    if (options.fixedFooter) document.body.classList.add('uc-shell-fixed-footer');
    applyTheme(getStoredTheme(), false);
    mountThemeToggle(options.actionsSelector);
    renderFooterText();
    fetchMeta(options.metaUrl || '/api/ui-meta');
    setInterval(renderFooterText, 1000);
    setInterval(function(){
      fetchMeta(options.metaUrl || '/api/ui-meta');
    }, options.metaRefreshMs || META_REFRESH_MS);
  }

  window.UCAgentShell = {
    init: init,
    applyTheme: applyTheme,
    getTheme: getTheme,
    onThemeChange: onThemeChange,
    themes: THEMES
  };
})();
