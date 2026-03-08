# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| 0.1.x   | :x:                |

## Reporting a Vulnerability

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, email **charleskithika@gmail.com** with the following details:

- Description of the vulnerability
- Steps to reproduce the issue
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment:** Within 48 hours of your report
- **Initial assessment:** Within 1 week
- **Fix or mitigation:** Depending on severity, typically within 2 weeks

We will keep you informed throughout the process and credit you in the fix (unless you prefer to remain anonymous).

## Demo-Mode Enforcement

Joe AI enforces **demo/paper trading mode by default** to prevent accidental live trades. Key safeguards include:

- All broker connections default to demo/paper mode unless explicitly overridden
- Capital.com integration uses the demo API endpoint by default
- IBKR connections target the paper trading port (7497) by default
- Environment variables must be explicitly set to enable live trading
- The pipeline includes pre-execution checks to confirm trading mode

If you discover a way to bypass demo-mode enforcement unintentionally, please treat it as a security vulnerability and report it via email.

## General Security Notes

- Never commit API keys, passwords, or credentials to the repository
- Use `.env` files for sensitive configuration (included in `.gitignore`)
- Rotate credentials immediately if you suspect they have been exposed
