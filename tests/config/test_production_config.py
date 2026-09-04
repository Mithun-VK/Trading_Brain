"""Production configuration audit (Phase 35).

Every default in `Settings` is chosen so a developer's first run works with
no setup. That is the right trade, but it makes the unsafe configuration the
quiet one: a synthetic price feed and an open API look exactly like a
working system. These tests pin down that production says so out loud.
"""

from __future__ import annotations

from config.settings import Settings

PROD = {"APP_ENV": "production"}


def _issues(**overrides: str) -> list[str]:
    # `_env_file=None` isolates the test from whatever the developer's local
    # .env happens to contain -- this test suite was bitten by exactly that
    # once before (health checks assuming Obsidian/Claude unconfigured while
    # the ambient .env had them set), and switching MARKET_DATA_PROVIDER to
    # yahoo for real-data experiments broke this file the same way until this
    # fix: Settings(APP_ENV="production") was silently reading "yahoo" from
    # .env instead of the "mock" default the test's docstring assumes.
    return Settings(**{**PROD, **overrides}, _env_file=None).production_issues()  # type: ignore[arg-type,call-arg]


def test_development_defaults_raise_no_production_issues() -> None:
    """Outside production none of these are problems, and reporting them
    would train the reader to ignore the list."""
    settings = Settings(
        APP_ENV="development", MARKET_DATA_PROVIDER="mock", _env_file=None  # type: ignore[call-arg]
    )
    assert settings.production_issues() == []


def test_the_bare_defaults_are_not_production_ready() -> None:
    """The important case: someone sets APP_ENV=production and changes
    nothing else."""
    issues = Settings(APP_ENV="production", _env_file=None).production_issues()  # type: ignore[call-arg]

    assert len(issues) >= 4
    joined = " ".join(issues)
    assert "MARKET_DATA_PROVIDER" in joined
    assert "API_AUTH_TOKENS" in joined
    assert "change-me" in joined
    assert "ANTHROPIC_API_KEY" in joined


def test_a_synthetic_provider_in_production_is_flagged() -> None:
    """Rule 4 -- generated numbers must never pass as real."""
    assert any("synthetic" in i for i in _issues(MARKET_DATA_PROVIDER="mock"))


def test_a_real_provider_is_not_flagged() -> None:
    assert not any("synthetic" in i for i in _issues(MARKET_DATA_PROVIDER="yahoo"))


def test_an_open_api_in_production_is_flagged() -> None:
    issue = next(i for i in _issues() if "API_AUTH_TOKENS" in i)

    assert "spend Anthropic API credits" in issue


def test_configured_auth_clears_that_issue() -> None:
    assert not any("API_AUTH_TOKENS" in i for i in _issues(API_AUTH_TOKENS="a-real-token"))


def test_the_placeholder_database_password_is_flagged() -> None:
    assert any("change-me" in i for i in _issues())


def test_a_real_database_url_clears_that_issue() -> None:
    url = "postgresql+psycopg://tb:s3cret@db.internal:5432/trading_brain"

    assert not any("change-me" in i for i in _issues(DATABASE_URL=url))


def test_unverified_obsidian_tls_is_flagged_only_when_obsidian_is_used() -> None:
    """No key means the integration is off; warning about its TLS settings
    would be noise."""
    assert not any("TLS" in i for i in _issues(OBSIDIAN_API_KEY=""))
    assert any("TLS" in i for i in _issues(OBSIDIAN_API_KEY="k", OBSIDIAN_VERIFY_TLS="false"))


def test_pinning_the_obsidian_ca_clears_the_tls_issue() -> None:
    issues = _issues(OBSIDIAN_API_KEY="k", OBSIDIAN_CA_CERT_PATH="/etc/tb/obsidian-ca.crt")

    assert not any("TLS" in i for i in issues)


def test_a_fully_configured_production_environment_is_clean() -> None:
    """The list must be reachable-empty. A check that can never pass is a
    check people learn to skip."""
    issues = Settings(
        APP_ENV="production",
        MARKET_DATA_PROVIDER="yahoo",
        API_AUTH_TOKENS="a-real-token",
        DATABASE_URL="postgresql+psycopg://tb:s3cret@db.internal:5432/trading_brain",
        ANTHROPIC_API_KEY="sk-real",
        OBSIDIAN_API_KEY="k",
        OBSIDIAN_CA_CERT_PATH="/etc/tb/obsidian-ca.crt",
        LOG_LEVEL="INFO",
    ).production_issues()

    assert issues == []
