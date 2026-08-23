/* Sessions page: translate a response against a stored mapping, and manage
 * the stored sessions themselves.
 *
 * Same two rules as app.js: no inline handlers, and innerHTML only for
 * markup web/highlight.py produced. */

'use strict';

(function () {
  var el = function (id) { return document.getElementById(id); };

  function setStatus(message, kind) {
    var node = el('translate-status');
    node.textContent = message;
    node.className = 'status' + (kind ? ' ' + kind : '');
  }

  function translate() {
    var sessionId = el('translate-session').value.trim();
    var text = el('translate-text').value;

    if (!sessionId) {
      setStatus('Choose a session first — “use” on any row fills this in.', 'error');
      return;
    }

    el('btn-translate').disabled = true;
    setStatus('Reconstructing…');

    fetch('/api/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, text: text })
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) {
          throw new Error(data.error || 'Request failed (' + response.status + ').');
        }
        return data;
      });
    }).then(function (data) {
      var output = el('translate-output');
      output.innerHTML = data.text_html;   // server-escaped
      output.hidden = false;

      var unresolved = data.tokens_seen - data.tokens_resolved;
      setStatus(
        data.tokens_resolved + ' of ' + data.tokens_seen + ' tokens resolved' +
        (unresolved > 0
          ? ' — ' + unresolved + ' did not match this session, marked in the output.'
          : '.'),
        unresolved > 0 ? 'error' : 'ok'
      );
    }).catch(function (error) {
      setStatus(error.message, 'error');
    }).finally(function () {
      el('btn-translate').disabled = false;
    });
  }

  function useSession(sessionId) {
    el('translate-session').value = sessionId;
    el('translate-text').focus();
    setStatus('Session ' + sessionId.slice(0, 12) + ' selected.');
  }

  function deleteSession(sessionId, row) {
    /* No confirm() dialog: this is a mapping table, and losing one only
       costs a re-abstraction of code the user still has. */
    fetch('/api/sessions/' + encodeURIComponent(sessionId), {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' }
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) {
          throw new Error(data.error || 'Delete failed (' + response.status + ').');
        }
        return data;
      });
    }).then(function () {
      row.remove();
      setStatus('Session ' + sessionId.slice(0, 12) + ' and its key deleted.', 'ok');
    }).catch(function (error) {
      setStatus(error.message, 'error');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    el('btn-translate').addEventListener('click', translate);

    var rows = el('session-rows');
    if (rows) {
      rows.addEventListener('click', function (event) {
        var button = event.target.closest('button');
        if (!button) { return; }
        var sessionId = button.dataset.session;
        if (button.classList.contains('use-session')) {
          useSession(sessionId);
        } else if (button.classList.contains('delete-session')) {
          deleteSession(sessionId, button.closest('tr'));
        }
      });
    }
  });
})();
