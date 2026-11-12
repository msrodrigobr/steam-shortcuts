from steam_shortcuts.cli import main


def test_cli_help_exits_successfully(capsys):
    assert main(["--help"]) == 0
    assert "add" in capsys.readouterr().out
