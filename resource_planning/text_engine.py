"""Optional chat-completions client; no third-party dependency for offline runs."""
import json
import os
from urllib.request import Request, urlopen


class DeepseekModel:
    def __init__(self, text_api_key="", model="", base_url="", timeout=60):
        self.api_key = text_api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.model = model or os.getenv("TEXT_MODEL", "deepseek-chat")
        self.base_url = base_url or os.getenv("TEXT_BASE_URL", "https://api.deepseek.com/v1")
        self.timeout = timeout

    def invoke(self, text=""):
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")
        body = {"model": self.model, "messages": [{"role": "user", "content": text}],
                "temperature": 0.3, "max_tokens": 6000,
                "response_format": {"type": "json_object"}}
        request = Request(self.base_url.rstrip("/") + "/chat/completions",
                          data=json.dumps(body).encode(), headers={
                              "Authorization": "Bearer " + self.api_key,
                              "Content-Type": "application/json", "Accept-Encoding": "identity"})
        with urlopen(request, timeout=self.timeout) as response:
            result = json.load(response)
        choice = result["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("Incomplete model response")
        return choice["message"]
