# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: quantum-service | Owner: Nanda | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README:
# no fabricated data, no invented metrics, every surrogate or fallback is
# clearly labelled, and no quantum speedup is ever claimed.

"""Version-consistency contract: the package version, config, and /health must
never drift from each other (a stale health version is a deployment trap)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import __version__, config
from app.main import app

client = TestClient(app)


def test_config_version_derives_from_package_version() -> None:
    assert config.SERVICE_VERSION == __version__


def test_health_reports_the_same_version_as_fastapi() -> None:
    body = client.get("/health").json()["data"]
    assert body["version"] == config.SERVICE_VERSION == __version__