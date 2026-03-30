# Quick Start

## 1. 环境要求

- Python 3.10+
- Linux / Ubuntu / Windows
- 推荐使用虚拟环境

## 2. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

## 3. 启动 Mock AcnAgent、Mock ARF、Mock AgentGW 与 Mock MOQ Relay

```bash
python3 mock/mock_acn_agent.py --host 127.0.0.1 --port 9010
python3 mock/mock_arf.py --host 127.0.0.1 --port 9001
python3 mock/mock_agent_gw.py --host 127.0.0.1 --port 9002
python3 mock/mock_moq_relay.py --host 127.0.0.1 --port 9003 --cache-dir data/moq-relay-cache
```

建议先启动四个 mock 服务，再运行 SDK 示例或测试，保证 `AcnSDK` 初始化后既能访问 `ACN Agent` / `ARF` HTTP 接口，也能和 `ws://127.0.0.1:9002/ws` 完成入网握手，并通过真实 `MOQ Relay` 完成 track 发布与订阅。

## 4. 运行示例

```bash
python3 examples/demo_identity_flow.py
python3 examples/demo_task_flow.py
```

其中 `demo_task_flow.py` 会创建两个独立 SDK 实例，演示：

- 发起方请求协同任务
- 协作方通过 WebSocket 接收 `TASK_REQUEST_COLLABORATION`
- 发起方发布 `Location` track
- 协作方通过真实 MOQ relay 收到 `MOQ_OBJECT`

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
3. 在项目解释器中安装 `requirements.txt`，并执行 `pip install -e .`。
4. 增加 FastAPI mock 运行配置：

```text
Script path: mock/mock_acn_agent.py
Parameters: --host 127.0.0.1 --port 9010
Working directory: 项目根目录
```

```text
Script path: mock/mock_arf.py
Parameters: --host 127.0.0.1 --port 9001
Working directory: 项目根目录
```

```text
Script path: mock/mock_agent_gw.py
Parameters: --host 127.0.0.1 --port 9002
Working directory: 项目根目录
```

```text
Script path: mock/mock_moq_relay.py
Parameters: --host 127.0.0.1 --port 9003 --cache-dir data/moq-relay-cache
Working directory: 项目根目录
```

5. 增加 SDK 示例运行配置：

```text
Script path: examples/demo_identity_flow.py
Working directory: 项目根目录
```

```text
Script path: examples/demo_task_flow.py
Working directory: 项目根目录
```

如未执行 `pip install -e .`，则需要把项目根目录标记为 `Sources Root`，否则 `from acn_sdk import ...` 无法导入。

6. 调试顺序：
   先启动 mock AcnAgent、mock ARF、mock AgentGW、mock MOQ Relay，再启动示例或 `pytest`。

7. 如需观察日志，默认输出文件为：

```text
logs/acn_sdk.log
```

## 8. 当前配置说明

`config/config.yaml` 当前包含两类配置：

- SDK 自身端口：`http_port=8001`、`ws_port=8002`、`moq_pub_port=8003`、`moq_sub_port=8004`
- 网端信息：`network_ip=127.0.0.1`、`acn_agent_port=9010`、`agent_gw_ws_port=9002`、`agent_gw_moq_port=9003`、`web_ui_port=9004`
- `config.py` 只提供模型默认值，运行时以 `config/config.yaml` 为准
- 修改 YAML 后，如需让已启动的 SDK 立即生效，调用 `sdk.reload_config()`
- 如需切换到其他环境，可直接修改 `config/config.yaml`，无需改动代码

## 9. 当前功能校验

当前实现已覆盖以下行为：

- `AcnSDK` 初始化时自动检查本地公钥和私钥，不存在则生成并保存 EC P-256 密钥
- `register_agent_info` 成功后保存 `agent_id` 和 `vc0`，请求体中的 `signature` 仅基于 `timestamp` 生成，编码采用 `base64`
- `register_agent_attribute(agent_id, capability)` 会先校验传入的 `agent_id` 与本机身份一致，再生成全部能力 VC，并以 `vc_list=[vc0, *capability_vcs]` 的格式发送到 `/arf/v1/agent-cards`，请求体字段顺序为 `agent_id`、`timestamp`、`signature`、`signature_encoding`、`vc_list`
- `deregister_robot` 仅清理本地身份状态，不删除已生成的公钥和私钥，请求体中的 `signature` 仅基于 `timestamp` 生成，编码采用 `base64`
- `join_network` 会先通过 WebSocket 向 AgentGW 发送 `SETUP`，收到对端 `SETUP/OK` 且本地 MOQ 客户端建立后才视为入网成功
- `demo_task_flow.py` 可以演示任务请求、服务端推送协同消息、SDK 回调通知、`SUBSCRIBE_TRACK` 处理和通过真实 MOQ relay 传输 `task_info_report`

本地验证命令：

```bash
pytest -q
```
