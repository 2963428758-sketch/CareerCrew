# RAG 检索增强生成

RAG（Retrieval-Augmented Generation）通过检索外部知识库增强大模型生成，减少幻觉。

## 检索流程
RAG 标准流程：query 编码 -> 向量检索召回 -> rerank 精排 -> 拼接上下文 -> 生成答案。两段式架构（召回+精排）平衡查准与查全。

## BGE-M3
BGE-M3 是三合一 embedding 模型，同时输出 dense、sparse、colbert 三路向量，支持多语言、长文本（8192 token）。稀疏路免额外 BM25 倒排索引。

## Hybrid 检索与 RRF
Hybrid 检索结合 dense（语义）和 sparse（关键词）两路召回，用 RRF（Reciprocal Rank Fusion）融合。RRF 用排名倒数 1/(k+rank) 而非分数，避免不同检索器分数量纲不一致。

## Contextual Chunking
Anthropic Contextual Retrieval：ingestion 时用 LLM 给每块生成文档级上下文前置再做 embedding，减少 49% 检索失败，叠加 rerank 降 67%。
