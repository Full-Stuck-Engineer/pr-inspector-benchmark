"""Tests for the pr-bench command line."""

from typer.testing import CliRunner

from pr_inspector_benchmark import __version__
from pr_inspector_benchmark.interface.cli import app

runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert f"pr-bench version {__version__}" in result.stdout


def test_cli_help():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Benchmark pr-inspector" in result.stdout
