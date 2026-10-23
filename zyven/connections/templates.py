"""Starter templates for the Connections page. A template only pre-fills the form; nothing is trusted or
enabled until the user tests the connection and reads the tool list."""

TEMPLATES = [
    {"id": "custom-http", "label": "Hosted MCP server (URL)", "kind": "http",
     "hint": "Paste the server's MCP URL. If it needs a key, add a header such as Authorization = Bearer ...",
     "url": "", "command": "", "args": [], "secrets": ["Authorization"]},
    {"id": "github", "label": "GitHub (all repository tools)", "kind": "stdio",
     "hint": "Runs the official GitHub MCP server with npx. Create a token at github.com/settings/tokens "
             "and give it only the scopes you want the agent to have.",
     "url": "", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
     "secrets": ["GITHUB_PERSONAL_ACCESS_TOKEN"]},
    {"id": "filesystem", "label": "Folder access", "kind": "stdio",
     "hint": "Lets the agent read and write inside ONE folder. Replace the last argument with that folder.",
     "url": "", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/folder"],
     "secrets": []},
    {"id": "custom-stdio", "label": "Local command", "kind": "stdio",
     "hint": "Any program that speaks MCP over stdin/stdout. It runs on this machine with your permissions.",
     "url": "", "command": "", "args": [], "secrets": []},
]
