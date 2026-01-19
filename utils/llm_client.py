"""
LLM 客户端封装，支持 DeepSeek API
"""
from typing import List, Dict, Optional
from openai import OpenAI
from config import Config


class LLMClient:
    """DeepSeek API 客户端封装"""
    
    def __init__(self, config: Config):
        self.config = config
        self.client = OpenAI(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url
        )
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None
    ) -> str:
        """
        调用 LLM 进行对话
        
        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大token数
            model: 模型名称
        
        Returns:
            LLM 返回的文本
        """
        # DeepSeek 当前 max_tokens 上限约 8192，做一次兜底截断
        max_t = max_tokens if max_tokens is not None else self.config.max_tokens
        if max_t is None:
            max_t = 2000
        max_t = min(max_t, 8000)
        try:
            response = self.client.chat.completions.create(
                model=model or self.config.model_name,
                messages=messages,
                temperature=temperature if temperature is not None else self.config.temperature,
                max_tokens=max_t
            )
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"LLM 调用失败: {str(e)}")
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        生成文本
        
        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            temperature: 温度参数
            max_tokens: 最大token数
        
        Returns:
            生成的文本
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        return self.chat(messages, temperature, max_tokens)

