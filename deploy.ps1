<# 
.SYNOPSIS
    Deploys the Hotel Information API and ALL supporting infrastructure to Azure.

.DESCRIPTION
    This script:
    1. Creates a resource group in Sweden Central
    2. Deploys Azure Container Registry and Container Apps infrastructure
    3. Builds and pushes the Docker image
    4. Deploys the Container App with Azure AI Foundry Bing Grounding configuration

.PARAMETER ResourceGroupName
    Name of the Azure resource group to create/use (default: rg-hotel-api-swedencentral)

.PARAMETER Location
    Azure region (default: swedencentral)

.PARAMETER BaseName
    Base name prefix for all resources (default: hotelapi)

.PARAMETER OpenAiChatModel
    OpenAI model for AI extraction, e.g. gpt-4, gpt-4o (default: gpt-4)

.PARAMETER FoundryModel
    Model for Bing Grounding agent - must support function calling (default: gpt-4.1-mini)

.PARAMETER BingSearchSku
    Pricing tier for Bing Search: S1 (production) or F1 (free) (default: S1)

.PARAMETER BingConnectionName
    Name for the Bing Grounding connection in AI Foundry (default: bing-grounding)

.PARAMETER SkipInfrastructure
    Skip infrastructure deployment - only rebuild and push the Docker image

.EXAMPLE
    # Deploy everything with defaults
    .\deploy.ps1 -ResourceGroupName "rg-hotel-api"

.EXAMPLE
    # Deploy with specific models
    .\deploy.ps1 -ResourceGroupName "rg-hotel-api" -OpenAiChatModel "gpt-4o" -FoundryModel "gpt-4.1-mini"

.PARAMETER AzureAiProjectEndpoint
    Azure AI Foundry project endpoint for Bing Grounding agent

.PARAMETER BingConnectionName
    Name of the Bing Grounding connection in Azure AI Foundry

.PARAMETER AzureAiModelDeployment
    Model deployment name for the Bing Grounding agent (must be gpt-4.1-mini)

.PARAMETER AzureOpenAiEndpoint
    Your Azure OpenAI endpoint URL

.PARAMETER AzureOpenAiDeployment
    Azure OpenAI model deployment name for AI extraction
.PARAMETER DeployBingSearch
    Switch to also deploy a Bing Search v7 resource. After deployment, connect it
    to your AI Foundry project manually via the portal.

.PARAMETER BingSearchSku
    Pricing tier for the Bing Search resource (S1 recommended, F1 = free tier)
.EXAMPLE
    .\deploy.ps1 -ResourceGroupName "rg-hotel-api" -AzureOpenAiApiKey "your-key" -AzureOpenAiEndpoint "https://your-resource.openai.azure.com/" -AzureAiProjectEndpoint "https://your-foundry.services.ai.azure.com/api/projects/yourproject" -BingConnectionName "my-bing-grounding"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroupName = "rg-hotel-api-swedencentral",
    
    [Parameter(Mandatory=$true)]
    [string]$AzureOpenAiApiKey,
    
    [Parameter(Mandatory=$true)]
    [string]$AzureAiProjectEndpoint,
    
    [Parameter(Mandatory=$true)]
    [string]$BingConnectionName,
    
    [Parameter(Mandatory=$false)]
    [string]$AzureAiModelDeployment = "gpt-4.1-mini",
    
    [Parameter(Mandatory=$true)]
    [string]$AzureOpenAiEndpoint,
    
    [Parameter(Mandatory=$false)]
    [string]$AzureOpenAiDeployment = "gpt-4",
    
    [Parameter(Mandatory=$false)]
    [switch]$DeployBingSearch,
    
    [Parameter(Mandatory=$false)]
    [string]$BingSearchSku = "S1",
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "swedencentral",

    [Parameter(Mandatory=$false)]
    [string]$BaseName = "hotelapi",

    [Parameter(Mandatory=$false)]
    [string]$OpenAiChatModel = "gpt-4",

    [Parameter(Mandatory=$false)]
    [string]$FoundryModel = "gpt-4.1-mini",

    [Parameter(Mandatory=$false)]
    [string]$BingSearchSku = "S1",

    [Parameter(Mandatory=$false)]
    [string]$BingConnectionName = "bing-grounding",

    [Parameter(Mandatory=$false)]
    [switch]$SkipInfrastructure
)

$ErrorActionPreference = "Stop"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Hotel API - Full Azure Infrastructure Deployment" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ─────────────────────────────────────────────────
# Step 1: Pre-flight checks
# ─────────────────────────────────────────────────

Write-Host "Step 1: Pre-flight checks..." -ForegroundColor Yellow

# Check Azure CLI is logged in
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "ERROR: Not logged in. Run 'az login' first." -ForegroundColor Red
    exit 1
}
Write-Host "  Logged in as: $($account.user.name)" -ForegroundColor Green
Write-Host "  Subscription: $($account.name) ($($account.id))" -ForegroundColor Green

# Check required CLI extensions
$extensions = @("containerapp")
foreach ($ext in $extensions) {
    $installed = az extension show --name $ext 2>$null
    if (-not $installed) {
        Write-Host "  Installing Azure CLI extension: $ext..." -ForegroundColor Gray
        az extension add --name $ext --yes --output none
    }
}

# Check Docker / ACR build availability
Write-Host "  Azure CLI extensions: OK" -ForegroundColor Green

# Check Bicep availability
$bicepVersion = az bicep version 2>$null
if (-not $bicepVersion) {
    Write-Host "  Installing Bicep CLI..." -ForegroundColor Gray
    az bicep install --output none
}
Write-Host "  Bicep CLI: OK" -ForegroundColor Green

# Check that the Bing resource provider is registered
Write-Host "  Checking resource provider registrations..." -ForegroundColor Gray
$bingProvider = az provider show --namespace Microsoft.Bing --query "registrationState" -o tsv 2>$null
if ($bingProvider -ne "Registered") {
    Write-Host "  Registering Microsoft.Bing provider (may take a few minutes)..." -ForegroundColor Gray
    az provider register --namespace Microsoft.Bing --output none
    $retries = 0
    while ($retries -lt 30) {
        Start-Sleep -Seconds 10
        $bingProvider = az provider show --namespace Microsoft.Bing --query "registrationState" -o tsv 2>$null
        if ($bingProvider -eq "Registered") { break }
        $retries++
        Write-Host "    Waiting for registration... ($retries/30)" -ForegroundColor Gray
    }
    if ($bingProvider -ne "Registered") {
        Write-Host "WARNING: Microsoft.Bing provider not yet registered. Bing Search deployment may fail." -ForegroundColor Yellow
        Write-Host "  You can register manually: az provider register --namespace Microsoft.Bing" -ForegroundColor Gray
    }
}
Write-Host "  Resource providers: OK" -ForegroundColor Green
Write-Host ""

# ─────────────────────────────────────────────────
# Step 2: Create Resource Group
# ─────────────────────────────────────────────────

Write-Host "Step 2: Creating resource group '$ResourceGroupName' in $Location..." -ForegroundColor Yellow
az group create --name $ResourceGroupName --location $Location --output none
Write-Host "  Resource group: OK" -ForegroundColor Green
Write-Host ""

# ─────────────────────────────────────────────────
# Step 3: Deploy Infrastructure (Bicep)
# ─────────────────────────────────────────────────

$deploymentOutput = az deployment group create `
    --resource-group $ResourceGroupName `
    --template-file "infra/main.bicep" `
    --parameters location=$Location `
    --parameters baseName=$BaseName `
    --parameters azureOpenAiEndpoint=$AzureOpenAiEndpoint `
    --parameters azureOpenAiApiKey=$AzureOpenAiApiKey `
    --parameters azureOpenAiDeployment=$AzureOpenAiDeployment `
    --parameters azureAiProjectEndpoint=$AzureAiProjectEndpoint `
    --parameters bingConnectionName=$BingConnectionName `
    --parameters azureAiModelDeployment=$AzureAiModelDeployment `
    --parameters deployBingSearch=$($DeployBingSearch.IsPresent.ToString().ToLower()) `
    --parameters bingSearchSku=$BingSearchSku `
    --query "properties.outputs" `
    --output json | ConvertFrom-Json

$acrLoginServer = $deploymentOutput.containerRegistryLoginServer.value
$acrName = $deploymentOutput.containerRegistryName.value
$appUrl = $deploymentOutput.containerAppUrl.value
$bingSearchResource = $deploymentOutput.bingSearchResourceName.value

Write-Host "Infrastructure deployed successfully!" -ForegroundColor Green
Write-Host "  Container Registry: $acrLoginServer" -ForegroundColor Gray
Write-Host "  App URL: $appUrl" -ForegroundColor Gray
if ($DeployBingSearch -and $bingSearchResource -ne "not-deployed") {
    Write-Host "  Bing Search Resource: $bingSearchResource" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  IMPORTANT: Connect this Bing Search resource to your AI Foundry project:" -ForegroundColor Yellow
    Write-Host "    1. Go to https://ai.azure.com > your project > Connected resources" -ForegroundColor Gray
    Write-Host "    2. Add a new Bing Search connection using the key from:" -ForegroundColor Gray
    Write-Host "       az cognitiveservices account keys list --name $bingSearchResource --resource-group $ResourceGroupName" -ForegroundColor Gray
    Write-Host "    3. Use the connection name you chose as the BingConnectionName parameter" -ForegroundColor Gray
}
Write-Host ""

            $connectionUri = "https://management.azure.com${hubResourceId}/connections/${BingConnectionName}?api-version=2024-10-01"
            
            try {
                $null = Invoke-RestMethod -Method PUT -Uri $connectionUri `
                    -Headers @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" } `
                    -Body $connectionBody
                Write-Host "  Bing Grounding connection '$BingConnectionName' created successfully!" -ForegroundColor Green
            }
            catch {
                Write-Host "  WARNING: Could not create Bing connection automatically." -ForegroundColor Yellow
                Write-Host "  Create it manually in Azure AI Foundry portal:" -ForegroundColor Yellow
                Write-Host "    1. Go to https://ai.azure.com > your project > Connected resources" -ForegroundColor Gray
                Write-Host "    2. Add a new connection, type: API key" -ForegroundColor Gray
                Write-Host "    3. Name: $BingConnectionName" -ForegroundColor Gray
                Write-Host "    4. Endpoint: https://api.bing.microsoft.com/" -ForegroundColor Gray
                Write-Host "    5. Get the key from: az resource invoke-action --action listKeys --ids <bing-resource-id> --api-version 2020-06-10" -ForegroundColor Gray
            }
        }
    } else {
        Write-Host "  WARNING: Could not retrieve Bing Search key." -ForegroundColor Yellow
        Write-Host "  Create the Bing Grounding connection manually in AI Foundry portal." -ForegroundColor Gray
    }
    Write-Host ""

} else {
    # Skip infrastructure - just get existing resource names
    Write-Host "Step 3: Skipping infrastructure (--SkipInfrastructure)" -ForegroundColor Yellow
    
    $acrName = az resource list --resource-group $ResourceGroupName --resource-type "Microsoft.ContainerRegistry/registries" --query "[0].name" -o tsv
    $acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
    $appUrl = az containerapp show --name "${BaseName}-app" --resource-group $ResourceGroupName --query "properties.configuration.ingress.fqdn" -o tsv
    if ($appUrl) { $appUrl = "https://$appUrl" }
    
    Write-Host "  Using existing resources:" -ForegroundColor Gray
    Write-Host "    ACR: $acrLoginServer" -ForegroundColor Gray
    Write-Host "    App: $appUrl" -ForegroundColor Gray
    Write-Host ""
}

# ─────────────────────────────────────────────────
# Step 5: Login to Container Registry
# ─────────────────────────────────────────────────

$stepNum = if ($SkipInfrastructure) { "Step 4" } else { "Step 5" }
Write-Host "${stepNum}: Logging into Container Registry..." -ForegroundColor Yellow
az acr login --name $acrName
Write-Host "  Logged into ACR." -ForegroundColor Green
Write-Host ""

# ─────────────────────────────────────────────────
# Step 6: Build and Push Docker Image
# ─────────────────────────────────────────────────

$stepNum = if ($SkipInfrastructure) { "Step 5" } else { "Step 6" }
Write-Host "${stepNum}: Building and pushing Docker image (ACR Tasks)..." -ForegroundColor Yellow
Write-Host "  This builds in the cloud (no local Docker needed)..." -ForegroundColor Gray

$imageName = "$acrLoginServer/${BaseName}:latest"

az acr build `
    --registry $acrName `
    --image "${BaseName}:latest" `
    --file Dockerfile `
    . 

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker build failed!" -ForegroundColor Red
    exit 1
}

Write-Host "  Docker image built and pushed successfully!" -ForegroundColor Green
Write-Host ""

# ─────────────────────────────────────────────────
# Step 7: Update Container App
# ─────────────────────────────────────────────────

$stepNum = if ($SkipInfrastructure) { "Step 6" } else { "Step 7" }
Write-Host "${stepNum}: Updating Container App with new image..." -ForegroundColor Yellow

az containerapp update `
    --name "${BaseName}-app" `
    --resource-group $ResourceGroupName `
    --image $imageName `
    --output none

Write-Host "  Container App updated!" -ForegroundColor Green
Write-Host ""

# ─────────────────────────────────────────────────
# Done!
# ─────────────────────────────────────────────────

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Your Hotel Information API is now available at:" -ForegroundColor White
Write-Host "  $appUrl" -ForegroundColor Yellow
Write-Host ""
Write-Host "API Endpoints:" -ForegroundColor White
Write-Host "  Health Check:   $appUrl/health" -ForegroundColor Gray
Write-Host "  Swagger Docs:   $appUrl/docs" -ForegroundColor Gray
Write-Host "  Hotel Lookup:   POST $appUrl/api/v1/hotel/lookup" -ForegroundColor Gray
Write-Host "  Batch Lookup:   POST $appUrl/api/v1/hotel/batch" -ForegroundColor Gray
Write-Host ""
Write-Host "Resources created:" -ForegroundColor White
Write-Host "  Resource Group:     $ResourceGroupName" -ForegroundColor Gray
if (-not $SkipInfrastructure) {
    Write-Host "  AI Services:        $aiServicesName" -ForegroundColor Gray
    Write-Host "  AI Hub:             $aiHubName" -ForegroundColor Gray
    Write-Host "  AI Project:         $aiProjectName" -ForegroundColor Gray
    Write-Host "  Project Endpoint:   $aiProjectEndpoint" -ForegroundColor Gray
    Write-Host "  Bing Search:        $bingSearchName" -ForegroundColor Gray
    Write-Host "  Bing Connection:    $BingConnectionName" -ForegroundColor Gray
    Write-Host "  Chat Model:         $OpenAiChatModel" -ForegroundColor Gray
    Write-Host "  Foundry Model:      $FoundryModel" -ForegroundColor Gray
}
Write-Host "  Container Registry: $acrLoginServer" -ForegroundColor Gray
Write-Host ""
Write-Host "Test with:" -ForegroundColor White
Write-Host "  curl $appUrl/health" -ForegroundColor Gray
Write-Host ""
