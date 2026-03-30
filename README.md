# ACN SDK

ACN SDK 是运行在机器人端侧的 Python 组件，用于与核心网侧 `AcnAgent` 和 `AgentGW` 通信。本项目当前只实现 SDK 侧能力，核心网相关部件通过 FastAPI 打桩模拟。

当前版本已将 SDK 包名统一为 `acn_sdk`，并按业务域进行垂直拆分：

- `acn_sdk/identity`：身份管理
- `acn_sdk/network`：HTTP、WebSocket、MoQ 网络通信
- `acn_sdk/credential`：能力凭证签发
- `acn_sdk/task`：任务管理
- `acn_sdk/sdk.py`：主编排入口
- `acn_sdk/config.py`：配置模型与默认值定义

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
├── mock/
│   ├── mock_acn_agent.py
│   ├── mock_agent_gw.py
│   └── mock_moq_relay.py
├── config/
│   └── config.yaml
├── docs/
│   ├── API.md
│   ├── ARCHITECTURE.md
│   └── QUICK_START.md
├── examples/
│   ├── demo_identity_flow.py
│   └── demo_task_flow.py
├── scripts/
│   ├── start_mock_moq_relay.sh
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
- 入网、任务执行、任务终止、协同请求、协同接受、任务启动
- HTTP/WebSocket/MoQ/TaskManager 组件封装
- 本地 `AcnAgent` + `AgentGW` + `MOQ Relay` mock 联调
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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python3 mock/mock_acn_agent.py --host 127.0.0.1 --port 9010
python3 mock/mock_arf.py --host 127.0.0.1 --port 9001
python3 mock/mock_agent_gw.py --host 127.0.0.1 --port 9002
python3 mock/mock_moq_relay.py --host 127.0.0.1 --port 9003 --cache-dir data/moq-relay-cache
python3 examples/demo_identity_flow.py
python3 examples/demo_task_flow.py
```

推荐启动顺序：

1. 安装依赖并执行 `pip install -e .`
2. 启动 `python3 mock/mock_acn_agent.py --host 127.0.0.1 --port 9010`
3. 启动 `python3 mock/mock_arf.py --host 127.0.0.1 --port 9001`
4. 启动 `python3 mock/mock_agent_gw.py --host 127.0.0.1 --port 9002`
5. 启动 `python3 mock/mock_moq_relay.py --host 127.0.0.1 --port 9003 --cache-dir data/moq-relay-cache`
6. 运行 `python3 examples/demo_identity_flow.py`、`python3 examples/demo_task_flow.py` 或 `pytest`

Windows + PyCharm：

1. 使用 PyCharm 打开项目根目录 `/home/acn/zxy` 对应工程副本。
2. 创建 Python 3.10+ 虚拟环境。
3. 安装 `requirements.txt`，并执行 `pip install -e .`。
4. 新建 `python mock/mock_acn_agent.py --host 127.0.0.1 --port 9010` 运行配置。
5. 新建 `python mock/mock_arf.py --host 127.0.0.1 --port 9001` 运行配置。
6. 新建 `python mock/mock_agent_gw.py --host 127.0.0.1 --port 9002` 运行配置。
7. 新建 `python mock/mock_moq_relay.py --host 127.0.0.1 --port 9003 --cache-dir data/moq-relay-cache` 运行配置。
8. 新建 `examples/demo_identity_flow.py` 和 `examples/demo_task_flow.py` 运行配置。
9. 先启动四个 mock 服务，再运行示例或测试。

`examples/demo_task_flow.py` 当前会启动两个 SDK 实例：

- `AliceAgent`：发起任务、请求协同、发布 `Location` track
- `RobotDog`：接受协同、订阅 `Location` track、接收真实 MOQ relay 转发的对象

真实联调成功时，终端会出现类似输出：

```text
[RobotDog] callback message_type=MOQ_OBJECT payload={'namespace': '/task-xxxxx/did:acn:agent:...', 'track': 'Location', 'message_info': b'2026-03-30T00:00:00Z'}
```

如果不做 `pip install -e .`，则需要把项目根目录标记为 `Sources Root`。

示例导入方式：

```python
from acn_sdk import AcnSDK, RobotInfo

sdk = AcnSDK(robot_name="AliceAgent")
```

当前配置文件 [config.yaml](/home/acn/zxy/config/config.yaml) 已调整为：

- SDK 自身端口：`http_port=8001`、`ws_port=8002`、`moq_pub_port=8003`、`moq_sub_port=8004`
- 网端信息：`network_ip=127.0.0.1`、`acn_agent_port=9010`、`agent_gw_ws_port=9002`、`agent_gw_moq_port=9003`、`web_ui_port=9004`
- `acn_sdk/config.py` 只提供配置模型和默认值，不是运行时入口
- 运行时优先读取 `config/config.yaml`；修改后可在代码里调用 `sdk.reload_config()` 立即重载

## 测试

```bash
pytest
```

当前主流程已经通过本地自动化测试验证：

- SDK 初始化时自动生成并保存 EC 公私钥
- 身份注册会持久化 `agent_id` 和 `vc0`，请求体中的 `signature` 仅基于 `timestamp` 生成，编码采用 `base64`
- 能力注册会生成多个能力 VC，并按 `vc_list` 发送到 `/arf/v1/agent-cards`，请求体字段顺序为 `agent_id`、`priority`、`timestamp`、`signature`、`signature_encoding`、`vc_list`
- 去注册只清理身份状态，不删除本地密钥，请求体中的 `signature` 仅基于 `timestamp` 生成，编码采用 `base64`

接口请求约定与最新示例以 [docs/API.md](docs/API.md) 为准。

## 文档

- [快速开始](docs/QUICK_START.md)
- [架构设计](docs/ARCHITECTURE.md)
- [接口文档](docs/API.md)
