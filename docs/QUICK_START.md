# Quick Start

## 1. 环境要求

- Python 3.10+
- Linux / Ubuntu / Windows
- 推荐使用虚拟环境

## 2. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. 启动 Mock AcnAgent

```bash
uvicorn app.mock_acn_agent:app --host 127.0.0.1 --port 9010
```

## 4. 运行示例

```bash
python examples/demo_identity_flow.py
```

示例中的 SDK 导入路径已经切换为：

```python
from acn_sdk import AcnSDK, RobotInfo

sdk = AcnSDK(robot_name="AliceAgent")
```

## 5. Linux / Ubuntu 一键启动

```bash
chmod +x scripts/start_sdk_demo.sh
./scripts/start_sdk_demo.sh
```

## 6. PyCharm 调试方式

1. 打开工程根目录。
2. 配置项目解释器为 Python 3.10+。
3. 安装 `requirements.txt`。
4. 增加 FastAPI mock 运行配置：

```text
Script: uvicorn
Parameters: app.mock_acn_agent:app --host 127.0.0.1 --port 9010
Working directory: 项目根目录
```

5. 增加 SDK 示例运行配置：

```text
Script path: examples/demo_identity_flow.py
Working directory: 项目根目录
```

6. 调试顺序：
   先启动 mock AcnAgent，再启动示例或 `pytest`。

7. 如需观察日志，默认输出文件为：

```text
logs/acn_sdk.log
```

## 8. 当前配置说明

`config/config.yaml` 当前包含两类配置：

- SDK 自身端口：`http_port=8001`、`ws_port=8002`、`moq_pub_port=8003`、`moq_sub_port=8004`
- 网端信息：`network_ip=127.0.0.1`、`acn_agent_port=9010`、`agent_gw_ws_port=9002`、`agent_gw_moq_port=9003`、`web_ui_port=9004`
