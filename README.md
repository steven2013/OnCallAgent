# OnCallAgent

值班排障技能放在 `.cursor/skills/`，由 Cursor 自动加载。

- `kafka-log-rca`：根据 broker、消费端、生产端、ZooKeeper 与 GC 日志定位 Kafka 根因。只读扫描，处置留给值班人执行。
