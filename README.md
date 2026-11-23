# PMAI-Agent

PMAI-Agent 的目标是做一个免费、开源的求职调查 Agent，帮助大学生和其他求职者从招聘推荐列表之外发现企业，找到值得自己核查的岗位。首个使用场景是深圳的 Agent 开发、大模型应用和 FDE 机会。

给它一份企业名单、城市、方向和可选的毕业届别，它将逐家查找材料，区分招聘依据、待确认机会和企业业务线索。求职者可以从每条岗位判断回到原文，看到哪些条件还未知，再决定是否跟进。投递和联系企业由求职者自己决定。

## 项目状态

已实现本地 PDF 名单导入。首版以本地单用户为目标，计划提供无需账户的样例调查、本地模型接入和公开来源调查。代码许可证尚待维护者选定。

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
