# 设备时钟校准簿

工厂数据采集工程师可在工作台上传来源 CSV，对照规则判断差异，签发合格批次或记录暂缓意见。

以两侧可信同步点做分段线性校准并拦截外推。基准换版时，已签发读数按记录键冻结、不会被新基准改写；晚到同步数据只推进未发布范围；受影响范围无法闭合则阻断整版。工作台可核对每条读数所用的基准版本与本版变化的读数。

## 启动

```sh
docker compose up --build -d --wait
```

打开 <http://localhost:18303>。页面预览带异常样例。选中阶段查看计算证据，选择可签发样例并执行批次，然后提交复核意见。

## 核验

```sh
docker compose exec -T app pytest -q
```

[输入字段](docs/DATA-DICTIONARY.md) · [阶段接口](docs/HTTP.md) · [操作步骤](docs/OPERATIONS.md) · [规则与测试](docs/DEPTH.md)
