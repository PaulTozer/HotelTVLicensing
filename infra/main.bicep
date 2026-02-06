@description('Location for all resources')
param location string = 'swedencentral'

@description('Base name for resources')
param baseName string = 'hotelapi'

@description('Azure OpenAI endpoint')
param azureOpenAiEndpoint string

@secure()
@description('Azure OpenAI API key')
param azureOpenAiApiKey string

@description('Azure OpenAI deployment name')
param azureOpenAiDeployment string = 'gpt-5.2-chat'

var uniqueSuffix = uniqueString(resourceGroup().id)
var containerRegistryName = '${baseName}acr${uniqueSuffix}'
var containerAppEnvName = '${baseName}-env-${uniqueSuffix}'
var containerAppName = '${baseName}-app'
var logAnalyticsName = '${baseName}-logs-${uniqueSuffix}'

// Log Analytics Workspace
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

// Container Registry
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

// Container Apps Environment
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

// Container App
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
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
          value: azureOpenAiApiKey
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
              value: azureOpenAiEndpoint
            }
            {
              name: 'AZURE_OPENAI_API_KEY'
              secretRef: 'azure-openai-key'
            }
            {
              name: 'AZURE_OPENAI_DEPLOYMENT'
              value: azureOpenAiDeployment
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
}

output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output containerRegistryLoginServer string = containerRegistry.properties.loginServer
output containerRegistryName string = containerRegistry.name
