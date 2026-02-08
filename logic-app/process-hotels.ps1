# Hotel Licensing Processor
# Reads hotels from Excel and calls the Logic App to enrich them

param(
    [Parameter(Mandatory=$true)]
    [string]$ExcelPath,
    
    [string]$OutputPath = "results_$(Get-Date -Format 'yyyy-MM-dd_HHmmss').xlsx",
    
    [int]$BatchSize = 20
)

# Logic App URL
$logicAppUrl = "https://prod-04.swedencentral.logic.azure.com:443/workflows/f25f1012c43d40439d72d7cf157839c3/triggers/manual/paths/invoke?api-version=2016-06-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=o6rTKvy6zfXDWApEEURjnvvyUE5qAFCmSRbAOSi6F4A"

Write-Host "=== Hotel TV Licensing Processor ===" -ForegroundColor Cyan
Write-Host ""

# Check if ImportExcel module is installed
if (-not (Get-Module -ListAvailable -Name ImportExcel)) {
    Write-Host "Installing ImportExcel module..." -ForegroundColor Yellow
    Install-Module ImportExcel -Scope CurrentUser -Force
}

# Import the Excel file
Write-Host "Reading Excel file: $ExcelPath" -ForegroundColor Yellow
$excelData = Import-Excel $ExcelPath

if (-not $excelData) {
    Write-Host "Error: No data found in Excel file" -ForegroundColor Red
    exit 1
}

Write-Host "Found $($excelData.Count) hotels" -ForegroundColor Green
Write-Host ""

# Convert to hotel format
$hotels = $excelData | ForEach-Object {
    $name = $_."Hotel Name" ?? $_."Name" ?? $_."HotelName"
    $address = $_."Address" ?? ""
    $city = $_."City" ?? ""
    $postcode = $_."Postcode" ?? $_."Post Code" ?? ""
    
    # Build full address
    $fullAddress = @($address, $city, $postcode) | Where-Object { $_ } | Join-String -Separator ", "
    
    @{
        name = $name
        address = $fullAddress
        city = $city
        postcode = $postcode
    }
}

# Process in batches
$allResults = @()
$totalBatches = [Math]::Ceiling($hotels.Count / $BatchSize)

for ($i = 0; $i -lt $hotels.Count; $i += $BatchSize) {
    $batchNum = [Math]::Floor($i / $BatchSize) + 1
    $batch = $hotels[$i..([Math]::Min($i + $BatchSize - 1, $hotels.Count - 1))]
    
    Write-Host "Processing batch $batchNum of $totalBatches ($($batch.Count) hotels)..." -ForegroundColor Yellow
    
    try {
        $body = @{ hotels = $batch } | ConvertTo-Json -Depth 5
        $response = Invoke-RestMethod -Uri $logicAppUrl -Method POST -Body $body -ContentType "application/json" -TimeoutSec 600
        
        Write-Host "  Successful: $($response.successful), Partial: $($response.partial), Failed: $($response.failed)" -ForegroundColor Green
        
        $allResults += $response.results
    }
    catch {
        Write-Host "  Error processing batch: $_" -ForegroundColor Red
    }
    
    # Small delay between batches
    if ($i + $BatchSize -lt $hotels.Count) {
        Start-Sleep -Seconds 2
    }
}

# Export results
Write-Host ""
Write-Host "Exporting results to: $OutputPath" -ForegroundColor Yellow

$allResults | Select-Object @(
    @{N='Hotel Name';E={$_.search_name}},
    @{N='Address';E={$_.search_address}},
    @{N='Rooms (Min)';E={$_.rooms_min}},
    @{N='Rooms (Max)';E={$_.rooms_max}},
    @{N='Official Website';E={$_.official_website}},
    @{N='UK Phone';E={$_.uk_contact_phone}},
    @{N='Status';E={$_.status}},
    @{N='Confidence';E={$_.confidence_score}},
    @{N='Room Source Notes';E={$_.rooms_source_notes}},
    @{N='Last Checked';E={$_.last_checked}}
) | Export-Excel $OutputPath -AutoSize -FreezeTopRow -BoldTopRow

# Summary
Write-Host ""
Write-Host "=== Processing Complete ===" -ForegroundColor Green
Write-Host "Total Hotels: $($allResults.Count)"
Write-Host "Successful: $($allResults | Where-Object status -eq 'success' | Measure-Object | Select-Object -ExpandProperty Count)"
Write-Host "Partial: $($allResults | Where-Object status -eq 'partial' | Measure-Object | Select-Object -ExpandProperty Count)"
Write-Host "Not Found: $($allResults | Where-Object status -eq 'not_found' | Measure-Object | Select-Object -ExpandProperty Count)"
Write-Host ""
Write-Host "Results saved to: $OutputPath" -ForegroundColor Cyan
