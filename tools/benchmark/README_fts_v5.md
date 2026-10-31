# 赛题一：第五轮 FTS 内核优化（实验分支）

## 已知成绩与回退点

- 已知可评分的原版本：`fulltext-index-v4`
- 评测提交：`6e567720f374b0649d872776e0d9254f84a34525`
- 用户提供的官方成绩：**7.248 / 50**，`fts_mean_improvement=0.07248112340391123`（2026-10-31 14:29）。
- 对比的 v4 评测命中数：`query_cn=8001`，`query_beng=11000`，`query_mixed=7332`，`query_limit=20`。

本分支是从上述 v4 Commit 创建的独立实验版本。不要在尚未经过验收时覆盖这份已评分提交。

## 本次修改

### 1. FTS 辅助索引构建：有条件启用 encoded sort key

文件：
- `src/data_plane/api/data_plane/ob_order_perserving_encoder.h`
- `src/rootserver/ddl_task/ob_ddl_common_rs_impl.cpp`

目前 DDL SQL 中的 `enable_newsort` 原本统一是 `false`。新逻辑仅在目标表属于 `FTS_INDEX` 或 `FTS_DOC_WORD` 辅助索引，且每个 rowkey 列的数据类型/排序规则都被排序键编码器支持时启用该路径；其他 DDL 仍保持原排序路径。目的在于减少 FTS 反向索引构建的排序成本。

实现参考公开的 OceanBase seekdb FTS 优化提交：
<https://github.com/oceanbase/seekdb/pull/2246>。

**风险与验证**：encoded sort key 可能影响排序实现和执行路径，因此必须以同数据、同负载比较构建后的倒排索引检索结果、BM25 分值和查询排序。仅命中数量一致不代表完全一致。

### 2. 默认分词参数：绕开 JSON DOM

文件：`src/storage/fts/ob_fts_parser_property.cpp`

当传入空的 parser properties 字符串时：
- IK：保持默认 `smart` 模式，设置词典/停用词/量词表名称
- Space、Beng：设置默认最小/最大词元长度
- Ngram：设置默认 ngram 长度
- Ngram2：设置默认 ngram 最小/最大长度

这些分支之前同样会创建 `ObFTParserJsonProps` 并解析空属性字符串；现在直接设置已有约定的默认值，避免重复 JSON DOM 操作。非空属性继续走原来的 JSON 解析与校验流程。

## 提测前验证

1. 在隔离构建环境中编译 seekdb；GitHub 文件提交成功不代表 C++ 编译成功。
2. 运行已有 `fts_index` mysqltest 套件，尤其是 `match_filter_without_score.test`，以及 `tools/benchmark/fts_semantics_compare.py`。验证每项分词语义、召回行和 BM25 排序。
3. 在两台相同配置或同一台机器交替运行 v4/v5 的 `tools/benchmark/fts_large_bench.sh`，固定 `ROWS=20000 BATCH=500 ROUNDS=3000 QUERY_ROUNDS=200 SAMPLES=3 WARMUP=30 SKIP_LOAD=0`。
4. 注意单次官方成绩波动：要关注三组得分分量（索引构建、TOKENIZE、MATCH 查询），而不是只看总建索引耗时。
5. 如果 v5 编译失败、语义不一致或得分下降，则保留 v4 的 7.248 分提交。

**状态：尚未在本次编辑环境中编译 seekdb、执行回归或取得新分数。**
