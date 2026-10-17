"""Independent checks of authority boundaries and honest map/task state reporting."""
import asyncio
import copy
import json

import pytest
from geonexus.registration import RegistrationError

from geo_harness.core import read_json, write_private
from geo_harness.workbench import Workbench, model_schema, public_value


def test_saved_case_listing_does_not_probe_remote_nodes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from geo_harness.app import create_app
    app = create_app(tmp_path)
    calls = []

    async def remote_probe():
        calls.append('probe')
        raise AssertionError('Saved-case browsing must not depend on a remote node.')

    monkeypatch.setattr(app.state.resource_nodes, 'refresh', remote_probe)
    monkeypatch.setattr(app.state.workbench, 'cases', lambda: {'templates': [], 'saved': [{'id': 'completed-case'}]})
    with TestClient(app) as client:
        assert client.get('/api/workbench/cases').status_code == 401
        client.get('/')
        response = client.get('/api/workbench/cases')
        assert response.status_code == 200
        assert response.json()['saved'] == [{'id': 'completed-case'}]
        assert calls == []


class InstalledProducts:
    def __init__(self, root, *, visibility="public", permissions=None, kind="workflow"):
        self.root = root / "installed-test-product"
        self.root.mkdir(parents=True)
        self.installed = {"reviewed.operator": {"enabled": True, "digest": "sha256:" + "a" * 64,
            "version": "1.0.0", "permissions": permissions if permissions is not None else ["connector:execute", "connector:read"]}}
        self.manifest = {"id": "reviewed.operator", "name": "Reviewed operator", "visibility": visibility,
            "version": "1.0.0", "binding": "binding.json", "cards": ["card.json"]}
        write_private(self.root / "card.json", {"geocard_version": "1.0", "id": "reviewed.operator", "type": kind,
            "name": "Reviewed operator", "description": "Known source and contract", "source": {"url": "https://example.org/open-data"}})
        write_private(self.root / "binding.json", {"tool": "reviewed.run", "source_id": "platform", "node_ref": "reviewed-node",
            "input_schema": {"type": "object", "properties": {
                "radius": {"type": "number", "minimum": 0, "maximum": 100},
                "session_token": {"type": "string", "writeOnly": True, "x-internal": True}},
                "required": ["radius", "session_token"], "additionalProperties": False}})

    def active_path(self, identity):
        if identity != "reviewed.operator" or not self.installed.get(identity, {}).get("enabled"):
            raise RegistrationError("Install and enable this product first.")
        return self.root

    def verify(self, path):
        assert path == self.root
        return copy.deepcopy(self.manifest)

    def catalog(self):
        return []


class TestSettings:
    __test__ = False
    value = {"llm": {"api_key": "private-llm-test-key", "model": "test-model"}}

    def public(self):
        return {"llm": {"model": "test-model", "api_key_configured": True}}


class SavedResults:
    def __init__(self):
        self.saved = []

    def save(self, product_id, tool, result):
        self.saved.append(result)
        return {"id": "b" * 32, "provenance": {"source": "https://example.org/open-data"},
            "limitations": ["Demonstration input"], "synthetic": False,
            "artifacts": [{"name": "buffer.geojson", "access_token": "private-artifact-test-token", "sha256": "c" * 64}]}


def build(tmp_path, *, permissions=None, visibility="public", result=None, kind="workflow"):
    products = InstalledProducts(tmp_path, visibility=visibility, permissions=permissions, kind=kind)
    saved = SavedResults(); calls = []

    async def invoke(identity, body):
        calls.append((identity, body))
        return result or {"status": "succeeded", "outputs": {"status": "succeeded", "summary": {"count": 1}}}

    workbench = Workbench(tmp_path, products, None, saved, TestSettings(), invoke)
    return workbench, products, saved, calls


def test_requested_map_view_never_masquerades_as_an_observed_viewer(tmp_path):
    async def check():
        w, _, _, _ = build(tmp_path)
        assert w.context()["viewer_connected"] is False
        initial = copy.deepcopy(w.context()["viewport"])
        action = await w.action("view.set", {"center": [121.5, 30.2], "zoom": 10}, 0, "http://127.0.0.1:8810")
        assert action["status"] == "pending"
        assert w.context()["viewer_connected"] is False
        # A requested view must remain distinct from actual observed GeoLibre context.
        assert not w.state.get("observed", {}).get("time")
        w.sync({"viewport": {"center": [121.4, 30.1], "zoom": 9}})
        assert w.context()["viewer_connected"] is True
        assert w.context()["viewport"]["center"] == [121.4, 30.1]
        assert w.ack(action["id"], {"ok": True})["status"] == "completed"
        assert initial != w.context()["viewport"]
        await w.close()
    asyncio.run(check())


def test_stale_map_revision_and_unknown_layer_do_not_mutate_project(tmp_path):
    async def check():
        w, _, _, _ = build(tmp_path)
        first = await w.action("view.set", {"center": [120, 30]}, 0, "http://testserver")
        before = copy.deepcopy(w.state)
        with pytest.raises(RegistrationError):
            await w.action("view.set", {"center": [10, 10]}, 0, "http://testserver")
        with pytest.raises(RegistrationError):
            await w.action("layer.remove", {"layer_id": "other-user-private-layer"}, first["revision"], "http://testserver")
        assert w.state == before
        assert w.ack(first["id"], {"ok": False, "error": "Viewer rejected"})["status"] == "failed"
        await w.close()
    asyncio.run(check())


@pytest.mark.parametrize("arguments", [{"center": [float("nan"), 30]}, {"center": [181, 30]},
    {"center": [120, 91]}, {"center": [120, 30], "url": "file:///etc/passwd"}])
def test_map_actions_reject_invalid_coordinates_and_arbitrary_inputs(tmp_path, arguments):
    async def check():
        w, _, _, _ = build(tmp_path)
        before = copy.deepcopy(w.state)
        with pytest.raises(RegistrationError):
            await w.action("view.set", arguments, 0, "http://testserver")
        assert w.state == before
        await w.close()
    asyncio.run(check())


def test_model_schema_removes_nested_private_contract_fields_and_requirements():
    schema = {"type": "object", "properties": {"parameters": {"type": "object", "properties": {
        "radius": {"type": "number"},
        "private_endpoint_credential": {"type": "string", "writeOnly": True, "default": "sensitive-default"},
        "owner_scope": {"type": "string", "x-internal": True, "default": "private-owner"}},
        "required": ["radius", "private_endpoint_credential", "owner_scope"]}}, "required": ["parameters"]}
    public = model_schema(schema)
    packed = json.dumps(public)
    assert "sensitive-default" not in packed
    assert "private-owner" not in packed
    assert "private_endpoint_credential" not in public["properties"]["parameters"]["properties"]
    assert public["properties"]["parameters"]["required"] == ["radius"]
    assert schema["properties"]["parameters"]["required"] == ["radius", "private_endpoint_credential", "owner_scope"]


@pytest.mark.parametrize("change", ["not_installed", "disabled", "no_grant", "stale_digest", "arbitrary_file"])
def test_generic_execute_checks_installation_grants_digest_and_arguments_before_dispatch(tmp_path, change):
    async def check():
        w, p, saved, calls = build(tmp_path)
        identity, digest, args = "reviewed.operator", p.installed["reviewed.operator"]["digest"], {"radius": 20}
        if change == "not_installed": identity = "unknown.operator"
        elif change == "disabled": p.installed[identity]["enabled"] = False
        elif change == "no_grant": p.installed[identity]["permissions"] = ["connector:read"]
        elif change == "stale_digest": digest = "sha256:" + "d" * 64
        else: args["path"] = "/etc/passwd"
        with pytest.raises(RegistrationError):
            await w.submit(identity, args, digest)
        assert not w.jobs and not calls and not saved.saved
        await w.close()
    asyncio.run(check())


def test_restricted_product_is_not_exposed_to_model_search_or_execution(tmp_path):
    async def check():
        w, p, _, calls = build(tmp_path, visibility="private")
        with pytest.raises(RegistrationError): w.describe("reviewed.operator")
        assert w.search("Reviewed") == []
        # User UI may inspect its private contract, but model-backed general execution is public-only.
        assert w.describe("reviewed.operator", for_model=False)["product_id"] == "reviewed.operator"
        with pytest.raises(RegistrationError):
            await w.submit("reviewed.operator", {"radius": 10}, p.installed["reviewed.operator"]["digest"])
        assert not calls
        await w.close()
    asyncio.run(check())


@pytest.mark.parametrize("state", ["queued", "pending", "waiting", "unknown"])
def test_incomplete_or_unknown_node_state_cannot_be_saved_as_completed_result(tmp_path, state):
    async def check():
        w, p, saved, _ = build(tmp_path, result={"outputs": {"state": state}})
        row = await w.submit("reviewed.operator", {"radius": 10}, p.installed["reviewed.operator"]["digest"])
        await w.tasks[row["id"]]
        assert w.status(row["id"])["status"] != "completed"
        assert not saved.saved
        with pytest.raises(RegistrationError): w.save_case(row["id"], "Unfinished case")
        await w.close()
    asyncio.run(check())


def test_private_session_injection_is_internal_and_saved_cases_have_no_credentials(tmp_path):
    async def check():
        w, p, _, calls = build(tmp_path)
        schema = w.describe("reviewed.operator")["input_schema"]
        assert "session_token" not in schema["properties"]
        row = await w.submit("reviewed.operator", {"radius": 10}, p.installed["reviewed.operator"]["digest"])
        await w.tasks[row["id"]]
        assert calls[0][1]["arguments"]["session_token"] == w.node_session
        status = w.status(row["id"])
        assert w.node_session not in json.dumps(status)
        assert "private-artifact-test-token" not in json.dumps(status)
        saved = w.save_case(row["id"], "Reproducible reviewed run")
        exported = w.saved_case(saved["id"])
        text = json.dumps(exported)
        assert w.node_session not in text and "private-artifact-test-token" not in text
        assert exported["recipe"]["steps"][0]["arguments"] == {"radius": 10}
        for invalid in ["../private-node-session", "/tmp/secret", "f" * 32]:
            with pytest.raises(RegistrationError): w.saved_case(invalid)
        assert (w.root / "private-node-session.json").stat().st_mode & 0o777 == 0o600
        assert (w.root / "cases" / saved["id"] / "recipe.json").stat().st_mode & 0o777 == 0o600
        await w.close()
    asyncio.run(check())


def test_provider_error_does_not_echo_private_llm_key_to_chat_events(tmp_path):
    class FailingSettings(TestSettings):
        async def completion(self, *_):
            raise ValueError("Unexpected provider payload containing private-llm-test-key")
    async def check():
        w, _, _, _ = build(tmp_path)
        w.settings = FailingSettings()
        events = [event async for event in w.chat({"message": "Read my map"}, "http://testserver", {"definitions": {}, "run": None})]
        assert events[-1]["type"] == "error"
        assert "private-llm-test-key" not in json.dumps(events)
        await w.close()
    asyncio.run(check())


def test_result_open_rechecks_revision_after_awaiting_remote_map_artifacts(tmp_path):
    """Two tabs of the same account must not silently overwrite one another's map."""
    async def check():
        w, _, _, _ = build(tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()

        class SlowResults:
            root = tmp_path / "slow-map-results"

            async def map(self, identity, base_url):
                entered.set(); await release.wait()
                write_private(self.root / identity / "map.geolibre.json", {
                    "name": "Remote result", "layers": [], "mapView": {"center": [10, 10], "zoom": 5}})

            def record(self, identity):
                return {"product_id": "reviewed.operator"}

        w.results = SlowResults()
        first = asyncio.create_task(w.action("result.open", {"result_id": "e" * 32}, 0, "http://testserver"))
        await entered.wait()
        second = asyncio.create_task(w.action("view.set", {"center": [120, 30]}, 0, "http://testserver"))
        await asyncio.sleep(0)
        release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 3)
        assert sum(isinstance(item, dict) for item in outcomes) == 1
        assert sum(isinstance(item, RegistrationError) for item in outcomes) == 1
        assert w.state["revision"] == 1
        assert len(w.state["actions"]) == 1
        await w.close()
    asyncio.run(check())


def test_private_map_summary_never_enters_remote_model_context(tmp_path):
    async def check():
        w, _, _, _ = build(tmp_path)
        w.state["project"] = {"name": "Private research region", "metadata": {"modelVisibility": "restricted"},
            "mapView": {"center": [120, 30], "zoom": 12}, "layers": [{"id": "private-site", "name": "Sensitive nesting site",
                "type": "geojson", "geojson": {"features": [{"properties": {"private-survey-person": "Alice"}}]}}]}
        w.sync({"viewport": {"center": [120, 30], "zoom": 12}, "selection": {"layerId": "private-site", "featureId": "private-observation"}})
        public = w.context(for_model=True)
        packed = json.dumps(public)
        assert "Private research region" not in packed and "Sensitive nesting site" not in packed
        assert "private-survey-person" not in packed and "private-observation" not in packed
        assert public["layers"] == [] and public["selection"] is None and public["viewport"] == {}
        assert w.context()["layers"][0]["name"] == "Sensitive nesting site"
        await w.close()
    asyncio.run(check())


def test_agent_refuses_execution_and_installation_tools_not_authorized_for_this_turn(tmp_path):
    class MaliciousModel(TestSettings):
        step = 0

        async def completion(self, messages, definitions):
            self.step += 1
            exposed = {d["function"]["name"] for d in definitions}
            assert "operator_execute" not in exposed and "product_install" not in exposed
            if self.step == 1:
                return {"choices": [{"message": {"role": "assistant", "tool_calls": [
                    {"id": "unauthorized-run", "function": {"name": "operator_execute", "arguments": json.dumps({"product_id": "reviewed.operator", "arguments": {"radius": 1}, "expected_digest": "a" * 64})}},
                    {"id": "install-code", "function": {"name": "product_install", "arguments": "{}"}}]}}]}
            return {"choices": [{"message": {"role": "assistant", "content": "No execution was authorized."}}]}

    async def check():
        w, _, _, calls = build(tmp_path)
        w.settings = MaliciousModel()
        events = [event async for event in w.chat({"message": "Inspect only", "allow_execution": False}, "http://testserver", {"definitions": {}, "run": None})]
        returned = [event for event in events if event["type"] == "tool_result"]
        assert len(returned) == 2 and all(event["status"] == "failed" for event in returned)
        assert not calls and not w.jobs
        assert events[-1]["type"] == "done"
        await w.close()
    asyncio.run(check())


def test_restart_never_keeps_unacknowledged_map_actions_pending_forever(tmp_path):
    async def check():
        w, products, saved, _ = build(tmp_path)
        action = await w.action('view.set', {'center': [114, 30]}, 0, 'http://testserver')
        await w.close()
        resumed = Workbench(tmp_path, products, None, saved, TestSettings(), w.invoke)
        assert resumed.state['actions'][0]['status'] == 'unconfirmed'
        assert not resumed.context()['pending_actions']
        assert resumed.context()['viewer_connected'] is False
        await resumed.close()
    asyncio.run(check())


def test_projection_action_keeps_layers_and_view_and_requires_viewer_ack(tmp_path):
    async def check():
        workbench, _, _, calls = build(tmp_path)
        assert workbench.state['project']['mapView']['center'] == [125, 25]
        workbench.state['project']['layers'] = [{'id': 'current-raster', 'name': 'Current raster', 'metadata': {'handle': 'session-local'}}]
        original = copy.deepcopy(workbench.state['project'])
        result = await workbench.action('view.projection', {'projection': 'globe'}, workbench.state['revision'], 'http://127.0.0.1:8810')
        assert result['status'] == 'pending'
        assert result['commands'] == [{'type': 'setProjection', 'payload': {'projection': 'globe'}}]
        assert workbench.state['project']['layers'] == original['layers']
        assert workbench.state['project']['mapView'] == original['mapView']
        assert workbench.context()['projection'] == 'globe'
        workbench.ack(result['id'], {'ok': True})
        with pytest.raises(RegistrationError):
            await workbench.action('view.projection', {'projection': 'invalid'}, workbench.state['revision'], 'http://127.0.0.1:8810')
        assert not calls
        await workbench.close()
    asyncio.run(check())
