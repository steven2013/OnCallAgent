# 磁盘空间不足

关键词：磁盘 空间 打满 no space left device /var/log pay-1 payment-api

现象：磁盘使用率超过 90%，写入失败，日志里出现 no space left on device。
pay-1 上的 payment-api 经常被自己的访问日志把磁盘打满。

处理步骤：
1. 先用 disk_usage 确认是哪台主机、哪个挂载点满了。
2. 清理 /var/log 里已经轮转、超过 7 天的日志，不要删除正在写入的文件。
3. payment-api 优先清理访问日志，然后确认使用率降到 80% 以下。
4. 磁盘满通常不是重启能解决的。不要在未批准时重启。
