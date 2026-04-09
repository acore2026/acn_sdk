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

## 3. 启动本地 Mock 服务

直接启动统一入口即可：

```bash
chmod +x scripts/start_mock_services.sh
./scripts/start_mock_services.sh
```

也可以直接用 Python：

```bash
python3 mock/start_mock_services.py
```

如果安装了 `acn-sdk-mock`，也可以直接运行：

```bash
start-mock-services
```

SDK 只访问 `AcnAgent` 的 HTTP 入口，`AcnAgent` 再转发到 `ARF`；入网时会和 `ws://127.0.0.1:9002/ws` 完成 WebSocket 握手，并通过 MOQ Relay 完成对象发布与订阅。

## 4. 运行 Demo

```bash
python3 examples/demo_identity_flow.py
python3 examples/demo_task_flow.py
python3 examples/demo_task_flow_realtime.py
python3 examples/demo_task_collaborator.py
python3 examples/demo_task_initiator.py
python3 examples/demo_task_initiator_realtime.py
python3 examples/demo_task_collaborator_realtime.py
```

### 4.1 身份流程

`examples/demo_identity_flow.py` 用于验证身份申请、能力注册、查询和去注册。

### 4.2 单进程任务流

`examples/demo_task_flow.py` 会在一个进程里创建两个 SDK 实例：

- `AliceAgent`：发起任务、请求协同、发布 `Location` track
- `RobotDog`：接受协同、订阅 `Location` track、接收真实 MOQ Relay 转发的对象

这个脚本会使用 `examples/demo_task_shared.py` 里的 debug 注入函数，通过 `/debug/*` 推进协同流程。

### 4.3 两终端任务流

`examples/demo_task_initiator.py` 和 `examples/demo_task_collaborator.py` 分别在两个终端运行。

- 协作方先启动，再启动发起方
- 两个脚本默认共享同一个 runtime 目录，用于交换 `collaborator.ready`、`task_id`、`shutdown.signal`
- 如果需要隔离运行目录，可以通过 `--runtime-root` 和 `--session-name` 覆盖默认值

### 4.4 Realtime Demo

`examples/demo_task_flow_realtime.py` 是单进程 realtime 版，不再使用 `/debug/*` 注入中间消息，而是等待真实 `TASK_REQUEST_COLLABORATION`、`DISCOVER_RESULT`、`START_TASK` 和 `SUBSCRIBE_TRACK` 消息流入。

`examples/demo_task_initiator_realtime.py` 和 `examples/demo_task_collaborator_realtime.py` 则把同一套 realtime 流程拆成两个终端入口：

- 仍然共享 session 目录用于协调启动与收尾
- 不再使用 `/debug/*` 注入中间消息
- 适合接真实 AgentGW / ARF / MOQ 组件

## 5. PyCharm 调试方式

1. 打开工程根目录。
2. 配置项目解释器为 Python 3.10+。
3. 安装 `requirements.txt`，并执行 `pip install -e .`。
4. 增加 mock 服务运行配置：

```text
Script path: scripts/start_mock_services.sh
Parameters: none
Working directory: 项目根目录
```

```text
Script path: mock/start_mock_services.py
Parameters: none
Working directory: 项目根目录
```

5. 增加示例运行配置：

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

6. 如果未执行 `pip install -e .`，需要把项目根目录标记为 `Sources Root`，否则 `from acn_sdk import ...` 无法导入。

7. 调试顺序保持为：先启动四个 mock 服务，再启动示例或 `pytest`。

## 6. 当前配置说明

`acn_sdk/config/config.yaml` 是运行时优先读取的配置源，默认包含以下信息：

- `network_ip=127.0.0.1`
- `acn_agent_port=9010`
- `arf_port=9001`
- `agent_gw_ws_port=9002`
- `agent_gw_moq_port=9003`
- `web_ui_port=9004`

修改 YAML 后，如需让已启动的 SDK 立即生效，调用 `sdk.reload_config()` 即可。

## 7. 当前功能校验

接口返回约定：

- `AcnSDK` 对外公共接口统一返回 `tuple[bool, str]`
- 第一个元素固定为 `bool` 型 `result`
- 成功时第二个元素为业务结果，失败时通常返回错误信息

本地验证命令：

```bash
pytest -q
```
