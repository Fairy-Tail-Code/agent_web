# 完成 6-6 Task 系列任务

## 目标

依次完成以下三个任务，每个任务需要通过测试验证可行性后再进入下一个。

---

## 项目结构（当前）

```
agent_web/
├── Agents/                    # Agents 相关模块
│   ├── agent/                 # Agent 定义
│   ├── team/                  # Team 定义
│   ├── tools/                 # Toolkit 定义
│   ├── knowledge/             # 知识库
│   └── server/               # MCP 服务
│       ├── data/              # Data MCP 服务
│       └── docx_use_mcp/      # Docx MCP 服务（待合并）
├── api/                       # FastAPI 入口
├── auth/                      # 认证中间件
├── config/                    # 配置
├── storage/                   # OSS 存储能力（七牛云）
├── hook/                      # 钩子
├── docs/
└── tests/
```

---

## 任务一：统一存储模块（`6-6-task-unified-storage.md`）

**目标**：实现 Data 服务和 Office 服务的统一存储抽象层，OSS 能力并入存储模块。

### 1.1 新增 `storage/file_manager.py`

- `BaseFileManager` 基类：`save_local()`、`register()`、`get_path()`、`load()`、`sync_to_oss()`
- `DataFileManager` 子类：CSV 数据文件管理，路径隔离
- `OfficeFileManager` 子类：办公文档管理，按格式分类输出目录
- `KnowledgeFileManager` 子类：知识库文件管理

### 1.2 修改 `auth/user_db.py`

添加 `storage.files` 建表 SQL（统一元数据表）

### 1.3 修改 `hook/preprocess.py`

使用 `DataFileManager` 替代原有上传逻辑

### 1.4 修改 `Agents/server/data/data_process/data_preprocessing.py`

使用 `DataFileManager.get_csv_path()` 替代 `_get_data_path_by_user()`

### 1.5 修改 `Agents/server/data/machine_learning/machine_learning_model.py`

使用 `DataFileManager` 替代路径解析

### 1.6 新增 `storage/oss_sync_worker.py`

后台归档 Worker，扫描 `status=local` 的文件，异步上传 OSS

### 1.7 线程池/进程池生命周期管理

- `Agents/server/data/data_process/task_pool.py`：注册 atexit 清理 + fork 后重新初始化
- `Agents/server/data/machine_learning/process_pool.py`：同上

**验收**：相关模块的单元测试通过，现有功能不受影响。

---

## 任务二：Docx MCP 合并进 Office Toolkit（与任务一同阶段）

**目标**：将 docx_use_mcp 从独立 MCP 服务改为本地 Toolkit，与 office 系列工具保持架构一致。

### 2.1 删除文件

| 文件 | 原因 |
|------|------|
| `Agents/agent/docx_use_agent.py` | 死代码，未被引用，功能与 `office_word_agent.py` 重叠 |
| `Agents/tools/mcp_tools/docx_use_mcp_tool.py` | MCPTools 替代品，合并后不再需要 |

### 2.2 新增 `Agents/tools/office_docx_toolkit.py`

把 `Agents/server/docx_use_mcp/docx_use_server/tools/` 下的 54 个 docx 工具做成本地 Toolkit，直接调用底层逻辑，不再走 MCP HTTP：

```python
class OfficeDocxToolkit(Toolkit):
    """Word 文档本地工具包"""
    def create_document(self, filename: str, user_id: str, title: str = None, ...):
        from Agents.server.docx_use_mcp.docx_use_server.tools.document_tools import create_document
        from storage.file_manager import OfficeFileManager
        fm = OfficeFileManager()
        file_path = fm.build_output_path(user_id, filename, "docx")
        result = create_document(file_path, title, author)
        fm.register(user_id, file_path, filename=filename)
        return result
```

### 2.3 修改 `Agents/agent/office_word_agent.py`

`docx_use_mcp_tool` → `OfficeDocxToolkit`

### 2.4 废弃 `Agents/server/docx_use_mcp/main.py` 和 `setup_mcp.py`

不再作为独立 MCP 入口，`docx_use_server/` 下的逻辑保留供 `OfficeDocxToolkit` 调用。

### 2.5 docker-compose.yaml

删除 `docx-use-mcp` 服务相关配置，`DOCX_USE_MCP_URL` 环境变量不再需要。

**验收**：Word 专家 Agent 能正常创建/修改文档，功能与改造前一致。

---

## 任务三：登录安全增强（`6-6-task-login-security.md`）

**目标**：实现登录安全增强，包括人机验证、登录计数、账号锁定、统一错误信息。

### 3.1 新增 `auth/login_security.py`

登录失败计数 + 账号锁定逻辑（Redis 或 SQLite 存储）

### 3.2 新增 `auth/captcha.py`

Turnstile token 验证

### 3.3 新增 `auth/login_router.py`

- `POST /auth/login`：新登录接口（推荐），验证 CAPTCHA + 检查计数 + 调用 Supabase Auth
- `POST /auth/login/supabase`：旧登录接口（废弃过渡）

### 3.4 新增 `auth/login_logs.py`

- `auth.login_logs` 建表 SQL
- `record_login_log()` 函数

### 3.5 修改 `auth/user_db.py`

添加 login_logs 建表 SQL

### 3.6 修改 `api/main.py`

注册 `login_router`

### 3.7 前端改造

- 登录页集成 Turnstile widget
- 登录请求调用 `/auth/login` 并附带 `turnstile_token`

**验收**：登录接口能正常工作，CAPTCHA 验证生效，登录失败计数和锁定生效。

---

## 任务四：代码清理（`6-6-task-code-cleanup.md`）

**目标**：清理项目中存在的死代码、未使用 import、孤文件等。

### 4.1 运行 `vulture` 检测死代码

### 4.2 运行 `ruff check` 检测未使用 import（F401、F821）

### 4.3 审查并删除孤文件

### 4.4 清理空文件夹

### 4.5 清理注释掉的废弃代码

**验收**：vulture 高置信度报告为空，ruff 无 F401/F821 警告，测试全部通过。

---

## 重要约束

1. 每个任务完成后运行 `pytest` 确保测试通过
2. 每个任务单独 commit，不要混在一起
3. 任务一和任务二可以并行（共享 `storage/file_manager.py`）
4. 任务三（代码清理）可以与任务一/二并行
5. 改造前先读一遍相关代码，了解现有逻辑
6. 遇到不确定的地方先讨论再动手

---

## 执行顺序

```
1. 统一存储模块（任务一）
2. Docx MCP 合并（任务二，与任务一同阶段）
3. 登录安全增强（任务三）
4. 代码清理（任务四，可与前三并行）
```
