/* Login and signup forms.
 *
 * Both submit as JSON rather than a plain form post: web/auth.py requires
 * Content-Type: application/json on /api/auth/* for the same CSRF reason
 * the rest of the API does (see web/routes.py's module docstring) -- a
 * plain <form method="post"> here would be exactly the cross-site request
 * that rule exists to rule out.
 */

'use strict';

(function () {
  var script = document.currentScript;
  var mode = script ? script.getAttribute('data-mode') : 'login';
  var form = document.getElementById(mode === 'signup' ? 'signup-form' : 'login-form');
  if (!form) return;

  var statusEl = document.getElementById('auth-status');

  function setStatus(message, kind) {
    statusEl.textContent = message;
    statusEl.className = 'status' + (kind ? ' ' + kind : '');
  }

  function submit(url, payload) {
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

  form.addEventListener('submit', function (event) {
    event.preventDefault();

    var email = document.getElementById('email').value.trim();
    var password = document.getElementById('password').value;
    var button = form.querySelector('button[type="submit"]');

    button.disabled = true;
    setStatus(mode === 'signup' ? 'Creating account…' : 'Signing in…');

    var payload = { email: email, password: password };
    var nextField = document.getElementById('next');
    if (nextField && nextField.value) {
      payload.next = nextField.value;
    }

    submit(mode === 'signup' ? '/api/auth/signup' : '/api/auth/login', payload)
      .then(function (data) {
        setStatus('Success — redirecting…', 'ok');
        window.location.href = data.redirect || '/dashboard';
      })
      .catch(function (err) {
        button.disabled = false;
        setStatus(err.message, 'error');
      });
  });
})();
