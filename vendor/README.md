# Bundled offline runtime

This directory contains optional third-party runtime files so Windows x64 users and self-hosted runners can start without downloading Python packages or Mihomo first.

- `python/windows-amd64/python-3.12.10-runtime.zip` contains the official CPython 3.12.10 embeddable distribution plus the Python dependencies declared by this project.
- `mihomo/windows-amd64/mihomo.exe` is the official Mihomo Meta v1.19.29 Windows amd64 binary.

The subscription sources and network checks still require Internet access. The bundled files only remove the initial runtime and dependency downloads.

See the notice files in each component directory for versions, hashes, upstream sources, and licenses.
