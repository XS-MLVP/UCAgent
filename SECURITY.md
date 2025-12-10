# Security Policy

## Supported Versions
The `main` branch receives security updates on a best-effort basis. Older tags or archived branches are not actively maintained. If you rely on a specific release, track changes in `main` and apply patches as needed.

## Reporting a Vulnerability
- Please do **not** create a public GitHub issue for security concerns.
- Email the maintainers at `unitychip@bosc.ac.cn` with a detailed report, including:
  - Description of the vulnerability and potential impact.
  - Steps to reproduce or proof-of-concept code.
  - Any known mitigations or workarounds.
- You can also request a private security advisory through GitHub (Security → Advisories → Report a vulnerability) if you prefer to coordinate disclosure within the GitHub platform.

We aim to acknowledge reports within **3 business days** and keep you informed about triage progress and remediation timelines.

## Coordinated Disclosure
We value responsible disclosure. Please give us a reasonable window to investigate and release a fix before public disclosure. Once a fix is available, we will publish release notes or advisories describing the impact, mitigation steps, and credits (if you consent).

## Security Best Practices for Contributors
- Review the [Code of Conduct](CODE_OF_CONDUCT.md) and [Contributing Guide](CONTRIBUTING.md) before submitting changes.
- Avoid introducing dependencies or configuration that weaken security (e.g., hard-coded credentials, insecure defaults, excessive privileges).
- Run the existing tests (including security-focused checks if available) before opening a pull request.

Thanks for helping us keep UCAgent secure for everyone.
