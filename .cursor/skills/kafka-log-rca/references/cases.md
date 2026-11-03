# 案例闭合条件

现网案例 ID 为 B / G / C。N 是公开排查里容易混进来的邻案，用来改判，不作为现网案例编号输出。

未配置的 broker 参数以当时生效值为准。`replica.lag.time.max.ms` 在这批现网案例里未配置，默认 10s；较新版本文档里的默认值常见为 30s。两者都不要凭记忆填，先读 broker 配置或版本文档。

## B0 双向反压

生产端 `buffer.memory` 与消费端本地阻塞队列会把压力传到对方。积压类先把下面四段放上同一时间线：

- 生产端：`Expiring N records`、`Buffer exhausted`、`NotEnoughReplicas`
- 消费端：阻塞队列剩余容量、poll 间隔
- 下游：单次耗时
- broker：ISR、磁盘、请求耗时

时间上更早变慢的一段是起点，另一侧写成反压后果。只有一侧日志时，置信度最高为中。

## B1 CES 下游负载不均

机制：下游响应变慢（现网是单次超过 1s）把消费端本地阻塞队列填满，应用停止 poll，fetch 停，lag 加大，批次更重，下游更慢，形成正反馈。

闭合，四条都要有：

1. 下游耗时升高，出现超过 1s 的请求。
2. 本地阻塞队列打满或出现拒绝。
3. 其后 poll 间隔变长，或出现 poll 超时。
4. lag 加速上升。

鉴别：ISR 稳定，磁盘未满，转发线程池未顶满，且不是单一热点分区。这些事实有日志或监控时写进「已排除」。

处置：均衡下游负载，同时降低发送线程或扩容网关，把正反馈打断。现网以此恢复。数据影响：无。

## B2 转发线程数不足

机制：AZ 倒换之后转发线程池成为上限，积压不下降。

闭合：

1. 时间落在 AZ 倒换之后。
2. 倒换完成后 lag 持平或继续上升。
3. 转发线程活跃数顶满、队列堆积，CPU 仍有余量。

鉴别：倒换期间有少量积压，随后 lag 持续下降。这是正常恢复，不立案，继续看下降趋势。下游耗时高且阻塞队列满时改核 B1。

处置：调高转发线程数。现网调高后恢复。数据影响：无。

## B3 ISR 不同步

机制：堆内存不合适，长 GC 频繁；follower 单次拉取被 `replica.fetch.max.bytes` 卡住（现网配过 6M，高流量 topic 仍追不上）；`replica.lag.time.max.ms` 未显式配置，按默认 10s 把落后副本踢出 ISR。副本进出 ISR，高水位上不去，生产和消费一起慢。

闭合，三条都要有：

1. GC 暂停达到当时生效的 `replica.lag.time.max.ms`。
2. 同一时段有 `Shrinking ISR`，并且之后有 `Expanding ISR`。
3. 落后发生在高流量 topic，拉取大小顶在 `replica.fetch.max.bytes`。

单条消息批次大于 `replica.fetch.max.bytes` 时，follower 会一直无法追上。日志里若有 batch larger than replica fetch，把这条写进机制。

鉴别：同一分区反复出现 `Cached zkVersion ... skip updating ISR`，且没有成功的 `Expanding ISR` 时，改判 C1。

处置：灰度调整同步参数（提高 `replica.fetch.max.bytes`，显式设置 `replica.lag.time.max.ms`，修正堆和 GC）。现网灰度后恢复。数据影响：无。

## B4 性能规格不足

机制：CPU、磁盘或网络已经打满，消费速度低于生产速度。现网发生在慢日志 topic，消费不掉。

闭合：

1. 目标 topic 各分区 lag 一起上升。慢日志 topic 优先对照本案例。
2. broker 或消费节点的 CPU、磁盘 IO 或网络打满。
3. 线程池和下游耗时正常。

鉴别：只有部分分区 lag、其余分区空闲时改核 B5。线程池顶满且 CPU 有余量时改核 B2。

处置：升级规格。现网升级后恢复。数据影响：无。

## B5 分区数不足

机制：分区并行度不够，单分区吞吐到顶。现网对高数据量 topic 扩分区后恢复。

闭合：

1. 高数据量 topic。
2. 热点分区 lag 高，其他分区明显更低；或分区数已经等于消费并发，单线程处理到顶。
3. 节点规格仍有余量。

处置：扩分区。新分区承接新消息；键的分区映射会变化；消费并发要一起增加。数据影响：无。旧消息不会因为扩分区重新分布。

## G1 消费组消失

机制：消息格式不合法，解析阻塞在 poll 线程上 → poll 超时 → 持续 rebalance → 全部成员失败 → 组变为 Empty / Dead。现场表现为组被删除或查询不到。有已提交位点时，组元数据可能要等位点过期才从协调器消失，以「查询不到」这条现场为准。

闭合，按这个顺序：

1. 先有格式或反序列化错误，或解析长时间不返回。
2. 然后出现 `poll timeout has expired`。
3. coordinator 出现 `has failed, removing it from the group`，rebalance 反复发生。
4. `is now empty` 或 `transitioned to Dead`，组查询不到。

鉴别：同一条 LeaveGroup 往往带有 `max.poll.interval.ms`。前面已有非法格式、最终组变空时，主因是 G1，N1 是超时的实现路径。业务 `catch` 已经存在，不能用来否定 G1：`poll()` 内部的反序列化到不了业务 `catch`；解析若只阻塞不抛异常，`catch` 也不会执行。

处置：格式失败要有界，并且离开 poll 线程（跳过并计数，或进入死信）。然后重启消费者，让组重新注册。加大 timeout 不能作为根因修复。数据影响：跳过非法消息时，这些消息需要有死信或计数才可追踪。

## G2 旧客户端心跳失败

机制：旧客户端把心跳放在 poll 里发送。一次处理超过 `session.timeout.ms`，coordinator 判定该成员死亡。

闭合：

1. 日志能看出心跳随 poll 发送（没有独立心跳线程；文案指向 heartbeat / session，而不是 `max.poll.interval.ms`）。
2. `heartbeat failed`、`Timed out HeartbeatRequest`，或成员因 session timeout 被移除。
3. 处理时长大于 `session.timeout.ms`。

鉴别：文案是 `consumer poll timeout has expired` 且点名 `max.poll.interval.ms` 时，改走 N1。那种情况去核对处理时长和 `max.poll.records`，不去放宽 `session.timeout.ms`。

处置：现网重启服务、重新注册后恢复。根因修复是让两次 poll 之间的处理短于会话超时，或升级到心跳与 poll 分离的客户端（KIP-62，0.10.1 起心跳线程独立）。数据影响：无。重启期间由组内其他成员接管；全员一起重启会有一段空窗。

## G3 offset 空洞永久卡住

机制：消息被清理后，日志里留下空洞。已提交 offset 仍被视为有效位点，所以 `auto.offset.reset=earliest` 不生效，消费者停在空洞上。

闭合：

1. 消费位点长时间不变。
2. 没有 `OffsetOutOfRange`，也没有 reset 到 earliest / latest 的记录。
3. 该分区目录中，最小段文件名的起始偏移大于已提交 offset。段文件名是 20 位起始偏移，例如 `00000000000000002000.log`。

第 3 条是现网确认动作。没有目录列表时，置信度最高为中。

鉴别：已经出现 `OffsetOutOfRange` 且客户端按 `auto.offset.reset` 跳转时，改走 N2。那种情况下重置策略已经生效。

处置：重置位点后可以恢复消费，空洞以及此前未消费的消息会丢失。数据影响：会丢消息。

## G4 告警 5013509

闭合：告警号为 5013509。

这项分流不在 broker 日志里完成。打开 Kafka 治理页面，查看该消费组的数据行数，按页面 SOP 决定等待自愈或升级服务。日志里没有行数时，结论写「待治理页面判定」。不编造行数阈值。

## C1 shrink 死循环

机制：社区缺陷 KAFKA-2729 / KAFKA-1382。ZK 会话抖动后，broker 缓存的 `zkVersion` 过期，ISR 更新被跳过，shrink 无限重试。相同日志在后续版本仍有现场（KAFKA-10127、KAFKA-7888），以日志为准，不因版本号放过。

闭合：

1. `Shrinking ISR` 与 `Cached zkVersion ... not equal to that in zookeeper, skip updating ISR` 成对反复出现。
2. 同一分区没有随后成功的 `Expanding ISR`。
3. 起始点附近有 ZK 会话过期或连接抖动。第 3 条缺失时置信度为中。

处置：重启打出过期 `zkVersion` 的那个 broker 进程。现网重启后恢复。打开副本不平衡 / UnderReplicated 告警，在循环形成前就能看见。数据影响：重启单台时，副本数和 `min.insync.replicas` 决定是否影响写入。把这个风险写进处置。

## C2 无法启动（vim `.swp`）

机制：root 使用 vim 留下交换文件，kafka 服务用户不可读，启动做目录校验时失败。

闭合：

1. `Failed to create or validate data directory`，或启动 Fatal 的原因是无法读取。
2. 路径指向 vim 交换文件：以 `.` 开头、以 `.swp` 结尾。
3. 属主是 root，运行用户不可读。

鉴别：Kafka 日志压缩留下的 `*.swap`、`*.cleaned` 是段恢复文件。文件名对不上 vim `.swp` 时，不按本案例删除。

处置：确认是 vim 残留后，由值班人删除该 `.swp` 再启动。预防：使用服务用户登录，vim 以 `:q` 退出，不把 root 的编辑会话留在 broker 上。数据影响：无。

## C3 磁盘满，指标丢失

机制：磁盘写满后 broker 不能继续写日志，进程退出或停写，抓取中断，监控上表现为指标丢失。

闭合：

1. `No space left on device`，或 `df` 已满。
2. 指标在同一时刻断点。
3. broker 日志停在 Fatal / `Exiting Kafka`。

处置：

1. 临时：保留从 72h 降到 12h。进程已经退出时，先清出能够启动的空间，只动已经滚动的旧段，不动当前活动段；启动之后缩短保留才会删掉数据。
2. 长期：磁盘扩容 500G。
3. 复发：磁盘超阈值告警要在写满之前触发。

数据影响：缩短保留会提前删除超过 12h 的日志，属于临时手段。

## C4 依赖组件静默不拉起

机制：启动脚本先检查 Kafka、ZK、DB。Kafka 未就绪时组件直接退出，失败路径没有打应用日志。

闭合：

1. 组件进程不在。
2. 应用日志没有新内容，或文件没有创建。
3. 启动脚本 stdout、journal 或预检输出里，Kafka、ZK 或 DB 未通过。

处置：按预检结果先把未就绪的依赖拉起来，再启动组件。复发项写明：启动失败必须在退出前落一行原因。数据影响：无。

## C5 ZK 连接 NoAuth

机制：broker 访问 ZooKeeper 被 ACL 拒绝。这是授权失败。

闭合：`NoAuthException`、`KeeperErrorCode = NoAuth` 或 `NoAuth for`，并且日志里带 znode 路径。

处置：按 ZK ACL 与连通性检查流程核对异常中的路径、该路径 ACL、broker 的 JAAS 与 `zookeeper.set.acl`、各 broker 是否一致、到 ZK 的连通性。不写修改或绕过 ACL 的命令。数据影响：无。

## 邻案

这些指纹出现时改判，不输出成现网案例号。

### N1 新客户端 poll 超时

指纹：`consumer poll timeout has expired`，并点名 `max.poll.interval.ms`。0.10.1 之后心跳线程与 poll 分离，处理过慢击穿的是 `max.poll.interval.ms`，不是 `session.timeout.ms`。

没有 G1 的非法格式链时，主因是单次处理超过 poll 间隔。核对 `max.poll.records` 与单条处理耗时。前面已有非法格式且组最终变空时，仍按 G1。

### N2 真越界

指纹：`OFFSET_OUT_OF_RANGE`、`OffsetOutOfRangeException` 或 `offset_out_of_range`。请求偏移小于 LogStartOffset 或大于 LogEndOffset 时，broker 返回越界，`auto.offset.reset` 会执行：`earliest` 从当前最早处重放，`latest` 跳到末尾，`none` 把异常交给应用。

这是保留时间追上了 lag，或日志被截断。与 G3 的差别是越界日志存在，重置策略已经生效。

### N3 过期 leader epoch

指纹：leader 变更之后出现 rebalance 或再次 fetch，随后 `OffsetOutOfRange`（KAFKA-19902）。提交进去的 epoch 还指向已被保留删除的段。与 G3 的差别同样是越界日志存在。与 N2 的差别是时间线上先有 leader 变更。

### N4 短暂 ISR 收缩

指纹：`Shrinking ISR` 之后短时间内 `Expanding ISR`，且没有持续的 `skip updating ISR`。先按 B3 的 GC、磁盘、拉取大小核对。三条闭不上时，结论保持「副本短暂落后」，不升到 C1。

### N5 cooperative-sticky 旧位点

指纹：rebalance 之后立刻 `offset_out_of_range`，再 reset 到 earliest，lag 顶在保留时长上。librdkafka 2.4.0 之前的 cooperative-sticky 会在保留分区上从旧位点继续拉取（issue 4686）。客户端是 librdkafka 且版本低于 2.4 时把这条写进机制。

## 公开经验里借用的判别

- 心跳与 poll 分离来自 KIP-62。旧客户端用 G2，新客户端的处理超时用 N1。
- `auto.offset.reset` 只在没有已提交位点、或位点越界时生效。位点仍被视作有效时用 G3，不用重置策略解释。
- ISR 是否死循环，看 `skip updating ISR` 是否持续、以及有没有成功的 `Expanding ISR`（KAFKA-2729 / 1382）。
- 越界若紧跟 leader 变更，补看提交 epoch 是否过期（KAFKA-19902）。
- 消费 lag 与副本 lag 分开看。follower 落后表现为 `UnderReplicatedPartitions` 和 ISR 收缩；消费组落后表现为该 group 的 lag。
