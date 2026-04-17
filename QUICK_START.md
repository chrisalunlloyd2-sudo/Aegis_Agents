# AEGIS-DIMON Quick Start Guide

## 🚀 Getting Started in 60 Seconds

### Prerequisites
1. **Python 3.8+** installed
2. **Ollama** installed and running
3. **Gemini API Key** (optional - for cloud mode)

### Quick Launch (Recommended)
```bash
# Just run this - it handles everything!
AEGIS_Launch.bat
```

The launcher will:
- ✅ Request admin privileges (approve UAC prompt)
- ✅ Start Ollama with Gemma 2B
- ✅ Initialize timescale memory system
- ✅ Launch FastAPI backend
- ✅ Create Cloudflare tunnel
- ✅ Open browser to your public URL

### Manual Setup (Advanced)

#### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

#### Step 2: Configure Environment
1. Copy `.env.template` to `.env`:
   ```bash
   copy .env.template .env
   ```
2. Edit `.env` and add your Gemini API key (optional):
   ```
   GEMINI_API_KEY=your_actual_api_key_here
   ```

#### Step 3: Install Local Model
```bash
ollama pull gemma2:2b
```

#### Step 4: Start the Server
```bash
python -m uvicorn gemini_bridge_api_fast:app --host 0.0.0.0 --port 5005
```

## 🎯 Access Points

- **Web UI**: http://localhost:5005/ui
- **API Health**: http://localhost:5005/api/health
- **API Docs**: http://localhost:5005/docs

## 🧠 Usage Modes

### Local Mode (Gemma 2B)
```
/local your prompt here
```

### Cloud Mode (Gemini)
Just type your prompt normally - it will use Gemini API

### Research Mode
```
/research your research topic
```

## 📊 System Architecture

### Core Components:

1. **Engine.py** - Master process orchestrator
2. **gemini_bridge_api_fast.py** - FastAPI server with timescale memory
3. **DIMON_CORE_DISTILLED.py** - Neural manifold mapper
4. **timescale_memory.py** - Revolutionary file-based memory system
5. **aegis_ui_clone.html** - Web interface

### 🧠 NEW: Timescale Memory System

**Replaces traditional vector RAG with hierarchical time-series files:**

- ✅ **Boolean Logic Only** - No NLP overhead
- ✅ **5KB Max Per File** - 60 heartbeat files per hour
- ✅ **Indexed Search** - Fast lookups without vectors
- ✅ **Daily Secrets** - Secure API/variable storage
- ✅ **Weekly Summaries** - Auto-compressed to 1KB

**Memory Structure:**
```
C:/Users/viper/Aegis_Memory/
├── session_id/subject/date/hour/
│   └── timestamp_hb01.txt (5KB max)
├── secrets/secrets_2026-04-17.json
├── weekly_summaries/summary_2026-W16.txt
└── feelings/feelings_2026-W16.txt (1KB)
```

## 🔧 Troubleshooting

### UAC Prompt Appears
- **Normal behavior** - Ollama needs admin privileges
- Click "Yes" to allow elevated permissions
- Required for hardware access

### Ollama Not Starting
```bash
# Manually start with admin:
Run as Administrator: C:\Program Files\Ollama\ollama.exe serve
```

### Memory System Offline
```bash
# Check memory path
dir C:\Users\viper\Aegis_Memory
# System auto-creates on first run
```

### API 500 Errors
```bash
# Clear Python cache
Remove-Item -Recurse -Force __pycache__
# Restart server
```

### Database Locked
- Close any other instances of the application
- Delete `gemini_bridge.db-shm` and `gemini_bridge.db-wal` if needed

### Port Already in Use
```bash
# Change port in command:
python -m uvicorn gemini_bridge_api_fast:app --port 5006
```

### Cloudflare Tunnel Fails
```bash
# Check tunnel log
type C:\Users\viper\tunnel.log
# Restart AEGIS_Launch.bat
```

## 📝 Key Features

- ✅ Hybrid AI (Cloud Gemini + Local Gemma)
- ✅ Automatic failover on API limits
- ✅ **NEW: Timescale Memory System** (replaces vector RAG)
- ✅ Real-time streaming responses
- ✅ DIMON neural manifold mapping
- ✅ SQLite + WAL mode for persistence
- ✅ Chain-of-Thought reasoning
- ✅ Boolean logic compression
- ✅ Weekly auto-summaries
- ✅ Admin privileges for Ollama

## 🎓 Advanced Usage

### Custom Model Selection
```python
# In gemini_bridge_api_fast.py, modify:
CHOOSER_MODEL = "gemma2:2b"  # Change to your preferred model
```

### Database Configuration
```python
# In .env file:
DATABASE_URL=sqlite:///gemini_bridge.db
# Or use PostgreSQL/TimescaleDB:
DATABASE_URL=postgresql://user:pass@localhost:5432/aegis
```

## 📚 Documentation

- `README.md` - **Comprehensive system documentation**
- `DIAGNOSTIC_REPORT.md` - System diagnostics and fixes
- `AEGIS_MANIFOLD_BLUEPRINT.txt` - Architecture details
- `TOOL_CALLING_GUIDE.md` - Tool usage guide

## 🆘 Support

If you encounter issues:
1. Check `DIAGNOSTIC_REPORT.md` for known issues
2. Review `api.log` for error messages
3. Inspect memory files: `C:/Users/viper/Aegis_Memory`
4. Ensure Ollama is running: `ollama list`
5. Verify admin privileges were granted

## 🎯 Quick Commands

```bash
# Start system
AEGIS_Launch.bat

# Check memory status
python -c "from timescale_memory import memory; print(memory.base_path)"

# Search memories
python -c "from timescale_memory import memory; print(memory.search('keyword'))"

# Create weekly summary
python -c "from timescale_memory import memory; memory.create_weekly_summary()"

# Clear old memories (30+ days)
python -c "from timescale_memory import memory; memory.cleanup(days=30)"
```

---
**Made with 🇨🇦 by Viper** 🤖