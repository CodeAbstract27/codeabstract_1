"""
Tests for the ``codeabstract web`` command.

The command's one real decision is the bind address, and it is a decision
worth a test rather than a comment. Accounts scope one signed-in user's
sessions away from another's, but do not gate the port itself: on loopback
that is still the CLI's own trust boundary, and on any other interface a
stranger can reach in, sign up, spend the operator's configured LLM
provider quota, and read any session nobody ever signed into.
"""

import pytest
import typer

from commands.web_cmd import is_loopback, run_web


class TestLoopbackDetection:

    @pytest.mark.parametrize('host', [
        '127.0.0.1', '127.1.2.3', 'localhost', 'LOCALHOST', '::1', '',
    ])
    def test_loopback_addresses_are_recognised(self, host):
        assert is_loopback(host) is True

    @pytest.mark.parametrize('host', [
        '0.0.0.0', '192.168.1.10', '10.0.0.5', '::', '2001:db8::1',
    ])
    def test_routable_addresses_are_not_loopback(self, host):
        assert is_loopback(host) is False

    @pytest.mark.parametrize('host', ['my-laptop.local', 'example.com', 'db'])
    def test_an_unresolved_hostname_is_treated_as_exposed(self, host):
        """
        A hostname resolves at bind time and could point anywhere.

        Treating the unknown case as exposed costs one extra flag; treating
        it as loopback would publish the vault on a wrong guess.
        """
        assert is_loopback(host) is False


class TestBindGuard:

    def test_binding_a_routable_address_is_refused(self):
        with pytest.raises(typer.Exit) as exc:
            run_web(host='0.0.0.0')
        assert exc.value.exit_code == 1

    def test_the_refusal_explains_why(self, capsys):
        with pytest.raises(typer.Exit):
            run_web(host='192.168.1.50')

        message = capsys.readouterr().out
        assert '--expose' in message
        # Accounts scope one signed-in user's sessions from another's, but
        # do not gate who can reach the port at all -- the refusal has to
        # say so, not lean on the stale claim that nothing here is
        # authenticated.
        assert 'account' in message.lower()

    def test_expose_overrides_the_guard(self, monkeypatch):
        """With ``--expose`` the command proceeds — the user was asked."""
        started = {}

        class FakeApp:
            config = {}

            def run(self, host, port, debug):
                started.update(host=host, port=port, debug=debug)

        monkeypatch.setattr(
            'web.create_app', lambda config=None: FakeApp(), raising=True,
        )
        run_web(host='0.0.0.0', port=8080, expose=True)

        assert started == {'host': '0.0.0.0', 'port': 8080, 'debug': False}

    def test_loopback_needs_no_acknowledgement(self, monkeypatch):
        started = {}

        class FakeApp:
            def run(self, host, port, debug):
                started.update(host=host)

        monkeypatch.setattr(
            'web.create_app', lambda config=None: FakeApp(), raising=True,
        )
        run_web(host='127.0.0.1')

        assert started == {'host': '127.0.0.1'}


class TestConfigPassthrough:

    def test_flags_reach_the_application_config(self, monkeypatch):
        captured = {}

        class FakeApp:
            def run(self, **_kwargs):
                pass

        def fake_create_app(config=None):
            captured.update(config or {})
            return FakeApp()

        monkeypatch.setattr('web.create_app', fake_create_app, raising=True)
        run_web(no_save=True, allow_reveal=True)

        assert captured['SAVE_SESSIONS'] is False
        assert captured['ALLOW_REVEAL'] is True

    def test_defaults_save_sessions_and_mask_secrets(self, monkeypatch):
        captured = {}

        class FakeApp:
            def run(self, **_kwargs):
                pass

        def fake_create_app(config=None):
            captured.update(config or {})
            return FakeApp()

        monkeypatch.setattr('web.create_app', fake_create_app, raising=True)
        run_web()

        assert captured['SAVE_SESSIONS'] is True
        assert captured['ALLOW_REVEAL'] is False


class TestTlsFlag:
    def test_warns_when_exposed_without_tls(self, capsys, monkeypatch):
        class FakeApp:
            config = {}

            def run(self, host, port, debug):
                pass

        monkeypatch.setattr(
            'web.create_app', lambda config=None: FakeApp(), raising=True,
        )
        run_web(host='0.0.0.0', expose=True, tls=False)

        message = capsys.readouterr().out
        assert 'plain http' in message.lower() or 'plaintext' in message.lower() or '--tls' in message

    def test_no_plaintext_warning_when_tls_is_on(self, capsys, monkeypatch):
        class FakeApp:
            config = {}

            def run(self, host, port, debug, ssl_context=None):
                assert ssl_context == 'adhoc'

        monkeypatch.setattr(
            'web.create_app', lambda config=None: FakeApp(), raising=True,
        )
        run_web(host='0.0.0.0', expose=True, tls=True)

        message = capsys.readouterr().out
        assert 'https' in message.lower()

    def test_no_plaintext_warning_on_loopback(self, capsys, monkeypatch):
        class FakeApp:
            config = {}

            def run(self, host, port, debug):
                pass

        monkeypatch.setattr(
            'web.create_app', lambda config=None: FakeApp(), raising=True,
        )
        run_web(host='127.0.0.1', tls=False)

        message = capsys.readouterr().out
        assert '--tls' not in message

    def test_ssl_context_only_passed_when_tls_requested(self, monkeypatch):
        """A caller whose fake app doesn't accept ssl_context must not break
        when --tls was never asked for -- see the ssl_context bug this
        guards against, caught by the pre-existing FakeApp fixtures above."""
        started = {}

        class FakeApp:
            config = {}

            def run(self, host, port, debug):
                started.update(host=host, port=port, debug=debug)

        monkeypatch.setattr(
            'web.create_app', lambda config=None: FakeApp(), raising=True,
        )
        run_web(host='127.0.0.1', tls=False)
        assert started['host'] == '127.0.0.1'


class TestCliRegistration:
    """The command has to be reachable, not merely defined."""

    def test_web_is_registered_on_the_app(self):
        from typer.main import get_command

        import cli

        assert 'web' in get_command(cli.app).commands

    def test_the_command_is_importable_without_starting_a_server(self):
        import commands.web_cmd as module

        assert callable(module.run_web)
