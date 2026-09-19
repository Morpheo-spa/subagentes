"""The compose base file is what production runs, so it is tested like code.

Audit E-06 and E-15: the dashboard was open, Redis had no password, the data
stores were published, there was no TLS, and the development overlay loaded
itself. Each of those is one assertion here; the development conveniences are
expected to live in docker-compose.dev.yml, which Compose only reads when it is
named with -f.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yml"
DEV_COMPOSE = REPO_ROOT / "docker-compose.dev.yml"
TRAEFIK_STATIC = REPO_ROOT / "infra" / "traefik" / "traefik.yml"
TRAEFIK_DEV_STATIC = REPO_ROOT / "infra" / "traefik" / "traefik.dev.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
CHECK_ENV = REPO_ROOT / "scripts" / "check_env.py"


def load_compose(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def services(path: Path) -> dict[str, Any]:
    return load_compose(path)["services"]


def load_check_env() -> Any:
    """check_env.py is a standalone script, not a package: load it by path."""
    spec = importlib.util.spec_from_file_location("check_env", CHECK_ENV)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- E-15: the development overlay must not load itself ----------------------


def test_there_is_no_auto_loaded_override_file() -> None:
    assert not (REPO_ROOT / "docker-compose.override.yml").exists()
    assert DEV_COMPOSE.is_file()


def test_only_the_dev_overlay_builds_the_dev_images() -> None:
    for name, service in services(BASE_COMPOSE).items():
        target = service.get("build", {}).get("target")
        assert target in (None, "runtime"), f"{name} builds {target} in the base file"

    dev_targets = {
        name: service.get("build", {}).get("target")
        for name, service in services(DEV_COMPOSE).items()
        if service.get("build")
    }
    assert set(dev_targets.values()) == {"dev"}


def test_debug_is_only_switched_on_by_the_dev_overlay() -> None:
    for name, service in services(BASE_COMPOSE).items():
        environment = service.get("environment") or {}
        assert "DEBUG" not in environment, f"{name} sets DEBUG in the base file"
    assert services(DEV_COMPOSE)["api"]["environment"]["DEBUG"] == "true"


# --- E-06: nothing but the proxy is published --------------------------------


def test_the_base_stack_publishes_only_http_and_https() -> None:
    published = {
        name: service.get("ports", [])
        for name, service in services(BASE_COMPOSE).items()
        if service.get("ports")
    }
    assert set(published) == {"traefik"}
    assert published["traefik"] == ["80:80", "443:443"]


def test_the_dev_overlay_publishes_only_to_localhost() -> None:
    for name, service in services(DEV_COMPOSE).items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} to the world"


def test_redis_requires_a_password() -> None:
    """Redis holds the JWT blacklist and the Dramatiq broker (audit E-06)."""
    command = services(BASE_COMPOSE)["redis"]["command"]
    assert "--requirepass" in command
    assert any("REDIS_PASSWORD" in str(part) for part in command)
    assert not services(BASE_COMPOSE)["redis"].get("ports")


def test_the_data_stores_have_no_built_in_credentials() -> None:
    store_env = {
        name: services(BASE_COMPOSE)[name].get("environment", {})
        for name in ("postgres", "garage")
    }
    required = [
        value
        for environment in store_env.values()
        for key, value in environment.items()
        if "PASSWORD" in key or key in {"GARAGE_RPC_SECRET", "GARAGE_ADMIN_TOKEN"}
    ]
    assert required, "expected credential variables on postgres and garage"
    for value in required:
        assert ":?" in value, f"{value} still has a built-in default"


def test_every_service_forbids_privilege_escalation() -> None:
    for name, service in services(BASE_COMPOSE).items():
        assert "no-new-privileges:true" in service.get("security_opt", []), name


# --- E-06: TLS and the dashboard ---------------------------------------------


def test_the_production_proxy_serves_tls_and_hides_its_dashboard() -> None:
    static = yaml.safe_load(TRAEFIK_STATIC.read_text(encoding="utf-8"))

    assert static["api"]["insecure"] is False
    assert static["api"]["dashboard"] is False
    assert static["entryPoints"]["web"]["http"]["redirections"]["entryPoint"]["to"] == "websecure"
    assert static["entryPoints"]["websecure"]["http"]["tls"]["certResolver"] == "letsencrypt"
    assert "letsencrypt" in static["certificatesResolvers"]
    addresses = {entry["address"] for entry in static["entryPoints"].values()}
    assert addresses == {":80", ":443"}, "the admin entrypoint must not be declared"


def test_the_insecure_dashboard_exists_only_in_the_dev_static_config() -> None:
    dev_static = yaml.safe_load(TRAEFIK_DEV_STATIC.read_text(encoding="utf-8"))
    assert dev_static["api"]["insecure"] is True

    referenced_by = [
        path.name
        for path in (BASE_COMPOSE, DEV_COMPOSE)
        if "traefik.dev.yml" in path.read_text(encoding="utf-8")
    ]
    assert referenced_by == [DEV_COMPOSE.name]


def test_the_proxy_hop_count_matches_the_rate_limit_strategy() -> None:
    """Traefik counts X-Forwarded-For from the right; so must the API (E-10)."""
    dynamic = yaml.safe_load(
        (REPO_ROOT / "infra" / "traefik" / "dynamic" / "middlewares.yml").read_text(
            encoding="utf-8"
        )
    )
    # Traefik at the edge keys its rate limiters on the TCP peer. A depth on
    # X-Forwarded-For would read a header Traefik has already stripped at that
    # point and bucket every public client under "" (audit N-01).
    limiters = {
        name: middleware["rateLimit"]
        for name, middleware in dynamic["http"]["middlewares"].items()
        if "rateLimit" in middleware
    }
    assert {"login-ratelimit", "viewer-ratelimit"} <= set(limiters)
    for name, limiter in limiters.items():
        assert "ipStrategy" not in limiter.get("sourceCriterion", {}), name
    get_settings.cache_clear()
    assert get_settings().trusted_proxy_count == 1


# --- E-15 / E-21: the application refuses to run in debug in production ------


def test_debug_in_production_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "true")

    with pytest.raises(ValueError) as excinfo:
        get_settings()

    assert "DEBUG" in str(excinfo.value)
    get_settings.cache_clear()


def test_production_without_debug_still_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "false")

    assert get_settings().is_production is True
    get_settings.cache_clear()


# --- The deploy-time gate ----------------------------------------------------


def test_the_template_carries_no_usable_secret() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in ("REDIS_PASSWORD", "POSTGRES_PASSWORD", "GARAGE_RPC_SECRET", "GARAGE_SECRET_KEY"):
        line = next(line for line in text.splitlines() if line.startswith(f"{key}="))
        assert "CHANGE_ME" in line, line
    assert "TRUSTED_PROXY_COUNT=1" in text


def test_check_env_rejects_redis_without_a_password() -> None:
    check_env = load_check_env()

    problems = check_env.check_redis(
        {"REDIS_URL": "redis://redis:6379/0", "REDIS_PASSWORD": "x" * 20}
    )

    assert any("carries no password" in problem for problem in problems)


def test_check_env_rejects_a_url_whose_password_drifted() -> None:
    check_env = load_check_env()

    problems = check_env.check_redis(
        {"REDIS_URL": "redis://:other@redis:6379/0", "REDIS_PASSWORD": "x" * 20}
    )

    assert any("does not match" in problem for problem in problems)


def test_check_env_rejects_default_object_store_credentials() -> None:
    check_env = load_check_env()

    assert check_env.check_object_store({"GARAGE_ACCESS_KEY": "minioadmin"})
    assert check_env.check_object_store({"GARAGE_ACCESS_KEY": "estampa"})
    assert check_env.check_object_store({"GARAGE_RPC_SECRET": "short"})
    assert check_env.check_object_store({"GARAGE_ACCESS_KEY": "GKnothex"})
    assert not check_env.check_object_store(
        {
            "GARAGE_RPC_SECRET": "ab" * 32,
            "GARAGE_ACCESS_KEY": "GK" + "0f" * 12,
            "GARAGE_SECRET_KEY": "9c" * 32,
        }
    )


def test_check_env_rejects_a_proxy_without_tls(tmp_path: Path) -> None:
    check_env = load_check_env()
    insecure = tmp_path / "traefik.yml"
    insecure.write_text(
        "api:\n  dashboard: true\n  insecure: true\nentryPoints:\n  web:\n    address: ':80'\n",
        encoding="utf-8",
    )

    problems = check_env.check_tls({"TRAEFIK_STATIC_CONFIG": "traefik.yml"}, tmp_path)

    assert any("without authentication" in problem for problem in problems)
    assert any("HTTP-to-HTTPS" in problem for problem in problems)
    assert any("certificate resolver" in problem for problem in problems)


def test_check_env_accepts_the_shipped_production_proxy_config() -> None:
    """Only the example ACME address should stand between it and deployable."""
    check_env = load_check_env()

    problems = check_env.check_tls({"TRAEFIK_STATIC_CONFIG": str(TRAEFIK_STATIC)}, REPO_ROOT)

    assert problems == [f"{TRAEFIK_STATIC.name}: the ACME contact is still the example address"]


# --- N-07: what the edge spools is bounded too ---------------------------------


def test_the_api_router_caps_requests_in_flight_and_spools_to_a_bounded_tmpfs() -> None:
    import yaml

    dynamic = yaml.safe_load(
        (REPO_ROOT / "infra" / "traefik" / "dynamic" / "middlewares.yml").read_text(
            encoding="utf-8"
        )
    )
    middlewares = dynamic["http"]["middlewares"]
    assert middlewares["api-inflight"]["inFlightReq"]["amount"] <= 64
    body_limit = middlewares["upload-body-limit"]["buffering"]["maxRequestBodyBytes"]
    api_ceiling = (100 * 5 + 1) * 1024 * 1024
    assert api_ceiling < body_limit <= api_ceiling + 64 * 1024 * 1024

    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    api = compose["services"]["api"]
    labels = "\n".join(api["labels"])
    assert "api-inflight@file" in labels
    spool = "/" + "tmp:size="  # noqa: S108 - a compose mount spec, not a path we open
    assert any(mount.startswith(spool) for mount in api["tmpfs"])


# --- scripts/make_secrets.py: the one secrets command that works on Windows too


def test_make_secrets_fills_every_placeholder_consistently(tmp_path: Path) -> None:
    import subprocess
    import sys

    target = tmp_path / ".env"
    target.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    script = REPO_ROOT / "scripts" / "make_secrets.py"

    subprocess.run([sys.executable, str(script), str(target)], check=True, capture_output=True)  # noqa: S603

    text = target.read_text(encoding="utf-8")
    assert not [
        line
        for line in text.splitlines()
        if "CHANGE_ME" in line and "=" in line and not line.startswith("#")
    ]
    env = dict(
        line.split("=", 1)
        for line in text.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    # check_env.py is the authority on whether the halves agree.
    spec = importlib.util.spec_from_file_location(
        "check_env", REPO_ROOT / "scripts" / "check_env.py"
    )
    assert spec is not None and spec.loader is not None
    check_env = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check_env)
    assert check_env.check_redis(env) == []
    assert check_env.check_postgres(env) == []
    assert check_env.check_object_store(env) == []
    assert check_env.check_storage_key(env) == []
    assert check_env.check_secrets(env) == []


def test_the_object_store_is_garage_with_a_read_only_config_and_no_console() -> None:
    garage = services(BASE_COMPOSE)["garage"]
    assert garage["image"].startswith("dxflrs/garage:v")
    assert not garage.get("ports"), "Garage is reachable only inside the compose network"
    assert any(mount.endswith("/etc/garage.toml:ro") for mount in garage["volumes"])
    config = (REPO_ROOT / "infra" / "garage" / "garage.toml").read_text(encoding="utf-8")
    assert "rpc_secret =" not in config, "the RPC secret comes from the environment, not the file"
    assert "admin_token =" not in config
    assert 'api_bind_addr = "[::]:3900"' in config
