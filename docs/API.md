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

### `AcnSDK.__init__(robot_name: str, issuer_id: str = "did:huaweiissuer@6gc.mnc015.mcc234.3gppnetwork", config_path: str | Path = "config/config.yaml")`

初始化 SDK，完成以下动作：

- 保存 `robot_name`
- 自动加载 `config/config.yaml`
- 初始化 `IdentityManager`、`HttpClient`、`CredentialIssuer`
- 将 `WebSocketClient`、`moq_pub_client`、`moq_sub_client`、`TaskManager` 初值设为 `None`
- 设置网络状态为 `OFFLINE`
- 若本地不存在密钥，则自动生成并保存
- `issuer_id` 用于选择能力 VC 的发放者；默认使用华为发放者，也可传入 RobotFactory 对应的发放者标识
- 可通过 `config_path` 参数指定其他 YAML 配置文件；运行中修改 YAML 后可调用 `reload_config()` 重新加载

### `reload_config() -> None`

重新读取 `config/config.yaml`（或 `config_path` 指定的文件），并刷新以下依赖：

- 日志级别与日志目录
- `IdentityManager`
- `HttpClient`
- 本地密钥文件路径

如果当前已经连接了网络组件，`reload_config()` 会先断开现有连接，再按新配置重新初始化运行环境。

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
- `signature` 仅基于 `timestamp` 生成，编码采用 `base64`

### `register_agent_attribute(capability: list[str]) -> dict[str, Any]`

先由 `CredentialIssuer` 按 `capability` 列表逐项模拟签发能力 VC，再向 `AcnAgent` 注册能力信息。

请求路径：

```text
POST /arf/v1/agent-cards
```

说明：

- 原始需求中出现 `agent—cards`，其中连接符疑似排版字符；工程中统一采用标准路径 `/arf/v1/agent-cards`。
- 当前请求体只包含 `agent_id`、`timestamp`、`signature`、`signature_encoding`、`vc_list`
- `signature` 仅基于 `timestamp` 生成，编码采用 `base64`
- `vc_list` 中第一个元素为 `vc0`，后续元素为全部能力 VC
- 当前能力 VC 使用 `BindingSIMCredential`，签名按发放者私钥生成：华为发放者使用 `Huawei_private_key.pem`，RobotFactory 发放者使用 `Robot_Factory_private_key.pem`

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
      "issuer": "did:udid:NewTypeOperator.rid678@6gc.mnc015.mcc234.3gppnetwork",
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
        "creator": "did:udid:NewTypeOperator.rid678@6gc.mnc015.mcc234.3gppnetwork#keys-1",
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

### `query_robot_id(robot_name: str, owner: str) -> str | None`

本地查询当前设备保存的身份信息，命中则返回 `agent_id`。

### `deregister_robot(agent_id: str, reason: str) -> dict[str, Any]`

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

### `connect_network() -> None`

初始化 `WebSocketClient`、`moq_pub_client`、`moq_sub_client`、`TaskManager`，并把状态切到 `ONLINE`。

### `disconnect_all() -> None`

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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
uvicorn app.mock_acn_agent:app --host 127.0.0.1 --port 9010
python3 examples/demo_identity_flow.py
pytest
```

推荐执行顺序：

1. `pip install -r requirements.txt`
2. `pip install -e .`
3. `uvicorn app.mock_acn_agent:app --host 127.0.0.1 --port 9010`
4. `python3 examples/demo_identity_flow.py`
5. `pytest -q`

PyCharm 调测：

1. 打开项目根目录。
2. 解释器选择 Python 3.10+。
3. 安装 `requirements.txt`，并执行 `pip install -e .`。
4. 创建 `uvicorn app.mock_acn_agent:app --host 127.0.0.1 --port 9010` 配置。
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
