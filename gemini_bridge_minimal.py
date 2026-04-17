#!/usr/bin/env python3
"""
MINIMAL Gemini Bridge - Zero dependencies except Flask
Works offline, no database required initially
"""

from flask import Flask, render_template_string, request, jsonify
from datetime import datetime
import threading
import time

app = Flask(__name__)

# In-memory storage (no database needed)
tasks = []
reminders = []
heartbeats = []

# HTML UI embedded
UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gemini Bridge</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0f172a;
            color: #f1f5f9;
            padding: 2rem;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { margin-bottom: 1rem; color: #10b981; }
        .nav { 
            display: flex; 
            gap: 1rem; 
            margin-bottom: 2rem;
            flex-wrap: wrap;
        }
        button {
            background: #1e293b;
            color: #f1f5f9;
            border: 2px solid #334155;
            padding: 0.75rem 1.5rem;
            cursor: pointer;
            border-radius: 0.5rem;
            font-weight: 600;
            transition: all 0.2s;
        }
        button:hover, button.active {
            background: #10b981;
            border-color: #10b981;
        }
        .page { display: none; padding: 1.5rem; background: #1e293b; border-radius: 0.5rem; }
        .page.active { display: block; }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .status-box {
            background: #0f172a;
            border: 2px solid #334155;
            padding: 1rem;
            border-radius: 0.5rem;
        }
        .status-label { font-size: 0.875rem; color: #cbd5e1; margin-bottom: 0.5rem; }
        .status-value { font-size: 1.5rem; color: #22c55e; font-weight: bold; }
        input, textarea {
            background: #0f172a;
            color: #f1f5f9;
            border: 2px solid #334155;
            padding: 0.75rem;
            border-radius: 0.5rem;
            font-family: inherit;
            width: 100%;
            margin-bottom: 1rem;
        }
        input:focus, textarea:focus {
            outline: none;
            border-color: #10b981;
        }
        .form-group { margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; font-weight: 600; }
        .task-list { max-height: 400px; overflow-y: auto; }
        .task-item {
            background: #0f172a;
            border: 1px solid #334155;
            padding: 1rem;
            margin-bottom: 0.5rem;
            border-radius: 0.5rem;
        }
        .task-status {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 0.25rem;
            font-size: 0.875rem;
            font-weight: 600;
        }
        .task-status.pending { background: #f59e0b; color: #000; }
        .task-status.completed { background: #22c55e; color: #000; }
        .task-status.running { background: #3b82f6; color: #fff; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌉 Gemini Bridge Control Center</h1>
        
        <div class="nav">
            <button onclick="showPage('dashboard')" class="nav-btn active">Dashboard</button>
            <button onclick="showPage('task')" class="nav-btn">Submit Task</button>
            <button onclick="showPage('monitor')" class="nav-btn">Monitor</button>
            <button onclick="showPage('history')" class="nav-btn">History</button>
        </div>

        <!-- Dashboard -->
        <div id="dashboard" class="page active">
            <h2>System Status</h2>
            <div class="status-grid">
                <div class="status-box">
                    <div class="status-label">System Status</div>
                    <div class="status-value" id="sys-status">🟢 ONLINE</div>
                </div>
                <div class="status-box">
                    <div class="status-label">Uptime</div>
                    <div class="status-value" id="sys-uptime">0s</div>
                </div>
                <div class="status-box">
                    <div class="status-label">Tasks Completed</div>
                    <div class="status-value" id="sys-tasks">0</div>
                </div>
                <div class="status-box">
                    <div class="status-label">Last Heartbeat</div>
                    <div class="status-value" id="sys-heartbeat">--</div>
                </div>
            </div>
            <button onclick="refreshStatus()">Refresh Status</button>
        </div>

        <!-- Submit Task -->
        <div id="task" class="page">
            <h2>Submit Task to Gemini CLI</h2>
            <div class="form-group">
                <label for="prompt">Task Description:</label>
                <textarea id="prompt" placeholder="What do you want Gemini to do?" rows="6"></textarea>
            </div>
            <div class="form-group">
                <label for="route">Route To:</label>
                <select id="route" style="background: #0f172a; color: #f1f5f9; border: 2px solid #334155; padding: 0.75rem; border-radius: 0.5rem; width: 100%;">
                    <option value="gemini">Gemini CLI</option>
                    <option value="cursor">Cursor AI</option>
                    <option value="auto">Auto (failover)</option>
                </select>
            </div>
            <button onclick="submitTask()">Submit Task</button>
            <div id="task-response" style="margin-top: 1rem; display: none; background: #0f172a; padding: 1rem; border-radius: 0.5rem;"></div>
        </div>

        <!-- Monitor -->
        <div id="monitor" class="page">
            <h2>Real-Time Monitor</h2>
            <p>System is collecting heartbeat data every 60 seconds</p>
            <div class="status-grid">
                <div class="status-box">
                    <div class="status-label">API Status</div>
                    <div class="status-value" id="monitor-api">✅ Ready</div>
                </div>
                <div class="status-box">
                    <div class="status-label">Heartbeats Collected</div>
                    <div class="status-value" id="monitor-hb">0</div>
                </div>
            </div>
            <button onclick="refreshMonitor()">Refresh</button>
        </div>

        <!-- History -->
        <div id="history" class="page">
            <h2>Task History</h2>
            <div class="task-list" id="history-list">
                <p style="color: #cbd5e1;">No tasks yet</p>
            </div>
        </div>
    </div>

    <script>
        const startTime = Date.now();

        function showPage(page) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(page).classList.add('active');
            event.target.classList.add('active');
        }

        function refreshStatus() {
            fetch('/api/health')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('sys-status').textContent = '🟢 ONLINE';
                    const uptime = Math.floor((Date.now() - startTime) / 1000);
                    document.getElementById('sys-uptime').textContent = uptime + 's';
                })
                .catch(e => {
                    document.getElementById('sys-status').textContent = '🔴 OFFLINE';
                });
        }

        function submitTask() {
            const prompt = document.getElementById('prompt').value;
            const route = document.getElementById('route').value;
            
            if (!prompt) {
                alert('Please enter a task');
                return;
            }

            fetch('/api/task', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt, route_to: route })
            })
            .then(r => r.json())
            .then(data => {
                const resp = document.getElementById('task-response');
                resp.style.display = 'block';
                resp.innerHTML = `<strong>✅ Task Submitted!</strong><br>ID: ${data.task_id}<br>Status: ${data.status}`;
                document.getElementById('prompt').value = '';
                setTimeout(() => refreshHistory(), 1000);
            })
            .catch(e => {
                document.getElementById('task-response').style.display = 'block';
                document.getElementById('task-response').innerHTML = `<strong>❌ Error:</strong> ${e}`;
            });
        }

        function refreshHistory() {
            fetch('/api/task')
                .then(r => r.json())
                .then(data => {
                    const list = document.getElementById('history-list');
                    if (!data.tasks || data.tasks.length === 0) {
                        list.innerHTML = '<p style="color: #cbd5e1;">No tasks yet</p>';
                        return;
                    }
                    list.innerHTML = data.tasks.map(t => `
                        <div class="task-item">
                            <span class="task-status ${t.status}">${t.status}</span>
                            <p>${t.prompt.substring(0, 100)}</p>
                            <small>${new Date(t.created_at).toLocaleString()}</small>
                        </div>
                    `).join('');
                });
        }

        function refreshMonitor() {
            fetch('/api/heartbeat')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('monitor-api').textContent = '✅ Ready';
                });
        }

        // Auto-refresh
        setInterval(refreshStatus, 5000);
        setInterval(refreshHistory, 10000);
    </script>
</body>
</html>
"""

# ===== API ENDPOINTS =====

@app.route('/')
def index():
    return jsonify({"message": "Gemini Bridge API - Minimal Edition", "version": "1.0"})

@app.route('/ui')
def ui():
    return render_template_string(UI_HTML)

@app.route('/api/health')
def health():
    return {
        "status": "ONLINE",
        "version": "1.0",
        "uptime_seconds": int((datetime.utcnow() - start_time).total_seconds()),
        "tasks_total": len(tasks),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.route('/api/task', methods=['GET', 'POST'])
def task_handler():
    if request.method == 'POST':
        data = request.get_json()
        prompt = data.get('prompt')
        route = data.get('route_to', 'gemini')
        
        task = {
            'id': len(tasks) + 1,
            'prompt': prompt,
            'route_to': route,
            'status': 'pending',
            'created_at': datetime.utcnow().isoformat(),
            'output': None
        }
        tasks.append(task)
        
        # Async execution
        threading.Thread(target=execute_task, args=(task,), daemon=True).start()
        
        return {'task_id': task['id'], 'status': 'submitted'}, 201
    else:
        return {'tasks': sorted(tasks, key=lambda x: x['created_at'], reverse=True)[:10]}

@app.route('/api/task/<int:task_id>')
def get_task(task_id):
    task = next((t for t in tasks if t['id'] == task_id), None)
    return task or {'error': 'not found'}, 404

@app.route('/api/heartbeat')
def heartbeat():
    hb = {
        'timestamp': datetime.utcnow().isoformat(),
        'status': 'healthy',
        'tasks_count': len(tasks)
    }
    heartbeats.append(hb)
    return hb

# Background task execution
def execute_task(task):
    try:
        task['status'] = 'running'
        time.sleep(2)  # Simulate work
        task['status'] = 'completed'
        task['output'] = f"Task processed: {task['prompt'][:50]}..."
        print(f"[TASK {task['id']}] {task['status'].upper()}")
    except Exception as e:
        task['status'] = 'failed'
        task['output'] = str(e)

# Track start time
start_time = datetime.utcnow()

if __name__ == '__main__':
    print("=" * 60)
    print("🌉 GEMINI BRIDGE - MINIMAL EDITION")
    print("=" * 60)
    print("\n✅ Starting Flask server...")
    print("   URL: http://localhost:5000/ui")
    print("   API: http://localhost:5000/api/health")
    print("\nNo dependencies required - Flask only!")
    print("=" * 60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False)
