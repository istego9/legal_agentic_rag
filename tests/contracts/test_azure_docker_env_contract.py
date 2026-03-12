from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_COMPOSE_PATH = REPO_ROOT / "infra" / "docker" / "docker-compose.yml"
DOCKER_ENV_EXAMPLE_PATH = REPO_ROOT / "infra" / "docker" / ".env.example"
REQUIRED_AZURE_VARS = (
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_MAX_TOKENS",
    "AZURE_OPENAI_TEMPERATURE",
    "AZURE_OPENAI_TIMEOUT_SECONDS",
    "AZURE_OPENAI_TOP_P",
    "AZURE_OPENAI_TRIES",
    "AZURE_OPENAI_TOKEN_PARAMETER",
    "AZURE_OPENAI_REASONING_EFFORT",
    "CORPUS_METADATA_NORMALIZER_PROVIDER",
    "CORPUS_METADATA_NORMALIZER_DEPLOYMENT",
    "CORPUS_METADATA_NORMALIZER_MODEL",
    "CORPUS_METADATA_NORMALIZER_MAX_TOKENS",
    "CORPUS_METADATA_NORMALIZER_TIMEOUT_SECONDS",
    "CORPUS_METADATA_NORMALIZER_TOKEN_PARAMETER",
    "CORPUS_METADATA_NORMALIZER_REASONING_EFFORT",
)

REQUIRED_OPENAI_VARS = (
    "LLM_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "OPENAI_MAX_TOKENS",
    "OPENAI_TEMPERATURE",
    "OPENAI_TIMEOUT_SECONDS",
    "OPENAI_TOP_P",
    "OPENAI_TRIES",
    "OPENAI_TOKEN_PARAMETER",
    "OPENAI_REASONING_EFFORT",
    "OPENAI_SERVICE_TIER",
)


def test_docker_compose_exposes_required_azure_env_vars() -> None:
    compose_text = DOCKER_COMPOSE_PATH.read_text(encoding="utf-8")

    for env_name in REQUIRED_AZURE_VARS:
        assert env_name in compose_text, f"{env_name} is not wired into infra/docker/docker-compose.yml"


def test_docker_env_example_lists_required_azure_vars() -> None:
    env_example_text = DOCKER_ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    for env_name in REQUIRED_AZURE_VARS:
        assert f"{env_name}=" in env_example_text, f"{env_name} is missing from infra/docker/.env.example"

    for env_name in REQUIRED_OPENAI_VARS:
        assert f"{env_name}=" in env_example_text, f"{env_name} is missing from infra/docker/.env.example"
