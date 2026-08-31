from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

ds="deepseek-v4-pro"
opus="claude-opus-4-7"
dsp="deepseek"
model = init_chat_model(
    model=opus,
    model_provider="anthropic",
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
    "language": "日语",
    "text": "游戏研发的核心不是单点完成某个文档、素材或代码，而是持续把创意转化为可验证、可上线、可运营的内容。当前游戏项目中，策划、美术、研发、运营各环节都依赖大量人工经验和跨部门沟通。一个新玩法或新活动从想法提出，到策划案、素材需求、研发实现、测试验证、运营上线，往往需要多轮沟通和反复修改。"
},stream_mode="updates"):
    # 打印每个生成的内容块，end="" 避免自动换行，flush=True 强制立即输出屏幕
    print(chunk.content, end="")
