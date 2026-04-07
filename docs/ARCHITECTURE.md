# 系统架构与模块设计

## 1. 总体说明

本工程只实现机器人端 `AcnSDK`，通过 HTTP 与核心网侧 `AcnAgent` 和 `ARF` 通信，通过 WebSocket 与 `AgentGW` 交互，通过 MOQ 与 relay 传输任务数据；当前工程提供 `mock_acn_agent`、`mock_arf`、`mock_agent_gw`、`mock_moq_relay` 四个本地测试桩，便于联调注册、入网、任务协同和对象转发链路。

## 2. 模块划分

目录分层如下：

```text
acn_sdk/
├── sdk.py
├── config.py
├── models.py
├── crypto.py
├── logging_config.py
├── identity/
├── network/
├── credential/
└── task/
```

- `AcnSDK`：主入口，编排身份申请、能力注册、查询、去注册、网络状态切换。
- `identity/IdentityManager`：本地身份状态持久化，保存 `agent_id`、`vc0`、`capability_vcs`、机器人基础信息。
- `credential/CredentialIssuer`：模拟第三方能力凭证签发。
- `network/HttpClient`：统一发送 HTTP 请求，记录请求与响应日志。
- `network/WebSocketClient`：预留与 `AgentGW` 的长连接通信能力。
- `network/MoQClient`：基于 `moq.pub.MOQPublisher` / `moq.sub.MOQSubscriber` 的 track 发布、订阅与对象回调入口。
- `task/TaskManager`：统一管理后台任务生命周期。
- `config.py`：定义 `SDKConfig` / `NetworkConfig` / `StorageConfig` 数据模型与默认值。
- `config/config.yaml`：运行时优先读取的配置文件，修改后可通过 `AcnSDK.reload_config()` 重新加载。
- `mock_acn_agent`：FastAPI 打桩服务，承载身份注册、任务执行、终止任务和去注册接口。
- `mock_arf`：FastAPI 打桩服务，承载能力注册和协同发现接口。

## 3. 核心流程时序图

```mermaid
sequenceDiagram
    participant Robot as Robot App
    participant SDK as AcnSDK
    participant ID as IdentityManager
    participant HTTP as HttpClient
    participant Agent as Mock AcnAgent
    participant ARF as Mock ARF
    participant GW as Mock AgentGW
    participant Relay as Mock MOQ Relay
    participant Issuer as CredentialIssuer

    Robot->>SDK: register_agent_info(AgentInfo)
    SDK->>SDK: 生成 timestamp / signature
    SDK->>HTTP: POST /idm/v1/identity-applications
    HTTP->>Agent: 发送身份申请
    Agent-->>HTTP: agent_id + vc0
    HTTP-->>SDK: 响应
    SDK->>ID: 保存 agent_id / vc0
    SDK-->>Robot: agent_id

    Robot->>SDK: register_agent_attribute(agent_id, capabilities)
    SDK->>Issuer: fetch_capacity_vc(agent_id, capabilities)
    Issuer-->>SDK: capability_vcs
    SDK->>ID: 保存 capability_vcs
    SDK->>HTTP: POST /arf/v1/agent-cards
    HTTP->>Agent: 转发到 ARF
    Agent->>ARF: 注册能力
    ARF-->>Agent: success
    Agent-->>HTTP: success
    HTTP-->>SDK: success

    Robot->>SDK: join_network(agent_id)
    SDK->>GW: WebSocket SETUP
    GW-->>SDK: SETUP/OK
    SDK->>SDK: 初始化 MoQ pub/sub
    SDK-->>Robot: online

    Robot->>SDK: request_task_execution(agent_id, task_info)
    SDK->>HTTP: POST /acn-agent/v1/task-executions
    HTTP->>Agent: 请求执行任务
    Agent-->>HTTP: success
    HTTP-->>SDK: task_id

    GW-->>SDK: TASK_REQUEST_COLLABORATION / START_TASK / SUBSCRIBE_TRACK
    SDK->>Robot: 回调通知业务侧
    Robot->>SDK: accept_task_collaboration / task_info_report
    SDK->>GW: WebSocket TASK_ACCEPT_COLLABORATION / PUBLISH_TRACK
    SDK->>Relay: MOQ publish / send_object
    Relay-->>SDK: MOQ object forwarding

    Robot->>SDK: deregister_agent(agent_id, reason)
    SDK->>HTTP: POST /acn-agent/v1/agent-deletions
    HTTP->>Agent: 去注册
    Agent-->>HTTP: success
    HTTP-->>SDK: success
    SDK->>ID: clear()
    SDK->>SDK: 断开连接 / 停止任务
```

## 4. 用例图

```mermaid
flowchart LR
    Robot[机器人应用] --> U1[申请数字身份]
    Robot --> U2[注册能力属性]
    Robot --> U3[查询数字身份]
    Robot --> U4[去注册]
    Robot --> U5[连接网络]
```

## 5. 状态设计

- 初始状态：`offline`
- 连接网络后：`online`
- 去注册或断开连接后：`offline`
- 任务上报前提：必须 `online`

状态切换均通过 `logging` 输出。

## 6. 配置设计

- `config.py` 只负责配置结构与默认值，不作为运行时配置入口。
- `config/config.yaml` 是当前工程的运行时配置源。
- 启动时优先读取 `config/config.yaml`，运行中需要热更新时调用 `AcnSDK.reload_config()`。

## 7. 扩展设计

- `HttpClient` 可替换为重试版、鉴权版、异步版。
- `IdentityManager` 可扩展为 SQLite 或加密存储。
- `CredentialIssuer` 未来可改为真实第三方服务调用。
- `mock_agent_gw` 当前负责 WebSocket 控制面联调和调试消息下发，不承担真实路由或鉴权能力。
- `mock_moq_relay` 基于 `moq.relay.MOQRelay` 运行，当前已可用于本地真实 QUIC/MOQ 对象转发验证。
- `TaskManager` 已抽象出统一任务入口，便于扩展心跳、订阅、重连任务。
