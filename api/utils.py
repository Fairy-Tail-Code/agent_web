from agno.agent import Agent
from agno.memory import MemoryManager
from agno.tools.duckduckgo import DuckDuckGoTools

from config.db_config import create_base_db
from config.model_config import get_ai_model


def _process_agent_tool_entrypoints(agent: Agent):
    """Process entrypoints for all agent tools to extract descriptions from docstrings."""
    try:
        if not agent.tools:
            return
        from agno.tools import Toolkit
        from agno.tools.function import Function

        for tool in agent.tools:  # ty:ignore[not-iterable]
            if isinstance(tool, Toolkit):
                for _, func in tool.functions.items():
                    if func.entrypoint and not func.skip_entrypoint_processing:
                        try:
                            # Only process if description is not already set
                            if not func.description:
                                func.process_entrypoint()
                        except Exception:
                            pass
            elif isinstance(tool, Function):
                if tool.entrypoint and not tool.skip_entrypoint_processing:
                    try:
                        if not tool.description:
                            tool.process_entrypoint()
                    except Exception:
                        pass
    except Exception:
        pass


def set_default_config_to_agent(agent: Agent):
    # unified config
    if isinstance(agent, Agent):
        agent.db = create_base_db(agent.id)  # ty:ignore[invalid-argument-type]
        # 如果 model 为 None 或是框架默认的 OpenAIChat(id="gpt-4o")，替换为系统的 get_ai_model()
        if not agent.model or (type(agent.model).__name__ == "OpenAIChat" and agent.model.id == "gpt-4o"):
            agent.model = get_ai_model()
        agent.memory_manager = agent.memory_manager or MemoryManager(
            model=get_ai_model(model_type="deepseek"),
            db=agent.db,
            debug_mode=False,
        )
        # Note: Fixed knowledge binding removed to enable multi-tenant isolation.
        # Agents should use knowledge query tools instead.

        # not default config
        agent.stream_intermediate_steps = True  # ty:ignore[unresolved-attribute]
        # agent.read_chat_history = True
        agent.add_history_to_context = True
        # 似乎开启这个以后，用户每轮消息都会被写入记忆。
        agent.enable_agentic_memory = True
        agent.store_history_messages=False

        # 每轮对话之后进行记忆
        # agent.enable_user_memories = True
        # agent.search_knowledge = True  # Disabled, using tools instead
        # agent.update_knowledge = True  # Disabled, no fixed knowledge to update
        agent.markdown = True
        agent.add_datetime_to_context = True
        agent.debug_mode = True
        agent.stream = True

        # Process tool entrypoints to ensure descriptions are extracted from docstrings
        _process_agent_tool_entrypoints(agent)

        # 批量添加工具
        agent.tools.extend([DuckDuckGoTools(),])  # ty:ignore[unresolved-attribute]

        # ── 统一追加文件下载提示到 system_message ──
        _file_download_hint = (
            "\n\n【文件交付规范】当你使用工具生成了文件（如 .docx/.pdf/.xlsx/.md 等），"
            "在回复的末尾必须包含该文件的下载链接，格式为：\n"
            "[下载 文件名](/backend/files/download/相对路径)\n"
            "其中「相对路径」是文件相对于 /app/user_cache/ 的路径。"
            "例如文件保存在 /app/user_cache/office/output/docx/报告.docx，"
            "则链接为 [下载 报告.docx](/backend/files/download/office/output/docx/报告.docx)。"
            "可以给出多个文件链接。"
        )
        if hasattr(agent, "system_message") and agent.system_message:
            agent.system_message += _file_download_hint  # ty:ignore[unsupported-operator]
        elif hasattr(agent, "instructions") and agent.instructions:
            agent.instructions += _file_download_hint  # ty:ignore[unsupported-operator]
    else:
        return agent
