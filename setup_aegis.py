"""
AEGIS-DIMON Setup Script
Automated setup and verification for the AEGIS system
"""
import os
import sys
import subprocess
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

def print_header(text):
    print("\n" + "="*80)
    print(f"  {text}")
    print("="*80)

def print_status(message, status="INFO"):
    symbols = {"INFO": "[i]", "OK": "[+]", "WARN": "[!]", "ERROR": "[x]"}
    print(f"{symbols.get(status, '[i]')} {message}")

def check_python_version():
    print_header("Checking Python Version")
    version = sys.version_info
    if version.major == 3 and version.minor >= 8:
        print_status(f"Python {version.major}.{version.minor}.{version.micro} - OK", "OK")
        return True
    else:
        print_status(f"Python {version.major}.{version.minor} - Need 3.8+", "ERROR")
        return False

def check_ollama():
    print_header("Checking Ollama Installation")
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print_status("Ollama is installed and running", "OK")
            if "gemma2:2b" in result.stdout:
                print_status("Gemma 2B model found", "OK")
                return True
            else:
                print_status("Gemma 2B model not found", "WARN")
                print_status("Run: ollama pull gemma2:2b", "INFO")
                return False
        return False
    except FileNotFoundError:
        print_status("Ollama not installed", "ERROR")
        print_status("Install from: https://ollama.ai", "INFO")
        return False
    except Exception as e:
        print_status(f"Error checking Ollama: {e}", "ERROR")
        return False

def check_env_file():
    print_header("Checking Environment Configuration")
    if not Path(".env").exists():
        print_status(".env file not found", "WARN")
        if Path(".env.template").exists():
            print_status("Creating .env from template...", "INFO")
            try:
                with open(".env.template", "r") as template:
                    content = template.read()
                with open(".env", "w") as env_file:
                    env_file.write(content)
                print_status(".env file created - Please add your API key", "OK")
            except Exception as e:
                print_status(f"Error creating .env: {e}", "ERROR")
        return False
    else:
        print_status(".env file exists", "OK")
        return True

def install_requirements():
    print_header("Installing Python Requirements")
    try:
        print_status("Installing packages from requirements.txt...", "INFO")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print_status("All packages installed successfully", "OK")
            return True
        else:
            print_status("Some packages failed to install", "WARN")
            print(result.stderr)
            return False
    except Exception as e:
        print_status(f"Error installing requirements: {e}", "ERROR")
        return False

def check_database():
    print_header("Checking Database")
    db_path = Path("gemini_bridge.db")
    if db_path.exists():
        print_status(f"Database found: {db_path}", "OK")
        return True
    else:
        print_status("Database will be created on first run", "INFO")
        return True

def create_consistency_db():
    print_header("Setting up Consistency Database")
    import sqlite3
    consistency_db = Path.home() / "consistency.db"
    try:
        conn = sqlite3.connect(str(consistency_db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS global_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
        print_status(f"Consistency DB ready: {consistency_db}", "OK")
        return True
    except Exception as e:
        print_status(f"Error creating consistency DB: {e}", "ERROR")
        return False

def main():
    print_header("AEGIS-DIMON SYSTEM SETUP")
    
    results = {
        "Python Version": check_python_version(),
        "Ollama": check_ollama(),
        "Environment": check_env_file(),
        "Requirements": install_requirements(),
        "Database": check_database(),
        "Consistency DB": create_consistency_db()
    }
    
    print_header("SETUP SUMMARY")
    for check, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {check}")
    
    if all(results.values()):
        print_header("SETUP COMPLETE")
        print_status("System is ready to use!", "OK")
        print_status("Next steps:", "INFO")
        print_status("1. Add your GEMINI_API_KEY to .env file", "INFO")
        print_status("2. Run: python test_system.py", "INFO")
        print_status("3. Start server: python -m uvicorn gemini_bridge_api_fast:app --port 5005", "INFO")
    else:
        print_header("SETUP INCOMPLETE")
        print_status("Please resolve the failed checks above", "WARN")
    
    return 0 if all(results.values()) else 1

if __name__ == "__main__":
    sys.exit(main())

# Made with Bob
