# 微信资源搜索机器人 —— 轮询漏消息问题分析（供其他 AI 参考）

## 一、项目背景

微信个人号资源搜索机器人（Windows 单文件 exe，PySide6 面板 + 微信双内核）。

- 内核：`wxauto4`（免费版）→ 未激活时回落；`wxautox4`（付费 Plus）走原生回调监听。
- 当前运行环境：**免费版 wxauto4**（日志显示「wxautox 未激活，已回落到免费版 wxauto4」）。
- 打包环境：`.venv313`（Python 3.13.12 + wxauto4/wxautox4 cp313 + PyInstaller 6.22.2）。
- 入口：`gui_main.py`（PySide6 面板）、`wxbot_core.py`（底座核心，26 万字节）。

### 已确认的内核能力边界（2026-09-10 运行时内省 + 用户实测）

| API | 免费版 wxauto4 | 说明 |
|---|---|---|
| `AddListenChat` | ✅ 有 | **但实测报错「当前实例只允许监听一个聊天」** → 无法多聊监听 |
| `StartListening` / `StopListening` / `RemoveListenChat` | ✅ 有 | — |
| `GetAllSubWindow` / `GetSubWindow` | ✅ 有 | — |
| `GetAllMessage` | ✅ 有 | 底层 `C_MsgList.GetChildren()` |
| `ChatWith(who, exact=True, force=False, force_wait=0.5)` | ✅ 有 | **切窗是异步的** |
| `GetListenMessage` / `GetNextNewMessage` | ❌ 无 | Plus 专属，免费版没有 |

**结论：免费版多聊监听，只能走「ChatWith + GetAllMessage 轮询」。**

## 二、核心问题

机器人能收到并处理「搜索 关键词 网盘」，但**后续的「下一页」「8」等翻页/选号指令经常完全收不到**（连"收到消息"日志都没有）。

### 典型现象（用户 2026-09-10 15:52 日志）

```
15:52:06 处理 Silence 窗口 Silence 消息：搜索 周星驰 夸克   ← 成功
15:52:18 [轮询] Silence 窗口回缩：上轮 14 条 → 本轮 10 条   ← 条数变少
（此后用户发「下一页」「下一页」「8」，全部无日志，直到 15:53:44 停止）
```

注意：机器人回复的搜索结果很长（59 条资源，拆成多条长消息）。

## 三、已定位的两个根因（均已确认）

### 根因 1：ChatWith 切窗是异步的

`ChatWith(who, force=False)` 走「搜索/点击会话」，**点击后立即返回，不等待窗口切换完成**
（`force_wait=0.5` 只在 `force=True` 时生效）。切窗后立即 `GetAllMessage()` 会读到
**上一个窗口（文件传输助手）的残留消息**，导致轮询把错误窗口的消息计入游标/指纹。

→ 已做：切窗后 `sleep(0.4)` + 空读重试。

### 根因 2（关键）：GetAllMessage 只返回「当前已渲染/可见」的消息

底层实现（`_ref/wxauto/wxauto/wxauto.py:491`）：

```python
def GetAllMessage(self, ...):
    if not self.C_MsgList.Exists(0.2):
        return []
    MsgItems = self.C_MsgList.GetChildren()   # ← 只取当前已渲染的消息控件
    return self._getmsgs(MsgItems, ...)
```

微信聊天列表是虚拟列表，**只渲染可见区域**。若窗口没滚到底部，
**最新消息（用户刚发的「下一页」）根本不在返回列表里** —— 这就是漏指令的直接原因。

「回缩 14→10」也可由此解释：机器人回复了很长的搜索结果，每条消息占屏更高，
**可见条数从 14 降到 10**（不是"历史被顶出"）。

→ 已做：读完先 `msgs[-1].roll_into_view()` 再读一次，取条数更多的结果。
（后续又改为**迭代滚动最多 3 次**：一次 `roll_into_view` 只把「当时已知的最后一条」滚进来，
其下方可能还有未渲染的新消息，反复滚动直到条数不再增长才算真正到达底部。）

### 根因 3（最关键，2026-09-10 用户日志复现确认）：连续相同内容指令被内容指纹吞掉

现象：搜索「刘德华 夸克」成功 → 第一次「下一页」成功（第 2/8 页）→ **第二次「下一页」毫无反应**。

用户日志：

```
16:28:39 [轮询] Silence 读取 8 条 | 最新「Silence: 下一页」| 本轮新处理 1 条
16:28:50 [轮询] Silence 窗口回缩：上轮 8 条 → 本轮 3 条   ← 长回复导致可渲染条数骤降
16:28:50 [轮询] Silence 读取 3 条 | 最新「Silence: 下一页」| 本轮新处理 0 条   ← 被吞
```

推理链：

1. 机器人回复第 2/8 页（多行长消息）→ 虚拟列表可渲染条数从 8 骤降到 3。
2. 下轮 `n(3) < cursor(8)` → 判定回缩 → 改用内容指纹 `last_fp` 定位。
3. 但 `last_fp` 是「上一轮最后消费的消息」= 第一次「下一页」的 key
   `(Silence, Silence, text, "下一页")`。
4. 而**新发的第二次「下一页」key 与它完全相同** —— 无论从前往后还是从后往前找，
   都只会定位到这一条，`cursor = start + 1` 直接越过它 → **第二次翻页被静默吞掉**。

**这是内容层面的死结**：wxauto4 免费版没有「跨轮稳定且唯一」的消息 ID
（`msg.id` 唯一但切 UI 会变、`msg.hash` 切 UI 不变但可能重复，官方文档已明示），
所以两条内容相同的消息在轮询视角下不可区分。

> 补充：v2.7.3 旧版能正常翻页，**不是因为它的去重更聪明**，而是它跑在
> `wxautox4` 的 `GetNextNewMessage` 新消息轮询模式（`bot_core.py:1247 poll_loop`），
> 每条新消息只投递一次、根本不需要内容去重。它的 `legacy_poll_loop`（ChatWith 轮询）
> 其实有同样的缺陷（`extract_new_messages` 同样是「从后往前找 last_fp + `seen` 过滤」，
> 连发两次「下一页」同样会被 `seen` 挡掉）。**这条路在免费版走不通，不要照抄。**

### ✅ 最终解法（2026-09-10 已重构落地）：序列前后缀对齐，唯一性由「位置」提供

> 上一版曾用「发送后重对齐游标 + 尾部兜底」缓解，但那是又一层补丁。
> 现已按「收拢成单点」的原则重写，四层补丁全部删除。

```python
@staticmethod
def _seq_overlap(prev, cur):
    """最大 t 使 prev[-t:] == cur[:t]"""
    for t in range(min(len(prev), len(cur)), 0, -1):
        if prev[-t:] == cur[:t]:
            return t
    return 0

# _poll_loop 每轮：
cur_seq = [self._msg_key(m, who) for m in msgs]
t = self._seq_overlap(self._poll_prev_seq.get(who, []), cur_seq)
new_idx = range(t, n) if t > 0 else [i for i in range(n) if cur_seq[i] not in seen]
```

**为什么成立**：虚拟列表两轮之间的变化只有「顶部截断 + 底部追加」两种，
所以 `cur` 必然形如 `prev[k:] + 新消息`，即 **prev 的一个后缀 == cur 的一个前缀**。
取最大重叠 t 后，`cur[t:]` 就是本轮真正新增的消息。

**为什么能解决本 bug**：完全不看内容。连发 N 次「下一页」在位置上就是 N 条不同的消息，
不存在撞键。因此下面这些补丁全部删除：

| 已删除 | 它原本在补什么 |
|---|---|
| 条数游标 `_poll_count` | 回缩后条数不可比 |
| 内容指纹游标 `_poll_last_fp` + shrink 定位 | 同内容消息无法区分 |
| `is_page` 分页指令豁免 | 内容键撞车时给翻页开后门 |
| `_is_last`「最新一条」豁免 | 同上，只放行最后一条 |
| 尾部兜底 | 前面都失准时补处理末尾 |
| `_poll_resync` 发送后重对齐 | 防止回缩发生在轮询里 |

`seen` 只剩一个作用：`t == 0`（两轮窗口完全无重叠，说明读取异常）时防重放。

已验证：序列对齐**不依赖**"发送后重对齐"补丁（去掉后连续 5 次翻页仍是 5/5）。

### ⚠️ 为什么没采纳 occurrence 计数（有实测反例）

外部 AI 建议「内容键 + 该内容在窗口中出现的第几次 occurrence」，并强调
seed / mark_chat_seen / 指纹游标三处写键规则要同步。**已按最强版本实现并实测**：

`_t_dedup_compare.py` 场景 1（连续 5 次「下一页」+ 每次长回复回缩）：

| 方案 | 逐轮新处理条数 |
|---|---|
| occurrence（含完整版三处同步） | `[1, 1, 0, 0, 0]` ❌ 第 3 次起失效 |
| 序列对齐 | `[1, 1, 1, 1, 1]` ✅ |

失效原因：**occurrence 在回缩时会漂移**。回缩后旧的同内容消息被挤出虚拟列表，
窗口里「下一页」固定只剩 2 条（occ=1、occ=2），每轮算出的键组合都一样；
第 2 次翻页用掉 `(下一页, 2)` 后，第 3 次翻页算出来还是 `(下一页, 2)` → 撞 seen。
**位置不变时 occurrence 也不变**，它并没有引入新的区分度。

顺带说明：Claude 对「第三次必然失效」的失效模式诊断是准确的，只是 occurrence 修不了它。

## 四、待解决 / 想请 AI 帮忙分析的点

1. **如何可靠地让聊天窗口滚到最底部**，确保 `GetAllMessage` 一定包含最新消息？
   - 已知可用：`msg.roll_into_view()`（消息对象方法，`msgs/base.pyi:32`）。
   - 是否有更直接的方式（如操作 `C_MsgList` 滚轮、SendKeys End 键、或其他 wxauto4 能力）？
   - 该库为闭源 `.pyd`，无法看实现；官方 `wx.pyi` 只暴露了 `GetAllMessage/ChatWith/GetSession/GetMyInfo/GetAllSubWindow/GetSubWindow`。

2. **去重策略**：`msg.id`（唯一但切 UI 后变）、`msg.hash`（切 UI 后不变但可能重复）——
   两个字段各有缺陷。当前用 `(会话名, 发送人, 类型, 内容)` 做内容级去重，
   导致「连续两次「下一页」」key 相同，需要靠"分页指令豁免 seen"绕开。有无更稳的方案？

3. **整体架构**：在「免费版无 GetListenMessage、AddListenChat 只能监听一个」的硬约束下，
   有没有比「ChatWith 轮询」更好的多聊监听方案？

## 五、已尝试过的方案（含失败记录，避免重复踩坑）

| 方案 | 结果 |
|---|---|
| 每轮末尾 `ChatWith(文件传输助手)` 切回 | ❌ 每轮多切一次窗口，加重竞态，**已按用户要求去掉** |
| 切窗后 `sleep(0.4)` + 空读重试 | 有缓解，但未根治 |
| `n==0` 时空读保护（不动游标/指纹） | ✅ 有效，已保留 |
| 分页指令仅 `rescan_all` 时才查 seen | ✅ 有效（修复"第二次翻页被误判已处理"），已保留 |
| 免费版改走 `AddListenChat` 回调监听 | ❌ **失败**：实测「当前实例只允许监听一个聊天」（已 revert） |
| 参考 `wx_cloud_search_plus/wx_driver.py` | ❌ 它用 `GetListenMessage()`，但**免费版无此 API**，其轮询会一直走异常分支 |
| 指纹游标改「从前往后」找 last_fp | ❌ **无效**：两次「下一页」在回缩后的窗口里只出现一次，正着找反着找结果一样 |
| 分页指令「最新一条」豁免 seen | ✅ 有效，作为第二道保险保留 |
| 照搬 v2.7.3 的 `dedup_window` 短时窗去重 | ❌ 未采用：它解决不了「回缩后 key 相同导致 cursor 越过」的问题，且会引入周期性重放 |
| **发送后重对齐游标（`_mark_chat_seen`）** | ✅ **本次主修复，已通过回归测试** |

## 六、关键代码位置（`wxbot_core.py`）

- `_WxSendRecorder.read_messages()` —— 切窗 + 等待渲染 + 滚动 + 读取（本次新增滚动）
- `WXBot._poll_loop()` —— 轮询主循环（条数游标 + 指纹游标 + seen 去重 + 详细日志）
- `WXBot._msg_key()` / `_is_page_cmd()` —— 去重键与分页指令识别
- `WXBot._seed_poll_seen()` —— 启动时标记历史消息，避免启动即回放
- `WXBot._mark_chat_seen()` —— 发送后只标记自己的回显（不吞用户指令）
- `init_wx_listeners()` —— 免费版走 `_start_poll_listeners()`，Plus 版走回调监听

回归测试：`_t_poll_regression.py`（13 个场景，纯内存模拟，不依赖 wxauto）。
其中场景 9A/9B/9C 精确复现上述用户场景的三种子情形（长回复可见 / 不可见 / 未即时渲染），
并已反向验证：关掉「发送后重对齐」后场景 9A 返回空 → 测试确实能抓到该 bug。

运行方式：

```bash
"D:/python/python.exe" _t_poll_regression.py
```
