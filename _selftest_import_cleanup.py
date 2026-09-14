# -*- coding: utf-8 -*-
"""v1.2.3 回归自测：本地导入 + 定时清理。用临时 data 目录，不污染项目。"""
import os, sys, json, tempfile, time

# 把项目根加入路径（本文件就在项目根）
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import core.paths as CP
TMP = tempfile.mkdtemp(prefix="wxbot_selftest_")
CP.data_dir = lambda: TMP          # 重定向所有落盘到临时目录

ok = []
def check(name, cond):
    ok.append((name, cond))
    print(("PASS" if cond else "FAIL"), name)

# ---------- 1. 导入解析（xlsx）----------
import openpyxl
from search import imported as IMP

xlsx = os.path.join(TMP, "res.xlsx")
wb = openpyxl.Workbook()
ws = wb.active
ws.append(["名称", "链接", "提取码", "网盘类型", "是否自己的"])
ws.append(["电影A", "https://pan.quark.cn/s/aaa", "1234", "夸克", "是"])
ws.append(["电影B", "https://pan.baidu.com/s/bbb", "", "百度", "否"])
ws.append(["电影C", "https://drive.uc.cn/s/ccc", "", "", "1"])   # 类型留空自动识别 + own
ws.append(["坏行", "", ""])                                       # 缺链接，应跳过
wb.save(xlsx)

cnt, errs = IMP.import_table(xlsx)
check("xlsx 导入条数=3", cnt == 3)
check("xlsx 跳过坏行=1", len(errs) == 1)

items = IMP.load_imported()
own_titles = {i["title"] for i in items if i.get("own")}
check("own 标记含 电影A/电影C", {"电影A", "电影C"} <= own_titles)
check("非 own 含 电影B", "电影B" in {i["title"] for i in items})
check("夸克类型识别", any(i["title"] == "电影A" and i["pan"] == "quark" for i in items))
check("百度类型识别", any(i["title"] == "电影B" and i["pan"] == "baidu" for i in items))
check("留空类型自动嗅探 uc", any(i["title"] == "电影C" and i["pan"] == "uc" for i in items))

# ---------- 2. 搜索过滤 ----------
r = IMP.search_imported("电影")
check("search_imported 关键词命中3", len(r) == 3)
r2 = IMP.search_imported("电影", pan="baidu")
check("search_imported pan 过滤", len(r2) == 1 and r2[0]["title"] == "电影B")
r3 = IMP.search_imported("不存在")
check("search_imported 无命中=0", len(r3) == 0)

# ---------- 3. 多文件合并 / 同名替换 / 单独移除 ----------
csvp = os.path.join(TMP, "res.csv")
with open(csvp, "w", encoding="utf-8-sig", newline="") as f:
    f.write("title,url,own\n")
    f.write("剧集X,https://pan.xunlei.com/s/xxx,TRUE\n")     # 列对齐
cnt2, _ = IMP.import_table(csvp)
# 关键：导入第二个文件不应清除第一个（客户反馈的 bug）
check("多文件共存：xlsx(3)+csv(1)=4", IMP.count_imported() == 4)
check("csv own=TRUE 识别", any(i.get("own") is True and i["title"] == "剧集X"
                               for i in IMP.load_imported()))
check("数据集个数=2", len(IMP.load_datasets()) == 2)

# 同一文件再次导入 => 替换（不翻倍）
cnt2b, _ = IMP.import_table(csvp)
check("同名重导替换不翻倍=4", IMP.count_imported() == 4)
check("同名重导后数据集仍=2", len(IMP.load_datasets()) == 2)

# 单独移除 csv 数据集
removed = IMP.remove_imported(csvp)
check("remove_imported 移除1个", removed == 1)
check("移除后总数回到3", IMP.count_imported() == 3)
check("移除后数据集=1", len(IMP.load_datasets()) == 1)

# 旧版扁平格式兼容（v1.2.3 之前是 item 列表，不是数据集列表）
with open(os.path.join(TMP, "imported.json"), "w", encoding="utf-8") as f:
    json.dump([{"title": "老数据", "url": "https://x", "pan": "", "own": False,
                "source": "本地导入", "datetime": "", "size": "", "origin": "imported"}],
              f, ensure_ascii=False)
check("旧版扁平格式可读取", any(i["title"] == "老数据" for i in IMP.load_imported()))

IMP.clear_imported()
check("clear_imported 后=0", IMP.count_imported() == 0)

# ---------- 4. 转存记录 + 定时清理 ----------
from transfer import base as TB
from transfer import cleanup as TC

# 用唯一 pan key，避免被 transfer/adapters.py 里真实的 quark 适配器覆盖注册
@TB.register("selftestpan")
class FakeQ(TB.BaseAdapter):
    IMPLEMENTED = True
    calls = []
    def check(self): return True, "ok"
    def list_dir(self, parent_id="0"): return []
    def save(self, share_url, password="", target_dir_id=""): return ["F1", "F2"]
    def share(self, file_ids, title="", expire_days=0): return TB.ShareResult(url="u", password="")
    def cleanup(self, file_ids):
        FakeQ.calls.append(list(file_ids)); return True

cfg = {"transfer": {"cleanup": {"enabled": True, "time": "03:00", "older_than_days": 1},
                    "accounts": [{"id": "acc1", "pan": "selftestpan", "cookie": "x", "enabled": True}]}}

TC.record_transfer("selftestpan", "acc1", ["F1", "F2"], title="t", url="u")
# 把记录回退到 2 天前，确保超过保留期（older_than_days=1）
_ent = TC.load_log()[0]
_ent["ts"] = int(time.time()) - 2 * 86400
TC.save_log([_ent])
log = TC.load_log()
check("record_transfer 写入1条", len(log) == 1)

# 超过保留期 + 账号存在 -> 真删
done, msg = TC.cleanup_due(cfg, save_fn=lambda c: None)
check("cleanup_due 清理1批", done == 1)
check("fake 适配器 cleanup 被调用", FakeQ.calls == [["F1", "F2"]])
check("清理后日志清空", TC.load_log() == [])

# 账号不存在 -> 不清、保留
TC.record_transfer("selftestpan", "ghost", ["F9"], title="t", url="u")
_ent2 = TC.load_log()[0]
_ent2["ts"] = int(time.time()) - 2 * 86400
TC.save_log([_ent2])
done2, _ = TC.cleanup_due(cfg, save_fn=lambda c: None)
check("账号缺失时不删(保留)", done2 == 0 and len(TC.load_log()) == 1)
IMP.clear_imported()  # 顺手清空

# ---------- 5. own_resource 模板渲染 ----------
from core import template as TPL
tpl = TPL.render("✅「{title}」是你的自有资源，无需转存，原链接如下：\n{url}",
                 title="电影A", url="https://pan.quark.cn/s/aaa")
check("own_resource 模板渲染", "电影A" in tpl and "https://pan.quark.cn/s/aaa" in tpl)

print("\n==== 结果 ====")
fails = [n for n, c in ok if not c]
print("通过 %d / %d" % (sum(1 for _, c in ok if c), len(ok)))
if fails:
    print("失败项：", fails)
    sys.exit(1)
print("ALL PASS")
