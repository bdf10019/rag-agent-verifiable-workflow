from __future__ import annotations

import yaml

from opsflow_agent.settings import PROJECT_ROOT


def test_compose_has_restricted_runtime() -> None:
    compose = yaml.safe_load((PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8"))
    app = compose["services"]["app"]

    assert app["read_only"] is True
    assert app["cap_drop"] == ["ALL"]
    assert app["security_opt"] == ["no-new-privileges:true"]
    assert app["environment"]["OPSFLOW_DATABASE_PATH"] == "/app/data/opsflow.db"


def test_kubernetes_manifests_are_valid_yaml() -> None:
    deployment_path = PROJECT_ROOT / "infra" / "k8s" / "deployment.yaml"
    documents = list(yaml.safe_load_all(deployment_path.read_text(encoding="utf-8")))
    service = yaml.safe_load(
        (PROJECT_ROOT / "infra" / "k8s" / "service.yaml").read_text(encoding="utf-8")
    )

    assert [item["kind"] for item in documents] == ["PersistentVolumeClaim", "Deployment"]
    deployment = documents[1]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert deployment["spec"]["replicas"] == 1
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert service["kind"] == "Service"


def test_dockerfile_uses_non_root_numeric_user_and_healthcheck() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER 10001:10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "--no-deps ." in dockerfile
