---
name: kafka-log-rca
description: >-
  根据 broker、consumer、producer、ZooKeeper 与 GC 日志定位 Kafka 根因并写出处置建议。
  用于消费积压、lag 不降、ISR 收缩、rebalance、消费组消失或 Dead、heartbeat 失败、
  位点不前进、OffsetOutOfRange、告警 5013509、磁盘满、启动失败、vim .swp、
  ZK NoAuth、依赖组件无日志退出。Use when diagnosing Kafka incidents from logs.
---

# Kafka 日志根因定位

用已有日志判断根因。扫描命中只说明「要核对哪条案例」，闭合条件齐了才能下结论。

本 skill 只分析。重启、删文件、改保留、重置位点、改 ACL 写进处置，交给值班人执行。

## 何时使用

消费积压、lag 不降、ISR 抖动、rebalance、消费组消失或 Dead、心跳失败、位点不前进、`OffsetOutOfRange`、告警 5013509、broker 起不来、磁盘满、指标断点、组件没有应用日志就退出、ZooKeeper `NoAuth`。

只有告警名、没有日志时：列出要拉的日志后停止，不猜案例。

## 先对齐的材料

同一条时间线使用同一个时区。时区未知时保留日志原文时间，并注明「时区未给」。

| 症状 | 必看 | 闭合邻案时再补 |
| --- | --- | --- |
| 积压 / lag | 消费端业务日志、broker `server.log`、该消费组 lag | producer 日志、GC 日志、下游耗时、线程池 |
| 消费组异常 | 消费端日志、GroupCoordinator 所在 broker 的 `server.log` | 分区目录段文件名、治理页面行数 |
| 集群故障 | 故障 broker 的 `server.log`、GC 日志、ZK 日志 | `controller.log`、启动脚本 stdout / journal、`df` |

常见文件名：`server.log`、`controller.log`、`state-change.log`、`kafkaServer-gc.log`、消费端应用日志、ZK `zookeeper.out`。

## 步骤

1. 记下每条证据的来源：哪一侧、哪台、哪个文件。积压类只看到消费端或只看到生产端时，置信度最高到「中」。
2. 日志在文件或目录中时运行：

```bash
bash .cursor/skills/kafka-log-rca/scripts/scan-kafka-logs.sh <事故日志路径>...
```

只把事故日志传进去。目录扫描会跳过本 skill 自己的说明和样例；仍不要把 skill 目录当成事故日志。脚本退出码 0 只表示扫描完成，不表示找到了根因。

3. 打开 `references/cases.md` 里命中 ID 对应的小节，逐条核对闭合条件。用户贴的是片段时，改查 `references/signatures.md`，不跑脚本。
4. 先定大类，再进案例：
   - 起不来、磁盘、ZK、进程无日志退出 → C
   - 组消失、全员失败、心跳、位点不前进、5013509 → G
   - lag 上升或只升不降，组还在 → B
   - 两类都有时，时间上更早的机制是根因，后面的标成后果
5. 闭合条件缺一条，就保持「待证」，不补日志里没有的数字。
6. 多个 ID 同时闭合时，只留一个主因。用该案例的「鉴别」把其余 ID 写成后果或排除。
7. 按输出结构写结论。会丢消息、或只是临时手段的，写在对应动作同一句里。

积压类在进入具体 B 案例前，先做 `references/cases.md` 的 B0：生产端缓冲、消费端阻塞队列、下游耗时、broker ISR 与磁盘放在同一条时间线上。

## 第一跳

以时间上更早的特征为准。

| 最先看到的特征 | 核对 |
| --- | --- |
| `No space left on device`，指标同时中断 | C3 |
| 启动目录校验失败，路径是 vim `.swp` | C2 |
| `NoAuth` | C5 |
| 进程不在，应用日志没有新行 | C4 |
| `Shrinking ISR` 与 `skip updating ISR` 反复出现，没有 `Expanding ISR` | C1 |
| `Shrinking ISR` 与 `Expanding ISR` 交替，并有长 GC | B3 |
| 非法格式在前，随后 poll 超时，组变空或 Dead | G1 |
| `heartbeat failed` / session timeout，心跳随 poll 发送 | G2 |
| 文案点名 `max.poll.interval.ms`，且没有非法格式链 | N1 |
| 位点不动，且没有 `OffsetOutOfRange` | G3，并向分区目录要段文件名 |
| `OffsetOutOfRange` 或客户端已经 reset | N2，再看有没有 leader epoch 链（N3） |
| 告警号 5013509 | G4 |
| 下游慢且本地阻塞队列打满 | B1 |
| AZ 倒换后 lag 不降，转发线程顶满 | B2 |
| 慢日志 topic，机器资源打满 | B4 |
| 热点分区 lag，节点仍有余量 | B5 |

## 置信度

- 高：闭合条件都有原文，时间顺序和机制一致。
- 中：主特征在，缺一条鉴别材料。写明缺哪一份。
- 低：只有 lag、告警号或「消费慢」。不指定案例，只写要补的日志。

## 输出

```
结论：<一句话，含案例 ID>
置信度：高|中|低
机制：<从第一下异常到用户可见症状>
证据：
- <时间> <来源> <原文一行>
已排除：
- <案例 ID>：<日志里已有的否定事实；没有排除项则写无>
处置：
1. <动作>。数据影响：无 / 会丢消息 / 临时
仍缺：<没有则写无>
复发：<要补的监控或配置>
```

证据保留原句和原数字。根因写成机制链，例如「下游超过 1s → 阻塞队列满 → poll 停 → lag 正反馈」，不单写「消费积压」。

## 边界

- 5013509 以 Kafka 治理页面上该消费组的数据行数为准。日志里没有行数时，停在 G4「待治理页面判定」，不编造阈值。
- 重置位点只在 G3 闭合后提出，并写明会丢消息。
- 保留从 72h 降到 12h 是 C3 的临时手段。长期手段是磁盘扩容 500G。进程已因磁盘满退出时，先腾出能启动的空间，缩短保留才会生效。
- C1 重启的是打出过期 `zkVersion` 的那个 broker 进程。
- 只把确认属于 vim、且服务用户不可读的 `.swp` 写入处置。Kafka 段恢复文件 `*.swap`、`*.cleaned` 不按 C2 删除。
- C5 停在核对：异常里的 znode、该路径 ACL、broker JAAS / `zookeeper.set.acl`、各 broker 配置是否一致、连通性。不写绕过 ACL 的步骤。
- 业务代码里的 `catch` 不能作为 G1 的修复。反序列化发生在 `poll()` 内部；只阻塞不抛异常时 `catch` 也不会执行。

## 参考

- 闭合条件、鉴别、处置：`references/cases.md`
- 特征与该打开的文件：`references/signatures.md`
- 扫描规则表：`references/patterns.tsv`
