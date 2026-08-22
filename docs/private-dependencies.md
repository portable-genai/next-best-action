# Private catalog commons

`consent-preference-kit` is currently private. Mkt5 keeps the dependency because it is the
versioned client half of Mkt6's consent decision boundary; copying those types or the transport
back into this repo would create another contract that can drift.

The approved build posture is a read-only GitHub App, not a personal access token and not a
vendored copy. Install that app only on `consent-preference-kit`, then configure these repository
secrets:

- `CATALOG_COMMONS_APP_ID`
- `CATALOG_COMMONS_APP_PRIVATE_KEY`

CI mints a job-scoped token with `actions/create-github-app-token`, rewrites only GitHub HTTPS
fetches for that job, and lets pip resolve the commit-pinned lockfile. No token is committed or
written into an artifact.

For an image build, export a short-lived installation token and pass it as a BuildKit secret:

```bash
docker build \
  --secret id=catalog_commons_token,env=CATALOG_COMMONS_TOKEN \
  -t next-best-action:local .
```

The Dockerfile requires the secret in its builder stage, removes the temporary Git rewrite in
the same layer, and copies only the virtual environment into the runtime image. The token is not
an image build argument or environment variable, so it is absent from image history and runtime.

Local source development can install the sibling checkout directly before running the gate:

```bash
.venv/bin/pip install -e ../consent-preference-kit
```

This credential is build-time source access only. Managed runtime calls to Mkt6 use a
short-lived Google-signed ID token minted through Workload Identity for the reviewed custom
audience. For non-GCP consumers, `CONSENT_S2S_TOKEN` and optional
`CONSENT_S2S_SIGNING_KEY` are separate credentials with separate rotation and least-privilege
scopes.
