# start_workers.sh
#!/bin/bash
#
docker stop $(docker ps -aq) > /dev/null 2>&1
docker rm $(docker ps -aq) > /dev/null 2>&1
# # 定义所有 Worker 端口
PORTS=(20000 20001 20002 20003 20004 20005 20006 20007 20008 20009 20010 20011 20012 20013 20014 20015 20016 20017 20018 20019)
#
# # 循环启动每个端口的 Worker
for port in "${PORTS[@]}"; do
   echo "Starting Uvicorn on port $port..."
     uvicorn main:app --port "$port" &
     done
#
     # 等待所有后台进程
     wait
