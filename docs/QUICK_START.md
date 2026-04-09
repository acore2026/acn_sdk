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

## 3. 启动 Mock ARF、Mock AcnAgent、Mock AgentGW 与 Mock MOQ Relay

```bash
python3 mock/mock_arf.py --host 127.0.0.1 --port 9001
python3 mock/mock_acn_agent.py --host 127.0.0.1 --port 9010 --arf-host 127.0.0.1 --arf-port 9001
python3 mock/mock_agent_gw.py --host 127.0.0.1 --port 9002
python3 mock/mock_moq_relay.py --host 127.0.0.1 --port 9003 --cache-dir data/moq-relay-cache
```

建议先启动四个 mock 服务，再运行 SDK 示例或测试。SDK 只会访问 `ACN Agent` 的 HTTP 入口，`AcnAgent` 会把能力注册和协同发现转发到 `ARF`；同时它还会和 `ws://127.0.0.1:9002/ws` 完成入网握手，并通过真实 `MOQ Relay` 完成 track 发布与订阅。

## 4. 运行示例

```bash
python3 examples/demo_identity_flow.py
python3 examples/demo_task_flow.py
python3 examples/demo_task_flow_realtime.py
python3 examples/demo_task_collaborator.py
python3 examples/demo_task_initiator.py
python3 examples/demo_task_initiator_realtime.py
python3 examples/demo_task_collaborator_realtime.py
```

其中 `demo_task_flow.py` 会创建两个独立 SDK 实例，演示：

- 发起方请求协同任务
- 协作方通过 WebSocket 接收 `TASK_REQUEST_COLLABORATION`
- 发起方发布 `Location` track
- 协作方通过真实 MOQ relay 收到 `MOQ_OBJECT`

`demo_task_flow_realtime.py` 不会再用 `/debug/*` 接口注入中间消息，而是等待真实核心网消息流入，适合联调外部 AgentGW / ARF / MOQ 组件。

`demo_task_initiator_realtime.py` 和 `demo_task_collaborator_realtime.py` 则把原来的双机器人拆成两个独立终端入口，且同样不使用 `/debug/*` 注入。

如果要在两个终端分别运行两个机器人，先启动协作方，再启动发起方。两个 realtime 脚本不再依赖共享目录来同步状态，发起方会通过 `query_agent_list()` 轮询网络可见的在线状态，协作方则只在本地保持进程存活，等待 WebSocket 回调触发。

示例中的 SDK 导入路径已经切换为：

```python
from acn_sdk import AcnSDK, AgentInfo

sdk = AcnSDK(agent_name="AliceAgent")
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
Parameters: --host 127.0.0.1 --port 9010 --arf-host 127.0.0.1 --arf-port 9001
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

```text
Script path: examples/demo_task_flow_realtime.py
Working directory: 项目根目录
```

```text
Script path: examples/demo_task_collaborator.py
Working directory: 项目根目录
```

```text
Script path: examples/demo_task_initiator.py
Working directory: 项目根目录
```

```text
Script path: examples/demo_task_initiator_realtime.py
Working directory: 项目根目录
```

```text
Script path: examples/demo_task_collaborator_realtime.py
Working directory: 项目根目录
```

如未执行 `pip install -e .`，则需要把项目根目录标记为 `Sources Root`，否则 `from acn_sdk import ...` 无法导入。

6. 调试顺序：
   先启动 mock ARF、mock AcnAgent、mock AgentGW、mock MOQ Relay，再启动示例或 `pytest`。

7. 如需观察日志，默认输出文件为：

```text
logs/acn_sdk.log
```

## 8. 当前配置说明

`acn_sdk/config/config.yaml` 当前包含两类配置：

- 网端信息：`network_ip=127.0.0.1`、`acn_agent_port=9010`、`arf_port=9001`、`agent_gw_ws_port=9002`、`agent_gw_moq_port=9003`、`web_ui_port=9004`
- `settings.py` 只提供模型默认值，运行时以 `acn_sdk/config/config.yaml` 为准
- 修改 YAML 后，如需让已启动的 SDK 立即生效，调用 `sdk.reload_config()`
- 如需切换到其他环境，可直接修改 `acn_sdk/config/config.yaml`，无需改动代码

## 9. 当前功能校验

接口返回约定：

- `AcnSDK` 对外公共接口统一返回 `Tuple`
- 第一个元素固定为 `bool` 型 `result`
- 成功时后续元素为业务结果，失败时通常返回错误信息

当前实现已覆盖以下行为：

- `AcnSDK` 初始化时自动检查本地公钥和私钥，不存在则生成并保存 EC P-256 密钥
- `register_agent_info` 成功后保存 `agent_id` 和 `vc0`，请求体中的 `signature` 仅基于 `timestamp` 生成，编码采用 `base64`
- `register_agent_attribute(agent_id, capability)` 会先校验传入的 `agent_id` 与本机身份一致，再生成全部能力 VC，并以 `vc_list=[vc0, *capability_vcs]` 的格式发送到 `/arf/v1/agent-cards`，SDK 仍然通过 `AcnAgent` 的 HTTP 入口发起请求，由 `AcnAgent` 转发到 `ARF`，请求体字段顺序为 `agent_id`、`timestamp`、`signature`、`signature_encoding`、`vc_list`
- `deregister_agent` 仅清理本地身份状态，不删除已生成的公钥和私钥，请求体中的 `signature` 仅基于 `timestamp` 生成，编码采用 `base64`
- `join_network` 会先通过 WebSocket 向 AgentGW 发送 `SETUP`，收到对端 `SETUP/OK` 且本地 MOQ 客户端建立后才视为入网成功
- `demo_task_flow.py` 可以演示任务请求、服务端推送协同消息、SDK 回调通知、`SUBSCRIBE_TRACK` 处理和通过真实 MOQ relay 传输 `task_info_report`

本地验证命令：

```bash
pytest -q
```
