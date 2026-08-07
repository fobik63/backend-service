"""Ollama local-LLM package (plan §69)."""

from app.infrastructure.ollama.client import OllamaClient, OllamaError

__all__ = ["OllamaClient", "OllamaError"]
