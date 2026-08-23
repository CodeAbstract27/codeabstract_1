/* Workbench behaviour.
 *
 * Two rules, both enforced by the Content-Security-Policy in web/app.py and
 * both worth stating because breaking either is silent:
 *
 * 1. No inline handlers. Everything binds here, by id or by delegation.
 * 2. innerHTML is used ONLY for markup the server produced -- the `html`
 *    field of a code line, and the *_html response fields. Those were
 *    escaped in web/highlight.py, which is the single place that decides
 *    what is safe. Anything else the user typed goes in via textContent.
 */

'use strict';

(function () {
  var el = function (id) { return document.getElementById(id); };

  var state = { report: null, filename: 'source.py' };

  /* ── Requests ─────────────────────────────────────── */

  function post(url, payload) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.json().catch(function () {
        return { error: 'Server returned a non-JSON response (' + response.status + ').' };
      }).then(function (data) {
        if (!response.ok) {
          throw new Error(data.error || 'Request failed (' + response.status + ').');
        }
        return data;
      });
    });
  }

  function readControls() {
    return {
      code: el('source').value,
      filename: el('filename').value,
      privacy_level: el('privacy-level').value,
      context_window: parseInt(el('context-window').value, 10),
      keep_comments: el('keep-comments').checked,
      reveal: el('reveal') ? el('reveal').checked : false
    };
  }

  function setStatus(message, kind) {
    var node = el('status');
    node.textContent = message;
    node.className = 'status' + (kind ? ' ' + kind : '');
  }

  function busy(isBusy) {
    el('btn-abstract').disabled = isBusy;
    el('btn-review').disabled = isBusy;
  }

  /* ── Rendering ────────────────────────────────────── */

  function renderCodePane(container, lines) {
    container.textContent = '';
    lines.forEach(function (line) {
      var row = document.createElement('div');
      row.className = 'code-line' + (line.css ? ' ' + line.css : '');
      row.dataset.line = String(line.number);
      if (line.linked !== null && line.linked !== undefined) {
        row.dataset.linked = String(line.linked);
      }

      var gutter = document.createElement('span');
      gutter.className = 'ln';
      gutter.textContent = String(line.number);

      var code = document.createElement('span');
      code.className = 'lc';
      code.innerHTML = line.html;   // server-escaped, see the header note

      row.appendChild(gutter);
      row.appendChild(code);
      container.appendChild(row);
    });
  }

  function renderChecklist(data, reviewed) {
    var list = el('checklist');
    list.textContent = '';

    var items = [
      {
        text: 'Code abstracted — ' + data.statistics.abstracted_nodes +
              ' identifiers replaced, ' + data.secrets_hidden + ' secret(s) hidden',
        state: 'done'
      },
      {
        text: data.report.summary.kept + ' name(s) deliberately kept readable',
        state: 'done'
      },
      {
        text: data.report.summary.uncertain + ' decision(s) below the confidence threshold',
        state: data.report.summary.uncertain > 0 ? 'alert' : 'done'
      },
      {
        text: reviewed
          ? 'LLM analysis complete — ' + data.provider + '/' + data.model +
            ' in ' + data.response_time + 's'
          : 'LLM analysis not run',
        state: reviewed ? 'done' : 'pending'
      },
      {
        text: reviewed
          ? 'Feedback mapped back to your names and line numbers'
          : 'Nothing sent anywhere',
        state: reviewed ? 'done' : 'pending'
      }
    ];

    items.forEach(function (item) {
      var li = document.createElement('li');
      li.textContent = item.text;
      if (item.state !== 'done') { li.className = item.state; }
      list.appendChild(li);
    });

    var strip = el('stat-strip');
    strip.textContent = '';
    var stats = [
      ['Session', data.session_id.slice(0, 12)],
      ['Language', data.language],
      ['Privacy', data.privacy_level],
      ['Hidden', data.report.summary.hidden],
      ['Kept', data.report.summary.kept],
      ['Secrets', data.secrets_hidden]
    ];
    stats.forEach(function (pair) {
      var wrap = document.createElement('div');
      var dt = document.createElement('dt');
      dt.textContent = pair[0];
      var dd = document.createElement('dd');
      dd.textContent = String(pair[1]);
      wrap.appendChild(dt);
      wrap.appendChild(dd);
      strip.appendChild(wrap);
    });

    el('summary').hidden = false;
  }

  function renderReport(data) {
    var summary = el('report-summary');
    summary.textContent = '';
    summary.className = 'report-summary';

    [
      data.headline,
      'Detector ' + data.report.detector_version,
      data.secrets_masked
        ? 'Secret values are masked on this page.'
        : 'Secret values are shown in full.'
    ].forEach(function (text) {
      var p = document.createElement('p');
      p.textContent = text;
      summary.appendChild(p);
    });

    var rows = data.report.kept.map(function (item) {
      return [item.name, 'kept — ' + item.reason, String(item.lineno),
              String(item.occurrences)];
    }).concat(data.report.uncertain.map(function (item) {
      return [item.name, 'unsure — ' + item.detector + ' @ ' + item.confidence,
              String(item.lineno), String(item.occurrences)];
    }));

    buildTable(el('report-table'),
      ['Name', 'Decision', 'Line', 'Occurrences'], rows,
      'Nothing was kept readable and no decision was uncertain.');
  }

  function renderVault(data) {
    var rows = data.vault_rows.map(function (item) {
      return [item.token, item.name + (item.masked ? '  (masked)' : ''),
              item.label, String(item.lineno), String(item.occurrences),
              item.detector, item.confidence];
    });
    buildTable(el('vault-table'),
      ['Token', 'Original', 'Label', 'Line', 'Uses', 'Detector', 'Conf.'],
      rows, 'Nothing was abstracted at this privacy level.');
  }

  function buildTable(table, headers, rows, emptyMessage) {
    table.textContent = '';
    table.className = 'data-table';

    if (!rows.length) {
      var caption = table.createCaption();
      caption.textContent = emptyMessage;
      caption.className = 'empty';
      return;
    }

    var head = table.createTHead().insertRow();
    headers.forEach(function (label) {
      var th = document.createElement('th');
      th.textContent = label;
      head.appendChild(th);
    });

    var tbody = table.createTBody();
    rows.forEach(function (cells) {
      var tr = tbody.insertRow();
      cells.forEach(function (value, index) {
        var td = tr.insertCell();
        td.textContent = value;
        if (index === 0) { td.className = 'mono'; }
      });
    });
  }

  function renderAll(data, reviewed) {
    state.report = data.report_markdown;
    state.filename = data.filename;

    renderCodePane(el('pane-original'), data.panes.original);
    renderCodePane(el('pane-abstract'), data.panes.abstract);
    renderChecklist(data, reviewed);
    renderReport(data);
    renderVault(data);

    el('raw-response').innerHTML = reviewed
      ? data.raw_response_html
      : 'Not run — use “Abstract → LLM → Reconstruct”.';
    el('mapped-feedback').innerHTML = reviewed
      ? data.mapped_feedback_html
      : 'Not run — use “Abstract → LLM → Reconstruct”.';

    el('code-panel').hidden = false;
    el('output-panel').hidden = false;
    showTab(reviewed ? 'mapped' : 'report');
  }

  /* ── Tabs ─────────────────────────────────────────── */

  function showTab(name) {
    ['report', 'vault', 'raw', 'mapped'].forEach(function (tab) {
      el('tab-' + tab).hidden = tab !== name;
    });
    Array.prototype.forEach.call(
      document.querySelectorAll('#tabs .tab'),
      function (button) {
        button.classList.toggle('active', button.dataset.tab === name);
      }
    );
  }

  /* ── Actions ──────────────────────────────────────── */

  function runAbstract() {
    busy(true);
    setStatus('Abstracting…');
    post('/api/abstract', readControls())
      .then(function (data) {
        renderAll(data, false);
        setStatus(data.headline + ' · session ' + data.session_id.slice(0, 12), 'ok');
      })
      .catch(function (error) { setStatus(error.message, 'error'); })
      .finally(function () { busy(false); });
  }

  function runReview() {
    var payload = readControls();
    payload.task = el('task').value;
    payload.provider = el('provider').value;
    payload.query = el('query').value;

    busy(true);
    setStatus('Abstracting, sending, reconstructing…');
    post('/api/review', payload)
      .then(function (data) {
        renderAll(data, true);
        var note = data.query_redactions > 0
          ? ' · ' + data.query_redactions + ' value(s) redacted from your question'
          : '';
        setStatus(data.headline + note, 'ok');
      })
      .catch(function (error) { setStatus(error.message, 'error'); })
      .finally(function () { busy(false); });
  }

  function downloadReport() {
    if (!state.report) { return; }
    var blob = new Blob([state.report], { type: 'text/markdown' });
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = state.filename.replace(/\.[^.]+$/, '') + '-privacy-report.md';
    link.click();
    URL.revokeObjectURL(link.href);
  }

  function openFile(event) {
    var file = event.target.files && event.target.files[0];
    if (!file) { return; }
    var reader = new FileReader();
    reader.onload = function () {
      el('source').value = String(reader.result);
      el('filename').value = file.name;
      setStatus('Loaded ' + file.name + ' — nothing has been sent anywhere yet.');
    };
    reader.readAsText(file);
  }

  /* Clicking a token scrolls the original pane to the line it came from,
     which is the whole point of keeping the two panes side by side. */
  function linkPanes(event) {
    var token = event.target.closest('.tok');
    if (!token) { return; }

    Array.prototype.forEach.call(
      document.querySelectorAll('.tok.active'),
      function (node) { node.classList.remove('active'); }
    );
    Array.prototype.forEach.call(
      document.querySelectorAll('.code-line.linked'),
      function (node) { node.classList.remove('linked'); }
    );

    token.classList.add('active');
    var line = el('pane-original')
      .querySelector('.code-line[data-line="' + token.dataset.line + '"]');
    if (line) {
      line.classList.add('linked');
      line.scrollIntoView({ block: 'center' });
    }
  }

  /* ── Wiring ───────────────────────────────────────── */

  document.addEventListener('DOMContentLoaded', function () {
    el('btn-abstract').addEventListener('click', runAbstract);
    el('btn-review').addEventListener('click', runReview);
    el('btn-report-md').addEventListener('click', downloadReport);
    el('file-input').addEventListener('change', openFile);

    el('tabs').addEventListener('click', function (event) {
      if (event.target.dataset.tab) { showTab(event.target.dataset.tab); }
    });

    document.addEventListener('click', linkPanes);

    /* A session chosen on the Sessions page lands here. */
    var pending = window.sessionStorage.getItem('codeabstract.session');
    if (pending) {
      window.sessionStorage.removeItem('codeabstract.session');
      setStatus('Session ' + pending.slice(0, 12) +
                ' — paste its response on the Sessions page to translate it.');
    }
  });
})();
