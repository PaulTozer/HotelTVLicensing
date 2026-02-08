# Hotel Licensing Logic App Deployment Script
# This script deploys the Logic App to process hotels from Excel

param(
    [string]$ResourceGroupName = "rg-hotel-logic-app",
    [string]$Location = "swedencentral",
    [string]$LogicAppName = "hotel-licensing-processor"
)

Write-Host "=== Hotel Licensing Logic App Deployment ===" -ForegroundColor Cyan

# Check if logged in
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "Please login to Azure..." -ForegroundColor Yellow
    az login
}

Write-Host "Using subscription: $($account.name)" -ForegroundColor Green

# Create resource group
Write-Host "`nCreating resource group..." -ForegroundColor Yellow
az group create --name $ResourceGroupName --location $Location --output none

# Create API connections first
Write-Host "Creating Excel Online connection..." -ForegroundColor Yellow
$excelConnectionJson = @{
    properties = @{
        displayName = "Excel Online (Business)"
        api = @{
            id = "/subscriptions/$($account.id)/providers/Microsoft.Web/locations/$Location/managedApis/excelonlinebusiness"
        }
    }
    location = $Location
} | ConvertTo-Json -Depth 10

az resource create `
    --resource-group $ResourceGroupName `
    --resource-type "Microsoft.Web/connections" `
    --name "excel-connection" `
    --properties $excelConnectionJson `
    --output none 2>$null

Write-Host "Creating OneDrive connection..." -ForegroundColor Yellow
$onedriveConnectionJson = @{
    properties = @{
        displayName = "OneDrive for Business"
        api = @{
            id = "/subscriptions/$($account.id)/providers/Microsoft.Web/locations/$Location/managedApis/onedriveforbusiness"
        }
    }
    location = $Location
} | ConvertTo-Json -Depth 10

az resource create `
    --resource-group $ResourceGroupName `
    --resource-type "Microsoft.Web/connections" `
    --name "onedrive-connection" `
    --properties $onedriveConnectionJson `
    --output none 2>$null

# Create the Logic App
Write-Host "Creating Logic App..." -ForegroundColor Yellow

$subscriptionId = $account.id

$workflowDefinition = @{
    definition = @{
        '$schema' = "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#"
        contentVersion = "1.0.0.0"
        parameters = @{
            '$connections' = @{
                defaultValue = @{}
                type = "Object"
            }
        }
        triggers = @{
            When_a_file_is_modified = @{
                type = "ApiConnection"
                recurrence = @{
                    frequency = "Minute"
                    interval = 15
                }
                evaluatedRecurrence = @{
                    frequency = "Minute"
                    interval = 15
                }
                inputs = @{
                    host = @{
                        connection = @{
                            name = "@parameters('`$connections')['onedriveforbusiness']['connectionId']"
                        }
                    }
                    method = "get"
                    path = "/datasets/default/triggers/onupdatedfile"
                    queries = @{
                        folderId = "root"
                        includeSubfolders = "false"
                    }
                }
            }
        }
        actions = @{
            Get_Tables = @{
                type = "ApiConnection"
                inputs = @{
                    host = @{
                        connection = @{
                            name = "@parameters('`$connections')['excelonlinebusiness']['connectionId']"
                        }
                    }
                    method = "get"
                    path = "/codeless/v1.0/drives/@{encodeURIComponent(triggerBody()?['folderId'])}/items/@{encodeURIComponent(triggerBody()?['id'])}/workbook/tables"
                }
                runAfter = @{}
            }
        }
    }
    parameters = @{
        '$connections' = @{
            value = @{
                excelonlinebusiness = @{
                    connectionId = "/subscriptions/$subscriptionId/resourceGroups/$ResourceGroupName/providers/Microsoft.Web/connections/excel-connection"
                    connectionName = "excel-connection"
                    id = "/subscriptions/$subscriptionId/providers/Microsoft.Web/locations/$Location/managedApis/excelonlinebusiness"
                }
                onedriveforbusiness = @{
                    connectionId = "/subscriptions/$subscriptionId/resourceGroups/$ResourceGroupName/providers/Microsoft.Web/connections/onedrive-connection"
                    connectionName = "onedrive-connection"
                    id = "/subscriptions/$subscriptionId/providers/Microsoft.Web/locations/$Location/managedApis/onedriveforbusiness"
                }
            }
        }
    }
} | ConvertTo-Json -Depth 20

$logicAppProperties = @{
    properties = @{
        state = "Enabled"
        definition = ($workflowDefinition | ConvertFrom-Json).definition
        parameters = ($workflowDefinition | ConvertFrom-Json).parameters
    }
    location = $Location
} | ConvertTo-Json -Depth 20

az resource create `
    --resource-group $ResourceGroupName `
    --resource-type "Microsoft.Logic/workflows" `
    --name $LogicAppName `
    --properties $logicAppProperties `
    --output none

Write-Host "`n=== Deployment Complete ===" -ForegroundColor Green
Write-Host "`nNext Steps:" -ForegroundColor Cyan
Write-Host "1. Go to Azure Portal: https://portal.azure.com" -ForegroundColor White
Write-Host "2. Navigate to Resource Group: $ResourceGroupName" -ForegroundColor White
Write-Host "3. Open 'excel-connection' and click 'Edit API connection'" -ForegroundColor White
Write-Host "4. Click 'Authorize' and sign in with your Microsoft 365 account" -ForegroundColor White
Write-Host "5. Repeat for 'onedrive-connection'" -ForegroundColor White
Write-Host "6. Open the Logic App '$LogicAppName' and configure the workflow" -ForegroundColor White

Write-Host "`nPortal Links:" -ForegroundColor Cyan
Write-Host "Resource Group: https://portal.azure.com/#@/resource/subscriptions/$subscriptionId/resourceGroups/$ResourceGroupName/overview" -ForegroundColor Blue
Write-Host "Logic App: https://portal.azure.com/#@/resource/subscriptions/$subscriptionId/resourceGroups/$ResourceGroupName/providers/Microsoft.Logic/workflows/$LogicAppName/logicApp" -ForegroundColor Blue
