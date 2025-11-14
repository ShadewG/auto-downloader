#!/usr/bin/env python3
"""
Web-based progress monitor for Skyvern downloads with Queue display.

Shows both active Skyvern tasks and upcoming cases from Notion.
Access at: http://SERVER_IP:8081
"""

import json
import os
import sys
from pathlib import Path
from flask import Flask, jsonify, render_template_string
from datetime import datetime

# Add case-downloader to path for imports
sys.path.insert(0, '/root/case-downloader')

app = Flask(__name__)

PROGRESS_FILE = Path("/root/case-downloader/download_progress.json")

# Import Notion API to get queue
try:
    from notion_api import NotionAPI
    from dotenv import load_dotenv
    load_dotenv('/root/case-downloader/.env')
    NOTION_API_KEY = os.getenv('NOTION_API_KEY')
    NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
    notion_client = NotionAPI(NOTION_API_KEY, NOTION_DATABASE_ID)
    NOTION_AVAILABLE = True
except ImportError:
    NOTION_AVAILABLE = False
    notion_client = None

# HTML template with queue section
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Skyvern Download Progress & Queue</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 30px;
            text-align: center;
        }
        .header h1 {
            color: #333;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        .header .subtitle {
            color: #666;
            font-size: 1.1em;
        }
        .refresh-info {
            color: #888;
            font-size: 0.9em;
            margin-top: 10px;
        }

        /* Section headers */
        .section-header {
            background: white;
            padding: 15px 25px;
            border-radius: 10px;
            margin-bottom: 15px;
            box-shadow: 0 3px 10px rgba(0,0,0,0.1);
        }
        .section-header h2 {
            color: #333;
            font-size: 1.5em;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .section-header .count {
            background: #667eea;
            color: white;
            padding: 2px 12px;
            border-radius: 20px;
            font-size: 0.8em;
        }

        .task-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .task-card {
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.15);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .task-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
        }
        .task-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 2px solid #f0f0f0;
        }
        .task-name {
            font-size: 1.3em;
            font-weight: 600;
            color: #333;
            flex: 1;
        }
        .status-badge {
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .status-created { background: #e3f2fd; color: #1976d2; }
        .status-queued { background: #fff3e0; color: #f57c00; }
        .status-running { background: #e8f5e9; color: #388e3c; }
        .status-completed { background: #c8e6c9; color: #2e7d32; }
        .status-failed { background: #ffebee; color: #c62828; }
        .status-error { background: #ffebee; color: #c62828; }
        .status-terminated { background: #fff9c4; color: #f57f17; }

        .task-info {
            margin: 15px 0;
        }
        .info-row {
            display: flex;
            margin: 8px 0;
            font-size: 0.95em;
        }
        .info-label {
            font-weight: 600;
            color: #666;
            min-width: 120px;
        }
        .info-value {
            color: #333;
            flex: 1;
            word-break: break-all;
        }
        .progress-bar-container {
            background: #f0f0f0;
            border-radius: 10px;
            height: 25px;
            overflow: hidden;
            margin: 15px 0;
        }
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 0.85em;
        }
        .current-action {
            background: #f5f5f5;
            padding: 12px;
            border-radius: 8px;
            margin: 15px 0;
            font-size: 0.9em;
            color: #555;
        }

        /* Queue list styles */
        .queue-list {
            background: white;
            border-radius: 15px;
            padding: 0;
            box-shadow: 0 5px 20px rgba(0,0,0,0.15);
            overflow: hidden;
        }
        .queue-item {
            padding: 20px 25px;
            border-bottom: 1px solid #f0f0f0;
            transition: background 0.2s;
            display: flex;
            align-items: center;
            gap: 20px;
        }
        .queue-item:hover {
            background: #f8f9fa;
        }
        .queue-item:last-child {
            border-bottom: none;
        }
        .queue-number {
            background: #667eea;
            color: white;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 1.1em;
            flex-shrink: 0;
        }
        .queue-details {
            flex: 1;
        }
        .queue-name {
            font-size: 1.1em;
            font-weight: 600;
            color: #333;
            margin-bottom: 5px;
        }
        .queue-url {
            font-size: 0.85em;
            color: #666;
            font-family: monospace;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .no-items {
            text-align: center;
            padding: 60px 20px;
            background: white;
            border-radius: 15px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.15);
        }
        .no-items-icon {
            font-size: 4em;
            margin-bottom: 20px;
        }
        .no-items h3 {
            color: #666;
            margin-bottom: 10px;
        }
        .no-items p {
            color: #999;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Skyvern Download Monitor</h1>
            <div class="subtitle">Real-time monitoring & queue tracking</div>
            <div class="refresh-info">Auto-refreshing every 3 seconds</div>
        </div>

        <!-- Active Tasks Section -->
        <div class="section-header">
            <h2>
                ⚡ Active Skyvern Tasks
                <span class="count" id="active-count">0</span>
            </h2>
        </div>
        <div id="active-tasks" class="task-grid">
            <div class="no-items">
                <div class="no-items-icon">⏳</div>
                <h3>Loading...</h3>
                <p>Fetching active tasks...</p>
            </div>
        </div>

        <!-- Queue Section -->
        <div class="section-header">
            <h2>
                📋 Download Queue
                <span class="count" id="queue-count">0</span>
            </h2>
        </div>
        <div id="queue-container">
            <div class="no-items">
                <div class="no-items-icon">⏳</div>
                <h3>Loading...</h3>
                <p>Fetching queue from Notion...</p>
            </div>
        </div>
    </div>

    <script>
        function updateProgress() {
            fetch('/api/progress')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('active-tasks');
                    const countBadge = document.getElementById('active-count');

                    if (Object.keys(data).length === 0) {
                        container.innerHTML = `
                            <div class="no-items">
                                <div class="no-items-icon">📭</div>
                                <h3>No Active Skyvern Tasks</h3>
                                <p>Skyvern tasks will appear here when running</p>
                            </div>
                        `;
                        countBadge.textContent = '0';
                        return;
                    }

                    container.innerHTML = '';
                    countBadge.textContent = Object.keys(data).length;

                    const tasks = Object.values(data).sort((a, b) =>
                        new Date(b.started_at) - new Date(a.started_at)
                    );

                    tasks.forEach(task => {
                        const progress = task.max_steps > 0
                            ? Math.round((task.steps_completed / task.max_steps) * 100)
                            : 0;

                        const statusClass = `status-${task.status.toLowerCase()}`;

                        const card = document.createElement('div');
                        card.className = 'task-card';
                        card.innerHTML = `
                            <div class="task-header">
                                <div class="task-name">${task.suspect_name || 'Unknown'}</div>
                                <div class="status-badge ${statusClass}">${task.status}</div>
                            </div>

                            <div class="task-info">
                                <div class="info-row">
                                    <div class="info-label">Task ID:</div>
                                    <div class="info-value">${task.task_id.substring(0, 12)}...</div>
                                </div>
                                <div class="info-row">
                                    <div class="info-label">URL:</div>
                                    <div class="info-value">${task.url.substring(0, 50)}...</div>
                                </div>
                                <div class="info-row">
                                    <div class="info-label">Started:</div>
                                    <div class="info-value">${new Date(task.started_at).toLocaleString()}</div>
                                </div>
                                ${task.files_downloaded > 0 ? `
                                <div class="info-row">
                                    <div class="info-label">Files Downloaded:</div>
                                    <div class="info-value">${task.files_downloaded}</div>
                                </div>
                                ` : ''}
                            </div>

                            ${task.status === 'running' && task.max_steps > 0 ? `
                            <div class="progress-bar-container">
                                <div class="progress-bar" style="width: ${progress}%">
                                    Step ${task.steps_completed}/${task.max_steps} (${progress}%)
                                </div>
                            </div>
                            ` : ''}

                            <div class="current-action">
                                ${task.current_action || 'Processing...'}
                            </div>

                            ${task.failure_reason ? `
                            <div class="current-action" style="background: #ffebee; color: #c62828;">
                                ❌ ${task.failure_reason}
                            </div>
                            ` : ''}
                        `;

                        container.appendChild(card);
                    });
                })
                .catch(error => {
                    console.error('Error fetching progress:', error);
                });
        }

        function updateQueue() {
            fetch('/api/queue')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('queue-container');
                    const countBadge = document.getElementById('queue-count');

                    if (!data.cases || data.cases.length === 0) {
                        container.innerHTML = `
                            <div class="no-items">
                                <div class="no-items-icon">✅</div>
                                <h3>Queue Empty</h3>
                                <p>No cases waiting for download</p>
                            </div>
                        `;
                        countBadge.textContent = '0';
                        return;
                    }

                    const queueList = document.createElement('div');
                    queueList.className = 'queue-list';

                    countBadge.textContent = data.cases.length;

                    data.cases.forEach((caseItem, index) => {
                        const item = document.createElement('div');
                        item.className = 'queue-item';
                        item.innerHTML = `
                            <div class="queue-number">${index + 1}</div>
                            <div class="queue-details">
                                <div class="queue-name">${caseItem.name}</div>
                                <div class="queue-url">${caseItem.url || 'No URL'}</div>
                            </div>
                        `;
                        queueList.appendChild(item);
                    });

                    container.innerHTML = '';
                    container.appendChild(queueList);
                })
                .catch(error => {
                    console.error('Error fetching queue:', error);
                });
        }

        // Update both immediately and then every 3 seconds
        updateProgress();
        updateQueue();
        setInterval(() => {
            updateProgress();
            updateQueue();
        }, 3000);
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    """Serve the progress monitor page."""
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/progress')
def get_progress():
    """API endpoint to get current Skyvern task progress."""
    try:
        if not PROGRESS_FILE.exists():
            return jsonify({})

        with open(PROGRESS_FILE, 'r') as f:
            progress_data = json.load(f)

        return jsonify(progress_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/queue')
def get_queue():
    """API endpoint to get queue of pending cases from Notion."""
    try:
        if not NOTION_AVAILABLE:
            return jsonify({"error": "Notion API not available", "cases": []})

        # Get cases from Notion
        cases = notion_client.get_cases_ready_for_download()

        # Format for display
        queue_data = {
            "cases": [
                {
                    "name": case.get('name', 'Unknown'),
                    "url": case.get('download_links', [''])[0] if case.get('download_links') else 'No URL'
                }
                for case in cases
            ]
        }

        return jsonify(queue_data)
    except Exception as e:
        return jsonify({"error": str(e), "cases": []})


if __name__ == '__main__':
    print("=" * 80)
    print("Skyvern Download Progress Monitor with Queue")
    print("=" * 80)
    print()
    print("Starting web server on port 8081...")
    print("Access the monitor at: http://YOUR_SERVER_IP:8081")
    print()
    print("Features:")
    print("  - Real-time Skyvern task monitoring")
    print("  - Download queue from Notion")
    print("  - Auto-refresh every 3 seconds")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 80)

    app.run(host='0.0.0.0', port=8081, debug=False)
