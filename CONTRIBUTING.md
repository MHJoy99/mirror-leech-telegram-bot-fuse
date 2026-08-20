# Contributing to mirror-leech-telegram-bot-fuse

Thank you for your interest in contributing to **mirror-leech-telegram-bot-fuse**! We welcome contributions, bug reports, and feature suggestions from the open-source community.

---

## 🛠️ Code of Conduct

By participating in this project, you agree to maintain a respectful, inclusive, and professional environment for all contributors.

---

## 🚀 How to Contribute

### 1. Reporting Bugs
- Check existing issues in the GitHub issue tracker before opening a new bug report.
- Provide a clear, reproducible description with system logs (sanitizing tokens, passwords, and personal credentials).
- Specify your runtime environment (OS distribution, Docker version, kernel FUSE version).

### 2. Suggesting Enhancements
- Open a Feature Request issue describing the proposed functionality and motivation.
- Highlight the expected benefits (e.g. storage efficiency, new direct link generators, concurrency improvements).

### 3. Pull Requests (PRs)
1. Fork the repository on GitHub.
2. Create a dedicated feature branch (`git checkout -b feat/your-feature-name`).
3. Follow the repository's coding style (PEP 8, clean AsyncIO patterns, strict error boundaries).
4. Run syntax and compilation checks before submitting:
   ```bash
   python3 -m py_compile bot/helper/ext_utils/files_utils.py
   ```
5. Ensure `.gitignore` is respected and no secrets or local configurations are committed.
6. Submit your Pull Request with a clear description of changes.

---

## 🔒 Security Vulnerabilities

If you discover a security vulnerability, please do not disclose it publicly on GitHub issues. Refer to [SECURITY.md](SECURITY.md) for instructions on confidential reporting.
