# CPU 持续过高

关键词：CPU 负载 飙高 火焰图 latency payment-api

现象：单核或平均负载持续高于 85%，接口延迟变长，但内存和磁盘正常。
payment-api 在发布后出现过 CPU 打满，伴随超时重试风暴。

处理步骤：
1. 用 service_status 看 cpu 和 restarts，确认是不是刚发布。
2. 用 tail_logs 找超时和重试，先限流或降级，而不是立刻重启。
3. 如果只有 payment-api 异常，对照上一版发布记录，考虑回滚。
4. 采样火焰图留给后续排查，本练习环境不提供真实采样。
