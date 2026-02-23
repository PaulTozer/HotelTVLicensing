// ============================================================================
// Hotel TV Licensing API - Complete Azure Infrastructure
// ============================================================================
// Deploys ALL resources needed for the Hotel API:
//   - Azure AI Services (OpenAI + AI Foundry) with model deployments
//   - Bing Search v7 for grounding
//   - AI Hub + AI Project (Azure AI Foundry)
//   - Connections (AI Services to Hub)
//   - Container Registry, Container Apps, Log Analytics
//   - RBAC role assignments for managed identity
// ============================================================================

// ──────────────────────────────────────────────
// Parameters
// ──────────────────────────────────────────────

@description('Location for all resources')
param location string = 'swedencentral'

@description('Base name prefix for all resources')
param baseName string = 'hotelapi'

@description('OpenAI chat model deployment name (used for AI extraction)')
param openAiChatModel string = 'gpt-4'

@description('AI Foundry agent model deployment name (used for Bing Grounding, must support tools)')
param foundryModel string = 'gpt-4.1-mini'

@description('Bing Search pricing tier (S1 = production, F1 = free tier)')
param bingSearchSku string = 'S1'

@description('Name for the Bing Grounding connection in AI Foundry')
param bingConnectionName string = 'bing-grounding'

@description('Tokens-per-minute capacity (in thousands) for chat model')
param chatModelCapacity int = 30

@description('Tokens-per-minute capacity (in thousands) for foundry model')
param foundryModelCapacity int = 30

// ──────────────────────────────────────────────
// Variables
// ──────────────────────────────────────────────

var uniqueSuffix = uniqueString(resourceGroup().id)
var aiServicesName = '${baseName}-ai-${uniqueSuffix}'
var storageAccountName = '${baseName}st${uniqueSuffix}'
var keyVaultName = '${baseName}kv${uniqueSuffix}'
var aiHubName = '${baseName}-hub-${uniqueSuffix}'
var aiProjectName = '${baseName}-project'
var bingSearchName = '${baseName}-bing-${uniqueSuffix}'
var logAnalyticsName = '${baseName}-logs-${uniqueSuffix}'
var containerRegistryName = '${baseName}acr${uniqueSuffix}'
var containerAppEnvName = '${baseName}-env-${uniqueSuffix}'
var containerAppName = '${baseName}-app'

// Well-known role definition IDs
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var keyVaultSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

// ──────────────────────────────────────────────
// AI Services (Azure OpenAI + AI Foundry)
// ──────────────────────────────────────────────

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: aiServicesName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: aiServicesName
    publicNetworkAccess: 'Enabled'
    apiProperties: {
      statisticsEnabled: false
    }
  }
}

// Chat model deployment (e.g., gpt-4) - used for AI extraction
resource chatModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiServices
  name: openAiChatModel
  sku: {
    name: 'Standard'
    capacity: chatModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: openAiChatModel
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

// Foundry agent model deployment (e.g., gpt-4.1-mini) - used for Bing Grounding
resource foundryModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiServices
  name: foundryModel
  dependsOn: [chatModelDeployment] // Sequential - ARM deploys children one at a time
  sku: {
    name: 'Standard'
    capacity: foundryModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: foundryModel
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

// ──────────────────────────────────────────────
// Bing Search v7
// ──────────────────────────────────────────────

resource bingSearch 'Microsoft.Bing/accounts@2020-06-10' = {
  name: bingSearchName
  location: 'global'
  kind: 'Bing.Search.v7'
  sku: {
    name: bingSearchSku
  }
}

// ──────────────────────────────────────────────
// AI Hub Dependencies (Storage + Key Vault)
// ──────────────────────────────────────────────

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enableRbacAuthorization: true
  }
}

// ──────────────────────────────────────────────
// AI Hub (Azure AI Foundry)
// ──────────────────────────────────────────────

resource aiHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01' = {
  name: aiHubName
  location: location
  kind: 'Hub'
  sku: {
    name: 'Basic'
    tier: 'Basic'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    friendlyName: 'Hotel API AI Hub'
    description: 'AI Hub for Hotel TV Licensing API'
    storageAccount: storageAccount.id
    keyVault: keyVault.id
    publicNetworkAccess: 'Enabled'
  }
}

// Grant AI Hub access to Storage Account
resource hubStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storageAccount
  name: guid(storageAccount.id, aiHub.id, storageBlobDataContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: aiHub.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Grant AI Hub access to Key Vault
resource hubKeyVaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, aiHub.id, keyVaultSecretsOfficerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficerRoleId)
    principalId: aiHub.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ──────────────────────────────────────────────
// AI Hub Connections
// ──────────────────────────────────────────────

// Connect AI Services (OpenAI) to the Hub
resource aiServicesConnection 'Microsoft.MachineLearningServices/workspaces/connections@2024-10-01' = {
  parent: aiHub
  name: '${baseName}-aiservices'
  dependsOn: [hubKeyVaultRole]
  properties: {
    authType: 'ApiKey'
    category: 'AzureOpenAI'
    isSharedToAll: true
    target: aiServices.properties.endpoint
    credentials: {
      key: aiServices.listKeys().key1
    }
    metadata: {
      ApiVersion: '2024-10-01'
      ApiType: 'Azure'
      ResourceId: aiServices.id
    }
  }
}

// ──────────────────────────────────────────────
// AI Project
// ──────────────────────────────────────────────

resource aiProject 'Microsoft.MachineLearningServices/workspaces@2024-10-01' = {
  name: aiProjectName
  location: location
  kind: 'Project'
  sku: {
    name: 'Basic'
    tier: 'Basic'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    friendlyName: 'Hotel API Project'
    description: 'AI Project for Hotel TV Licensing API'
    hubResourceId: aiHub.id
    publicNetworkAccess: 'Enabled'
  }
  dependsOn: [aiServicesConnection]
}

// ──────────────────────────────────────────────
// Container Infrastructure
// ──────────────────────────────────────────────

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: containerRegistryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerAppEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ──────────────────────────────────────────────
// Container App (with Managed Identity)
// ──────────────────────────────────────────────

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnvironment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: containerRegistry.properties.loginServer
          username: containerRegistry.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: containerRegistry.listCredentials().passwords[0].value
        }
        {
          name: 'azure-openai-key'
          value: aiServices.listKeys().key1
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'hotel-api'
          image: '${containerRegistry.properties.loginServer}/${baseName}:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: aiServices.properties.endpoint
            }
            {
              name: 'AZURE_OPENAI_API_KEY'
              secretRef: 'azure-openai-key'
            }
            {
              name: 'AZURE_OPENAI_DEPLOYMENT'
              value: openAiChatModel
            }
            {
              name: 'AZURE_AI_PROJECT_ENDPOINT'
              value: '${aiServices.properties.endpoint}api/projects/${aiProject.name}'
            }
            {
              name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME'
              value: foundryModel
            }
            {
              name: 'BING_CONNECTION_NAME'
              value: bingConnectionName
            }
            {
              name: 'USE_BING_GROUNDING'
              value: 'true'
            }
            {
              name: 'LOG_LEVEL'
              value: 'INFO'
            }
            {
              name: 'MAX_REQUESTS_PER_MINUTE'
              value: '30'
            }
            {
              name: 'SCRAPE_TIMEOUT_SECONDS'
              value: '30'
            }
            {
              name: 'BATCH_MAX_CONCURRENT'
              value: '25'
            }
            {
              name: 'BING_MAX_CONCURRENT'
              value: '15'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [
          {
            name: 'http-rule'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
  dependsOn: [foundryModelDeployment, aiProject]
}

// ──────────────────────────────────────────────
// RBAC: Container App → AI Services
// ──────────────────────────────────────────────

// Container App managed identity needs Cognitive Services User
// for DefaultAzureCredential in the Bing Grounding agent
resource containerAppCogServicesRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiServices
  name: guid(aiServices.id, containerApp.id, cognitiveServicesUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ──────────────────────────────────────────────
// Outputs
// ──────────────────────────────────────────────

output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output containerRegistryLoginServer string = containerRegistry.properties.loginServer
output containerRegistryName string = containerRegistry.name
output aiServicesEndpoint string = aiServices.properties.endpoint
output aiServicesName string = aiServices.name
output aiProjectName string = aiProject.name
output aiProjectEndpoint string = '${aiServices.properties.endpoint}api/projects/${aiProject.name}'
output bingSearchName string = bingSearch.name
output bingConnectionName string = bingConnectionName
output aiHubName string = aiHub.name
