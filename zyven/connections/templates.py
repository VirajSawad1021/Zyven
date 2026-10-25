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
    {"id": "notion", "label": "Notion", "kind": "stdio",
     "hint": "Official Notion MCP server, run with npx. Create an internal integration at notion.so/profile/integrations, "
             "give it only the capabilities you want, share the pages it may see with it, and paste its token.",
     "url": "", "command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"], "secrets": ["NOTION_TOKEN"]},
    {"id": "slack", "label": "Slack (bot token, community server)", "kind": "stdio",
     "hint": "A community server, not Slack's own: review its code before trusting it. Create a Slack app, add a bot with "
             "only the scopes you want (for example chat:write, channels:history), install it, and paste the xoxb- token. "
             "The bot only sees channels it was invited to.",
     "url": "", "command": "npx", "args": ["-y", "@ubie-oss/slack-mcp-server"], "secrets": ["SLACK_BOT_TOKEN"]},
    {"id": "filesystem", "label": "Folder access", "kind": "stdio",
     "hint": "Lets the agent read and write inside ONE folder. Replace the last argument with that folder.",
     "url": "", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/folder"],
     "secrets": []},
    {"id": "custom-stdio", "label": "Local command", "kind": "stdio",
     "hint": "Any program that speaks MCP over stdin/stdout. It runs on this machine with your permissions.",
     "url": "", "command": "", "args": [], "secrets": []},
    {"id": "notion-hosted", "label": "Notion (hosted by Notion)", "kind": "http", "oauth": True,
     "hint": "Notion's own hosted server, signed in through Notion. No token to paste.",
     "url": "https://mcp.notion.com/mcp", "command": "", "args": [], "secrets": []},
    {"id": "gmail", "label": "Gmail (Google hosted)", "kind": "http", "oauth": True,
     "hint": "Google's hosted Gmail server (preview) can read mail and create drafts, not send. Google does not register "
             "apps automatically: create a Google Cloud project, enable the Gmail API and the Gmail MCP API, make an OAuth "
             "client with redirect URI http://127.0.0.1:8765/oauth/callback (use your board's address), and paste its client id and secret below.",
     "url": "https://gmailmcp.googleapis.com/mcp/v1", "command": "", "args": [], "secrets": []},
    {"id": "google-docs", "label": "Google Docs (Google hosted)", "kind": "http", "oauth": True,
     "hint": "Google's hosted Docs server (preview). Google does not register apps automatically: in a Google Cloud project "
             "enable the Google Docs API and the Google Docs MCP API, make an OAuth client with redirect URI "
             "http://127.0.0.1:8765/oauth/callback (use your board's address), and paste its client id and secret below.",
     "url": "https://docsmcp.googleapis.com/mcp/v1", "command": "", "args": [], "secrets": []},
    {"id": "slack-hosted", "label": "Slack (hosted by Slack)", "kind": "http", "oauth": True,
     "hint": "Slack's own hosted server, signed in through Slack. If Slack asks for an app, paste its client id and secret below.",
     "url": "https://mcp.slack.com/mcp", "command": "", "args": [], "secrets": []},
]
