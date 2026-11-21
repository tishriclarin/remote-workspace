"use strict";
const status = document.getElementById("status");
const details = document.getElementById("details");
document.getElementById("installer").addEventListener("click", () => {
  chrome.tabs.create({url:"https://github.com/tishriclarin/remote-workspace/actions/workflows/companion-build.yml"});
});
try {
  chrome.runtime.sendNativeMessage("com.remoteworkspace.companion", {action:"status"}, response => {
    if (chrome.runtime.lastError || !response || response.error) {
      status.textContent="Local companion not detected";
      details.textContent="Install a matching desktop build and register the extension ID using remoteworkspace register-chrome ID. Installation requires user approval.";
      return;
    }
    status.textContent="Companion detected: "+String(response.gateway_mode||"unknown")+" gateway";
    details.textContent="Version "+String(response.version||"?")+". Web ChatGPT requires a separate supported MCP connection.";
  });
} catch {
  status.textContent="Native messaging unavailable";
  details.textContent="This browser may not support native-host integration.";
}
