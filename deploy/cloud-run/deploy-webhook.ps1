param(
    [Parameter(Mandatory = $true)] [string] $ProjectId,
    [Parameter(Mandatory = $true)] [string] $Region,
    [Parameter(Mandatory = $true)] [string] $Image,
    [Parameter(Mandatory = $true)] [string] $ServiceAccount,
    [Parameter(Mandatory = $true)] [string] $CloudSqlInstanceConnectionName,
    [Parameter(Mandatory = $true)] [string] $WebhookSecretName,
    [Parameter(Mandatory = $true)] [string] $WebhookAuthTokenSecretName,
    [Parameter(Mandatory = $true)] [string] $PubSubTopic
)

gcloud run deploy ci-observability-webhook `
  --project $ProjectId `
  --region $Region `
  --image $Image `
  --platform managed `
  --allow-unauthenticated `
  --service-account $ServiceAccount `
  --add-cloudsql-instances $CloudSqlInstanceConnectionName `
  --set-env-vars "CI_OBS_PUBSUB_TOPIC=$PubSubTopic" `
  --set-secrets "CI_OBS_WEBHOOK_SECRET=$WebhookSecretName:latest,CI_OBS_WEBHOOK_AUTH_TOKEN=$WebhookAuthTokenSecretName:latest"

