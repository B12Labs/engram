# Contributing to Engram

Thanks for your interest in contributing to Engram! This project aims to make AI agent memory portable, lightweight, and privacy-preserving.

## Getting Started

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Run tests (`pytest`)
5. Commit your changes (`git commit -m 'Add your feature'`)
6. Push to the branch (`git push origin feature/your-feature`)
7. Open a Pull Request

## Development Setup

```bash
git clone https://github.com/B12Labs/engram.git
cd engram
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -e ".[dev]"
```

## Areas We Need Help

- **Storage backends** — additional cloud storage adapters (GCS, Azure Blob, MinIO)
- **Data connectors** — ingest from more sources (Notion, Google Drive, Obsidian)
- **Language SDKs** — JavaScript/TypeScript, Rust, Go clients
- **Benchmarks** — performance comparisons across different hardware
- **Documentation** — tutorials, examples, integration guides

## Code Style

- Python: follow PEP 8, type hints required
- Rust: follow `rustfmt` defaults
- Tests: required for all new features

## Reporting Issues

- Use GitHub Issues for bugs and feature requests
- Include reproduction steps and environment details
- Label appropriately (bug, enhancement, question)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
