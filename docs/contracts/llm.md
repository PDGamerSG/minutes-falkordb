# Contract: LLM and embedding clients (`apps/api/llm`)

```python
class LLM:
    """One interface, three backends chosen by env LLM_BACKEND = gemini | openrouter | ollama."""
    def __init__(self, backend: str, model: str, api_key: str | None = None, base_url: str | None = None): ...
    def complete(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 2048) -> str
    def complete_json(self, system: str, user: str, schema: type[BaseModel], temperature: float = 0.1) -> BaseModel
        # asks for JSON; strips code fences; validates; ONE retry with the validation error appended; then raises LLMFormatError
    def tool_loop(self, system: str, messages: list[dict], tools: list[ToolSpec], execute: Callable[[str, dict], dict], max_steps: int = 6) -> ToolLoopResult
        # native function calling when the backend supports it (OpenAI tools format on openrouter/ollama, Gemini tools on gemini);
        # otherwise a JSON protocol: model returns {"tool": name, "args": {...}} or {"final": "..."}.
        # Every tool call's args are validated against ToolSpec.args_model before execute(). Invalid -> one retry -> fail loudly.

class ToolSpec(BaseModel):
    name: str; description: str; args_model: type[BaseModel]

class ToolLoopResult(BaseModel):
    final: str | None; steps: list[dict]; failed: bool; reason: str | None; model: str; latency_ms: int

class Embedder:
    """EmbeddingGemma via ONNX Runtime on CPU, 768-d, L2-normalized. Falls back to gemini-embedding-001 (768) if ONNX missing and GEMINI_API_KEY set."""
    dim: int = 768
    def embed(self, texts: list[str], kind: Literal["query", "document"] = "document") -> list[list[float]]
```

Environment
```
LLM_BACKEND=ollama            # gemini | openrouter | ollama
LLM_MODEL=gemma4:e4b          # gemini: gemma-4-26b-a4b-it ; openrouter: google/gemma-4-26b-a4b-it ; ollama: gemma4:e4b | gemma4:12b
LLM_MODEL_SMALL=gemma4:e4b
GEMINI_API_KEY=
OPENROUTER_API_KEY=
OLLAMA_BASE_URL=http://localhost:11434/v1
EMBED_BACKEND=onnx            # onnx | gemini | fake
EMBED_MODEL=onnx-community/embeddinggemma-300m-ONNX
HF_HOME=D:\hf-cache
```

Backends
- gemini: `google-genai` SDK, `client.models.generate_content(model=..., contents=..., config=GenerateContentConfig(system_instruction=..., tools=[...], response_mime_type="application/json"))`. Verify that Gemma 4 model ids accept `tools` and `response_mime_type`; if not, the JSON protocol path is used automatically.
- openrouter and ollama: `openai` SDK with `base_url`; tools in OpenAI format. Ollama serves `/v1/chat/completions` with tools for Gemma 4.
- fake (tests): `FakeLLM(responses=[...])` returns scripted outputs; `FakeEmbedder` returns deterministic hashed vectors of dim 768.

EmbeddingGemma prompt prefixes (from the model card): queries `"task: search result | query: {text}"`, documents `"title: none | text: {text}"`.
