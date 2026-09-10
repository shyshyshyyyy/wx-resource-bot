# -*- coding: utf-8 -*-
"""去重方案三方对比：A=当前代码(内容键+四层补丁) / B=Claude 提的 occurrence 计数 / C=序列对齐。

Claude 的诊断（主键无唯一性 → 所有豁免都是补丁）是对的，但他提的
「内容键 + 该内容在窗口中出现的第几次 occurrence」在**窗口回缩**时会漂移：
回缩后旧的同内容消息被挤出虚拟列表，新消息的 occurrence 重新从 1 开始，
键又撞上了 —— 而回缩恰恰是本 bug 的触发场景。

本脚本用同一组场景跑三个方案，输出对比结果。
"""
import time


class M:
    def __init__(self, attr, sender, typ, content):
        self.attr, self.sender, self.type, self.content = attr, sender, typ, content

    def __repr__(self):
        return f"<{self.attr}:{self.content[:12]}>"


def fr(c, s="Silence"):
    return M('friend', s, 'text', c)


def slf(c):
    return M('self', '机器人', 'text', c)


def ckey(m, who="Silence"):
    """内容主键（当前 _msg_key，不含 attr）"""
    return (who, m.sender, m.type, m.content)


# ---------------- A：当前代码（内容键 + 条数游标 + 指纹游标 + is_page/_is_last 豁免 + 尾部兜底）
class A:
    NAME = "A 当前代码（内容键+四层补丁）"

    def __init__(self):
        self.seen, self.count, self.fp, self.resync, self.ready = {}, {}, {}, {}, set()

    def mark_sent(self, who, msgs):
        for m in msgs:
            if m.attr == 'self':
                self.seen.setdefault(who, set()).add(ckey(m, who))
        if msgs:
            self.count[who] = len(msgs)
            self.fp[who] = ckey(msgs[-1], who)
            self.resync[who] = True

    def seed(self, who, msgs):
        seen = self.seen.setdefault(who, set())
        for m in msgs:
            seen.add(ckey(m, who))
        self.count[who] = len(msgs)
        if msgs:
            self.fp[who] = ckey(msgs[-1], who)
        self.ready.add(who)

    def poll(self, who, msgs):
        n = len(msgs)
        if n == 0:
            return []
        seen = self.seen.setdefault(who, set())
        cur, shrink = self.count.get(who, 0), n < self.count.get(who, 0)
        rescan = False
        if shrink:
            lf = self.fp.get(who)
            start = -1
            if lf:
                for i in range(n):
                    if ckey(msgs[i], who) == lf:
                        start = i
                        break
            cur, rescan = (start + 1, False) if start != -1 else (0, True)
        out, handled = [], set()
        for i in range(cur, n):
            m, k = msgs[i], ckey(msgs[i], who)
            is_last, is_page = i == n - 1, m.content.strip() == "下一页"
            if (not is_page) and k in seen:
                continue
            if is_page and (not is_last) and k in seen:
                continue
            seen.add(k)
            handled.add(k)
            if m.attr in ('self', 'system') or m.type == 'time':
                continue
            out.append(m.content)
        # 尾部兜底
        t = msgs[-1]
        if who in self.ready and t.attr not in ('self', 'system') and t.type != 'time':
            tk = ckey(t, who)
            if tk not in handled and tk not in seen:
                seen.add(tk)
                out.append(t.content)
        if not self.resync.pop(who, False):
            self.count[who] = n
            if msgs:
                self.fp[who] = ckey(msgs[-1], who)
        self.ready.add(who)
        return out


# ---------------- B：Claude 的方案（内容键 + occurrence，删掉 is_page/_is_last 豁免）
class B:
    NAME = "B occurrence 计数（Claude 方案）"

    def __init__(self):
        self.seen, self.count, self.resync = {}, {}, {}

    def mark_sent(self, who, msgs):
        for m in msgs:
            if m.attr == 'self':
                self.seen.setdefault(who, set()).add(ckey(m, who))
        if msgs:
            self.count[who] = len(msgs)
            self.resync[who] = True

    def seed(self, who, msgs):
        seen = self.seen.setdefault(who, set())
        occ = {}
        for m in msgs:
            k = ckey(m, who)
            occ[k] = occ.get(k, 0) + 1
            seen.add(k + (occ[k],))
        self.count[who] = len(msgs)

    def poll(self, who, msgs):
        n = len(msgs)
        if n == 0:
            return []
        seen = self.seen.setdefault(who, set())
        occ, keys = {}, []
        for m in msgs:                      # occurrence = 该内容在本窗口出现的第几次
            k = ckey(m, who)
            occ[k] = occ.get(k, 0) + 1
            keys.append(k + (occ[k],))
        start = self.count.get(who, 0)
        if start > n:                       # 回缩：退化成整段重扫
            start = 0
        out = []
        for i in range(start, n):
            m, k = msgs[i], keys[i]
            if k in seen:                   # 无 is_page / _is_last 豁免
                continue
            seen.add(k)
            if m.attr in ('self', 'system') or m.type == 'time':
                continue
            out.append(m.content)
        if not self.resync.pop(who, False):
            self.count[who] = n
        return out


# ---------------- B2：Claude 完整方案（occurrence + 条数游标 + 指纹游标，三处写键规则统一）
class B2:
    NAME = "B2 occurrence 完整版（含指纹游标同步）"

    def __init__(self):
        self.seen, self.count, self.fp, self.resync = {}, {}, {}, {}

    def _keys(self, who, msgs):
        """按整段列表预扫 occurrence：第几次出现 —— 与 Claude 给的伪代码一致"""
        occ, out = {}, []
        for m in msgs:
            bk = ckey(m, who)
            occ[bk] = occ.get(bk, 0) + 1
            out.append(bk + (occ[bk],))
        return out

    def seed(self, who, msgs):
        ks = self._keys(who, msgs)                 # 种子也用 occurrence 键
        self.seen.setdefault(who, set()).update(ks)
        self.count[who] = len(msgs)
        if ks:
            self.fp[who] = ks[-1]

    def mark_sent(self, who, msgs):
        ks = self._keys(who, msgs)                 # 发送后对齐也用 occurrence 键
        for m, k in zip(msgs, ks):
            if m.attr == 'self':
                self.seen.setdefault(who, set()).add(k)
        if msgs:
            self.count[who] = len(msgs)
            self.fp[who] = ks[-1]                  # 指纹游标也存 occurrence 键
            self.resync[who] = True

    def poll(self, who, msgs):
        n = len(msgs)
        if n == 0:
            return []
        seen = self.seen.setdefault(who, set())
        ks = self._keys(who, msgs)
        cur = self.count.get(who, 0)
        if n < cur:                                # 回缩：用指纹游标定位（从前往后找最早匹配）
            lf = self.fp.get(who)
            start = -1
            if lf:
                for i in range(n):
                    if ks[i] == lf:
                        start = i
                        break
            cur = start + 1 if start != -1 else 0
        out = []
        for i in range(cur, n):
            m, k = msgs[i], ks[i]
            if k in seen:                          # is_page/_is_last 已成死代码，不生效
                continue
            seen.add(k)
            if m.attr in ('self', 'system') or m.type == 'time':
                continue
            out.append(m.content)
        if not self.resync.pop(who, False):
            self.count[who] = n
            if msgs:
                self.fp[who] = ks[-1]
        return out


# ---------------- C：序列对齐（prev 的后 t 条 == cur 的前 t 条，未匹配的 cur[t:] 即新增）
def overlap(prev, cur):
    for t in range(min(len(prev), len(cur)), 0, -1):
        if prev[-t:] == cur[:t]:
            return t
    return 0


class C:
    NAME = "C 序列对齐（位置感知，无内容豁免）"

    def __init__(self):
        self.seen, self.prev = {}, {}

    def mark_sent(self, who, msgs):
        for m in msgs:
            if m.attr == 'self':
                self.seen.setdefault(who, set()).add(ckey(m, who))
        if msgs:                            # 发送后把序列对齐到含回复的真实状态
            self.prev[who] = [ckey(m, who) for m in msgs]

    def seed(self, who, msgs):
        self.seen.setdefault(who, set()).update(ckey(m, who) for m in msgs)
        self.prev[who] = [ckey(m, who) for m in msgs]

    def poll(self, who, msgs):
        n = len(msgs)
        if n == 0:
            return []
        seen = self.seen.setdefault(who, set())
        cur = [ckey(m, who) for m in msgs]
        prev = self.prev.get(who, [])
        t = overlap(prev, cur)
        if t > 0:
            new_idx = range(t, n)           # 对齐成功：只看位置，不查 seen
        else:
            new_idx = [i for i in range(n) if cur[i] not in seen]   # 无法对齐：seen 防重放
        out = []
        for i in new_idx:
            m = msgs[i]
            seen.add(cur[i])
            if m.attr in ('self', 'system') or m.type == 'time':
                continue
            out.append(m.content)
        self.prev[who] = cur
        return out


# ================= 场景 =================
def run(title, builds, script, expect):
    """script: [(本轮窗口, 机器人是否在本轮处理后发送, 发送后读到的窗口)] -> {方案: 处理结果列表}"""
    print(f"\n{'='*78}\n{title}\n{'='*78}")
    res = {}
    for cls in (A, B, B2, C):
        sim = cls()
        got = []
        sim.seed("Silence", script[0][0])      # 首轮作为启动 seed：只登记不处理
        for msgs, do_send, after in script[1:]:
            r = sim.poll("Silence", msgs)
            got.extend(r)
            if do_send:
                sim.mark_sent("Silence", after if after is not None else msgs)
        res[cls.NAME] = got
        ok = "✅" if got == expect else "❌"
        print(f"  {ok} {cls.NAME}\n      处理序列: {got}\n      期望:     {expect}")
        if got != expect and verbose:
            sim = cls()
            sim.seed("Silence", script[0][0])
            per = []
            for msgs, do_send, after in script[1:]:
                r = sim.poll("Silence", msgs)
                per.append(len(r))
                if do_send:
                    sim.mark_sent("Silence", after if after is not None else msgs)
            print(f"      ↳ 逐轮新处理条数: {per}  （1=该轮翻页被执行，0=被吞）")
    return res


NX = "下一页"
R2 = "🔵 第2/8页 结果（多行长消息）"
R3 = "🔵 第3/8页 结果（多行长消息）"
R4 = "🔵 第4/8页 结果（多行长消息）"

# 场景1：连续 5 次「下一页」，机器人长回复导致窗口回缩（8→3）
s1 = [
    ([fr("搜索 刘德华 夸克"), slf(R2)], False, None),          # seed
    ([fr("搜索 刘德华 夸克"), slf(R2), fr(NX)], True,
     [fr("搜索 刘德华 夸克"), slf(R2), fr(NX), slf(R3)]),      # 第1次翻页 → 回复
    ([fr(NX), slf(R3), fr(NX)], True, [fr(NX), slf(R3), fr(NX), slf(R4)]),   # 回缩8→3，第2次翻页
    ([fr(NX), slf(R4), fr(NX)], True, [fr(NX), slf(R4), fr(NX), slf(R2)]),   # 第3次
    ([fr(NX), slf(R2), fr(NX)], True, [fr(NX), slf(R2), fr(NX), slf(R3)]),   # 第4次
    ([fr(NX), slf(R3), fr(NX)], True, [fr(NX), slf(R3), fr(NX), slf(R4)]),   # 第5次
]
run("场景1 连续 5 次「下一页」+ 长回复回缩（用户真实场景）", (A, B, C), s1,
    [NX] * 5)

# 场景2：不回缩，连续 3 次翻页
s2 = [
    ([fr("搜索"), slf(R2)], False, None),
    ([fr("搜索"), slf(R2), fr(NX)], True, [fr("搜索"), slf(R2), fr(NX), slf(R3)]),
    ([fr("搜索"), slf(R2), fr(NX), slf(R3), fr(NX)], True,
     [fr("搜索"), slf(R2), fr(NX), slf(R3), fr(NX), slf(R4)]),
    ([fr("搜索"), slf(R2), fr(NX), slf(R3), fr(NX), slf(R4), fr(NX)], True,
     [fr("搜索"), slf(R2), fr(NX), slf(R3), fr(NX), slf(R4), fr(NX), slf(R2)]),
]
run("场景2 不回缩，连续 3 次翻页", (A, B, C), s2, [NX] * 3)

# 场景3：启动不重放历史 + 空读恢复
s3 = [
    ([fr("旧1"), fr("旧2"), slf("旧3")], False, None),
    ([], False, None),                                   # 空读
    ([fr("旧1"), fr("旧2"), slf("旧3"), fr(NX)], True,
     [fr("旧1"), fr("旧2"), slf("旧3"), fr(NX), slf(R2)]),
]
run("场景3 启动不重放历史 + 空读恢复后处理新指令", (A, B, C), s3, [NX])

# 场景4：一轮内用户连发两条不同指令
s4 = [
    ([fr("旧1")], False, None),
    ([fr("旧1"), fr("搜索 A"), fr("搜索 B")], True,
     [fr("旧1"), fr("搜索 A"), fr("搜索 B"), slf("结果")]),
]
run("场景4 一轮内连发两条不同指令（都要处理）", (A, B, C), s4, ["搜索 A", "搜索 B"])

# 场景5：完全无新消息时不重放
s5 = [
    ([fr("旧1"), fr("旧2")], False, None),
    ([fr("旧1"), fr("旧2")], False, None),
    ([fr("旧2")], False, None),                          # 回缩但无新消息
]
run("场景5 无新消息（含回缩）不重放", (A, B, C), s5, [])

print("\n" + "=" * 78)
