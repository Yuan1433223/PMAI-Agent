"""Official candidate pools. A source version pins the actual attachment."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CityList:
    city: str
    year: int
    status: str
    publication: str
    attachment: str
    digest: str
    count: int
    title: str


SHENZHEN = CityList(
    city="深圳",
    year=2025,
    status="公示",
    publication="https://zxqyj.sz.gov.cn/gkmlpt/content/12/12595/post_12595049.html",
    attachment="https://zxqyj.sz.gov.cn/attachment/1/1671/1671112/12595049.pdf",
    digest="94f04587ef1d100b654428fea9119b9f89ae86fe6d84358359577c92df1ff03e",
    count=2536,
    title="2025年深圳市专精特新中小企业名单",
)

CITY_LISTS = {SHENZHEN.city: SHENZHEN}
