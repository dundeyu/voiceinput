# Contributing

感谢你对这个项目感兴趣。

## Development Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

## Project Layout

- `main.py`: 程序入口
- `src/`: 录音、音频处理、ASR、CLI 与运行时辅助逻辑
- `config/`: 配置文件
- `bin/voice`: 便于加入 PATH 的命令行入口
- `tests/`: `pytest` 回归测试
- `pyproject.toml`: 打包与 `voice` 命令入口配置

## Before Opening a PR

请至少确认：

```bash
venv/bin/python -m pytest tests
```

如果你修改了以下内容，请同时补回归测试：

- 文本清洗或词汇纠错
- CLI 输出格式
- 启动流程
- 配置加载逻辑
- 录音会话控制逻辑

## Coding Guidelines

- 使用 Python 4 空格缩进
- 函数和变量使用 `snake_case`
- 类名使用 `PascalCase`
- 保持模块职责单一，延续当前 `src/` 目录拆分
- 避免无意义的风格化重排
- 用户可见文案保持当前中英文风格一致

## Commit Messages

建议继续使用 Conventional Commits，例如：

- `feat: add config example for open source setup`
- `fix: suppress inference progress noise`
- `docs: add installation guide for global voice command`

## Issues

提交问题时请尽量附带：

- 操作系统版本
- Python 版本
- 启动方式，是 `voice`、`./run.sh` 还是 `python main.py`
- 相关配置片段
- 终端报错信息

仓库已经提供 issue 和 PR 模板。提交前尽量按模板补全环境、复现步骤和验证方式，这会显著提高处理效率。
