# ACN Android Light SDK + Python Gateway

本工程实现“Android 只触发操作，所有 ACN 能力由 Python Gateway 执行”的方案。

```text
Android App
  -> 7 个无业务参数 HTTP 调用
Python Gateway
  -> Python AcnSDK / callbacks / WebSocket / MoQ
ACN Agent / ARF / AgentGW / MoQ Relay
```

Android 不保存 `agent_id`、`task_id`、身份密钥或业务配置，也不建立 ACN WebSocket/MoQ 连接。Gateway 是实际 ACN Agent，Android 只是控制端。

完整设计、部署关系、接口映射、状态流转、密钥和日志位置见 [IMT2030测试用例ACN_SDK设计文档.md](/home/acn/zxy/imt/acn-sdk-android-light/IMT2030测试用例ACN_SDK设计文档.md)。

## 1. 修改配置

复制配置示例：

```bash
cp gateway/config.example.yaml gateway/config.yaml
```

如果已经进入 `gateway` 目录，则执行：

```bash
cp config.example.yaml config.yaml
```

日常使用只需要修改复制后的 `gateway/config.yaml`；完整字段可参考 [config.example.yaml](gateway/config.example.yaml)：

- `python_sdk.source_path`：Python SDK 路径；
- `python_sdk.network`：ACN、ARF、AgentGW、MoQ、Web UI 地址和端口；
- `agent`：身份注册信息；
- `capabilities`：能力列表；
- `task.task_id`：固定任务 ID，Android 执行任务时不传，由 Gateway 使用该值；
- `task`：任务、协同和广播结束参数；
- `deregister.reason`：去注册原因；
- `callbacks.fetch_tracks`：需要使用 `fetch` 的 MoQ track，其余默认 `subscribe`。

`owner` 必须是 6～20 位数字，可带 `+` 前缀。Gateway 会在 `python_sdk.runtime_dir` 下自动生成 Python SDK 配置、身份文件、密钥和日志。

推荐新主机部署目录如下，`gateway` 和原版 Python SDK `acn_sdk` 保持同级：

```text
acn-gateway-deploy/
├── acn_sdk/
└── gateway/
    ├── acn_gateway/
    ├── config.yaml
    ├── requirements.txt
    └── start_gateway.sh
```

这种目录下，`gateway/config.yaml` 里保持：

```yaml
python_sdk:
  source_path: ../acn_sdk
  runtime_dir: ./runtime
```

路径填写时重点检查这几处：

- `gateway/config.yaml` 的 `python_sdk.source_path`：原版 Python SDK 源码路径；同级部署时填 `../acn_sdk`。
- `gateway/config.yaml` 的 `python_sdk.runtime_dir`：Gateway 运行时目录；默认 `./runtime`，会解析到 `gateway/runtime`。
- `gateway/config.yaml` 的 `python_sdk.network.network_ip`：ACN 网络组件地址；组件和 Gateway 在同一台主机时可填 `localhost`，否则填实际 IP。
- `gateway/config.yaml` 的 `task.task_id`：固定任务 ID；如需换任务 ID，只改这里。
- Android 里的 `GatewayConfig(baseUrl = "...")`：填写 Gateway 主机对 Android 可访问的 IP 和端口，例如 `http://192.168.1.10:9011`。
- `gateway/requirements.txt` 的 `-e ../acn_sdk`：和上面的同级部署结构匹配；如果 Python SDK 放到别处，这里也要同步修改。

## 2. 启动 Gateway

在推荐目录结构下，进入 `gateway` 目录安装依赖并启动：

```bash
cd gateway
python3 -m pip install -r requirements.txt
chmod +x start_gateway.sh
./start_gateway.sh
```

也可以指定配置：

```bash
./start_gateway.sh /absolute/path/to/config.yaml
```

如果在工程根目录启动，也可以使用兼容入口：

```bash
./gateway/start_gateway.sh
```

默认监听 `0.0.0.0:9011`。验证：

```bash
curl http://127.0.0.1:9011/health
```

## 3. Gateway 接口

所有 POST 请求都不需要请求参数：

| 顺序 | 接口 | Python SDK 映射 |
|---|---|---|
| 1 | `POST /sdk/register-identity` | `register_agent_info()` |
| 2 | `POST /sdk/register-capabilities` | `register_agent_attribute()` |
| 3 | `POST /sdk/join-network` | `join_network()` |
| 4 | `POST /sdk/execute-task` | `request_task_execution()` |
| 5 | `POST /sdk/broadcast-terminate-task` | `broadcast_terminate_task()` |
| 6 | `POST /sdk/logout-network` | `logout_network()` |
| 7 | `POST /sdk/deregister` | `deregister_agent()` |

状态查询为 `GET /sdk/status`。所有响应格式一致：

```json
{
  "result": true,
  "message": "",
  "data": {"task_id": "task-001"},
  "state": {
    "agent_id": "did:acn:agent:001",
    "current_task_id": "task-001",
    "network_status": "online",
    "task_status": "processing"
  }
}
```

广播结束接口成功表示广播已发出，此时 `task_status` 为 `terminating`。Python Gateway 收到 `TASK_TERMINATION` 后会自动调用 `request_terminate_task()` 清理本地任务，并切换为 `terminated`；之后才能退出网络。

## 4. Android 集成

将 `:acn-sdk` 作为本地 module 引入 App，然后创建客户端。Android 仅需要配置 Gateway 地址：

```kotlin
val acnSdk = AcnSdk(
    GatewayConfig(baseUrl = "http://192.168.1.10:9011")
)
```

该 Android module 没有 OkHttp、WebSocket、MoQ、协程库或 JSON 库等第三方运行依赖；网络和 JSON 使用 Android 平台 API，7 个挂起函数会自动在线程池中执行 HTTP。

按操作调用：

```kotlin
lifecycleScope.launch {
    acnSdk.registerIdentity().requireSuccess()
    acnSdk.registerCapabilities().requireSuccess()
    acnSdk.joinNetwork().requireSuccess()
    acnSdk.executeTask().requireSuccess()

    // 需要结束时调用；等 Python 回调完成后再触发 logout。
    acnSdk.broadcastTerminateTask().requireSuccess()
}
```

退出及去注册：

```kotlin
lifecycleScope.launch {
    acnSdk.logoutNetwork().requireSuccess()
    acnSdk.deregister().requireSuccess()
}
```

若使用局域网 HTTP，宿主 App 需要允许明文流量；推荐仅在联调环境中使用：

```xml
<application android:usesCleartextTraffic="true" />
```

生产环境应为 Gateway 配置 HTTPS 和访问鉴权。

## 5. 测试和构建

Gateway：

```bash
cd gateway
pytest
```

Android：

```bash
./gradlew :acn-sdk:assembleDebug
```

生成的 AAR 位于 `acn-sdk/build/outputs/aar/acn-sdk-debug.aar`。
