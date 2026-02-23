<# 
.SYNOPSIS
    Deploys the Hotel Information API to Azure Container Apps

.DESCRIPTION
    This script:
    1. Creates a resource group in Sweden Central
    2. Deploys Azure Container Registry and Container Apps infrastructure
    3. Builds and pushes the Docker image
    4. Deploys the Container App with Azure AI Foundry Bing Grounding configuration

.PARAMETER ResourceGroupName
    Name of the Azure resource group to create/use

.PARAMETER AzureOpenAiApiKey
    Your Azure OpenAI API key

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
    [string]$BaseName = "hotelapi"
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Hotel API - Azure Container Apps Deploy" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Azure CLI is logged in
Write-Host "Checking Azure CLI login..." -ForegroundColor Yellow
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "Not logged in. Please run 'az login' first." -ForegroundColor Red
    exit 1
}
Write-Host "Logged in as: $($account.user.name)" -ForegroundColor Green
Write-Host "Subscription: $($account.name)" -ForegroundColor Green
Write-Host ""

# Step 1: Create Resource Group
Write-Host "Step 1: Creating resource group '$ResourceGroupName' in $Location..." -ForegroundColor Yellow
az group create --name $ResourceGroupName --location $Location --output none
Write-Host "Resource group created." -ForegroundColor Green
Write-Host ""

# Step 2: Deploy Infrastructure
Write-Host "Step 2: Deploying infrastructure (Container Registry, Container Apps Environment)..." -ForegroundColor Yellow
Write-Host "This may take 3-5 minutes..." -ForegroundColor Gray

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

# Step 3: Login to Container Registry
Write-Host "Step 3: Logging into Container Registry..." -ForegroundColor Yellow
az acr login --name $acrName
Write-Host "Logged into ACR." -ForegroundColor Green
Write-Host ""

# Step 4: Build and Push Docker Image
Write-Host "Step 4: Building and pushing Docker image..." -ForegroundColor Yellow
Write-Host "This may take 2-3 minutes..." -ForegroundColor Gray

$imageName = "$acrLoginServer/${BaseName}:latest"

# Build using ACR Tasks (builds in the cloud, no local Docker needed)
az acr build `
    --registry $acrName `
    --image "${BaseName}:latest" `
    --file Dockerfile `
    . 

Write-Host "Docker image built and pushed successfully!" -ForegroundColor Green
Write-Host ""

# Step 5: Update Container App with the new image
Write-Host "Step 5: Updating Container App with new image..." -ForegroundColor Yellow

az containerapp update `
    --name "${BaseName}-app" `
    --resource-group $ResourceGroupName `
    --image $imageName `
    --output none

Write-Host "Container App updated!" -ForegroundColor Green
Write-Host ""

# Done!
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Your Hotel Information API is now available at:" -ForegroundColor White
Write-Host "  $appUrl" -ForegroundColor Yellow
Write-Host ""
Write-Host "API Endpoints:" -ForegroundColor White
Write-Host "  Health Check: $appUrl/health" -ForegroundColor Gray
Write-Host "  Swagger Docs: $appUrl/docs" -ForegroundColor Gray
Write-Host "  Hotel Lookup: POST $appUrl/api/v1/hotel/lookup" -ForegroundColor Gray
Write-Host ""
Write-Host "Test with:" -ForegroundColor White
Write-Host "  curl $appUrl/health" -ForegroundColor Gray
Write-Host ""
