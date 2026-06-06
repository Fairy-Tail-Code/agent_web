import os

from Agents.server.data.main import mcp

if __name__ == '__main__':

    mcp.run(
        transport="streamable-http",
        host=os.getenv("DATA_MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("DATA_MCP_PORT", "8085")),
    )
