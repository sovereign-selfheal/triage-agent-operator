# triage-agent-operator

A small [kopf](https://kopf.readthedocs.io/)-based Kubernetes operator that reconciles
`TriageAgent` custom resources (`triage.sovereign-selfheal.io/v1alpha1`). Each `TriageAgent`
CR deploys one dedicated triage-agent stack (Gradio UI + OGX sidecar, Service, Route, API
key, OGX config, knowledge ConfigMap) in its own namespace, so that namespace's applications
can be troubleshot by an agent that lives next to them.

This lets the platform deploy "one triage-agent per namespace" declaratively, instead of
copy-pasting the `triage-agent` Helm chart per namespace.

## Custom Resource

See [`deploy/crd.yaml`](deploy/crd.yaml) for the full schema and
[`deploy/example-triageagent.yaml`](deploy/example-triageagent.yaml) for a worked example.

```yaml
apiVersion: triage.sovereign-selfheal.io/v1alpha1
kind: TriageAgent
metadata:
  name: triage-agent
  namespace: my-app-namespace
spec:
  router:
    url: https://router.apps.example.com/v1
  mcpServers:
    prometheus: http://prometheus-mcp-server.my-app-namespace.svc:8080/mcp
```

Every field besides `spec.router.url` has an operator-side default (see
[`app/config.py`](app/config.py)).

## What the operator creates per CR

| Resource | Name | Notes |
|---|---|---|
| ServiceAccount | `<cr.name>` | Pod identity |
| ConfigMap | `<cr.name>-ogx-config` | OGX `stack_run_config.yaml` |
| ConfigMap | `<cr.name>-knowledge` | Only when `spec.knowledge.configMapName` is empty |
| Secret | `<cr.name>-apikey` | Only when `spec.apiKey.existingSecret` is empty; plain `Secret`, not ESO (no in-cluster secret store dependency for the operator) |
| Deployment | `<cr.name>` | `ogx-server` + `triage-agent` containers |
| Service | `<cr.name>` | Port 7860 |
| Route | `<cr.name>` | Only when `spec.route.enabled` (default `true`) |

All child resources carry an owner reference to the `TriageAgent` CR, so deleting the CR
cascades. The operator reports progress in `status.phase`, `status.routeUrl` and
`status.conditions`.

## Run locally (against a real cluster, out-of-cluster)

```bash
pip install -r requirements-dev.txt
oc apply -f deploy/crd.yaml
kopf run --all-namespaces -m app.operator --verbose
```

## Build

```bash
podman build -t quay.io/sovereign-selfheal/triage-agent-operator:<tag> .
```

CI (`.github/workflows/lint.yml`) runs tests and a build smoke test on pull requests and
pushes to `main`. Quay builds/pushes the tagged release image separately.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests cover the resource builders in `app/resources.py` only (pure functions, no cluster
needed): given a CR spec, do they render the same shape as the existing
`components/triage-agent` Helm templates in the `gitops` repo?

## Consumer

The CRD install, the operator Deployment/RBAC, and the `TriageAgent` CR instances all live
in other repos:

- **CRD + operator Deployment + cluster RBAC:** `ansible` repo (cluster-scoped objects,
  gitops `AGENTS.md` section 2).
- **`TriageAgent` CR instances + pinned image digest:** `gitops` repo,
  `components/triage-agent-operator-cr/`.

This repo only owns the operator's Python source, its `Containerfile`, and the CRD schema
(`deploy/crd.yaml`, copied verbatim by whoever installs it).
