param(
    [Parameter(Mandatory = $true)] [string] $ProjectId,
    [Parameter(Mandatory = $true)] [string] $Region,
    [Parameter(Mandatory = $true)] [string] $Image,
    [Parameter(Mandatory = $true)] [string] $CloudSqlInstanceConnectionName,
    [Parameter(Mandatory = $true)] [string] $GithubAppId,
    [Parameter(Mandatory = $true)] [string] $GithubPrivateKeySecretName,
    [Parameter(Mandatory = $true)] [string] $DatabaseUrlSecretName
)

gcloud run deploy ci-observability-worker `
  --project $ProjectId `
  --region $Region `
  --image $Image `
  --platform managed `
  --no-allow-unauthenticated `
  --add-cloudsql-instances $CloudSqlInstanceConnectionName `
  --set-env-vars "CI_OBS_GITHUB_APP_ID=$GithubAppId" `
  --set-secrets "CI_OBS_GITHUB_APP_PRIVATE_KEY=$GithubPrivateKeySecretName:latest,CI_OBS_DATABASE_URL=$DatabaseUrlSecretName:latest"
