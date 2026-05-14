# P16 — 乐观 UI 更新：所有操作优先同步本地 state/task_state.json

**状态:** Active  
**优先级:** P1  
**开始:** 2026-05-14  
**负责人:** AgenticOS  

---

## 原则

所有用户操作遵循同一模式：

```
用户点击
  ↓
立即更新本地 state/task_state.json（文件写 + 内存缓存）
立即更新 UI（关闭弹窗 / 刷新面板）
  ↓（fire-and-forget，不 await）
异步同步到 Linear API
```

---

## 当前慢操作

| # | 操作 | 触发方式 | 当前行为 |
|---|------|---------|---------|
| 1 | Cancel | `cancelLinearIssue()` | PATCH 到 Linear API，等返回才关弹窗 |
| 2 | Cancel (card) | `cancelLinearIssueById()` | 同上 |
| 3 | Save to Linear | `saveLinearIssue()` | POST/PATCH 到 Linear API，等返回 |
| 4 | 状态变更 (dropdown) | `linear-edit-state` onChange | 发送 PATCH |
| 5 | Dispatch (▶) | `dispatchFromDetail()` | PATCH state + preferred_agent，等返回 |
| 6 | Approve (In Review → Done) | `approveLinearIssue()` | PATCH state，等返回 |
| 7 | Comment/Feedback 提交 | `submitReply()` | POST comment + PATCH 状态 |

---

## 执行计划

### Phase 1 — 后端本地同步路由

**文件：** `runner/modules/linear/__init__.py`

新增 `PATCH /api/linear/issues/local/<issue_id>` 路由，只写本地不调 Linear API：

```python
@self._route("/api/linear/issues/local/<issue_id>", methods=["PATCH"])
def _local_sync_handler(issue_id):
    data = request.get_json() or {}
    if issue_id in self.issues_cache:
        self.issues_cache[issue_id].update(data)
    local = self.get_local_tracker()
    if "state_name" in data:
        local.update_issue_state(issue_id, data["state_name"])
    if "preferred_agent" in data:
        local.set_issue_agent(issue_id, data["preferred_agent"])
    return jsonify({"ok": True})
```

**依赖：** `local_tracker.py` 需要 `set_issue_agent()` 方法。

**完成标准：**
- [ ] `PATCH /api/linear/issues/local/<id>` 实现
- [ ] 只写本地，不调 Linear API

---

### Phase 2 — 前端乐观更新

**文件：** `runner/templates/index.html`

逐操作改为乐观模式，共用函数：

**Cancel（✅ 已完成）**
- `cancelLinearIssue()`: 关弹窗 → 刷新面板 → fire-and-forget PATCH

**Save to Linear**
- `saveLinearIssue()`: 写本地 state → fire-and-forget PATCH

**状态变更**
- `linear-edit-state` onChange: 写本地 state → fire-and-forget PATCH

**Dispatch**
- `dispatchFromDetail()`: 本地写 state → fire-and-forget PATCH

**Approve**
- `approveLinearIssue()`: 本地写 state → fire-and-forget PATCH

**Comment/Feedback**
- `submitReply()`: 本地写 → fire-and-forget PATCH

**Card-level Cancel**
- `cancelLinearIssueById()`: 乐观更新

**完成标准：**
- [ ] 所有 7 个操作用户点击后 < 50ms 响应
- [ ] API 调用 fire-and-forget，不阻塞 UI

---

### Phase 3 — 验证

1. 点击 Cancel → 弹窗即时关闭
2. 修改状态/标题/评论 → UI 即时更新
3. 断开网络 → 本地操作仍然流畅
4. 恢复网络 → 轮询线程最终一致

---

## 非目标

- ❌ 不改 Linear API 全量轮询
- ❌ 不改 PTY/SSE/SSH
- ❌ 不改 dispatch 线程行为

---

## 风险

| 风险 | 缓解 |
|------|------|
| Linear API 失败后数据不一致 | 轮询线程最终修复 |
| 并发 fire-and-forget 排队 | 无副作用 |
| 本地写失败 | catch 静默 |
