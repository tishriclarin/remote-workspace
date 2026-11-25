# Native companion distribution

Rust is the sole supported application implementation (see [AGENTS.md](../AGENTS.md)). Build and test the native companion from the repository root:

```sh
cargo test --manifest-path companion/Cargo.toml
cargo build --release --manifest-path companion/Cargo.toml
```

The executable is `remoteworkspace` (`remoteworkspace.exe` on Windows). The desktop CI stages the native executable and a SHA-256 checksum before attempting legacy packaging. The Python packaging scripts and regression tests in this directory are migration debt, not a supported distribution pipeline. Do not restore the legacy Python server or launcher.

Desktop packaging remains unverified: [desktop CI run 45266421265](https://github.com/tishriclarin/remote-workspace/actions/runs/45266421265) failed. Native compilation alone does not establish plugin installation or ChatGPT integration. The [Android ARM64 build](https://github.com/tishriclarin/remote-workspace/actions/runs/45302508790) passed, but is not a real-device installation test.

The intended integration uses host-managed MCP invocation without a separate OpenAI model API or token. Browser and mobile local execution must be verified through supported platform interfaces. Unsigned CI artifacts are for review, not signed installers or published releases.
