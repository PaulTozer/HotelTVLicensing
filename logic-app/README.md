# Hotel TV Licensing - Logic App Setup

This Logic App reads hotels from an Excel spreadsheet and enriches them with room counts, phone numbers, and website information using the Hotel API.

## Prerequisites

1. An Excel file stored in OneDrive for Business or SharePoint
2. The Excel data must be in a **Table** format (not just cells)
3. Azure subscription with permissions to create Logic Apps

## Excel File Format

Your Excel file should have a table with at least these columns:

| Hotel Name | Address | City | Postcode |
|------------|---------|------|----------|
| The Grand Hotel | 123 Main St | London | SW1A 1AA |
| Brighton Marina House Hotel | 8 Charlotte St | Brighton | BN2 1AG |

**Important**: Select your data and press `Ctrl+T` to convert it to a Table. Name the table (e.g., "Hotels").

## Deployment

### Option 1: Deploy via Azure CLI

```powershell
# Create resource group (if needed)
az group create --name rg-hotel-logic-app --location swedencentral

# Deploy the Logic App
az deployment group create `
    --resource-group rg-hotel-logic-app `
    --template-file logic-app/main.bicep `
    --parameters logicAppName=hotel-processor
```

### Option 2: Deploy via Azure Portal

1. Go to Azure Portal → Create a resource → Logic App
2. Create a blank Logic App
3. Import the workflow from `logic-app-workflow.json`

## Post-Deployment Setup

### 1. Authorize the Excel Connection

After deployment, you need to authorize the Excel Online connection:

1. Go to **Azure Portal** → **Resource Groups** → **rg-hotel-logic-app**
2. Click on **office365-connection**
3. Click **Edit API connection**
4. Click **Authorize** and sign in with your Microsoft 365 account
5. Click **Save**

### 2. Configure the Logic App

1. Open the Logic App in the Azure Portal
2. Click **Logic app designer**
3. Update the **Get rows from Excel** action:
   - Select your OneDrive/SharePoint location
   - Browse to your Excel file
   - Select your table name

## Running the Logic App

### Manual Trigger (via HTTP)

```powershell
# Get the Logic App URL (after deployment)
$callbackUrl = az logic workflow show `
    --resource-group rg-hotel-logic-app `
    --name hotel-processor `
    --query "triggers.manual.callbackUrl" -o tsv

# Trigger the Logic App
Invoke-RestMethod -Uri $callbackUrl -Method POST -ContentType "application/json" -Body '{}'
```

### Schedule Trigger (Optional)

To run automatically on a schedule, modify the trigger in the Logic App Designer:
1. Delete the HTTP trigger
2. Add a **Recurrence** trigger
3. Set your desired schedule (e.g., daily at 9 AM)

## Output

The Logic App returns a JSON response with all processed hotels:

```json
{
  "processed_count": 10,
  "results": [
    {
      "hotel_name": "The Grand Hotel",
      "address": "123 Main St, London",
      "rooms_min": 201,
      "rooms_max": 201,
      "official_website": "https://www.grandhotel.co.uk",
      "uk_contact_phone": "+44 20 1234 5678",
      "status": "success",
      "confidence_score": 0.95,
      "rooms_source_notes": "Found on About page"
    }
  ]
}
```

## Writing Results Back to Excel

To write results back to a new Excel file, add these actions after the For Each loop:

1. **Create file** (OneDrive) - Create a new CSV/Excel file
2. **Add a row into a table** - For each result, add a row

Or use the **Create CSV table** action to generate a CSV from the results array.

## Troubleshooting

### "Table not found" Error
- Ensure your data is formatted as an Excel Table (Ctrl+T)
- The table must have a name (check in Table Design tab)

### "Authorization failed" Error  
- Re-authorize the Excel connection in the API Connections blade

### Timeouts on Large Files
- The Logic App processes hotels sequentially with a 2-second delay
- For 100 hotels, expect ~5-10 minutes runtime
- Consider splitting large files into batches of 50

### Rate Limiting
- The API handles rate limiting automatically
- If you see many failures, increase the delay between calls

## Cost Estimation

- **Logic App**: ~$0.000025 per action execution
- **100 hotels** = ~500 actions = ~$0.0125 per run
- **Monthly (daily runs)**: ~$0.40/month

## Alternative: Batch Endpoint

For better performance, modify the Logic App to use the batch endpoint:

```json
{
  "method": "POST",
  "uri": "https://<your-app-name>.<unique-id>.swedencentral.azurecontainerapps.io/api/v1/hotel/batch",
  "body": {
    "hotels": [
      {"name": "Hotel 1", "address": "Address 1"},
      {"name": "Hotel 2", "address": "Address 2"}
    ]
  }
}
```

This processes multiple hotels in parallel (5 concurrent) and is faster for large batches.
