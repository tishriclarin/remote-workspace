"use strict";
(async () => {
  const platformElement = document.getElementById("platform");
  const recommendation = document.getElementById("recommendation");
  const install = document.getElementById("install");
  const explanation = document.getElementById("explanation");
  const buildUrl = "https://github.com/tishriclarin/ssh-workspace/actions/workflows/companion-build.yml";
  const ua = navigator.userAgent || "";
  let os = "unknown", arch = "unknown";
  if (navigator.userAgentData && navigator.userAgentData.getHighEntropyValues) {
    try {
      const info = await navigator.userAgentData.getHighEntropyValues(["architecture","bitness","platform"]);
      const p = String(info.platform || "").toLowerCase();
      os = p.includes("windows")?"windows":p.includes("mac")?"macos":p.includes("android")?"android":p.includes("linux")?"linux":os;
      arch = info.architecture === "arm" ? "arm64" : info.architecture === "x86" ? (info.bitness === "64"?"x64":"x86") : arch;
    } catch { /* Fall back to browser user agent below. */ }
  }
  if (os === "unknown") {
    os = /android/i.test(ua)?"android":/iphone|ipad|ipod/i.test(ua)?"ios":/windows/i.test(ua)?"windows":/mac os/i.test(ua)?"macos":/linux/i.test(ua)?"linux":"unknown";
  }
  if (os === "ios" || /iphone|ipad|ipod/i.test(ua)) os = "ios";
  if (arch === "unknown") {
    arch = /aarch64|arm64/i.test(ua) ? "arm64" : /x86_64|x64|win64|amd64|intel mac/i.test(ua) ? "x64" : "unknown";
  }
  platformElement.textContent = os + " · " + arch;
  const supported = ["windows","macos","linux"].includes(os);
  if (supported) {
    recommendation.textContent = "Choose a matching native development build for this desktop. The GitHub workflow includes Windows x64, macOS Intel/Apple Silicon, and Linux x64/ARM64.";
    install.textContent = "View available desktop builds";
    install.disabled = false;
    explanation.textContent = "Build artifacts are unsigned and require your explicit approval. They are not production-ready installers.";
    install.addEventListener("click", () => window.open(buildUrl, "_blank", "noopener,noreferrer"));
  } else if (os === "android" || os === "ios") {
    recommendation.textContent = "A signed " + (os === "android" ? "Android" : "iOS") + " companion app has not been published yet.";
    install.textContent = "Mobile app not available";
    explanation.textContent = "Installing an unsupported desktop binary on your phone is not recommended.";
  } else {
    recommendation.textContent = "Platform could not be confidently identified.";
    install.textContent = "Review supported platforms";
    install.disabled = false;
    install.addEventListener("click", () => window.open(buildUrl, "_blank", "noopener,noreferrer"));
  }
})();
