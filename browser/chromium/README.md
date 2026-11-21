# Browser companion detection (preview)

This optional Chromium extension only detects a local companion. It never issues SSH commands.

1. Download a build for your desktop operating system from the GitHub Actions artifacts after its checks pass (currently unsigned development artifacts).
2. Run the downloaded companion once with **remoteworkspace setup**.
3. Install the extension for testing from **chrome://extensions** using Load unpacked.
4. Copy the displayed 32-letter extension ID and run **remoteworkspace register-chrome EXTENSION_ID** with your installed native binary.
5. Reopen the popup to view the local gateway mode.

Browser extension installation and native software execution always require required OS/browser approval. Chrome's Native Messaging uses an explicit origin allowlist. This extension is *not* a web-ChatGPT MCP tunnel. Signed extension and native installer distribution are release prerequisites.
