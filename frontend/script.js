// VERITAS Frontend — Main application logic
const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  ? 'http://localhost:5000'
  : '';

// ─── SCREEN MANAGEMENT ────────────────────────────────────

let _dashShaderDone = false;
let _resultsShaderDone = false;

function showScreen(name) {
  document.querySelectorAll('.screen').forEach(function(s) { s.style.display = 'none'; });
  var el = document.getElementById('s-' + name);
  if (el) el.style.display = 'block';

  if (name === 'landing') {
    window._initHeroShader && window._initHeroShader();
    window._initReportAnim && window._initReportAnim();
    initScrollReveal();
  }
  if (name === 'dashboard' && !_dashShaderDone) {
    _dashShaderDone = true;
    ShaderBG.init('dashShader');
  }
  if (name === 'results' && !_resultsShaderDone) {
    _resultsShaderDone = true;
    ShaderBG.init('resultsShader');
  }
}

// Show landing on initial load
window.addEventListener('load', function() {
  showScreen('landing');
});

// "Try Now" buttons → dashboard
document.querySelectorAll('[data-action="try"]').forEach(function(btn) {
  btn.addEventListener('click', function() { showScreen('dashboard'); });
});

// Dashboard bottom-left exit → landing
document.getElementById('dashExit').addEventListener('click', function() {
  showScreen('landing');
});

// Results bottom-left exit → dashboard
document.getElementById('resultsExit').addEventListener('click', function() {
  resetDashboard();
  showScreen('dashboard');
});

// ─── DASHBOARD — WORD COUNTER ─────────────────────────────

var claimTextarea = document.getElementById('claimText');
var inputLbl = document.getElementById('inputLbl');

claimTextarea.addEventListener('input', function() {
  var words = claimTextarea.value.trim().split(/\s+/).filter(Boolean).length;
  inputLbl.textContent = 'TEXT · ' + words + ' WORDS';
});

// Clear button
document.getElementById('btnClear').addEventListener('click', function() {
  claimTextarea.value = '';
  claimTextarea.dispatchEvent(new Event('input'));
  claimTextarea.focus();
});

// Submit on Enter (Shift+Enter for newline)
claimTextarea.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runAnalysis(); }
});

// Verify button
document.getElementById('btnRun').addEventListener('click', runAnalysis);

// ─── ANALYSIS FUNCTION ────────────────────────────────────

var _lpTimers = [];

async function runAnalysis() {
  var text = claimTextarea.value.trim();
  if (!text) { claimTextarea.focus(); return; }

  // Show loading overlay
  document.getElementById('dashInner').style.display = 'none';
  document.getElementById('dashLoading').style.display = 'flex';
  document.getElementById('dashLoading').style.justifyContent = 'center';
  document.getElementById('dashLoading').style.alignItems = 'center';
  document.getElementById('dashLoading').style.width = '100%';
  document.getElementById('dashError').style.display = 'none';
  document.getElementById('btnRun').disabled = true;

  // Activate pipeline steps sequentially
  ['lp-1','lp-2','lp-3','lp-4'].forEach(function(id) {
    document.getElementById(id).classList.remove('lp-active');
  });
  var delays = [0, 8000, 30000, 55000];
  _lpTimers = delays.map(function(d, i) {
    return setTimeout(function() {
      document.getElementById('lp-' + (i+1)).classList.add('lp-active');
    }, d);
  });

  try {
    var res = await fetch(API_BASE + '/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text }),
    });

    _lpTimers.forEach(clearTimeout);

    var data = await res.json();

    if (!res.ok || data.error) {
      showDashError(data.error || 'A server error occurred.');
      return;
    }

    renderResults(data);
    showScreen('results');

  } catch (err) {
    _lpTimers.forEach(clearTimeout);
    showDashError('Could not connect to server. Make sure the Flask server is running.');
    console.error(err);
  } finally {
    document.getElementById('btnRun').disabled = false;
  }
}

function showDashError(msg) {
  document.getElementById('dashLoading').style.display = 'none';
  document.getElementById('dashInner').style.display = 'block';
  var errEl = document.getElementById('dashError');
  errEl.textContent = msg;
  errEl.style.display = 'block';
}

function resetDashboard() {
  _lpTimers.forEach(clearTimeout);
  document.getElementById('dashLoading').style.display = 'none';
  document.getElementById('dashInner').style.display = 'block';
  document.getElementById('dashError').style.display = 'none';
}

// ─── REPORT PARSER ───────────────────────────────────────

function parseReportText(text) {
  if (!text) return null;

  var result = { taskId: '', claims: [], averageScore: 0, results: [], summary: '', sources: [] };
  var lines = text.split('\n');
  var section = null;
  var currentResult = null;

  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    var t = line.trim();
    if (!t) continue;

    if (t.startsWith('TASK_ID:')) { result.taskId = t.replace('TASK_ID:', '').trim(); continue; }
    if (t === 'CLAIMS:') { section = 'claims'; continue; }
    if (t.startsWith('AVERAGE SCORE:')) {
      var m = t.match(/(\d+)/); if (m) result.averageScore = parseInt(m[1]); continue;
    }
    if (t === 'RESULTS:') {
      if (currentResult) { result.results.push(currentResult); currentResult = null; }
      section = 'results'; continue;
    }
    if (t === 'SUMMARY:') {
      if (currentResult) { result.results.push(currentResult); currentResult = null; }
      section = 'summary'; continue;
    }
    if (t === 'SOURCES:') {
      if (currentResult) { result.results.push(currentResult); currentResult = null; }
      section = 'sources'; continue;
    }

    if (section === 'claims' && /^\d+[.)]\s/.test(t)) {
      result.claims.push(t.replace(/^\d+[.)]\s*/, ''));
    }

    if (section === 'results') {
      var numM = t.match(/^(\d+)[.)]\s+(.+)/);
      if (numM) {
        if (currentResult) result.results.push(currentResult);
        currentResult = { id: parseInt(numM[1]), text: numM[2], score: 0, verdict: 'UNCERTAIN', analysis: '' };
      } else if (currentResult) {
        if (t.match(/^Score:/i)) {
          var sm = t.match(/Score:\s*(\d+)/i); if (sm) currentResult.score = parseInt(sm[1]);
          var vm = t.match(/Verdict:\s*(\S+)/i); if (vm) currentResult.verdict = vm[1];
        } else if (t.match(/^Analysis:/i)) {
          currentResult.analysis = t.replace(/^Analysis:\s*/i, '');
        } else if (currentResult.analysis && !t.match(/^\d+[.)]/)) {
          currentResult.analysis += ' ' + t;
        }
      }
    }

    if (section === 'summary') {
      result.summary += (result.summary ? ' ' : '') + t;
    }

    if (section === 'sources' && t.startsWith('-')) {
      result.sources.push(t.replace(/^-\s*/, ''));
    }
  }

  if (currentResult) result.results.push(currentResult);
  return result;
}

function verdictLabel(v) {
  var vup = (v || '').toUpperCase();
  if (vup === 'TRUE') return 'TRUE';
  if (vup === 'FALSE') return 'FALSE';
  if (vup === 'PARTIALLY_TRUE') return 'PARTIALLY TRUE';
  return 'UNCERTAIN';
}

function verdictClass(v) {
  var vup = (v || '').toUpperCase();
  if (vup === 'TRUE') return 'ok';
  if (vup === 'FALSE') return 'err';
  if (vup === 'PARTIALLY_TRUE') return 'warn';
  return 'info';
}

// ─── RESULT RENDER ───────────────────────────────────────

function renderResults(data) {
  var report = data.report;
  var taskId = data.task_id || '';

  // Show task ID
  var tidEl = document.getElementById('taskIdDisplay');
  tidEl.textContent = taskId ? '#' + taskId.slice(0, 8) : '—';

  // Reset verdict
  document.getElementById('verdictMeter').style.setProperty('--w', 0);
  document.getElementById('verdictVal').textContent = '—';

  var parsed = null;
  if (report && report.text) {
    parsed = parseReportText(report.text);
  }

  var reportBody = document.getElementById('reportBody');
  reportBody.innerHTML = '';

  if (!parsed || (!parsed.results.length && !parsed.summary && !parsed.claims.length)) {
    // Fallback: raw text
    var raw = (report && (report.text || report.raw)) || data.raw || '';
    var pre = document.createElement('pre');
    pre.className = 'raw-text';
    pre.textContent = raw;
    reportBody.appendChild(pre);
    document.getElementById('summaryCard').style.display = 'none';
    document.getElementById('sourcesCard').style.display = 'none';
    return;
  }

  // Use parsed results if available, otherwise build from claims
  var items = parsed.results.length ? parsed.results :
    parsed.claims.map(function(c, i) {
      return { id: i+1, text: c, score: 0, verdict: 'UNCERTAIN', analysis: '' };
    });

  items.forEach(function(r) {
    var cls = verdictClass(r.verdict);
    var lbl = verdictLabel(r.verdict);
    var div = document.createElement('div');
    div.className = 'result-item';
    div.innerHTML =
      '<div class="ri-head">' +
        '<span class="ri-id">C.' + String(r.id).padStart(2,'0') + '</span>' +
        '<span class="ri-text">' + escHtml(r.text) + '</span>' +
      '</div>' +
      '<div class="ri-meta">' +
        '<span class="ri-verdict v-' + cls + '">' + lbl + '</span>' +
        '<span class="ri-bar-wrap">' +
          '<span class="ri-bar"><span class="ri-bar-fill bar-' + cls + '" style="width:' + r.score + '%"></span></span>' +
          '<span class="ri-score score-' + cls + '">' + r.score + '/100</span>' +
        '</span>' +
      '</div>' +
      (r.analysis ? '<p class="ri-analysis">' + escHtml(r.analysis) + '</p>' : '');
    reportBody.appendChild(div);
  });

  // Average score
  var avg = parsed.averageScore;
  if (!avg && items.length) {
    avg = Math.round(items.reduce(function(s, r) { return s + r.score; }, 0) / items.length);
  }
  setTimeout(function() {
    document.getElementById('verdictMeter').style.setProperty('--w', avg / 100);
    var v = 0;
    (function tick() {
      v += 2;
      if (v >= avg) { document.getElementById('verdictVal').textContent = avg + '%'; return; }
      document.getElementById('verdictVal').textContent = v + '%';
      setTimeout(tick, 22);
    })();
  }, 400);

  // Summary
  if (parsed.summary) {
    document.getElementById('summaryBody').textContent = parsed.summary;
    document.getElementById('summaryCard').style.display = 'block';
  } else {
    document.getElementById('summaryCard').style.display = 'none';
  }

  // Sources
  if (parsed.sources.length) {
    var sb = document.getElementById('sourcesBody');
    sb.innerHTML = parsed.sources.map(function(s) {
      var idx = s.indexOf(' — ');
      var title = idx > -1 ? s.slice(0, idx) : s;
      var url = idx > -1 ? s.slice(idx + 3) : '';
      var isUrl = url.startsWith('http://') || url.startsWith('https://');
      return '<div class="source-row">' +
        '<span class="src-dot"></span>' +
        '<div class="src-info">' +
          '<span class="src-title">' + escHtml(title) + '</span>' +
          (isUrl ? '<a class="src-url" href="' + escHtml(url) + '" target="_blank" rel="noopener noreferrer">' + escHtml(url) + '</a>' : '') +
        '</div>' +
      '</div>';
    }).join('');
    document.getElementById('sourcesCard').style.display = 'block';
  } else {
    document.getElementById('sourcesCard').style.display = 'none';
  }
}

// ─── SCROLL REVEAL (landing) ──────────────────────────────

function initScrollReveal() {
  if (window._revealReady) return;
  window._revealReady = true;
  var io = new IntersectionObserver(function(entries) {
    entries.forEach(function(e) {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    });
  }, { threshold: 0.08 });
  document.querySelectorAll('.reveal').forEach(function(el) { io.observe(el); });
}

// ─── HELPERS ─────────────────────────────────────────────

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
