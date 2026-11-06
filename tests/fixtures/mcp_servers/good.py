"""A well-behaved MCP server for `zyven verify` tests."""

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer(name="good-calc")


@server.tool(name="add", description="Add two integers and return their sum.",
             annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    server.run("stdio")
