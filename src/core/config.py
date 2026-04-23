import os

from dotenv import load_dotenv

# override=True 确保.env文件优先
load_dotenv(override=True)

# 从环境变量读取配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

from langchain.chat_models import init_chat_model
from langchain_ollama import OllamaEmbeddings


# 通过统一接口初始化LLM
deepseek_llm = init_chat_model(
    model="deepseek-chat",
    model_provider="deepseek",
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
    streaming=True,
    temperature=0,
)

qwen_llm = init_chat_model(
    model="qwen3.5-plus",
    api_key=QWEN_API_KEY,
    base_url=QWEN_BASE_URL,
    model_provider='deepseek'
)

# 初始化 Ollama 嵌入模型
ollama_embeddings = OllamaEmbeddings(
    model="qwen3-embedding:4b",
    base_url="http://localhost:11434",
)




