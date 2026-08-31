/* Insights page — just the two-tab toggle; everything else is rendered
 * server-side (see web/routes.py's insights() and web/service.py's
 * audit_overview() / benchmark_summary()). */

'use strict';

(function () {
  var el = function (id) { return document.getElementById(id); };

  function showTab(name) {
    ['audit', 'benchmarks'].forEach(function (tab) {
      el('tab-' + tab).hidden = tab !== name;
    });
    Array.prototype.forEach.call(
      document.querySelectorAll('#insight-tabs .tab'),
      function (button) {
        button.classList.toggle('active', button.dataset.tab === name);
      }
    );
  }

  var tabs = el('insight-tabs');
  if (tabs) {
    tabs.addEventListener('click', function (event) {
      if (event.target.dataset.tab) { showTab(event.target.dataset.tab); }
    });
  }

  /* ── Run benchmarks now ───────────────────────────────── */

  function setRunStatus(message, kind) {
    var node = el('benchmarks-run-status');
    if (!node) { return; }
    node.textContent = message;
    node.className = 'status' + (kind ? ' ' + kind : '');
  }

  var runButton = el('btn-run-benchmarks');
  if (runButton) {
    runButton.addEventListener('click', function () {
      runButton.disabled = true;
      setRunStatus('Running the evaluation suite (skipping the performance pillar) — this takes a few seconds…');

      fetch('/api/benchmarks/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) {
            throw new Error(data.error || 'Run failed (' + response.status + ').');
          }
          return data;
        });
      }).then(function () {
        setRunStatus('Done — reloading with fresh numbers…', 'ok');
        window.location.reload();
      }).catch(function (error) {
        runButton.disabled = false;
        setRunStatus(error.message, 'error');
      });
    });
  }
})();
