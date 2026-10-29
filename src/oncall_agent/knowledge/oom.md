# 内存耗尽与 OOM

关键词：OOM Killed 内存 不足 order-worker dmesg

现象：进程消失，日志附近有 Killed 或 Out of memory，服务 restarts 增加。
order-worker 在大批量对账时会把内存吃满，然后被系统杀掉。

处理步骤：
1. 用 service_status 看 mem 和 restarts。
2. 用 tail_logs 确认是不是 OOM，而不是主动退出。
3. 先缩小 order-worker 的批大小或暂停新任务，再考虑扩容。
4. 仅当进程已死且需要拉起时，才申请重启，并等待人工批准。
