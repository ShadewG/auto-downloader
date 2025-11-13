# Case Download & Upload Automation

Automatically downloads case files from links in Notion and uploads them to Dropbox (team folder).

## Setup

### 1. Authorize Dropbox (First Time Only)

Before running the main application, you need to authorize Dropbox:

```bash
cd /root/case-downloader
source venv/bin/activate
python setup_dropbox.py
```

This will:
1. Display an authorization URL
2. You'll need to visit that URL in your browser
3. Click "Allow" to authorize the app
4. Copy the authorization code
5. Paste it back into the terminal

The token will be saved to `.dropbox_token` for future use.

### 2. Configure Test/Continuous Mode

Edit `.env` file:

```bash
# For testing (runs once, processes 4 cases)
TEST_MODE=True
TEST_CASE_LIMIT=4

# For continuous monitoring (checks every hour)
TEST_MODE=False
CHECK_INTERVAL=3600
```

## Usage

### Option 1: Manual Run (Test Mode)

```bash
cd /root/case-downloader
source venv/bin/activate
python main.py
```

### Option 2: Continuous Service

```bash
# Enable and start the service
sudo systemctl enable case-downloader
sudo systemctl start case-downloader

# Check status
sudo systemctl status case-downloader

# View logs
sudo tail -f /var/log/case-downloader.log

# Stop the service
sudo systemctl stop case-downloader
```

## How It Works

1. **Notion Query**: Searches for cases where:
   - "Download Status" = "Ready for Download"
   - "Download Link" is not empty

2. **Download**: 
   - Updates status to "Downloading"
   - Downloads files from all link fields:
     - Download Link
     - Download Link (2)
     - Download Link (3)
     - Download Links (4) (text field with multiple URLs)
   - Uses login credentials from "Download Login" field if needed
   - Tries simple HTTP download first, falls back to Playwright for complex sites

3. **Upload**:
   - Updates status to "Uploading"
   - Creates folder: `/Cases/{Suspect Name} {YYYY-MM-DD}`
   - Uploads all files to Dropbox
   - Generates shared link
   - Adds link to Notion "Dropbox URL" field
   - Updates status to "Uploaded"

4. **Cleanup**: Deletes local files after successful upload

## Notion Fields Used

- **Download Status** (select): Ready for Download → Downloading → Uploading → Uploaded
- **Download Link** (URL): Primary download link
- **Download Link (2)** (URL): Additional link
- **Download Link (3)** (URL): Additional link
- **Download Links (4)** (rich_text): Multiple URLs separated by spaces/newlines
- **Download Login** (rich_text): Login credentials (format: username:password)
- **Suspect** (rich_text): Used for folder naming
- **Dropbox URL** (URL): Populated with shared link after upload

## File Structure

```
/root/case-downloader/
├── main.py                 # Main orchestrator
├── notion_api.py          # Notion API client
├── dropbox_client.py      # Dropbox API client with OAuth
├── downloader.py          # Download handler (HTTP + Playwright)
├── setup_dropbox.py       # Dropbox authorization helper
├── debug_notion.py        # Notion database inspector
├── .env                   # Configuration & credentials
├── .dropbox_token         # Saved Dropbox token (auto-generated)
├── requirements.txt       # Python dependencies
└── venv/                  # Python virtual environment
```

## Debugging

### Check Notion Database Structure

```bash
cd /root/case-downloader
source venv/bin/activate
python debug_notion.py
```

This shows:
- All available Notion properties
- First 5 pages with their status
- Count of pages matching "Ready for Download"

### Check Logs

```bash
# Service logs
sudo tail -f /var/log/case-downloader.log
sudo tail -f /var/log/case-downloader-error.log

# Manual run shows output directly in terminal
```

## Requirements

- Python 3.12+
- 289GB free disk space on volume
- Network access to Notion, Dropbox, and download sources
- Dropbox app credentials with team folder access

## Environment Variables

See `.env` file for all configuration options:
- NOTION_API_KEY
- NOTION_DATABASE_ID
- DROPBOX_APP_KEY
- DROPBOX_APP_SECRET
- DOWNLOAD_PATH
- CHECK_INTERVAL
- TEST_MODE
- TEST_CASE_LIMIT
