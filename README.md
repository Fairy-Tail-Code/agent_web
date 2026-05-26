# Agent Manage - 智能代理管理平台

一个基于 `Agno + FastAPI + MCP` 的多 Agent 编排项目，提供智能代理管理、文档处理、数据分析、浏览器自动化等核心能力。

## 项目特性

- **Agent 编排**: 基于 Agno 框架的多 Agent 协作系统
- **MCP 集成**: 数据处理、文档处理等能力通过 MCP 服务提供
- **浏览器自动化**: 支持浏览器监控、自动化操作
- **办公文档处理**: Word、PDF 等文档的智能处理
- **数据分析与训练**: 支持数据预处理、机器学习模型训练

## 环境配置

项目使用 Docker Compose 区分开发和生产环境：

| 文件 | 用途 |
|------|------|
| `docker-compose.yaml` | 默认/生产环境 |
| `docker-compose.dev.yaml` | 开发环境 |
| `docker-compose.prod.yaml` | 生产环境（CI/CD 用） |
| `.env` | 当前激活的环境变量 |
| `.env.dev.example` | 开发环境配置模板 |

### 主要区别

**开发环境**：
- 本地构建镜像（`build`）
- 启用热重载：`UVICORN_RELOAD: "true"`
- `NODE_ENV: development`
- 使用开发版 Nginx 配置
- 端口：`8080:80`
- 源代码挂载支持热重载

**生产环境**：
- 使用预构建镜像
- 禁用热重载：`UVICORN_RELOAD: "false"`
- `NODE_ENV: production`
- 支持 HTTPS（`80/443` 端口）
- 完整安全配置

## 快速开始

### 开发环境

```bash
docker compose -f docker-compose.dev.yaml up -d
```

访问：`http://localhost:8080`

### 生产环境

```bash
# 设置环境变量后启动
docker compose up -d
```

## 常用命令

```bash
# 启动开发环境
docker compose -f docker-compose.dev.yaml up -d

# 查看日志
docker compose -f docker-compose.dev.yaml logs -f

# 查看特定服务日志
docker compose -f docker-compose.dev.yaml logs -f app
docker compose -f docker-compose.dev.yaml logs -f gateway

# 停止服务
docker compose -f docker-compose.dev.yaml down

# 重建镜像
docker compose -f docker-compose.dev.yaml up -d --build

# 清理所有数据（谨慎使用）
docker compose -f docker-compose.dev.yaml down -v
```

## 端口说明

| 服务 | 开发模式 | 生产模式 |
|------|---------|---------|
| 网关 | 8080 | 80, 443 |
| 后端 | 容器内 8005 | 容器内 8005 |
| 数据库 | 容器内 5432 | 容器内 5432 |
| Data MCP | 容器内 8085 | 容器内 8085 |
| Docx MCP | 容器内 8008 | 容器内 8008 |

## 目录结构

```
agent_web/
├── agent/              # Agent 定义
├── api/                # API 路由和接口
├── auth/               # 认证授权
├── config/             # 配置文件
├── deploy/             # 部署相关（Nginx 配置等）
├── docs/               # 项目文档
├── knowledge/          # 知识库
├── server/             # MCP 服务
├── team/               # Agent 团队
├── tools/              # 工具集
├── main.py             # 主入口
└── data_mcp_main.py    # 数据 MCP 服务入口
```

## 浏览器配置

如需让浏览器直接使用用户 Cookie，需进行以下设置：

**Edge 浏览器**：
```
设置 → 系统和性能 → 关闭下面两项：
☐ 关闭 Microsoft Edge 后继续运行后台扩展和应用
☐ 启动提速
```

Chrome 浏览器同理。

完成后关闭浏览器，并在 `.env` 中设置用户目录。

## 文档

- [本地开发指南](docs/本地开发指南.md) - 详细的开发环境配置说明
- [Agent 开发索引](AGENTS.md) - Agent 开发指南和代码架构说明
- [API 文档](docs/api.md) - API 接口文档
- [agent_docs/](docs/agent_docs/) - Agent 专题文档

## 技术栈

- **后端**: Python 3.12, FastAPI, Agno
- **数据库**: PostgreSQL + pgvector
- **容器**: Docker, Docker Compose
- **网关**: OpenResty (Nginx)
- **MCP**: FastMCP
- **前端**: Next.js (独立仓库)

## License

MIT