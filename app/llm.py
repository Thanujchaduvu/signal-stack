"""Provider-agnostic LLM client. Only free tiers / local models are supported."""
import os, json, re, time, httpx

class LLMUnavailable(Exception):
    pass

STUB = None  # tests may set a callable(prompt, system, json_mode)->str

def provider():
    p = os.getenv("LLM_PROVIDER", "").lower()
    if p: return p
    if os.getenv("GEMINI_API_KEY"): return "gemini"
    if os.getenv("GROQ_API_KEY"): return "groq"
    return ""

def chat(prompt, system="", json_mode=False, temperature=0.3, retries=3):
    if STUB: return STUB(prompt, system, json_mode)
    p = provider()
    if not p:
        raise LLMUnavailable("No LLM configured. Set LLM_PROVIDER and a free API key in .env (Gemini, Groq) or run Ollama.")
    last = None
    for i in range(retries):
        try:
            with httpx.Client(timeout=120) as h:
                if p == "gemini":
                    key = os.getenv("GEMINI_API_KEY"); m = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
                    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                            "generationConfig": {"temperature": temperature, **({"responseMimeType": "application/json"} if json_mode else {})}}
                    if system: body["systemInstruction"] = {"parts": [{"text": system}]}
                    r = h.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", params={"key": key}, json=body)
                    if r.status_code in (429, 503): raise RuntimeError(f"rate limited {r.status_code}")
                    r.raise_for_status()
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"]
                if p == "groq":
                    body = {"model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), "temperature": temperature,
                            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]}
                    if json_mode: body["response_format"] = {"type": "json_object"}
                    r = h.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"}, json=body)
                    if r.status_code == 429: raise RuntimeError("rate limited 429")
                    r.raise_for_status()
                    return r.json()["choices"][0]["message"]["content"]
                if p == "ollama":
                    body = {"model": os.getenv("OLLAMA_MODEL", "llama3.1:8b"), "stream": False, "options": {"temperature": temperature},
                            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]}
                    if json_mode: body["format"] = "json"
                    r = h.post(os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/chat", json=body)
                    r.raise_for_status()
                    return r.json()["message"]["content"]
                raise LLMUnavailable(f"Unknown LLM_PROVIDER '{p}'")
        except LLMUnavailable:
            raise
        except Exception as e:  # backoff for free-tier rate limits
            last = e; time.sleep(4 * (i + 1))
    raise RuntimeError(f"LLM call failed: {last}")

def parse_json(txt):
    t = re.sub(r"^```(?:json)?|```$", "", (txt or "").strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"(\{.*\}|\[.*\])", t, re.S)
        if m:
            return json.loads(m.group(1))
        raise ValueError("LLM did not return valid JSON")

SYSTEM = ("You are a rigorous business-intelligence analyst. Never invent facts, sources, URLs, dates or quotes. "
          "Separate what is evidenced from what is your interpretation. If information is missing, say so. Return only what is asked.")

def chat_json(prompt, temperature=0.2):
    last = None
    for _ in range(2):
        try:
            return parse_json(chat(prompt, SYSTEM, True, temperature))
        except ValueError as e:
            last = e
    raise RuntimeError(str(last))
