# ACN SDK

ACN SDK 是运行在机器人端侧的 Python 组件，用于与核心网侧 `AcnAgent` 和 `AgentGW` 通信。本项目当前只实现 SDK 侧能力，核心网相关部件通过 FastAPI 打桩模拟。

当前版本已将 SDK 包名统一为 `acn_sdk`，并按业务域进行垂直拆分：

- `acn_sdk/identity`：身份管理
- `acn_sdk/network`：HTTP、WebSocket、MoQ 网络通信
- `acn_sdk/credential`：能力凭证签发
- `acn_sdk/task`：任务管理
- `acn_sdk/sdk.py`：主编排入口

## 项目结构

```text
acn-sdk/
├── acn_sdk/
│   ├── __init__.py
│   ├── sdk.py
│   ├── config.py
│   ├── crypto.py
│   ├── logging_config.py
│   ├── models.py
│   ├── credential/
│   │   ├── __init__.py
│   │   └── credential_issuer.py
│   ├── identity/
│   │   ├── __init__.py
│   │   └── identity_manager.py
│   ├── network/
│   │   ├── __init__.py
│   │   ├── http_client.py
│   │   ├── moq_client.py
│   │   └── websocket_client.py
│   └── task/
│       ├── __init__.py
│       └── task_manager.py
├── app/
│   └── mock_acn_agent.py
├── config/
│   └── config.yaml
├── docs/
│   ├── API.md
│   ├── ARCHITECTURE.md
│   └── QUICK_START.md
├── examples/
│   └── demo_identity_flow.py
├── scripts/
│   └── start_sdk_demo.sh
├── tests/
│   ├── conftest.py
│   └── test_identity_flow.py
├── pyproject.toml
└── requirements.txt
```

## 功能范围

- 机器人身份申请与本地持久化
- 能力 VC 模拟签发与注册
- 机器人身份查询
- 机器人去注册
- HTTP/WebSocket/MoQ/TaskManager 组件封装
- 关键消息与状态转换日志记录
- FastAPI 打桩测试

## 快速开始

Linux/Ubuntu 一键演示：

```bash
chmod +x scripts/start_sdk_demo.sh
./scripts/start_sdk_demo.sh
```

手工运行：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.mock_acn_agent:app --host 127.0.0.1 --port 9010
python examples/demo_identity_flow.py
```

Windows + PyCharm：

1. 使用 PyCharm 打开项目根目录 `/home/acn/zxy` 对应工程副本。
2. 创建 Python 3.10+ 虚拟环境。
3. 安装 `requirements.txt`。
4. 新建 `uvicorn app.mock_acn_agent:app --host 127.0.0.1 --port 9010` 运行配置。
5. 新建 `examples/demo_identity_flow.py` 运行配置。
6. 先启动 mock 服务，再运行示例或测试。

示例导入方式：

```python
from acn_sdk import AcnSDK, RobotInfo

sdk = AcnSDK(robot_name="AliceAgent")
```

当前配置文件 [config.yaml](/home/acn/zxy/config/config.yaml) 已调整为：

- SDK 自身端口：`http_port=8001`、`ws_port=8002`、`moq_pub_port=8003`、`moq_sub_port=8004`
- 网端信息：`network_ip=127.0.0.1`、`acn_agent_port=9010`、`agent_gw_ws_port=9002`、`agent_gw_moq_port=9003`、`web_ui_port=9004`

## 测试

```bash
pytest
```

## 文档

- [快速开始](docs/QUICK_START.md)
- [架构设计](docs/ARCHITECTURE.md)
- [接口文档](docs/API.md)
