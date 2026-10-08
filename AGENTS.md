# AGENTS.md: `triage-agent-operator` repository

Guidance for AI coding agents and humans working in this repo. Read it fully before you
change anything.

## 1. Purpose

This repository builds **triage-agent-operator**: a [kopf](https://kopf.readthedocs.io/)
Kubernetes operator that reconciles `TriageAgent` custom resources
(`triage.sovereign-selfheal.io/v1alpha1`, see `deploy/crd.yaml`). Each CR deploys one
dedicated triage-agent stack (Gradio UI + OGX sidecar, Service, Route, API key, OGX config,
knowledge ConfigMap) in its own namespace, so that applications in that namespace get an
agent instance that troubleshoots them locally.

This operator never defines the agent's own behavior (system prompt, MCP tool list, model
selection): that logic is entirely inside the `triage-agent` image (`triage-agent/agent.py`,
a separate repo). This operator only manages the Kubernetes objects that run that image,
the same role `components/triage-agent` plays in the `gitops` repo today — but
parameterized per namespace via a CR instead of per-cluster via Helm values.

## 2. Repository structure

```
app/
  __init__.py
  operator.py      # kopf handlers: create/update/delete for TriageAgent
  resources.py      # pure functions: CR spec -> child resource manifests (dicts)
  config.py         # defaults merged into an incomplete CR spec
  status.py         # status/condition helpers
deploy/
  crd.yaml                  # TriageAgent CustomResourceDefinition
  example-triageagent.yaml  # worked example CR
tests/
  conftest.py
  test_resources.py
  test_config.py
Containerfile        # python:3.11-slim, non-root UID 1001
requirements.txt
requirements-dev.txt     # + pytest (CI/local only)
.github/workflows/lint.yml
```

No `pyproject.toml` or installable package, same flat-module pattern as `triage-agent` and
`ogx-alert-translator`.

## 3. Architecture rules

1. **One CR, one agent stack.** `apply`/`update` on a `TriageAgent` CR reconciles exactly the
   resources listed in `README.md` ("What the operator creates per CR"), all in the CR's own
   namespace. The operator never touches resources outside that namespace and never lists
   or mutates other `TriageAgent` CRs when reconciling one.
2. **Owner references everywhere.** Every child resource gets an owner reference to its
   `TriageAgent` CR (`kopf.adopt`). Deleting the CR cascades; the operator does not need an
   explicit `on.delete` cleanup handler for owned objects.
3. **Idempotent, server-side apply.** Reconciliation always re-applies the full desired
   state (no partial patches against hand-edited fields) so that repeated reconciles (and
   operator restarts) converge to the same objects.
4. **Defaults live in the operator, not the CRD.** `app/config.py` merges an incomplete
   spec with built-in defaults (images, resources, model alias, MCP URLs) before building
   resources. The CRD's OpenAPI schema defaults cover only scalar leaf fields it can
   express; `app/config.py` is the single source of truth when the two could disagree.
5. **No OGX/agent logic here.** This operator never sets a system prompt, MCP tool list, or
   knowledge content beyond what `spec.knowledge.content` or `spec.knowledge.configMapName`
   says. Changing *how* the agent behaves happens in the `triage-agent` repo, not here.
6. **Status reflects real state.** `status.phase` follows the child Deployment's own
   availability (`Pending` until the Deployment exists and is observed, `Running` once
   `status.availableReplicas >= 1`, `Degraded` otherwise). Do not report `Running` just
   because the reconcile loop didn't error.
7. **12-factor config for the operator process itself.** `LOG_LEVEL` is the only env var the
   operator process reads; everything about a given agent instance comes from its CR, never
   from the operator's own environment.

## 4. Security boundaries

| Boundary | Rule |
|---|---|
| **Identity** | Operator container runs as non-root UID **1001**. Child Pods it creates keep the same `securityContext` as the current `components/triage-agent` templates (`runAsNonRoot`, drop `ALL` capabilities, `RuntimeDefault` seccomp). |
| **RBAC** | The operator's own ServiceAccount, ClusterRole and ClusterRoleBinding (needed because it watches `--all-namespaces`) are cluster-scoped: they live in the `ansible` repo, never here. |
| **Secrets** | When `spec.apiKey.existingSecret` is empty, the operator generates a plain Kubernetes `Secret` (random token) — no External Secrets Operator dependency in the operator itself, unlike `components/triage-agent`'s ESO `Password`/`ExternalSecret` pair. If a cluster needs ESO-managed rotation, set `existingSecret` to a Secret managed by `gitops`/ESO instead. |
| **Images** | Pinned by digest wherever referenced outside this repo (`gitops`, `ansible`). This repo's own image, `quay.io/sovereign-selfheal/triage-agent-operator`, follows the same convention when consumed. |

## 5. Contract with the `gitops` repo

| Owner | Items |
|---|---|
| `triage-agent-operator` (this repo) | Python source, `Containerfile`, CI tests/build, CRD schema (`deploy/crd.yaml`), image `quay.io/sovereign-selfheal/triage-agent-operator` |
| `gitops` | `TriageAgent` CR instances (`components/triage-agent-operator-cr/`), image digest pin |
| `ansible` | CRD install (copy of `deploy/crd.yaml`), operator Deployment + ServiceAccount + ClusterRole/Binding, Argo CD health check for `TriageAgent` |

1. **CRD changes are breaking by default.** Any field rename or removal in `deploy/crd.yaml`
   needs matching updates in `gitops` (CR instances) and `ansible` (CRD install) in the same
   change window. Additive fields with sane defaults are safe to land here first.
2. **Images by digest.** Same convention as every other `sovereign-selfheal` image: comment
   with tag and resolve date in the consuming repo; bump via PR there, not here.
3. **No cluster-scoped objects here.** The CRD YAML in `deploy/` is a schema definition for
   others to install, not something this repo applies itself.

## 6. Build and CI

- **Local / CI image build:** `podman build -t localhost/triage-agent-operator:ci .`
- **Tests:** `pytest` from repo root with `requirements-dev.txt` installed. Tests exercise
  only the pure resource-builder functions (`app/resources.py`, `app/config.py`) — no live
  cluster needed.
- **Manual end-to-end check:** apply `deploy/crd.yaml` and `deploy/example-triageagent.yaml`
  to a dev cluster, run `kopf run --all-namespaces -m app.operator --verbose` out-of-cluster,
  and confirm the child resources and `status` populate.

## 7. Out of scope

- The `triage-agent` image, its system prompt, MCP tool wiring, knowledge base content
  beyond what a CR passes in, and model selection logic → `triage-agent` repo
  (`agent.py`), never duplicated here.
- MCP server deployments (`prometheus-mcp-server`, `ticketing-mcp-server`) → their own
  repos + `gitops` components. This operator only consumes MCP URLs as CR input.
- CRD installation, operator RBAC, operator Deployment → `ansible` repo.
- `TriageAgent` CR instances for a given cluster → `gitops` repo.

## 8. When in doubt

- Prefer the smallest change that keeps reconciliation idempotent and keeps the operator
  itself free of agent-specific logic (prompt, tools, knowledge format).
- Ask before changing the CRD's `apiVersion`/`group`, removing a field, or changing which
  repo owns an object.
