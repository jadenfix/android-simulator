# Security

- Prefer the `play` profile for ordinary apps. It is not rooted.
- Direct APK downloads require HTTPS unless `--allow-http` is explicitly used.
- Supply `--sha256` for APK URLs whenever the publisher provides a digest.
- Do not install APKs from unknown mirrors. A virtual device limits some host
  impact but does not make untrusted applications safe.
- This project does not implement device-identity spoofing, Play Integrity
  bypasses, certificate-pinning bypasses, or account automation.

Report repository vulnerabilities privately through GitHub Security Advisories.
