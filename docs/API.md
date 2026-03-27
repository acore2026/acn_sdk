# 接口 API 文档

## 1. AcnSDK 公共接口

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

### `AcnSDK.__init__(robot_name: str)`

初始化 SDK，完成以下动作：

- 保存 `robot_name`
- 自动加载 `config/config.yaml`
- 初始化 `IdentityManager`、`HttpClient`、`CredentialIssuer`
- 将 `WebSocketClient`、`moq_pub_client`、`moq_sub_client`、`TaskManager` 初值设为 `None`
- 设置网络状态为 `OFFLINE`
- 若本地不存在密钥，则自动生成并保存

### `register_robot_info(robot_info: RobotInfo) -> str`

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
  "priority": 5,
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

- `agent_id`

副作用：

- `IdentityManager` 保存 `agent_id`、`vc0`、机器人信息

### `register_agent_attribute(capability: list[str]) -> dict[str, Any]`

先由 `CredentialIssuer` 模拟签发能力 VC，再向 `AcnAgent` 注册能力信息。

请求路径：

```text
POST /arf/v1/agent-cards
```

说明：

- 原始需求中出现 `agent—cards`，其中连接符疑似排版字符；工程中统一采用标准路径 `/arf/v1/agent-cards`。

### `query_robot_id(robot_name: str, owner: str) -> str | None`

本地查询当前设备保存的身份信息，命中则返回 `agent_id`。

### `deregister_robot(agent_id: str, reason: str) -> dict[str, Any]`

请求去注册。只有传入的 `agent_id` 与本机一致时才允许执行。

请求路径：

```text
POST /acn-agent/v1/agent-deletions
```

成功后：

- 清空本地 `agent_id`、`vc0`、`capability_vc`
- 关闭 HTTP/WebSocket/MoQ 连接
- 停止全部任务

### `connect_network() -> None`

初始化 `WebSocketClient`、`moq_pub_client`、`moq_sub_client`、`TaskManager`，并把状态切到 `ONLINE`。

### `disconnect_all() -> None`

断开所有网络连接、停止任务，并把状态切回 `OFFLINE`。

## 2. 配置文件

文件路径：

```text
config/config.yaml
```

字段说明：

- `sdk.http_port`：AcnSDK 本地 HTTP 端口
- `sdk.ws_port`：AcnSDK 本地 WebSocket 端口
- `sdk.moq_pub_port`：AcnSDK 本地 MoQ 发布端口
- `sdk.moq_sub_port`：AcnSDK 本地 MoQ 订阅端口
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
uvicorn app.mock_acn_agent:app --host 127.0.0.1 --port 9010
python examples/demo_identity_flow.py
pytest
```

PyCharm 调测：

1. 打开项目根目录。
2. 解释器选择 Python 3.10+。
3. 安装 `requirements.txt`。
4. 创建 `uvicorn app.mock_acn_agent:app --host 127.0.0.1 --port 9010` 配置。
5. 创建 `examples/demo_identity_flow.py` 配置。
6. 先启动 mock 服务，再启动示例或测试。

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
