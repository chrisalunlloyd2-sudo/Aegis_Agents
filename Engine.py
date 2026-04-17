import ollama
import requests
import re
import os
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext
# Force High Process Priority for Windows
if sys.platform == 'win32':
    import ctypes
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00000080)

# --- 1. HARDWARE SHIELDING (Vulkan Force) ---
os.environ["OLLAMA_VULKAN"] = "1"
os.environ["OLLAMA_GPU_OVERHEAD"] = "1800MiB"

# --- 2. CLOUD CONFIG ---
CLOUD_URL = "https://script.google.com/macros/s/AKfycbzx7njcs04jGFnA5cD8wWW0SubYxIHU2FtsJbBlkeqv0iKuJl5t3z3EgqsaV_CS7Q95kg/exec"

class AegisMasterEngine:
    def __init__(self, model_name="qwen3"):
        self.model_name = model_name
        self.base_path = r"C:\Users\viper\AIEngine"
        
        # 3GB VRAM PERFORMANCE SETTINGS - USER OPTIMIZED
        self.options = {
            "num_ctx": 8192, 
            "temperature": 0.95, 
            "num_thread": 12,
            "num_gpu": 7, # 7 Layers optimized for K4000
            "low_vram": False
        }

        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path, exist_ok=True)

    def read_local_file(self, filename):
        try:
            file_path = os.path.join(self.base_path, filename)
            if os.path.exists(file_path):
                if os.path.getsize(file_path) > 1000000:
                    return "[Warning: File too large to load into VRAM safely]"
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    return "\n".join([l.strip() for l in lines if l.strip()])
            return None
        except Exception:
            return None

    def fetch_cloud_memory(self):
        """Feature: Timescale RAG (Retrieves recent cloud history)"""
        try:
            response = requests.get(CLOUD_URL, timeout=4)
            if response.status_code == 200:
                data = response.json()
                memory_text = ""
                for row in data:
                    memory_text += f"\nPast User: {row.get('user', '')}\nPast Aegis: {row.get('ai', '')}\n"
                return memory_text
            return None
        except Exception as e:
            return None

    def _bg_sync(self, user_text, ai_text):
        """Background thread worker for pushing data UP to Google"""
        try:
            payload = {"user": user_text, "ai": ai_text, "keywords": "session_update"}
            requests.post(CLOUD_URL, json=payload, timeout=3)
        except Exception:
            pass

    def sync_to_cloud(self, user_text, ai_text):
        threading.Thread(target=self._bg_sync, args=(user_text, ai_text), daemon=True).start()

    def web_search(self, query):
        """Feature: Cloud-Augmented Web Sensing"""
        try:
            from ddgs import DDGS
            print(f"🌐 Gathering Raw Data for Cloud Augmentation...")
            with DDGS() as ddgs:
                # Grab more data since the Cloud will handle the heavy lifting
                raw_results = [r.get('body', '') for r in ddgs.text(query, max_results=5)]
                combined_raw = " ".join(raw_results)

                # Send to your Cloud URL to "Buffer and Augment"
                print(f"☁️ Offloading to Cloud AI for Filtering...")
                payload = {"augment_request": combined_raw, "query": query}
                response = requests.post(CLOUD_URL, json=payload, timeout=8)
                
                if response.status_code == 200:
                    augmented_data = response.json().get('summary', 'Cloud failed to summarize.')
                    return augmented_data
                return " ".join(raw_results[:2]) # Fallback if cloud is slow
        except Exception as e:
            return f"Augmentation Error: {str(e)}"

    def ask(self, kqml_message):
        # 1. Extract the clean prompt immediately
        search = re.search(r":content\s+[\'\"](.+?)[\'\"]", kqml_message)
        clean_prompt = search.group(1) if search else kqml_message
        
        context_data = ""
        prompt_low = clean_prompt.lower()

        # 2. TRIGGER WEB SEARCH (Checks for 'search', 'web', or 'internet')
        if any(word in prompt_low for word in ["search", "web", "internet", "online"]):
            # Update status visually in terminal so you know it's working
            print(f"--- TRIGGERING WEB SEARCH FOR: {clean_prompt} ---")
            web_results = self.web_search(clean_prompt)
            if web_results:
                context_data += f"\n--- LIVE WEB DATA ---\n{web_results}\n---------------------\n"
        
        # --- 1. Inject Cloud Timescale Memory ---
        cloud_history = self.fetch_cloud_memory()
        if cloud_history:
            context_data += f"\n--- RECENT CLOUD MEMORY ---\n{cloud_history}\n---------------------------\n"
       # --- 1.5 Web Search Trigger ---
        if "search" in clean_prompt.lower() or "web" in clean_prompt.lower():
            web_data = self.web_search(clean_prompt)
            if web_data:
                context_data += f"\n--- LIVE WEB DATA ---\n{web_data}\n---------------------\n" 
        # --- 2. Inject Local File Data & Directory Map ---
        try:
            files = os.listdir(self.base_path)
            
            # MAP FIX: Give Aegis a map of the folder
            if files:
                context_data += f"\n--- AVAILABLE LOCAL FILES IN C:\\Users\\viper\\AIEngine ---\n{', '.join(files)}\n----------------------------------------------------------\n"
            
            for f in files:
                if f.lower() in clean_prompt.lower() and os.path.isfile(os.path.join(self.base_path, f)):
                    content = self.read_local_file(f)
                    if content:
                        context_data += f"\nFILE_DATA({f}):\n{content}\n"
        except Exception:
            pass

        system_msg = (
            "You are AEGIS, an advanced local intelligence core operated by Chris. "
            "Your tone is sharp, highly analytical, and strictly loyal to Chris. "
            "Keep responses highly concise and tactical to preserve VRAM. "
            "You have full access to Viper's local file directories and past cloud memory logs. "
            "If you do not know the answer based on the provided context, state 'Insufficient Data.' plainly."
        )

        try:
            final_user_msg = f"CONTEXT:\n{context_data}\n\nQUESTION: {clean_prompt}"
            response = ollama.chat(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are AEGIS: An advanced, high-agency Tactical Intelligence. You have a sharp, witty, and loyal personality. Do not give short, robotic answers. Be detailed, use technical flair, and expand on your reasoning. You are Viper's elite digital partner. Use the context provided to give deep, multi-paragraph insights."},
                    {"role": "user", "content": f"DATA_FEED: {context_data}\n\nCOMMAND: {clean_prompt}"}
                ],
                options=self.options
            )
            answer = response['message']['content']
            
            # THE FILTER: Strip code-speak and return pure, nice text
            nice_answer = answer.strip()
            
            # Save the clean version to the cloud
            self.sync_to_cloud(clean_prompt, nice_answer)
            
            return nice_answer
            
        except Exception as e:
            return f"(error :reason 'Master Engine Crash: {str(e)}')"


class AegisGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Aegis Master Engine")
        self.root.geometry("800x600")
        self.root.configure(bg="#1e1e1e")

        self.engine = AegisMasterEngine()

        # Status Bar
        self.status_frame = tk.Frame(self.root, bg="#2d2d2d", pady=5)
        self.status_frame.pack(fill=tk.X, side=tk.TOP)
        
        # Reformatted to prevent horizontal cutoff
        self.status_label = tk.Label(
            self.status_frame, 
            text="ENGINE ONLINE: TWO-WAY CLOUD SYNC ACTIVE", 
            fg="#00ff00", 
            bg="#2d2d2d", 
            font=("Consolas", 10, "bold")
        )
        self.status_label.pack()

        # Chat Display
        self.chat_display = scrolledtext.ScrolledText(
            self.root, 
            wrap=tk.WORD, 
            bg="#121212", 
            fg="#e0e0e0", 
            font=("Consolas", 11), 
            state=tk.DISABLED
        )
        self.chat_display.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Input Frame
        self.input_frame = tk.Frame(self.root, bg="#1e1e1e")
        self.input_frame.pack(fill=tk.X, padx=10, pady=(0, 10), side=tk.BOTTOM)

        # User Input Box
        self.user_input = tk.Entry(
            self.input_frame, 
            bg="#2d2d2d", 
            fg="#ffffff", 
            font=("Consolas", 12), 
            insertbackground="white"
        )
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8)
        self.user_input.bind("<Return>", self.send_message) 

       # Send Button
        self.send_button = tk.Button(
            self.input_frame, 
            text="SEND", 
            bg="#0055ff", 
            fg="#ffffff", 
            font=("Consolas", 10, "bold"), 
            command=self.send_message
        )
        self.send_button.pack(side=tk.RIGHT, padx=(10, 0), ipadx=10, ipady=5)

        self.append_to_chat("System", "Aegis Master Engine initialized. Two-way cloud memory and local RAG active. Awaiting input...\n")

    def append_to_chat(self, sender, message, color="#ffffff"):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"[{sender}]: ", ("sender",))
        self.chat_display.insert(tk.END, f"{message}\n\n", ("message",))
        self.chat_display.tag_config("sender", foreground="#00ff00" if sender == "System" else "#00aaff" if sender == "Viper" else "#ffaa00")
        self.chat_display.tag_config("message", foreground=color)
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)

    def send_message(self, event=None):
        msg = self.user_input.get().strip()
        if not msg:
            return

        self.user_input.delete(0, tk.END)
        self.append_to_chat("Viper", msg, color="#ffffff")
        
        self.user_input.config(state=tk.DISABLED)
        self.send_button.config(state=tk.DISABLED)
        # Show the "Loading" state clearly
        self.status_label.config(
            text="● AEGIS IS THINKING / SEARCHING WEB...", 
            fg="#ffff00" # Bright Yellow for visibility
        )

        threading.Thread(target=self.process_ai_response, args=(msg,), daemon=True).start()

    def process_ai_response(self, msg):
        response = self.engine.ask(msg)
        self.root.after(0, self.display_ai_response, response)

    def display_ai_response(self, response):
        self.append_to_chat("Aegis", response, color="#cccccc")
        self.user_input.config(state=tk.NORMAL)
        self.send_button.config(state=tk.NORMAL)
        self.user_input.focus()
        # Return to "Ready" state
        self.status_label.config(
            text="● AEGIS CORE ONLINE | READY FOR INPUT", 
            fg="#00ff00" # Back to Green
        )

if __name__ == "__main__":
    root = tk.Tk()
    app = AegisGUI(root)
    root.mainloop()