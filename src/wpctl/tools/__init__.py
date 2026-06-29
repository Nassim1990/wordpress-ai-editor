"""R0 read tools. Each is a thin async function over the AppContext; the MCP
layer in server.py adapts them to tool calls. Writes (R1/R2) register through
the Gate in later build steps."""
