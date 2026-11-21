"use strict";
(async () => {
  const platformElement = document.getElementById("platform");
  const recommendation = document.getElementById("recommendation");
  const install = document.getElementById("install");
  const explanation = document.getElementById("explanation");
  const buildUrl = "https://github.com/tishriclarin/remote-workspace/actions/workflows/companion-build.yml";
  const ua = navigator.userAgent || "";
  const detect = (text) => /iphone|ipad|ipod/i.test(text) ? "ios" : /android/i.test(text) ? "android" : /windows/i.test(text) ? "windows" : /macintosh|mac os x/i.test(text) ? "macos" : /linux/i.test(text) ? "linux" : "unknown";
  let os = detect(ua), arch = "unknown";
  if (navigator.userAgentData?.getHighEntropyValues) {
    try {
      const info = await navigator.userAgentData.getHighEntropyValues(["architecture", "bitness", "platform"]);
      const detected = detect(String(info.platform || ""));
      if (detected !== "unknown" && os !== "ios" && os !== "android") os = detected;
      if (info.architecture === "arm") arch = info.bitness === "64" ? "arm64" : "arm";
      if (info.architecture === "x86") arch = info.bitness === "64" ? "x64" : "x86";
    } catch { /* UA remains a fallback. */ }
  }
  if (arch === "unknown") {
    arch = /aarch64|arm64/i.test(ua) ? "arm64" : /x86_64|x64|win64|amd64/i.test(ua) ? "x64" : "unknown";
  }
  // Browsers frequently hide CPU architecture, especially on Android and iOS.
  // Never guess an executable architecture when that signal is absent.
  const targets = {
    windows: {x64: "windows-x64"},
    macos: {x64: "macos-intel", arm64: "macos-arm64"},
    linux: {x64: "linux-x64", arm64: "linux-arm64"}
  };
  const label = targets[os]?.[arch];
  platformElement.textContent = os + " · " + arch;
  install.disabled = true;
  if (label) {
    recommendation.textContent = "Matching native desktop build: remote-workspace-desktop-v0.7.0-" + label + ".zip";
    install.textContent = "Review matching build";
    install.disabled = false;
    explanation.textContent = "Unsigned development build. Confirm the matching artifact, checksum and OS approval before installing. This page cannot execute local installers.";
  } else if (targets[os]) {
    recommendation.textContent = "Desktop OS detected; architecture could not be verified. Select your CPU architecture on the build page.";
    install.textContent = "Review desktop builds";
    install.disabled = false;
    explanation.textContent = "Do not install a binary for an unverified CPU architecture.";
  } else if (os === "android" || os === "ios") {
    recommendation.textContent = os === "android"
      ? "Android companion: no verified APK or Android-native MCP integration is available yet."
      : "iOS companion: no verified signed app or iOS-native MCP integration is available yet.";
    install.textContent = "Mobile companion unavailable";
    explanation.textContent = "Desktop ZIP and Linux ARM64 binaries are not mobile apps. An OS-specific companion and approved ChatGPT connection are required.";
  } else {
    recommendation.textContent = "OS could not be identified. Review available desktop builds manually.";
    install.textContent = "Review build targets";
    install.disabled = false;
    explanation.textContent = "Only verified OS/CPU combinations may be installed.";
  }
  if (!install.disabled) install.addEventListener("click", () => window.open(buildUrl, "_blank", "noopener,noreferrer"));
})();
