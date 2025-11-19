#!/usr/bin/env python3
"""
Simple web dashboard to monitor the case downloader process
"""
from flask import Flask, render_template_string, jsonify
import os
import subprocess
import json
from datetime import datetime

app = Flask(__name__)

# Configuration
LOG_FILE = "/tmp/main_streaming_upload.log"
SKYVERN_API_BASE = "http://5.161.210.79:8000/api/v1"
SKYVERN_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjQ5MDc5MzY4NDcsInN1YiI6Im9fNDYwODIyNzA2MTQ3NzI4MTE4In0.a81nQ5EZV5xcE942hWfzkU-3Z7Kwqc31ypgahKKithI"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Case Downloader Monitor</title>
    <meta http-equiv="refresh" content="10">
    <style>
        body {
            font-family: 'Courier New', monospace;
            background: #1e1e1e;
            color: #d4d4d4;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            color: #4ec9b0;
            border-bottom: 2px solid #4ec9b0;
            padding-bottom: 10px;
        }
        h2 {
            color: #569cd6;
            margin-top: 30px;
        }
        .status-box {
            background: #252526;
            border: 1px solid #3e3e42;
            border-radius: 5px;
            padding: 15px;
            margin: 10px 0;
        }
        .log-box {
            background: #1e1e1e;
            border: 1px solid #3e3e42;
            border-radius: 5px;
            padding: 15px;
            margin: 10px 0;
            max-height: 600px;
            overflow-y: auto;
            font-size: 12px;
            line-height: 1.4;
        }
        .log-line {
            margin: 2px 0;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        .log-line.error {
            color: #f48771;
        }
        .log-line.success {
            color: #4ec9b0;
        }
        .log-line.warning {
            color: #dcdcaa;
        }
        .log-line.info {
            color: #569cd6;
        }
        .metric {
            display: inline-block;
            margin: 10px 20px 10px 0;
        }
        .metric-label {
            color: #858585;
            font-size: 12px;
        }
        .metric-value {
            color: #4ec9b0;
            font-size: 24px;
            font-weight: bold;
        }
        .workflow {
            background: #2d2d30;
            border-left: 3px solid #007acc;
            padding: 10px;
            margin: 5px 0;
        }
        .workflow.completed {
            border-left-color: #4ec9b0;
        }
        .workflow.failed {
            border-left-color: #f48771;
        }
        .workflow.running {
            border-left-color: #dcdcaa;
        }
        .timestamp {
            color: #858585;
            font-size: 11px;
        }
        .refresh-notice {
            color: #858585;
            font-size: 12px;
            text-align: center;
            margin-top: 20px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }
        th, td {
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid #3e3e42;
        }
        th {
            color: #4ec9b0;
            font-weight: bold;
        }
        .status-completed { color: #4ec9b0; }
        .status-failed { color: #f48771; }
        .status-running { color: #dcdcaa; }
        .status-downloading { color: #569cd6; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Case Downloader Monitor</h1>
        <div class="timestamp">Last updated: {{ now }}</div>

        <h2>📈 System Status</h2>
        <div class="status-box">
            <div class="metric">
                <div class="metric-label">Process Status</div>
                <div class="metric-value">{{ process_status }}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Cases Downloading</div>
                <div class="metric-value">{{ downloading_count }}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Cases Ready</div>
                <div class="metric-value">{{ ready_count }}</div>
            </div>
        </div>

        <h2>🔄 Recent Workflows</h2>
        <div class="status-box">
            {% for wf in workflows %}
            <div class="workflow {{ wf.status }}">
                <strong>{{ wf.workflow_run_id }}</strong> -
                <span class="status-{{ wf.status }}">{{ wf.status }}</span>
                <br>
                <span class="timestamp">{{ wf.created_at }}</span>
            </div>
            {% endfor %}
        </div>

        <h2>📋 Notion Cases with "Downloading" Status</h2>
        <div class="status-box">
            {% if notion_downloading %}
            <table>
                <tr>
                    <th>Suspect Name</th>
                    <th>Page ID</th>
                    <th>Workflow Run ID</th>
                    <th>Download Link</th>
                </tr>
                {% for case in notion_downloading %}
                <tr>
                    <td>{{ case.suspect_name }}</td>
                    <td><code>{{ case.page_id[:20] }}...</code></td>
                    <td><code>{{ case.workflow_run_id or 'None' }}</code></td>
                    <td>{{ case.download_link[:50] }}...</td>
                </tr>
                {% endfor %}
            </table>
            {% else %}
            <p style="color: #858585;">No cases currently marked as "Downloading"</p>
            {% endif %}
        </div>

        <h2>📝 Live Logs (Last 100 lines)</h2>
        <div class="log-box">
            {% for line in log_lines %}
            <div class="log-line {{ line.class }}">{{ line.text }}</div>
            {% endfor %}
        </div>

        <div class="refresh-notice">
            Auto-refreshing every 10 seconds |
            <a href="/" style="color: #569cd6;">Manual Refresh</a>
        </div>
    </div>
</body>
</html>
"""

def get_process_status():
    """Check if main.py is running"""
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True
        )
        if "python3 -u main.py" in result.stdout or "python3 main.py" in result.stdout:
            return "Running ✅"
        return "Stopped ❌"
    except:
        return "Unknown"

def get_log_lines(num_lines=100):
    """Read last N lines from log file"""
    try:
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()[-num_lines:]

        formatted_lines = []
        for line in lines:
            line = line.rstrip()
            css_class = ""

            if "❌" in line or "Error" in line or "error" in line or "Failed" in line:
                css_class = "error"
            elif "✅" in line or "Success" in line or "completed" in line:
                css_class = "success"
            elif "⚠️" in line or "Warning" in line or "warning" in line:
                css_class = "warning"
            elif "INFO" in line or "Status:" in line:
                css_class = "info"

            formatted_lines.append({
                "text": line,
                "class": css_class
            })

        return formatted_lines
    except Exception as e:
        return [{"text": f"Error reading log: {e}", "class": "error"}]

def get_workflows():
    """Get recent workflow runs"""
    try:
        import requests
        response = requests.get(
            f"{SKYVERN_API_BASE}/workflow_runs?page=1&page_size=5",
            headers={"x-api-key": SKYVERN_API_KEY},
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("workflow_runs", [])
        return []
    except Exception as e:
        print(f"Error fetching workflows: {e}")
        return []

def get_notion_downloading_cases():
    """Get cases from Notion with 'Downloading' status"""
    try:
        import sys
        sys.path.insert(0, '/root/case-downloader')
        from notion_api import NotionCaseClient

        # Initialize Notion client
        notion_api_key = os.getenv('NOTION_API_KEY')
        notion_db_id = os.getenv('NOTION_DATABASE_ID')

        if not notion_api_key or not notion_db_id:
            return []

        notion = NotionCaseClient(notion_api_key, notion_db_id)

        # Query for cases with "Downloading" status
        response = notion.client.databases.query(
            database_id=notion_db_id,
            filter={
                "property": "Download Status",
                "select": {
                    "equals": "Downloading"
                }
            },
            page_size=10
        )

        cases = []
        for page in response.get('results', []):
            case_data = notion._extract_case_data(page)
            if case_data:
                cases.append({
                    "suspect_name": case_data.get('suspect_name', 'Unknown'),
                    "page_id": case_data.get('page_id', 'N/A'),
                    "workflow_run_id": case_data.get('workflow_run_id', None),
                    "download_link": case_data.get('download_links', [''])[0] if case_data.get('download_links') else ''
                })

        return cases
    except Exception as e:
        print(f"Error fetching Notion cases: {e}")
        return []

def count_notion_cases(status):
    """Count cases with a specific status in Notion"""
    try:
        import sys
        sys.path.insert(0, '/root/case-downloader')
        from notion_api import NotionCaseClient

        notion_api_key = os.getenv('NOTION_API_KEY')
        notion_db_id = os.getenv('NOTION_DATABASE_ID')

        if not notion_api_key or not notion_db_id:
            return 0

        notion = NotionCaseClient(notion_api_key, notion_db_id)
        return notion.count_cases_with_status(status)
    except Exception as e:
        print(f"Error counting Notion cases: {e}")
        return 0

@app.route('/')
def index():
    """Main dashboard page"""
    process_status = get_process_status()
    log_lines = get_log_lines(100)
    workflows = get_workflows()
    downloading_count = count_notion_cases("Downloading")
    ready_count = count_notion_cases("Ready For Download")
    notion_downloading = get_notion_downloading_cases()

    return render_template_string(
        HTML_TEMPLATE,
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        process_status=process_status,
        log_lines=log_lines,
        workflows=workflows,
        downloading_count=downloading_count,
        ready_count=ready_count,
        notion_downloading=notion_downloading
    )

@app.route('/api/status')
def api_status():
    """JSON API endpoint"""
    return jsonify({
        "process_status": get_process_status(),
        "workflows": get_workflows(),
        "downloading_count": count_notion_cases("Downloading"),
        "ready_count": count_notion_cases("Ready For Download"),
        "notion_downloading": get_notion_downloading_cases()
    })

if __name__ == '__main__':
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv('/root/case-downloader/.env')

    # Run on port 8082
    app.run(host='0.0.0.0', port=8082, debug=False)
