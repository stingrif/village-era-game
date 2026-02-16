import os, requests, logging

API_BASE = os.getenv("LLM_API_BASE", "http://127.0.0.1:11434/v1")
API_KEY  = os.getenv("LLM_API_KEY", "none")
MODEL    = os.getenv("LLM_MODEL", "local-model")

def chat(system:str, user:str, max_tokens=120, temperature=0.7):
    url = f"{API_BASE}/chat/completions"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role":"system","content":system},
            {"role":"user","content":user}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"LLM fail: {e}")
        return None


