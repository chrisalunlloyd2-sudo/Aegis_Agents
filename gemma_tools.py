"""
Tool Calling System for Gemma 2B
Enables Gemma to use tools through structured prompts
"""
import json
import os
import subprocess
from typing import Dict, List, Any, Callable

# Define available tools
TOOLS = {
    "create_file": {
        "description": "Create a new file with content",
        "parameters": {
            "path": "string - file path",
            "content": "string - file content"
        }
    },
    "read_file": {
        "description": "Read contents of a file",
        "parameters": {
            "path": "string - file path"
        }
    },
    "list_directory": {
        "description": "List files in a directory",
        "parameters": {
            "path": "string - directory path"
        }
    },
    "execute_command": {
        "description": "Execute a shell command",
        "parameters": {
            "command": "string - command to execute"
        }
    },
    "search_web": {
        "description": "Search the web for information",
        "parameters": {
            "query": "string - search query"
        }
    }
}

def create_file(path: str, content: str) -> str:
    """Create a file with content"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"✅ File created: {path}"
    except Exception as e:
        return f"❌ Error: {e}"

def read_file(path: str) -> str:
    """Read file contents"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"❌ Error: {e}"

def list_directory(path: str) -> str:
    """List directory contents"""
    try:
        files = os.listdir(path)
        return "\n".join(files)
    except Exception as e:
        return f"❌ Error: {e}"

def execute_command(command: str) -> str:
    """Execute shell command"""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return result.stdout if result.stdout else result.stderr
    except Exception as e:
        return f"❌ Error: {e}"

def search_web(query: str) -> str:
    """Search web (placeholder)"""
    return f"Web search for: {query} (implement with DuckDuckGo API)"

# Map tool names to functions
TOOL_FUNCTIONS: Dict[str, Callable] = {
    "create_file": create_file,
    "read_file": read_file,
    "list_directory": list_directory,
    "execute_command": execute_command,
    "search_web": search_web
}

def get_tools_prompt() -> str:
    """Generate prompt describing available tools"""
    tools_desc = "You have access to the following tools:\n\n"
    for name, info in TOOLS.items():
        tools_desc += f"**{name}**: {info['description']}\n"
        tools_desc += "Parameters:\n"
        for param, desc in info['parameters'].items():
            tools_desc += f"  - {param}: {desc}\n"
        tools_desc += "\n"
    
    tools_desc += """
To use a tool, respond with JSON in this format:
```json
{
  "tool": "tool_name",
  "parameters": {
    "param1": "value1",
    "param2": "value2"
  }
}
```

After using a tool, I will show you the result and you can continue or use another tool.
"""
    return tools_desc

def parse_tool_call(response: str) -> Dict[str, Any] | None:
    """Parse tool call from Gemma's response"""
    try:
        # Look for JSON in code blocks
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
        else:
            json_str = response.strip()
        
        return json.loads(json_str)
    except:
        return None

def execute_tool(tool_call: Dict[str, Any]) -> str:
    """Execute a tool call"""
    tool_name = tool_call.get("tool")
    parameters = tool_call.get("parameters", {})
    
    if tool_name not in TOOL_FUNCTIONS:
        return f"❌ Unknown tool: {tool_name}"
    
    try:
        func = TOOL_FUNCTIONS[tool_name]
        result = func(**parameters)
        return result
    except Exception as e:
        return f"❌ Tool execution error: {e}"

def create_system_prompt() -> str:
    """Create system prompt with tool instructions"""
    return f"""You are AEGIS, an AI assistant with access to tools.

{get_tools_prompt()}

When a user asks you to do something that requires a tool:
1. Identify which tool to use
2. Respond with the tool call in JSON format
3. Wait for the tool result
4. Continue helping the user

Always explain what you're doing before calling a tool.
"""

# Made with Bob
