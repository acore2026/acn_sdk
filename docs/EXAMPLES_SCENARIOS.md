# ACM SDK 自测试设计
## 1. 场景总览

| 场景族 | 覆盖重点 | 相关脚本 |
| --- | --- | --- |
| 身份生命周期 | 身份申请、能力注册去重、本地查询、去注册 | `demo_identity_flow.py` |
| 单进程双 Agent | 一个进程内跑 initiator + collaborator，验证完整任务协同和 MoQ 数据流 | `demo_task_flow.py`, `demo_task_flow_realtime.py` |
| 双终端基础协同 | initiator/collaborator 分别运行，共享 runtime 目录或直接实时等待 | `demo_task_initiator.py`, `demo_task_collaborator.py`, `demo_task_initiator_realtime.py`, `demo_task_collaborator_realtime.py`, `demo_task_initiator_rt.py`, `demo_task_collaborator_rt.py` |
| 最新订阅 / fetch 策略 | `on_subscribe_track_received` 按 track 选择 `fetch` 或 `subscribe` | `demo_task_initiator_rt_latest.py`, `demo_task_collaborator_rt_latest.py`, `demo_task_initiator_rt_latest_single_device.py`, `demo_task_collaborator_rt_latest_single_device.py` |
| 广播终止 | 通过 `broadcast_terminate_task()` 通知参与方终止任务 | `demo_task_initiator_broadcast_rt.py`, `demo_task_collaborator_broadcast_rt.py`, `demo_task_initiator_broadcast_rt_t1.py`, `demo_task_collaborator_broadcast_rt_t1.py` |
| 两个协作者 | 同一任务先后拉起两个不同能力的协作者 | `demo_task_initiator_broadcast_rt_t2.py`, `demo_task_collaborator1_broadcast_rt_t2.py`, `demo_task_collaborator2_broadcast_rt_t2.py` |
| 三级协同链 | A 发起任务，B 加入后再请求 C 加入，形成 A -> B -> C 链路 | `demo_task_agent_a_broadcast_rt_t3.py`, `demo_task_agent_b_broadcast_rt_t3.py`, `demo_task_agent_c_broadcast_rt_t3.py` |
| 三级协同 + fetch 回调 | 三级链路基础上验证订阅回调选择 `fetch` | `demo_task_agent_a_broadcast_rt_t3_subscribe_callback.py`, `demo_task_agent_b_broadcast_rt_t3_subscribe_callback.py`, `demo_task_agent_c_broadcast_rt_t3_subscribe_callback.py` |
| 三级协同 + 双 track | A 发布 `Position` 和 `Status` 两个 track，B/C 对不同 track 使用不同策略 | `demo_task_agent_a_broadcast_rt_t3_two_tracks_subscribe_callback.py`, `demo_task_agent_b_broadcast_rt_t3_two_tracks_subscribe_callback.py`, `demo_task_agent_c_broadcast_rt_t3_two_tracks_subscribe_callback.py` |
| 共享辅助脚本 | runtime 目录、独立配置、debug 消息注入、持续上报工具 | `demo_task_shared.py` |

## 2. 基础身份场景

### `demo_identity_flow.py`

角色：单个 `AliceAgent`。

覆盖流程：

1. `register_agent_info()` 申请数字身份。
2. `register_agent_attribute()` 注册 `可疑人员识别`、`目标跟踪`、`声光驱离`。
3. 第二次能力注册传入 `目标跟踪`、`无人机侦测`，验证已有能力去重和新增能力追加。
4. `query_agent_id()` 查询本地身份。
5. `deregister_agent()` 去注册并清理身份。

主要验证点：

- `agent_id` 生成和保存。
- `vc0` + 能力 VC 组合注册。
- 重复能力不会重复签发。
- 去注册后本地身份被清理。

## 3. 单进程双 Agent 场景

### `demo_task_flow.py`

角色：

- `AliceAgent`：任务发起方，能力为 `可疑人员识别`、`目标跟踪`。
- `RobotDog`：协作方，能力为 `声光驱离`。

运行模式：单进程内创建两个 `AcnSDK` 实例，使用临时目录隔离配置和身份文件。

覆盖流程：

1. 两个 Agent 分别注册身份、注册能力、入网。
2. `AliceAgent` 发起 `可疑人员驱离` 任务。
3. `AliceAgent` 发布 `Location` track，并持续通过 MoQ 上报位置数据。
4. 通过 `/debug/*` 接口注入 `TASK_REQUEST_COLLABORATION`、`DISCOVER_RESULT`、`START_TASK`、`SUBSCRIBE_TRACK`。
5. `RobotDog` 接受协作，收到启动命令后请求任务执行并订阅 `Location`。
6. 双方终止任务、退网、去注册。

主要验证点：

- HTTP 身份/能力/任务接口。
- WebSocket 控制面消息分发。
- MoQ publish / subscribe / object callback。
- Debug 注入方式推动完整流程。

### `demo_task_flow_realtime.py`

角色同 `demo_task_flow.py`。

运行模式：单进程内创建两个 SDK 实例，但不使用 `/debug/*` 注入中间消息。

覆盖流程：

1. 两个 Agent 注册、入网、注册回调。
2. `AliceAgent` 请求任务执行和任务协同。
3. 通过真实 mock AgentGW/ARF 消息流等待 `TASK_REQUEST_COLLABORATION`、`DISCOVER_RESULT`、`START_TASK`。
4. 协同建立后持续上报 `Location`。
5. 双方按任务终止、退网、去注册顺序清理。

主要验证点：

- 不依赖 debug 注入的实时控制面闭环。
- 事件等待和回调驱动状态推进。
- `TASK_TERMINATION` 回调到本地 `request_terminate_task()` 的处理。

## 4. 双终端基础协同场景

### `demo_task_initiator.py` + `demo_task_collaborator.py`

角色：

- `demo_task_initiator.py`：`AliceAgent`。
- `demo_task_collaborator.py`：`RobotDog`。

运行模式：两个终端分别运行，通过 runtime 目录交换 `agent_id`、`task_id`、ready/shutdown 信号；仍使用 `/debug/*` 推进中间控制面消息。

覆盖流程：

- collaborator 先启动，写入 `collaborator.ready`。
- initiator 等待 collaborator ready 后发起任务、发布 `Location`、请求协同。
- initiator 注入协作请求、发现结果、启动任务、订阅 track。
- collaborator 接收请求、接受协同、执行任务并接收 MoQ 对象。
- initiator 写入 shutdown 信号，双方清理。

主要验证点：

- 两进程共享 runtime 文件协调。
- 多终端下的身份文件隔离。
- Debug 注入版双终端完整链路。

### `demo_task_initiator_realtime.py` + `demo_task_collaborator_realtime.py`

角色同上。

运行模式：两个终端运行，共享 runtime 目录，但不注入 `/debug/*` 中间消息。

覆盖流程：

- 双方各自使用 repo 配置生成隔离运行配置。
- collaborator 等待真实协同请求。
- initiator 请求协同后等待真实 `DISCOVER_RESULT`。
- collaborator 收到真实 `START_TASK` 后执行任务。
- initiator 持续上报 `Location`，最后终止、退网、去注册。

主要验证点：

- 双终端 realtime 控制面闭环。
- runtime 只负责进程协调，不负责伪造控制面消息。

### `demo_task_initiator_rt.py` + `demo_task_collaborator_rt.py`

角色同上。

运行模式：早期/简化 realtime 双脚本，使用默认配置和固定等待时间，不使用 runtime 文件协调。

覆盖流程：

- initiator 发起任务和协同。
- collaborator 等待协同请求并接受。
- 双方使用固定 sleep 等待消息和任务完成。

主要验证点：

- 最小 realtime 双脚本流程。
- 适合快速手工观察，不如 runtime 版本稳定。

## 5. 最新订阅 / fetch 策略场景

### `demo_task_initiator_rt_latest.py` + `demo_task_collaborator_rt_latest.py`

角色：`AliceAgent` + `RobotDog`。

覆盖流程：

- 基本协同流程与 realtime 双脚本一致。
- 双方注册 `on_subscribe_track_received`。
- 当收到 `Location` track 时返回 `fetch`，其他 track 返回 `subscribe`。
- initiator 使用 `broadcast_terminate_task()` 广播终止。

主要验证点：

- `SUBSCRIBE_TRACK` 回调先于默认 subscribe 执行。
- `Location` 使用 MoQ fetch 拉历史对象，再 subscribe 实时对象。
- 广播终止通知参与方。

### `demo_task_initiator_rt_latest_single_device.py` + `demo_task_collaborator_rt_latest_single_device.py`

角色同上。

运行模式：与 `rt_latest` 类似，但通过 `--runtime-root` / `--session-name` 为每侧生成隔离配置和运行目录。

主要验证点：

- 单机多进程运行时的身份/密钥/日志隔离。
- fetch/subscribe 策略与广播终止在隔离配置下仍可用。

## 6. 广播终止场景

### `demo_task_initiator_broadcast_rt.py` + `demo_task_collaborator_broadcast_rt.py`

角色：`AliceAgent` 发起，`RobotDog` 协作。

覆盖流程：

- initiator 发起任务、请求 `声光驱离` 能力协作。
- collaborator 接受并执行任务。
- initiator 分两段持续发布 `Location`。
- initiator 调用 `broadcast_terminate_task()` 广播终止。
- collaborator 收到 `TASK_TERMINATION` 后调用本地 `request_terminate_task()`。

主要验证点：

- 广播终止由任务发起方触发。
- 参与方通过 `on_terminate_task_received` 做本地任务终止。

### `demo_task_initiator_broadcast_rt_t1.py` + `demo_task_collaborator_broadcast_rt_t1.py`

角色同上。

差异点：

- collaborator 侧在等待后调用 `broadcast_terminate_task()`。
- 用于验证非发起方也能发起任务终止广播的场景。

主要验证点：

- 广播终止的触发方不是固定 initiator。
- initiator 也注册 `TASK_TERMINATION` 回调并终止本地任务。

## 7. 两个协作者场景

### `demo_task_initiator_broadcast_rt_t2.py`

角色：`AliceAgentT2`。

流程：

1. 注册能力 `可疑人员识别`、`目标跟踪`。
2. 发起 `可疑人员驱离` 任务并发布 `Location`。
3. 第一阶段请求 `声光驱离`，等待 collaborator 1 建立协同。
4. 第二阶段请求 `空中喊话`，等待 collaborator 2 建立协同。
5. 每个阶段协同建立后继续发送 `Location`。
6. 最后广播终止任务。

### `demo_task_collaborator1_broadcast_rt_t2.py`

角色：`RobotDogT2One`，能力 `声光驱离`。

覆盖点：

- 接受第一阶段协同。
- 收到 `TASK_TERMINATION` 后终止本地任务。

### `demo_task_collaborator2_broadcast_rt_t2.py`

角色：`SpeakerDroneT2Two`，能力 `空中喊话`。

覆盖点：

- 接受第二阶段协同。
- 收到同一个任务的终止广播后清理。

主要验证点：

- 同一任务按能力分阶段发现多个协作者。
- 多协作者共享同一 task_id 和 `Location` track。
- 广播终止覆盖所有参与者。

## 8. 三级协同链场景

### 基础三级链

相关脚本：

- `demo_task_agent_a_broadcast_rt_t3.py`
- `demo_task_agent_b_broadcast_rt_t3.py`
- `demo_task_agent_c_broadcast_rt_t3.py`

角色：

- A：`AliceAgentT3A`，任务发起方和 `Location` 发布方，能力 `可疑人员识别`、`目标跟踪`、`位置发布`。
- B：`BridgeRobotT3B`，桥接协作者，能力 `现场声光处置`、`协作转发`。
- C：`SpeakerDroneT3C`，叶子协作者，能力 `空中喊话支援`。

覆盖流程：

1. A 发起任务并发布第一条 `Location`。
2. A 请求 B 参加。
3. B 接受 A 的协同并订阅 A 的 `Location`。
4. B 收到第 3 条 track 消息后，请求 C 参加。
5. C 接受 B 的协同并接收 A 发布的任务数据。
6. A 广播终止任务，B/C 通过 `TASK_TERMINATION` 回调终止本地任务。

主要验证点：

- A -> B -> C 级联协同。
- 中间节点 B 既是协作者，也是下一级协同发起方。
- 广播终止跨三级参与者传播。

### 三级链 + 订阅回调 fetch

相关脚本：

- `demo_task_agent_a_broadcast_rt_t3_subscribe_callback.py`
- `demo_task_agent_b_broadcast_rt_t3_subscribe_callback.py`
- `demo_task_agent_c_broadcast_rt_t3_subscribe_callback.py`

差异点：

- A/B/C 都注册 `on_subscribe_track_received`。
- 对 `Location` 返回 `fetch`，其他 track 返回 `subscribe`。

主要验证点：

- 三级链路中每个参与方都能定制订阅策略。
- 后加入节点可通过 fetch 获取历史 `Location` 对象。

### 三级链 + 双 track

相关脚本：

- `demo_task_agent_a_broadcast_rt_t3_two_tracks_subscribe_callback.py`
- `demo_task_agent_b_broadcast_rt_t3_two_tracks_subscribe_callback.py`
- `demo_task_agent_c_broadcast_rt_t3_two_tracks_subscribe_callback.py`

角色与能力：

- A：`AliceAgentT3A2Tracks`，发布 `Position` 和 `Status`，能力含 `位置发布`、`状态发布`。
- B：`BridgeRobotT3B2Tracks`，订阅两个 track，只在收到第 3 条 `Position` 后请求 C。
- C：`SpeakerDroneT3C2Tracks`，对 `Position` 使用 `fetch`，对 `Status` 使用 `subscribe`。

主要验证点：

- 单任务多 track 发布。
- 按 track 区分触发逻辑。
- 同一个 `SUBSCRIBE_TRACK` payload 中不同 track 可选择不同接收模式。

## 9. 辅助脚本

### `demo_task_shared.py`

不是独立运行入口，供部分双终端 demo 复用。

提供能力：

- 创建 runtime/session 目录。
- 生成隔离 `config.yaml`。
- 生成定位 payload。
- 持续调用 `task_info_report()` 上报任务数据。
- 调用 AgentGW `/debug/*` 接口注入协同请求、发现结果、启动任务、订阅 track。
- 读写 runtime 文件，用于进程间同步 `agent_id`、`task_id`、ready、shutdown 信号。

## 10. 建议运行顺序

基础验证：

```bash
python3 examples/demo_identity_flow.py
python3 examples/demo_task_flow.py
python3 examples/demo_task_flow_realtime.py
```

双终端 debug 版：

```bash
# terminal 1
python3 examples/demo_task_collaborator.py --reset

# terminal 2
python3 examples/demo_task_initiator.py
```

双终端 realtime 版：

```bash
# terminal 1
python3 examples/demo_task_collaborator_realtime.py --reset

# terminal 2
python3 examples/demo_task_initiator_realtime.py
```

广播终止两方场景：

```bash
# terminal 1
python3 examples/demo_task_collaborator_broadcast_rt.py

# terminal 2
python3 examples/demo_task_initiator_broadcast_rt.py
```

两协作者场景：

```bash
# terminal 1
python3 examples/demo_task_collaborator1_broadcast_rt_t2.py

# terminal 2
python3 examples/demo_task_collaborator2_broadcast_rt_t2.py

# terminal 3
python3 examples/demo_task_initiator_broadcast_rt_t2.py
```

三级协同链：

```bash
# terminal 1
python3 examples/demo_task_agent_c_broadcast_rt_t3.py

# terminal 2
python3 examples/demo_task_agent_b_broadcast_rt_t3.py

# terminal 3
python3 examples/demo_task_agent_a_broadcast_rt_t3.py
```

三级协同双 track：

```bash
# terminal 1
python3 examples/demo_task_agent_c_broadcast_rt_t3_two_tracks_subscribe_callback.py

# terminal 2
python3 examples/demo_task_agent_b_broadcast_rt_t3_two_tracks_subscribe_callback.py

# terminal 3
python3 examples/demo_task_agent_a_broadcast_rt_t3_two_tracks_subscribe_callback.py
```
