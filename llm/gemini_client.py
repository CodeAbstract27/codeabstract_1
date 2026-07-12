"""
Google Gemini LLM Client

Integrates with Google Gemini models.
"""

import time
import google.generativeai as genai
from dataclasses import dataclass
from typing import Optional

@dataclass
class LLMResponse:
    content: str
    response_time: float
    success: bool
    error: Optional[str] = None

SYSTEM_PROMPT = """You are an expert code reviewer. 
The code uses abstract identifiers (FUNC_0, VAR_1, CLASS_0) 
for privacy. Use these exact names in your response.
Reference specific line numbers when pointing out issues."""

TASK_PROMPTS = {
    'debug': "Find bugs and errors in this code:\n\n```python\n{code}\n```",
    'review': "Review this code for quality and issues:\n\n```python\n{code}\n```",
    'optimize': "Suggest optimizations for this code:\n\n```python\n{code}\n```",
    'security': "Find security issues in this code:\n\n```python\n{code}\n```",
    'explain': "Explain what this code does:\n\n```python\n{code}\n```",
}

class GeminiClient:
    
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name=model,
            system_instruction=SYSTEM_PROMPT
        )
    
    def send(self, abstract_code: str, task: str = "review") -> LLMResponse:
        start = time.time()
        try:
            prompt = TASK_PROMPTS.get(task, TASK_PROMPTS['review'])
            response = self.model.generate_content(
                prompt.format(code=abstract_code)
            )
            return LLMResponse(
                content=response.text,
                response_time=time.time() - start,
                success=True
            )
        except Exception as e:
            return LLMResponse(
                content="",
                response_time=time.time() - start,
                success=False,
                error=str(e)
            )
