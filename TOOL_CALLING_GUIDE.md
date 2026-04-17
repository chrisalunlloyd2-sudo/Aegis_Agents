# AEGIS Tool Calling System

## Overview
The AEGIS system now includes a tool calling capability for the local Gemma 2B model. This allows Gemma to perform actions like creating files, reading files, executing commands, and more.

## How It Works

### 1. System Architecture
- **gemma_tools.py**: Core tool calling system with tool definitions and execution
- **gemini_bridge_api_fast.py**: FastAPI backend integrated with tool calling
- **System Prompt**: Gemma receives instructions about available tools in every request

### 2. Available Tools

#### create_file
Create a new file with content
```json
{
  "tool": "create_file",
  "parameters": {
    "path": "path/to/file.txt",
    "content": "File content here"
  }
}
```

#### read_file
Read contents of a file
```json
{
  "tool": "read_file",
  "parameters": {
    "path": "path/to/file.txt"
  }
}
```

#### list_directory
List files in a directory
```json
{
  "tool": "list_directory",
  "parameters": {
    "path": "path/to/directory"
  }
}
```

#### execute_command
Execute a shell command
```json
{
  "tool": "execute_command",
  "parameters": {
    "command": "dir"
  }
}
```

#### search_web
Search the web (placeholder for future implementation)
```json
{
  "tool": "search_web",
  "parameters": {
    "query": "search query"
  }
}
```

## Usage

### Via Web UI
1. Open the AEGIS web interface
2. Select "Local" kernel mode
3. Ask Gemma to perform an action, for example:
   - "Create a file called test.txt with content 'Hello World'"
   - "List all files in the current directory"
   - "Read the contents of AEGIS_MANIFOLD_BLUEPRINT.txt"

### How Gemma Responds
When you ask Gemma to do something that requires a tool:
1. Gemma analyzes your request
2. Gemma responds with a JSON tool call
3. The system executes the tool
4. Gemma receives the result and continues helping you

### Example Conversation
```
User: Create a file called hello.py with a simple hello world script

Gemma: I'll create that file for you.
```json
{
  "tool": "create_file",
  "parameters": {
    "path": "hello.py",
    "content": "print('Hello, World!')"
  }
}
```

System: ✅ File created: hello.py

Gemma: I've successfully created hello.py with a simple hello world script. The file will print "Hello, World!" when executed.
```

## Testing

### Quick Test
Run the test script on your desktop:
```
C:\Users\viper\Desktop\Test_AEGIS_Tools.bat
```

### Manual Test
1. Start the system with GeminiX.bat
2. Open the web UI
3. Switch to "Local" mode
4. Try these test prompts:
   - "Create a test file"
   - "List files in the current directory"
   - "Read a file"

## Troubleshooting

### Tool Not Executing
- Ensure you're in "Local" kernel mode
- Check that Gemma is responding with valid JSON
- Look for errors in the console/logs

### Gemma Not Using Tools
- The system prompt includes tool instructions
- Gemma should naturally use tools when appropriate
- If not, try being more explicit: "Use the create_file tool to..."

### Tool Execution Errors
- Check file paths are valid
- Ensure you have permissions
- Review error messages in the response

## Adding New Tools

To add a new tool:

1. Add tool definition to `TOOLS` dict in `gemma_tools.py`
2. Create the tool function
3. Add function to `TOOL_FUNCTIONS` mapping
4. Restart the system

Example:
```python
def my_new_tool(param1: str) -> str:
    """Do something cool"""
    try:
        # Your logic here
        return "Success!"
    except Exception as e:
        return f"❌ Error: {e}"

TOOL_FUNCTIONS["my_new_tool"] = my_new_tool
```

## Technical Details

### Prompt Engineering
The system uses prompt engineering to teach Gemma about tools. Each request includes:
- Tool descriptions
- Parameter specifications
- JSON format examples
- Usage instructions

### Tool Execution Flow
1. User sends message
2. System adds tool instructions to prompt
3. Gemma generates response
4. System parses response for JSON tool calls
5. If tool call found, execute it
6. Send result back to Gemma
7. Gemma generates follow-up response
8. Stream complete response to user

### Security Considerations
- Tool execution happens server-side
- File operations are restricted to accessible paths
- Command execution has timeout protection
- Consider adding permission checks for production use

## Future Enhancements
- [ ] Add more tools (web scraping, API calls, etc.)
- [ ] Implement tool permission system
- [ ] Add tool usage analytics
- [ ] Create tool chaining for complex tasks
- [ ] Add web search implementation
- [ ] Tool result caching