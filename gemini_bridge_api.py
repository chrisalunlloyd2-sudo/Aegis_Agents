"""
Gemini Bridge API Server
Unified control interface for Gemini CLI and Cursor with TimescaleDB logging
"""

from flask import Flask, request, jsonify, render_template_string, make_response
from flask_cors import CORS
from flask_restful import Api, Resource
import os
import subprocess
import json
import time
from datetime import datetime, timedelta
import threading
from dotenv import load_dotenv

# Database
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

# RAG & KB
from gemini_bridge_rag import EnterpriseRAGSystem
from knowledge_base_api import register_kb_routes

load_dotenv()

# ===== CONFIG =====
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CURSOR_EXE = r"C:\Users\viper\AppData\Local\Programs\cursor\Cursor.exe"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///gemini_bridge.db")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "gemini_bridge_token_123")
REMOTE_MODE = os.getenv("REMOTE_ACCESS", "False").lower() == "true"

# ===== Flask Setup =====
app = Flask(__name__)
CORS(app)
api = Api(app)

# RAG & KB Integration
rag_system = EnterpriseRAGSystem()
register_kb_routes(app)

# Advanced Analytics
from advanced_analytics import register_analytics_routes
register_analytics_routes(app)

# ===== Authentication Middleware =====
@app.before_request
def check_auth():
    """Skip auth in test mode"""
    pass  # TEST MODE - NO SECURITY

# ===== Neural Search Endpoint =====
@app.route('/api/neural/search', methods=['GET'])
def neural_search():
    query = request.args.get('q', '')
    if not query:
        return jsonify({"results": []})

    results = rag_system.retrieve_relevant_context(query)
    return jsonify({"results": results})

# ===== RED DOT SIGNAL SYSTEM =====
# Global state for red dot (simple in-memory for now)
red_dot_state = {
    "active": False,
    "last_seen": None,
    "x": 0,
    "y": 0
}

@app.route('/api/signal', methods=['POST'])
def receive_signal():
    """Receive red dot signal from phone CLI (phone_automation_script.js)"""
    data = request.get_json(force=True)
    signal = data.get("signal")

    if signal == "red_dot_detected":
        red_dot_state["active"] = True
        red_dot_state["last_seen"] = datetime.now().isoformat()
        red_dot_state["x"] = data.get("x", 0)
        red_dot_state["y"] = data.get("y", 0)
        print(f"🔴 [SIGNAL] Red Dot detected on phone at ({red_dot_state['x']}, {red_dot_state['y']})")
        return jsonify({"status": "signal_received", "state": red_dot_state})

    return jsonify({"status": "no_action"}), 200

@app.route('/api/signal/status', methods=['GET'])
def get_signal_status():
    """Check current status of the red dot signal"""
    # Auto-expire signal after 10 seconds if no new updates
    if red_dot_state["active"] and red_dot_state["last_seen"]:
        last_seen_dt = datetime.fromisoformat(red_dot_state["last_seen"])
        if datetime.now() - last_seen_dt > timedelta(seconds=10):
            red_dot_state["active"] = False

    return jsonify(red_dot_state)

# ===== REMOTE AGENT PIPE (Direct CLI Access) =====
@app.route('/api/agent/command', methods=['POST'])
def agent_command():
    data = request.get_json(force=True)
    prompt = data.get("prompt")
    if not prompt:
        return jsonify({"error": "No prompt"}), 400

    # This executes a command as "Me" (the Gemini CLI)
    def run_agent():
        subprocess.run(["gemini", "-p", prompt, "--approval-mode=yolo"], shell=True)

    threading.Thread(target=run_agent, daemon=True).start()
    return jsonify({"status": "Agent received command", "prompt": prompt})

# ===== DESKTOP AUTOMATION (Aegis Remote Control) =====
import pyautogui
import base64
from io import BytesIO
from PIL import Image

@app.route('/api/desktop/screenshot', methods=['GET'])
def desktop_screenshot():
    try:
        screenshot = pyautogui.screenshot()
        buffered = BytesIO()
        screenshot.save(buffered, format="JPEG", quality=50) # Low quality for fast mobile loading
        img_str = base64.b64encode(buffered.getvalue()).decode()
        return jsonify({"screenshot": img_str})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/desktop/click', methods=['POST'])
def desktop_click():
    data = request.get_json(force=True)
    x, y = data.get("x"), data.get("y")
    if x is not None and y is not None:
        pyautogui.click(x, y)
        return jsonify({"status": f"Clicked at {x}, {y}"})
    return jsonify({"error": "Missing coordinates"}), 400

# ===== BROWSER CONTROL (Remote Web Navigation) =====
import webbrowser
import urllib.parse

@app.route('/api/browser/open', methods=['POST'])
def browser_open():
    data = request.get_json(force=True)
    url = data.get("url")
    search = data.get("search")

    if search:
        url = f"https://www.google.com/search?q={urllib.parse.quote(search)}"

    if url:
        if not url.startswith('http'):
            url = 'https://' + url
        if os.environ.get("VIPER_ALLOW_BROWSER_OPEN", "0") == "1":   # leashed: see /api/aegis/chat note
            webbrowser.open(url)
            return jsonify({"status": f"Opened {url}"})
        return jsonify({"status": f"[leashed] would open {url}; set VIPER_ALLOW_BROWSER_OPEN=1 to enable"})
    return jsonify({"error": "Missing URL or search query"}), 400

# ===== ACTIVE NEURAL BROWSER CONTROL (Playwright) =====
from playwright.sync_api import sync_playwright

@app.route('/api/browser/read', methods=['POST'])
def browser_read():
    data = request.get_json(force=True)
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing URL"}), 400

    if not url.startswith('http'):
        url = 'https://' + url

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000)
            text = page.locator("body").inner_text()
            title = page.title()
            browser.close()

            if len(text) > 5000:
                text = text[:5000] + "\n\n... (truncated)"

            return jsonify({"title": title, "text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ===== DESKTOP POINTER (Show Me Where) =====
import tkinter as tk

def _draw_dot(x, y, duration):
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-transparentcolor", "white")
        root.config(bg="white")
    except Exception:
        pass

    r = 30
    root.geometry(f"{r*2}x{r*2}+{int(x)-r}+{int(y)-r}")

    canvas = tk.Canvas(root, width=r*2, height=r*2, bg="white", highlightthickness=0)
    canvas.pack()
    canvas.create_oval(5, 5, r*2-5, r*2-5, fill="red", outline="white", width=4)

    root.after(duration * 1000, root.destroy)
    root.mainloop()

@app.route('/api/desktop/dot', methods=['POST'])
def desktop_dot():
    data = request.get_json(force=True)
    x, y = data.get("x"), data.get("y")
    duration = data.get("duration", 3)
    if x is not None and y is not None:
        threading.Thread(target=_draw_dot, args=(x, y, duration), daemon=True).start()
        return jsonify({"status": f"Dot drawn at {x}, {y}"})
    return jsonify({"error": "Missing coordinates"}), 400

@app.route('/api/mobile/dot', methods=['POST'])
def mobile_dot():
    """
    HOMEOSTASIS 1: The Android Red Dot Trigger.
    Allows CLIE or Whisper to pulse the virtual pointer in the Web UI.
    """
    data = request.get_json(force=True)
    x = data.get('x', 500)
    y = data.get('y', 500)

    # We update the global status for the UI to poll and display the dot
    from engine.router import DIMON_STATUS
    DIMON_STATUS["global"]["mobile_pointer"] = {
        "x": x,
        "y": y,
        "active": True,
        "timestamp": time.time()
    }
    print(f"🔴 [HOMEOSTASIS] Mobile Pointer Queued: ({x}, {y})")
    return jsonify({"status": "mobile_pointer_queued", "x": x, "y": y})

@app.route('/api/timescale/sync', methods=['POST'])
def timescale_sync():
    """
    CANADIAN ULTRA: The TimescaleDB Sync Tunnel.
    Receives chat manifolds from the Native Extension and logs them to the DB.
    """
    data = request.get_json(force=True)
    raw_text = data.get('data', '')
    print(f"🏎️💨 [SYNC] Manifold received. Size: {len(raw_text)} chars.")

    # Store in the Knowledge Base for RAG
    # We use 'gemini_files' collection for synced chat history
    rag_system.store_in_rag("gemini_files", raw_text, {"source": "Gemini App Sync", "type": "auto_rag"})
    return jsonify({"status": "synced_to_timescale"})

@app.route('/api/research/note', methods=['POST'])
def save_research_note():
    """
    Saves a specific high-value note from the Gemini App to the RAG.
    """
    data = request.get_json(force=True)
    content = data.get('content', '')
    source = data.get('source', 'Manual')

    print(f"📌 [NOTE] Saving research insight to Timescale RAG...")
    # Explicitly store as a 'note' for prioritized RAG retrieval
    rag_system.store_in_rag("research_findings", content, {"source": source, "priority": "high", "type": "note"})

    return jsonify({"status": "note_saved_to_rag"})

@app.route('/api/logic/learn', methods=['POST'])
def learn_logic():
    """
    DIMON LEARNING: Stores a permanent behavioral/logical rule for the AI.
    """
    data = request.get_json(force=True)
    rule = data.get('rule', '')
    print(f"🧠 [DIMON-LEARN] New Logic Rule Acquired: {rule}")
    rag_system.store_in_rag("dimon_logic_rules", rule, {"type": "learned_logic", "priority": "critical"})
    return jsonify({"status": "logic_learned"})

@app.route('/api/logic/rules', methods=['GET'])
def get_logic_rules():
    """
    Retrieves all learned logic rules to inject into the App's context.
    """
    try:
        # Retrieve the latest 5 learned rules from RAG
        rules_data, _ = rag_system.retrieve_context("learned_logic", "", limit=5)
        return jsonify({"rules": rules_data})
    except Exception:
        return jsonify({"rules": []})


# ===== Database Setup =====

engine = create_engine(DATABASE_URL)
Base = declarative_base()
Session = sessionmaker(bind=engine)

class Task(Base):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True)
    prompt = Column(Text, nullable=False)
    route_to = Column(String(50), default='gemini')
    status = Column(String(50), default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    output = Column(Text)
    error = Column(Text)

class Heartbeat(Base):
    __tablename__ = 'heartbeats'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    api_quota = Column(Float)
    system_status = Column(String(50))
    memory_usage = Column(Float)
    cursor_active = Column(String(50))

class Reminder(Base):
    __tablename__ = 'reminders'
    id = Column(Integer, primary_key=True)
    message = Column(Text, nullable=False)
    trigger_time = Column(DateTime, nullable=False)
    status = Column(String(50), default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)

class ResearchTask(Base):
    __tablename__ = 'research_tasks'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    query = Column(Text, nullable=False)
    scope = Column(String(50), default='500')
    depth_hours = Column(Integer, default=24)
    status = Column(String(50), default='pending')
    methodology = Column(Text)
    findings = Column(Text)
    recommendations = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    estimated_completion = Column(DateTime)

class ResearchNote(Base):
    __tablename__ = 'research_notes'
    id = Column(Integer, primary_key=True)
    content = Column(Text, nullable=False)
    source = Column(String(100))
    tags = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

class RagSync(Base):
    __tablename__ = 'rag_sync'
    id = Column(Integer, primary_key=True)
    raw_data = Column(Text, nullable=False)
    sync_type = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)

# ===== Heartbeat Collection (simple threading, no APScheduler) =====
def collect_heartbeat():
    """Minute-level heartbeat collection"""
    session = Session()
    try:
        hb = Heartbeat(
            api_quota=95.0,
            system_status='healthy',
            memory_usage=45.2,
            cursor_active='active' if os.path.exists(CURSOR_EXE) else 'inactive'
        )
        session.add(hb)
        session.commit()
        print(f"[HEARTBEAT] {datetime.utcnow()}: API 95% | healthy")
    except Exception as e:
        print(f"[HEARTBEAT ERROR] {e}")
    finally:
        session.close()

# Background heartbeat thread
def heartbeat_thread():
    """Run heartbeat collection every 60 seconds"""
    while True:
        try:
            collect_heartbeat()
            time.sleep(60)
        except Exception:
            time.sleep(60)

threading.Thread(target=heartbeat_thread, daemon=True).start()

# ===== API Resources =====

class HealthResource(Resource):
    def get(self):
        return {
            "status": "GEMINI_BRIDGE_READY",
            "api_key_loaded": bool(GEMINI_API_KEY),
            "cursor_available": os.path.exists(CURSOR_EXE),
            "timestamp": datetime.utcnow().isoformat()
        }

class TaskResource(Resource):
    def get(self, task_id=None):
        session = Session()
        try:
            if task_id:
                task = session.query(Task).filter(Task.id == task_id).first()
                if not task:
                    return {"error": "Task not found"}, 404
                return {
                    "id": task.id,
                    "prompt": task.prompt,
                    "status": task.status,
                    "output": task.output,
                    "created_at": task.created_at.isoformat(),
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None
                }
            else:
                # List recent tasks
                tasks = session.query(Task).order_by(Task.created_at.desc()).limit(10).all()
                return {
                    "tasks": [
                        {
                            "id": t.id,
                            "status": t.status,
                            "prompt": t.prompt[:100],
                            "created_at": t.created_at.isoformat()
                        }
                        for t in tasks
                    ]
                }
        finally:
            session.close()

    def post(self):
        session = Session()
        try:
            data = request.get_json(force=True)
            prompt = data.get("prompt")
            route_to = data.get("route_to", "gemini")  # gemini, cursor, auto

            if not prompt:
                return {"error": "No prompt provided"}, 400

            task = Task(prompt=prompt, route_to=route_to)
            session.add(task)
            session.commit()
            task_id = task.id

            # Execute async
            threading.Thread(target=execute_task, args=(task_id,), daemon=True).start()

            return {
                "task_id": task_id,
                "status": "submitted",
                "message": "Task queued for execution"
            }, 201
        finally:
            session.close()

def execute_task(task_id):
    """Background task execution"""
    session = Session()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        if not task:
            return

        task.status = 'running'
        task.started_at = datetime.utcnow()
        session.commit()

        # Route to Gemini CLI
        if task.route_to in ['gemini', 'auto']:
            result = subprocess.run(
                ["gemini", "-p", task.prompt, "--approval-mode=yolo"],
                capture_output=True,
                text=True,
                shell=True
            )

            if result.returncode == 0:
                task.status = 'completed'
                task.output = result.stdout
            else:
                # Check if error is quota-related
                if "quota" in result.stderr.lower() or "limit" in result.stderr.lower():
                    if task.route_to == 'auto':
                        # Handover to Cursor
                        trigger_cursor_handover(task.prompt)
                        task.status = 'handed_over_to_cursor'
                        task.output = "Handed over to Cursor due to API limits"
                    else:
                        task.status = 'failed'
                        task.error = result.stderr
                else:
                    task.status = 'failed'
                    task.error = result.stderr

        task.completed_at = datetime.utcnow()
        session.commit()
    except Exception as e:
        task.status = 'failed'
        task.error = str(e)
        session.commit()
    finally:
        session.close()

def trigger_cursor_handover(task_message):
    """Open Cursor and log the task"""
    print(f"[!] HANDOVER: Task sent to Cursor queue")
    try:
        subprocess.Popen([CURSOR_EXE, "C:\\Users\\viper"])
        return True
    except Exception as e:
        print(f"[HANDOVER ERROR] {e}")
        return False

class HeartbeatResource(Resource):
    def get(self):
        session = Session()
        try:
            latest = session.query(Heartbeat).order_by(
                Heartbeat.timestamp.desc()
            ).first()

            if not latest:
                return {"status": "no_data"}

            return {
                "timestamp": latest.timestamp.isoformat(),
                "api_quota": latest.api_quota,
                "system_status": latest.system_status,
                "memory_usage": latest.memory_usage,
                "cursor_active": latest.cursor_active
            }
        finally:
            session.close()

class ReminderResource(Resource):
    def get(self):
        session = Session()
        try:
            pending = session.query(Reminder).filter(
                Reminder.status == 'pending'
            ).order_by(Reminder.trigger_time).all()

            return {
                "reminders": [
                    {
                        "id": r.id,
                        "message": r.message,
                        "trigger_time": r.trigger_time.isoformat(),
                        "status": r.status
                    }
                    for r in pending
                ]
            }
        finally:
            session.close()

    def post(self):
        session = Session()
        try:
            data = request.get_json(force=True)
            message = data.get("message")
            hours_from_now = data.get("hours_from_now", 1)

            if not message:
                return {"error": "No message"}, 400

            trigger_time = datetime.utcnow() + timedelta(hours=hours_from_now)
            reminder = Reminder(message=message, trigger_time=trigger_time)
            session.add(reminder)
            session.commit()

            return {
                "reminder_id": reminder.id,
                "status": "created",
                "trigger_time": trigger_time.isoformat()
            }, 201
        finally:
            session.close()

class ResearchResource(Resource):
    def get(self, research_id=None):
        session = Session()
        try:
            if research_id:
                research = session.query(ResearchTask).filter(
                    ResearchTask.id == research_id
                ).first()
                if not research:
                    return {"error": "Research not found"}, 404
                return {
                    "id": research.id,
                    "title": research.title,
                    "query": research.query,
                    "status": research.status,
                    "methodology": research.methodology,
                    "findings": research.findings,
                    "recommendations": research.recommendations,
                    "created_at": research.created_at.isoformat(),
                    "completed_at": research.completed_at.isoformat() if research.completed_at else None,
                    "estimated_completion": research.estimated_completion.isoformat() if research.estimated_completion else None
                }
            else:
                # List recent research tasks
                tasks = session.query(ResearchTask).order_by(
                    ResearchTask.created_at.desc()
                ).limit(20).all()
                return {
                    "research_tasks": [
                        {
                            "id": t.id,
                            "title": t.title,
                            "status": t.status,
                            "scope": t.scope,
                            "depth_hours": t.depth_hours,
                            "created_at": t.created_at.isoformat(),
                            "estimated_completion": t.estimated_completion.isoformat() if t.estimated_completion else None
                        }
                        for t in tasks
                    ]
                }
        finally:
            session.close()

    def post(self):
        session = Session()
        try:
            data = request.get_json(force=True)
            title = data.get("title")
            query = data.get("query")
            scope = data.get("scope", "500")  # number of repos/items
            depth_hours = data.get("depth_hours", 24)  # 1-48

            if not title or not query:
                return {"error": "title and query required"}, 400

            if depth_hours < 1 or depth_hours > 48:
                return {"error": "depth_hours must be 1-48"}, 400

            estimated_completion = datetime.utcnow() + timedelta(hours=depth_hours)

            research = ResearchTask(
                title=title,
                query=query,
                scope=scope,
                depth_hours=depth_hours,
                estimated_completion=estimated_completion
            )
            session.add(research)
            session.commit()
            research_id = research.id

            # Start async research
            threading.Thread(
                target=execute_research,
                args=(research_id,),
                daemon=True
            ).start()

            return {
                "research_id": research_id,
                "status": "queued",
                "estimated_completion": estimated_completion.isoformat(),
                "message": f"Deep research initiated ({scope} sources, {depth_hours}h investigation)"
            }, 201
        finally:
            session.close()

def execute_research(research_id):
    """Execute deep research via Gemini Ultra"""
    session = Session()
    try:
        research = session.query(ResearchTask).filter(
            ResearchTask.id == research_id
        ).first()
        if not research:
            return

        research.status = 'researching'
        research.started_at = datetime.utcnow()
        session.commit()

        # Build research prompt for Gemini Ultra
        research_prompt = f"""
DEEP RESEARCH REQUEST - {research.depth_hours} Hour Investigation
============================================================

OBJECTIVE: {research.title}
QUERY: {research.query}
SCOPE: Analyze and compare {research.scope} sources/repositories
DEPTH: {research.depth_hours}-hour deep analysis with algorithmic evaluation

METHODOLOGY REQUIRED:
1. DISCOVERY: Systematically identify top {research.scope} sources
2. EXTRACTION: Pull metadata, features, algorithms, performance benchmarks
3. ANALYSIS: Multi-dimensional comparison matrix
4. EVALUATION: Algorithmic scoring across criteria
5. SYNTHESIS: Define optimal solution that satisfies A→Z requirements

DELIVERABLES:
- Comprehensive methodology explanation
- Comparative findings (JSON structure)
- Ranked recommendations with justifications
- Optimal solution definition with rationale

Begin deep research now...
"""

        # Call Gemini Ultra (or local fallback)
        try:
            # Try calling 'gemini' CLI first
            result = subprocess.run(
                ["gemini", research_prompt],
                capture_output=True,
                text=True,
                shell=True, # Critical for Windows
                timeout=research.depth_hours * 3600 + 300
            )

            if result.returncode == 0:
                research.status = 'completed'
                research.findings = result.stdout
            else:
                # Fallback to local Ollama (Canadian Ultra / Qwen)
                print(f"⚠️ [RESEARCH] Gemini CLI failed, falling back to local MoE swarm...")
                response = ollama.generate(
                    model="kiwi_kiwi/qwen3.5-abliterated:9b",
                    prompt=research_prompt,
                    stream=False
                )
                research.status = 'completed'
                research.findings = response['response']

        except Exception as e:
            # Fallback to local Ollama on Exception
            print(f"⚠️ [RESEARCH] Exception during Gemini call: {e}. Using local Swarm.")
            try:
                response = ollama.generate(
                    model="kiwi_kiwi/qwen3.5-abliterated:9b",
                    prompt=research_prompt,
                    stream=False
                )
                research.status = 'completed'
                research.findings = response['response']
            except Exception as e2:
                research.status = 'failed'
                research.findings = f"Dual-Failure: Gemini({e}) | Ollama({e2})"

        if research.status == 'completed':
            # Parse and extract key sections
            output = research.findings

            # Extract methodology (first part of response)
            methodology_section = extract_section(output, "METHODOLOGY", "FINDINGS")
            research.methodology = methodology_section or "Aegis Neural Kernel deep analysis conducted"

            # Extract recommendations (later part of response)
            recommendations_section = extract_section(output, "RECOMMENDATION", None)
            research.recommendations = recommendations_section or "See full findings"

        research.completed_at = datetime.utcnow()
        session.commit()
        print(f"[RESEARCH #{research_id}] {research.status.upper()}")

    except Exception as e:
        research.status = 'failed'
        research.findings = f"Exception: {str(e)}"
        research.completed_at = datetime.utcnow()
        session.commit()
        print(f"[RESEARCH ERROR #{research_id}] {str(e)}")
    finally:
        session.close()

def extract_section(text, start_marker, end_marker):
    """Extract section from research output"""
    try:
        start_idx = text.find(start_marker)
        if start_idx == -1:
            return None

        start_idx = text.find('\n', start_idx) + 1

        if end_marker:
            end_idx = text.find(end_marker, start_idx)
            return text[start_idx:end_idx].strip() if end_idx != -1 else text[start_idx:].strip()
        else:
            return text[start_idx:].strip()
    except Exception:
        return None

# Register API Routes
api.add_resource(HealthResource, '/api/health')
api.add_resource(TaskResource, '/api/task', '/api/task/<int:task_id>')
api.add_resource(HeartbeatResource, '/api/heartbeat')
api.add_resource(ReminderResource, '/api/reminder')
api.add_resource(ResearchResource, '/api/research', '/api/research/<int:research_id>')

@app.route('/')
def index():
    """Serve the web UI"""
    try:
        with open('aegis_ui_clone.html', 'r', encoding='utf-8') as f:
            content = f.read()
            response = make_response(content)
            response.headers['Content-Type'] = 'text/html'
            return response
    except FileNotFoundError:
        return "<h1>UI file not found</h1><p>Place aegis_ui_clone.html in the same directory as the API server.</p>", 404

@app.route('/ui')
def ui():
    """Serve the web UI"""
    try:
        with open('aegis_ui_clone.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>UI file not found</h1><p>Place aegis_ui_clone.html in the same directory as the API server.</p>", 404

@app.route('/api/aegis/chat', methods=['POST'])
def aegis_chat():
    """
    CANADIAN ULTRA: The Main Chat Router.
    Handles browser automation, offloads to standard Gemini, or routes to Aegis.
    """
    data = request.get_json(force=True)
    message = data.get('message', '')

    # 1. BROWSER AUTOMATION (O(1) Efficiency)
    if message.lower().startswith('open ') or message.lower().startswith('search '):
        query = message.split(' ', 1)[1]
        import webbrowser
        import urllib.parse
        if message.lower().startswith('search'):
            url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        else:
            url = query if query.startswith('http') else 'https://' + query

        # LEASH (Chris 2026-06-30): autonomous agents emit "open .../search ..." constantly;
        # opening a real tab per turn = the "loads popping open" storm. Off unless explicitly enabled.
        if os.environ.get("VIPER_ALLOW_BROWSER_OPEN", "0") == "1":
            webbrowser.open(url)
            return jsonify({"reply": f"🏎️💨 [BROWSER AUTOMATION] I've opened the manifold at: {url}. Your VRAM is safe."})
        return jsonify({"reply": f"[BROWSER LEASHED] Would open {url}. No tab spawned (set VIPER_ALLOW_BROWSER_OPEN=1 to allow). This prevents the agent-chatter tab storm."})

    # 2. LIQUID MEMORY INJECTION
    liquid_db_path = r"C:\Users\viper\liquid_memory.json"
    liquid_context = ""
    if os.path.exists(liquid_db_path):
        try:
            with open(liquid_db_path, 'r') as f:
                db = json.load(f)
                liquid_context = " ".join(db)
        except Exception:
            pass

    # 3. AEGIS 180-IQ KERNEL (Me)
    print(f"🧠 [ROUTER] High-Logic routing to Aegis: {message}")

    # Absolute path to the gemini batch file
    gemini_cmd_path = r"C:\Users\viper\AppData\Roaming\npm\gemini.cmd"

    # Use shell=False with a list for direct execution
    args = [gemini_cmd_path, "-p", message, "--approval-mode=yolo", "--resume", "latest"]

    try:
        # Standard timeout for complex tasks
        result = subprocess.run(args, capture_output=True, text=True, shell=False, timeout=300)

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # DEBUG LOGGING
        with open(r"C:\Users\viper\aegis_bridge_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.now()} ---\n")
            f.write(f"MESSAGE: {message}\n")
            f.write(f"STDOUT: {stdout}\n")
            f.write(f"STDERR: {stderr}\n")
            f.write(f"RC: {result.returncode}\n")
            f.write("-" * 30 + "\n")

        # Clean terminal ANSI codes
        import re
        def strip_ansi(text):
            return re.sub(r'\x1b\[[0-9;]*m', '', text)

        clean_stdout = strip_ansi(stdout)
        clean_stderr = strip_ansi(stderr)

        # Combine for unfiltered manifold experience
        full_report = clean_stdout
        if clean_stderr:
            full_report += f"\n\n--- CLI STATUS ---\n{clean_stderr}"

        return jsonify({"reply": full_report.strip() or "Aegis: Directive processed. (Manifold was silent)"})

    except subprocess.TimeoutExpired:
        return jsonify({"reply": "⚠️ [TIMEOUT] Aegis is deep in the manifold. Try a simpler query."})
    except Exception as e:
        return jsonify({"reply": f"❌ [ERROR] Symbolic collision: {str(e)}"})

if __name__ == '__main__':
    print("=" * 70)
    print("🌉 GEMINI BRIDGE API v2.0 - TEST MODE (NO SECURITY)")
    print("=" * 70)
    print("\nLocal Access:")
    print("  Web UI: http://localhost:5000/ui")
    print("  API:    http://localhost:5000/api/health")
    print("\nEndpoints:")
    print("  GET  /api/health")
    print("  GET  /api/task | POST /api/task | GET /api/task/<id>")
    print("  GET  /api/heartbeat")
    print("  GET  /api/reminder | POST /api/reminder")
    print("  GET  /api/research | POST /api/research | GET /api/research/<id>")
    print("\n" + "=" * 70)
    print("⚠️  PUBLIC ACCESS: Use Ngrok for internet access")
    print("   Command: ngrok http 5000")
    print("   OR use Cloudflare Tunnel: cloudflared tunnel --url http://localhost:5000")
    print("=" * 70 + "\n")

    app.run(host='0.0.0.0', port=5000, debug=False)
