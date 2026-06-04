"""Sibling and Victim LLM interfaces for PCV-MIA.

中文说明：本文件是 src/llm 包的入口说明(__init__.py)。
llm 包统一封装所有对大语言模型的调用，分两种角色：
    - victim(受害者模型)：被攻击的目标问答系统所用的模型。
    - sibling(兄弟模型)：辅助模型，用来生成伪造文本、给伪造质量打分等。
底层都走 OpenAI 兼容接口(openai_compatible.py)，由 factory.py 按配置创建对应客户端。
"""
