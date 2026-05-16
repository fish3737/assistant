# 智能家居边缘自治 Agent（基础系统）

这个项目对应你的开题报告第 2.3 节基础平台要求，包含完整闭环：

1. 传感器模拟：温度、门磁、人体红外、光照  
2. MQTT 消息传输：传感器上报 + Agent 控制命令  
3. 本地边缘 Agent：读状态、规则决策、优先级调度  
4. 设备执行：灯、空调、报警器状态更新  

## 目录结构

```text
edge_home_agent/
├── docker-compose.yml
├── homeassistant/configuration.yaml
├── mosquitto/config/mosquitto.conf
├── requirements.txt
└── src
    ├── agent/edge_agent.py
    ├── device/device_executor.py
    ├── simulator/sensor_simulator.py
    └── run_demo.py
```

## 一、启动 MQTT + Home Assistant

### Docker

```bash
cd /Users/fish37/Desktop/程序设计/edge_home_agent
docker compose up -d
```

默认会启动两个服务：

1. MQTT broker（Mosquitto）：`127.0.0.1:1883`
2. Home Assistant：`http://127.0.0.1:8123`

首次打开 Home Assistant 需要创建管理员账号，创建完成后即可在页面里看到 MQTT 传感器和开关实体。


## 二、安装 Python 依赖

```bash
cd /Users/fish37/Desktop/程序设计/edge_home_agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 三、运行系统

### 方式 A：一键运行（3 个模块同时启动）

```bash
python -m src.run_demo
```

该命令会同时启动：

1. `device_executor`（设备执行）
2. `edge_agent`（边缘决策）
3. `sensor_simulator`（传感器模拟）

### 方式 B：分开运行（便于观察日志）

终端 1：

```bash
python -m src.device.device_executor
```

终端 2：

```bash
python -m src.agent.edge_agent
```

终端 3：

```bash
python -m src.simulator.sensor_simulator
```

## 四、已实现规则场景（Agent）

1. 开门且环境昏暗：开灯（中优先级）  
2. 环境明亮：关灯（低优先级）  
3. 长时间无人：关空调（中优先级）  
4. 温度高且有人：开空调（低优先级）  
5. 夜间门磁触发且无人：触发报警（高优先级）  
6. 门关闭且检测到有人：关闭报警（中优先级）

Agent 使用优先队列调度任务，高优先级任务先执行。

## 五、Home Assistant 中可见实体

1. 传感器：`Home Temperature`、`Home Illuminance`
2. 二值传感器：`Door Contact`、`Motion PIR`
3. 可控开关：`Demo Light`、`Demo AC`、`Demo Alarm`

你可以在 Home Assistant 的 Dashboard 里直接切换这 3 个开关，它会通过 MQTT 下发命令到设备执行模块。

## 六、通信约束模拟（用于后续实验）

你可以直接通过环境变量模拟时延和丢包。

传感器链路：

```bash
export SENSOR_DROP_RATE=0.2
export SENSOR_DELAY_MS=300
```

Agent 控制链路：

```bash
export CMD_DROP_RATE=0.1
export CMD_DELAY_MS=200
```

再运行模块即可进入“非理想通信环境”实验模式。

## 七、常用参数

- `MQTT_HOST`（默认 `127.0.0.1`）  
- `MQTT_PORT`（默认 `1883`）  
- `NO_MOTION_AC_OFF_SEC`（默认 `20` 秒）  
- `HOT_TEMP_THRESHOLD`（默认 `28` 摄氏度）  
- `NIGHT_LUX_THRESHOLD`（默认 `80` lux）

## 八、后续可扩展方向（对应开题后半部分）

1. 将任务成功率、响应时间写入 CSV 自动统计  
2. 扩展更多设备（窗帘、新风、门锁）  
3. 加入“边缘/云协同”策略切换  
4. 增加任务截止时间与抢占式调度
