# Secrets handling

`backend/.env` holds real API keys (`OPENAI_API_KEY`, and `GEMINI_API_KEY` if set). Never read `.env` contents into chat output, log them, or hardcode key values into source files. Already correctly gitignored (`.env`, `**/.env.production`) — keep it that way; don't loosen `.gitignore` around env files.
