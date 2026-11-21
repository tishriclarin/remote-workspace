"use strict";
(() => {
  const repository = "tishriclarin/ssh-workspace";
  const allowed = new Set([
    "README.md", "AGENTS.md", "docs/DEVICE_POLICY.md",
    "skills/remote-safety/SKILL.md", "skills/remote-workspace/SKILL.md",
    "skills/ssh-client/SKILL.md", "gateway/README.md"
  ]);
  const picker = document.getElementById("doc-file");
  const editor = document.getElementById("doc-editor");
  const status = document.getElementById("doc-status");
  const reload = document.getElementById("doc-reload");
  const download = document.getElementById("doc-download");
  const propose = document.getElementById("doc-propose");
  let loadedText = "";
  let currentPath = "";
  let controller;
  const source = (path) => "https://raw.githubusercontent.com/" + repository + "/main/" + path;
  function setButtons(ready) {
    download.disabled = !ready;
    propose.disabled = !ready;
  }
  async function load() {
    const path = picker.value;
    if (!allowed.has(path)) { status.textContent = "Document not allowed"; return; }
    if (controller) controller.abort();
    controller = new AbortController();
    currentPath = "";
    setButtons(false);
    editor.value = "";
    status.textContent = "Loading " + path + "…";
    try {
      const response = await fetch(source(path), {signal:controller.signal, cache:"no-store"});
      if (!response.ok) throw new Error("HTTP " + response.status);
      const text = await response.text();
      if (picker.value !== path) return;
      if (text.length > 512000) throw new Error("Document too large");
      loadedText = text;
      currentPath = path;
      editor.value = text;
      setButtons(true);
      status.textContent = "Loaded " + path + " · Edit below; changes are local until exported.";
    } catch (error) {
      if (error.name !== "AbortError") status.textContent = "Could not load document: " + error.message;
    }
  }
  function saveCopy() {
    if (!currentPath) return;
    const blob = new Blob([editor.value], {type:"text/markdown;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = currentPath.split("/").pop();
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status.textContent = "Edited copy saved locally. Repository and device configuration unchanged.";
  }
  function proposeChange() {
    if (!currentPath) return;
    // GitHub's editor handles authentication and commits; never place contents or secrets in a URL.
    const url = "https://github.com/" + repository + "/edit/main/" + currentPath;
    window.open(url, "_blank", "noopener,noreferrer");
    status.textContent = editor.value !== loadedText
      ? "GitHub editor opened. Copy your local edits into it to submit the change."
      : "GitHub editor opened for this document.";
  }
  picker.addEventListener("change", load);
  reload.addEventListener("click", load);
  download.addEventListener("click", saveCopy);
  propose.addEventListener("click", proposeChange);
  load();
})();
