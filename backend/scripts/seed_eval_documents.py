"""为检索质量评测创建固定语料（幂等：按 eval_seed 元数据先删后建）。

用法（需已完成 alembic upgrade head 并创建默认用户）：

    python scripts/seed_eval_documents.py

每份资料内容围绕一个独特主题词展开，评测集
`scripts/retrieval_eval_set.ci.jsonl` 用这些主题词作为 expected_keywords。
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document
from app.schemas.document import NoteCreate
from app.services import document_service

EVAL_SEED_TAG = "eval-seed"

# (标题, 主题词, 正文段落列表)。主题词在语料中唯一出现，保证评测确定性。
EVAL_DOCUMENTS = [
    (
        "光合作用入门",
        "光合作用",
        [
            "光合作用是植物利用光能将二氧化碳和水转化为有机物的过程。",
            "叶绿体中的叶绿素吸收光能，光反应阶段产生 ATP 和 NADPH。",
            "暗反应阶段通过卡尔文循环固定二氧化碳，生成葡萄糖。",
        ],
    ),
    (
        "贝叶斯定理笔记",
        "贝叶斯定理",
        [
            "贝叶斯定理描述了在已知先验分布的条件下如何更新后验概率。",
            "P(A|B) = P(B|A) * P(A) / P(B) 是贝叶斯定理的标准形式。",
            "朴素贝叶斯分类器假设特征之间条件独立，广泛用于文本分类。",
        ],
    ),
    (
        "哥德巴赫猜想简介",
        "哥德巴赫猜想",
        [
            "哥德巴赫猜想声称任何大于 2 的偶数都可以表示为两个素数之和。",
            "这一猜想至今未被证明，陈景润证明了 1+2 的弱化形式。",
            "数值验证已经覆盖了极大范围，但一般证明仍然缺失。",
        ],
    ),
    (
        "潮汐锁定现象",
        "潮汐锁定",
        [
            "潮汐锁定指天体自转周期与公转周期相同，始终以同一面朝向伴星。",
            "月球被地球潮汐锁定，因此我们永远只能看到月球的正面。",
            "潮汐力源于引力梯度，随距离衰减得比引力本身更快。",
        ],
    ),
    (
        "发酵与酵母",
        "酵母发酵",
        [
            "酵母发酵是酵母菌将糖类转化为乙醇和二氧化碳的代谢过程。",
            "面包蓬松的结构来自酵母发酵产生的二氧化碳气泡。",
            "控制温度和糖浓度可以调节酵母发酵的速率。",
        ],
    ),
    (
        "向量数据库索引",
        "向量索引",
        [
            "向量索引支持在高维空间中做近似最近邻查询。",
            "pgvector 提供的 HNSW 索引在查询时使用 ef_search 控制候选队列。",
            "构建向量索引时需要在召回率和内存占用之间做权衡。",
        ],
    ),
    (
        "罗马水道工程",
        "罗马水道",
        [
            "罗马水道依靠缓慢的重力坡度把水从山区输送到城市。",
            "罗马水道的拱券结构减少了材料用量并保持长期稳定。",
            "沉淀池和通风井是罗马水道维护水质的常见设计。",
        ],
    ),
    (
        "季风气候特点",
        "季风气候",
        [
            "季风气候的特点是雨热同期，夏季降水集中。",
            "海陆热力性质差异是季风气候形成的根本原因。",
            "季风气候区农业生产对降水的季节分布非常敏感。",
        ],
    ),
    (
        "珊瑚白化原因",
        "珊瑚白化",
        [
            "珊瑚白化是珊瑚虫在高温胁迫下排出共生藻类的现象。",
            "海水温度持续升高是珊瑚白化的主要诱因。",
            "失去共生藻类后珊瑚仍能短期存活，但长期会死亡。",
        ],
    ),
    (
        "青霉素的发现",
        "青霉素",
        [
            "青霉素是最早投入大规模使用的抗生素。",
            "弗莱明在清洗培养皿时偶然发现了青霉素的抑菌作用。",
            "青霉素通过干扰细菌细胞壁合成来杀灭细菌。",
        ],
    ),
    (
        "板块构造理论",
        "板块构造",
        [
            "板块构造理论认为岩石圈被划分为若干相对运动的大板块。",
            "板块边界处常见地震、火山和造山运动。",
            "海底扩张是板块构造理论的重要证据来源。",
        ],
    ),
    (
        "丝绸之路简史",
        "丝绸之路",
        [
            "丝绸之路是连接东亚与地中海世界的古代贸易网络。",
            "丝绸、香料和纸张经由丝绸之路在欧亚大陆间流通。",
            "丝绸之路同时传播了宗教、技术和艺术风格。",
        ],
    ),
    (
        "蒸汽机车原理",
        "蒸汽机车",
        [
            "蒸汽机车通过燃烧煤炭加热锅炉产生高压蒸汽。",
            "高压蒸汽推动汽缸内的活塞，再经连杆驱动车轮。",
            "蒸汽机车在二十世纪中叶逐渐被内燃和电力机车取代。",
        ],
    ),
    (
        "量子纠缠概述",
        "量子纠缠",
        [
            "量子纠缠指两个粒子的量子态无法分别描述的现象。",
            "对纠缠粒子之一的测量会瞬间决定另一粒子的测量结果分布。",
            "量子纠缠是量子通信和量子计算的核心资源。",
        ],
    ),
    (
        "pgvector 使用笔记",
        "pgvector",
        [
            "pgvector is a PostgreSQL extension for vector similarity search.",
            "pgvector 提供的 HNSW 索引在查询时使用 ef_search 控制候选队列。",
            "向量索引 is the general term for approximate nearest neighbor structures.",
        ],
    ),
]


def _existing_eval_document_ids(db) -> list:
    rows = db.query(Document.id).filter(
        Document.title.in_([title for title, _, _ in EVAL_DOCUMENTS])
    )
    return [row[0] for row in rows]


def main() -> int:
    with SessionLocal() as db:
        removed = 0
        for document_id in _existing_eval_document_ids(db):
            document_service.delete_document(db, settings.default_user_id, document_id)
            removed += 1
        db.commit()

        created = 0
        for title, _, paragraphs in EVAL_DOCUMENTS:
            document_service.create_note(
                db,
                settings.default_user_id,
                NoteCreate(
                    title=title,
                    content="\n\n".join(paragraphs),
                    tags=[EVAL_SEED_TAG],
                ),
                metadata={"eval_seed": True},
            )
            created += 1

    print(f"eval seed documents: created={created} removed_previous={removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
