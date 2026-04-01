# 接口 API 文档

## 1. AcnSDK 公共接口

返回值约定：

- `AcnSDK` 对机器人暴露的公共接口统一返回 `tuple[bool, str]`
- 第一个元素固定为 `result`，类型为 `bool`
- `True` 时，第二个元素为业务结果字符串，复杂结果通常用 JSON 字符串编码
- `False` 时，第二个元素为错误信息字符串

包结构：

```text
acn_sdk.sdk.AcnSDK
acn_sdk.identity.identity_manager.IdentityManager
acn_sdk.network.http_client.HttpClient
acn_sdk.network.websocket_client.WebSocketClient
acn_sdk.network.moq_client.MoQClient
acn_sdk.credential.credential_issuer.CredentialIssuer
acn_sdk.task.task_manager.TaskManager
```

### `AcnSDK.__init__(robot_name: str, issuer_id: str = "did:huaweiissuer@6gc.mnc015.mcc234.3gppnetwork", config_path: str | Path = "config/config.yaml")`

初始化 SDK，完成以下动作：

- 保存 `robot_name`
- 自动加载 `config/config.yaml`
- 初始化 `IdentityManager`、`HttpClient`、`CredentialIssuer`
- 将 `WebSocketClient`、`moq_pub_client`、`moq_sub_client`、`TaskManager` 初值设为 `None`
- 设置网络状态为 `OFFLINE`
- 若本地不存在密钥，则自动生成并保存
- `issuer_id` 目前保留为兼容参数；能力 VC 的实际发放者已改为按能力名称自动选择
- 可通过 `config_path` 参数指定其他 YAML 配置文件；运行中修改 YAML 后可调用 `reload_config()` 重新加载

### `register_callbacks(...) -> tuple[bool, str]`

注册业务侧回调。

支持的回调包括：

- `on_task_collaboration_request(payload)`：收到 `TASK_REQUEST_COLLABORATION` 时触发
- `on_discover_result_received(payload)`：收到 `DISCOVER_RESULT` 时触发，通常在回调里调用 `start_task_collaboration()`
- `on_task_start_command(payload)`：收到 `START_TASK` 时触发
- `on_moq_message_received(namespace, track, payload)`：收到 MOQ 订阅对象时触发
- `on_message_received(message_type, payload)`：保留的通用回调，继续兼容旧用法

未注册对应回调时，SDK 会跳过对应处理，仅保留通用回调行为。

### `reload_config() -> tuple[bool, str]`

重新读取 `config/config.yaml`（或 `config_path` 指定的文件），并刷新以下依赖：

- 日志级别与日志目录
- `IdentityManager`
- `HttpClient`
- 本地密钥文件路径

如果当前已经连接了网络组件，`reload_config()` 会先断开现有连接，再按新配置重新初始化运行环境。

### `register_agent_info(robot_info: RobotInfo) -> tuple[bool, str]`

向 `AcnAgent` 提交数字身份申请，返回 `agent_id`。

请求路径：

```text
POST /idm/v1/identity-applications
```

请求体示例：

```json
{
  "owner": "+8613800138000",
  "name": "AliceAgent",
  "public_key": "-----BEGIN PUBLIC KEY----- ...",
  "description": "AgentModel-X, SN123456",
  "timestamp": "2026-03-27T10:00:00Z",
  "signature": "base64-signature",
  "signature_encoding": "base64",
  "metadata": {
    "region": "CN",
    "os": "Linux",
    "version": "1.0.0"
  }
}
```

返回值：

- 成功：`(True, agent_id)`
- 失败：`(False, error_message)`

副作用：

- `IdentityManager` 保存 `agent_id`、`vc0`、机器人信息
- `signature` 仅基于 `timestamp` 生成，编码采用 `base64`

### `register_agent_attribute(agent_id: str, capability: list[str]) -> tuple[bool, str]`

先由 `CredentialIssuer` 按 `capability` 列表逐项模拟签发能力 VC，再向 `AcnAgent` 注册能力信息。

请求路径：

```text
POST /arf/v1/agent-cards
```

说明：

- SDK 通过 `AcnAgent` 的 HTTP 入口发起请求，表面路径仍然是 `/arf/v1/agent-cards`，由 `AcnAgent` 转发到 `ARF`。
- 原始需求中出现 `agent—cards`，其中连接符疑似排版字符；工程中统一采用标准路径 `/arf/v1/agent-cards`。
- 调用前会校验传入的 `agent_id` 必须与本机已注册身份一致，否则直接抛出 `ValueError`
- 当前请求体包含 `agent_id`、`timestamp`、`signature`、`signature_encoding`、`vc_list`
- `signature` 仅基于 `timestamp` 生成，编码采用 `base64`
- `vc_list` 中第一个元素为 `vc0`，后续元素为全部能力 VC
- 当前能力 VC 使用 `BindingSIMCredential`，签名按能力名称自动分流：`可疑人员识别` 和 `目标跟踪` 使用华为发放者及 `Huawei_private_key.pem`，其他能力使用 RobotFactory 发放者及 `Robot_Factory_private_key.pem`

请求体示例：

```json
{
  "agent_id": "did:acn:agent:987654321",
  "timestamp": "2026-03-27T10:00:00Z",
  "signature": "base64-signature",
  "signature_encoding": "base64",
  "vc_list": [
    {
      "context": ["3gpp-ts-33.xxx-v20.0.0"],
      "id": "CMCC/credentials/3732",
      "type": ["VerifiableCredential", "BindingSIMCredential"],
      "issuer": "did:robotfactoryissuer@6gc.mnc015.mcc234.3gppnetwork",
      "valid_from": "2026-03-27T10:00:00+00:00",
      "valid_until": "2027-03-27T10:00:00+00:00",
      "claims": {
        "agent_name": "AliceAgent",
        "agent_id": "did:acn:agent:987654321",
        "agent_attribute": "运营商颁发，Agent与主UE的绑定关系，用于对外出示，审计确权",
        "master_id": "type0.master.mock@3gppnetwork.org",
        "self_id": "type0.self.mock@3gppnetwork.org"
      },
      "proof": {
        "creator": "did:robotfactoryissuer@6gc.mnc015.mcc234.3gppnetwork#keys-1",
        "signature_value": "mock-proof-signature"
      }
    },
    {
      "context": ["3gpp-ts-33.xxx-v20.0.0"],
      "id": "huawei/credentials/3737",
      "type": ["VerifiableCredential", "BindingSIMCredential"],
      "issuer": "did:huaweiissuer@6gc.mnc015.mcc234.3gppnetwork",
      "valid_from": "2026-03-27T10:00:00+00:00",
      "valid_until": "2027-03-27T10:00:00+00:00",
      "claims": {
        "agent_name": "AliceAgent",
        "agent_id": "did:acn:agent:987654321",
        "agent_attribute": "pick",
        "authorization_mode": "Mode2"
      },
      "proof": {
        "creator": "did:huaweiissuer@6gc.mnc015.mcc234.3gppnetwork#keys-1",
        "signature_value": "base64-ecdsa-signature"
      }
    }
  ]
}
```

### `query_robot_id(robot_name: str, owner: str) -> tuple[bool, str]`

本地查询当前设备保存的身份信息，命中则返回 `(True, agent_id)`，未命中返回 `(False, None)`。

### `deregister_robot(agent_id: str, reason: str) -> tuple[bool, str]`

请求去注册。只有传入的 `agent_id` 与本机一致时才允许执行。

请求路径：

```text
POST /acn-agent/v1/agent-deletions
```

成功后：

- 清空本地 `agent_id`、`vc0`、`capability_vcs`
- 关闭 HTTP/WebSocket/MoQ 连接
- 停止全部任务
- `signature` 仅基于 `timestamp` 生成，编码采用 `base64`

### `join_network(agent_id: str) -> tuple[bool, str]`

入网认证入口。

行为：

- 校验 `agent_id` 必须与本机已注册身份一致
- 创建 `WebSocketClient`，连接 `ws://<network_ip>:<agent_gw_ws_port><path>`
- 发送 `SETUP` 消息，必须收到对端 `SETUP` 且 `payload.status == "OK"`
- 初始化 `moq_pub_client`、`moq_sub_client`、`TaskManager`
- 成功入网后自动启动后台 WebSocket 监听线程，后续下行消息默认自动处理
- 全部成功后将状态切换为 `ONLINE`

返回示例：

```python
(True, "did:acn:agent:987654321")
```

### `logout_network(agent_id: str) -> tuple[bool, str]`

主动退网。

行为：

- 发送 `DISCONNECTION`
- 断开 WebSocket / MoQ / TaskManager
- 状态切换回 `OFFLINE`

### `request_task_execution(agent_id: str, task_info: str, task_id: str | None = None) -> tuple[bool, str]`

任务执行请求。

请求路径：

```text
POST /acn-agent/v1/task-executions
```

说明：

- 仅允许在 `ONLINE` 状态调用
- 若未传 `task_id`，SDK 自动生成 `task-xxxxx`
- 成功时返回 `(True, task_id)`
- 失败时返回 `(False, error_message)`

### `request_terminate_task(agent_id: str, task_id: str, reason: str = "", force: bool = False) -> tuple[bool, str]`

任务终止请求。

请求路径：

```text
POST /acn-agent/v1/task-execution-terminations
```

### `task_info_report(agent_id: str, task_id: str, topic: str, message_info: bytes) -> tuple[bool, str]`

任务信息上报。

行为：

- 仅允许在 `ONLINE` 状态调用
- 自动拼装 `namespace=/{task_id}/{agent_id}`
- 若该 `namespace + track` 首次发布，则先执行 MOQ `publish`
- 首次发布后发送 WebSocket `PUBLISH_TRACK`
- 然后执行 MOQ `send_object`
- 当前实现默认使用 MOQ datagram 发送对象，便于本地 relay 联调

### `request_task_collaboration(agent_id: str, task_id: str, required_capabilities: str | list[str]) -> tuple[bool, str]`

请求协同智能体。

请求路径：

```text
POST /arf/v1/agent-discoveries
```

说明：

- SDK 通过 `AcnAgent` 的 HTTP 入口发起请求，表面路径仍然是 `/arf/v1/agent-discoveries`，由 `AcnAgent` 转发到 `ARF`。

### `accept_task_collaboration(agent_id: str, task_id: str, dst_agent_id: str | None = None) -> tuple[bool, str]`

接受协同任务，请求体通过 WebSocket 发送 `TASK_ACCEPT_COLLABORATION`。

- `dst_agent_id` 为空时，SDK 会优先使用最近一次 `TASK_REQUEST_COLLABORATION` 中的 `src_agent_id`。

### `start_task_collaboration(agent_id: str, dst_agent_id: str, task_id: str, task_description: str) -> tuple[bool, str]`

发送 WebSocket `START_TASK`，用于通知协作方开始执行任务。

### `handle_network_message(message: str | dict[str, Any]) -> tuple[bool, str]`

处理服务端下发的 WebSocket 消息。

当前支持：

- `SUBSCRIBE_TRACK`：触发本地 MOQ 订阅
- `CLEAR`：清空本地任务、发布和订阅缓存
- `TASK_REQUEST_COLLABORATION`：触发 `on_task_collaboration_request(payload)` 回调
- `DISCOVER_RESULT`：触发 `on_discover_result_received(payload)` 回调
- `START_TASK`：触发 `on_task_start_command(payload)` 回调
- 其他消息类型：透传给初始化时注册的 `on_message_received(message_type, payload)` 回调

### `connect_network() -> tuple[bool, str]`

保留的轻量连接方法，只做本地网络组件初始化，不执行 WebSocket `SETUP` 握手。更推荐使用 `join_network()`。

### `disconnect_all(close_http: bool = True) -> tuple[bool, str]`

断开所有网络连接、停止任务，并把状态切回 `OFFLINE`。

## 2. 配置文件

文件路径：

```text
config/config.yaml
```

说明：

- `config.py` 只定义配置模型和默认值
- `config/config.yaml` 是运行时优先读取的配置源
- 修改 YAML 后，如需让已启动的 SDK 立即生效，调用 `reload_config()`
- 如果要切换部署环境，只需要改 YAML，不需要改 `acn_sdk/config.py`

字段说明：

- `network.network_ip`：网端 IP
- `network.acn_agent_port`：AcnAgent HTTP 端口
- `network.agent_gw_ws_port`：AgentGW WebSocket 端口
- `network.agent_gw_moq_port`：AgentGW MoQ 端口
- `network.web_ui_port`：Web UI 端口
- `network.path`：AgentGW WebSocket 路径
- `storage.identity_file`：身份状态文件
- `storage.private_key_file`：私钥文件
- `storage.public_key_file`：公钥文件
- `storage.log_dir`：日志目录
- `log_level`：日志级别

## 3. 启动与执行方式

命令行运行：

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
pytest
```

推荐执行顺序：

1. `pip install -r requirements.txt`
2. `pip install -e .`
3. `python3 mock/mock_acn_agent.py --host 127.0.0.1 --port 9010`
4. `python3 mock/mock_arf.py --host 127.0.0.1 --port 9001`
5. `python3 mock/mock_agent_gw.py --host 127.0.0.1 --port 9002`
6. `python3 mock/mock_moq_relay.py --host 127.0.0.1 --port 9003 --cache-dir data/moq-relay-cache`
7. `python3 examples/demo_identity_flow.py`
8. `python3 examples/demo_task_flow.py`
9. `pytest -q`

`demo_task_flow.py` 的当前校验目标：

- `AliceAgent` 和 `RobotDog` 分别完成注册与入网
- `RobotDog` 通过 WebSocket 收到协同消息
- `RobotDog` 通过真实 MOQ relay 收到 `Location` 对象，回调类型为 `MOQ_OBJECT`

PyCharm 调测：

1. 打开项目根目录。
2. 解释器选择 Python 3.10+。
3. 安装 `requirements.txt`，并执行 `pip install -e .`。
4. 创建 `python mock/mock_acn_agent.py --host 127.0.0.1 --port 9010` 配置。
5. 创建 `examples/demo_identity_flow.py` 配置。
6. 先启动 mock 服务，再启动示例或测试。
7. 如果你修改了 `config/config.yaml`，在调试会话里直接调用 `sdk.reload_config()` 即可重新读取配置。

如未执行 `pip install -e .`，则需要将项目根目录标记为 `Sources Root`。

## 4. Mock AcnAgent API

### `POST /idm/v1/identity-applications`

返回：

- `result`
- `agent_id`
- `vc0`

### `POST /arf/v1/agent-cards`

返回：

- `result`
- `message`
- `agent_id`
- `capabilities`

### `POST /acn-agent/v1/agent-deletions`

返回：

- `result`
- `message`
- `agent_id`
- `reason`
