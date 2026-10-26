"""消费方契约：SDK 公共面一旦漂移，这里先红（#4）。

对应 Platform v0.9.2 与 GeoHarness 0.2.9 实际调用的四处入口。
"""

from __future__ import annotations

import inspect

import pytest


def test_geocard_contracts_surface():
    from geonexus.geocard.contracts import (
        ContractReport,
        ContractRequest,
        ResultManifest,
        validate_contract,
    )

    request = ContractRequest(bbox=[-73.9, -15, -44, 5], crs="EPSG:4326", start="2015-01-01", end="2025-12-31", required_bands=["red"])
    assert request.bbox == [-73.9, -15, -44, 5]
    assert callable(validate_contract)
    assert hasattr(ContractReport, "model_dump")
    assert hasattr(ResultManifest, "model_validate")


def test_mcp_adapter_guarded_signature():
    from geonexus.mcp_adapter import create_mcp_server

    parameters = inspect.signature(create_mcp_server).parameters
    assert "http_guarded" in parameters
    assert parameters["http_guarded"].kind is inspect.Parameter.KEYWORD_ONLY


def test_registration_helpers():
    from geonexus.registration import RegistrationError, make_draft, safe_url, validate_profile

    assert issubclass(RegistrationError, Exception)
    assert set(inspect.signature(make_draft).parameters) >= {"metadata", "kind", "operation"}
    assert set(inspect.signature(validate_profile).parameters) >= {"card", "binding"}
    assert safe_url("http://127.0.0.1:8787").startswith("http://")


def test_registry_accepts_harness_arguments():
    from geonexus.registry.server import RegistryServer

    parameters = inspect.signature(RegistryServer.__init__).parameters
    assert {"public_submissions", "api_key_principals"} <= set(parameters)
    assert "submitted_by" in inspect.signature(RegistryServer.register).parameters
