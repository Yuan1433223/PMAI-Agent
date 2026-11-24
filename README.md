# PMAI-Agent

PMAI-Agent 的目标是做一个免费、开源的求职调查 Agent，帮助大学生和其他求职者从招聘推荐列表之外发现企业，找到值得自己核查的岗位。首个使用场景是深圳的 Agent 开发、大模型应用和 FDE 机会。

给它一份企业名单、城市、方向和可选的毕业届别，它会在支持的招聘来源逐家查找材料，区分有招聘依据、待确认和明确不匹配的岗位。求职者可以从每条判断回到原文，看到哪些条件还未知，再决定是否跟进。

## 项目状态

首版支持本地 PDF 名单导入、单家或小批次调查、证据核查、反馈和导出。离线样例无需账户。代码许可证尚待维护者选定。

- [阶段计划与验收](docs/首版实施计划.md)
- [用户任务与需求](docs/需求.md)
- [调查流程与模块边界](docs/开发设计.md)
- [数据关系](docs/数据模型.md)
- [贡献与协作约定](AGENTS.md)

## 本地运行

使用 Python 3.11 或更新版本，在项目根目录执行以下命令。样例为自行生成的两页合成 PDF。当前导入格式要求文本层每行包含连续序号和企业名，无法解析的行会报告页码。

```shell
python -m pip install .
python -m pmai_agent import-list pmai_agent/samples/companies.pdf
python -m pmai_agent list 1
python -m unittest discover -s tests -v
```

默认数据库为 `data/app.sqlite3`。可在子命令之前传入 `--db 文件路径`。

用 `python -m pmai_agent demo` 回放一次补查；用 `python -m pmai_agent show 1` 查看调查，用 `python -m pmai_agent resume 1` 继续未结束的调查。数字取实际调查 ID。

## 从深圳名单开始

下载[深圳市中小企业服务局公示附件 1](https://zxqyj.sz.gov.cn/attachment/1/1671/1671112/12595049.pdf)。当前登记的是 2025 年度 2,536 家企业的公示快照。导入时会校验原件 SHA-256 和行数，并保存来源、页码及行号。

```shell
python -m pmai_agent import-city-list "<已下载的官方 PDF>"
python -m pmai_agent investigate --city 深圳 --first-row 1 --count 8 --role "Agent / 大模型应用 / FDE" --cohort 2027 --limit 4
python -m pmai_agent summarize 1 2 3 4 5 6 7 8
```

`summarize` 使用调查命令打印的实际 ID。省略企业和文档参数时使用该城市登记的官方名单。公开中文招聘搜索需要在 `.env` 配置 `DEEPSEEK_API_KEY`。每家发两次入口查询，最多核查 `--limit` 个页面。计数区分有主体证据的招聘入口、具体岗位正文和待应届生核查的岗位。手动指定企业时可加 `--web-search` 使用同一搜索方式。详见[深圳样本验收](docs/深圳样本验收.md)。

## 手动调查公开岗位

把 `.env.example` 的配置项填入本机 `.env`；已有文件只补缺项。本地接口支持 Ollama 或 llama.cpp 的 OpenAI 兼容入口。配置本地模型和 DeepSeek 时，地点交给小模型，职责、届别和时效交给 `deepseek-flash`。只配置一个模型时由该模型完成分析。模型只接收任务条件与单岗位的公开材料。演示无需配置。

腾讯及 Greenhouse 调查可用 `PMAI_LOCAL_ONLY=1` 切换到本地推理。中文网页搜索仍使用配置的 DeepSeek 搜索和招聘主体核对。公开岗位调查需要联网。

```shell
python -m pmai_agent investigate --company 腾讯 --role Agent --city 深圳 --cohort 2027 --limit 2
python -m pmai_agent investigate --company Anthropic --role Engineer --city "San Francisco" --limit 1
python -m pmai_agent investigate --document 1 --first-row 1 --count 3 --limit 2
```

导入名单后可用 `--company-id` 选择已登记主体。腾讯招聘适配器从首批最多 50 条候选中优先调查目标城市；其他企业尝试按英文名称查询 Greenhouse，再核实岗位所属公司。也可传 `--url` 指定这两类来源的岗位详情。国内中小企业覆盖仍有限。每次保存调查 ID，可用 `show` 看抓取时间、原文、引文位置、失败原因与未知项。

Windows CPU 用户可运行 `python scripts/prepare_local_model.py` 在 `data/model` 准备 llama.cpp 和 Qwen2.5-1.5B-Instruct。脚本核对固定版本的 SHA-256。启用本地服务后将服务地址与模型别名填入 `.env`。

已有 Ollama 的机器可使用 `ollama run qwen2.5:1.5b` 准备模型，再使用模板里的本地地址和名称。已有 llama-server 的机器可用 `--weights-only` 只下载权重，然后启动下列服务并配置 `PMAI_LOCAL_BASE=http://127.0.0.1:18087/v1` 和 `PMAI_LOCAL_MODEL=qwen-local`。

```shell
llama-server -m data/model/qwen-1.5b.gguf --alias qwen-local --host 127.0.0.1 --port 18087 -c 4096
```

“无法访问”可展开查看网络或来源错误。“未调查”表示当前来源缺入口。“待核查”可查看快照及被拒绝的判断。中断后使用原调查 ID 恢复；已经结束的调查再次执行 `investigate` 会保留一份新的独立记录。

## 核查与跟进

运行 `python -m pmai_agent review`，打开终端打印的本机地址。输入企业名筛选调查，打开岗位查看支持原文、未知项和页面快照。可对岗位或整次调查保存“值得跟进”“判断有误”等反馈，并下载包含证据和反馈的 JSON。查看与刷新均只读取本地调查。

在调查详情点击“保存企业线索”或“保存岗位线索”，从“我的求职清单”复制搜索词到招聘软件。清单提供“待核查”“新增未看”等筛选和 CSV 导出。保存核查进度和备注后，下次打开可继续使用。同一登记企业或来源岗位再次保存时，保留原有状态和首次保存时间，并记录新调查。

## 从相关业务发现企业

导入深圳官方名单并配置 `DEEPSEEK_API_KEY` 后，可以先查企业公开的产品、项目和技术工作。

```shell
python -m pmai_agent investigate --business --city 深圳 --first-row 1 --count 4 --role "Agent / 大模型应用 / FDE" --limit 4
python -m pmai_agent review
```

系统核对网页正文里的企业全称和业务原文。符合条件的企业进入“我的求职清单”，每个岗位方向各给一条可复制的搜索词。正文紧接企业全称明确说明简称时，也会生成简称搜索词。业务线索的岗位和届别留待核查。可用 `--company "企业全称"` 调查单家企业，另加 `--url "公开业务页"` 则核对指定页面。

也可以从业务关键词反查企业。下例与本机已经导入的深圳公示快照比对，只保存其中未出现的企业。

```shell
python -m pmai_agent prospect --city 深圳 --keywords "工业质检 视觉大模型" --outside-roster --limit 8
```

`--role` 用于生成带到招聘软件的搜索词，默认方向为 Agent、大模型应用和 FDE。命令打印网页核查结果和本次新增清单数，保存企业全称、项目原文和城市关联原文；再次找到已有企业会保留核查状态。省略 `--outside-roster` 时也会保存名单内结果；未导入本城名单时标记为“名单未比对”。
