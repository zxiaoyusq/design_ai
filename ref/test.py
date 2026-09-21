from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

ds="deepseek-v4-pro"
opus="claude-opus-4-7"
dsp="deepseek"
sol="gpt-5.6-sol"
terra="gpt-5.6-terra"
model = init_chat_model(
    model=terra,
    model_provider="openai",
    anthropic_api_key="sk-322b29fc30a0e3439687aa33c56e4a8d22ba6d1e8f19669f", # 显式传入 Key
    base_url="https://api.himodels.ai",                        # 显式传入中转 URL
    # temperature=0,
    # other parameters
)

# 构建消息列表
messages = [
    # SystemMessage(content="你是一个精通 Python 的资深程序员，回答要简明扼要。"),
    HumanMessage(content="你是那个模型")
]
# 1. 创建提示词模板
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个专业的翻译官，请将以下文本翻译成{language}。"),
    ("human", "{text}")
])

# 2. 使用管道符 `|` 将提示词和模型连接成一个处理链 (Chain)
chain = prompt | model


for chunk in chain.stream({
    "text": ""
},stream_mode="updates"):
    # 打印每个生成的内容块，end="" 避免自动换行，flush=True 强制立即输出屏幕
    print(chunk.content, end="")
