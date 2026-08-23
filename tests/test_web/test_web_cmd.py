"""
Tests for the ``codeabstract web`` command.

The command's one real decision is the bind address, and it is a decision
worth a test rather than a comment. Nothing in the web app authenticates a
caller: on loopback that matches the CLI's own trust boundary, and on any
other interface it publishes every stored session's mapping table to
whoever can reach the port.
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
        assert 'authentication' in message.lower()

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


class TestCliRegistration:
    """The command has to be reachable, not merely defined."""

    def test_web_is_registered_on_the_app(self):
        from typer.main import get_command

        import cli

        assert 'web' in get_command(cli.app).commands

    def test_the_command_is_importable_without_starting_a_server(self):
        import commands.web_cmd as module

        assert callable(module.run_web)
