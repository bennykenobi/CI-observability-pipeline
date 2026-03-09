param(
    [Parameter(Mandatory = $true)] [string] $ProjectId,
    [Parameter(Mandatory = $true)] [string] $Region,
    [Parameter(Mandatory = $true)] [string] $Image,
    [Parameter(Mandatory = $true)] [string] $ServiceAccount,
    [Parameter(Mandatory = $true)] [string] $WebhookSecretName,
    [Parameter(Mandatory = $true)] [string] $WebhookAuthTokenSecretName,
    [Parameter(Mandatory = $true)] [string] $PubSubTopic,
    [Parameter(Mandatory = $false)] [string] $ReplayStoreUrl = "",
    [Parameter(Mandatory = $false)] [string] $ReplayStoreKeyPrefix = "ci-obs:replay"
)

if ([string]::IsNullOrWhiteSpace($ReplayStoreUrl)) {
  $envVars = "CI_OBS_PUBSUB_TOPIC=$PubSubTopic"
}
else {
  $envVars = "CI_OBS_PUBSUB_TOPIC=$PubSubTopic,CI_OBS_REPLAY_STORE_URL=$ReplayStoreUrl,CI_OBS_REPLAY_STORE_KEY_PREFIX=$ReplayStoreKeyPrefix"
}

gcloud run deploy ci-observability-webhook `
  --project $ProjectId `
  --region $Region `
  --image $Image `
  --platform managed `
  --allow-unauthenticated `
  --service-account $ServiceAccount `
  --set-env-vars $envVars `
  --set-secrets "CI_OBS_WEBHOOK_SECRET=$WebhookSecretName:latest,CI_OBS_WEBHOOK_AUTH_TOKEN=$WebhookAuthTokenSecretName:latest"

