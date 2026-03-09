# GitHub App Setup

This runbook covers creation and installation of the GitHub App used by the worker service to read GitHub Actions run, job, and step metadata across multiple repositories.

Keep this separate from GCP bootstrap:

- GitHub App setup is not GCP-specific
- it has its own security-sensitive decisions
- the private key should be generated and handled carefully before it is stored in Secret Manager

## Goal

Create a GitHub App that can:

- read workflow run metadata
- read workflow job and step metadata
- be installed on multiple repositories
- provide a private key and App ID for the worker service

## 1. Create the app

In GitHub:

- go to `Settings` -> `Developer settings` -> `GitHub Apps`
- click `New GitHub App`

Suggested app name:

- something organization-scoped and clear, for example:
  - `ci-observability-ingestion`

Recommended homepage URL:

- your repository URL
- or a short internal landing page if you have one

Webhook URL and webhook secret:

- the platform ingests native GitHub `workflow_run` webhooks
- if you are using the GitHub App as the webhook delivery source, point it at:
  - `https://YOUR_WEBHOOK_SERVICE_URL/github/webhook`
- use the same secret you store as `ci-obs-webhook-secret`
- enable SSL verification
- if your organization uses repository-level or org-managed webhooks instead of GitHub App webhook delivery, you may use a temporary valid HTTPS URL during app creation and configure the actual webhook separately afterward

OAuth callback URL:

- not used by this project
- if GitHub requires it, use a harmless stable URL you control such as the repository URL
- this is not the same thing as the runtime callback endpoint implemented by this project

## 2. Set permissions

Repository permissions:

- `Actions: Read-only`
- `Contents: Read-only`
- `Metadata: Read-only`

Those are the minimum expected permissions for the current worker behavior.

Do not grant write permissions unless a future feature explicitly needs them.

## 3. Subscribe to events

Subscribe to:

- `workflow_run`

The worker still relies on GitHub App authentication for API calls even when webhook delivery is configured outside the app.

## 4. Create the app and capture identifiers

After creation, record:

- GitHub App ID
- App slug

The App ID will be needed as a worker environment variable.

## 5. Generate the private key

From the app settings page:

- generate a private key
- download the PEM file

Treat the PEM file as secret material:

- do not commit it
- do not place it in the repo
- keep it in a secure local path temporarily
- store its contents in Secret Manager as `ci-obs-github-app-private-key`

## 6. Install the app

Install it on the repositories you want to monitor.

For this project, install it on:

- the repositories whose workflow runs will be ingested
- the repositories that call the reusable workflows you want to observe

If your goal is zero repo-by-repo installation work, install the app at the organization level and choose `All repositories`.

If you want a smaller blast radius for the first test, start with a bounded repo set and expand later.

## 7. Verify access

Before deployment, confirm:

- the app is installed on the intended repos
- the permissions are read-only and sufficient
- the private key is stored in Secret Manager
- the App ID is recorded for worker deployment

## 8. Values needed by this project

After GitHub App setup, you should have:

- `CI_OBS_GITHUB_APP_ID`
- `ci-obs-github-app-private-key`

The worker service needs both.

The GitHub App client secret is not needed for the current architecture.

## Security notes

- Do not store the PEM key in the repository.
- Do not paste the PEM into shell history if you can avoid it.
- Keep permissions read-only.
- Install the app only on the repositories required for the MVP first.
