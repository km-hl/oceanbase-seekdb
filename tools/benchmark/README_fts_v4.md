# 赛题一：第四轮实验（安全的检索结果 LIMIT）

## 已验证的成绩回退点

- 已评分分支：`fulltext-index-tuning`
- 已评分提交：`e670394a2dc36ac0761f543e7c7603d5b2c7d256`
- 用户 2026-10-31 13:55 的官方记录：**5.124 / 50**，`fts_mean_improvement=0.05124033957599561`。
- 四项 MATCH 命中量：8001 / 11000 / 7332 / 20。
- 本实验分支 `fulltext-index-v4` 从上述提交创建，不修改已评分分支。

## 这一轮的核心假设

大多数检索操作已使用 `ObDASLegacyTRMergeIter::create_sparse_retrieval_iter()`，但它原来只从 **倒排扫描子节点** 获取 `limit_param_`。含有附加 DAS 任务的 table scan 在 `ObTableScanOp::init_das_scan_rtdef()` 中默认禁止 `LIMIT` 下推。因此，对于无 ORDER BY 的 `MATCH ... LIMIT 20`，底层合并迭代器可能扫描远多于 20 个匹配文档。

直接将 `LIMIT` 写入倒排扫描子节点不安全：每个 query token 的 posting 列表可能先被截断，导致本来能匹配的文档被漏掉。

本实验单独把最终检索结果限制作为运行时 `retrieval_limit_param_` 保存在 `ObDASIRScanRtDef`，**不修改倒排表扫描的 limit**。合并迭代器只在匹配文档通过内部 MATCH 过滤后停止。

为了避免改变其他算子语义，仅在下列条件全部满足时启用：IR attach 节点是根节点、表扫描已有显式有效的正数 LIMIT、没有 OFFSET、没有额外的表扫描过滤器或存储下推过滤器、没有 index-back/lookup。否则沿用旧逻辑。

新增文件变更：
- `src/sql/das/ob_das_ir_define.h`
- `src/sql/engine/table/ob_table_scan_op.cpp`
- `src/observer/composition/retrieval/ob_das_legacy_tr_merge_iter.cpp`
- 扩展 `tools/deploy/mysql_test/test_suite/fts_index/t/match_filter_without_score.test` 和对应 result 文件

## 验证步骤（尚未运行）

1. 使用 `2026-competition` 和 `fulltext-index-v4` 编译 seekdb Release 版，确保 C++ 编译通过。
2. 按仓库文档运行 `fts_index` 测试套件（尤其 `match_filter_without_score`），验证没有改变 MATCH 命中、BM25 排序、LIMIT/OFFSET 的语义。
3. 两版数据与执行参数保持一致，运行 `tools/benchmark/fts_large_bench.sh`，检查四项 `*_hits`、比较 `query_limit_avg_ms` 和整体三大类平均改善率。
4. 至少 A/B 交替进行两次评分；避免将单次波动误认为真实加速。
5. 如果发现新提交有编译错误、查询缺失、回归失败或综合性能降低，请继续使用已确认 5.124 分的原提交；**本轮实验尚未证实能提高分数**。

> 安全提示：所有 GitHub 仓库地址请使用 `https://github.com/km-hl/oceanbase-seekdb` 这类不带访问令牌的形式。令牌如已被公开，应立即撤销并更换。
