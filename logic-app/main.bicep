// Azure Logic App for Hotel TV Licensing
// Reads hotels from Excel, calls the Hotel API, and writes results back

@description('Location for all resources')
param location string = resourceGroup().location

@description('Name of the Logic App')
param logicAppName string = 'hotel-licensing-processor'

@description('Hotel API URL')
param hotelApiUrl string = 'https://hotelapi-app.orangeflower-3dda66b0.swedencentral.azurecontainerapps.io'

// Office 365 connection for Excel
resource office365Connection 'Microsoft.Web/connections@2016-06-01' = {
  name: 'office365-connection'
  location: location
  properties: {
    displayName: 'Excel Online (Business)'
    api: {
      id: subscriptionResourceId('Microsoft.Web/locations/managedApis', location, 'excelonlinebusiness')
    }
  }
}

// Logic App
resource logicApp 'Microsoft.Logic/workflows@2019-05-01' = {
  name: logicAppName
  location: location
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      parameters: {
        '$connections': {
          defaultValue: {}
          type: 'Object'
        }
        hotelApiUrl: {
          defaultValue: hotelApiUrl
          type: 'String'
        }
      }
      triggers: {
        manual: {
          type: 'Request'
          kind: 'Http'
          inputs: {
            schema: {
              type: 'object'
              properties: {
                excelFileId: {
                  type: 'string'
                  description: 'OneDrive file ID or path to Excel file'
                }
                tableName: {
                  type: 'string'
                  description: 'Name of the Excel table'
                }
              }
            }
          }
        }
      }
      actions: {
        Initialize_Results: {
          type: 'InitializeVariable'
          inputs: {
            variables: [
              {
                name: 'ProcessedResults'
                type: 'array'
                value: []
              }
            ]
          }
          runAfter: {}
        }
        Initialize_Counter: {
          type: 'InitializeVariable'
          inputs: {
            variables: [
              {
                name: 'ProcessedCount'
                type: 'integer'
                value: 0
              }
            ]
          }
          runAfter: {
            Initialize_Results: ['Succeeded']
          }
        }
        Get_Excel_Rows: {
          type: 'ApiConnection'
          inputs: {
            host: {
              connection: {
                name: '@parameters(\'$connections\')[\'excelonlinebusiness\'][\'connectionId\']'
              }
            }
            method: 'get'
            path: '/codeless/v1.0/drives/@{encodeURIComponent(triggerBody()?[\'driveId\'])}/items/@{encodeURIComponent(triggerBody()?[\'excelFileId\'])}/workbook/tables/@{encodeURIComponent(triggerBody()?[\'tableName\'])}/rows'
          }
          runAfter: {
            Initialize_Counter: ['Succeeded']
          }
        }
        For_Each_Hotel: {
          type: 'Foreach'
          foreach: '@body(\'Get_Excel_Rows\')?[\'value\']'
          actions: {
            Call_Hotel_API: {
              type: 'Http'
              inputs: {
                method: 'POST'
                uri: '@{parameters(\'hotelApiUrl\')}/api/v1/hotel/lookup'
                headers: {
                  'Content-Type': 'application/json'
                }
                body: {
                  name: '@items(\'For_Each_Hotel\')?[\'values\'][0]'
                  address: '@items(\'For_Each_Hotel\')?[\'values\'][1]'
                }
              }
              runAfter: {}
            }
            Append_Result: {
              type: 'AppendToArrayVariable'
              inputs: {
                name: 'ProcessedResults'
                value: {
                  hotel_name: '@items(\'For_Each_Hotel\')?[\'values\'][0]'
                  address: '@items(\'For_Each_Hotel\')?[\'values\'][1]'
                  rooms_min: '@body(\'Call_Hotel_API\')?[\'rooms_min\']'
                  rooms_max: '@body(\'Call_Hotel_API\')?[\'rooms_max\']'
                  official_website: '@body(\'Call_Hotel_API\')?[\'official_website\']'
                  uk_contact_phone: '@body(\'Call_Hotel_API\')?[\'uk_contact_phone\']'
                  status: '@body(\'Call_Hotel_API\')?[\'status\']'
                  confidence_score: '@body(\'Call_Hotel_API\')?[\'confidence_score\']'
                  rooms_source_notes: '@body(\'Call_Hotel_API\')?[\'rooms_source_notes\']'
                }
              }
              runAfter: {
                Call_Hotel_API: ['Succeeded', 'Failed']
              }
            }
            Increment_Counter: {
              type: 'IncrementVariable'
              inputs: {
                name: 'ProcessedCount'
                value: 1
              }
              runAfter: {
                Append_Result: ['Succeeded']
              }
            }
            Delay_Between_Calls: {
              type: 'Wait'
              inputs: {
                interval: {
                  count: 2
                  unit: 'Second'
                }
              }
              runAfter: {
                Increment_Counter: ['Succeeded']
              }
            }
          }
          runAfter: {
            Get_Excel_Rows: ['Succeeded']
          }
          runtimeConfiguration: {
            concurrency: {
              repetitions: 1
            }
          }
        }
        Response: {
          type: 'Response'
          kind: 'Http'
          inputs: {
            statusCode: 200
            body: {
              processed_count: '@variables(\'ProcessedCount\')'
              results: '@variables(\'ProcessedResults\')'
            }
          }
          runAfter: {
            For_Each_Hotel: ['Succeeded']
          }
        }
      }
    }
    parameters: {
      '$connections': {
        value: {
          excelonlinebusiness: {
            connectionId: office365Connection.id
            connectionName: 'excelonlinebusiness'
            id: subscriptionResourceId('Microsoft.Web/locations/managedApis', location, 'excelonlinebusiness')
          }
        }
      }
    }
  }
}

output logicAppUrl string = listCallbackUrl('${logicApp.id}/triggers/manual', '2019-05-01').value
output logicAppName string = logicApp.name
