# 代码清理任务

> 日期：2026-06-06
> 状态：待实施

## 1. 背景

项目经历了三个月的 vibe coding 开发，任务完成后可能出现以下遗留问题：

1. **死代码**：从未被调用的函数、类、方法、变量
2. **未使用 import**：`import` 了但实际未使用的模块
3. **孤文件**：没有被任何入口引用或导入的模块文件
4. **注释掉的废弃代码**：历史遗留的注释代码块
5. **空文件夹**：没有 `__init__.py` 的 Python 包目录
6. **重复代码**：功能相同但分散在多处的代码片段
7. **过期的配置**：`.env` 中定义了但代码中已不使用的环境变量

此外，任务开始之前的**现状基线**也存在上述问题，需要一并清理。

---

## 2. 清理范围

### 2.1 优先清理（高价值）

| 类别 | 范围 | 工具 |
|------|------|------|
| 未使用 import | `agent_web/` 下所有 Python 文件 | `pyflakes` / `ruff` |
| 死代码（函数/类） | `agent_web/` 下所有 Python 文件 | `vulture` |
| 孤文件 | `agent_web/` 下未被引用的 .py 文件 | 人工 + grep 确认 |

### 2.2 次要清理（中等价值）

| 类别 | 范围 | 工具 |
|------|------|------|
| 注释掉的代码 | `agent_web/` 下所有 Python 文件 | 人工审查 |
| 重复代码 | 跨文件的相似函数/逻辑 | `jellyfish` / 人工 |
| 空文件夹 | `agent_web/` 下无 `__init__.py` 的目录 | 人工 |

### 2.3 延后清理（低价值）

| 类别 | 说明 |
|------|------|
| 过期的 .env 配置 | 需要对照代码确认，谨慎处理 |
| 文档过期 | 独立任务，不在本 plan 范围 |

---

## 3. 实施步骤

### 3.1 第一轮：自动化工具检测

**工具安装**：
```bash
pip install vulture ruff pyflakes
```

**执行检测**：

```bash
# 1. 死代码检测（vulture）
cd agent_web
vulture . --min-confidence 80 --sort-by-size | tee vulture_report.txt

# 2. 未使用 import 检测（ruff）
ruff check . --select=F401,F821 | tee ruff_report.txt

# 3. 组合检测（pyflakes）
find . -name "*.py" -exec pyflakes {} \; 2>&1 | tee pyflakes_report.txt
```

### 3.2 第二轮：人工审查

**审查孤文件**：
```bash
# 列出所有 .py 文件
find . -name "*.py" | sort > all_py_files.txt

# 检查每个文件是否被 import 或在其他文件引用
# （人工 + grep 辅助）
```

**审查注释掉的代码**：
- 搜索 `"""...` 内的注释、`# if `、`# else` 等被注释的代码块
- 关键词：`# TODO`、`# FIXME`、`# DEPRECATED`、`# 废弃`

### 3.3 第三轮：清理执行

**按优先级逐个处理**：

1. 删除确认的孤文件
2. 删除确认的未使用 import
3. 删除确认的未使用函数/类（按 vulture 报告）
4. 清理空文件夹
5. 删除注释掉的废弃代码

**注意**：
- 每次删除前确认无引用
- 删除后运行测试确保功能正常
- 较大的改动单独 commit

---

## 4. 检测命令汇总

```bash
# 进入 agent_web 目录
cd agent_web

# 死代码检测（函数/类未被调用）
vulture . --min-confidence 80 --sort-by-size

# 未使用 import 和变量
ruff check . --select=F401,F811,F821

# 语法和格式问题
ruff check . --select=F,E

# 未定义名称
pyflakes .

# 查找可能的死代码（手动确认）
grep -r "def " --include="*.py" | grep -v "__" | awk -F: '{print $1}' | sort -u > all_functions.txt
```

---

## 5. 验收标准

| 标准 | 说明 |
|------|------|
| vulture 报告无高置信度死代码 | confidence >= 80 的项全部处理 |
| ruff check 无 F401/F821 警告 | 所有未使用 import 和未定义变量已清理 |
| 无孤 .py 文件 | 每个 .py 文件至少被一个入口引用 |
| 无空文件夹 | 所有 Python 包目录有 `__init__.py` |
| 测试通过 | `pytest` 全部通过 |

---

## 6. 注意事项

1. **不要过度清理**：保留合理的工具函数和工具类，即使当前未直接调用
2. **谨慎删除**：不确定的文件先注释掉，观察一周后再删除
3. **保留接口**：已被外部引用的接口不要删除（检查 `__all__` 和显式 import）
4. **IDE 辅助**：用 PyCharm/VSCode 的 unused symbol 检测作为辅助
5. **分批提交**：每次清理单独 commit，便于回滚

---

## 7. 与其他任务的关系

- **独立任务**：可以在其他任务开发过程中并行进行
- **前置清理**：建议在实施 Phase 1 之前完成基线清理，减少后续冲突
- **后续清理**：每次任务完成后顺手清理，不积累

---

*文档创建日期：2026-06-06*
*方案状态：待实施*
