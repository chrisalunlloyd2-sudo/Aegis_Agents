from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import subprocess
import json
import asyncio
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from pydantic import BaseModel
from io import BytesIO
import pyautogui
from dotenv import load_dotenv
from functools import lru_cache

import sys
from pathlib import Path

# Add current directory to path for local module imports
sys.path.append(str(Path(__file__).parent))

# Moltbook v3.8 Core
from DIMON_CORE_DISTILLED import DIMONCore
from aegis_dspy import initialize_dspy
from gemma_tools import create_system_prompt, parse_tool_call, execute_tool
dimon = DIMONCore()
optimizer = None # Lazy load DSPy

# Database & Timescale Memory
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from timescale_memory import memory as timescale_memory

load_dotenv()

# ===== CONFIG =====
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CURSOR_EXE = r"C:\Users\viper\AppData\Local\Programs\cursor\Cursor.exe"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///gemini_bridge.db")
CONSISTENCY_DB = r"C:\Users\viper\consistency.db"
CHOOSER_MODEL = "gemma2:2b" # Exclusive Gemma 2B Kernel

# ===== FastAPI Setup =====
app = FastAPI(title="Aegis-DIMON Bridge v3.8.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Database Setup =====
from sqlalchemy import event
Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class NeuralManifold(Base):
    __tablename__ = 'neural_manifolds'
    id = Column(Integer, primary_key=True)
    source_origin = Column(String(255))
    ast_nodes = Column(Integer)
    structural_depth = Column(Integer)
    canonical_coords = Column(Text)
    operator_signature = Column(String(100))
    timestamp = Column(DateTime, default=datetime.utcnow)

class Task(Base):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True)
    prompt = Column(Text)
    result = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

class Conversation(Base):
    __tablename__ = 'conversations'
    id = Column(Integer, primary_key=True)
    session_id = Column(String(100))
    role = Column(String(20)) # user, assistant
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

class Feedback(Base):
    __tablename__ = 'feedback'
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer) # Linked to conversation ID
    score = Column(Integer) # 1 for like, -1 for dislike
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ===== Global Systems =====
# Timescale Memory System (replaces RAG)
# rag_system = EnterpriseRAGSystem()  # DEPRECATED - using timescale_memory instead

# ===== State =====
kernel_state = {
    "local_fallback_active": False,
    "fallback_until": datetime.now(),
    "last_error": None,
    "mode": "auto" # auto, cloud, local
}
red_dot_state = {"active": False, "x": 0, "y": 0, "last_seen": None}
global_config = {"kernel_mode": "auto"}
chat_memory = {} # {session_id: [messages]}

def get_memory_status():
    """Check timescale memory system status"""
    try:
        if timescale_memory.base_path.exists():
            return "ACTIVE"
        return "INITIALIZING"
    except Exception:
        return "OFFLINE"

def sync_state(key, value):
    """Persists global state to consistency.db"""
    try:
        conn = sqlite3.connect(CONSISTENCY_DB)
        conn.execute("INSERT OR REPLACE INTO global_state (key, value, last_updated) VALUES (?, ?, CURRENT_TIMESTAMP)", (key, str(value)))
        conn.commit()
        conn.close()
    except: pass

# ===== Models =====
class ChatMessage(BaseModel):
    message: str
    mode: Optional[str] = "auto"
    retry: Optional[bool] = False

class SignalData(BaseModel):
    signal: str
    x: Optional[int] = 0
    y: Optional[int] = 0

class FeedbackData(BaseModel):
    message_id: int
    score: int

import ollama

# --- Background Task Logic ---
async def perform_deep_research(objective: str):
    print(f"[DEEP-RESEARCH] Starting background scan for: {objective}")
    try:
        # Search timescale memory
        results = timescale_memory.search(objective, time_range="last_week")
        print(f"[DEEP-RESEARCH] Found {len(results)} relevant memory blocks.")
        report = f"# [REPORT] DEEP RESEARCH: {objective}\n\n"
        for file_path, content in results:
            report += f"## Source: {file_path}\n{content[:300]}...\n\n"

        report_path = f"C:/Users/viper/RESEARCH_REPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"✅ [DEEP-RESEARCH] Report locked: {report_path}")
    except Exception as e:
        print(f"[DEEP-RESEARCH] Error: {e}")

async def agent_chooser(prompt: str):
    """Always route to gemma2:2b as per user requirement - single model system."""
    return "gemma2:2b"

# ===== ROUTES =====

@app.get("/")
@app.get("/ui")
async def get_ui():
    ui_path = os.path.join(os.path.dirname(__file__), 'aegis_ui_clone.html')
    if os.path.exists(ui_path):
        return FileResponse(ui_path, media_type='text/html')
    return HTMLResponse(content="<h1>UI file not found</h1>", status_code=404)

@app.get("/api/health")
async def health():
    return {
        "status": "MOLTBOOK_v3.8.1_ACTIVE",
        "engine": "FASTAPI_UVIVORN",
        "kernel": "LOCAL" if kernel_state["local_fallback_active"] else "CLOUD",
        "mode": global_config["kernel_mode"],
        "memory_status": get_memory_status(),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/api/feedback")
async def post_feedback(data: FeedbackData):
    session = SessionLocal()
    try:
        new_fb = Feedback(message_id=data.message_id, score=data.score)
        session.add(new_fb)
        session.commit()

        # If score is positive, catalog it for learning
        if data.score > 0:
            print(f"🌟 [LEARNING] Positive feedback for message {data.message_id}. Cataloged.")
            # Future: Copy message to learning collection in Qdrant

        return {"status": "recorded"}
    finally:
        session.close()

@app.get("/api/signal/status")
async def get_signal_status():
    if red_dot_state["active"] and red_dot_state["last_seen"]:
        last_seen_dt = datetime.fromisoformat(red_dot_state["last_seen"])
        if datetime.now() - last_seen_dt > timedelta(seconds=15):
            red_dot_state["active"] = False
    return red_dot_state

@app.post("/api/signal")
async def receive_signal(data: SignalData):
    red_dot_state.update({
        "active": True,
        "x": data.x,
        "y": data.y,
        "last_seen": datetime.now().isoformat()
    })
    return {"status": "ok"}

@app.delete("/api/conversation/local")
async def delete_conversation():
    session = SessionLocal()
    try:
        session.query(Conversation).delete()
        session.commit()
        chat_memory.clear()
        return {"status": "cleared"}
    finally:
        session.close()

@app.post("/api/aegis/chat")
async def aegis_chat(data: ChatMessage, background_tasks: BackgroundTasks, request: Request):
    global optimizer, chat_memory
    message = data.message
    requested_mode = data.mode or global_config["kernel_mode"]
    session_id = request.client.host

    if session_id not in chat_memory: chat_memory[session_id] = []
    sync_state(f"last_message_{session_id}", message)

    # 🛡️ MANUAL MODEL SELECTOR / LOCAL MODE
    if message.lower().startswith('/local') or requested_mode == "local" or (kernel_state["local_fallback_active"] and datetime.now() < kernel_state["fallback_until"]):
        target_model = None
        prompt = message
        if message.lower().startswith('/local'):
            parts = message.split(' ', 2)
            if len(parts) > 2:
                target_model = parts[1]
                prompt = parts[2]
            elif len(parts) == 2:
                prompt = parts[1]
            else:
                prompt = message

        # Determine model
        if not target_model:
            target_model = await agent_chooser(prompt)

        print(f"🧠 [STREAM-INIT] Routing to {target_model}...")

        async def event_generator():
            # Chain of Thought Reasoning
            cot_thoughts = f"Engaging local hardware ({target_model}). Initiating Chain of Thought... Mapping context... Analyzing objective..."
            yield json.dumps({"thoughts": cot_thoughts}) + "\n"

            # Context Retrieval from Timescale Memory
            context_text = ""
            try:
                # Get recent context for this session
                context = timescale_memory.get_context(session_id, "chat", max_files=5)
                if context:
                    context_text = f"\nRECENT CONTEXT:\n{context[:500]}"
            except Exception as e:
                print(f"❌ Memory retrieval error: {e}")

            # Store current message in timescale memory
            try:
                timescale_memory.store(session_id, "chat", prompt)
            except Exception as e:
                print(f"❌ Memory storage error: {e}")

            history = chat_memory.get(session_id, [])
            # Add tool calling instructions to system prompt
            system_prompt = create_system_prompt()
            full_messages = [{'role': 'system', 'content': f'{system_prompt}\n\n{context_text}'}] + history + [{'role': 'user', 'content': prompt}]

            full_reply = ""
            try:
                def call_stream():
                    # Increased max tokens and set temperature
                    return ollama.chat(model=target_model, messages=full_messages, stream=True, options={
                        "num_ctx": 4096,
                        "temperature": 0.6,
                        "num_predict": 4096
                    })

                response_gen = await asyncio.to_thread(call_stream)
                for chunk in response_gen:
                    content = chunk['message']['content']
                    full_reply += content
                    yield json.dumps({"reply_chunk": content}) + "\n"

                # Check if response contains a tool call
                tool_call = parse_tool_call(full_reply)
                if tool_call:
                    yield json.dumps({"thoughts": f"Executing tool: {tool_call.get('tool')}..."}) + "\n"
                    tool_result = execute_tool(tool_call)
                    yield json.dumps({"reply_chunk": f"\n\n**Tool Result:**\n{tool_result}\n\n"}) + "\n"

                    # Add tool result to context and get follow-up response
                    tool_context = f"Tool '{tool_call.get('tool')}' executed. Result: {tool_result}\n\nPlease continue helping the user based on this result."
                    follow_up_messages = full_messages + [
                        {'role': 'assistant', 'content': full_reply},
                        {'role': 'user', 'content': tool_context}
                    ]

                    follow_up_gen = await asyncio.to_thread(lambda: ollama.chat(
                        model=target_model,
                        messages=follow_up_messages,
                        stream=True,
                        options={"num_ctx": 4096, "temperature": 0.6, "num_predict": 2048}
                    ))

                    for chunk in follow_up_gen:
                        content = chunk['message']['content']
                        full_reply += content
                        yield json.dumps({"reply_chunk": content}) + "\n"

                # Update Memory
                chat_memory[session_id].append({"role": "user", "content": prompt})
                chat_memory[session_id].append({"role": "assistant", "content": full_reply})
                chat_memory[session_id] = chat_memory[session_id][-10:]

                # Persist to DB
                db_session = SessionLocal()
                try:
                    db_session.add(Conversation(session_id=session_id, role="user", content=prompt))
                    db_session.add(Conversation(session_id=session_id, role="assistant", content=full_reply))
                    db_session.commit()
                finally:
                    db_session.close()

            except Exception as e:
                yield json.dumps({"error": str(e)}) + "\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # 0. DEEP RESEARCH
    if message.lower().startswith('/research'):
        objective = message[9:].strip()
        background_tasks.add_task(perform_deep_research, objective)
        return {"reply": f"Research manifold active. Scouring: {objective}", "thoughts": "VRAM partitioned."}

    # 1. CLOUD EXECUTION
    gemini_cmd_path = r"C:\Users\viper\AppData\Roaming\npm\gemini.cmd"
    try:
        def run_cli():
            return subprocess.run([gemini_cmd_path, "-p", message, "--approval-mode=yolo", "--resume", "latest"], capture_output=True, text=True, shell=False, timeout=600)
        result = await asyncio.to_thread(run_cli)

        if "quota exceeded" in result.stdout.lower() or "429" in result.stderr:
            kernel_state.update({"local_fallback_active": True, "fallback_until": datetime.now() + timedelta(minutes=15)})
            return await aegis_chat(data, background_tasks, request)

        def strip_ansi(text): return re.sub(r'\x1b\[[0-9;]*m', '', text)
        clean_res = strip_ansi(result.stdout).strip()
        chat_memory[session_id].append({"role": "user", "content": message})
        chat_memory[session_id].append({"role": "assistant", "content": clean_res})
        chat_memory[session_id] = chat_memory[session_id][-10:]

        return {"reply": f"[CLOUD] {clean_res}", "thoughts": "Teacher manifold verified."}
    except Exception:
        return await aegis_chat(data, background_tasks, request)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5005)
