"""拆分单元测试：一图多题按年份/题号拆分、答案键提取、退化行为。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from habit_checkin.services.split import split_question_lines

IMG1 = [
    "I. （ 2021 · 黑龙江）下列关于世界上最年轻的高原的说法， E 确、是：",
    "為",
    "A. 地热资源丰富，可发电",
    "· 在这个高原上可看到极光",
    "、巴一世界第一长河发源地",
    "D. 有世界上最高的瀑布",
    "（ 2017 · 天津）尼罗河是世界第一长河流，也是世界文明的发祥地之一",
    "向流经布隆迪、乌干达和埃及等国，最后注人：",
    "· 太平洋一北冰洋一大西洋一印度洋",
    "/ 大西洋",
    "c. 印度洋",
    "B. 地中海",
    "D. 红海",
    "3 ，（ 2017 · 河南）关于中美洲地区，下列说法 0 的是：",
    "A. 好望角属于该地区",
    "匚麦哲曾经到达这一地区",
    "' 陆地东侧有寒流经过",
    "D. 此地原住民主要是印第安人",
    "17 · 辽宁）世界上最大的丨亠家是：",
    "哈萨克斯坦",
    "c. 塔吉克斯坦",
    "B. 吉尔吉斯斯坦",
    "' 阿富汗",
    "5 ，",
    "2017 · 江西）四大洋面积从大到小的排列顺序是：",
    "B. 大西洋一太平洋一北冰洋一印度洋",
    "c. 大西洋一太平洋一印度洋一北冰洋",
    "D. 平洋一大西洋一印度洋一北冰洋",
    "答案速览",
    "ABDAD",
]

IMG2 = [
    "（ 2 25 · 江苏）本土药材：野生药材：名贵药材",
    "、海高铁：跨省高铁：城际高铁",
    "& 牛奶产业：传统产业：养殖产业",
    "C. 超限车辆：超载车辆：超重车辆丈",
    "D. 社区治理：社会治理：水．上治理",
    "2024 · 四川）政治家：军事、操",
    "2 ．",
    "固体：食品：苹果",
    "A",
    "。直辖市：港亠 i ：北京人",
    "c. 企业家：科学家：爱因斯坦",
    "步 ' 废展中国家：亚洲国家：菲律宾",
    "3 ．（ 2021 · 山东）水生动物：卵生动物",
    "A. 腔肠动物：软体动物",
    "C. 行动物：哺乳动物",
    "4 ． 2020 · 浙江）保温：玻璃杯",
    "望远镜：显微镜",
    "C 裙：真丝裙",
    "5 ． 20 ] 8 · 吉林）漫画：推理漫画：连环漫画",
    "A. 可见光：红光：紫光",
    "：对流层：中间层",
    "C.",
    "019 · 江苏）男博士：女教授：教授",
    "6 ，",
    "政治家：文学家：作家",
    "匚电动车：电冰箱：电器",
    "夕 ' 甲壳纲动物：节肢动物",
    "D. 脊椎动物：无脊椎动物",
    "B. 自行车：三轮车",
    "D. 白炽灯 :LED 灯",
    "文物：馆藏文物：史前文物",
    "D. 离子：阳离子：阴离子",
    "理数：正整数：正数",
    "D. 公路桥：铁路桥：桥梁",
    "（ 2022 · 国家）二线城市：港口城市：商业城市",
    "7",
    "· 海上战争：常规战争：空中战争",
    "B. 科技期刊：电子期刊：纸本期刊",
]


class TestSplitQuestions(unittest.TestCase):
    def test_img1_splits_into_five_with_answers(self):
        chunks = split_question_lines(IMG1)
        self.assertEqual(len(chunks), 5)
        self.assertEqual([c["analysis"] for c in chunks],
                         ["【答案】A", "【答案】B", "【答案】D", "【答案】A", "【答案】D"])
        self.assertIn("2021 · 黑龙江", chunks[0]["text"])
        self.assertIn("2017 · 天津", chunks[1]["text"])
        self.assertIn("2017 · 河南", chunks[2]["text"])
        self.assertIn("辽宁", chunks[3]["text"])
        self.assertIn("江西", chunks[4]["text"])
        self.assertNotIn("答案速览", chunks[4]["text"])

    def test_img2_splits_into_seven(self):
        chunks = split_question_lines(IMG2)
        self.assertEqual(len(chunks), 7)
        self.assertIn("江苏", chunks[0]["text"])
        self.assertIn("四川", chunks[1]["text"])
        self.assertIn("山东", chunks[2]["text"])
        self.assertIn("浙江", chunks[3]["text"])
        self.assertIn("吉林", chunks[4]["text"])
        self.assertIn("江苏", chunks[5]["text"])
        self.assertIn("国家", chunks[6]["text"])

    def test_no_boundary_returns_single_chunk(self):
        lines = ["A. 甲", "B. 乙", "C. 丙", "D. 丁"]
        chunks = split_question_lines(lines)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], "\n".join(lines))

    def test_numbered_fallback(self):
        lines = ["1. 第一题题干", "A. 甲", "B. 乙", "2. 第二题题干", "A. 丙", "B. 丁"]
        chunks = split_question_lines(lines)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0]["text"].startswith("1. 第一题题干"))
        self.assertTrue(chunks[1]["text"].startswith("2. 第二题题干"))

    def test_empty(self):
        self.assertEqual(split_question_lines([]), [])
        self.assertEqual(split_question_lines(None), [])


if __name__ == "__main__":
    unittest.main()
