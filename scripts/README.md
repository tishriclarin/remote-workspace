# Native plugin distribution

Supported ChatGPT desktop local execution uses the existing ChatGPT session and host-managed MCP tool routing. No extra login, API key, tunnel or central SSH gateway is required for that local path. Ordinary ChatGPT browser/mobile sessions cannot automatically expose the same native executor.

A desktop CI build produces a platform-specific ZIP that contains the native Rust SSH engine, local stdio MCP configuration, a plugin manifest and a read-only skill. It does not require Python or an external SSH client on the recipient machine.

This is an **unsigned development package**, not a signed installer. The OS and browser must approve installation and execution. The desktop-only plugin publishing path requires OpenAI approval for local MCP submissions.

Example build:

    python scripts/build_desktop_plugin.py --binary companion/target/release/remoteworkspace --target x86_64-unknown-linux-gnu --version 0.7.0 --output companion/dist

Test:

    python -m unittest discover -s scripts/tests -v

Hosted ChatGPT uses a separate supported secure tunnel or remote MCP endpoint. The desktop bundle targets local threads.
