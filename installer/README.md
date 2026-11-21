# Platform-aware setup preview

Open **setup.html** locally in a browser after extracting the repository to see automatic OS detection and an appropriate installation action. This is an early **development** interface:

- Windows, Linux and macOS: open the native build artifacts for manual review and approved installation.
- Android and iOS: state that a signed mobile app is not yet available.
- Default gateway mode: local/native. Central HTTPS gateway: configurable from the companion CLI.
- No code runs with system privileges from the browser. No download is performed until the user clicks.
- Chrome native-messaging extension source is in browser/chromium.

A true production one-click installer requires signed installer assets and a trusted distribution channel; GitHub workflow artifacts are unsigned and are not a substitute. A browser page cannot silently execute an OS installer.
