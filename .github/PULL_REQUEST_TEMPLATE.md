## Description
<!-- Provide a clear, concise summary of the changes introduced in this pull request. -->

## Type of Change
- [ ] 🐛 Bug fix (non-breaking change fixing an issue)
- [ ] ✨ New feature (non-breaking change adding functionality)
- [ ] ⚡ Performance optimization (improving speed, RAM, or disk usage)
- [ ] 🔒 Security hardening (resolving vulnerability or leak risk)
- [ ] 📚 Documentation update (expanding guides, runbooks, or specs)
- [ ] 🔧 Refactoring / Code cleanup

## Subsystems Affected
- [ ] FUSE Virtual Filesystem (`archivemount`)
- [ ] Telegram Inline ZIP Picker (`zip_selector.py`)
- [ ] TDLib Multi-Session Concurrency Pool
- [ ] Leech & Telegram Uploader (`telegram_uploader.py`)
- [ ] Google Drive & Rclone Integrations
- [ ] Direct Download Engines (aria2, qBit, Sabnzbd, JD2, yt-dlp)
- [ ] Docker & Deployment Configurations

## Verification & Testing
<!-- Describe the tests and verification steps you performed to confirm your changes. -->
- [ ] Code syntax validated with `python3 -m py_compile`
- [ ] Tested live task execution (Mirror / Leech / Extraction)
- [ ] Verified disk cleanup and unmount routines (`fusermount -uz`)
- [ ] Verified `.gitignore` and confirmed zero secrets/credentials committed

## Checklist
- [ ] My code adheres to the repository's coding standards.
- [ ] I have updated relevant documentation where applicable.
- [ ] No hardcoded passwords, tokens, API keys, or personal paths are present.
