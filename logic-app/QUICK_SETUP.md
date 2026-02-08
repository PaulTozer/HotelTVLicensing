# Quick Setup: Hotel Processing Logic App

## ✅ Logic App Already Deployed!

Your Logic App is ready to use:

**Logic App URL:**
```
https://prod-04.swedencentral.logic.azure.com:443/workflows/f25f1012c43d40439d72d7cf157839c3/triggers/manual/paths/invoke?api-version=2016-06-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=o6rTKvy6zfXDWApEEURjnvvyUE5qAFCmSRbAOSi6F4A
```

**Resource Group:** `rg-hotel-logic-app`
**Logic App Name:** `hotel-processor`

---

## How to Use

### Option 1: PowerShell Script (Easiest)

Create a file `process-hotels.ps1`:

```powershell
# Read hotels from Excel/CSV and process them
param(
    [string]$ExcelPath = "hotels.xlsx"
)

# Logic App URL
$logicAppUrl = "https://prod-04.swedencentral.logic.azure.com:443/workflows/f25f1012c43d40439d72d7cf157839c3/triggers/manual/paths/invoke?api-version=2016-06-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=o6rTKvy6zfXDWApEEURjnvvyUE5qAFCmSRbAOSi6F4A"

# Import Excel module if needed
if (-not (Get-Module -ListAvailable -Name ImportExcel)) {
    Install-Module ImportExcel -Scope CurrentUser -Force
}

# Read Excel file
$hotels = Import-Excel $ExcelPath | ForEach-Object {
    @{
        name = $_."Hotel Name"
        address = "$($_."Address"), $($_."City")"
    }
}

Write-Host "Processing $($hotels.Count) hotels..."

# Call Logic App
$body = @{ hotels = $hotels } | ConvertTo-Json -Depth 5
$result = Invoke-RestMethod -Uri $logicAppUrl -Method POST -Body $body -ContentType "application/json"

# Output results
$result.results | Export-Excel "results_$(Get-Date -Format 'yyyy-MM-dd_HHmmss').xlsx"
Write-Host "Done! Processed $($result.total_requested) hotels."
Write-Host "  Successful: $($result.successful)"
Write-Host "  Partial: $($result.partial)"
Write-Host "  Failed: $($result.failed)"
```

Run it:
```powershell
.\process-hotels.ps1 -ExcelPath "my-hotels.xlsx"
```

### Option 2: Direct API Call

```powershell
$url = "https://prod-04.swedencentral.logic.azure.com:443/workflows/f25f1012c43d40439d72d7cf157839c3/triggers/manual/paths/invoke?api-version=2016-06-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=o6rTKvy6zfXDWApEEURjnvvyUE5qAFCmSRbAOSi6F4A"

$body = @{
    hotels = @(
        @{ name = "The Savoy"; address = "Strand, London" },
        @{ name = "The Grand Hotel"; address = "Brighton" }
    )
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri $url -Method POST -Body $body -ContentType "application/json"
```

### Option 3: From Excel with Power Automate

1. Open Power Automate (flow.microsoft.com)
2. Create a new flow with trigger: "When a row is added" (Excel)
3. Add action: HTTP POST to the Logic App URL
4. Map Excel columns to the request body

---

## Excel File Format

Your Excel file should have these columns:

| Hotel Name | Address | City | Postcode |
|------------|---------|------|----------|
| The Grand Hotel | 123 High Street | London | SW1A 1AA |
| Marina House Hotel | 8 Charlotte St | Brighton | BN2 1AG |

---

## Response Format

The Logic App returns:

```json
{
  "total_requested": 2,
  "successful": 1,
  "partial": 1,
  "failed": 0,
  "results": [
    {
      "search_name": "The Savoy",
      "search_address": "Strand, London",
      "official_website": "https://thesavoylondon.com/",
      "uk_contact_phone": "+44 (0)20 7836 4343",
      "rooms_min": 263,
      "rooms_max": 263,
      "status": "success",
      "confidence_score": 0.92
    }
  ]
}
```
