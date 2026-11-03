# 特征与取证位置

`scripts/scan-kafka-logs.sh` 按 `patterns.tsv` 计数。命中后用 `cases.md` 的闭合条件决定是否成立。脚本不判断时间顺序。

## 扫描结果怎么读

- 同一案例的多个 ID 都出现，只表示该案例进入核对，不表示已经闭合。
- `B3-SHRINK` 同时出现在 B3 和 C1。有 `C1-ZKVER` 且没有 `B3-EXPAND` 时先核 C1；有 `B3-EXPAND` 且没有 `C1-ZKVER` 时先核 B3。
- `G1-POLL` 与 `N1-POLL` 经常出现在同一条 LeaveGroup 上。有 `G1-DESER` 且随后有 `G1-EMPTY` 时主因按 G1。
- `G3-OOR` 出现时，G3 不成立，改核 N2 / N3。
- `B2-FALLING` 出现且倒换后 lag 在下降时，B2 不立案。
- 结果为 `NO_HITS` 时，不从案例表里挑一个最像的。改为按症状补日志。

## 脚本覆盖不到、必须另取的材料

| 案例 | 还要看 | 闭合时的事实 |
| --- | --- | --- |
| B1 | 下游耗时监控、队列剩余容量 | 单次超过 1s，并且队列打满发生在 lag 加速之前 |
| B2 | 转发线程池活跃数、CPU、lag 曲线 | 线程顶满、CPU 有余量、倒换后 lag 不降 |
| B3 | `kafkaServer-gc.log`、broker 配置 | GC 暂停 ≥ 当时的 `replica.lag.time.max.ms`；该参数是否未显式配置 |
| B4 / B5 | CPU、磁盘、网络、各分区 lag | 资源打满走 B4；热点分区且资源有余走 B5 |
| G3 | 分区目录 `ls` | 最小段文件起始偏移 > 已提交 offset |
| G4 | Kafka 治理页面 | 该消费组数据行数 |
| C2 | `ls -l` 交换文件 | 属主 root、服务用户不可读、名字是 vim `.swp` |
| C3 | `df`、指标曲线 | 磁盘满与指标断点同一时刻 |
| C4 | systemd journal、启动脚本 stdout | 预检失败发生在应用日志创建之前 |

## 日志里的原句对应哪一侧

| 原句片段 | 通常所在 | 支持 |
| --- | --- | --- |
| `Shrinking ISR` / `Expanding ISR` / `Cached zkVersion` | leader broker `server.log` | B3、C1 |
| `Pause Full` / `Full GC` | `kafkaServer-gc.log` | B3 |
| `replica.fetch.max.bytes` | broker 配置或 follower 拉取日志 | B3 |
| `ZooKeeper session has expired` | broker 或 ZK 日志 | C1 的起点 |
| `NoAuth for /...` | broker `server.log` | C5，路径要保留 |
| `No space left on device` / `Exiting Kafka` | broker `server.log` | C3 |
| `Failed to create or validate data directory` | 启动日志 | C2 |
| `poll timeout has expired` | 消费端 | G1 或 N1 |
| `has failed, removing it from the group` / `is now empty` / `transitioned to Dead` | GroupCoordinator `server.log` | G1 |
| `heartbeat failed` / `Timed out HeartbeatRequest` | 消费端或 coordinator | G2 |
| `OffsetOutOfRange` | 消费端 | N2、N3 |
| `Expiring N records` / `NotEnoughReplicas` | 生产端 | B0，先分清起点还是后果 |
| `RecordDeserializationException` / `Unknown magic byte` | 消费端，且在 `poll()` 栈内 | G1 |

## 时间顺序

G1、B1、C1 都要求「谁先发生」。扫描计数相同的两份日志，要回到原文比时间：

- G1：格式错误早于 poll 超时，poll 超时早于组变空。
- B1：下游变慢早于队列打满，队列打满早于 lag 加速。
- C1：ZK 会话异常早于成对的 shrink 与 skip；中间没有 Expanding。
