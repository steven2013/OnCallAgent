# 重启策略

关键词：重启 批准 人工 request_restart 擅自

重启会中断正在处理的请求，必须先取证，再申请，最后等人工批准。

允许申请重启的情况：
- 进程已经被 OOM 杀掉，需要拉起
- 死锁且日志已经保留

不要靠重启处理的情况：
- 磁盘满
- 单纯的 CPU 高
- 刚刚发布失败（应优先回滚）

工具 request_restart 只会改模拟集群的状态。图里的 approve 节点会用 interrupt 暂停，等调用方用 Command(resume=...) 明确批准后，ToolNode 才会执行它。
